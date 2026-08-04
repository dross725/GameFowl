"""
Tests for SmartWagers model layer.

Covers: Wagers transaction ID generation, Totals append-only behaviour,
Settings latest-row pattern, Fight_Status canonical ordering,
TellerTransaction sequential IDs and choices, TellerStatus OneToOne
enforcement, and Event is_active exclusivity.
"""

import pytest
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction

from SmartWagers.models import (
    AdminBankTransaction,
    Event,
    Fight_Status,
    Settings,
    TellerStatus,
    TellerTransaction,
    Totals,
    Wagers,
)


# ---------------------------------------------------------------------------
# Wagers
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestWagersModel:

    def test_teller_wager_id_format_six_digits(self):
        w = Wagers.objects.create(fightnum=1, side='MERON', wager=100, cashier='teller1')
        assert w.transactionid.isdigit(), "Teller transaction ID must be numeric"
        assert len(w.transactionid) == 6, "Teller transaction ID must be zero-padded to 6 digits"

    def test_teller_wager_id_starts_at_one_when_no_prior_wagers(self):
        w = Wagers.objects.create(fightnum=1, side='MERON', wager=50, cashier='teller1')
        assert w.transactionid == '000001'

    def test_teller_wager_id_increments_sequentially(self):
        w1 = Wagers.objects.create(fightnum=1, side='MERON', wager=100, cashier='teller1')
        w2 = Wagers.objects.create(fightnum=1, side='WALA',  wager=200, cashier='teller2')
        assert int(w2.transactionid) == int(w1.transactionid) + 1

    def test_system_wager_id_starts_with_s(self):
        w = Wagers.objects.create(fightnum=1, side='START', wager=0, cashier='System')
        assert w.transactionid.startswith('S'), "System wager ID must start with 'S'"
        assert len(w.transactionid) == 10, "System wager ID must be 10 chars (S + 9 hex)"

    def test_system_and_teller_ids_never_collide(self):
        sw = Wagers.objects.create(fightnum=1, side='START', wager=0, cashier='System')
        tw = Wagers.objects.create(fightnum=1, side='MERON', wager=100, cashier='teller1')
        assert sw.transactionid != tw.transactionid

    def test_cashed_out_defaults_false(self):
        w = Wagers.objects.create(fightnum=1, side='MERON', wager=100, cashier='teller1')
        assert w.cashed_out is False

    def test_registered_defaults_true(self):
        w = Wagers.objects.create(fightnum=1, side='MERON', wager=100, cashier='teller1')
        assert w.registered is True

    def test_wager_str_contains_key_fields(self):
        w = Wagers.objects.create(fightnum=2, side='WALA', wager=500, cashier='teller1')
        s = str(w)
        assert '2' in s
        assert 'WALA' in s
        assert '500' in s

    def test_unique_transactionid_constraint(self):
        """Updating a row to a duplicate transactionid must raise IntegrityError."""
        w1 = Wagers.objects.create(fightnum=1, side='MERON', wager=100, cashier='teller1')
        w2 = Wagers.objects.create(fightnum=1, side='WALA', wager=200, cashier='teller2')
        with pytest.raises(IntegrityError):
            # Bypass the custom save() by using a direct queryset update
            Wagers.objects.filter(pk=w2.pk).update(transactionid=w1.transactionid)

    def test_soft_cancelled_pending_id_is_not_reused(self):
        w1 = Wagers.objects.create(
            fightnum=1, side='MERON', wager=100, cashier='teller1',
            registered=False, cancelled=True,
        )
        w2 = Wagers.objects.create(
            fightnum=1, side='WALA', wager=200, cashier='teller2', registered=False,
        )
        assert int(w2.transactionid) > int(w1.transactionid)


# ---------------------------------------------------------------------------
# Totals — append-only behaviour
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestTotalsModel:

    def test_each_save_creates_new_row(self):
        Totals.objects.create(fightnum=1, mtotal=100, wtotal=200, mpayout=0, wpayout=0, totalpot=300)
        Totals.objects.create(fightnum=1, mtotal=150, wtotal=200, mpayout=0, wpayout=0, totalpot=350)
        assert Totals.objects.count() == 2

    def test_latest_row_is_authoritative(self):
        Totals.objects.create(fightnum=1, mtotal=100, wtotal=0, mpayout=0, wpayout=0, totalpot=100)
        Totals.objects.create(fightnum=1, mtotal=200, wtotal=0, mpayout=0, wpayout=0, totalpot=200)
        latest = Totals.objects.order_by('-id').first()
        assert latest.mtotal == 200

    def test_str_contains_fight_number(self):
        t = Totals.objects.create(fightnum=5, mtotal=0, wtotal=0, mpayout=0, wpayout=0, totalpot=0)
        assert '5' in str(t)


# ---------------------------------------------------------------------------
# Settings — latest-row pattern
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSettingsModel:

    def test_latest_by_id_returns_most_recent(self):
        Settings.objects.create(plasada=0.05)
        Settings.objects.create(plasada=0.10)
        latest = Settings.objects.order_by('-id').first()
        assert latest.plasada == 0.10

    def test_defaults_are_sane(self):
        s = Settings.objects.create(plasada=0.05)
        assert s.admin_initial_fund == 100000.0
        assert s.teller_initial_fund == 10000.0
        assert s.M_control_status == 'OPEN'
        assert s.W_control_status == 'OPEN'

    def test_str_contains_plasada(self):
        s = Settings.objects.create(plasada=0.07)
        assert '0.07' in str(s)


# ---------------------------------------------------------------------------
# AdminBankTransaction — bank ledger
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestAdminBankTransactionModel:

    def test_records_admin_event_type_and_amount(
            self, active_event, admin_user):
        txn = AdminBankTransaction.objects.create(
            event=active_event,
            admin=admin_user,
            transaction_type=AdminBankTransaction.BORROW,
            amount=25000,
        )
        assert txn.event == active_event
        assert txn.admin == admin_user
        assert txn.amount == 25000

    def test_amount_must_be_positive(self, active_event, admin_user):
        with pytest.raises(IntegrityError):
            AdminBankTransaction.objects.create(
                event=active_event,
                admin=admin_user,
                transaction_type=AdminBankTransaction.REMIT,
                amount=0,
            )


# ---------------------------------------------------------------------------
# Fight_Status — canonical ordering
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestFightStatusModel:

    def test_order_by_id_first_is_canonical_row(self):
        fs1 = Fight_Status.objects.create(fightnum=1, overall_status='OPEN',
                                          meron_status='OPEN', wala_status='OPEN')
        fs2 = Fight_Status.objects.create(fightnum=2, overall_status='CLOSED',
                                          meron_status='CLOSE', wala_status='CLOSE')
        canonical = Fight_Status.objects.order_by('id').first()
        assert canonical.pk == fs1.pk, "Canonical row must be the first created (lowest pk)"

    def test_str_contains_status(self):
        fs = Fight_Status.objects.create(fightnum=1, overall_status='OPEN',
                                         meron_status='OPEN', wala_status='OPEN')
        assert 'OPEN' in str(fs)


# ---------------------------------------------------------------------------
# TellerTransaction — sequential IDs and choices
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestTellerTransactionModel:

    def test_transaction_id_starts_with_r(self, teller_user):
        txn = TellerTransaction.objects.create(
            user=teller_user, transaction_type=TellerTransaction.REMIT, amount=500,
        )
        assert txn.transaction_id.startswith('R')

    def test_transaction_id_is_r_plus_six_digits(self, teller_user):
        txn = TellerTransaction.objects.create(
            user=teller_user, transaction_type=TellerTransaction.COLLECT, amount=1000,
        )
        assert len(txn.transaction_id) == 7
        assert txn.transaction_id[1:].isdigit()

    def test_transaction_ids_increment(self, teller_user):
        t1 = TellerTransaction.objects.create(
            user=teller_user, transaction_type=TellerTransaction.REMIT, amount=100,
        )
        t2 = TellerTransaction.objects.create(
            user=teller_user, transaction_type=TellerTransaction.REMIT, amount=200,
        )
        n1 = int(t1.transaction_id[1:])
        n2 = int(t2.transaction_id[1:])
        assert n2 == n1 + 1

    def test_valid_transaction_types(self, teller_user):
        for tt in (TellerTransaction.REMIT, TellerTransaction.COLLECT, TellerTransaction.PAYOUT):
            TellerTransaction.objects.create(user=teller_user, transaction_type=tt, amount=10)

    def test_str_contains_username_and_type(self, teller_user):
        txn = TellerTransaction.objects.create(
            user=teller_user, transaction_type=TellerTransaction.REMIT, amount=300,
        )
        s = str(txn)
        assert teller_user.username in s
        assert 'REMIT' in s


# ---------------------------------------------------------------------------
# TellerStatus — OneToOne enforcement
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestTellerStatusModel:

    def test_one_to_one_enforcement(self, teller_user):
        TellerStatus.objects.create(user=teller_user, is_online=True)
        with pytest.raises(IntegrityError):
            TellerStatus.objects.create(user=teller_user, is_online=False)

    def test_is_online_default_true(self, teller_user):
        ts = TellerStatus.objects.create(user=teller_user)
        assert ts.is_online is True

    def test_str_shows_online_status(self, teller_user):
        ts = TellerStatus.objects.create(user=teller_user, is_online=True)
        assert 'Online' in str(ts)
        ts.is_online = False
        ts.save()
        assert 'Offline' in str(ts)


# ---------------------------------------------------------------------------
# Event — is_active exclusivity (model-level)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestEventModel:

    def test_event_str_shows_name_and_status(self):
        ev = Event.objects.create(name='Derby Night', is_active=True)
        s = str(ev)
        assert 'Derby Night' in s
        assert 'Active' in s

    def test_ended_event_str_shows_ended(self):
        ev = Event.objects.create(name='Old Event', is_active=False)
        assert 'Ended' in str(ev)

    def test_database_rejects_multiple_active_events(self):
        Event.objects.create(name='Event A', is_active=True)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Event.objects.create(name='Event B', is_active=True)
        assert Event.objects.filter(is_active=True).count() == 1
