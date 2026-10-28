# Release manager runbook

Build one immutable package from a tested Git commit, deploy it to the canary site over Tailscale, then deploy the same package to the remaining sites. Do not sync an uncommitted working tree to production.

## One-time management path

1. Install Tailscale on the operator PC and on every Windows server. Approve only the operator and the servers into the tailnet. Server firewall, OpenSSH, MagicDNS, and `sites.json` steps are in [HOW_TO_RELEASE.md](HOW_TO_RELEASE.md) section 2.6.
2. Install OpenSSH Server on each Windows server and allow port 22 from the tailnet, not from the public internet.
3. Do not publish Daphne port 8080, PostgreSQL, Redis, or SSH to the public internet.
4. Copy [sites.example.json](sites.example.json) to `deploy/sites.json`. `sites.json` is gitignored.
5. Use a distinct SSH key path per site. Do not put passwords in the registry.
6. Copy [sync_config.example.env](sync_config.example.env) to `deploy/sync_config.env` only for a one-site fallback. That file is gitignored. If an older copy was committed, remove it from the Git index and rotate any credential that was stored in it.

## Build a release

From a clean checkout of the tag or commit to ship:

```bash
python deploy/pre_release.py
python deploy/build_release.py --ref v1.14.0 --output releases --field-kit --skip-checks
```

`pre_release.py` runs the test suite, `manage.py check`, and `makemigrations --check`. The package contains the Git tree, Windows wheels, checksums, the commit SHA, Python 3.12, and the migration level. Uncommitted files are excluded.

`--field-kit` adds the checklist, diagnostics, restore script, and an optional `--previous-package` for onsite rollback.

## Deploy

Canary first. A failure stops the rest of the fleet; sites that already succeeded stay on the new release until you roll them back.

```bash
python deploy/fleet.py preflight --sites deploy/sites.json --group canary
python deploy/fleet.py deploy --sites deploy/sites.json --group canary --package releases/<package>
python deploy/fleet.py verify --sites deploy/sites.json --group canary --expect-sha <commit>
python deploy/fleet.py deploy --sites deploy/sites.json --group fleet --package releases/<package>
python deploy/fleet.py status --sites deploy/sites.json
```

Each attempt is appended to `deploy/fleet_history/<site>.jsonl` with the operator, time, version, and result.

## Inventory repair

If a site was patched by hand, export its inventory and build a repair package. The repair package still uses `release.json` and the same apply engine.

```bash
python deploy/build_release.py --inventory path/to/server_inventory.json --output releases --skip-checks
```

## Configuration that stays on the site

`.env` holds hosts, CSRF origins, PostgreSQL, SMTP, Redis, timezone, and the venue name. Production startup fails if hosts or CSRF origins are missing. Generate a new site with `deploy\1_setup_env.bat`, then:

```bat
python manage.py check_site_config
```

The command prints setting names and warnings, not secret values.

## Version visibility

- `http://<server>:8080/health/` is liveness and includes the version and schema.
- `http://<server>:8080/health/ready/` checks database, Redis, migrations, master lock, and release metadata.
- `http://<server>:8080/operations/status/` is limited to admin users and adds backup, email queue, disk, and teller-agent status.
