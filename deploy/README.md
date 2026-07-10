# SmartWagers — Windows Deployment Guide

Follow these steps **in order** on the Windows server machine.

---

## Before You Start

1. **Copy this entire project** to the server. Recommended path: `C:\SmartWagers\GameFowl\`
2. **Install Python 3.12** from [python.org](https://python.org)
   - Check **"Add Python to PATH"** and **"Install for all users"** during setup.
   - Verify: open Command Prompt → `python --version`
3. **Install Memurai** (native Redis for Windows) from [memurai.com](https://www.memurai.com)
   - The installer registers itself as a Windows service automatically (starts on boot).
   - Verify: open Command Prompt → `redis-cli ping` → should return `PONG`
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
- `CSRF_TRUSTED_ORIGINS` set to `http://<SERVER-IP>:8000`

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

Then open `http://localhost:8000/admin/` and:
1. Create three **Groups**: `admin`, `teller`, `display`
2. Create user accounts and assign each to its group

---

## Step 4 — Install Daphne as a Windows service

Run `deploy\4_install_service.bat` **as Administrator**.

This registers a Windows service called **SmartWagers-Daphne** that:
- Starts automatically on boot
- Runs Daphne on `0.0.0.0:8000` (all network interfaces)
- Logs to `C:\SmartWagers\logs\daphne_stdout.log`

Verify: open `http://localhost:8000/login` — you should see the login page.

### Service management

Use `deploy\service_control.bat` to start, stop, restart, check status, or open logs:

```cmd
service_control.bat start
service_control.bat stop
service_control.bat restart
service_control.bat status
service_control.bat logs
```

---

## Step 5 — Open the Windows Firewall

Run `deploy\5_firewall.bat` **as Administrator**.

This adds an inbound rule that allows LAN clients to reach TCP port 8000.

Test from another PC on the network: `http://<SERVER-IP>:8000/login`

---

## Step 6 — Deploy the print agent on each cashier PC

On every Windows PC that will handle payouts (teller/cashier stations):

1. Copy the `local_print_agent\` folder to the cashier PC (e.g. `C:\SmartWagers\local_print_agent\`)
2. Run `local_print_agent\install_print_agent.bat`
   - Installs `pywin32`
   - Creates `config.json` and opens it in Notepad — set `printer_name` to the
     exact Windows printer queue name for that PC's receipt printer
   - Adds the agent to the Windows **Startup** folder so it auto-starts on login

Test: open `http://127.0.0.1:8765/health` in a browser on the cashier PC.

---

## Verification Checklist

Test from a LAN client browser at `http://<SERVER-IP>:8000/login`:

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
| Login page shows 400 Bad Request | `CSRF_TRUSTED_ORIGINS` in `.env` must match the URL in the browser exactly (include `:8000`) |
| WebSocket disconnects immediately | Memurai/Redis not running — `redis-cli ping` |
| "DisallowedHost" error | Server IP missing from `DJANGO_ALLOWED_HOSTS` in `.env` |
| Static files not loading (CSS/JS missing) | Re-run `3_init_database.bat` to re-collect static files |
| Service shows as stopped after reboot | Open `service_control.bat status`; check error logs in `C:\SmartWagers\logs\` |
| Print agent not printing | Verify `printer_name` in `config.json`; run `http://127.0.0.1:8765/printers` to list available printers |

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
