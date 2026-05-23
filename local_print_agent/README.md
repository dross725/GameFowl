# SmartWagers Local Print Agent

This agent runs on each Windows cashier PC and listens only on `127.0.0.1`.
The browser sends wager and payout receipt data to this local agent, and the agent prints
silently to the cashier's own USB receipt printer through the Windows print queue.

## Install On Each Cashier PC

1. Install the USB receipt printer driver in Windows.
2. Install Python 3 for Windows.
3. Install pywin32:

```bat
py -m pip install pywin32
```

4. Copy `config.example.json` to `config.json`.
5. Set `printer_name` in `config.json` to the exact Windows printer name.
   Leave it empty to use the Windows default printer.
6. Start the agent:

```bat
run_print_agent.bat
```

## Find Printer Names

With the agent running, open this URL on the cashier PC:

```text
http://127.0.0.1:8765/printers
```

Copy the printer name into `config.json`.

## Print Modes

Use `windows_driver` for normal Windows printer drivers, including inkjet/laser
printers and many USB receipt printers:

```json
"print_mode": "windows_driver"
```

Use `escpos` only for ESC/POS thermal receipt printers that accept raw receipt
commands:

```json
"print_mode": "escpos"
```

If the Windows queue briefly appears and disappears without printing, switch to
`windows_driver`. That usually means the printer driver accepted the raw job but
could not render ESC/POS commands.

## Test Health

Open:

```text
http://127.0.0.1:8765/health
```

You should see a JSON response saying the agent is running.

## Browser Override

The web app uses `http://127.0.0.1:8765` by default. To use a different port
on a cashier browser, set this once in the browser console:

```javascript
localStorage.setItem("smartwagersPrintAgentUrl", "http://127.0.0.1:8766");
```

Then refresh the SmartWagers page.

## Endpoints

- `POST /print-wager` prints a bet receipt.
- `POST /print-payout` prints a payout receipt.
