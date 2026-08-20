"""Generation-aware transaction ID allocation and conflict archival."""

from __future__ import annotations

from django.db import transaction as db_transaction
from django.db.models import Q

from SmartWagers.models import (
    AdminBankTransaction,
    ArchivedAdminBankTransaction,
    ArchivedTellerTransaction,
    ArchivedWager,
    Event,
    Fight_Results,
    TellerCloseOut,
    TellerTransaction,
    TransactionSequence,
    Wagers,
)

MAX_SEQUENCE_VALUE = 999999


class RolloverBlockedError(Exception):
    """Raised when a reused ID would overwrite a row that cannot be archived."""

    def __init__(self, namespace, transaction_id, reason):
        self.namespace = namespace
        self.transaction_id = transaction_id
        self.reason = reason
        super().__init__(
            f"{namespace} rollover blocked for {transaction_id}: {reason}"
        )


def format_wager_id(value):
    return str(value).zfill(6)


def format_teller_id(value):
    return f"R{format_wager_id(value)}"


def format_admin_bank_id(value):
    return f"B{format_wager_id(value)}"


def _next_sequence_state(sequence):
    if sequence.value >= MAX_SEQUENCE_VALUE:
        return 0, sequence.cycle + 1
    return sequence.value + 1, sequence.cycle


def resolve_event_for_timestamp(ts):
    return (
        Event.objects.filter(started_at__lte=ts)
        .filter(Q(ended_at__isnull=True) | Q(ended_at__gte=ts))
        .order_by('-started_at')
        .first()
    )


def is_current_event_scope(event):
    if event is None:
        return True
    from SmartWagers import services

    scope_event, _ = services.get_event_scope()
    if scope_event is None:
        return False
    return scope_event.pk == event.pk


def _lock_sequence(key):
    try:
        return TransactionSequence.objects.select_for_update().get(key=key)
    except TransactionSequence.DoesNotExist:
        TransactionSequence.objects.create(key=key, value=0, cycle=0)
        return TransactionSequence.objects.select_for_update().get(key=key)


def _advance_sequence(sequence, next_value, next_cycle):
    sequence.value = next_value
    sequence.cycle = next_cycle
    sequence.save(update_fields=['value', 'cycle'])


def _wager_can_archive(wager, event):
    if event is None:
        return False, 'unresolved_event'
    if is_current_event_scope(event):
        return False, 'current_event'

    if wager.cancelled or not wager.registered:
        return True, None
    if wager.cashed_out:
        return True, None

    fight_result = (
        Fight_Results.objects.filter(fightnum=wager.fightnum, event=event)
        .order_by('id')
        .first()
    )
    if fight_result is None:
        return False, 'unresolved_liability'

    result_side = fight_result.side.upper()
    if result_side in ('DRAW', 'CANCELLED'):
        return False, 'unresolved_liability'

    if result_side in ('MERON', 'WALA'):
        if wager.side.upper() == result_side:
            return False, 'unresolved_liability'
        return True, None

    return False, 'unresolved_liability'


def _archive_wager(wager):
    event = resolve_event_for_timestamp(wager.created_at)
    can_archive, reason = _wager_can_archive(wager, event)
    if not can_archive:
        raise RolloverBlockedError(
            TransactionSequence.WAGER, wager.transactionid, reason,
        )

    ArchivedWager.objects.create(
        source_pk=wager.pk,
        sequence_cycle=wager.sequence_cycle or 0,
        transactionid=wager.transactionid,
        fightnum=wager.fightnum,
        side=wager.side,
        wager=wager.wager,
        cashier=wager.cashier,
        created_at=wager.created_at,
        cashed_out=wager.cashed_out,
        registered=wager.registered,
        cancelled=wager.cancelled,
        client_request_id=wager.client_request_id,
        event=event,
    )
    wager.delete()


def _teller_can_archive(txn, event):
    if event is None:
        return False, 'unresolved_event'
    if is_current_event_scope(event):
        return False, 'current_event'
    return True, None


def _archive_teller_transaction(txn):
    event = resolve_event_for_timestamp(txn.created_at)
    can_archive, reason = _teller_can_archive(txn, event)
    if not can_archive:
        raise RolloverBlockedError(
            TransactionSequence.TELLER, txn.transaction_id, reason,
        )

    close_out = TellerCloseOut.objects.filter(remit_transaction=txn).first()
    ArchivedTellerTransaction.objects.create(
        source_pk=txn.pk,
        sequence_cycle=txn.sequence_cycle,
        transaction_id=txn.transaction_id,
        user=txn.user,
        transaction_type=txn.transaction_type,
        amount=txn.amount,
        received=txn.received,
        affects_admin_fund=txn.affects_admin_fund,
        created_at=txn.created_at,
        event=event,
        close_out=close_out,
    )
    txn.delete()


def _admin_bank_can_archive(txn):
    event = txn.event
    if is_current_event_scope(event):
        return False, 'current_event'
    if event.is_active:
        return False, 'current_event'
    return True, None


def _archive_admin_bank_transaction(txn):
    can_archive, reason = _admin_bank_can_archive(txn)
    if not can_archive:
        raise RolloverBlockedError(
            TransactionSequence.ADMIN_BANK, txn.transaction_id, reason,
        )

    ArchivedAdminBankTransaction.objects.create(
        source_pk=txn.pk,
        sequence_cycle=txn.sequence_cycle,
        transaction_id=txn.transaction_id,
        event=txn.event,
        admin=txn.admin,
        transaction_type=txn.transaction_type,
        amount=txn.amount,
        created_at=txn.created_at,
    )
    txn.delete()


def _resolve_wager_conflict(display_id):
    conflict = Wagers.objects.select_for_update().filter(
        transactionid=display_id,
    ).first()
    if conflict is None:
        return
    _archive_wager(conflict)


def _resolve_teller_conflict(display_id):
    conflict = TellerTransaction.objects.select_for_update().filter(
        transaction_id=display_id,
    ).first()
    if conflict is None:
        return
    _archive_teller_transaction(conflict)


def _resolve_admin_bank_conflict(display_id):
    conflict = AdminBankTransaction.objects.select_for_update().filter(
        transaction_id=display_id,
    ).first()
    if conflict is None:
        return
    _archive_admin_bank_transaction(conflict)


def assign_wager_identity(wager):
    """Assign the next wager transaction id inside the caller's atomic block."""
    sequence = _lock_sequence(TransactionSequence.WAGER)
    next_value, next_cycle = _next_sequence_state(sequence)
    display_id = format_wager_id(next_value)
    _resolve_wager_conflict(display_id)
    _advance_sequence(sequence, next_value, next_cycle)
    wager.transactionid = display_id
    wager.sequence_cycle = next_cycle


def assign_teller_identity(txn):
    """Assign the next teller transaction id inside the caller's atomic block."""
    sequence = _lock_sequence(TransactionSequence.TELLER)
    next_value, next_cycle = _next_sequence_state(sequence)
    display_id = format_teller_id(next_value)
    _resolve_teller_conflict(display_id)
    _advance_sequence(sequence, next_value, next_cycle)
    txn.transaction_id = display_id
    txn.sequence_cycle = next_cycle


def assign_admin_bank_identity(txn):
    """Assign the next admin-bank transaction id inside the caller's atomic block."""
    sequence = _lock_sequence(TransactionSequence.ADMIN_BANK)
    next_value, next_cycle = _next_sequence_state(sequence)
    display_id = format_admin_bank_id(next_value)
    _resolve_admin_bank_conflict(display_id)
    _advance_sequence(sequence, next_value, next_cycle)
    txn.transaction_id = display_id
    txn.sequence_cycle = next_cycle


def allocate_wager(**fields):
    wager = Wagers(**fields)
    with db_transaction.atomic():
        assign_wager_identity(wager)
        wager.save(force_insert=True)
    return wager


def allocate_teller_transaction(**fields):
    txn = TellerTransaction(**fields)
    with db_transaction.atomic():
        assign_teller_identity(txn)
        txn.save(force_insert=True)
    return txn


def allocate_admin_bank_transaction(**fields):
    txn = AdminBankTransaction(**fields)
    with db_transaction.atomic():
        assign_admin_bank_identity(txn)
        txn.save(force_insert=True)
    return txn
