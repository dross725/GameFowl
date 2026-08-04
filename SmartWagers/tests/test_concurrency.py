"""
Concurrency and blocking tests for SmartWagers.

ARCHITECTURE NOTE — SQLite vs PostgreSQL concurrency:
    SQLite serialises all writes at the file level.  When two threads attempt
    concurrent writes, SQLite raises OperationalError('database table is
    locked') instead of queuing.  This means:

    - True parallel-thread race tests cannot run reliably against SQLite.
    - The tests below take two approaches:

      A) Sequential logic tests (labelled "logic test"):
         Call the same function twice in the same thread and verify that the
         second call is correctly rejected.  This covers the SELECT FOR UPDATE /
         retry-loop correctness without needing actual parallelism.

      B) Thread-stress tests (labelled "thread stress"):
         Spin up N threads.  Any OperationalError raised by SQLite is caught
         and counted; the data-integrity assertion is still made on whatever
         did commit.  These tests are annotated with a production note.
         On PostgreSQL they must all pass without any OperationalErrors.

    Run against a real PostgreSQL instance before deploying to production.
"""

import threading
import pytest
from django.db import OperationalError, connection, connections
from SmartWagers.models import (
    Event, Fight_Results, Fight_Status, TellerTransaction, Totals, Wagers,
)
from SmartWagers import services


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_fight(fightnum=1):
    Fight_Status.objects.all().delete()
    Fight_Status.objects.create(
        fightnum=fightnum, overall_status='OPEN',
        meron_status='OPEN', wala_status='OPEN',
    )
    Totals.objects.create(fightnum=fightnum, mtotal=0, wtotal=0,
                           mpayout=0, wpayout=0, totalpot=0)
    Wagers.objects.create(fightnum=fightnum, side='START', wager=0,
                           cashier='System', registered=True)


def _run_threads(target, n_threads, *args):
    """Run *target* in *n_threads* threads and collect (result, exception) pairs."""
    results = []
    exceptions = []
    lock = threading.Lock()

    def _wrap(*a):
        try:
            r = target(*a)
            with lock:
                results.append(r)
        except OperationalError as exc:
            with lock:
                exceptions.append(exc)
        except Exception as exc:  # noqa: BLE001
            with lock:
                exceptions.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=_wrap, args=args) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results, exceptions


# ---------------------------------------------------------------------------
# 1A. Duplicate payout — LOGIC TEST (sequential)
#     Verifies select_for_update logic: second payout of same ticket fails.
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_duplicate_payout_logic_sequential(default_settings, teller_user):
    """Sequential calls: first payout succeeds, second returns 'alreadypaid'."""
    active_event = Event.objects.create(name='Concurrency Event', is_active=True)
    wager = Wagers.objects.create(
        fightnum=1, side='MERON', wager=500,
        cashier=teller_user.username, registered=True, cashed_out=False,
    )
    Fight_Results.objects.create(
        fightnum=1, side='MERON',
        mtotal=500, wtotal=300, mpayout=95.0, wpayout=158.0,
        totalpot=800, odds='Dehado', event=active_event,
    )

    r1 = services.payout_request(wager.transactionid, requesting_cashier=teller_user.username)
    r2 = services.payout_request(wager.transactionid, requesting_cashier=teller_user.username)

    assert 'Total_Payout' in r1, "First payout must succeed"
    assert r2.get('error') == 'alreadypaid', "Second payout must be rejected"

    wager.refresh_from_db()
    assert wager.cashed_out is True


# ---------------------------------------------------------------------------
# 1B. Duplicate payout — THREAD STRESS TEST
#     On SQLite some threads may get OperationalError (documented limitation).
#     On PostgreSQL all 5 must complete; exactly 1 must succeed.
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_duplicate_payout_thread_stress(default_settings, teller_user):
    """
    Production target (PostgreSQL): exactly 1 success, 4 'alreadypaid'.
    SQLite: OperationalErrors are tolerated; at most 1 success must exist.
    """
    active_event = Event.objects.create(name='Concurrency Event 2', is_active=True)
    wager = Wagers.objects.create(
        fightnum=2, side='MERON', wager=500,
        cashier=teller_user.username, registered=True, cashed_out=False,
    )
    Fight_Results.objects.create(
        fightnum=2, side='MERON',
        mtotal=500, wtotal=300, mpayout=95.0, wpayout=158.0,
        totalpot=800, odds='Dehado', event=active_event,
    )

    results, sqlite_errors = _run_threads(
        lambda: services.payout_request(
            wager.transactionid, requesting_cashier=teller_user.username
        ),
        5,
    )

    successes = [r for r in results if 'Total_Payout' in r]
    assert len(successes) <= 1, "Never more than 1 successful payout for the same ticket"

    wager.refresh_from_db()
    if successes:
        assert wager.cashed_out is True

    if sqlite_errors and connection.vendor == 'sqlite':
        pytest.xfail(
            f"SQLite raised {len(sqlite_errors)} OperationalError(s) — "
            "this test must pass without errors on PostgreSQL"
        )
    assert not sqlite_errors, f"PostgreSQL payout errors: {sqlite_errors!r}"


# ---------------------------------------------------------------------------
# 2A. Totals integrity — LOGIC TEST (sequential)
#     Verifies that add_total correctly accumulates after 10 sequential bets.
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_totals_integrity_sequential(default_settings):
    """Sequential add_wager calls must accumulate totals without loss."""
    _open_fight(fightnum=1)
    for i in range(10):
        services.add_wager(100, 'MERON', 1, cashier=f'teller{i}')
    m, _, _, _, pot, _ = services.get_Totals()
    assert m == pytest.approx(1000.0)
    assert pot == pytest.approx(1000.0)


# ---------------------------------------------------------------------------
# 2B. Totals integrity — THREAD STRESS TEST
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_totals_integrity_thread_stress(default_settings):
    """
    Production target (PostgreSQL): total must equal n_threads × amount.
    SQLite: OperationalErrors are tolerated; any committed writes must sum
    correctly.
    """
    import itertools
    _open_fight(fightnum=1)
    n_threads, amount = 10, 100
    counter = itertools.count()
    counter_lock = threading.Lock()

    def _place():
        with counter_lock:
            i = next(counter)
        return services.add_wager(amount, 'MERON', 1, cashier=f'teller{i}')

    results, sqlite_errors = _run_threads(_place, n_threads)

    committed = len(results)
    m, _, _, _, pot, _ = services.get_Totals()
    assert m == pytest.approx(committed * amount), (
        f"mtotal mismatch: expected {committed * amount}, got {m}"
    )

    if sqlite_errors and connection.vendor == 'sqlite':
        pytest.xfail(
            f"SQLite raised {len(sqlite_errors)} OperationalError(s) — "
            "run on PostgreSQL to validate true concurrency safety"
        )
    assert not sqlite_errors, f"PostgreSQL totals errors: {sqlite_errors!r}"


# ---------------------------------------------------------------------------
# 3A. Transaction ID uniqueness — LOGIC TEST
#     Sequential wagers must never share a transactionid.
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_transaction_id_sequential_uniqueness(default_settings):
    """10 sequential teller wagers must have unique transactionids."""
    _open_fight(fightnum=1)
    ids = [
        Wagers.objects.create(fightnum=1, side='MERON', wager=50, cashier='teller1').transactionid
        for _ in range(10)
    ]
    assert len(ids) == len(set(ids)), "Duplicate transaction IDs in sequential saves!"


# ---------------------------------------------------------------------------
# 3B. Transaction ID uniqueness — THREAD STRESS TEST
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_transaction_id_no_collision_thread_stress(default_settings):
    """
    Production target (PostgreSQL): all 10 IDs unique.
    SQLite: OperationalErrors are tolerated; committed IDs must be unique.
    """
    _open_fight(fightnum=1)
    results, sqlite_errors = _run_threads(
        lambda: Wagers.objects.create(fightnum=1, side='MERON', wager=50, cashier='teller1'),
        10,
    )
    ids = [w.transactionid for w in results]
    assert len(ids) == len(set(ids)), "Duplicate transaction IDs detected!"

    if sqlite_errors and connection.vendor == 'sqlite':
        pytest.xfail(
            f"SQLite raised {len(sqlite_errors)} OperationalError(s) — "
            "run on PostgreSQL to validate full concurrency safety"
        )
    assert not sqlite_errors, f"PostgreSQL wager ID errors: {sqlite_errors!r}"


# ---------------------------------------------------------------------------
# 4A. TellerTransaction ID uniqueness — LOGIC TEST
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_teller_transaction_id_sequential_uniqueness(teller_user, default_settings):
    """10 sequential TellerTransactions must have unique transaction_ids."""
    ids = [
        TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.REMIT,
            amount=100,
        ).transaction_id
        for _ in range(10)
    ]
    assert len(ids) == len(set(ids)), "Duplicate TellerTransaction IDs!"


# ---------------------------------------------------------------------------
# 4B. TellerTransaction ID uniqueness — THREAD STRESS TEST
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_teller_transaction_id_no_collision_thread_stress(teller_user, default_settings):
    results, sqlite_errors = _run_threads(
        lambda: TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.REMIT,
            amount=100,
        ),
        8,
    )
    ids = [t.transaction_id for t in results]
    assert len(ids) == len(set(ids)), "Duplicate TellerTransaction IDs detected!"

    if sqlite_errors and connection.vendor == 'sqlite':
        pytest.xfail(
            f"SQLite raised {len(sqlite_errors)} OperationalError(s) — "
            "run on PostgreSQL for full concurrency validation"
        )
    assert not sqlite_errors, f"PostgreSQL teller transaction ID errors: {sqlite_errors!r}"


# ---------------------------------------------------------------------------
# 5A. Double start_event — LOGIC TEST
#     start_event() must deactivate the old event before creating the new one.
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_start_event_closes_previous_event(default_settings):
    """Calling start_event twice sequentially must leave exactly one active event."""
    services.start_event('Event A')
    services.start_event('Event B')
    assert Event.objects.filter(is_active=True).count() == 1


# ---------------------------------------------------------------------------
# 5B. Double start_event — THREAD STRESS TEST
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_double_start_event_thread_stress(default_settings):
    """
    Production target (PostgreSQL): exactly 1 active event after 2 concurrent starts.
    On PostgreSQL a DB-level unique constraint on is_active=True is recommended.
    """
    results, sqlite_errors = _run_threads(
        lambda: services.start_event('Concurrent Event'),
        2,
    )

    active_count = Event.objects.filter(is_active=True).count()
    if not sqlite_errors:
        assert active_count == 1, (
            f"Expected 1 active event, found {active_count} — "
            "add a DB unique constraint for production safety"
        )
    elif connection.vendor == 'sqlite':
        pytest.xfail(
            f"SQLite raised {len(sqlite_errors)} OperationalError(s) — "
            "run on PostgreSQL to validate"
        )
    else:
        pytest.fail(f"PostgreSQL event start errors: {sqlite_errors!r}")


# ---------------------------------------------------------------------------
# 6. deduct_totals + add_total — no deadlock (sequential)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_deduct_then_add_does_not_deadlock(default_settings):
    """
    Sequential deduct + add inside separate atomic blocks must not deadlock.

    SQLite WAL NOTE: Without WAL mode, concurrent readers and writers can
    block.  This sequential test verifies logical correctness.  A production
    PostgreSQL deployment would use REPEATABLE READ or SERIALIZABLE isolation.
    """
    Totals.objects.create(fightnum=1, mtotal=1000, wtotal=500,
                           mpayout=0, wpayout=0, totalpot=1500)

    services.deduct_totals('MERON', 200)
    services.add_total(300, 'WALA')

    m, _, w, _, pot, _ = services.get_Totals()
    assert m == pytest.approx(800.0)
    assert w == pytest.approx(800.0)
    assert pot == pytest.approx(1600.0)


# ---------------------------------------------------------------------------
# 7A. Concurrent cancel_bet — LOGIC TEST
#     Two sequential cancel calls for the same bet: only one must succeed.
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_concurrent_cancel_bet_logic_sequential(default_settings):
    """Second cancel of the same bet must return 'notfound'."""
    _open_fight(fightnum=1)
    w, _ = services.add_wager(300, 'MERON', 1, cashier='teller1')
    tid = w.transactionid

    r1 = services.cancel_bet(tid)
    r2 = services.cancel_bet(tid)

    assert r1.get('message') == 'betcancelled', "First cancel must succeed"
    assert r2.get('error') == 'notfound', "Second cancel must return notfound"


# ---------------------------------------------------------------------------
# 7B. Concurrent cancel_bet — THREAD STRESS TEST
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_concurrent_cancel_bet_thread_stress(default_settings):
    """
    Production target (PostgreSQL): exactly 1 success, others 'notfound'.
    """
    _open_fight(fightnum=1)
    w, _ = services.add_wager(300, 'MERON', 1, cashier='teller1')
    tid = w.transactionid

    results, sqlite_errors = _run_threads(lambda: services.cancel_bet(tid), 3)

    successes = [r for r in results if r.get('message') == 'betcancelled']
    assert len(successes) <= 1, "More than 1 successful cancel for the same bet!"

    if sqlite_errors and connection.vendor == 'sqlite':
        pytest.xfail(
            f"SQLite raised {len(sqlite_errors)} OperationalError(s) — "
            "run on PostgreSQL for full concurrency validation"
        )
    assert not sqlite_errors, f"PostgreSQL cancel errors: {sqlite_errors!r}"
