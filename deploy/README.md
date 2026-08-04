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
4. **Install PostgreSQL** on the same Windows server
   - Use a currently supported PostgreSQL release and include Command Line Tools.
   - Keep the service startup type set to **Automatic** and listen on localhost only.
   - Add `C:\Program Files\PostgreSQL\<version>\bin` to the system `PATH`.
5. **Download NSSM** from [nssm.cc/download](https://nssm.cc/download)
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
- Master lock signing key placeholders (`MASTER_LOCK_*`)
- A generated PostgreSQL database name, application user, and password

Create the PostgreSQL role and database from an elevated Command Prompt. Use
the exact generated values from `.env`:

```cmd
psql -U postgres -d postgres
CREATE ROLE smartwagers_app WITH LOGIN PASSWORD '<POSTGRES_PASSWORD from .env>';
CREATE DATABASE smartwagers OWNER smartwagers_app ENCODING 'UTF8';
\q
```

PostgreSQL remains bound to localhost; port 5432 must not be opened to teller PCs.

Then:
1. Run `python manage.py hash_master_lock_key` and paste the hash into `MASTER_LOCK_PASSWORD_HASH=`
2. Run `deploy\6_init_master_lock.bat` to create `C:\SmartWagers\data\master_lock.state` (disabled)
3. Restrict ACLs on `C:\SmartWagers\data` to Administrators + the Daphne service account

> **Never commit `.env` or `master_lock.state` to git.**

---

## Step 2 — Install Python dependencies

Double-click `deploy\2_install_deps.bat` (or run from Command Prompt).

This runs `pip install -r requirements.txt` and installs Django, Psycopg,
Daphne, Channels, Redis, ReportLab, WhiteNoise, and their dependencies.

---

## Step 3 — Initialize the database and static files

Double-click `deploy\3_init_database.bat`.

This runs:
- `python manage.py check_database` — verifies the PostgreSQL login
- `python manage.py migrate` — creates or updates the PostgreSQL schema
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

The service launcher waits for PostgreSQL before starting Daphne. The daily
server launcher also starts the local PostgreSQL Windows service if needed.

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
- [ ] `python manage.py check_database` reports `vendor=postgresql`
- [ ] `python manage.py verify_database --strict` succeeds

---

## Migrating an Existing SQLite Installation

### Users only (recommended for a clean restart)

If you only need existing login accounts and roles (`admin` / `teller` /
`display`), and you do **not** need old wagers, payouts, or events:

1. Confirm PostgreSQL login works: `python manage.py check_database`
2. Keep Daphne stopped
3. Copy the **old** `db.sqlite3` that still contains users onto the server
   (or keep its full path handy — a fresh GameFowl install usually has none)
4. Run `deploy\10_migrate_users_to_postgres.bat` and paste that old SQLite path
5. Start Daphne, log in with an existing account, create Settings, then start a
   new event

This path ignores Fight_Status and all SmartWagers financial tables.

### Full data migration

Use a planned maintenance window. Do not allow any teller or admin writes while
the data is copied. Print and sign the full
[`POSTGRESQL_CUTOVER.md`](POSTGRESQL_CUTOVER.md) runbook.

1. Install PostgreSQL, create the empty database/user, update `.env`, and run
   `deploy\2_install_deps.bat`.
2. Preserve an additional offline copy of `db.sqlite3`, `.env`, and
   `C:\SmartWagers\data\master_lock.state`.
3. Run `deploy\9_migrate_sqlite_to_postgres.bat` as Administrator.
4. The migration stops Daphne, upgrades a frozen SQLite copy, exports users,
   groups, and SmartWagers data, migrates PostgreSQL, imports records, resets
   sequences, compares SHA-256 manifests and financial invariants, then creates
   a PostgreSQL dump.
5. Leave Daphne stopped if any verification fails. Inspect the timestamped
   directory under `C:\SmartWagers\backups`.
6. After success, start Daphne and complete every item in the verification
   checklist before reopening betting.

The source SQLite file is never modified by the transfer script. PostgreSQL
must be empty except for schema/migration data. The script refuses to import
over existing SmartWagers records.

### Backup and restore

Create a PostgreSQL custom-format backup:

```cmd
deploy\7_backup_postgres.bat
```

Restore only during an outage; this replaces current PostgreSQL contents:

```cmd
deploy\8_restore_postgres.bat C:\SmartWagers\backups\smartwagers-YYYYMMDD-HHMMSS.dump
```

The restore script requires typing the configured database name. Always retain
an off-machine copy of event-day backups.

### Rollback

Rollback is only clean while PostgreSQL has not accepted new production writes:

1. Stop `SmartWagers-Daphne`.
2. Restore the frozen pre-cutover `.env` and `db.sqlite3`.
3. Set `DJANGO_DEBUG=True` only for a temporary local recovery run; normal
   production startup intentionally refuses SQLite.
4. Do not merge independent PostgreSQL and SQLite writes. If production writes
   occurred after cutover, restore PostgreSQL from backup instead.

---

## Troubleshooting

| Problem | Check |
|---------|-------|
| Login page shows 400 Bad Request | `CSRF_TRUSTED_ORIGINS` in `.env` must match the URL in the browser exactly (include `:8080`) |
| WebSocket disconnects immediately | Memurai not running — `memurai-cli ping` |
| Daphne reports database readiness failure | Start the PostgreSQL Windows service; verify `POSTGRES_*` values and run `python manage.py check_database` |
| `pg_dump` or `pg_restore` not found | Add the PostgreSQL `bin` directory to the system `PATH`, then reopen Command Prompt |
| Migration reports integrity problems | Leave Daphne stopped; resolve the reported duplicate status/event/result or totals mismatch in the source before retrying |
| "DisallowedHost" error | Server IP missing from `DJANGO_ALLOWED_HOSTS` in `.env` |
| Static files not loading (CSS/JS missing) | Re-run `3_init_database.bat` to re-collect static files |
| Service shows as stopped after reboot | Open `service_control.bat status`; check error logs in `C:\SmartWagers\logs\` |
| Print agent not printing | Verify `printer_name` in `config.json`; run `http://127.0.0.1:8765/printers` to list available printers |
| `service_control.bat start` says **"Unexpected status SERVICE_PAUSED"** and logs are empty | Daphne crashed under the service account. **1)** `memurai-cli ping` must return `PONG`. **2)** Open `C:\SmartWagers\logs\daphne_wrapper.log`. **3)** Manual test: `python -m daphne -v 2 -b 0.0.0.0 -p 8080 GameFowl.asgi:application`. **4)** Re-run `4_install_service.bat` as Administrator after fixing. |
| Admin pages show **Server Error 500** with `AttributeError: 'super' object has no attribute 'dicts'` | Python 3.14 is not supported by Django 5.1. Install **Python 3.12**, re-run `2_install_deps.bat`, update `deploy\python_path.txt`, and restart the service. A temporary compatibility patch is in `settings.py` for 3.14, but 3.12 is recommended for production. |
| App redirects to `/master-lock/` | Lock is enabled and expired (or state missing/tampered in production). Enter the master key to **Enable** or **Extend**. |
| Daphne will not start: `MASTER_LOCK_SIGNING_KEY` / `PASSWORD_HASH` | Set both in `.env`, then restart the service. Generate hash with `python manage.py hash_master_lock_key`. |
| `init_master_lock` refuses to run | Existing state file is present or unusable. Do **not** overwrite casually — restore from backup or use recovery procedures. |

---

## Master Lock

Offline monthly activation. Disabled by default after `6_init_master_lock.bat`.

| Action | Effect |
|--------|--------|
| **Enable** | Requires master key; grants 30 days from now |
| **Extend** | Requires master key; adds 30 days to `max(now, valid_until)` |
| **Disable** | Requires master key; turns enforcement off |

- Activation UI: `http://<SERVER-IP>:8080/master-lock/`
- Admin settings also has Enable / Extend / Disable controls
- Health probe (always 200 while Daphne is up): `http://127.0.0.1:8080/health/`
- State file: `C:\SmartWagers\data\master_lock.state` (HMAC-signed; deleting it fails closed in production)

**Limitation:** This deters casual tampering. A Windows administrator who can patch Python/source or read process secrets can bypass an offline lock.

---

## File Locations

| Item | Path |
|------|------|
| Project root | `C:\SmartWagers\GameFowl\` |
| Production config | `C:\SmartWagers\GameFowl\.env` |
| PostgreSQL data | Managed by the PostgreSQL Windows service |
| PostgreSQL backups | `C:\SmartWagers\backups\` |
| Legacy SQLite source | `C:\SmartWagers\GameFowl\db.sqlite3` (migration/rollback only) |
| Master lock state | `C:\SmartWagers\data\master_lock.state` |
| Static files | `C:\SmartWagers\GameFowl\staticfiles\` |
| Service logs | `C:\SmartWagers\logs\` |
| NSSM | `C:\SmartWagers\nssm\nssm.exe` |
| Print agent | `C:\SmartWagers\local_print_agent\` (on each cashier PC) |
