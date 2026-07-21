# SmartWagers — Windows Deployment Guide

Follow these steps **in order** on the Windows server machine.

---

## Before You Start

1. **Copy this entire project** to the server. Recommended path: `C:\SmartWagers\GameFowl\`
2. **Install Python 3.12** from [python.org](https://python.org)
   - Use **3.12** (or 3.13). Do **not** use Python 3.14 with Django 5.1 — admin pages crash.
   - Check **"Add Python to PATH"** and **"Install for all users"** during setup.
   - Verify: open Command Prompt → `python --version`
3. **Install Memurai** (native Redis for Windows) from [memurai.com](https://www.memurai.com)
   - The installer registers itself as a Windows service automatically (starts on boot).
   - Verify: open Command Prompt → `memurai-cli ping` → should return `PONG`
4. **Download NSSM** from [nssm.cc/download](https://nssm.cc/download)
   - Extract `nssm.exe` to `C:\SmartWagers\nssm\`

---

## Step 1 — Create the production .env

Open `deploy\1_setup_env.bat` in Notepad and change `SERVER_IP` to the LAN IP of
this server (e.g. `192.168.1.10`). Then **right-click → Run as administrator**.

This creates `C:\SmartWagers\GameFowl\.env` with:
- A fresh `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG=False`
- `ALLOWED_HOSTS` locked to localhost + your server IP
- `CSRF_TRUSTED_ORIGINS` set to `http://<SERVER-IP>:8080`

> **Never commit `.env` to git.** It is already listed in `.gitignore`.

---

## Step 2 — Install Python dependencies

Double-click `deploy\2_install_deps.bat` (or run from Command Prompt).

This runs `pip install -r requirements.txt` and installs Django, Daphne, Channels,
Redis, ReportLab, WhiteNoise, and their dependencies.

---

## Step 3 — Initialize the database and static files

Double-click `deploy\3_init_database.bat`.

This runs:
- `python manage.py migrate` — creates `db.sqlite3` (or updates existing)
- `python manage.py collectstatic` — copies static assets to `staticfiles/`

### Create the superuser (first deployment only)

After the script finishes, open Command Prompt in `C:\SmartWagers\GameFowl\` and run:

```cmd
python manage.py createsuperuser
```

Then open `http://localhost:8080/admin/` and:
1. Create three **Groups**: `admin`, `teller`, `display`
2. Create user accounts and assign each to its group

---

## Step 4 — Install Daphne as a Windows service

Run `deploy\4_install_service.bat` **as Administrator**.

This registers a Windows service called **SmartWagers-Daphne** that:
- Starts automatically on boot
- Runs Daphne on `0.0.0.0:8080` (all network interfaces)
- Logs to `C:\SmartWagers\logs\daphne_stdout.log`

Verify: open `http://localhost:8080/login` — you should see the login page.

### Service management

Use `deploy\service_control.bat` to start, stop, restart, check status, or open logs:

```cmd
service_control.bat start
service_control.bat stop
service_control.bat restart
service_control.bat status
service_control.bat logs
```

### Daily launchers

| PC | Script | What it does |
|----|--------|--------------|
| **Server** | `deploy\start_server.bat` | Checks/starts Memurai + Daphne (waits until `:8080` responds) + print agent, then opens Chrome to `/login` |
| **Server (silent)** | `deploy\start_server_silent.vbs` | Same checks hidden (no CMD); logs to `C:\SmartWagers\logs\start_server_silent.log`; opens Chrome only when Daphne is ready |
| **Teller** | `local_print_agent\start_teller.bat` | Starts the print agent if needed, then opens Chrome to `SMARTWAGERS_SERVER_URL` from `.env` / `server.env` |
| **Teller (silent)** | `local_print_agent\start_teller_silent.vbs` | Same as teller, **no CMD window** |
| **Print agent only** | `local_print_agent\run_print_agent.bat` | Starts the agent in the background via `pythonw` (no console) |

**Server:** pin `start_server_silent.vbs` to the desktop (or put a shortcut in Startup). For a logo icon, run `deploy\create_server_shortcut.bat`. Use **Run as administrator** if Daphne fails to start. Daphne and Memurai already run as Windows services; the silent launcher only checks them and starts the print agent + Chrome.

**Teller:** copy `local_print_agent\` to the cashier PC, create `server.env` from `server.env.example`, and set:

```
SMARTWAGERS_SERVER_URL=http://<SERVER-LAN-IP>:8080
```

On the server `.env`, also add (or regenerate with an updated `1_setup_env.bat`):

```
SMARTWAGERS_SERVER_URL=http://<SERVER-LAN-IP>:8080
```

---

## Step 5 — Open the Windows Firewall

Run `deploy\5_firewall.bat` **as Administrator**.

This adds an inbound rule that allows LAN clients to reach TCP port 8080.

Test from another PC on the network: `http://<SERVER-IP>:8080/login`

---

## Step 6 — Deploy the print agent on each cashier PC

On every Windows PC that will handle payouts (teller/cashier stations):

1. Copy the `local_print_agent\` folder to the cashier PC (e.g. `C:\SmartWagers\local_print_agent\`)
2. Run `local_print_agent\install_print_agent.bat`
   - Installs `pywin32`
   - Creates `config.json` and opens it in Notepad — set `printer_name` to the
     exact Windows printer queue name for that PC's receipt printer
   - Adds the agent to the Windows **Startup** folder so it auto-starts on login
3. Optional: run `local_print_agent\create_teller_shortcut.bat` to put a
   **SmartWagers Teller** icon (club logo) on the Desktop that launches
   `start_teller_silent.vbs`

Test: open `http://127.0.0.1:8765/health` in a browser on the cashier PC.

---

## Verification Checklist

Test from a LAN client browser at `http://<SERVER-IP>:8080/login`:

- [ ] Login page loads
- [ ] Admin can start a fight and change fight status
- [ ] Teller page shows live pot updates via WebSocket when admin acts
- [ ] Display board updates in real time
- [ ] Bet can be placed and receipt is generated
- [ ] Payout barcode scan works and print agent prints the receipt
- [ ] Restart the server — both Memurai and SmartWagers-Daphne services start automatically

---

## Troubleshooting

| Problem | Check |
|---------|-------|
| Login page shows 400 Bad Request | `CSRF_TRUSTED_ORIGINS` in `.env` must match the URL in the browser exactly (include `:8080`) |
| WebSocket disconnects immediately | Memurai not running — `memurai-cli ping` |
| "DisallowedHost" error | Server IP missing from `DJANGO_ALLOWED_HOSTS` in `.env` |
| Static files not loading (CSS/JS missing) | Re-run `3_init_database.bat` to re-collect static files |
| Service shows as stopped after reboot | Open `service_control.bat status`; check error logs in `C:\SmartWagers\logs\` |
| Print agent not printing | Verify `printer_name` in `config.json`; run `http://127.0.0.1:8765/printers` to list available printers |
| `service_control.bat start` says **"Unexpected status SERVICE_PAUSED"** and logs are empty | Daphne crashed under the service account. **1)** `memurai-cli ping` must return `PONG`. **2)** Open `C:\SmartWagers\logs\daphne_wrapper.log`. **3)** Manual test: `python -m daphne -v 2 -b 0.0.0.0 -p 8080 GameFowl.asgi:application`. **4)** Re-run `4_install_service.bat` as Administrator after fixing. |
| Admin pages show **Server Error 500** with `AttributeError: 'super' object has no attribute 'dicts'` | Python 3.14 is not supported by Django 5.1. Install **Python 3.12**, re-run `2_install_deps.bat`, update `deploy\python_path.txt`, and restart the service. A temporary compatibility patch is in `settings.py` for 3.14, but 3.12 is recommended for production. |

---

## File Locations

| Item | Path |
|------|------|
| Project root | `C:\SmartWagers\GameFowl\` |
| Production config | `C:\SmartWagers\GameFowl\.env` |
| Database | `C:\SmartWagers\GameFowl\db.sqlite3` |
| Static files | `C:\SmartWagers\GameFowl\staticfiles\` |
| Service logs | `C:\SmartWagers\logs\` |
| NSSM | `C:\SmartWagers\nssm\nssm.exe` |
| Print agent | `C:\SmartWagers\local_print_agent\` (on each cashier PC) |
