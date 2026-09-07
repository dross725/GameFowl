from .models import Wagers
from .models import Totals
from .models import Settings
from .models import Fight_Results
from .models import Fight_Status
from .models import Event
from .models import AdminBankTransaction
from .models import ArchivedAdminBankTransaction
from .models import ArchivedTellerTransaction
from .models import ArchivedWager
from .models import TellerTransaction
from .models import TellerStatus
from .models import TellerCloseOut
from . import reporting
from .transaction_ids import RolloverBlockedError
from django.contrib.auth.models import User
from datetime import timedelta
from django.conf import settings
from django.utils.timezone import now
from django.db import connection
from django.db import IntegrityError
from django.db import transaction as db_transaction
from functools import lru_cache
import logging
import math
import re
import os
import shutil
import subprocess
import tempfile
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode import code128
from reportlab.lib.units import mm

logger = logging.getLogger('SmartWagers.services')

_CLIENT_REQUEST_ID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


def normalize_client_request_id(raw):
    """Return a normalized UUID string, or None when missing/invalid."""
    value = str(raw or '').strip()
    if not value or not _CLIENT_REQUEST_ID_RE.match(value):
        return None
    return value.lower()


def _lookup_idempotent_wager(client_request_id):
    return (
        Wagers.objects
        .filter(client_request_id=client_request_id, registered=True, cancelled=False)
        .first()
    )


def normalize_wager_transaction_id(raw):
    """Normalize a scanned/typed wager transaction id.

    Bet IDs are stored zero-padded to 6 digits (e.g. ``000123``). Many barcode
    scanners drop leading zeros when they emit as keyboard input, so pad digits
    back to 6. Non-numeric ids (system ``S…`` tickets) are left as-is after trim.
    """
    tid = str(raw or "").strip()
    if tid.isdigit():
        return tid.zfill(6)
    return tid


def normalize_teller_transaction_id(raw):
    """Normalize a scanned/typed teller (remit) transaction id.

    Remit IDs are stored as ``R`` + 6 zero-padded digits (e.g. ``R000123``).
    Accept ``R123``, ``r000123``, etc. Returns ``None`` when the value is not
    a teller transaction id.
    """
    tid = str(raw or "").strip().upper()
    if not tid:
        return None
    if tid.startswith("R") and tid[1:].isdigit():
        return "R" + tid[1:].zfill(6)
    return None


def send_pdf_to_printer(pdf_path):
    printer_name = getattr(settings, "RECEIPT_PRINTER_NAME", None)
    print_options = getattr(settings, "RECEIPT_PRINT_OPTIONS", [])

    lp_command = shutil.which("lp")
    lpr_command = shutil.which("lpr")

    if lp_command:
        command = [lp_command]
        for option in print_options:
            command.extend(["-o", option])
        if printer_name:
            command.extend(["-d", printer_name])
        command.append(pdf_path)
    elif lpr_command:
        command = [lpr_command]
        if printer_name:
            command.extend(["-P", printer_name])
        command.append(pdf_path)
    else:
        raise RuntimeError("No print command found. Install/configure CUPS so `lp` or `lpr` is available.")

    logger.debug("Sending PDF to printer: command=%s", command)
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        logger.debug("PDF sent to printer successfully: %s", pdf_path)
    except subprocess.CalledProcessError as exc:
        error_message = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        logger.error("Failed to print receipt %s: %s", pdf_path, error_message)
        raise RuntimeError(f"Failed to print receipt: {error_message}") from exc

def get_fightnum():
    wagers = Wagers.objects.filter(registered=True).order_by('-id').first()
    if wagers == None:
        #database is empty
        fight_num = 1
    else:
        fight_num = wagers.fightnum
    return (fight_num)

@lru_cache(maxsize=1)
def get_comm_val():
    comm = Settings.objects.order_by('-id').values_list('plasada', flat=True).first()
    if comm is None:
        setcomm = Settings(plasada=0.05)  # Default commission value
        setcomm.save()
        comm = 0.05

    return (comm)


def invalidate_comm_cache():
    get_comm_val.cache_clear()


def get_control_status():
    m_control_status = Settings.objects.order_by('-id').values_list('M_control_status', flat=True).first()
    w_control_status = Settings.objects.order_by('-id').values_list('W_control_status', flat=True).first()

    if m_control_status is None:
        m_control_status = "Open"
    if w_control_status is None:
        w_control_status = "Open"

    return (m_control_status, w_control_status)



def get_Wagers():
    latest_wager = Wagers.objects.filter(registered=True).order_by('-id').first()  # Get latest entry by ID
    if latest_wager:
        ts_id = latest_wager.transactionid
        fight_num = latest_wager.fightnum
        side = latest_wager.side
        wager = latest_wager.wager
    else:
        ts_id = 0
        fight_num = 0
        side = '-----'
        wager = 0
    return (ts_id, fight_num, side, wager)

def compute_payout(m_total, w_total, total_pot):
    comm = get_comm_val()

    if m_total > 0:
        m_payout = total_pot / m_total
        m_payout = m_payout - (m_payout * comm)
        m_payout = format(m_payout * 100, '.2f')
    else:
        m_payout = 0

    if w_total > 0:
        w_payout = total_pot / w_total
        w_payout = w_payout - (w_payout * comm)
        w_payout = format(w_payout * 100, '.2f')
    else:
        w_payout = 0

    return (m_payout, w_payout)

def add_total(amount, side):
    with db_transaction.atomic():
        # Lock the current latest row so concurrent bet registrations are
        # serialized and cannot read a stale snapshot of the totals.
        latest = Totals.objects.select_for_update().order_by('-id').first()
        if latest:
            m_total   = latest.mtotal
            w_total   = latest.wtotal
            total_pot = latest.totalpot
            fn        = latest.fightnum
        else:
            m_total = w_total = total_pot = 0
            fn = 0

        if side.upper() == "MERON":
            m_total += amount
        elif side.upper() == "WALA":
            w_total += amount

        total_pot += amount

        m_payout, w_payout = compute_payout(m_total, w_total, total_pot)
        Totals.objects.create(
            fightnum=fn, mtotal=m_total, wtotal=w_total,
            mpayout=m_payout, wpayout=w_payout, totalpot=total_pot,
        )
    return

DUPLICATE_WAGER_WINDOW_SECONDS = 3


class BettingClosedError(Exception):
    """Raised when a bet is rejected because betting is no longer open."""

    def __init__(self, side=None):
        self.side = side
        super().__init__(f"Betting closed for side={side!r}")


class NoActiveEventError(Exception):
    """Raised when an operation requires an active event."""


class StationAlreadyClosedError(Exception):
    """Raised when a teller attempts to close an already-closed station."""


class CloseOutAlreadyCountedError(Exception):
    """Raised when admin tries to modify a reconciled close-out."""


class CloseOutNotFoundError(Exception):
    """Raised when a close-out record cannot be found."""


def add_wager(amount, side, fightnum, cashier="Juan DelaCruz", require_side_open=True,
              client_request_id=None):
    """Register a wager and update pot totals.

    Returns ``(wager, created)`` where *created* is False when an idempotent
    retry or the 3-second duplicate window reused an existing registered wager.

    *client_request_id*:
      UUID generated when the confirm modal opens. Retries of the same
      submission (double-click, Enter repeat, slow network) return the
      original wager without creating a duplicate or updating totals again.

    *require_side_open*:
      True  (tellers) — overall match OPEN and the specific side OPEN.
      False (admins)  — overall match OPEN only; per-side CLOSE does not block.
      This is intentional: admins may still bet on a closed side until the
      Close Betting button sets overall status to CLOSED.
    """
    client_request_id = normalize_client_request_id(client_request_id)

    with db_transaction.atomic():
        if client_request_id:
            existing = (
                Wagers.objects
                .select_for_update()
                .filter(
                    client_request_id=client_request_id,
                    registered=True,
                    cancelled=False,
                )
                .first()
            )
            if existing:
                logger.warning(
                    "IDEMPOTENT BET RETRY: txn=%s client_request_id=%s cashier=%s",
                    existing.transactionid, client_request_id, cashier,
                )
                return existing, False

        if require_side_open:
            if not is_betting_open(side):
                raise BettingClosedError(side)
        elif not is_match_open():
            raise BettingClosedError(side)

        # Prefer live fight number so a mid-flight fight start cannot attach
        # the bet to a stale fightnum from the request start.
        live_fn = get_fightnum()
        if live_fn:
            fightnum = live_fn

        if not client_request_id:
            duplicate_cutoff = now() - timedelta(seconds=DUPLICATE_WAGER_WINDOW_SECONDS)
            existing = (
                Wagers.objects
                .filter(cashier=cashier, fightnum=fightnum, side=side, wager=amount,
                        registered=True, cancelled=False, created_at__gte=duplicate_cutoff)
                .order_by('-created_at')
                .first()
            )
            if existing:
                logger.warning(
                    "DUPLICATE BET BLOCKED: txn=%s fight=%s side=%s amount=%.2f cashier=%s",
                    existing.transactionid, fightnum, side, amount, cashier,
                )
                log_teller_action(
                    'bet',
                    cashier,
                    transaction_id=existing.transactionid,
                    outcome='duplicate_blocked',
                    level='warning',
                    fight=fightnum,
                    side=side,
                    amount=f"{amount:.2f}",
                )
                return existing, False

        addwager = Wagers(
            fightnum=fightnum,
            side=side,
            wager=amount,
            cashier=cashier,
            registered=True,
            client_request_id=client_request_id,
        )
        try:
            # Savepoint so a unique-key race on client_request_id only rolls
            # back the insert, not the whole atomic block (PostgreSQL).
            with db_transaction.atomic():
                addwager.save()
        except IntegrityError:
            if client_request_id:
                existing = _lookup_idempotent_wager(client_request_id)
                if existing:
                    logger.warning(
                        "IDEMPOTENT BET RACE: txn=%s client_request_id=%s cashier=%s",
                        existing.transactionid, client_request_id, cashier,
                    )
                    log_teller_action(
                        'bet',
                        cashier,
                        transaction_id=existing.transactionid,
                        outcome='idempotent_retry',
                        client_request_id=client_request_id,
                    )
                    return existing, False
            raise
        add_total(amount, side)
    logger.info(
        "BET PLACED: txn=%s fight=%s side=%s amount=%.2f cashier=%s",
        addwager.transactionid, fightnum, side, amount, cashier,
    )
    log_teller_action(
        'bet',
        cashier,
        transaction_id=addwager.transactionid,
        outcome='placed',
        fight=fightnum,
        side=side,
        amount=f"{amount:.2f}",
    )
    return addwager, True

def is_wager_receipt_printing_enabled():
    return getattr(settings, "WAGER_RECEIPT_PRINTING_ENABLED", True)


def is_discard_trailing_3_6_enabled():
    """Return whether bets ending in 3 or 6 should be rejected (wrong punch guard)."""
    setting = Settings.objects.order_by('-id').first()
    if setting is None:
        return True
    return bool(setting.discard_trailing_3_6)


def is_wrong_punch_amount(amount):
    """True when the amount ends with 3 or 6 (accidental punch before Enter)."""
    try:
        value = abs(int(amount))
    except (TypeError, ValueError):
        return False
    return (value % 10) in (3, 6)


def get_wrong_punch_count(user, event=None):
    """Return the teller's wrong-punch count for the event (0 if none)."""
    if user is None:
        return 0
    if event is None:
        event = get_active_event()
    if event is None:
        return 0
    from .models import TellerWrongPunch
    row = TellerWrongPunch.objects.filter(user=user, event=event).only('count').first()
    return int(row.count) if row else 0


def get_wrong_punch_stats(user, event=None):
    """Return wrong-punch count/rank for a user without incrementing.

    Rank is among users with at least one wrong punch this event.
    Highest count wins (rank 1 = most butterfingers). Clean sheets get rank=None.
    """
    if user is None:
        return {
            'count': 0,
            'rank': None,
            'tellers_counted': 0,
            'event_name': None,
        }

    if event is None:
        event = get_active_event()
    if event is None:
        return {
            'count': 0,
            'rank': None,
            'tellers_counted': 0,
            'event_name': None,
        }

    from .models import TellerWrongPunch

    count = get_wrong_punch_count(user, event=event)
    board = list(
        TellerWrongPunch.objects.filter(event=event, count__gt=0)
        .order_by('-count', 'user__username')
        .values_list('user_id', 'count')
    )
    tellers_counted = len(board)
    rank = None
    if count > 0:
        for index, (uid, _count) in enumerate(board, start=1):
            if uid == user.pk:
                rank = index
                break

    return {
        'count': count,
        'rank': rank,
        'tellers_counted': tellers_counted,
        'event_name': event.name,
    }


def get_wrong_punch_leaderboard(event):
    """Return the wrong-punch board and winner(s) for an event.

    Includes tellers who placed at least one registered wager during the event
    window and/or recorded a wrong punch. Most punches wins; ties share the crown.
    """
    from .models import TellerWrongPunch

    if event is None:
        return {
            'event_name': None,
            'winners': [],
            'board': [],
            'best_count': None,
            'has_contestants': False,
        }

    teller_ids = set(
        User.objects.filter(groups__name='teller').values_list('id', flat=True)
    )
    punch_rows = {
        user_id: int(count)
        for user_id, count in TellerWrongPunch.objects.filter(event=event)
        .values_list('user_id', 'count')
    }

    wager_qs = Wagers.objects.filter(
        registered=True,
        created_at__gte=event.started_at,
    ).exclude(cashier='System')
    if event.ended_at is not None:
        wager_qs = wager_qs.filter(created_at__lte=event.ended_at)
    wager_usernames = set(wager_qs.values_list('cashier', flat=True).distinct())

    contestant_ids = set(punch_rows.keys())
    if wager_usernames:
        contestant_ids.update(
            User.objects.filter(
                username__in=wager_usernames,
                id__in=teller_ids,
            ).values_list('id', flat=True)
        )
    # Keep punch rows even if the user is no longer in the teller group.
    contestant_ids.update(uid for uid in punch_rows if uid)

    if not contestant_ids:
        return {
            'event_name': event.name,
            'winners': [],
            'board': [],
            'best_count': None,
            'has_contestants': False,
        }

    users = {
        u.id: u
        for u in User.objects.filter(id__in=contestant_ids).only('id', 'username')
    }
    board = []
    for user_id in contestant_ids:
        user = users.get(user_id)
        if user is None:
            continue
        board.append({
            'user_id': user_id,
            'username': user.username,
            'count': punch_rows.get(user_id, 0),
        })
    # Highest wrong-punch count first — the butterfingers crown.
    board.sort(key=lambda row: (-row['count'], row['username'].lower()))

    best_count = board[0]['count'] if board else None
    winners = [row for row in board if row['count'] == best_count] if board else []
    for index, row in enumerate(board, start=1):
        row['rank'] = index

    return {
        'event_name': event.name,
        'winners': winners,
        'board': board,
        'best_count': best_count,
        'has_contestants': bool(board),
    }


def record_wrong_punch(user, event=None):
    """Increment the user's wrong-punch counter for the active event.

    Returns a dict with count, rank (1 = most punches), and tellers_counted.
    """
    from .models import TellerWrongPunch
    from django.db.models import F

    if user is None:
        return {
            'count': 0,
            'rank': None,
            'tellers_counted': 0,
            'event_name': None,
        }

    if event is None:
        event = get_active_event()
    if event is None:
        return {
            'count': 0,
            'rank': None,
            'tellers_counted': 0,
            'event_name': None,
        }

    with db_transaction.atomic():
        row, _ = TellerWrongPunch.objects.select_for_update().get_or_create(
            user=user,
            event=event,
            defaults={'count': 0},
        )
        TellerWrongPunch.objects.filter(pk=row.pk).update(count=F('count') + 1)
        row.refresh_from_db(fields=['count'])

    stats = get_wrong_punch_stats(user, event=event)
    logger.info(
        "WRONG PUNCH: user=%s event=%s count=%s rank=%s/%s",
        getattr(user, 'username', user),
        event.name,
        stats['count'],
        stats['rank'],
        stats['tellers_counted'],
    )
    return stats


def get_active_event():
    """Return the currently active Event, or None."""
    return Event.objects.filter(is_active=True).order_by('-started_at').first()


def get_event_scope():
    """Return (event, apply_end_bound) for scoping teller data to a single event.

    Use this instead of get_active_event() whenever data should always be
    scoped to a single event (e.g. teller grand totals, balances).  This
    prevents totals from accumulating across multiple events when the system
    is between events.

    apply_end_bound is True only when an event is actively running — meaning
    a newer event's data must be excluded from the previous event's window.
    When the system is between events (no active event), apply_end_bound is
    False so that post-event settlement transactions (REMIT/COLLECT issued
    after ended_at) are still counted in the last event's totals.
    """
    active = get_active_event()
    if active is not None:
        return active, True
    last = Event.objects.filter(is_active=False).order_by('-started_at').first()
    return last, False


def get_admin_fund_summary(event=None, apply_end_bound=True, include_archived=None):
    """Return the shared admin fund balance and bank totals for an event."""
    from django.db.models import Sum

    if event is None:
        event, apply_end_bound = get_event_scope()
    if include_archived is None:
        include_archived = reporting.include_archived_for_event(event)
    if event is None:
        return {
            'balance': 0.0,
            'balance_before_closeouts': 0.0,
            'teller_closeout_remits': 0.0,
            'opening_fund': 0.0,
            'additional_bank_borrowed': 0.0,
            'bank_borrowed': 0.0,
            'bank_remitted': 0.0,
            'net_bank_funding': 0.0,
            'admin_wagers': 0.0,
            'admin_payouts': 0.0,
            'teller_remits': 0.0,
            'teller_borrows': 0.0,
        }

    admin_ids = User.objects.filter(
        groups__name='admin',
    ).values_list('id', flat=True)
    admin_usernames = User.objects.filter(
        groups__name='admin',
    ).values_list('username', flat=True)
    teller_ids = User.objects.filter(
        groups__name='teller',
    ).exclude(
        pk__in=admin_ids,
    ).values_list('id', flat=True)

    admin_wager_qs = reporting.active_wagers_for_event(event).filter(
        cashier__in=admin_usernames,
        registered=True,
        cancelled=False,
    )
    archived_admin_wager_qs = (
        reporting.archived_wagers_for_event(event).filter(
            cashier__in=admin_usernames,
            registered=True,
            cancelled=False,
        )
        if include_archived else None
    )
    admin_payout_qs = reporting.active_teller_transactions_for_event(event).filter(
        user_id__in=admin_ids,
        transaction_type=TellerTransaction.PAYOUT,
        affects_admin_fund=True,
    )
    archived_admin_payout_qs = (
        reporting.archived_teller_transactions_for_event(event).filter(
            user_id__in=admin_ids,
            transaction_type=TellerTransaction.PAYOUT,
            affects_admin_fund=True,
        )
        if include_archived else None
    )
    teller_txn_qs = reporting.active_teller_transactions_for_event(event).filter(
        user_id__in=teller_ids,
        affects_admin_fund=True,
    )
    archived_teller_txn_qs = (
        reporting.archived_teller_transactions_for_event(event).filter(
            user_id__in=teller_ids,
            affects_admin_fund=True,
        )
        if include_archived else None
    )

    if apply_end_bound and event.ended_at:
        admin_wager_qs = admin_wager_qs.filter(created_at__lte=event.ended_at)
        if archived_admin_wager_qs is not None:
            archived_admin_wager_qs = archived_admin_wager_qs.filter(
                created_at__lte=event.ended_at,
            )
        admin_payout_qs = admin_payout_qs.filter(created_at__lte=event.ended_at)
        if archived_admin_payout_qs is not None:
            archived_admin_payout_qs = archived_admin_payout_qs.filter(
                created_at__lte=event.ended_at,
            )
        teller_txn_qs = teller_txn_qs.filter(created_at__lte=event.ended_at)
        if archived_teller_txn_qs is not None:
            archived_teller_txn_qs = archived_teller_txn_qs.filter(
                created_at__lte=event.ended_at,
            )

    opening_fund = float(event.admin_opening_fund)
    explicit_borrows = reporting.sum_admin_bank_amounts(
        reporting.active_admin_bank_for_event(event).filter(
            transaction_type=AdminBankTransaction.BORROW,
        ),
        reporting.archived_admin_bank_for_event(event).filter(
            transaction_type=AdminBankTransaction.BORROW,
        ) if include_archived else None,
    )
    bank_remitted = reporting.sum_admin_bank_amounts(
        reporting.active_admin_bank_for_event(event).filter(
            transaction_type=AdminBankTransaction.REMIT,
        ),
        reporting.archived_admin_bank_for_event(event).filter(
            transaction_type=AdminBankTransaction.REMIT,
        ) if include_archived else None,
    )
    admin_wagers = reporting.sum_wagers(
        admin_wager_qs, archived_admin_wager_qs,
    )
    admin_payouts = reporting.sum_teller_amounts(
        admin_payout_qs, archived_admin_payout_qs,
    )
    teller_remits = reporting.sum_teller_amounts(
        teller_txn_qs.filter(
            transaction_type=TellerTransaction.REMIT,
            received=True,
        ),
        archived_teller_txn_qs.filter(
            transaction_type=TellerTransaction.REMIT,
            received=True,
        ) if archived_teller_txn_qs is not None else None,
    )
    teller_borrows = reporting.sum_teller_amounts(
        teller_txn_qs.filter(transaction_type=TellerTransaction.COLLECT),
        archived_teller_txn_qs.filter(
            transaction_type=TellerTransaction.COLLECT,
        ) if archived_teller_txn_qs is not None else None,
    )
    closeout_remit_qs = TellerCloseOut.objects.filter(
        event=event,
        remit_transaction__isnull=False,
        remit_transaction__received=True,
        remit_transaction__affects_admin_fund=True,
        remit_transaction__created_at__gte=event.started_at,
    )
    archived_closeout_remit_qs = TellerCloseOut.objects.filter(
        event=event,
        archived_remit_transaction__isnull=False,
        archived_remit_transaction__received=True,
        archived_remit_transaction__affects_admin_fund=True,
        archived_remit_transaction__created_at__gte=event.started_at,
    ) if include_archived else None
    if apply_end_bound and event.ended_at:
        closeout_remit_qs = closeout_remit_qs.filter(
            remit_transaction__created_at__lte=event.ended_at,
        )
        if archived_closeout_remit_qs is not None:
            archived_closeout_remit_qs = archived_closeout_remit_qs.filter(
                archived_remit_transaction__created_at__lte=event.ended_at,
            )
    teller_closeout_remits = (
        closeout_remit_qs.aggregate(total=Sum('remit_transaction__amount'))['total'] or 0.0
    )
    if archived_closeout_remit_qs is not None:
        teller_closeout_remits += (
            archived_closeout_remit_qs.aggregate(
                total=Sum('archived_remit_transaction__amount'),
            )['total'] or 0.0
        )

    bank_borrowed = opening_fund + float(explicit_borrows)
    net_bank_funding = bank_borrowed - float(bank_remitted)
    balance = (
        net_bank_funding
        + float(admin_wagers)
        - float(admin_payouts)
        + float(teller_remits)
        - float(teller_borrows)
    )
    balance_before_closeouts = balance - float(teller_closeout_remits)
    return {
        'balance': round(balance, 2),
        'balance_before_closeouts': round(balance_before_closeouts, 2),
        'teller_closeout_remits': round(float(teller_closeout_remits), 2),
        'opening_fund': round(opening_fund, 2),
        'additional_bank_borrowed': round(float(explicit_borrows), 2),
        'bank_borrowed': round(bank_borrowed, 2),
        'bank_remitted': round(float(bank_remitted), 2),
        'net_bank_funding': round(net_bank_funding, 2),
        'admin_wagers': round(float(admin_wagers), 2),
        'admin_payouts': round(float(admin_payouts), 2),
        'teller_remits': round(float(teller_remits), 2),
        'teller_borrows': round(float(teller_borrows), 2),
    }


def get_event_commission_shares(event, *, fight_commissions, include_archived=None):
    """Allocate each fight's commission to cashiers by wager share on that fight.

    Returns a mapping of cashier username → commission share.  Summing all
    values matches the event's pot-based commission total (within per-row
    rounding).
    """
    from collections import defaultdict
    from django.db.models import Sum

    if event is None:
        return {}

    if include_archived is None:
        include_archived = reporting.include_archived_for_event(event)

    payable_fights = {
        fc['fightnum']: fc
        for fc in fight_commissions
        if fc['side'] not in ('CANCELLED', 'DRAW') and fc['totalpot'] > 0
    }
    if not payable_fights:
        return {}

    fight_nums = list(payable_fights.keys())
    wager_qs = reporting.active_wagers_for_event(event).filter(
        registered=True,
        cancelled=False,
        fightnum__in=fight_nums,
    )
    archived_wager_qs = (
        reporting.archived_wagers_for_event(event).filter(
            registered=True,
            cancelled=False,
            fightnum__in=fight_nums,
        )
        if include_archived else None
    )
    if event.ended_at:
        wager_qs = wager_qs.filter(created_at__lte=event.ended_at)
        if archived_wager_qs is not None:
            archived_wager_qs = archived_wager_qs.filter(
                created_at__lte=event.ended_at,
            )

    shares = defaultdict(float)

    def add_rows(qs):
        if qs is None:
            return
        for row in qs.values('fightnum', 'cashier').annotate(total=Sum('wager')):
            fight = payable_fights.get(row['fightnum'])
            if fight is None:
                continue
            pot = float(fight['totalpot'])
            if pot <= 0:
                continue
            wager_total = float(row['total'] or 0)
            if wager_total <= 0:
                continue
            shares[row['cashier']] += (wager_total / pot) * float(fight['commission'])

    add_rows(wager_qs)
    add_rows(archived_wager_qs)

    return {cashier: round(amount, 2) for cashier, amount in shares.items()}


def get_event_betting_surplus_shares(event, include_archived=None):
    """Return each cashier's wagers minus payouts for the event."""
    from collections import defaultdict
    from django.db.models import Sum

    if event is None:
        return {}

    if include_archived is None:
        include_archived = reporting.include_archived_for_event(event)

    wager_qs = reporting.active_wagers_for_event(event).filter(
        registered=True,
        cancelled=False,
    )
    archived_wager_qs = (
        reporting.archived_wagers_for_event(event).filter(
            registered=True,
            cancelled=False,
        )
        if include_archived else None
    )
    payout_qs = reporting.active_teller_transactions_for_event(event).filter(
        transaction_type=TellerTransaction.PAYOUT,
    )
    archived_payout_qs = (
        reporting.archived_teller_transactions_for_event(event).filter(
            transaction_type=TellerTransaction.PAYOUT,
        )
        if include_archived else None
    )
    if event.ended_at:
        wager_qs = wager_qs.filter(created_at__lte=event.ended_at)
        if archived_wager_qs is not None:
            archived_wager_qs = archived_wager_qs.filter(
                created_at__lte=event.ended_at,
            )
        payout_qs = payout_qs.filter(created_at__lte=event.ended_at)
        if archived_payout_qs is not None:
            archived_payout_qs = archived_payout_qs.filter(
                created_at__lte=event.ended_at,
            )

    wagers_by_cashier = defaultdict(float)
    payouts_by_cashier = defaultdict(float)

    def add_wagers(qs):
        if qs is None:
            return
        for row in qs.values('cashier').annotate(total=Sum('wager')):
            wagers_by_cashier[row['cashier']] += float(row['total'] or 0)

    def add_payouts(qs):
        if qs is None:
            return
        for row in qs.values('user__username').annotate(total=Sum('amount')):
            payouts_by_cashier[row['user__username']] += float(row['total'] or 0)

    add_wagers(wager_qs)
    add_wagers(archived_wager_qs)
    add_payouts(payout_qs)
    add_payouts(archived_payout_qs)

    cashiers = set(wagers_by_cashier) | set(payouts_by_cashier)
    return {
        cashier: round(
            wagers_by_cashier.get(cashier, 0.0) - payouts_by_cashier.get(cashier, 0.0),
            2,
        )
        for cashier in cashiers
    }


def get_event_cash_reconciliation(
    event,
    *,
    teller_cash_on_hand,
    total_bets_collected,
    total_opening_fund,
    admin_fund_summary,
    expected_commission,
    close_out_variance_total=0.0,
    include_archived=None,
):
    """Reconcile physical cash (admin + tellers) against expected commission.

    Two independent checks:
      1. Betting surplus vs expected commission — same house take measured two
         ways (wagers−payouts vs pot×plasada); variance should be ~0.
      2. Net earnings (from cash position) vs betting surplus — physical cash
         after stripping house capital and adding back bank remits that already
         left the drawers; variance should be ~0 unless stations were short/over
         at close-out (see close_out_variance_total).
    """
    from django.db.models import Sum

    if event is None:
        return None

    admin_ids = User.objects.filter(
        groups__name='admin',
    ).values_list('pk', flat=True)
    teller_ids = User.objects.filter(
        groups__name='teller',
    ).exclude(
        pk__in=admin_ids,
    ).values_list('pk', flat=True)

    if include_archived is None:
        include_archived = reporting.include_archived_for_event(event)

    txn_qs = reporting.active_teller_transactions_for_event(event).filter(
        user_id__in=teller_ids,
    )
    archived_txn_qs = (
        reporting.archived_teller_transactions_for_event(event).filter(
            user_id__in=teller_ids,
        )
        if include_archived else None
    )
    if event.ended_at:
        txn_qs = txn_qs.filter(created_at__lte=event.ended_at)
        if archived_txn_qs is not None:
            archived_txn_qs = archived_txn_qs.filter(created_at__lte=event.ended_at)

    remit_qs = txn_qs.filter(transaction_type=TellerTransaction.REMIT)
    archived_remit_qs = (
        archived_txn_qs.filter(transaction_type=TellerTransaction.REMIT)
        if archived_txn_qs is not None else None
    )
    teller_remits_all = reporting.sum_teller_amounts(remit_qs, archived_remit_qs)
    remits_not_in_admin = reporting.sum_teller_amounts(
        remit_qs.exclude(received=True, affects_admin_fund=True),
        archived_remit_qs.exclude(received=True, affects_admin_fund=True)
        if archived_remit_qs is not None else None,
    )
    total_payouts = reporting.sum_teller_amounts(
        reporting.active_teller_transactions_for_event(event).filter(
            transaction_type=TellerTransaction.PAYOUT,
        ).filter(created_at__lte=event.ended_at) if event.ended_at else
        reporting.active_teller_transactions_for_event(event).filter(
            transaction_type=TellerTransaction.PAYOUT,
        ),
        reporting.archived_teller_transactions_for_event(event).filter(
            transaction_type=TellerTransaction.PAYOUT,
        ).filter(created_at__lte=event.ended_at) if (
            include_archived and event.ended_at
        ) else (
            reporting.archived_teller_transactions_for_event(event).filter(
                transaction_type=TellerTransaction.PAYOUT,
            ) if include_archived else None
        ),
    )

    admin_cash = admin_fund_summary['balance_before_closeouts']
    total_cash = teller_cash_on_hand + admin_cash
    admin_opening_fund = float(admin_fund_summary['opening_fund'])
    additional_bank_borrowed = float(admin_fund_summary['additional_bank_borrowed'])
    bank_borrowed = float(admin_fund_summary['bank_borrowed'])
    bank_remitted = float(admin_fund_summary['bank_remitted'])
    net_bank = admin_fund_summary['net_bank_funding']
    # Same math as − net_bank, but shown as admin petty / borrows vs remits
    # added back so drawer cash can be traced up to commission.
    net_earnings = (
        total_cash
        + float(remits_not_in_admin)
        - float(total_opening_fund)
        - admin_opening_fund
        - additional_bank_borrowed
        + bank_remitted
    )
    betting_surplus = float(total_bets_collected) - float(total_payouts)
    surplus_vs_commission = betting_surplus - float(expected_commission)
    close_out_variance = float(close_out_variance_total)
    physical_net_earnings = net_earnings + close_out_variance

    return {
        'teller_cash_on_hand': round(float(teller_cash_on_hand), 2),
        'admin_cash_on_hand': round(float(admin_cash), 2),
        'total_cash_on_hand': round(float(total_cash), 2),
        'opening_fund_total': round(float(total_opening_fund), 2),
        'admin_opening_fund': round(admin_opening_fund, 2),
        'additional_bank_borrowed': round(additional_bank_borrowed, 2),
        'bank_borrowed': round(bank_borrowed, 2),
        'bank_remitted': round(bank_remitted, 2),
        'net_bank_funding': round(float(net_bank), 2),
        'teller_remits_all': round(float(teller_remits_all), 2),
        'remits_not_in_admin': round(float(remits_not_in_admin), 2),
        'total_payouts': round(float(total_payouts), 2),
        'betting_surplus': round(betting_surplus, 2),
        'net_earnings': round(net_earnings, 2),
        'expected_commission': round(float(expected_commission), 2),
        'surplus_vs_commission': round(surplus_vs_commission, 2),
        'earnings_vs_betting_surplus': round(net_earnings - betting_surplus, 2),
        'close_out_variance_total': round(close_out_variance, 2),
        'physical_net_earnings': round(physical_net_earnings, 2),
        'physical_vs_commission': round(physical_net_earnings - float(expected_commission), 2),
        # Kept for backwards compatibility in templates/tests.
        'earnings_vs_commission': round(net_earnings - float(expected_commission), 2),
    }


def _get_teller_outstanding_balance(user, event=None, apply_end_bound=True):
    """Return the outstanding balance for a teller, optionally scoped to an event.

    apply_end_bound controls whether the event's ended_at timestamp is used as
    an upper bound.  Pass False when the system is between events so that
    post-event settlement transactions are still counted.
    """
    from django.db.models import Sum
    from SmartWagers import reporting

    wager_qs = Wagers.objects.filter(cashier=str(user), registered=True, cancelled=False)
    txn_qs   = TellerTransaction.objects.filter(user=user)

    wager_qs = reporting.filter_wagers_for_teller(
        wager_qs, user, event, apply_end_bound,
    )
    txn_qs = reporting.filter_transactions_for_teller(
        txn_qs, user, event, apply_end_bound,
    )

    grand_total   = wager_qs.aggregate(t=Sum('wager'))['t']  or 0.0
    remit_total   = txn_qs.filter(transaction_type=TellerTransaction.REMIT  ).aggregate(t=Sum('amount'))['t'] or 0.0
    collect_total = txn_qs.filter(transaction_type=TellerTransaction.COLLECT).aggregate(t=Sum('amount'))['t'] or 0.0
    payout_total  = txn_qs.filter(transaction_type=TellerTransaction.PAYOUT ).aggregate(t=Sum('amount'))['t'] or 0.0

    return grand_total - remit_total + collect_total - payout_total


def compute_teller_balance_breakdown(user, event=None, apply_end_bound=True):
    """Return balance components for a teller, optionally scoped to an event."""
    from django.db.models import Sum
    from SmartWagers import reporting

    username = str(user)
    wager_qs = Wagers.objects.filter(cashier=username, registered=True, cancelled=False)
    txn_qs = TellerTransaction.objects.filter(user=user)

    wager_qs = reporting.filter_wagers_for_teller(
        wager_qs, user, event, apply_end_bound,
    )
    txn_qs = reporting.filter_transactions_for_teller(
        txn_qs, user, event, apply_end_bound,
    )

    grand_total = wager_qs.aggregate(total=Sum('wager'))['total'] or 0.0
    remit_total = txn_qs.filter(
        transaction_type=TellerTransaction.REMIT,
    ).aggregate(total=Sum('amount'))['total'] or 0.0
    collect_total = txn_qs.filter(
        transaction_type=TellerTransaction.COLLECT,
    ).aggregate(total=Sum('amount'))['total'] or 0.0
    payout_total = txn_qs.filter(
        transaction_type=TellerTransaction.PAYOUT,
    ).aggregate(total=Sum('amount'))['total'] or 0.0
    balance = grand_total - remit_total + collect_total - payout_total

    return {
        'balance': round(balance, 2),
        'grand_total': round(grand_total, 2),
        'remit_total': round(remit_total, 2),
        'collect_total': round(collect_total, 2),
        'payout_total': round(payout_total, 2),
    }


def get_teller_close_out(user, event=None):
    """Return the close-out for *user* and *event*, or None."""
    if event is None:
        event = get_active_event()
    if event is None:
        return None
    return TellerCloseOut.objects.filter(user=user, event=event).first()


def teller_station_is_closed(user, event=None):
    """Return True if the teller has closed their station for the event."""
    return get_teller_close_out(user, event=event) is not None


def close_teller_station(user, event=None):
    """Close a teller's station for the active event and snapshot balances."""
    if event is None:
        event = get_active_event()
    if event is None or not event.is_active:
        raise NoActiveEventError()

    if TellerCloseOut.objects.filter(user=user, event=event).exists():
        raise StationAlreadyClosedError()

    _, _, _, fightnum = get_fight_status()
    breakdown = compute_teller_balance_breakdown(user, event=event, apply_end_bound=True)

    with db_transaction.atomic():
        close_out = TellerCloseOut.objects.create(
            user=user,
            event=event,
            fightnum=fightnum,
            expected_cash_on_hand=breakdown['balance'],
            grand_total=breakdown['grand_total'],
            remit_total=breakdown['remit_total'],
            collect_total=breakdown['collect_total'],
            payout_total=breakdown['payout_total'],
        )
        ts, _ = TellerStatus.objects.get_or_create(user=user, defaults={'is_online': True})
        ts.is_online = False
        ts.save(update_fields=['is_online'])

    logger.info(
        "STATION CLOSED: teller=%s event=%s fight=%s expected=%.2f",
        user.username, event.pk, fightnum, breakdown['balance'],
    )
    log_teller_action(
        'close_station',
        user,
        outcome='closed',
        event=event.pk,
        fight=fightnum,
        close_out_id=close_out.pk,
        expected_cash=f"{breakdown['balance']:.2f}",
    )
    return close_out


def reopen_teller_station(close_out_id, admin_user):
    """Cancel an uncounted close-out and bring the teller back online."""
    with db_transaction.atomic():
        close_out = TellerCloseOut.objects.select_for_update().select_related(
            'user',
        ).filter(pk=close_out_id).first()
        if close_out is None:
            raise CloseOutNotFoundError()
        if close_out.actual_cash_counted is not None:
            raise CloseOutAlreadyCountedError()

        teller = close_out.user
        event_id = close_out.event_id
        close_out.delete()

        ts, _ = TellerStatus.objects.get_or_create(
            user=teller,
            defaults={'is_online': True},
        )
        ts.is_online = True
        ts.save(update_fields=['is_online'])

    logger.info(
        "STATION REOPENED: teller=%s event=%s admin=%s",
        teller.username, event_id, admin_user.username,
    )
    return teller


def register_teller_cash_count(close_out_id, actual_amount, admin_user):
    """Record physically counted cash and create a REMIT for the actual amount."""
    if actual_amount < 0:
        raise ValueError('actual_amount must be non-negative')

    with db_transaction.atomic():
        close_out = TellerCloseOut.objects.select_for_update().select_related(
            'user', 'event',
        ).filter(pk=close_out_id).first()
        if close_out is None:
            raise CloseOutNotFoundError()
        if close_out.actual_cash_counted is not None:
            raise CloseOutAlreadyCountedError()

        variance = round(actual_amount, 2) - round(close_out.expected_cash_on_hand, 2)
        remit_txn = TellerTransaction.objects.create(
            user=close_out.user,
            transaction_type=TellerTransaction.REMIT,
            amount=round(actual_amount, 2),
            received=True,
            affects_admin_fund=True,
        )
        close_out.actual_cash_counted = round(actual_amount, 2)
        close_out.variance = round(variance, 2)
        close_out.counted_by = admin_user
        close_out.counted_at = now()
        close_out.remit_transaction = remit_txn
        close_out.save(update_fields=[
            'actual_cash_counted',
            'variance',
            'counted_by',
            'counted_at',
            'remit_transaction',
        ])

    logger.info(
        "STATION RECONCILED: teller=%s close_out=%s actual=%.2f variance=%.2f admin=%s",
        close_out.user.username, close_out.pk, actual_amount, variance, admin_user.username,
    )
    return close_out


def truncate_payout_to_pesos(amount):
    """Drop centavos from a payout amount with no rounding. 165.50 -> 165."""
    return math.trunc(float(amount))


def cashier_username(user_or_name):
    """Normalize a User or stored cashier string to the Wagers.cashier username."""
    if user_or_name is None:
        return None
    if hasattr(user_or_name, 'username'):
        return user_or_name.username
    return str(user_or_name).strip()


def normalize_logged_transaction_id(raw):
    """Normalize wager/remit/test ids for consistent audit log lines."""
    if raw is None:
        return None
    tid = str(raw).strip()
    if not tid:
        return None
    if tid.lower() == 'test':
        return 'test'
    remit_tid = normalize_teller_transaction_id(tid)
    if remit_tid:
        return remit_tid
    return normalize_wager_transaction_id(tid)


def log_teller_action(action, teller, *, transaction_id=None, outcome=None, level='info', **extra):
    """Write a standardized teller audit line to app.log."""
    parts = [f"TELLER {str(action).upper()}"]
    if outcome:
        parts.append(f"outcome={outcome}")
    teller_name = cashier_username(teller)
    if teller_name:
        parts.append(f"teller={teller_name}")
    txn = normalize_logged_transaction_id(transaction_id)
    if txn:
        parts.append(f"txn={txn}")
    for key, value in extra.items():
        if value is not None and value != '':
            parts.append(f"{key}={value}")
    log_fn = getattr(logger, level, logger.info)
    log_fn(" ".join(parts))


def _payout_exceeds_cash_on_hand(cashier_username, amount, transaction_id):
    """Return an error dict if *amount* exceeds the cashier's cash on hand, else None.

    Locks the cashier row to serialize payouts across different tickets for the
    same teller. Must be called inside a transaction.atomic() block.
    """
    try:
        cashier_user = User.objects.select_for_update().get(username=cashier_username)
    except User.DoesNotExist:
        logger.error(
            "PAYOUT REJECTED (cashier_not_found): txn=%s cashier=%s",
            transaction_id, cashier_username,
        )
        return {
            'error': 'cashier_not_found',
            'cashier': cashier_username,
        }

    event_scope, apply_end_bound = get_event_scope()
    if cashier_user.groups.filter(name='admin').exists():
        balance = get_admin_fund_summary(
            event=event_scope,
            apply_end_bound=apply_end_bound,
        )['balance']
    else:
        balance = _get_teller_outstanding_balance(
            cashier_user, event=event_scope, apply_end_bound=apply_end_bound,
        )
    amount = float(amount)
    if round(amount, 2) > round(balance, 2):
        logger.warning(
            "PAYOUT REJECTED (exceeds_cash_on_hand): txn=%s amount=%.2f balance=%.2f cashier=%s",
            transaction_id, amount, balance, cashier_username,
        )
        return {
            'error': 'exceeds_cash_on_hand',
            'balance': balance,
            'required': round(amount, 2),
        }
    return None


def _closing_event_for_settlement():
    """Return the event whose teller balances should be settled before a new event opens."""
    active_event = Event.objects.filter(is_active=True).order_by('-started_at').first()
    if active_event is not None:
        return active_event
    return Event.objects.filter(is_active=False).order_by('-started_at').first()


def teller_has_opening_fund_for_event(teller, event):
    """Return True if *teller* already received opening float in *event*.

    Matches any bank-sourced opening COLLECT (affects_admin_fund=False) in the
    event window, not just the current settings amount.  That keeps issuance
    idempotent if teller_initial_fund is changed mid-event.
    """
    if event is None:
        return False
    txn_qs = reporting.active_teller_transactions_for_event(event).filter(user=teller)
    return txn_qs.filter(
        transaction_type=TellerTransaction.COLLECT,
        affects_admin_fund=False,
    ).exists()


def get_teller_opening_fund_total(teller, event, txn_qs=None, include_archived=False):
    """Return the opening float issued to *teller* within *event*."""
    from django.db.models import Sum

    if event is None:
        return 0.0
    setting = Settings.objects.order_by('-id').first()
    initial_fund = setting.teller_initial_fund if setting else 10000.0
    if initial_fund <= 0:
        return 0.0

    if txn_qs is None:
        txn_qs = reporting.active_teller_transactions_for_event(event).filter(user=teller)
    archived_txn_qs = None
    if include_archived:
        archived_txn_qs = reporting.archived_teller_transactions_for_event(
            event,
        ).filter(user=teller)

    filters = {
        'transaction_type': TellerTransaction.COLLECT,
        'amount': round(initial_fund, 2),
        'affects_admin_fund': False,
    }
    total = txn_qs.filter(**filters).aggregate(total=Sum('amount'))['total'] or 0.0
    if archived_txn_qs is not None:
        total += archived_txn_qs.filter(**filters).aggregate(
            total=Sum('amount'),
        )['total'] or 0.0
    return round(float(total), 2)


def _reset_teller_balances():
    """Create a settlement transaction for every teller who has a non-zero
    outstanding balance.  These are created NOW (before the new event is
    opened) so they fall inside the closing event's time-window and the new
    event starts at zero for every teller.

    Positive balance  → teller owes the house  → record a REMIT to clear it.
    Negative balance  → house owes the teller  → record a COLLECT to clear it.

    These rollover entries are accounting-only. The outgoing event is settled
    with the bank, so they must not change the next event's shared admin fund.

    Returns the primary keys of settlement rows created in this call.
    """
    closing_event = _closing_event_for_settlement()
    if closing_event is None:
        return []

    # Active events have no ended_at yet; already-ended events must include
    # post-ended_at settlement rows in the closing event's report window.
    already_ended = not closing_event.is_active
    apply_end_bound = closing_event.is_active

    admin_ids = User.objects.filter(
        groups__name='admin',
    ).values_list('pk', flat=True)
    cashiers = User.objects.filter(groups__name='teller').exclude(
        pk__in=admin_ids,
    )

    created_settlements = False
    settlement_ids = []
    for cashier in cashiers:
        balance = _get_teller_outstanding_balance(
            cashier, event=closing_event, apply_end_bound=apply_end_bound,
        )
        if balance == 0:
            continue
        created_settlements = True
        if balance > 0:
            txn = TellerTransaction.objects.create(
                user=cashier,
                transaction_type=TellerTransaction.REMIT,
                amount=round(balance, 2),
                received=True,
                affects_admin_fund=False,
            )
        else:
            txn = TellerTransaction.objects.create(
                user=cashier,
                transaction_type=TellerTransaction.COLLECT,
                amount=round(abs(balance), 2),
                affects_admin_fund=False,
            )
        settlement_ids.append(txn.pk)

    if already_ended and created_settlements:
        Event.objects.filter(pk=closing_event.pk).update(ended_at=now())

    return settlement_ids


def issue_teller_opening_fund_if_needed(teller, event=None, *, require_online=True):
    """Issue opening float to *teller* for *event* when eligible.

    Returns True when a COLLECT row is created.  Offline tellers are skipped
    when *require_online* is True (the default).  Idempotent: callers may
    invoke this whenever an online teller should have opening funds, including
    for tellers created after the current event already started.
    """
    if event is None:
        event = get_active_event()
    if event is None:
        return False

    admin_ids = User.objects.filter(
        groups__name='admin',
    ).values_list('pk', flat=True)
    if teller.pk in admin_ids or not teller.groups.filter(name='teller').exists():
        return False

    if require_online:
        status, _ = TellerStatus.objects.get_or_create(
            user=teller, defaults={'is_online': True},
        )
        if not status.is_online:
            return False

    setting = Settings.objects.order_by('-id').first()
    initial_fund = setting.teller_initial_fund if setting else 10000.0
    if initial_fund <= 0:
        return False

    with db_transaction.atomic():
        # Serialize concurrent issuance (teller page + toggle + create user).
        User.objects.select_for_update().filter(pk=teller.pk).first()
        if teller_has_opening_fund_for_event(teller, event):
            return False

        TellerTransaction.objects.create(
            user=teller,
            transaction_type=TellerTransaction.COLLECT,
            amount=round(initial_fund, 2),
            affects_admin_fund=False,
        )
    return True


def _issue_initial_teller_funds():
    """Issue bank-sourced opening funds to online tellers.

    Called immediately after the new event object is created so the
    transactions fall inside the new event's window.

    A COLLECT increases the teller's balance (they owe the house the borrowed
    amount on top of any bets they collect during the event).

    Offline/absent tellers are intentionally skipped — they receive no opening
    float.  If they are later marked online mid-event, issue_teller_opening_fund_if_needed
    issues a matching COLLECT at that point.  If they register bets while still
    marked offline, that is an admin-visible alert (by design: we notify rather
    than block, since the physical teller may be present but just forgotten to
    be toggled on).
    """
    admin_ids = User.objects.filter(
        groups__name='admin',
    ).values_list('pk', flat=True)
    tellers = User.objects.filter(groups__name='teller').exclude(
        pk__in=admin_ids,
    )
    for teller in tellers:
        issue_teller_opening_fund_if_needed(teller)


def start_event(name):
    """Deactivate any running event, create a new one, and reset the fight counter to 0
    so the first call to startnewmatch() produces fight #1.

    Cashier balances are settled before the new event opens so every teller
    and admin starts the new event at zero and the outgoing event's report is
    clean.
    """
    logger.info("EVENT STARTING: name=%r — settling teller balances", name)

    with db_transaction.atomic():
        # PostgreSQL advisory lock serializes event lifecycle commands even
        # when no Event or Settings row exists yet. SQLite remains a dev-only
        # fallback and serializes writes at the database-file level.
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [0x534D415254])
        else:
            Settings.objects.select_for_update().order_by('id').first()

        # Settle all outstanding teller balances against the closing event
        # before it is deactivated so the entries stay in the old event scope.
        settlement_ids = _reset_teller_balances()
        ended_at = now()
        Event.objects.filter(is_active=True).update(
            is_active=False, ended_at=ended_at,
        )
        if settlement_ids:
            # Anchor settlement rows inside the closing event window so they
            # never appear in the next event's teller/admin totals.
            TellerTransaction.objects.filter(pk__in=settlement_ids).update(
                created_at=ended_at,
            )

        setting = Settings.objects.order_by('-id').first()
        admin_opening_fund = setting.admin_initial_fund if setting else 100000.0
        # Stamp started_at strictly after settlement so rollover transactions
        # never leak into the new event window on backends with coarse timestamps.
        event_start = ended_at + timedelta(microseconds=1)
        event = Event.objects.create(
            name=name,
            is_active=True,
            started_at=event_start,
            admin_opening_fund=round(admin_opening_fund, 2),
        )

        # Issue configured starting funds inside the same transaction.
        _issue_initial_teller_funds()

        fight_status = Fight_Status.objects.select_for_update().order_by('id').first()
        if fight_status:
            fight_status.fightnum = 0
            fight_status.overall_status = 'CLOSE'
            fight_status.meron_status = 'CLOSE'
            fight_status.wala_status = 'CLOSE'
            fight_status.save()
        else:
            Fight_Status.objects.create(
                fightnum=0, overall_status='CLOSE',
                meron_status='CLOSE', wala_status='CLOSE',
            )

        Wagers.objects.create(
            fightnum=0, side='EVENT_START', wager=0, cashier='System'
        )
        Totals.objects.create(
            fightnum=0, mtotal=0, wtotal=0,
            mpayout=0, wpayout=0, totalpot=0,
        )

    logger.info(
        "EVENT STARTED: id=%s name=%r started_at=%s",
        event.id, event.name, event.started_at,
    )
    return event


def end_event(actual_admin_cash, counted_by):
    """End the active event and snapshot the shared admin cash count."""
    actual_admin_cash = float(actual_admin_cash)
    if not math.isfinite(actual_admin_cash) or actual_admin_cash < 0:
        raise ValueError('actual_admin_cash must be a non-negative amount')

    with db_transaction.atomic():
        event = Event.objects.select_for_update().filter(
            is_active=True,
        ).order_by('-started_at').first()
        if event is None:
            logger.warning("END EVENT called but no active event found")
            return None

        expected_admin_cash = get_admin_fund_summary(
            event=event,
            apply_end_bound=True,
        )['balance_before_closeouts']
        actual_admin_cash = round(actual_admin_cash, 2)
        event.is_active = False
        event.ended_at = now()
        event.expected_admin_cash_on_hand = expected_admin_cash
        event.actual_admin_cash_counted = actual_admin_cash
        event.admin_cash_variance = round(
            actual_admin_cash - expected_admin_cash,
            2,
        )
        event.admin_cash_counted_by = counted_by
        event.admin_cash_counted_at = now()
        event.save(update_fields=[
            'is_active',
            'ended_at',
            'expected_admin_cash_on_hand',
            'actual_admin_cash_counted',
            'admin_cash_variance',
            'admin_cash_counted_by',
            'admin_cash_counted_at',
        ])

    logger.info(
        "EVENT ENDED: id=%s name=%r ended_at=%s expected_admin_cash=%.2f "
        "actual_admin_cash=%.2f variance=%.2f counted_by=%s",
        event.id,
        event.name,
        event.ended_at,
        event.expected_admin_cash_on_hand,
        event.actual_admin_cash_counted,
        event.admin_cash_variance,
        counted_by.username,
    )
    return event


def build_wager_receipt_payload(wager):
    event = get_active_event()
    return {
        'receipt_type': 'cancel' if getattr(wager, 'cancelled', False) else 'wager',
        'event_name': event.name if event else '',
        'transaction_id': wager.transactionid,
        'fightnum': wager.fightnum,
        'side': wager.side,
        'amount': format(wager.wager, '.2f'),
        'cashier': wager.cashier,
        'date': wager.created_at.strftime("%Y-%m-%d %H:%M:%S"),
    }

def is_betting_open(side):
    """Teller-level check: overall match must be OPEN *and* the specific side must be OPEN.

    Intentionally stricter than is_match_open(). Tellers are blocked when a
    single side is closed; admins may still bet until overall Close Betting.
    """
    fight_status = Fight_Status.objects.order_by('id').first()
    if fight_status is None:
        return False

    if fight_status.overall_status != "OPEN":
        return False

    if side == "MERON":
        return fight_status.meron_status == "OPEN"
    if side == "WALA":
        return fight_status.wala_status == "OPEN"

    return False


def is_match_open():
    """Admin-level check: overall match must be OPEN (ignores per-side status).

    Business rule: when only MERON or WALA is closed, admins may still place
    bets on that side. Admins are blocked only when Close Betting sets overall
    status away from OPEN.
    """
    fight_status = Fight_Status.objects.order_by('id').first()
    if fight_status is None:
        return False
    return fight_status.overall_status == "OPEN"

def print_wager_reciept(amount, side, fightnum, transaction_id, date, cashier="Juan DelaCruz"):
    logger.debug(
        "print_wager_receipt: txn=%s fight=%s side=%s amount=%.2f cashier=%s",
        transaction_id, fightnum, side, amount, cashier,
    )

    # Here you would implement the actual printing logic
    # For now, we just return a string representation

    width = 58 * mm
    height = 58 * mm

    #Create canvas
    c = canvas.Canvas("receipt_with_barcode.pdf", pagesize=(width, height))

    # Sample receipt text
    c.setFont("Helvetica", 10)
    c.drawCentredString(width / 2, height - 30, str(date))

    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(width / 2, height - 50, f"Fight Number: {fightnum}")
    c.drawCentredString(width / 2, height - 70, str(side).upper())
    c.drawCentredString(width / 2, height - 90, f"Amount: {amount:.2f}")
    
    c.setFont("Helvetica", 10)
    c.drawCentredString(width / 2, height - 110, f"Cashier: {cashier}")
    c.drawCentredString(width / 2, height - 120, f"Transaction ID: {transaction_id}")
    # Generate barcode (can be a transaction ID, order number, etc.)
    barcode_value = transaction_id
    barcode = code128.Code128(barcode_value, barHeight=20, barWidth=0.6)

    # Draw barcode (centered horizontally)
    barcode_x = (width - barcode.width) / 2
    barcode_y = height - 150
    barcode.drawOn(c, barcode_x, barcode_y)

    # Finalize PDF
    c.showPage()
    c.save()

    return f"Receipt: {amount} on {side} for fight {fightnum} by {cashier}"

def print_payout_reciept(payout_data):
    logger.debug("print_payout_receipt: %s", payout_data)

    amount = float(str(payout_data['Total_Payout']).replace(",", ""))
    side = payout_data['side']
    fightnum = payout_data['fightnum']
    transaction_id = payout_data['transaction_id']
    odds = payout_data['multiplier']
    bet_odds = payout_data['odds']
    date = now().strftime("%Y-%m-%d %H:%M:%S")
    cashier = payout_data['cashier']

    width = 58 * mm
    height = 70 * mm

    temp_file = tempfile.NamedTemporaryFile(
        prefix=f"payout_receipt_{transaction_id}_",
        suffix=".pdf",
        delete=False,
    )
    temp_file.close()
    pdf_path = temp_file.name

    # Create the receipt as a temporary PDF, then hand it to the OS print queue.
    c = canvas.Canvas(pdf_path, pagesize=(width, height))

    # Sample receipt text
    c.setFont("Helvetica", 10)
    c.drawCentredString(width / 2, height - 30, str(date))

    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(width / 2, height - 50, f"CONGRATULATIONS!")
    c.drawCentredString(width / 2, height - 65, f"Fight Number: {fightnum}")
    c.drawCentredString(width / 2, height - 80, f"{side.upper()} - {bet_odds}")
    wager_amount = payout_data.get('wager', payout_data.get('amount', ''))
    c.drawCentredString(width / 2, height - 95, f"Amount: {wager_amount}")
    c.drawCentredString(width / 2, height - 110, f"Odds: {odds}")
    c.drawCentredString(width / 2, height - 125, f"Payout Amount: {math.trunc(amount)}")
    
    c.setFont("Helvetica", 10)
    c.drawCentredString(width / 2, height - 145, f"Cashier: {cashier}")
    c.drawCentredString(width / 2, height - 155, f"Transaction ID: {transaction_id}")
    
    # Generate barcode (can be a transaction ID, order number, etc.)
    barcode_value = transaction_id
    barcode = code128.Code128(barcode_value, barHeight=20, barWidth=0.6)

    # Draw barcode (centered horizontally)
    barcode_x = (width - barcode.width) / 2
    barcode_y = height - 185
    barcode.drawOn(c, barcode_x, barcode_y)

    # Finalize PDF
    c.showPage()
    c.save()

    try:
        send_pdf_to_printer(pdf_path)
    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)

    return f"Payout Receipt: {amount} on {side} for fight {fightnum} by {cashier}"

def update_control_status(side, status):
    logger.debug("SIDE CONTROL: side=%s status=%s", side, status)
    update_status = Fight_Status.objects.order_by('id').first()
    if update_status is None:
        logger.warning("Fight_Status row missing — creating default")
        update_status = Fight_Status(overall_status='OPEN', meron_status='OPEN', wala_status='OPEN')
        update_status.save()

    if side == 'MERON':
        update_status.meron_status = status
    elif side == 'WALA':
        update_status.wala_status = status
    elif side == 'BOTH':
        update_status.meron_status = status
        update_status.wala_status = status
    else:
        logger.error("SIDE CONTROL: unknown side=%r — no update applied", side)

    # When sides are reopened and the fight is in a bettable state (CLOSED),
    # restore overall_status to OPEN so the server accepts new bets.
    # CANCELLED and COMPLETE are terminal — never reopen those.
    if status == 'OPEN' and update_status.overall_status == 'CLOSED':
        update_status.overall_status = 'OPEN'

    update_status.save()
    return

def get_Totals():
    latest_totals = Totals.objects.order_by('-id').first()
    if latest_totals:
        m_total = latest_totals.mtotal
        m_payout = latest_totals.mpayout
        w_total = latest_totals.wtotal
        w_payout = latest_totals.wpayout
        total_pot = latest_totals.totalpot
        fight_num = latest_totals.fightnum
    else:
        m_total = 0
        m_payout = 0
        w_total = 0
        w_payout = 0
        total_pot = 0
        fight_num = 0
    return (m_total, m_payout, w_total, w_payout, total_pot, fight_num)

def update_wagers(status, fight_num=0):
    if fight_num == 0:
        fight_num = get_fightnum()
    updatewagers= Wagers(fightnum=fight_num, side=status , wager=0, cashier='System')
    updatewagers.save()


def update_fightresults(side):
    m_total, m_payout, w_total, w_payout, total_pot, fightnum = get_Totals()
    
    if m_payout < w_payout:
        meron_odds = "Llamado"
        wala_odds = "Dehado"
    else:
        meron_odds = "Dehado"
        wala_odds = "Llamado"

    side = side.upper()
    odds = '----'
    if side == "MERON":
        odds = meron_odds
    elif side == "WALA":
        odds = wala_odds

    if side == "CANCELLED":
        odds = "CANCELLED"
        side = "CANCELLED"
    
    if side == "DRAW":
        odds = "DRAW"
        side = "DRAW"

    active_event = get_active_event()
    add_fight_result = Fight_Results(
        fightnum=fightnum, side=side, mtotal=m_total, wtotal=w_total,
        mpayout=m_payout, wpayout=w_payout, totalpot=total_pot, odds=odds,
        event=active_event,
    )
    add_fight_result.save()
    endmatch = Wagers(fightnum=fightnum, side=side, wager=0, cashier='System')
    endmatch.save()
    initialize_totals()
    return

def startnewmatch():
    fn = get_fightnum()
    if fn == 0:
        fightnum = initialize_fightnum()
    else:
        fightnum = fn + 1

    logger.info("FIGHT STARTED: fight=%s", fightnum)
    update_wagers('START', fightnum)
    initialize_totals()
    update_fight_status("START")
    return

def closematch():
    fightnum = get_fightnum()
    logger.info("FIGHT CLOSED (betting closed): fight=%s", fightnum)
    update_wagers("CLOSED")
    update_fight_status("CLOSED", "BOTH")

def cancelmatch():
    fightnum = get_fightnum()
    logger.info("FIGHT CANCELLED: fight=%s", fightnum)
    update_wagers("CANCELLED")
    update_fight_status("CANCEL")
    update_fightresults("CANCELLED")

def endmatch(winner):
    fightnum = get_fightnum()
    logger.info("FIGHT ENDED: fight=%s winner=%s", fightnum, winner)
    update_wagers("END")
    update_fight_status("END")
    update_fightresults(winner)

def get_fight_status():
    fight_status = Fight_Status.objects.order_by('id').first()
    if fight_status is None:
        logger.warning("Fight_Status row missing — creating default CLOSE state")
        fightnum = get_fightnum()
        fight_status = Fight_Status(fightnum=fightnum, overall_status='CLOSE', meron_status='CLOSE', wala_status='CLOSE')
        fight_status.save()
    return (fight_status.overall_status, fight_status.meron_status, fight_status.wala_status, fight_status.fightnum)

def initialize_totals():
    logger.debug("Initializing totals for fight=%s", get_fightnum())
    m_total = 0
    m_payout = 0
    w_total = 0
    w_payout = 0
    total_pot = 0
    fight_num = get_fightnum()

    addtotal = Totals(fightnum=fight_num, mtotal=m_total, wtotal=w_total, mpayout=m_payout, wpayout=w_payout, totalpot=total_pot)
    addtotal.save()
    return (m_total, m_payout, w_total, w_payout, total_pot)

def initialize_fightnum():
    logger.debug("Initializing fight counter to 1")
    fight_num = 1
    addwager = Wagers(fightnum=fight_num, side='INIT', wager=0, cashier='System')
    addwager.save()
    return fight_num

def update_fight_status(fightstatus, side=None):
    logger.debug("update_fight_status: status=%s side=%s", fightstatus, side)
    fight_status = Fight_Status.objects.order_by('id').first()
    fn = get_fightnum()
    overall_status = ''
    meron_status = ''
    wala_status = ''

    if fn is None:
        fn = 1

    if fight_status is None:
        logger.warning("Fight_Status row missing in update_fight_status — creating default")
        fight_status = Fight_Status(fightnum=fn, overall_status='CLOSE', meron_status='CLOSE', wala_status='CLOSE')
        fight_status.save()

    if fightstatus == 'START':
        overall_status = 'OPEN'
        meron_status = 'OPEN'
        wala_status = 'OPEN'
    
    elif fightstatus == 'CLOSED':
        overall_status = 'CLOSED'
        meron_status = 'CLOSE'
        wala_status = 'CLOSE'

    elif fightstatus == 'CANCEL':
        overall_status = 'CANCELLED'
        meron_status = 'CLOSE'
        wala_status = 'CLOSE'

    elif fightstatus == 'END':
        overall_status = 'COMPLETE'
        meron_status = 'CLOSE'
        wala_status = 'CLOSE'
    else:
        logger.error("update_fight_status: unknown status=%r — no state change applied", fightstatus)

    fight_status.overall_status = overall_status
    fight_status.meron_status = meron_status
    fight_status.wala_status = wala_status
    if fightstatus == 'START':
        fight_status.fightnum = fn
    fight_status.save()
    return


def build_payout_reprint_payload(wager):
    """Rebuild a payout receipt for an already-paid winning wager."""
    from django.db.models import Q

    event = Event.objects.filter(
        started_at__lte=wager.created_at,
    ).filter(
        Q(ended_at__isnull=True) | Q(ended_at__gte=wager.created_at),
    ).order_by('-started_at').first()

    results = Fight_Results.objects.filter(fightnum=wager.fightnum)
    if event:
        results = results.filter(event=event)
    fight_result = results.order_by('id').first()

    if fight_result is None:
        return None

    side = fight_result.side.upper()
    if side == "DRAW":
        receipt_kind = "draw_refund"
        payout_rate = 100
        odds = "FULL REFUND"
    elif side == "CANCELLED":
        receipt_kind = "cancel_refund"
        payout_rate = 100
        odds = "FULL REFUND"
    elif side == wager.side.upper() == "MERON":
        receipt_kind = "payout"
        payout_rate = fight_result.mpayout
        odds = fight_result.odds
    elif side == wager.side.upper() == "WALA":
        receipt_kind = "payout"
        payout_rate = fight_result.wpayout
        odds = fight_result.odds
    else:
        return None

    multiplier = round(payout_rate / 100, 4)
    total_payout = truncate_payout_to_pesos(wager.wager * multiplier)
    receipt_date = now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        'receipt_type': receipt_kind,
        'transaction_id': wager.transactionid,
        'fightnum': wager.fightnum,
        'side': side,
        'amount': format(wager.wager, '.2f'),
        'odds': odds,
        'multiplier': format(multiplier, '.4f'),
        'Total_Payout': format(total_payout, '.0f'),
        'cashier': wager.cashier,
        'date': receipt_date,
        'reprint': True,
    }


def payout_request(transaction_id, requesting_cashier=None):
    """Serialize payouts for the ticket's cashier before validating balance."""
    transaction_id = normalize_wager_transaction_id(transaction_id)
    active_event = get_active_event()
    wager_qs = Wagers.objects.filter(
        transactionid=transaction_id, registered=True, cancelled=False,
    )
    if active_event:
        wager = wager_qs.filter(created_at__gte=active_event.started_at).first()
    else:
        wager = wager_qs.first()

    cashier_hint = wager.cashier if wager else None
    result = _payout_request_locked(
        transaction_id,
        requesting_cashier=requesting_cashier,
        cashier_hint=cashier_hint,
    )
    _audit_payout_result(transaction_id, requesting_cashier, result)
    return result


def _audit_payout_result(transaction_id, requesting_cashier, result):
    actor = requesting_cashier or result.get('cashier')
    txn = result.get('transaction_id') or transaction_id
    if result.get('error'):
        extra = {}
        if result['error'] == 'wrong_teller':
            extra['owner'] = result.get('original_cashier')
        if result['error'] == 'cashier_not_found':
            extra['ticket_cashier'] = result.get('cashier')
        if result.get('reprint_available'):
            extra['reprint'] = 'available'
        warning_errors = {
            'notfound', 'wrong_teller', 'alreadypaid', 'wrongside',
            'exceeds_cash_on_hand', 'cashier_not_found',
        }
        log_teller_action(
            'payout',
            actor,
            transaction_id=txn,
            outcome=result['error'],
            level='warning' if result['error'] in warning_errors else 'info',
            **extra,
        )
        return

    side = str(result.get('side', '')).upper()
    if side == 'CANCELLED':
        outcome = 'cancel_refund'
    elif side == 'DRAW':
        outcome = 'draw_refund'
    else:
        outcome = 'paid'
    extra = {}
    if result.get('fightnum') is not None:
        extra['fight'] = result.get('fightnum')
    if side:
        extra['side'] = side
    if result.get('Total_Payout') is not None:
        extra['payout'] = result.get('Total_Payout')
    if result.get('wager') is not None:
        extra['wager'] = result.get('wager')
    log_teller_action(
        'payout',
        actor or result.get('cashier'),
        transaction_id=txn,
        outcome=outcome,
        **extra,
    )


def _audit_cancel_result(transaction_id, requesting_cashier, result, cancel_data=None):
    actor = requesting_cashier or (cancel_data.cashier if cancel_data else None)
    txn = result.get('transaction_id') or transaction_id
    if result.get('error'):
        extra = {}
        if result['error'] == 'wrong_teller':
            extra['owner'] = result.get('original_cashier')
        log_teller_action(
            'cancel_bet',
            actor,
            transaction_id=txn,
            outcome=result['error'],
            level='warning',
            **extra,
        )
        return

    extra = {'amount': result.get('amount')}
    if cancel_data is not None:
        extra['fight'] = cancel_data.fightnum
        extra['side'] = cancel_data.side
    log_teller_action(
        'cancel_bet',
        actor or (cancel_data.cashier if cancel_data else None),
        transaction_id=txn,
        outcome='cancelled',
        **extra,
    )


def _payout_request_locked(transaction_id, requesting_cashier=None, cashier_hint=None):
    from django.db.models import Q
    from django.db.models import F

    payout_result = {'payout': True, 'transaction_id': transaction_id}
    comm = get_comm_val()
    active_event = get_active_event()

    with db_transaction.atomic():
        if active_event:
            # All admin cashiers share one fund. This write serializes payouts,
            # teller borrows, and bank remits against that event-wide balance.
            Event.objects.filter(pk=active_event.pk).update(
                is_active=F('is_active'),
            )
        if cashier_hint:
            # This no-op UPDATE is deliberately the first query in the atomic
            # block. It acquires SQLite's write lock before any balance read;
            # on row-locking databases it serializes payouts for this cashier.
            User.objects.filter(username=cashier_hint).update(username=F('username'))

        # Lock the wager row so two simultaneous barcode scans cannot both
        # pass the cashed_out check and issue a double payout.
        base_qs = Wagers.objects.select_for_update().filter(
            transactionid=transaction_id, registered=True, cancelled=False,
        )

        if active_event:
            payout_data = base_qs.filter(created_at__gte=active_event.started_at).first()
        else:
            payout_data = base_qs.first()

        if payout_data is None or payout_data.transactionid is None:
            logger.warning("PAYOUT: txn=%s not found", transaction_id)
            payout_result['error'] = 'notfound'
            return payout_result

        requesting_cashier = cashier_username(requesting_cashier)
        if requesting_cashier and payout_data.cashier != requesting_cashier:
            logger.warning(
                "PAYOUT WRONG TELLER: txn=%s belongs to %s, requested by %s",
                transaction_id, payout_data.cashier, requesting_cashier,
            )
            payout_result['error'] = 'wrong_teller'
            payout_result['original_cashier'] = payout_data.cashier
            return payout_result

        if payout_data.cashed_out:
            logger.warning(
                "PAYOUT DUPLICATE: txn=%s fight=%s already paid cashier=%s",
                transaction_id, payout_data.fightnum, payout_data.cashier,
            )
            payout_result['error'] = 'alreadypaid'
            receipt = build_payout_reprint_payload(payout_data)
            if receipt:
                payout_result['receipt'] = receipt
                payout_result['reprint_available'] = True
            return payout_result

        # Resolve cashier before any cash-out so a missing User never leaves
        # cashed_out=True without a TellerTransaction ledger row.
        try:
            cashier_user = User.objects.select_for_update().get(
                username=payout_data.cashier,
            )
        except User.DoesNotExist:
            logger.error(
                "PAYOUT REJECTED (cashier_not_found): txn=%s cashier=%s",
                transaction_id, payout_data.cashier,
            )
            payout_result['error'] = 'cashier_not_found'
            payout_result['cashier'] = payout_data.cashier
            return payout_result

        payout_data_fn = payout_data.fightnum
        wager_datetime = payout_data.created_at
        event = Event.objects.filter(
            started_at__lte=wager_datetime
        ).filter(
            Q(ended_at__isnull=True) | Q(ended_at__gte=wager_datetime)
        ).order_by('-started_at').first()

        if event:
            payout_fightresults = Fight_Results.objects.filter(
                fightnum=payout_data_fn, event=event
            ).order_by('id').first()
        else:
            payout_fightresults = Fight_Results.objects.filter(
                fightnum=payout_data_fn
            ).order_by('-id').first()

        if payout_fightresults is None:
            payout_result['error'] = 'notfound'
            return payout_result

        payout_fightresult_side = payout_fightresults.side

        if payout_fightresult_side.upper() == "CANCELLED":
            reject = _payout_exceeds_cash_on_hand(
                payout_data.cashier, payout_data.wager, transaction_id,
            )
            if reject:
                payout_result.update(reject)
                return payout_result

            payout_data.cashed_out = True
            payout_data.save(update_fields=['cashed_out'])
            TellerTransaction.objects.create(
                user=cashier_user,
                transaction_type=TellerTransaction.PAYOUT,
                amount=payout_data.wager,
            )
            receipt_date = now().strftime("%Y-%m-%d %H:%M:%S")
            payout_result.update({
                'print_required': is_wager_receipt_printing_enabled(),
                'transaction_id': transaction_id,
                'fightnum': payout_data_fn,
                'side': "CANCELLED",
                'wager': format(payout_data.wager, ','),
                'cashier': payout_data.cashier,
                'receipt_date': receipt_date,
                'receipt': {
                    'receipt_type': 'cancel_refund',
                    'transaction_id': transaction_id,
                    'fightnum': payout_data_fn,
                    'side': 'CANCELLED',
                    'amount': format(payout_data.wager, '.2f'),
                    'odds': 'FULL REFUND',
                    'multiplier': '1.00',
                    'Total_Payout': format(payout_data.wager, '.2f'),
                    'cashier': payout_data.cashier,
                    'date': receipt_date,
                },
            })
            return payout_result

        if payout_fightresult_side.upper() == "DRAW":
            reject = _payout_exceeds_cash_on_hand(
                payout_data.cashier, payout_data.wager, transaction_id,
            )
            if reject:
                payout_result.update(reject)
                return payout_result

            payout_data.cashed_out = True
            payout_data.save(update_fields=['cashed_out'])
            TellerTransaction.objects.create(
                user=cashier_user,
                transaction_type=TellerTransaction.PAYOUT,
                amount=payout_data.wager,
            )
            receipt_date = now().strftime("%Y-%m-%d %H:%M:%S")
            payout_result.update({
                'print_required': is_wager_receipt_printing_enabled(),
                'transaction_id': transaction_id,
                'fightnum': payout_data_fn,
                'side': "DRAW",
                'wager': format(payout_data.wager, ','),
                'cashier': payout_data.cashier,
                'receipt_date': receipt_date,
                'receipt': {
                    'receipt_type': 'draw_refund',
                    'transaction_id': transaction_id,
                    'fightnum': payout_data_fn,
                    'side': 'DRAW',
                    'amount': format(payout_data.wager, '.2f'),
                    'odds': 'FULL REFUND',
                    'multiplier': '1.00',
                    'Total_Payout': format(payout_data.wager, '.2f'),
                    'cashier': payout_data.cashier,
                    'date': receipt_date,
                },
            })
            return payout_result

        if payout_fightresult_side != payout_data.side:
            logger.info(
                "PAYOUT LOSING TICKET: txn=%s fight=%s bet=%s winner=%s cashier=%s",
                transaction_id, payout_data_fn, payout_data.side,
                payout_fightresult_side, payout_data.cashier,
            )
            payout_result['error'] = 'wrongside'
            return payout_result

        # Winning ticket — compute payout
        wager = payout_data.wager
        if payout_fightresult_side == "MERON":
            payout_multiplier = payout_fightresults.mpayout
        elif payout_fightresult_side == "WALA":
            payout_multiplier = payout_fightresults.wpayout
        else:
            payout_multiplier = 100

        payout_multiplier = round(payout_multiplier / 100, 4)
        total_payout = truncate_payout_to_pesos(wager * payout_multiplier)

        reject = _payout_exceeds_cash_on_hand(
            payout_data.cashier, total_payout, transaction_id,
        )
        if reject:
            payout_result.update(reject)
            return payout_result

        # Mark paid and record teller transaction inside the same atomic block
        # so neither can succeed without the other.
        payout_data.cashed_out = True
        payout_data.save(update_fields=['cashed_out'])
        TellerTransaction.objects.create(
            user=cashier_user,
            transaction_type=TellerTransaction.PAYOUT,
            amount=total_payout,
        )

    logger.info(
        "PAYOUT SUCCESS: txn=%s fight=%s side=%s wager=%.2f multiplier=%.4f payout=%.2f cashier=%s",
        transaction_id, payout_data_fn, payout_fightresult_side,
        wager, payout_multiplier, total_payout, payout_data.cashier,
    )
    receipt_date = now().strftime("%Y-%m-%d %H:%M:%S")
    payout_result.update({
        'print_required': is_wager_receipt_printing_enabled(),
        'transaction_id': transaction_id,
        'fightnum': payout_data_fn,
        'side': payout_fightresult_side,
        'wager': wager,
        'odds': payout_fightresults.odds,
        'cashier': payout_data.cashier,
        'receipt_date': receipt_date,
        'Total_Payout': format(total_payout, '.0f'),
        'multiplier': format(payout_multiplier, '.4f'),
        'receipt': {
            'receipt_type': 'payout',
            'transaction_id': transaction_id,
            'fightnum': payout_data_fn,
            'side': payout_fightresult_side,
            'amount': format(wager, '.2f'),
            'odds': payout_fightresults.odds,
            'multiplier': format(payout_multiplier, '.4f'),
            'Total_Payout': format(total_payout, '.0f'),
            'cashier': payout_data.cashier,
            'date': receipt_date,
        },
    })
    return payout_result

def payout_old_ticket(event, teller_username, transaction_id):
    """Process a payout for a winning ticket from a previous (ended) event.

    This is an admin-only operation.  Unlike payout_request() it is explicitly
    scoped to a known event + teller so there is no ambiguity between events
    that share the same sequential transaction IDs.

    Returns a dict with:
      ok=True  + fight, side, wager, payout_amount, multiplier, odds
      ok=False + error code (notfound | already_claimed | not_a_winner |
                             no_result_yet | cancelled | draw)
    For 'draw' and 'cancelled' the refund is also processed and ok=True is
    returned so the caller can display the refund details.
    """
    transaction_id = normalize_wager_transaction_id(transaction_id)
    wager_qs = Wagers.objects.filter(
        transactionid=transaction_id,
        cashier=teller_username,
        registered=True,
        cancelled=False,
        created_at__gte=event.started_at,
    )
    if event.ended_at:
        wager_qs = wager_qs.filter(created_at__lte=event.ended_at)

    with db_transaction.atomic():
        wager = wager_qs.select_for_update().first()

        if wager is None:
            return {'ok': False, 'error': 'notfound'}

        if wager.cashed_out:
            return {'ok': False, 'error': 'already_claimed'}

        fight_result = Fight_Results.objects.filter(
            fightnum=wager.fightnum,
            event=event,
        ).order_by('id').first()

        if fight_result is None:
            return {'ok': False, 'error': 'no_result_yet'}

        try:
            cashier_user = User.objects.select_for_update().get(username=teller_username)
        except User.DoesNotExist:
            logger.error(
                "PAYOUT OLD TICKET REJECTED (cashier_not_found): txn=%s cashier=%s",
                transaction_id, teller_username,
            )
            return {'ok': False, 'error': 'cashier_not_found', 'cashier': teller_username}

        winner_side = fight_result.side.upper()

        def _record_payout(amount):
            TellerTransaction.objects.create(
                user=cashier_user,
                transaction_type=TellerTransaction.PAYOUT,
                amount=amount,
            )

        if winner_side == 'CANCELLED':
            wager.cashed_out = True
            wager.save(update_fields=['cashed_out'])
            _record_payout(wager.wager)
            return {
                'ok': True,
                'result': 'cancelled',
                'transaction_id': transaction_id,
                'fight': wager.fightnum,
                'side': wager.side,
                'wager': wager.wager,
                'payout_amount': wager.wager,
                'odds': fight_result.odds,
            }

        if winner_side == 'DRAW':
            wager.cashed_out = True
            wager.save(update_fields=['cashed_out'])
            _record_payout(wager.wager)
            return {
                'ok': True,
                'result': 'draw',
                'transaction_id': transaction_id,
                'fight': wager.fightnum,
                'side': wager.side,
                'wager': wager.wager,
                'payout_amount': wager.wager,
                'odds': fight_result.odds,
            }

        if winner_side != wager.side.upper():
            return {
                'ok': False,
                'error': 'not_a_winner',
                'winner': winner_side,
                'bet_side': wager.side,
            }

        # Winning ticket — compute payout
        if winner_side == 'MERON':
            payout_multiplier = fight_result.mpayout
        elif winner_side == 'WALA':
            payout_multiplier = fight_result.wpayout
        else:
            payout_multiplier = 100.0

        payout_multiplier = round(payout_multiplier / 100, 4)
        total_payout = truncate_payout_to_pesos(wager.wager * payout_multiplier)

        wager.cashed_out = True
        wager.save(update_fields=['cashed_out'])
        _record_payout(total_payout)

        return {
            'ok': True,
            'result': 'winner',
            'transaction_id': transaction_id,
            'fight': wager.fightnum,
            'side': winner_side,
            'wager': wager.wager,
            'payout_amount': total_payout,
            'multiplier': round(payout_multiplier, 4),
            'odds': fight_result.odds,
        }


def lookup_wager_for_reprint(transaction_id, cashier=None):
    transaction_id = normalize_wager_transaction_id(transaction_id)
    active_event = get_active_event()
    qs = Wagers.objects.filter(
        transactionid=transaction_id, registered=True, cancelled=False,
    )
    cashier = cashier_username(cashier)
    if cashier is not None:
        qs = qs.filter(cashier=cashier)
    if active_event:
        qs = qs.filter(created_at__gte=active_event.started_at)
    wager = qs.first()
    if wager is None:
        return None
    return build_wager_receipt_payload(wager)


def build_remit_receipt_payload(txn):
    """Build the local-print-agent payload for a REMIT receipt reprint."""
    event_scope, apply_end_bound = get_event_scope()
    breakdown = compute_teller_balance_breakdown(
        txn.user, event=event_scope, apply_end_bound=apply_end_bound,
    )
    return {
        'transaction_type': txn.transaction_type,
        'transaction_id': txn.transaction_id,
        'amount': txn.amount,
        'balance': breakdown['balance'],
        'grand_total': breakdown['grand_total'],
        'cashier': str(txn.user),
        'date': txn.created_at.strftime("%Y-%m-%d %H:%M:%S"),
    }


def lookup_remit_for_reprint(transaction_id, user=None):
    """Return a remit receipt payload, or None if not found / not a REMIT."""
    tid = normalize_teller_transaction_id(transaction_id)
    if tid is None:
        return None

    qs = TellerTransaction.objects.select_related('user').filter(
        transaction_id=tid,
        transaction_type=TellerTransaction.REMIT,
    )
    if user is not None:
        qs = qs.filter(user=user)

    active_event = get_active_event()
    if active_event:
        qs = qs.filter(created_at__gte=active_event.started_at)

    txn = qs.first()
    if txn is None:
        return None
    return build_remit_receipt_payload(txn)


def get_fight_results(*args):
    active_event = get_active_event()
    qs = Fight_Results.objects.order_by('-fightnum')
    if active_event is not None:
        qs = qs.filter(event=active_event)
    return qs.values(*args)

def cancel_bet(transaction_id, requesting_cashier=None):
    """Cancel a registered bet. Tellers may only cancel their own tickets.

    When *requesting_cashier* is set (teller terminal), a mismatch with the
    ticket's cashier returns wrong_teller. When None (admin), any ticket may
    be cancelled.
    """
    transaction_id = normalize_wager_transaction_id(transaction_id)
    active_event = get_active_event()
    cancel_result = {'cancel_bet': True, 'transaction_id': transaction_id}
    requesting_actor = cashier_username(requesting_cashier)

    with db_transaction.atomic():
        qs = Wagers.objects.select_for_update().filter(
            transactionid=transaction_id, registered=True, cancelled=False,
        )
        if active_event:
            qs = qs.filter(created_at__gte=active_event.started_at)
        cancel_data = qs.first()
        logger.debug("CANCEL BET REQUEST: txn=%s data=%s", transaction_id, cancel_data)

        if cancel_data is None:
            logger.warning("CANCEL BET: txn=%s not found", transaction_id)
            cancel_result['error'] = 'notfound'
            _audit_cancel_result(transaction_id, requesting_actor, cancel_result)
            return cancel_result

        if cancel_data.transactionid is None:
            logger.warning("CANCEL BET: txn=%s has null transactionid", transaction_id)
            cancel_result['error'] = 'notfound'
            _audit_cancel_result(transaction_id, requesting_actor, cancel_result)
            return cancel_result

        requesting_cashier = requesting_actor
        if requesting_cashier and cancel_data.cashier != requesting_cashier:
            logger.warning(
                "CANCEL BET WRONG TELLER: txn=%s belongs to %s, requested by %s",
                transaction_id, cancel_data.cashier, requesting_cashier,
            )
            cancel_result['error'] = 'wrong_teller'
            cancel_result['original_cashier'] = cancel_data.cashier
            _audit_cancel_result(transaction_id, requesting_actor, cancel_result, cancel_data)
            return cancel_result

        if cancel_data.cashed_out:
            logger.warning(
                "CANCEL BET REJECTED (already paid): txn=%s fight=%s", transaction_id, cancel_data.fightnum
            )
            cancel_result['error'] = 'alreadypaid'
            _audit_cancel_result(transaction_id, requesting_actor, cancel_result, cancel_data)
            return cancel_result

        if cancel_data.side not in ('MERON', 'WALA'):
            logger.warning(
                "CANCEL BET REJECTED (invalid side): txn=%s side=%s", transaction_id, cancel_data.side
            )
            cancel_result['error'] = 'notfound'
            _audit_cancel_result(transaction_id, requesting_actor, cancel_result, cancel_data)
            return cancel_result

        if cancel_data.cashier == 'System':
            logger.warning("CANCEL BET REJECTED (system wager): txn=%s", transaction_id)
            cancel_result['error'] = 'notfound'
            _audit_cancel_result(transaction_id, requesting_actor, cancel_result, cancel_data)
            return cancel_result

        fn = cancel_data.fightnum

        fight_status = Fight_Status.objects.filter(fightnum=fn).first()
        if fight_status is None:
            fight_result = Fight_Results.objects.filter(fightnum=cancel_data.fightnum).first()
            if fight_result is not None:
                logger.warning(
                    "CANCEL BET REJECTED (match complete): txn=%s fight=%s", transaction_id, fn
                )
                cancel_result['error'] = 'matchcomplete'
                _audit_cancel_result(transaction_id, requesting_actor, cancel_result, cancel_data)
                return cancel_result

            logger.error("CANCEL BET: Fight_Status not found for fight=%s", fn)
            cancel_result['error'] = 'systemerror'
            _audit_cancel_result(transaction_id, requesting_actor, cancel_result, cancel_data)
            return cancel_result

        overall_status = fight_status.overall_status

        if overall_status != "OPEN":
            logger.warning(
                "CANCEL BET REJECTED (match not open): txn=%s fight=%s status=%s",
                transaction_id, fn, overall_status,
            )
            cancel_result['error'] = 'matchnotopen'
            _audit_cancel_result(transaction_id, requesting_actor, cancel_result, cancel_data)
            return cancel_result

        # Deduct totals and mark the wager cancelled inside the same atomic
        # block so neither can succeed without the other. Row is retained for
        # report audit with status=cancelled.
        deduct_totals(cancel_data.side, cancel_data.wager)
        cancel_data.cancelled = True
        cancel_data.save(update_fields=['cancelled'])
        cancel_result['message'] = 'betcancelled'
        cancel_result['amount'] = format(cancel_data.wager, ",")
        cancel_result['transaction_id'] = cancel_data.transactionid
        cancel_result['receipt'] = build_wager_receipt_payload(cancel_data)
        cancel_result['print_required'] = is_wager_receipt_printing_enabled()

    logger.info(
        "BET CANCELLED: txn=%s fight=%s side=%s amount=%.2f cashier=%s",
        cancel_result['transaction_id'], fn, cancel_data.side,
        cancel_data.wager, cancel_data.cashier,
    )
    _audit_cancel_result(transaction_id, requesting_actor, cancel_result, cancel_data)
    return cancel_result

#update totals due to cancelled bet
def deduct_totals(side, amount):
    with db_transaction.atomic():
        latest = Totals.objects.select_for_update().order_by('-id').first()
        if latest:
            m_total   = latest.mtotal
            w_total   = latest.wtotal
            total_pot = latest.totalpot
            fn        = latest.fightnum
        else:
            m_total = w_total = total_pot = 0
            fn = 0

        if side.upper() == "MERON":
            m_total -= amount
        elif side.upper() == "WALA":
            w_total -= amount

        total_pot -= amount
        m_payout, w_payout = compute_payout(m_total, w_total, total_pot)
        Totals.objects.create(
            fightnum=fn, mtotal=m_total, wtotal=w_total,
            mpayout=m_payout, wpayout=w_payout, totalpot=total_pot,
        )

