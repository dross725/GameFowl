"""
Performance tests for SmartWagers service functions.

Each test measures wall-clock time for a realistic workload against the
in-memory SQLite test database and asserts a soft threshold.

Thresholds are intentionally generous to avoid flaky CI failures on slow
machines while still catching catastrophically slow regressions.

To get detailed timing output run:
    pytest SmartWagers/tests/test_performance.py -v -s
"""

import time
import pytest
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
    Totals.objects.create(fightnum=fightnum, mtotal=0, wtotal=0, mpayout=0, wpayout=0, totalpot=0)
    Wagers.objects.create(fightnum=fightnum, side='START', wager=0,
                           cashier='System', registered=True)


def _elapsed(func):
    """Return (result, elapsed_seconds) for a callable."""
    start = time.perf_counter()
    result = func()
    elapsed = time.perf_counter() - start
    return result, elapsed


# ---------------------------------------------------------------------------
# add_wager — 100 sequential wagers
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_add_wager_100_sequential(default_settings):
    """100 sequential add_wager calls must complete in under 5 seconds on
    the SQLite test DB. Threshold is intentionally high to avoid flaky CI."""
    _open_fight()
    sides = ['MERON', 'WALA']

    def run():
        for i in range(100):
            services.add_wager(100, sides[i % 2], 1, cashier=f'teller{i}')

    _, elapsed = _elapsed(run)
    print(f"\nadd_wager x100: {elapsed:.3f}s")
    assert elapsed < 5.0, f"add_wager x100 took {elapsed:.2f}s — exceeds 5s threshold"

    m, _, w, _, pot, _ = services.get_Totals()
    assert pot == pytest.approx(10_000.0)


# ---------------------------------------------------------------------------
# get_Totals — 1000 reads
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_get_totals_1000_reads(default_settings):
    """1000 sequential get_Totals() calls must complete in under 1 second."""
    Totals.objects.create(fightnum=1, mtotal=500, wtotal=300, mpayout=95, wpayout=158, totalpot=800)

    def run():
        for _ in range(1000):
            services.get_Totals()

    _, elapsed = _elapsed(run)
    print(f"\nget_Totals x1000: {elapsed:.3f}s")
    assert elapsed < 1.0, f"get_Totals x1000 took {elapsed:.2f}s — exceeds 1s threshold"


# ---------------------------------------------------------------------------
# compute_payout — 10,000 pure-logic calls (no DB)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_compute_payout_10000_calls(default_settings):
    """10,000 compute_payout() calls (1 DB hit for plasada, rest cached) must
    complete in under 0.5 seconds."""
    # Warm up the settings cache with one DB hit
    services.get_comm_val()

    def run():
        for i in range(10_000):
            services.compute_payout(500 + i % 100, 300 + i % 50, 800 + i % 150)

    _, elapsed = _elapsed(run)
    print(f"\ncompute_payout x10000: {elapsed:.3f}s")
    # Commission is cached and invalidated whenever Settings changes.
    assert elapsed < 0.5, f"compute_payout x10000 took {elapsed:.2f}s — exceeds 0.5s threshold"


# ---------------------------------------------------------------------------
# payout_request — 50 sequential successful payouts
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_payout_request_50_sequential(default_settings, teller_user):
    """50 successful payout_request() calls must complete in under 5 seconds."""
    active_event = Event.objects.create(name='Perf Event', is_active=True)

    # Create 50 registered MERON wagers
    wager_ids = []
    for i in range(50):
        w = Wagers.objects.create(
            fightnum=i + 1, side='MERON', wager=100,
            cashier=teller_user.username, registered=True, cashed_out=False,
        )
        Fight_Results.objects.create(
            fightnum=i + 1, side='MERON',
            mtotal=500, wtotal=300,
            mpayout=95.0, wpayout=158.0,
            totalpot=800, odds='Dehado',
            event=active_event,
        )
        wager_ids.append(w.transactionid)

    def run():
        for tid in wager_ids:
            services.payout_request(tid, requesting_cashier=teller_user.username)

    _, elapsed = _elapsed(run)
    print(f"\npayout_request x50: {elapsed:.3f}s")
    assert elapsed < 5.0, f"payout_request x50 took {elapsed:.2f}s — exceeds 5s threshold"

    # All wagers should be marked cashed out
    uncashed = Wagers.objects.filter(
        transactionid__in=wager_ids, cashed_out=False
    ).count()
    assert uncashed == 0


# ---------------------------------------------------------------------------
# _get_teller_outstanding_balance with 500 transactions
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_teller_balance_with_500_transactions(default_settings, teller_user):
    """Balance calculation across 500 transactions must complete in under 1 second."""
    active_event = Event.objects.create(name='Perf Event', is_active=True)

    # 200 bets at 100 each = 20,000
    for i in range(200):
        Wagers.objects.create(
            fightnum=1, side='MERON', wager=100,
            cashier=teller_user.username, registered=True,
        )
    # 150 REMIT at 50 each = 7,500
    for _ in range(150):
        TellerTransaction.objects.create(
            user=teller_user, transaction_type=TellerTransaction.REMIT, amount=50,
        )
    # 100 COLLECT at 50 each = 5,000
    for _ in range(100):
        TellerTransaction.objects.create(
            user=teller_user, transaction_type=TellerTransaction.COLLECT, amount=50,
        )
    # 50 PAYOUT at 80 each = 4,000
    for _ in range(50):
        TellerTransaction.objects.create(
            user=teller_user, transaction_type=TellerTransaction.PAYOUT, amount=80,
        )

    def run():
        return services._get_teller_outstanding_balance(teller_user, event=active_event)

    balance, elapsed = _elapsed(run)
    print(f"\nbalance x500 txns: {elapsed:.3f}s, balance={balance:.2f}")
    assert elapsed < 1.0, f"balance calc took {elapsed:.2f}s — exceeds 1s threshold"

    # 20,000 - 7,500 + 5,000 - 4,000 = 13,500
    assert balance == pytest.approx(13_500.0, rel=1e-4)


# ---------------------------------------------------------------------------
# get_fightnum — 500 reads
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_get_fightnum_500_reads():
    """500 sequential get_fightnum() reads must complete in under 1 second."""
    Wagers.objects.create(fightnum=42, side='START', wager=0, cashier='System', registered=True)

    def run():
        for _ in range(500):
            services.get_fightnum()

    _, elapsed = _elapsed(run)
    print(f"\nget_fightnum x500: {elapsed:.3f}s")
    assert elapsed < 1.0, f"get_fightnum x500 took {elapsed:.2f}s — exceeds 1s threshold"
