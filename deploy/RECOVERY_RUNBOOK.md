# Recovery runbook

The apply engine stops Daphne, snapshots code, backs up PostgreSQL when migrations run, and writes `deploy/.deployed_release.json` only after readiness passes. A failed migration, dependency install, readiness check, or service start restores that snapshot and backup, then writes `deploy/.last_deploy_failure.json`.

## Automatic rollback failed or the power dropped

1. Read `C:\SmartWagers\logs\usb_release.log` and `deploy\.last_deploy_failure.json`.
2. Restore the previous code and database recorded by the last successful release:

```bat
python deploy\apply_engine.py --rollback --target C:\SmartWagers\GameFowl
```

3. If that snapshot is missing, apply the previous package from the field kit `rollback` folder with `APPLY_RELEASE.bat`.
4. Confirm `http://localhost:8080/health/ready/` before opening the site to tellers.

A database-only restore replaces venue data. Use it when the code snapshot is already correct:

```bat
deploy\8_restore_postgres.bat
```

Type the database name exactly when prompted. Practice this restore on a copy before relying on it at a venue.

## Diagnostics

On the server:

```bat
python deploy\collect_diagnostics.py --output C:\SmartWagers\logs\diagnostics.json
```

From the operator PC:

```bash
python deploy/fleet.py collect-diagnostics --sites deploy/sites.json --site <name>
```

The bundle lists environment names, release, backup status, disk space, and recent logs. It does not copy secret values.

## Failure drills

Rehearse these on a non-production Windows host before the first remote venue, then once on the canary site.

| Drill | Expected result |
| --- | --- |
| Disconnect VPN during upload | The package is not applied. The running release stays in place. |
| Change one byte of a packaged file | Checksum verification fails before files are copied. |
| Fill the disk below the required free space | Apply stops before Daphne is stopped. |
| Stop PostgreSQL | Readiness fails and the previous code and backup return. |
| Stop Memurai | Readiness fails and the previous release returns. |
| Force a migration error | The pre-migration backup is restored and the old code returns. |
| Make the service start fail | The old release is restored and start is attempted again. |
| Interrupt power after copy starts | Rerun the same package. A finished release is detected and not applied twice. |
| Apply the previous USB package | The site returns to that package and records the rollback. |

Do not promote the fleet until remote deploy, automatic rollback, backup restore, and USB recovery have each been completed on the canary.

## Backups

`deploy\schedule_maintenance.bat` creates a daily validated backup and keeps 14 dumps. `backup-maintain` records `C:\SmartWagers\backups\last_backup.json`. Copy encrypted backup files off the server when the link is up. Master-lock state is not inside the database backup; copy `C:\SmartWagers\data\master_lock.state` separately and restrict its ACL.
