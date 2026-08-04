# PostgreSQL Cutover Runbook

Use one maintenance window with a named operator and verifier. Do not reopen
betting until both sign the acceptance section.

## Before the window

- Install PostgreSQL locally, create the `smartwagers_app` role/database, and
  restrict PostgreSQL to `127.0.0.1`.
- Confirm `pg_dump`, `pg_restore`, Python, Memurai, and NSSM are available.
- Confirm `.env` `POSTGRES_PORT` matches the Windows PostgreSQL listen port.
- Run the complete test suite against a non-production PostgreSQL database.
- Verify print agents on every teller PC.
- Announce the outage and ensure no fight is in progress.

### Choose the migration mode

- **Users only:** keep login accounts/groups, discard old wagers/events/payouts.
  Use `deploy\10_migrate_users_to_postgres.bat` and skip Fight_Status repair.
- **Full data:** preserve all SmartWagers records. Continue with the steps below
  and record the current active event, fight number, pot totals, teller
  balances, last wager ID, and last remit ID.

## Freeze and transfer

1. Close betting and wait for all submitted wagers/payouts to finish.
2. Stop `SmartWagers-Daphne`; confirm `/health/` is unreachable.
3. Copy `db.sqlite3`, `.env`, and `master_lock.state` to write-protected,
   timestamped storage.
4. Repair known SQLite integrity issues before transfer:
   ```cmd
   python manage.py repair_fight_status
   python manage.py repair_fight_status --apply
   python manage.py verify_database --strict
   ```
5. Run `deploy\9_migrate_sqlite_to_postgres.bat`.
6. Keep the generated source/target manifests, JSON fixture, frozen SQLite
   database, and PostgreSQL custom-format dump together.
7. If any strict integrity check fails, do not start Daphne. Correct the source
   data deliberately, make a new frozen copy, and restart the procedure.

## Acceptance checks

Run:

```cmd
python manage.py check
python manage.py check_database
python manage.py showmigrations
python manage.py verify_database --strict
```

Then start Daphne and verify:

- `/health/` returns HTTP 200 and logs contain no database/Redis errors.
- Admin, teller, and display users can log in with existing credentials.
- Admin, teller, and display WebSockets connect and receive the same fight
  number, pot values, overall status, and side statuses.
- Open and close a test fight; teller close/reopen modals update immediately.
- Two tellers submit simultaneous MERON/WALA test wagers. IDs are unique,
  totals reconcile, and both wager receipts print.
- Declare a test winner and pay the winning ticket at its original teller.
  Exactly one payout ledger entry is created and the payout receipt prints.
- Reprint the wager and payout receipts without creating another financial row.
- Cancel an eligible test wager and confirm totals/balance adjust once.
- Complete teller borrow/remit and admin bank collect/remit test transactions.
- Confirm the active event, fight status, users/groups, last production IDs,
  original teller balances, and pre-cutover financial totals match the recorded
  values.

Remove or clearly label all smoke-test records before reopening betting.

## Backup retention

- Keep the frozen pre-cutover SQLite database, `.env`, master-lock state, source
  manifest, and first accepted PostgreSQL dump for **at least 30 days**.
- Keep daily PostgreSQL dumps for **30 days** and event-closing dumps for
  **90 days**, with at least one copy off the application server.
- Never store `.env` in source control. Backup storage containing `.env` must be
  access-controlled and encrypted.
- Test a restore into a separate database before cutover and at least monthly.

## Rollback

If acceptance fails before production writes are allowed:

1. Stop `SmartWagers-Daphne`.
2. Restore the frozen `db.sqlite3`, pre-cutover `.env`, and master-lock state.
3. Use the prior application version/configuration that explicitly enables the
   SQLite development/recovery database.
4. Start Daphne and repeat health, login, WebSocket, balance, and print checks.

If PostgreSQL has accepted any real post-cutover writes, do **not** return to
the frozen SQLite file and do not merge databases manually. Stop service,
preserve the failed database, and restore the latest accepted PostgreSQL dump
with `deploy\8_restore_postgres.bat`.

## Sign-off

- Operator: ____________________  Time: ____________________
- Verifier: ____________________  Time: ____________________
- Source manifest retained: yes / no
- PostgreSQL restore tested: yes / no
- All acceptance checks passed: yes / no
- Betting reopened at: ____________________
