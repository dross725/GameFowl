import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
AGENT_VERSION = "1.2-code39-bars"
DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 8765,
    "printer_name": "",
    "print_mode": "windows_driver",
    "code_page": "cp437",
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
        return f"{float(str(value).replace(',', '')):.2f}"
    except (TypeError, ValueError):
        return str(value or "0.00")


def text_line(value="", code_page="cp437"):
    return f"{value}\n".encode(code_page, errors="replace")


def receipt_type(receipt):
    return str(receipt.get("receipt_type", "payout")).lower()


def escpos_receipt(receipt, code_page="cp437"):
    transaction_id = str(receipt.get("transaction_id", ""))
    side = str(receipt.get("side", "")).upper()
    odds = str(receipt.get("odds", ""))
    multiplier = str(receipt.get("multiplier", ""))
    total_payout = money(receipt.get("Total_Payout") or receipt.get("total_payout"))
    amount = money(receipt.get("amount"))
    fightnum = str(receipt.get("fightnum", ""))
    cashier = str(receipt.get("cashier", ""))
    date = str(receipt.get("date", ""))
    is_wager = receipt_type(receipt) == "wager"

    output = bytearray()
    output += b"\x1b@"  # Initialize printer
    output += b"\x1ba\x01"  # Center alignment
    output += text_line(date, code_page)
    output += b"\x1bE\x01"
    if is_wager:
        output += text_line("BET RECEIPT", code_page)
    else:
        output += text_line("CONGRATULATIONS!", code_page)
    output += text_line(f"Fight Number: {fightnum}", code_page)
    if is_wager:
        output += text_line(side, code_page)
        output += text_line(f"Amount: {amount}", code_page)
    else:
        output += text_line(f"{side} - {odds}", code_page)
        output += text_line(f"Odds: {multiplier}", code_page)
        output += text_line(f"Payout Amount: {total_payout}", code_page)
    output += b"\x1bE\x00"
    output += text_line("", code_page)
    output += text_line(f"Cashier: {cashier}", code_page)
    output += text_line(f"Transaction ID: {transaction_id}", code_page)
    output += text_line("", code_page)

    if transaction_id:
        barcode_data = ("{B" + transaction_id).encode("ascii", errors="ignore")
        output += b"\x1dH\x02"  # Barcode text below
        output += b"\x1dh\x50"  # Barcode height
        output += b"\x1dw\x02"  # Barcode width
        output += b"\x1dk\x49" + bytes([len(barcode_data)]) + barcode_data
        output += text_line("", code_page)

    output += text_line("", code_page)
    output += text_line("", code_page)
    output += b"\x1dV\x42\x00"  # Partial cut
    return bytes(output)


def get_win32print():
    try:
        import win32print
    except ImportError as exc:
        raise RuntimeError("pywin32 is not installed. Run: py -m pip install pywin32") from exc

    return win32print


def get_win32ui():
    try:
        import win32ui
    except ImportError as exc:
        raise RuntimeError("pywin32 is not installed. Run: py -m pip install pywin32") from exc

    return win32ui


def get_win32con():
    try:
        import win32con
    except ImportError as exc:
        raise RuntimeError("pywin32 is not installed. Run: py -m pip install pywin32") from exc

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


def print_windows_driver(printer_name, receipt):
    win32ui = get_win32ui()
    win32con = get_win32con()
    transaction_id = str(receipt.get("transaction_id", ""))
    side = str(receipt.get("side", "")).upper()
    odds = str(receipt.get("odds", ""))
    multiplier = str(receipt.get("multiplier", ""))
    total_payout = money(receipt.get("Total_Payout") or receipt.get("total_payout"))
    amount = money(receipt.get("amount"))
    fightnum = str(receipt.get("fightnum", ""))
    cashier = str(receipt.get("cashier", ""))
    date = str(receipt.get("date", ""))
    is_wager = receipt_type(receipt) == "wager"

    dc = win32ui.CreateDC()
    dc.CreatePrinterDC(printer_name)
    dpi_x = dc.GetDeviceCaps(win32con.LOGPIXELSX)
    dpi_y = dc.GetDeviceCaps(win32con.LOGPIXELSY)
    page_width = dc.GetDeviceCaps(win32con.HORZRES)
    margin_x = max(int(dpi_x * 0.15), 30)
    y = max(int(dpi_y * 0.15), 30)
    line_gap = int(dpi_y * 0.12)

    normal_font = win32ui.CreateFont({
        "name": "Arial",
        "height": int(dpi_y * 0.11),
        "weight": 400,
    })
    bold_font = win32ui.CreateFont({
        "name": "Arial",
        "height": int(dpi_y * 0.13),
        "weight": 700,
    })
    barcode_font = win32ui.CreateFont({
        "name": "Consolas",
        "height": int(dpi_y * 0.10),
        "weight": 700,
    })
    barcode_height = int(dpi_y * 0.45)
    barcode_narrow = max(int(dpi_x * 0.012), 2)

    def draw_centered(text, font):
        nonlocal y
        dc.SelectObject(font)
        text_width, text_height = dc.GetTextExtent(text)
        x = max(int((page_width - text_width) / 2), margin_x)
        dc.TextOut(x, y, text)
        y += text_height + line_gap

    def draw_left(text, font=normal_font):
        nonlocal y
        dc.SelectObject(font)
        _, text_height = dc.GetTextExtent(text)
        dc.TextOut(margin_x, y, text)
        y += text_height + line_gap

    dc.StartDoc("SmartWagers Receipt")
    try:
        dc.StartPage()
        draw_centered(date, normal_font)
        draw_centered("BET RECEIPT" if is_wager else "CONGRATULATIONS!", bold_font)
        draw_centered(f"Fight Number: {fightnum}", bold_font)
        if is_wager:
            draw_centered(side, bold_font)
            draw_centered(f"Amount: {amount}", bold_font)
        else:
            draw_centered(f"{side} - {odds}", bold_font)
            draw_centered(f"Odds: {multiplier}", bold_font)
            draw_centered(f"Payout Amount: {total_payout}", bold_font)
        y += line_gap
        draw_left(f"Cashier: {cashier}")
        draw_left(f"Transaction ID: {transaction_id}")
        y += line_gap
        if transaction_id:
            barcode_width = code39_width(transaction_id, barcode_narrow)
            barcode_x = max(int((page_width - barcode_width) / 2), margin_x)
            draw_code39(dc, transaction_id, barcode_x, y, barcode_narrow, barcode_height)
            y += barcode_height + line_gap
            draw_centered(transaction_id, barcode_font)
        dc.EndPage()
    finally:
        dc.EndDoc()
        dc.DeleteDC()

    return None


def print_receipt(config, printer_name, receipt):
    print_mode = str(config.get("print_mode", "windows_driver")).lower()
    if print_mode == "escpos":
        payload = escpos_receipt(receipt, config["code_page"])
        return print_raw(printer_name, payload)
    if print_mode == "windows_driver":
        return print_windows_driver(printer_name, receipt)

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
            self.send_json(200, {
                "ok": True,
                "message": "SmartWagers print agent is running.",
                "version": AGENT_VERSION,
            })
            return

        if self.path == "/printers":
            try:
                self.send_json(200, {"ok": True, "printers": list_printers()})
            except RuntimeError as exc:
                self.send_json(500, {"ok": False, "error": str(exc)})
            return

        self.send_json(404, {"ok": False, "error": "Unknown endpoint."})

    def do_POST(self):
        if not self.is_loopback_request():
            self.send_json(403, {"ok": False, "error": "Only localhost requests are allowed."})
            return

        if self.path not in ("/print-payout", "/print-wager"):
            self.send_json(404, {"ok": False, "error": "Unknown endpoint."})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length)
            receipt = json.loads(raw_body.decode("utf-8"))
            config = load_config()
            printer_name = configured_printer(config)
            job_id = print_receipt(config, printer_name, receipt)
        except json.JSONDecodeError:
            self.send_json(400, {"ok": False, "error": "Invalid JSON payload."})
            return
        except RuntimeError as exc:
            self.send_json(500, {"ok": False, "error": str(exc)})
            return
        except Exception as exc:
            self.send_json(500, {"ok": False, "error": f"Print failed: {exc}"})
            return

        self.send_json(200, {
            "ok": True,
            "message": f"Receipt sent to {printer_name}.",
            "job_id": job_id,
            "printer_name": printer_name,
        })


def main():
    config = load_config()
    server_address = (config["host"], int(config["port"]))
    httpd = HTTPServer(server_address, PrintAgentHandler)
    print(f"SmartWagers print agent {AGENT_VERSION} running at http://{server_address[0]}:{server_address[1]}")
    print("Press Ctrl+C to stop.")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
