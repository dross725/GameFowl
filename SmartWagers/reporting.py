"""Report-only helpers that combine active and archived transaction ledgers."""

from __future__ import annotations

from django.db.models import Count, Q, Sum

from SmartWagers.models import (
    AdminBankTransaction,
    ArchivedAdminBankTransaction,
    ArchivedTellerTransaction,
    ArchivedWager,
    TellerTransaction,
    Wagers,
)


def include_archived_for_event(event):
    """Historical closed events include archived rows in report totals."""
    return event is not None and event.ended_at is not None and not event.is_active


def teller_activity_started_at(user, event=None):
    """Earliest timestamp from which this teller account's rows count.

    Wagers are keyed by cashier username, so a recycled username would otherwise
    inherit another person's history.  Always bound activity to account creation,
    and to the event window when one is supplied.
    """
    joined = user.date_joined
    if event is None or event.started_at is None:
        return joined
    if event.started_at > joined:
        return event.started_at
    return joined


def filter_wagers_for_teller(qs, user, event=None, apply_end_bound=True):
    """Scope a wager queryset to one teller account (and optional event)."""
    qs = qs.filter(created_at__gte=teller_activity_started_at(user, event))
    if event is not None and apply_end_bound and event.ended_at:
        qs = qs.filter(created_at__lte=event.ended_at)
    return qs


def filter_transactions_for_teller(qs, user, event=None, apply_end_bound=True):
    """Scope a teller transaction queryset to one account (and optional event)."""
    qs = qs.filter(created_at__gte=teller_activity_started_at(user, event))
    if event is not None and apply_end_bound and event.ended_at:
        qs = qs.filter(created_at__lte=event.ended_at)
    return qs


def filter_active_wagers_by_event(qs, event):
    qs = qs.filter(created_at__gte=event.started_at)
    if event.ended_at:
        qs = qs.filter(created_at__lte=event.ended_at)
    return qs


def filter_active_teller_transactions_by_event(qs, event):
    qs = qs.filter(created_at__gte=event.started_at)
    if event.ended_at:
        qs = qs.filter(created_at__lte=event.ended_at)
    return qs


def active_wagers_for_event(event):
    return filter_active_wagers_by_event(Wagers.objects.all(), event)


def archived_wagers_for_event(event):
    return ArchivedWager.objects.filter(event=event)


def active_teller_transactions_for_event(event):
    return filter_active_teller_transactions_by_event(
        TellerTransaction.objects.all(), event,
    )


def archived_teller_transactions_for_event(event):
    return ArchivedTellerTransaction.objects.filter(event=event)


def active_admin_bank_for_event(event):
    return AdminBankTransaction.objects.filter(event=event)


def archived_admin_bank_for_event(event):
    return ArchivedAdminBankTransaction.objects.filter(event=event)


def wager_sources_for_event(event, *, include_archived=False):
    active = active_wagers_for_event(event)
    if not include_archived:
        return active, None
    return active, archived_wagers_for_event(event)


def teller_transaction_sources_for_event(event, *, include_archived=False):
    active = active_teller_transactions_for_event(event)
    if not include_archived:
        return active, None
    return active, archived_teller_transactions_for_event(event)


def admin_bank_sources_for_event(event, *, include_archived=False):
    active = active_admin_bank_for_event(event)
    if not include_archived:
        return active, None
    return active, archived_admin_bank_for_event(event)


def _sum_field(active_qs, archived_qs, field):
    active_total = active_qs.aggregate(total=Sum(field))['total'] or 0.0
    archived_total = 0.0
    if archived_qs is not None:
        archived_total = archived_qs.aggregate(total=Sum(field))['total'] or 0.0
    return float(active_total) + float(archived_total)


def _count_rows(active_qs, archived_qs):
    total = active_qs.count()
    if archived_qs is not None:
        total += archived_qs.count()
    return total


def aggregate_wagers(event, *, include_archived=False, filters=None):
    """Return count and wager sum for active (+ archived) rows in an event."""
    filters = filters or {}
    active_qs, archived_qs = wager_sources_for_event(
        event, include_archived=include_archived,
    )
    active_qs = active_qs.filter(**filters)
    if archived_qs is not None:
        archived_qs = archived_qs.filter(**filters)
    return {
        'count': _count_rows(active_qs, archived_qs),
        'total': _sum_field(active_qs, archived_qs, 'wager'),
    }


def aggregate_teller_transactions(event, *, include_archived=False, filters=None):
    filters = filters or {}
    active_qs, archived_qs = teller_transaction_sources_for_event(
        event, include_archived=include_archived,
    )
    active_qs = active_qs.filter(**filters)
    if archived_qs is not None:
        archived_qs = archived_qs.filter(**filters)
    return {
        'count': _count_rows(active_qs, archived_qs),
        'total': _sum_field(active_qs, archived_qs, 'amount'),
    }


def aggregate_admin_bank_transactions(event, *, include_archived=False, filters=None):
    filters = filters or {}
    active_qs, archived_qs = admin_bank_sources_for_event(
        event, include_archived=include_archived,
    )
    active_qs = active_qs.filter(**filters)
    if archived_qs is not None:
        archived_qs = archived_qs.filter(**filters)
    return {
        'count': _count_rows(active_qs, archived_qs),
        'total': _sum_field(active_qs, archived_qs, 'amount'),
    }


def combined_wager_aggregate(event, include_archived, active_qs, amount_field='wager'):
    """Apply the same filters to active and archived wagers and combine sums."""
    if not include_archived:
        return active_qs.aggregate(
            count=Count('id'),
            total=Sum(amount_field),
        )
    archived_qs = archived_wagers_for_event(event)
    active_agg = active_qs.aggregate(count=Count('id'), total=Sum(amount_field))
    archived_agg = archived_qs.filter(
        pk__in=_matching_archived_wager_pks(active_qs, event),
    ).aggregate(count=Count('id'), total=Sum(amount_field))
    return {
        'count': (active_agg['count'] or 0) + (archived_agg['count'] or 0),
        'total': float(active_agg['total'] or 0) + float(archived_agg['total'] or 0),
    }


def _matching_archived_wager_pks(active_qs, event):
    """Best-effort archived mirror when callers pass a pre-filtered active queryset."""
    del active_qs
    return archived_wagers_for_event(event).values_list('pk', flat=True)


def combined_teller_aggregate(event, include_archived, active_qs):
    if not include_archived:
        return active_qs.aggregate(count=Count('id'), total=Sum('amount'))
    archived_qs = archived_teller_transactions_for_event(event)
    active_agg = active_qs.aggregate(count=Count('id'), total=Sum('amount'))
    archived_filters = _archived_teller_mirror_filters(active_qs)
    archived_agg = archived_qs.filter(**archived_filters).aggregate(
        count=Count('id'),
        total=Sum('amount'),
    )
    return {
        'count': (active_agg['count'] or 0) + (archived_agg['count'] or 0),
        'total': float(active_agg['total'] or 0) + float(archived_agg['total'] or 0),
    }


def _archived_teller_mirror_filters(active_qs):
    """Extract simple equality filters that can be replayed on archive rows."""
    filters = {}
    for child in active_qs.query.where.children:
        if not hasattr(child, 'lhs') or not hasattr(child, 'rhs'):
            continue
        field_name = getattr(child.lhs, 'target', None)
        if field_name is None:
            continue
        name = field_name.name
        if name in {
            'user_id', 'transaction_type', 'received', 'affects_admin_fund',
        }:
            filters[name if name != 'user_id' else 'user_id'] = child.rhs
    return filters


def sum_wagers(active_qs, archived_qs, field='wager'):
    return _sum_field(active_qs, archived_qs, field)


def sum_teller_amounts(active_qs, archived_qs):
    return _sum_field(active_qs, archived_qs, 'amount')


def sum_admin_bank_amounts(active_qs, archived_qs):
    return _sum_field(active_qs, archived_qs, 'amount')


def filter_payable_unclaimed_wagers(event, payable_filter, include_archived=False):
    active_qs = active_wagers_for_event(event).filter(
        payable_filter,
        cashed_out=False,
        registered=True,
        cancelled=False,
    ).exclude(cashier='System')
    if not include_archived:
        return active_qs, None
    archived_qs = archived_wagers_for_event(event).filter(
        payable_filter,
        cashed_out=False,
        registered=True,
        cancelled=False,
    ).exclude(cashier='System')
    return active_qs, archived_qs


def unclaimed_wager_rows(event, payable_filter, include_archived=False):
    active_qs, archived_qs = filter_payable_unclaimed_wagers(
        event, payable_filter, include_archived=include_archived,
    )
    rows = list(
        active_qs.order_by('cashier', 'fightnum', 'transactionid').values(
            'transactionid', 'cashier', 'fightnum', 'side', 'wager',
        ),
    )
    if archived_qs is not None:
        rows.extend(
            archived_qs.order_by('cashier', 'fightnum', 'transactionid').values(
                'transactionid', 'cashier', 'fightnum', 'side', 'wager',
            ),
        )
    return rows
