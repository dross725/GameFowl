"""ESC/POS receipt builders shared by the mobile print queue.

Layout matches local_print_agent/print_agent.py escpos mode (58mm / 384 dots).
"""
from __future__ import annotations

import math
from typing import Any, Mapping


DEFAULT_CODE_PAGE = "cp437"
DEFAULT_PAPER_WIDTH_DOTS = 384
DEFAULT_TEXT_ALIGN = "center"
DEFAULT_BARCODE_MODULE_WIDTH = 3
DEFAULT_BARCODE_HEIGHT = 120

TELLER_TRANSACTION_RECEIPT_COPIES = ("TELLERS COPY", "ADMIN COPY")
ADMIN_BANK_RECEIPT_COPIES = ("ADMIN COPY", "BANK COPY")

# Blank lines before tear-off / between dual copies (also helps printers without a cutter).
DEFAULT_CUT_FEED_LINES = 4


def escpos_feed_and_cut(feed_lines: int = DEFAULT_CUT_FEED_LINES) -> bytes:
    """Feed blank lines, then partial-cut with the same feed amount.

    GS V 66 n = feed n vertical units then partial cut. Explicit newlines make the
    gap visible even when the printer ignores or lacks an auto-cutter.
    """
    n = max(0, min(int(feed_lines), 255))
    return (b"\n" * n) + bytes([0x1D, 0x56, 0x42, n])


def money(value: Any) -> str:
    """Format a monetary amount with centavos, truncating beyond 2 decimals (no rounding)."""
    try:
        num = float(str(value).replace(",", ""))
        truncated = math.trunc(num * 100) / 100
        return f"{truncated:,.2f}"
    except (TypeError, ValueError):
        return str(value or "0.00")


FONT_A_WIDTH_DOTS = 12


def normalize_paper_width_dots(paper_width_dots: Any) -> int:
    """Return the printable width used consistently by all layout helpers."""
    return max(int(paper_width_dots or DEFAULT_PAPER_WIDTH_DOTS), 192)


def text_line(value: Any = "", code_page: str = DEFAULT_CODE_PAGE) -> bytes:
    return f"{value}\n".encode(code_page, errors="replace")


def escpos_align_byte(text_align: str = DEFAULT_TEXT_ALIGN) -> bytes:
    """ESC a n - 0 left, 1 center, 2 right."""
    align = str(text_align or "left").strip().lower()
    if align == "center":
        return b"\x1ba\x01"
    if align == "right":
        return b"\x1ba\x02"
    return b"\x1ba\x00"


def fit_centered_text(text: Any, paper_width_dots: int, double: bool = False) -> str:
    """Pad a line so it sits in the middle of a 58mm head.

    LogicOwl ESC a center uses an 80mm page. On 58mm paper that parks the
    bold event title on the left and clips the last digits of a double-width
    amount. Font A is 12 dots, so 384 dots is 32 columns (16 when doubled).
    """
    raw = str(text)
    cell = FONT_A_WIDTH_DOTS * (2 if double else 1)
    columns = max(normalize_paper_width_dots(paper_width_dots) // cell, 1)
    if len(raw) >= columns:
        return raw
    return (" " * ((columns - len(raw)) // 2)) + raw


def place_line(
    text: Any,
    code_page: str,
    paper_width_dots: int,
    text_align: str = "center",
    bold: bool | None = None,
    double: bool = False,
    force_center: bool = False,
) -> bytes:
    """Print one line from the left edge, centered with spaces when asked."""
    mode = "center" if force_center else str(text_align or "center").strip().lower()
    if mode == "center":
        rendered = fit_centered_text(text, paper_width_dots, double)
        align = b"\x1ba\x00"
    elif mode == "right":
        rendered = str(text)
        align = b"\x1ba\x02"
    else:
        rendered = str(text)
        align = b"\x1ba\x00"
    output = bytearray()
    output += b"\x1dL\x00\x00"
    output += align
    if bold is True:
        output += b"\x1bE\x01"
    elif bold is False:
        output += b"\x1bE\x00"
    if double:
        output += b"\x1d!\x11"
    output += align
    output += text_line(rendered, code_page)
    if double:
        output += b"\x1d!\x00"
    return bytes(output)


def escpos_page_setup(paper_width_dots: int = DEFAULT_PAPER_WIDTH_DOTS) -> bytes:
    """Lock the printable area to the 58mm roll and clear the left margin."""
    width = normalize_paper_width_dots(paper_width_dots)
    n_l = width & 0xFF
    n_h = (width >> 8) & 0xFF
    output = bytearray()
    output += b"\x1b@"  # Initialize
    output += b"\x1dL\x00\x00"  # GS L: left margin = 0
    output += b"\x1dW" + bytes([n_l, n_h])  # GS W: print area width
    output += b"\x1b3\x14"  # Tight line spacing (20 dots)
    return bytes(output)


def code128_width_dots(transaction_id: Any, module_width: int = DEFAULT_BARCODE_MODULE_WIDTH) -> int:
    """Dot width of the CODE128 symbol printed for this transaction id."""
    tid = normalize_receipt_transaction_id(transaction_id)
    modules = 11 * (len(tid) + 2) + 13
    width = max(2, min(int(module_width or DEFAULT_BARCODE_MODULE_WIDTH), 6))
    return modules * width


def position_barcode(
    transaction_id: Any,
    paper_width_dots: int,
    text_align: str,
    module_width: int,
) -> bytes:
    """Place the barcode on the 58mm head. ESC a center would use 80mm."""
    output = bytearray()
    if str(text_align or "center").strip().lower() == "center":
        bar_width = code128_width_dots(transaction_id, module_width)
        offset = max((normalize_paper_width_dots(paper_width_dots) - bar_width) // 2, 0)
        output += bytes([0x1D, 0x4C, offset & 0xFF, (offset >> 8) & 0xFF])
        output += b"\x1ba\x00"
    else:
        output += b"\x1dL\x00\x00"
        output += escpos_align_byte(text_align)
    return bytes(output)


def normalize_receipt_transaction_id(raw: Any) -> str:
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


def escpos_barcode_payload(transaction_id: Any) -> bytes:
    """Return the exact CODE128 payload bytes for a transaction id."""
    tid = normalize_receipt_transaction_id(transaction_id)
    return ("{B" + tid).encode("ascii", errors="ignore")


def escpos_barcode(
    transaction_id: Any,
    module_width: int = DEFAULT_BARCODE_MODULE_WIDTH,
    height: int = DEFAULT_BARCODE_HEIGHT,
) -> bytes:
    """CODE128 barcode (Code Set B) - encodes the txn id exactly as printed."""
    barcode_data = escpos_barcode_payload(transaction_id)
    width = max(2, min(int(module_width or DEFAULT_BARCODE_MODULE_WIDTH), 6))
    bar_h = max(40, min(int(height or DEFAULT_BARCODE_HEIGHT), 162))
    output = bytearray()
    output += b"\n"  # Quiet zone above barcode
    output += b"\x1dH\x00"  # No HRI under bars
    output += b"\x1dh" + bytes([bar_h])
    output += b"\x1dw" + bytes([width])
    output += b"\x1dk\x49" + bytes([len(barcode_data)]) + barcode_data
    output += b"\n"  # Quiet zone below before cut
    return bytes(output)


def receipt_type(receipt: Mapping[str, Any]) -> str:
    return str(receipt.get("receipt_type", "payout")).lower()


def is_wager_style_receipt(receipt: Mapping[str, Any]) -> bool:
    return receipt_type(receipt) in ("wager", "cancel")


def is_refund_receipt(receipt: Mapping[str, Any]) -> bool:
    return receipt_type(receipt) in ("draw_refund", "cancel_refund")


def is_bet_receipt(receipt: Mapping[str, Any]) -> bool:
    return receipt_type(receipt) == "wager"


def is_test_receipt(receipt: Mapping[str, Any]) -> bool:
    return receipt_type(receipt) == "test" or receipt.get("test_print") is True


def is_teller_remit_receipt(receipt: Mapping[str, Any]) -> bool:
    return str(receipt.get("transaction_type", "REMIT")).upper() == "REMIT"


def should_print_barcode(receipt: Mapping[str, Any]) -> bool:
    return is_bet_receipt(receipt) or is_test_receipt(receipt)


def should_print_transaction_id(receipt: Mapping[str, Any]) -> bool:
    return is_bet_receipt(receipt) or is_test_receipt(receipt)


def receipt_title(receipt: Mapping[str, Any]) -> str:
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


def transaction_receipt_copies(receipt: Mapping[str, Any]) -> tuple[str, str]:
    if receipt.get("receipt_scope") == "admin_bank":
        return ADMIN_BANK_RECEIPT_COPIES
    return TELLER_TRANSACTION_RECEIPT_COPIES


def receipt_fight_number(receipt: Mapping[str, Any]) -> str:
    """Current fight stamped on advance and borrow receipts. Empty when absent."""
    raw = receipt.get("fightnum")
    if raw is None:
        return ""
    return str(raw).strip()


def escpos_receipt(
    receipt: Mapping[str, Any],
    code_page: str = DEFAULT_CODE_PAGE,
    paper_width_dots: int = DEFAULT_PAPER_WIDTH_DOTS,
    text_align: str = DEFAULT_TEXT_ALIGN,
    barcode_module_width: int = DEFAULT_BARCODE_MODULE_WIDTH,
    barcode_height: int = DEFAULT_BARCODE_HEIGHT,
) -> bytes:
    paper_width_dots = normalize_paper_width_dots(paper_width_dots)
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

    def emit(text: Any, bold: bool | None = None, double: bool = False, force_center: bool = False) -> bytes:
        return place_line(
            text,
            code_page,
            paper_width_dots,
            text_align,
            bold=bold,
            double=double,
            force_center=force_center,
        )

    output = bytearray()
    output += escpos_page_setup(paper_width_dots)
    if event_name:
        output += emit(event_name, bold=True, force_center=True)
    output += emit(date, bold=False)
    output += emit(receipt_title(receipt), bold=True)
    if is_test:
        output += emit(f"Teller: {cashier}", bold=True)
        output += emit("Current Total:", bold=True)
        output += emit(amount, bold=True, double=True)
    else:
        output += emit(f"Fight Number: {fightnum}", bold=True)
    if is_wager:
        output += emit(side, bold=True, double=True)
        output += emit(f"Amount: {amount}", bold=True, double=True)
    elif not is_test:
        output += emit(f"{side} - {odds}", bold=True, double=True)
        output += emit(f"Amount: {amount}", bold=True)
        if not is_refund:
            output += emit(f"Amount Won: {total_payout}", bold=True)
        output += emit(f"Odds: {multiplier}", bold=True)
        output += emit("Refund Amount:" if is_refund else "Payout Amount:", bold=True)
        output += emit(total_payout, bold=True, double=True)
    if not is_test:
        output += emit(f"Cashier: {cashier}", bold=False)
    if show_txn:
        output += emit(transaction_id, bold=False)

    if show_barcode:
        output += position_barcode(
            transaction_id, paper_width_dots, text_align, barcode_module_width,
        )
        output += escpos_barcode(
            transaction_id,
            module_width=barcode_module_width,
            height=barcode_height,
        )

    output += escpos_feed_and_cut()
    return bytes(output)


def escpos_remit_receipt(
    receipt: Mapping[str, Any],
    code_page: str = DEFAULT_CODE_PAGE,
    paper_width_dots: int = DEFAULT_PAPER_WIDTH_DOTS,
    text_align: str = DEFAULT_TEXT_ALIGN,
    barcode_module_width: int = DEFAULT_BARCODE_MODULE_WIDTH,
    barcode_height: int = DEFAULT_BARCODE_HEIGHT,
) -> bytes:
    paper_width_dots = normalize_paper_width_dots(paper_width_dots)
    transaction_type = str(receipt.get("transaction_type", "REMIT")).upper()
    transaction_id = normalize_receipt_transaction_id(receipt.get("transaction_id", ""))
    amount = money(receipt.get("amount"))
    balance = money(receipt.get("balance"))
    cashier = str(receipt.get("cashier", ""))
    date = str(receipt.get("date", ""))
    event_name = str(receipt.get("event_name", ""))
    fightnum = receipt_fight_number(receipt)
    is_admin_bank = receipt.get("receipt_scope") == "admin_bank"
    show_barcode = (
        not is_admin_bank
        and is_teller_remit_receipt(receipt)
        and bool(transaction_id)
    )

    label = "ADVANCE RECEIPT" if transaction_type == "REMIT" else "BORROW RECEIPT"
    output = bytearray()
    for copy_label in transaction_receipt_copies(receipt):
        output += escpos_page_setup(paper_width_dots)
        output += place_line(date, code_page, paper_width_dots, text_align, bold=False)
        output += place_line(label, code_page, paper_width_dots, text_align, bold=True)
        output += place_line(copy_label, code_page, paper_width_dots, text_align, bold=True)
        if fightnum != "":
            output += place_line(
                f"Fight Number: {fightnum}", code_page, paper_width_dots, text_align, bold=True,
            )
        if event_name:
            output += place_line(
                f"Event    : {event_name}",
                code_page,
                paper_width_dots,
                text_align,
                bold=False,
                force_center=True,
            )
        actor_label = "Admin" if is_admin_bank else "Teller"
        output += place_line(
            f"{actor_label:<9}: {cashier}", code_page, paper_width_dots, "left", bold=False,
        )
        output += place_line(f"Amount   : {amount}", code_page, paper_width_dots, "left", bold=False)
        output += place_line(f"Balance  : {balance}", code_page, paper_width_dots, "left", bold=False)
        if transaction_id:
            output += place_line(
                f"Txn ID   : {transaction_id}", code_page, paper_width_dots, "left", bold=False,
            )

        if show_barcode:
            output += position_barcode(
                transaction_id, paper_width_dots, text_align, barcode_module_width,
            )
            output += escpos_barcode(
                transaction_id,
                module_width=barcode_module_width,
                height=barcode_height,
            )

        output += escpos_feed_and_cut()
    return bytes(output)


def render_escpos_bytes(
    endpoint: str,
    receipt: Mapping[str, Any],
    *,
    code_page: str = DEFAULT_CODE_PAGE,
    paper_width_dots: int = DEFAULT_PAPER_WIDTH_DOTS,
    text_align: str = DEFAULT_TEXT_ALIGN,
    barcode_module_width: int = DEFAULT_BARCODE_MODULE_WIDTH,
    barcode_height: int = DEFAULT_BARCODE_HEIGHT,
) -> bytes:
    """Render raw ESC/POS for wager/payout/remit endpoints."""
    kind = str(endpoint or "").strip().lower()
    kwargs = {
        "code_page": code_page,
        "paper_width_dots": paper_width_dots,
        "text_align": text_align,
        "barcode_module_width": barcode_module_width,
        "barcode_height": barcode_height,
    }
    if kind in ("remit", "print-remit"):
        return escpos_remit_receipt(receipt, **kwargs)
    return escpos_receipt(receipt, **kwargs)


def infer_endpoint(receipt: Mapping[str, Any], explicit: str | None = None) -> str:
    if explicit:
        value = str(explicit).strip().lower().replace("print-", "")
        if value in ("wager", "payout", "remit"):
            return value
    if "transaction_type" in receipt and receipt.get("receipt_type") is None:
        return "remit"
    kind = receipt_type(receipt)
    if kind in ("wager", "cancel", "test"):
        return "wager"
    if kind in ("payout", "draw_refund", "cancel_refund"):
        return "payout"
    if receipt.get("transaction_type"):
        return "remit"
    return "wager"
