# How to release SmartWagers

Use this when shipping a version to a Windows venue. Build the package once. A **new site** is installed from that package. An **existing site** receives the same package over Tailscale, or from USB when the site is offline.

Do not copy an uncommitted working tree to a server. Do not overwrite `.env`, `.email_password`, PostgreSQL data, or `C:\SmartWagers\data\master_lock.state`.

Related pages:

- First-time Windows clicks and dialogs: [README.md](README.md)
- Day-of-event checks at the venue: [OPERATOR_RUNBOOK.md](OPERATOR_RUNBOOK.md)
- Failed apply or restore: [RECOVERY_RUNBOOK.md](RECOVERY_RUNBOOK.md)

## 1. Build the release

On the development machine, from a clean checkout of the tag or commit to ship:

```bash
git checkout v1.14.0
python deploy/pre_release.py
python deploy/build_release.py --ref v1.14.0 --output releases --field-kit
```

`pre_release.py` runs the test suite, `manage.py check`, and `makemigrations --check`. Stop if any of those fail. `build_release.py` runs those checks again unless you pass `--skip-checks`.

The command writes two folders under `releases/`:

| Folder | Use |
| --- | --- |
| `SmartWagers-<timestamp>-<sha>/` | The package. Fleet upload and `APPLY_RELEASE.bat` both use this. |
| `SmartWagers-<timestamp>-<sha>-field-kit/` | USB copy for a site with no VPN. Contains `release/`, `tools/`, and `CHECKLIST.txt`. |

To keep the previous package on the USB drive for onsite rollback:

```bash
python deploy/build_release.py --ref v1.14.0 --output releases --field-kit --previous-package releases/<previous-package> --skip-checks
```

Record the commit from `release.json` (`commit_sha`). You will pass that value to `fleet.py verify`.

The package contains the Git tree, SHA-256 checksums, Python 3.12, the database schema level, and Windows wheels. It does not contain venue secrets.

## 2. New deployment

Do this once per venue. Later updates follow section 3.

### 2.1 Prepare the server

On the new Windows server:

1. Install **Python 3.12** for all users and add it to PATH. Do not use Python 3.14.
2. Install **Memurai** and confirm `memurai-cli ping` returns `PONG`.
3. Install **PostgreSQL** with command-line tools. Leave it listening on localhost only, and put its `bin` directory on PATH.
4. Extract **NSSM** to `C:\SmartWagers\nssm\nssm.exe`.
5. Install **Tailscale** and **OpenSSH Server** so later updates can be pushed remotely. Allow SSH only from the tailnet. Do not publish ports 22, 5432, 6379, or 8080 to the public internet.

Copy the package **payload** to the server:

```text
releases/SmartWagers-.../payload/  ->  C:\SmartWagers\GameFowl\
```

Also copy these installer files from the package root into `C:\SmartWagers\GameFowl\deploy\` if they are not already in the payload: `apply_usb_release.py`, `apply_engine.py`, and `release_metadata.py`.

### 2.2 Create the site configuration

1. Edit `SERVER_IP` in `deploy\1_setup_env.bat` to this server's LAN address.
2. Run `deploy\1_setup_env.bat` as Administrator. It writes `C:\SmartWagers\GameFowl\.env`.
3. Create the database with the generated `.env` values:

```cmd
psql -U postgres -d postgres
CREATE ROLE smartwagers_app WITH LOGIN PASSWORD '<POSTGRES_PASSWORD from .env>';
CREATE DATABASE smartwagers OWNER smartwagers_app ENCODING 'UTF8';
\q
```

4. Add the venue name and, if this site uses remote admin, its Tailscale hostname:

```text
LOCATION=Venue Name
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,<LAN-IP>,<tailscale-host>
DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080,http://<LAN-IP>:8080,http://<tailscale-host>:8080
```

5. Put the SMTP password in `.email_password` next to `manage.py`, or set `EMAIL_HOST_PASSWORD` in `.env`.
6. Run `python manage.py hash_master_lock_key` and paste the result into `MASTER_LOCK_PASSWORD_HASH`.
7. Run `deploy\6_init_master_lock.bat`. Restrict `C:\SmartWagers\data` to Administrators and the Daphne service account.
8. Run `python manage.py check_site_config`. It prints missing setting names, not secret values.

### 2.3 Install and start

Run these as Administrator, in order:

1. `deploy\2_install_deps.bat`
2. `deploy\3_init_database.bat`
3. `python manage.py createsuperuser`
4. In Django admin (`http://localhost:8080/admin/` after the service is up), create groups `admin`, `teller`, and `display`, then assign users.
5. `deploy\4_install_service.bat` — registers **SmartWagers-Daphne** and schedules the daily backup plus commission-email retry.
6. `deploy\5_firewall.bat` — opens TCP 8080 on the LAN.

### 2.4 Tellers and remote access

1. On the server, run `local_print_agent\prepare_vendor.bat` once while the server has internet.
2. On each cashier PC, install the receipt printer, download the print agent from **Admin → Print Agent**, and run `install_print_agent.bat`.
3. Set `SMARTWAGERS_SERVER_URL=http://<LAN-IP>:8080` in the teller `server.env`.
4. On the operator PC, copy `deploy/sites.example.json` to `deploy/sites.json`. Add this venue with its Tailscale hostname and SSH key path. Set `"group": "canary"` for the first site you will update remotely. Do not put passwords in that file.

### 2.5 Confirm the new site

From a teller PC, open `http://<LAN-IP>:8080/login`. Then check:

- `http://localhost:8080/health/ready/` on the server returns `"ok": true`
- Admin can open a fight and the display board updates
- A teller can place a bet and print a receipt
- `C:\SmartWagers\backups\last_backup.json` appears after the first scheduled backup, or run `python deploy\postgres_tools.py backup-maintain` once
- Reboot the server. PostgreSQL, Memurai, and SmartWagers-Daphne come back without a manual start

Register the installed commit so the next remote update can see what is running. If you applied the package with `APPLY_RELEASE.bat` after the install scripts, this file already exists. Otherwise the first remote deploy in section 3 writes it.

## 3. Update an existing deployment

Stop new bets and wait until tellers are idle. Leave the server powered on. The apply stops Daphne, backs up PostgreSQL when there are migrations, then starts Daphne again.

### 3.1 Remote update (normal path)

From the operator PC, with Tailscale connected:

```bash
python deploy/fleet.py preflight --sites deploy/sites.json --site <venue>
python deploy/fleet.py deploy --sites deploy/sites.json --site <venue> --package releases/<package>
python deploy/fleet.py verify --sites deploy/sites.json --site <venue> --expect-sha <commit>
```

For several venues, update the canary group first. A failed site stops the rest. Sites that already succeeded stay on the new release until you roll those sites back.

```bash
python deploy/fleet.py deploy --sites deploy/sites.json --group canary --package releases/<package>
python deploy/fleet.py verify --sites deploy/sites.json --group canary --expect-sha <commit>
python deploy/fleet.py deploy --sites deploy/sites.json --group fleet --package releases/<package>
python deploy/fleet.py status --sites deploy/sites.json
```

`--dry-run` prints the SSH and copy commands without connecting. Each attempt is appended to `deploy/fleet_history/<site>.jsonl`.

Deploying the same commit again does not copy or migrate a second time.

### 3.2 USB update (site is offline)

1. Copy the field-kit folder to a USB drive.
2. At the venue, run `release\<package>\APPLY_RELEASE.bat` as Administrator.
3. Wait until it says the release was applied. Then open `http://localhost:8080/health/ready/`.

The USB installer uses the same apply engine as the remote deploy. Checksums are verified before files change.

### 3.3 Site files were edited by hand

Export an inventory before building the corrective package:

```bat
deploy\13_export_server_inventory.bat E:\server_inventory.json
```

On the development machine:

```bash
python deploy/build_release.py --inventory /path/to/server_inventory.json --output releases --skip-checks
```

Apply that package with section 3.1 or 3.2. It still refuses to replace `.env`, the database, and the master-lock state.

### 3.4 After every update

- `http://<server>:8080/health/ready/` returns `"ok": true`
- `/health/` shows the new `app_version` and `commit_sha`
- Admin login, display board, one test bet, and one receipt all work
- If a teller receipt fails, reinstall that PC's print agent from **Admin → Print Agent**. An old teller agent does not roll the server back

Record a teller that was updated:

```bat
python deploy\record_teller_agent.py --host TELLER-1 --version 1.13.2-shared-printer
```

## 4. If the update fails

The installer restores the previous code and the pre-migration database backup, then writes `deploy\.last_deploy_failure.json`. Daphne is started again on the restored code.

If the server is still down:

```bat
python deploy\apply_engine.py --rollback --target C:\SmartWagers\GameFowl
```

From the operator PC:

```bash
python deploy/fleet.py rollback --sites deploy/sites.json --site <venue>
python deploy/fleet.py collect-diagnostics --sites deploy/sites.json --site <venue>
```

Full restore steps are in [RECOVERY_RUNBOOK.md](RECOVERY_RUNBOOK.md).
