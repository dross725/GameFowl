# Operator runbook

Use this at a venue. Release managers use [RELEASE_MANAGER_RUNBOOK.md](RELEASE_MANAGER_RUNBOOK.md). Failed updates use [RECOVERY_RUNBOOK.md](RECOVERY_RUNBOOK.md).

## Normal remote update

1. Stop new bets and wait until tellers are idle.
2. Leave the server on. The release manager applies the package over Tailscale.
3. After the manager confirms success, open `http://<server>:8080/health/ready/`.
4. `ok` must be true. Then log in as admin and open the display board.
5. If teller receipts fail, reinstall the print agent from Admin, Print Agent. An old teller agent does not roll the server back.

## What the server keeps locally

- Application: `C:\SmartWagers\GameFowl`
- Secrets: `.env`, `.email_password`, and `C:\SmartWagers\data\master_lock.state`
- Backups: `C:\SmartWagers\backups`
- Previous two code snapshots: `C:\SmartWagers\release_history`
- Logs: `C:\SmartWagers\logs`

Do not copy secrets into a release folder or email them.

## Daily checks

- `http://localhost:8080/health/ready/` returns `ok: true`.
- PostgreSQL and Memurai services are running.
- `C:\SmartWagers\backups\last_backup.json` shows a validated backup from the last day.
- Commission email retry is scheduled as `SmartWagers-SendPendingReports`.

## Onsite USB update

Use this only when Tailscale cannot reach the site.

1. Insert the field kit built for the approved release.
2. Read `CHECKLIST.txt` on the USB drive.
3. Run `release\<package>\APPLY_RELEASE.bat` as Administrator.
4. Confirm `/health/ready/` before tellers resume.

The USB package uses the same apply engine as a VPN update. A package that already matches the running commit is not applied again.

## Tellers

Record each teller agent after installation:

```bat
python deploy\record_teller_agent.py --host TELLER-1 --version 1.13.2-shared-printer
```

Outdated agents are reported by `python deploy\fleet.py status` and by the admin operations page. Update those PCs separately.
