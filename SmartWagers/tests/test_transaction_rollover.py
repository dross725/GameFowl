"""Tests for generation-aware transaction ID rollover and archival."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import IntegrityError
from django.utils.timezone import now

from SmartWagers import reporting, services, transaction_ids
from SmartWagers.models import (
    AdminBankTransaction,
    ArchivedWager,
    Event,
    Fight_Results,
    Fight_Status,
    Settings,
    TellerCloseOut,
    TellerTransaction,
    Totals,
    TransactionSequence,
    Wagers,
)
from SmartWagers.transaction_ids import RolloverBlockedError


def _seed_sequences():
    for key in (
        TransactionSequence.WAGER,
        TransactionSequence.TELLER,
        TransactionSequence.ADMIN_BANK,
    ):
        TransactionSequence.objects.update_or_create(
            key=key, defaults={'value': 0, 'cycle': 0},
        )


def _ended_event(name='Old Event', *, hours_ago=48):
    ended_at = now() - timedelta(hours=hours_ago)
    started_at = ended_at - timedelta(hours=10)
    return Event.objects.create(
        name=name,
        is_active=False,
        started_at=started_at,
        ended_at=ended_at,
    )


def _open_event_setup():
    Settings.objects.create(plasada=0.05)
    Fight_Status.objects.create(
        fightnum=1, overall_status='OPEN',
        meron_status='OPEN', wala_status='OPEN',
    )
    Totals.objects.create(
        fightnum=1, mtotal=0, wtotal=0, mpayout=0, wpayout=0, totalpot=0,
    )
    Wagers.objects.create(
        fightnum=1, side='START', wager=0, cashier='System', registered=True,
    )


def _settled_losing_wager(event, teller_username='testteller', txn_id='000000'):
    wager = Wagers.objects.create(
        fightnum=1,
        side='MERON',
        wager=100.0,
        cashier=teller_username,
        registered=True,
        cancelled=False,
        cashed_out=False,
    )
    Wagers.objects.filter(pk=wager.pk).update(
        transactionid=txn_id,
        sequence_cycle=0,
        created_at=event.started_at + timedelta(hours=1),
    )
    Fight_Results.objects.create(
        fightnum=1,
        side='WALA',
        mtotal=0,
        wtotal=100,
        mpayout=0,
        wpayout=200,
        totalpot=100,
        odds='2:1',
        event=event,
    )
    return Wagers.objects.get(pk=wager.pk)


@pytest.mark.django_db
class TestSequenceBoundaries:
    def setup_method(self):
        _seed_sequences()

    def test_wager_999999_rolls_to_000000(self, teller_user):
        TransactionSequence.objects.filter(key=TransactionSequence.WAGER).update(
            value=999999, cycle=0,
        )
        wager = Wagers.objects.create(
            fightnum=1, side='MERON', wager=50.0,
            cashier=str(teller_user), registered=True,
        )
        assert wager.transactionid == '000000'
        assert wager.sequence_cycle == 1

    def test_teller_999999_rolls_to_r000000(self, teller_user):
        TransactionSequence.objects.filter(key=TransactionSequence.TELLER).update(
            value=999999, cycle=0,
        )
        txn = TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.REMIT,
            amount=25.0,
        )
        assert txn.transaction_id == 'R000000'
        assert txn.sequence_cycle == 1

    def test_admin_bank_999999_rolls_to_b000000(self, admin_user, active_event):
        TransactionSequence.objects.filter(key=TransactionSequence.ADMIN_BANK).update(
            value=999999, cycle=0,
        )
        txn = AdminBankTransaction.objects.create(
            event=active_event,
            admin=admin_user,
            transaction_type=AdminBankTransaction.BORROW,
            amount=1000.0,
        )
        assert txn.transaction_id == 'B000000'
        assert txn.sequence_cycle == 1

    def test_namespaces_roll_independently(self, teller_user):
        TransactionSequence.objects.filter(key=TransactionSequence.WAGER).update(
            value=999999, cycle=0,
        )
        TransactionSequence.objects.filter(key=TransactionSequence.TELLER).update(
            value=10, cycle=0,
        )

        wager = Wagers.objects.create(
            fightnum=1, side='MERON', wager=10.0,
            cashier='testteller', registered=True,
        )
        txn = TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.REMIT,
            amount=10.0,
        )

        assert wager.transactionid == '000000'
        assert txn.transaction_id == 'R000011'


@pytest.mark.django_db
class TestConflictArchival:
    def setup_method(self):
        _seed_sequences()
        _open_event_setup()

    def test_settled_wager_is_archived_on_reuse(self, teller_user, active_event):
        old_event = _ended_event()
        _settled_losing_wager(old_event, teller_username=str(teller_user))

        TransactionSequence.objects.filter(key=TransactionSequence.WAGER).update(
            value=999999, cycle=0,
        )
        new_wager = Wagers.objects.create(
            fightnum=1,
            side='WALA',
            wager=25.0,
            cashier=str(teller_user),
            registered=True,
        )

        assert new_wager.transactionid == '000000'
        assert new_wager.sequence_cycle == 1
        assert not Wagers.objects.filter(transactionid='000000', sequence_cycle=0).exists()
        archived = ArchivedWager.objects.get(transactionid='000000', sequence_cycle=0)
        assert archived.source_pk is not None
        assert archived.event == old_event

    def test_unpaid_winner_blocks_wager_rollover(self, teller_user):
        old_event = _ended_event()
        wager = Wagers.objects.create(
            fightnum=1,
            side='MERON',
            wager=100.0,
            cashier=str(teller_user),
            registered=True,
        )
        Wagers.objects.filter(pk=wager.pk).update(
            transactionid='000000',
            sequence_cycle=0,
            created_at=old_event.started_at + timedelta(hours=1),
        )
        Fight_Results.objects.create(
            fightnum=1,
            side='MERON',
            mtotal=100,
            wtotal=0,
            mpayout=200,
            wpayout=0,
            totalpot=100,
            odds='2:1',
            event=old_event,
        )
        TransactionSequence.objects.filter(key=TransactionSequence.WAGER).update(
            value=999999, cycle=0,
        )

        with pytest.raises(RolloverBlockedError):
            Wagers.objects.create(
                fightnum=1,
                side='WALA',
                wager=50.0,
                cashier=str(teller_user),
                registered=True,
            )

    def test_current_event_wager_blocks_rollover(self, teller_user, active_event):
        wager = Wagers.objects.create(
            fightnum=1,
            side='MERON',
            wager=100.0,
            cashier=str(teller_user),
            registered=True,
            cashed_out=True,
        )
        Wagers.objects.filter(pk=wager.pk).update(transactionid='000000', sequence_cycle=0)
        TransactionSequence.objects.filter(key=TransactionSequence.WAGER).update(
            value=999999, cycle=0,
        )

        with pytest.raises(RolloverBlockedError):
            Wagers.objects.create(
                fightnum=1,
                side='WALA',
                wager=50.0,
                cashier=str(teller_user),
                registered=True,
            )

    def test_admin_bank_id_is_stored_and_preserved(self, admin_user, active_event):
        txn = AdminBankTransaction.objects.create(
            event=active_event,
            admin=admin_user,
            transaction_type=AdminBankTransaction.BORROW,
            amount=5000.0,
        )
        stored_id = txn.transaction_id
        assert stored_id.startswith('B')
        assert len(stored_id) == 7

        txn.amount = 5001.0
        txn.save(update_fields=['amount'])
        txn.refresh_from_db()
        assert txn.transaction_id == stored_id

    def test_close_out_link_survives_teller_archival(
        self, teller_user, active_event,
    ):
        old_event = _ended_event()
        old_txn = TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.REMIT,
            amount=100.0,
            received=True,
        )
        TellerTransaction.objects.filter(pk=old_txn.pk).update(
            transaction_id='R000000',
            sequence_cycle=0,
            created_at=old_event.started_at + timedelta(hours=1),
        )
        old_txn = TellerTransaction.objects.get(pk=old_txn.pk)
        close_out = TellerCloseOut.objects.create(
            user=teller_user,
            event=old_event,
            fightnum=1,
            expected_cash_on_hand=0.0,
            remit_transaction=old_txn,
        )

        TransactionSequence.objects.filter(key=TransactionSequence.TELLER).update(
            value=999999, cycle=0,
        )
        TellerTransaction.objects.create(
            user=teller_user,
            transaction_type=TellerTransaction.REMIT,
            amount=50.0,
        )

        close_out.refresh_from_db()
        assert close_out.remit_transaction is None
        assert close_out.archived_remit_transaction is not None
        assert close_out.archived_remit_transaction.transaction_id == 'R000000'


@pytest.mark.django_db
class TestOperationalVsReporting:
    def setup_method(self):
        _seed_sequences()
        _open_event_setup()

    def test_archived_wager_missing_from_operational_lookup(self, teller_user, active_event):
        old_event = _ended_event()
        _settled_losing_wager(old_event, teller_username=str(teller_user))
        TransactionSequence.objects.filter(key=TransactionSequence.WAGER).update(
            value=999999, cycle=0,
        )
        Wagers.objects.create(
            fightnum=1, side='WALA', wager=10.0,
            cashier=str(teller_user), registered=True,
        )

        assert ArchivedWager.objects.filter(
            transactionid='000000', sequence_cycle=0,
        ).exists()
        assert services.payout_old_ticket(
            old_event, str(teller_user), '000000',
        )['error'] == 'notfound'
        assert Wagers.objects.get(transactionid='000000').sequence_cycle == 1

    def test_historical_event_report_includes_archived_wagers(self, teller_user, active_event):
        old_event = _ended_event()
        _settled_losing_wager(old_event, teller_username=str(teller_user))
        active_before = reporting.aggregate_wagers(
            old_event, include_archived=False,
        )['total']
        TransactionSequence.objects.filter(key=TransactionSequence.WAGER).update(
            value=999999, cycle=0,
        )
        Wagers.objects.create(
            fightnum=1, side='WALA', wager=10.0,
            cashier=str(teller_user), registered=True,
        )
        active_after = reporting.aggregate_wagers(
            old_event, include_archived=False,
        )['total']
        combined_after = reporting.aggregate_wagers(
            old_event, include_archived=True,
        )['total']

        assert active_after == 0.0
        assert combined_after == pytest.approx(active_before)


@pytest.mark.django_db
class TestAllocatorRollback:
    def setup_method(self):
        _seed_sequences()
        _open_event_setup()

    def test_forced_insert_failure_restores_sequence(self, teller_user, active_event, monkeypatch):
        old_event = _ended_event()
        _settled_losing_wager(old_event, teller_username=str(teller_user))
        TransactionSequence.objects.filter(key=TransactionSequence.WAGER).update(
            value=999999, cycle=0,
        )

        original_save = Wagers.save

        def flaky_save(self, *args, **kwargs):
            if self.pk is None and self.transactionid == '000000':
                raise IntegrityError('forced failure')
            return original_save(self, *args, **kwargs)

        monkeypatch.setattr(Wagers, 'save', flaky_save)

        with pytest.raises(IntegrityError):
            Wagers.objects.create(
                fightnum=1, side='WALA', wager=25.0,
                cashier=str(teller_user), registered=True,
            )

        sequence = TransactionSequence.objects.get(key=TransactionSequence.WAGER)
        assert sequence.value == 999999
        assert sequence.cycle == 0
        assert Wagers.objects.filter(transactionid='000000').exists()
