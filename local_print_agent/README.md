# SmartWagers Local Print Agent

This agent runs on each Windows cashier PC and listens only on `127.0.0.1`.
The browser sends wager and payout receipt data to this local agent, and the agent prints
silently to the cashier's own USB receipt printer through the Windows print queue.

Offline teller PCs use a **bundled embeddable Python 3.12 + pywin32** under `python\`
(built on the server). No system Python and no internet are required on the cashier PC.

## Download From The Server

1. On the SmartWagers server (with internet), run once:

```bat
local_print_agent\prepare_vendor.bat
```

2. In the web app: **Admin ▾ → Print Agent → Download Print Agent**
3. Copy `SmartWagers-PrintAgent.zip` to each cashier PC (LAN, USB, etc.)

## Install On Each Cashier PC

1. Install the USB receipt printer driver in Windows.
2. Set that printer as the **Windows default printer**.
3. Unzip to e.g. `C:\SmartWagers\local_print_agent\`.
4. Double-click `install_print_agent.bat`

That script:

- Uses bundled `python\python.exe` (falls back to PATH only if the bundle is missing)
- Verifies pywin32 (does **not** call pip / the internet)
- Shows the detected Windows default printer and installed queues
- Creates `config.json` from the example with `printer_name` left empty
- Adds a silent Startup entry so the agent launches hidden on login

Leave `printer_name` empty so the agent always uses the Windows default.
Set `printer_name` only if the receipt printer is **not** the Windows default.

5. Start the agent in the background (no console window):

```bat
run_print_agent.bat
```

Or double-click `start_print_agent_silent.vbs`. For a visible debug console, use
`run_print_agent_debug.bat`.

## Desktop icon (teller)

Windows cannot change the icon of a `.vbs` file itself. To get the club logo on the desktop:

1. Create `server.env` from `server.env.example` with `SMARTWAGERS_SERVER_URL=...`
2. Double-click `create_teller_shortcut.bat`.

That creates a **SmartWagers Teller** shortcut on the Desktop that runs `start_teller_silent.vbs` with the logo icon. Pin that shortcut if you want.

## Find Printer Names

With the agent running, open this URL on the cashier PC:

```text
http://127.0.0.1:8765/printers
```

Usually you do not need to copy a name into `config.json` — empty `printer_name`
uses the Windows default. Use `/printers` only when overriding.

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

To force the browser to use the mobile server print queue (or always use the
Windows agent):

```javascript
localStorage.setItem("smartwagersPrintMode", "server"); // or "local" or "auto"
```

## Mobile Bluetooth

Android/iOS Bluetooth printing is handled by the companion app in
`../mobile_print_agent/` (not this Windows agent). See that README and
**Admin → Print Agent** for APK / TestFlight install steps.

## Endpoints

- `POST /print-wager` prints a bet receipt.
- `POST /print-payout` prints a payout receipt.
