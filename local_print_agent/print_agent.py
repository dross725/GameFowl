# -*- coding: utf-8 -*-
import json
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
STARTUP_LOG_PATH = BASE_DIR / "print_agent_silent.log"
AGENT_VERSION = "1.11.1-barcode-match"
DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 8765,
    "printer_name": "",
    "print_mode": "windows_driver",
    "code_page": "cp437",
    "font_scale": 1.0,
    # 58mm roll printable width is typically 384 dots (48mm @ 203dpi).
    "paper_width_dots": 384,
    # 58mm paper sits on the left of the printer path - use left by default.
    "text_align": "left",
    # Barcode size (ESC/POS). Width 2-6; height in dots (e.g. 80-162).
    "barcode_module_width": 3,
    "barcode_height": 120,
}


def pywin32_status():
    """Report whether this process can import the pywin32 modules used for printing."""
    modules = {}
    for name in ("win32print", "win32ui", "win32con"):
        try:
            __import__(name)
            modules[name] = True
        except ImportError as exc:
            modules[name] = False
            modules[f"{name}_error"] = str(exc)

    ready = all(modules.get(name) for name in ("win32print", "win32ui", "win32con"))
    escpos_ready = bool(modules.get("win32print"))
    if ready:
        fix_hint = None
    elif escpos_ready and not modules.get("win32ui"):
        fix_hint = (
            f'win32ui DLL failed. Run: "{sys.executable}" -m pip install '
            f'--upgrade --force-reinstall pywin32 && "{sys.executable}" -m pywin32_postinstall -install. '
            "If it still fails, install the MSVC Redistributable, or set "
            '"print_mode": "escpos" in config.json (uses win32print only).'
        )
    else:
        fix_hint = (
            f'Install pywin32 into THIS Python, then restart the agent: '
            f'"{sys.executable}" -m pip install --upgrade --force-reinstall pywin32 '
            f'&& "{sys.executable}" -m pywin32_postinstall -install'
        )
    return {
        "ready": ready,
        "escpos_ready": escpos_ready,
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "modules": modules,
        "fix_hint": fix_hint,
    }


def load_config():
    if not CONFIG_PATH.exists():
        return DEFAULT_CONFIG.copy()

    with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
        config = json.load(config_file)

    merged_config = DEFAULT_CONFIG.copy()
    merged_config.update(config)
    return merged_config


def money(value):
    try:
        return f"{int(round(float(str(value).replace(',', '')))):,}"
    except (TypeError, ValueError):
        return str(value or "0")


def text_line(value="", code_page="cp437"):
    return f"{value}\n".encode(code_page, errors="replace")


def escpos_align_byte(text_align="left"):
    """ESC a n - 0 left, 1 center, 2 right."""
    align = str(text_align or "left").strip().lower()
    if align == "center":
        return b"\x1ba\x01"
    if align == "right":
        return b"\x1ba\x02"
    return b"\x1ba\x00"


def escpos_page_setup(paper_width_dots=384):
    """Lock printable area to 58mm so layout matches left-fed paper.

    Many XP-58 printers default to an 80mm-wide print area. Centering against
    that wider area pushes content to the right on 58mm paper.
    """
    width = max(int(paper_width_dots or 384), 192)
    n_l = width & 0xFF
    n_h = (width >> 8) & 0xFF
    output = bytearray()
    output += b"\x1b@"            # Initialize
    output += b"\x1dL\x00\x00"    # GS L: left margin = 0
    output += b"\x1dW" + bytes([n_l, n_h])  # GS W: print area width
    output += b"\x1b3\x14"        # Tight line spacing (20 dots)
    return bytes(output)


def normalize_receipt_transaction_id(raw):
    """Canonical txn id for receipt text and barcode (must match exactly)."""
    tid = str(raw or "").strip()
    if not tid:
        return tid
    upper = tid.upper()
    if upper.startswith("R") and upper[1:].isdigit():
        return "R" + upper[1:].zfill(6)
    if tid.isdigit():
        return tid.zfill(6)
    return tid


def escpos_barcode_payload(transaction_id):
    """Return the exact CODE128 payload bytes for a transaction id."""
    tid = normalize_receipt_transaction_id(transaction_id)
    return ("{B" + tid).encode("ascii", errors="ignore")


def escpos_barcode(transaction_id, module_width=3, height=120):
    """CODE128 barcode (Code Set B) - encodes the txn id exactly as printed.

    Code Set B maps each character literally, so scanned output always matches
    the transaction id line on the receipt. (Code Set C required even-length
    padding that could diverge from the printed id.)
    """
    barcode_data = escpos_barcode_payload(transaction_id)
    width = max(2, min(int(module_width or 3), 6))
    bar_h = max(40, min(int(height or 120), 162))
    output = bytearray()
    output += b"\n"          # Quiet zone above barcode
    output += b"\x1dH\x00"   # No HRI under bars (txn id printed as text already)
    output += b"\x1dh" + bytes([bar_h])
    output += b"\x1dw" + bytes([width])
    output += b"\x1dk\x49" + bytes([len(barcode_data)]) + barcode_data
    output += b"\n"          # Quiet zone below before cut
    return bytes(output)


def receipt_type(receipt):
    return str(receipt.get("receipt_type", "payout")).lower()


def is_wager_style_receipt(receipt):
    return receipt_type(receipt) in ("wager", "cancel")


def is_refund_receipt(receipt):
    return receipt_type(receipt) in ("draw_refund", "cancel_refund")


def is_bet_receipt(receipt):
    """Bet receipts keep barcode + transaction id for scan/cancel/payout."""
    return receipt_type(receipt) == "wager"


def is_test_receipt(receipt):
    return receipt_type(receipt) == "test" or receipt.get("test_print") is True


def is_teller_remit_receipt(receipt):
    """Only REMIT (not COLLECT) keeps a barcode."""
    return str(receipt.get("transaction_type", "REMIT")).upper() == "REMIT"


def should_print_barcode(receipt):
    return is_bet_receipt(receipt) or is_test_receipt(receipt)


def should_print_transaction_id(receipt):
    # Cancel, payout, and refund slips omit txn id to save paper.
    return is_bet_receipt(receipt) or is_test_receipt(receipt)


def receipt_title(receipt):
    kind = receipt_type(receipt)
    if is_test_receipt(receipt):
        return "PRINTER TEST"
    if kind == "cancel":
        return "CANCEL RECEIPT"
    if kind == "wager":
        return "BET RECEIPT"
    if kind == "draw_refund":
        return "DRAW - REFUND RECEIPT"
    if kind == "cancel_refund":
        return "CANCELLED - REFUND RECEIPT"
    return "CONGRATULATIONS!"


def escpos_receipt(
    receipt,
    code_page="cp437",
    paper_width_dots=384,
    text_align="left",
    barcode_module_width=3,
    barcode_height=120,
):
    transaction_id = normalize_receipt_transaction_id(receipt.get("transaction_id", ""))
    event_name = str(receipt.get("event_name", "")).strip()
    side = str(receipt.get("side", "")).upper()
    odds = str(receipt.get("odds", ""))
    multiplier = str(receipt.get("multiplier", ""))
    total_payout = money(receipt.get("Total_Payout") or receipt.get("total_payout"))
    amount = money(receipt.get("amount"))
    fightnum = str(receipt.get("fightnum", ""))
    cashier = str(receipt.get("cashier", ""))
    date = str(receipt.get("date", ""))
    is_test = is_test_receipt(receipt)
    is_wager = is_wager_style_receipt(receipt) and not is_test
    is_refund = is_refund_receipt(receipt)
    show_txn = should_print_transaction_id(receipt) and bool(transaction_id)
    show_barcode = should_print_barcode(receipt) and bool(transaction_id)
    align = escpos_align_byte(text_align)

    output = bytearray()
    output += escpos_page_setup(paper_width_dots)
    output += align
    if event_name:
        output += b"\x1bE\x01"
        output += text_line(event_name, code_page)
        output += b"\x1bE\x00"
    output += text_line(date, code_page)
    output += b"\x1bE\x01"
    output += text_line(receipt_title(receipt), code_page)
    if is_test:
        output += text_line(f"Teller: {cashier}", code_page)
        output += text_line("Current Total:", code_page)
        output += b"\x1d!\x11"  # Double width + double height
        output += text_line(amount, code_page)
        output += b"\x1d!\x00"  # Back to normal size
    else:
        output += text_line(f"Fight Number: {fightnum}", code_page)
    if is_wager:
        output += b"\x1d!\x11"  # Double width + double height
        output += text_line(side, code_page)
        output += text_line(f"Amount: {amount}", code_page)
        output += b"\x1d!\x00"  # Back to normal size
    elif not is_test:
        output += b"\x1d!\x11"  # Double width + double height
        output += text_line(f"{side} - {odds}", code_page)
        output += b"\x1d!\x00"  # Back to normal size
        output += text_line(f"Amount: {amount}", code_page)
        output += text_line(f"Odds: {multiplier}", code_page)
        output += text_line("Refund Amount:" if is_refund else "Payout Amount:", code_page)
        output += b"\x1d!\x11"  # Double width + double height
        output += text_line(total_payout, code_page)
        output += b"\x1d!\x00"  # Back to normal size
    output += b"\x1bE\x00"
    if not is_test:
        output += text_line(f"Cashier: {cashier}", code_page)
    if show_txn:
        output += text_line(f"{transaction_id}", code_page)

    if show_barcode:
        output += align
        output += escpos_barcode(
            transaction_id,
            module_width=barcode_module_width,
            height=barcode_height,
        )

    output += b"\x1dV\x42\x00"  # Partial cut
    return bytes(output)


def _pywin32_missing_error(detail=None):
    hint = (
        "pywin32 is missing or broken for the Python running this print agent "
        f"({sys.executable}). "
        f'Fix: \"{sys.executable}\" -m pip install --upgrade --force-reinstall pywin32 '
        f'&& \"{sys.executable}\" -m pywin32_postinstall -install '
        "then restart the agent. Also install the Microsoft Visual C++ Redistributable "
        "if win32ui still fails with a DLL load error. "
        "Thermal ESC/POS printers can avoid win32ui by setting "
        '"print_mode": "escpos" in config.json.'
    )
    if detail:
        return RuntimeError(f"{detail} {hint}")
    return RuntimeError(hint)


def get_win32print():
    try:
        import win32print
    except ImportError as exc:
        raise _pywin32_missing_error(str(exc)) from exc

    return win32print


def get_win32ui():
    try:
        import win32ui
    except ImportError as exc:
        raise _pywin32_missing_error(
            f"win32ui failed to load ({exc})."
        ) from exc

    return win32ui


def get_win32con():
    try:
        import win32con
    except ImportError as exc:
        raise _pywin32_missing_error(str(exc)) from exc

    return win32con


def configured_printer(config):
    win32print = get_win32print()
    printer_name = str(config.get("printer_name") or "").strip()
    if printer_name:
        return printer_name

    printer_name = win32print.GetDefaultPrinter()
    if not printer_name:
        raise RuntimeError("No printer_name configured and Windows has no default printer.")
    return printer_name


def list_printers():
    win32print = get_win32print()
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    return [printer[2] for printer in win32print.EnumPrinters(flags)]


def print_raw(printer_name, payload):
    win32print = get_win32print()
    handle = win32print.OpenPrinter(printer_name)
    try:
        job_id = win32print.StartDocPrinter(handle, 1, ("SmartWagers Payout Receipt", None, "RAW"))
        try:
            win32print.StartPagePrinter(handle)
            win32print.WritePrinter(handle, payload)
            win32print.EndPagePrinter(handle)
        finally:
            win32print.EndDocPrinter(handle)
    finally:
        win32print.ClosePrinter(handle)

    return job_id


CODE39_PATTERNS = {
    "0": "nnnwwnwnn",
    "1": "wnnwnnnnw",
    "2": "nnwwnnnnw",
    "3": "wnwwnnnnn",
    "4": "nnnwwnnnw",
    "5": "wnnwwnnnn",
    "6": "nnwwwnnnn",
    "7": "nnnwnnwnw",
    "8": "wnnwnnwnn",
    "9": "nnwwnnwnn",
    "A": "wnnnnwnnw",
    "B": "nnwnnwnnw",
    "C": "wnwnnwnnn",
    "D": "nnnnwwnnw",
    "E": "wnnnwwnnn",
    "F": "nnwnwwnnn",
    "G": "nnnnnwwnw",
    "H": "wnnnnwwnn",
    "I": "nnwnnwwnn",
    "J": "nnnnwwwnn",
    "K": "wnnnnnnww",
    "L": "nnwnnnnww",
    "M": "wnwnnnnwn",
    "N": "nnnnwnnww",
    "O": "wnnnwnnwn",
    "P": "nnwnwnnwn",
    "Q": "nnnnnnwww",
    "R": "wnnnnnwwn",
    "S": "nnwnnnwwn",
    "T": "nnnnwnwwn",
    "U": "wwnnnnnnw",
    "V": "nwwnnnnnw",
    "W": "wwwnnnnnn",
    "X": "nwnnwnnnw",
    "Y": "wwnnwnnnn",
    "Z": "nwwnwnnnn",
    "-": "nwnnnnwnw",
    ".": "wwnnnnwnn",
    " ": "nwwnnnwnn",
    "$": "nwnwnwnnn",
    "/": "nwnwnnnwn",
    "+": "nwnnnwnwn",
    "%": "nnnwnwnwn",
    "*": "nwnnwnwnn",
}


def code39_value(value):
    allowed = set(CODE39_PATTERNS.keys()) - {"*"}
    cleaned = "".join(character for character in str(value).upper() if character in allowed)
    if not cleaned:
        raise RuntimeError("Barcode value contains no Code 39 compatible characters.")
    return f"*{cleaned}*"


def draw_code39(dc, value, x, y, narrow, height):
    barcode_value = code39_value(value)
    wide = narrow * 3
    cursor_x = x

    for character in barcode_value:
        pattern = CODE39_PATTERNS[character]
        for index, width_code in enumerate(pattern):
            width = wide if width_code == "w" else narrow
            if index % 2 == 0:
                dc.FillSolidRect((cursor_x, y, cursor_x + width, y + height), 0)
            cursor_x += width
        cursor_x += narrow

    return cursor_x - x


def code39_width(value, narrow):
    barcode_value = code39_value(value)
    wide = narrow * 3
    width = 0

    for character in barcode_value:
        pattern = CODE39_PATTERNS[character]
        for width_code in pattern:
            width += wide if width_code == "w" else narrow
        width += narrow

    return width


def start_print_doc(dc, title):
    """Start a GDI print job; raise a clear error if the printer rejects StartDoc."""
    hint = (
        'XP-58C and most thermal receipt printers need '
        '"print_mode": "escpos" in config.json, then restart the print agent.'
    )
    try:
        dc.StartDoc(title)
    except Exception as exc:
        raise RuntimeError(f"StartDoc failed for Windows GDI printing ({exc}). {hint}") from exc
    except BaseException as exc:
        # Older pywin32 raises win32ui.error outside Exception.
        raise RuntimeError(f"StartDoc failed for Windows GDI printing ({exc}). {hint}") from exc


def print_windows_driver(printer_name, receipt, font_scale=1.0, text_align="left"):
    win32ui = get_win32ui()
    win32con = get_win32con()
    transaction_id = normalize_receipt_transaction_id(receipt.get("transaction_id", ""))
    event_name = str(receipt.get("event_name", "")).strip()
    side = str(receipt.get("side", "")).upper()
    odds = str(receipt.get("odds", ""))
    multiplier = str(receipt.get("multiplier", ""))
    total_payout = money(receipt.get("Total_Payout") or receipt.get("total_payout"))
    amount = money(receipt.get("amount"))
    fightnum = str(receipt.get("fightnum", ""))
    cashier = str(receipt.get("cashier", ""))
    date = str(receipt.get("date", ""))
    is_test = is_test_receipt(receipt)
    is_wager = is_wager_style_receipt(receipt) and not is_test
    is_refund = is_refund_receipt(receipt)
    show_txn = should_print_transaction_id(receipt) and bool(transaction_id)
    show_barcode = should_print_barcode(receipt) and bool(transaction_id)
    align_left = str(text_align or "left").strip().lower() != "center"

    dc = win32ui.CreateDC()
    dc.CreatePrinterDC(printer_name)
    dpi_x = dc.GetDeviceCaps(win32con.LOGPIXELSX)
    dpi_y = dc.GetDeviceCaps(win32con.LOGPIXELSY)
    page_width = dc.GetDeviceCaps(win32con.HORZRES)
    margin_x = max(int(dpi_x * 0.10), 20)
    y = max(int(dpi_y * 0.04), 8)
    line_gap = int(dpi_y * 0.04 * font_scale)
    tight_gap = max(int(dpi_y * 0.015 * font_scale), 2)

    normal_font = win32ui.CreateFont({
        "name": "Arial",
        "height": int(dpi_y * 0.11 * font_scale),
        "weight": 400,
    })
    bold_font = win32ui.CreateFont({
        "name": "Arial",
        "height": int(dpi_y * 0.13 * font_scale),
        "weight": 700,
    })
    highlight_font = win32ui.CreateFont({
        "name": "Arial",
        "height": int(dpi_y * 0.20 * font_scale),
        "weight": 700,
    })
    barcode_font = win32ui.CreateFont({
        "name": "Consolas",
        "height": int(dpi_y * 0.10 * font_scale),
        "weight": 700,
    })
    barcode_height = int(dpi_y * 0.55)
    barcode_narrow = max(int(dpi_x * 0.016), 3)

    def draw_line(text, font, gap=None):
        nonlocal y
        if gap is None:
            gap = line_gap
        dc.SelectObject(font)
        text_width, text_height = dc.GetTextExtent(text)
        if align_left:
            x = margin_x
        else:
            x = max(int((page_width - text_width) / 2), margin_x)
        dc.TextOut(x, y, text)
        y += text_height + gap

    start_print_doc(dc, "SmartWagers Receipt")
    try:
        dc.StartPage()
        if event_name:
            draw_line(event_name, bold_font, tight_gap)
        draw_line(date, normal_font, tight_gap)
        draw_line(receipt_title(receipt), bold_font, tight_gap)
        if is_test:
            draw_line(f"Teller: {cashier}", bold_font)
            draw_line(f"Current Total: {amount}", highlight_font)
        else:
            draw_line(f"Fight Number: {fightnum}", bold_font)
        if is_wager:
            draw_line(side, highlight_font)
            draw_line(f"Amount: {amount}", highlight_font)
        elif not is_test:
            draw_line(f"{side} - {odds}", highlight_font)
            draw_line(f"Amount: {amount}", bold_font)
            draw_line(f"Odds: {multiplier}", bold_font)
            draw_line("Refund Amount:" if is_refund else "Payout Amount:", bold_font)
            draw_line(total_payout, highlight_font)
        if not is_test:
            draw_line(f"Cashier: {cashier}", normal_font, tight_gap)
        if show_txn:
            draw_line(f"{transaction_id}", normal_font, tight_gap)
        if show_barcode:
            barcode_width = code39_width(transaction_id, barcode_narrow)
            if align_left:
                barcode_x = margin_x
            else:
                barcode_x = max(int((page_width - barcode_width) / 2), margin_x)
            draw_code39(dc, transaction_id, barcode_x, y, barcode_narrow, barcode_height)
            y += barcode_height + tight_gap
            draw_line(transaction_id, barcode_font, tight_gap)
        dc.EndPage()
    finally:
        dc.EndDoc()
        dc.DeleteDC()

    return None


def print_receipt(config, printer_name, receipt):
    print_mode = str(config.get("print_mode", "windows_driver")).lower()
    font_scale = float(config.get("font_scale", 1.0))
    text_align = str(config.get("text_align", "left"))
    if print_mode == "escpos":
        payload = escpos_receipt(
            receipt,
            config.get("code_page", "cp437"),
            paper_width_dots=int(config.get("paper_width_dots", 384)),
            text_align=text_align,
            barcode_module_width=int(config.get("barcode_module_width", 3)),
            barcode_height=int(config.get("barcode_height", 120)),
        )
        return print_raw(printer_name, payload)
    if print_mode == "windows_driver":
        return print_windows_driver(
            printer_name, receipt, font_scale=font_scale, text_align=text_align,
        )

    raise RuntimeError("Invalid print_mode. Use 'windows_driver' or 'escpos'.")


# -- Remit / Collect receipts --

def escpos_remit_receipt(
    receipt,
    code_page="cp437",
    paper_width_dots=384,
    text_align="left",
    barcode_module_width=3,
    barcode_height=120,
):
    transaction_type = str(receipt.get("transaction_type", "REMIT")).upper()
    transaction_id = normalize_receipt_transaction_id(receipt.get("transaction_id", ""))
    amount = money(receipt.get("amount"))
    balance = money(receipt.get("balance"))
    grand_total = money(receipt.get("grand_total"))
    cashier = str(receipt.get("cashier", ""))
    date = str(receipt.get("date", ""))
    event_name = str(receipt.get("event_name", ""))
    is_admin_bank = receipt.get("receipt_scope") == "admin_bank"
    show_barcode = (
        not is_admin_bank
        and is_teller_remit_receipt(receipt)
        and bool(transaction_id)
    )
    align = escpos_align_byte(text_align)

    label = "ADVANCE RECEIPT" if transaction_type == "REMIT" else "BORROW RECEIPT"
    output = bytearray()
    for copy_label in transaction_receipt_copies(receipt):
        output += escpos_page_setup(paper_width_dots)
        output += align
        output += text_line(date, code_page)
        output += b"\x1bE\x01"
        output += text_line(label, code_page)
        output += text_line(copy_label, code_page)
        output += b"\x1bE\x00"
        output += b"\x1ba\x00"   # Detail lines always left for columns
        if event_name:
            output += text_line(f"Event    : {event_name}", code_page)
        actor_label = "Admin" if is_admin_bank else "Teller"
        output += text_line(f"{actor_label:<9}: {cashier}", code_page)
        output += text_line(f"Amount   : {amount}", code_page)
        output += text_line(f"Balance  : {balance}", code_page)
        if transaction_id:
            output += text_line(f"Txn ID   : {transaction_id}", code_page)

        if show_barcode:
            output += align
            output += escpos_barcode(
                transaction_id,
                module_width=barcode_module_width,
                height=barcode_height,
            )

        output += b"\x1dV\x42\x00"  # Partial cut between copies
    return bytes(output)


def print_windows_driver_remit(printer_name, receipt, font_scale=1.0, text_align="left"):
    win32ui = get_win32ui()
    win32con = get_win32con()

    transaction_type = str(receipt.get("transaction_type", "REMIT")).upper()
    transaction_id = normalize_receipt_transaction_id(receipt.get("transaction_id", ""))
    amount = money(receipt.get("amount"))
    balance = money(receipt.get("balance"))
    grand_total = money(receipt.get("grand_total"))
    cashier = str(receipt.get("cashier", ""))
    date = str(receipt.get("date", ""))
    event_name = str(receipt.get("event_name", ""))
    is_admin_bank = receipt.get("receipt_scope") == "admin_bank"

    label = "ADVANCE RECEIPT" if transaction_type == "REMIT" else "BORROW RECEIPT"
    show_barcode = (
        not is_admin_bank
        and is_teller_remit_receipt(receipt)
        and bool(transaction_id)
    )
    align_left = str(text_align or "left").strip().lower() != "center"

    dc = win32ui.CreateDC()
    dc.CreatePrinterDC(printer_name)
    dpi_x = dc.GetDeviceCaps(win32con.LOGPIXELSX)
    dpi_y = dc.GetDeviceCaps(win32con.LOGPIXELSY)
    page_width = dc.GetDeviceCaps(win32con.HORZRES)
    margin_x = max(int(dpi_x * 0.10), 20)
    top_margin = max(int(dpi_y * 0.04), 8)
    y = top_margin
    line_gap = int(dpi_y * 0.04 * font_scale)
    tight_gap = max(int(dpi_y * 0.015 * font_scale), 2)

    normal_font = win32ui.CreateFont({
        "name": "Arial", "height": int(dpi_y * 0.11 * font_scale), "weight": 400,
    })
    bold_font = win32ui.CreateFont({
        "name": "Arial", "height": int(dpi_y * 0.13 * font_scale), "weight": 700,
    })
    barcode_font = win32ui.CreateFont({
        "name": "Consolas", "height": int(dpi_y * 0.10 * font_scale), "weight": 700,
    })
    barcode_height = int(dpi_y * 0.55)
    barcode_narrow = max(int(dpi_x * 0.016), 3)

    def draw_header(text, font, gap=None):
        nonlocal y
        if gap is None:
            gap = line_gap
        dc.SelectObject(font)
        text_width, text_height = dc.GetTextExtent(text)
        if align_left:
            x = margin_x
        else:
            x = max(int((page_width - text_width) / 2), margin_x)
        dc.TextOut(x, y, text)
        y += text_height + gap

    def draw_left(text, font=normal_font, gap=None):
        nonlocal y
        if gap is None:
            gap = line_gap
        dc.SelectObject(font)
        _, text_height = dc.GetTextExtent(text)
        dc.TextOut(margin_x, y, text)
        y += text_height + gap

    start_print_doc(dc, f"SmartWagers {label.title()}")
    try:
        for copy_label in transaction_receipt_copies(receipt):
            y = top_margin
            dc.StartPage()
            draw_header(date, normal_font, tight_gap)
            draw_header(label, bold_font, tight_gap)
            draw_header(copy_label, bold_font)
            if event_name:
                draw_left(f"Event     : {event_name}")
            actor_label = "Admin" if is_admin_bank else "Teller"
            draw_left(f"{actor_label:<10}: {cashier}")
            draw_left(f"Amount    : {amount}")
            draw_left(f"Balance   : {balance}")
            draw_left(f"Grand Tot : {grand_total}")
            if transaction_id:
                draw_left(f"Txn ID    : {transaction_id}", gap=tight_gap)
            if show_barcode:
                barcode_width = code39_width(transaction_id, barcode_narrow)
                barcode_x = margin_x if align_left else max(int((page_width - barcode_width) / 2), margin_x)
                draw_code39(dc, transaction_id, barcode_x, y, barcode_narrow, barcode_height)
                y += barcode_height + tight_gap
                draw_header(transaction_id, barcode_font, tight_gap)
            dc.EndPage()
    finally:
        dc.EndDoc()
        dc.DeleteDC()

    return None


def print_remit_receipt(config, printer_name, receipt):
    print_mode = str(config.get("print_mode", "windows_driver")).lower()
    font_scale = float(config.get("font_scale", 1.0))
    text_align = str(config.get("text_align", "left"))
    if print_mode == "escpos":
        payload = escpos_remit_receipt(
            receipt,
            config.get("code_page", "cp437"),
            paper_width_dots=int(config.get("paper_width_dots", 384)),
            text_align=text_align,
            barcode_module_width=int(config.get("barcode_module_width", 3)),
            barcode_height=int(config.get("barcode_height", 120)),
        )
        return print_raw(printer_name, payload)
    if print_mode == "windows_driver":
        return print_windows_driver_remit(
            printer_name, receipt, font_scale=font_scale, text_align=text_align,
        )

    raise RuntimeError("Invalid print_mode. Use 'windows_driver' or 'escpos'.")


class PrintAgentHandler(BaseHTTPRequestHandler):
    server_version = "SmartWagersPrintAgent/1.0"

    def log_message(self, format, *args):
        print("%s - %s" % (self.address_string(), format % args))

    def is_loopback_request(self):
        return self.client_address[0] in ("127.0.0.1", "::1")

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self):
        if not self.is_loopback_request():
            self.send_json(403, {"ok": False, "error": "Only localhost requests are allowed."})
            return

        if self.path == "/health":
            config = load_config()
            print_mode = str(config.get("print_mode", "windows_driver")).lower()
            status = pywin32_status()
            if print_mode == "escpos":
                print_ready = bool(status.get("escpos_ready"))
            else:
                print_ready = bool(status.get("ready"))
            self.send_json(200, {
                "ok": True,
                "message": "SmartWagers print agent is running.",
                "version": AGENT_VERSION,
                "config_path": str(CONFIG_PATH),
                "print_mode": print_mode,
                "text_align": str(config.get("text_align", "left")),
                "paper_width_dots": int(config.get("paper_width_dots", 384)),
                "printer_name": config.get("printer_name") or "(Windows default)",
                "pywin32": status,
                "print_ready": print_ready,
            })
            return

        if self.path == "/printers":
            try:
                self.send_json(200, {"ok": True, "printers": list_printers()})
            except RuntimeError as exc:
                self.send_json(500, {"ok": False, "error": str(exc)})
            return

        if self.path in ("/print-payout", "/print-wager", "/print-remit"):
            self.send_json(405, {
                "ok": False,
                "error": f"{self.path} only accepts POST from the SmartWagers page, not a browser address bar.",
            })
            return

        self.send_json(404, {"ok": False, "error": "Unknown endpoint."})

    def do_POST(self):
        if not self.is_loopback_request():
            self.send_json(403, {"ok": False, "error": "Only localhost requests are allowed."})
            return

        if self.path not in ("/print-payout", "/print-wager", "/print-remit"):
            self.send_json(404, {"ok": False, "error": "Unknown endpoint."})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length)
            receipt = json.loads(raw_body.decode("utf-8"))
            config = load_config()
            printer_name = configured_printer(config)
            if self.path == "/print-remit":
                job_id = print_remit_receipt(config, printer_name, receipt)
            else:
                job_id = print_receipt(config, printer_name, receipt)
        except json.JSONDecodeError:
            self.send_json(400, {"ok": False, "error": "Invalid JSON payload."})
            return
        except RuntimeError as exc:
            self.send_json(500, {"ok": False, "error": str(exc)})
            return
        except Exception as exc:
            message = str(exc)
            if "StartDoc" in message:
                message = (
                    f"{message}. For XP-58C / thermal printers set "
                    '"print_mode": "escpos" in config.json and restart the agent.'
                )
            self.send_json(500, {"ok": False, "error": f"Print failed: {message}"})
            return
        except BaseException as exc:
            # Older pywin32 raises win32ui.error outside Exception.
            message = str(exc)
            if "StartDoc" in message:
                message = (
                    f"{message}. For XP-58C / thermal printers set "
                    '"print_mode": "escpos" in config.json and restart the agent.'
                )
            self.send_json(500, {"ok": False, "error": f"Print failed: {message}"})
            return

        self.send_json(200, {
            "ok": True,
            "message": f"Receipt sent to {printer_name}.",
            "job_id": job_id,
            "printer_name": printer_name,
        })


def startup_log(message):
    """Append a line to print_agent_silent.log (visible when pythonw has no console)."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with STARTUP_LOG_PATH.open("a", encoding="utf-8") as log_file:
            log_file.write(f"{timestamp} {message}\n")
    except OSError:
        pass


def main():
    config = load_config()
    host = str(config.get("host") or "127.0.0.1")
    port = int(config.get("port") or 8765)
    server_address = (host, port)
    startup_log(
        f"Starting SmartWagers print agent {AGENT_VERSION} on http://{host}:{port} "
        f"(python {sys.version.split()[0]} @ {sys.executable})"
    )
    try:
        httpd = HTTPServer(server_address, PrintAgentHandler)
    except OSError as exc:
        win_error = getattr(exc, "winerror", None)
        if exc.errno in (98, 10048) or win_error == 10048:
            startup_log(
                f"ERROR: port {port} already in use. "
                "Stop the other print agent in Task Manager or change port in config.json."
            )
        else:
            startup_log(f"ERROR: could not bind {host}:{port}: {exc}")
        raise
    print(f"SmartWagers print agent {AGENT_VERSION} running at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    httpd.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        startup_log("Print agent stopped (KeyboardInterrupt).")
    except Exception as exc:
        startup_log(f"FATAL: {type(exc).__name__}: {exc}")
        raise
