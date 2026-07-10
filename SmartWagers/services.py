from .models import Wagers
from .models import Totals
from .models import Settings
from .models import Fight_Results
from .models import Fight_Status
from .models import Event
from .models import TellerTransaction
from .models import TellerStatus
from django.contrib.auth.models import User
from datetime import timedelta
from django.conf import settings
from django.utils.timezone import now
from django.db import transaction as db_transaction
import barcode
import logging
import os
import shutil
import subprocess
import tempfile
from barcode.writer import ImageWriter
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode import code128
from reportlab.lib.units import mm

logger = logging.getLogger('SmartWagers.services')

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

def get_comm_val():
    comm = Settings.objects.order_by('-id').values_list('plasada', flat=True).first()
    if comm is None:
        setcomm = Settings(plasada=0.05)  # Default commission value
        setcomm.save()
        comm = 0.05

    return (comm)

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

    logger.debug(
        "compute_payout: comm=%.4f m_total=%s w_total=%s total_pot=%s",
        comm, m_total, w_total, total_pot,
    )

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

    logger.debug("compute_payout result: m_payout=%s w_payout=%s", m_payout, w_payout)
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

def add_wager(amount, side, fightnum, cashier="Juan DelaCruz"):
    with db_transaction.atomic():
        addwager = Wagers(fightnum=fightnum, side=side, wager=amount, cashier=cashier, registered=True)
        addwager.save()
        add_total(amount, side)
    logger.info(
        "BET PLACED: txn=%s fight=%s side=%s amount=%.2f cashier=%s",
        addwager.transactionid, fightnum, side, amount, cashier,
    )
    return addwager

def is_wager_receipt_printing_enabled():
    return getattr(settings, "WAGER_RECEIPT_PRINTING_ENABLED", True)

def reserve_wager_receipt(amount, side, fightnum, cashier="Juan DelaCruz"):
    pending_wager = Wagers(fightnum=fightnum, side=side, wager=amount, cashier=cashier, registered=False)
    pending_wager.save()
    logger.debug(
        "BET RESERVED (pending print): txn=%s fight=%s side=%s amount=%.2f cashier=%s",
        pending_wager.transactionid, fightnum, side, amount, cashier,
    )
    return pending_wager

def confirm_wager_receipt(transaction_id, admin=False):
    active_event = get_active_event()
    with db_transaction.atomic():
        qs = Wagers.objects.select_for_update().filter(transactionid=transaction_id, registered=False)
        if active_event:
            qs = qs.filter(created_at__gte=active_event.started_at)
        pending_wager = qs.first()
        if pending_wager is None:
            logger.warning("CONFIRM BET: txn=%s not found or already registered", transaction_id)
            return None

        betting_ok = is_match_open() if admin else is_betting_open(pending_wager.side)
        if not betting_ok:
            pending_wager.delete()
            logger.warning(
                "CONFIRM BET REJECTED (betting closed): txn=%s side=%s cashier=%s",
                transaction_id, pending_wager.side, pending_wager.cashier,
            )
            return None

        pending_wager.registered = True
        pending_wager.save(update_fields=['registered'])
        add_total(pending_wager.wager, pending_wager.side)

    logger.info(
        "BET CONFIRMED: txn=%s fight=%s side=%s amount=%.2f cashier=%s",
        pending_wager.transactionid, pending_wager.fightnum,
        pending_wager.side, pending_wager.wager, pending_wager.cashier,
    )
    return pending_wager

def cancel_wager_receipt(transaction_id):
    active_event = get_active_event()
    qs = Wagers.objects.filter(transactionid=transaction_id, registered=False)
    if active_event:
        qs = qs.filter(created_at__gte=active_event.started_at)
    pending_wager = qs.first()
    if pending_wager is not None:
        logger.info(
            "BET RECEIPT CANCELLED (before confirm): txn=%s side=%s amount=%.2f cashier=%s",
            transaction_id, pending_wager.side, pending_wager.wager, pending_wager.cashier,
        )
        pending_wager.delete()
    else:
        logger.debug("CANCEL RECEIPT: txn=%s not found (already confirmed or expired)", transaction_id)

    return pending_wager is not None

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


def _get_teller_outstanding_balance(user, event=None):
    """Return the outstanding balance for a teller, optionally scoped to an event."""
    from django.db.models import Sum
    wager_qs = Wagers.objects.filter(cashier=str(user), registered=True)
    txn_qs   = TellerTransaction.objects.filter(user=user)

    if event is not None:
        wager_qs = wager_qs.filter(created_at__gte=event.started_at)
        txn_qs   = txn_qs.filter(created_at__gte=event.started_at)
        if event.ended_at:
            wager_qs = wager_qs.filter(created_at__lte=event.ended_at)
            txn_qs   = txn_qs.filter(created_at__lte=event.ended_at)

    grand_total   = wager_qs.aggregate(t=Sum('wager'))['t']  or 0.0
    remit_total   = txn_qs.filter(transaction_type=TellerTransaction.REMIT  ).aggregate(t=Sum('amount'))['t'] or 0.0
    collect_total = txn_qs.filter(transaction_type=TellerTransaction.COLLECT).aggregate(t=Sum('amount'))['t'] or 0.0
    payout_total  = txn_qs.filter(transaction_type=TellerTransaction.PAYOUT ).aggregate(t=Sum('amount'))['t'] or 0.0

    return grand_total - remit_total + collect_total - payout_total


def _reset_teller_balances():
    """Create a settlement transaction for every teller who has a non-zero
    outstanding balance.  These are created NOW (before the new event is
    opened) so they fall inside the closing event's time-window and the new
    event starts at zero for every teller.

    Positive balance  → teller owes the house  → record a REMIT to clear it.
    Negative balance  → house owes the teller  → record a COLLECT to clear it.
    """
    active_event = Event.objects.filter(is_active=True).order_by('-started_at').first()
    tellers = User.objects.filter(groups__name='teller')

    for teller in tellers:
        balance = _get_teller_outstanding_balance(teller, event=active_event)
        if balance == 0:
            continue
        if balance > 0:
            TellerTransaction.objects.create(
                user=teller,
                transaction_type=TellerTransaction.REMIT,
                amount=round(balance, 2),
            )
        else:
            TellerTransaction.objects.create(
                user=teller,
                transaction_type=TellerTransaction.COLLECT,
                amount=round(abs(balance), 2),
            )


def _issue_initial_teller_funds():
    """Create a COLLECT (borrow) transaction for every *online* teller equal to
    the configured initial fund amount.  Called immediately after the new event
    object is created so the transactions fall inside the new event's window.

    A COLLECT increases the teller's balance (they owe the house the borrowed
    amount on top of any bets they collect during the event).

    Offline/absent tellers are intentionally skipped — they receive no opening
    float.  If they are later marked online mid-event, toggle_teller_online
    issues a matching COLLECT at that point.  If they register bets while still
    marked offline, that is an admin-visible alert (by design: we notify rather
    than block, since the physical teller may be present but just forgotten to
    be toggled on).
    """
    setting = Settings.objects.order_by('-id').first()
    initial_fund = setting.teller_initial_fund if setting else 10000.0
    if initial_fund <= 0:
        return

    tellers = User.objects.filter(groups__name='teller')
    for teller in tellers:
        status, _ = TellerStatus.objects.get_or_create(user=teller)
        if not status.is_online:
            continue
        TellerTransaction.objects.create(
            user=teller,
            transaction_type=TellerTransaction.COLLECT,
            amount=round(initial_fund, 2),
        )


def start_event(name):
    """Deactivate any running event, create a new one, and reset the fight counter to 0
    so the first call to startnewmatch() produces fight #1.

    Teller balances are settled before the new event opens so every teller
    starts the new event at zero and the outgoing event's report is clean.
    """
    logger.info("EVENT STARTING: name=%r — settling teller balances", name)

    # Settle all outstanding teller balances against the closing event FIRST,
    # before we change is_active.  This ensures the transactions fall inside
    # the old event's time window and are excluded from the new event.
    _reset_teller_balances()

    Event.objects.filter(is_active=True).update(is_active=False, ended_at=now())

    event = Event.objects.create(name=name, is_active=True)
    logger.info("EVENT STARTED: id=%s name=%r started_at=%s", event.id, event.name, event.started_at)

    # Issue the configured starting fund as a borrowed (COLLECT) transaction
    # for every teller.  These land inside the new event's time window so
    # teller balances correctly reflect the borrowed cash from day one.
    _issue_initial_teller_funds()

    fight_status = Fight_Status.objects.order_by('id').first()
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

    anchor = Wagers(fightnum=0, side='EVENT_START', wager=0, cashier='System')
    anchor.save()

    Totals.objects.create(fightnum=0, mtotal=0, wtotal=0, mpayout=0, wpayout=0, totalpot=0)

    return event


def end_event():
    """Mark the active event as ended and return it."""
    event = Event.objects.filter(is_active=True).order_by('-started_at').first()
    if event is None:
        logger.warning("END EVENT called but no active event found")
        return None
    event.is_active = False
    event.ended_at = now()
    event.save(update_fields=['is_active', 'ended_at'])
    logger.info("EVENT ENDED: id=%s name=%r ended_at=%s", event.id, event.name, event.ended_at)
    return event


def build_wager_receipt_payload(wager):
    event = get_active_event()
    return {
        'receipt_type': 'wager',
        'event_name': event.name if event else '',
        'transaction_id': wager.transactionid,
        'fightnum': wager.fightnum,
        'side': wager.side,
        'amount': format(wager.wager, '.2f'),
        'cashier': wager.cashier,
        'date': wager.created_at.strftime("%Y-%m-%d %H:%M:%S"),
    }

def is_betting_open(side):
    """Teller-level check: overall match must be OPEN *and* the specific side must be OPEN."""
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
    """Admin-level check: overall match must be OPEN (ignores per-side status)."""
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
    c.drawCentredString(width / 2, height - 95, f"Odds: {odds}")
    c.drawCentredString(width / 2, height - 110, f"Payout Amount: {amount:.2f}")
    
    c.setFont("Helvetica", 10)
    c.drawCentredString(width / 2, height - 130, f"Cashier: {cashier}")
    c.drawCentredString(width / 2, height - 140, f"Transaction ID: {transaction_id}")
    
    # Generate barcode (can be a transaction ID, order number, etc.)
    barcode_value = transaction_id
    barcode = code128.Code128(barcode_value, barHeight=20, barWidth=0.6)

    # Draw barcode (centered horizontally)
    barcode_x = (width - barcode.width) / 2
    barcode_y = height - 170
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


def payout_request(transaction_id, requesting_cashier=None):
    from django.db.models import Q

    payout_result = {'payout': True}
    comm = get_comm_val()
    active_event = get_active_event()

    with db_transaction.atomic():
        # Lock the wager row so two simultaneous barcode scans cannot both
        # pass the cashed_out check and issue a double payout.
        base_qs = Wagers.objects.select_for_update().filter(
            transactionid=transaction_id, registered=True
        )

        if active_event:
            payout_data = base_qs.filter(created_at__gte=active_event.started_at).first()
        else:
            payout_data = base_qs.first()

        if payout_data is None or payout_data.transactionid is None:
            logger.warning("PAYOUT: txn=%s not found", transaction_id)
            payout_result['error'] = 'notfound'
            return payout_result

        if payout_data.cashed_out:
            logger.warning(
                "PAYOUT DUPLICATE: txn=%s fight=%s already paid cashier=%s",
                transaction_id, payout_data.fightnum, payout_data.cashier,
            )
            payout_result['error'] = 'alreadypaid'
            return payout_result

        if requesting_cashier and payout_data.cashier != requesting_cashier:
            logger.warning(
                "PAYOUT WRONG TELLER: txn=%s belongs to %s, requested by %s",
                transaction_id, payout_data.cashier, requesting_cashier,
            )
            payout_result['error'] = 'wrong_teller'
            payout_result['original_cashier'] = payout_data.cashier
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
            payout_data.cashed_out = True
            payout_data.save(update_fields=['cashed_out'])
            try:
                cashier_user = User.objects.get(username=payout_data.cashier)
                TellerTransaction.objects.create(
                    user=cashier_user,
                    transaction_type=TellerTransaction.PAYOUT,
                    amount=payout_data.wager,
                )
            except User.DoesNotExist:
                pass
            payout_result['side'] = "CANCELLED"
            payout_result['wager'] = format(payout_data.wager, ',')
            return payout_result

        if payout_fightresult_side.upper() == "DRAW":
            payout_data.cashed_out = True
            payout_data.save(update_fields=['cashed_out'])
            try:
                cashier_user = User.objects.get(username=payout_data.cashier)
                TellerTransaction.objects.create(
                    user=cashier_user,
                    transaction_type=TellerTransaction.PAYOUT,
                    amount=payout_data.wager,
                )
            except User.DoesNotExist:
                pass
            payout_result['side'] = "DRAW"
            payout_result['wager'] = format(payout_data.wager, ',')
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

        payout_multiplier = round(payout_multiplier / 100, 2)
        total_payout = wager * payout_multiplier

        # Mark paid and record teller transaction inside the same atomic block
        # so neither can succeed without the other.
        payout_data.cashed_out = True
        payout_data.save(update_fields=['cashed_out'])

        try:
            cashier_user = User.objects.get(username=payout_data.cashier)
            TellerTransaction.objects.create(
                user=cashier_user,
                transaction_type=TellerTransaction.PAYOUT,
                amount=total_payout,
            )
        except User.DoesNotExist:
            logger.warning("PAYOUT: cashier user %r not found in auth.User", payout_data.cashier)

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
        'Total_Payout': format(total_payout, '.2f'),
        'multiplier': format(payout_multiplier, '.2f'),
        'receipt': {
            'receipt_type': 'payout',
            'transaction_id': transaction_id,
            'fightnum': payout_data_fn,
            'side': payout_fightresult_side,
            'odds': payout_fightresults.odds,
            'multiplier': format(payout_multiplier, '.2f'),
            'Total_Payout': format(total_payout, '.2f'),
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
    wager_qs = Wagers.objects.filter(
        transactionid=transaction_id,
        cashier=teller_username,
        registered=True,
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

        winner_side = fight_result.side.upper()

        def _record_payout(amount):
            try:
                cashier_user = User.objects.get(username=teller_username)
                TellerTransaction.objects.create(
                    user=cashier_user,
                    transaction_type=TellerTransaction.PAYOUT,
                    amount=amount,
                )
            except User.DoesNotExist:
                pass

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
        total_payout = wager.wager * payout_multiplier

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
            'payout_amount': round(total_payout, 2),
            'multiplier': round(payout_multiplier, 4),
            'odds': fight_result.odds,
        }


def lookup_wager_for_reprint(transaction_id):
    active_event = get_active_event()
    qs = Wagers.objects.filter(transactionid=transaction_id, registered=True)
    if active_event:
        qs = qs.filter(created_at__gte=active_event.started_at)
    wager = qs.first()
    if wager is None:
        return None
    return build_wager_receipt_payload(wager)

def get_fight_results(*args):
    active_event = get_active_event()
    qs = Fight_Results.objects.order_by('-fightnum')
    if active_event is not None:
        qs = qs.filter(event=active_event)
    return qs.values(*args)

def cancel_bet(transaction_id):
    active_event = get_active_event()
    qs = Wagers.objects.filter(transactionid=transaction_id, registered=True)
    if active_event:
        qs = qs.filter(created_at__gte=active_event.started_at)
    cancel_data = qs.first()
    cancel_result = {}
    cancel_result["cancel_bet"] = True
    logger.debug("CANCEL BET REQUEST: txn=%s data=%s", transaction_id, cancel_data)

    if cancel_data is None:
        logger.warning("CANCEL BET: txn=%s not found", transaction_id)
        cancel_result['error'] = 'notfound'
        return cancel_result

    if cancel_data.transactionid is None:
        logger.warning("CANCEL BET: txn=%s has null transactionid", transaction_id)
        cancel_result['error'] = 'notfound'
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
            return cancel_result

        logger.error("CANCEL BET: Fight_Status not found for fight=%s", fn)
        cancel_result['error'] = 'systemerror'
        return cancel_result

    overall_status = fight_status.overall_status

    if overall_status != "OPEN":
        logger.warning(
            "CANCEL BET REJECTED (match not open): txn=%s fight=%s status=%s",
            transaction_id, fn, overall_status,
        )
        cancel_result['error'] = 'matchnotopen'
        return cancel_result

    deduct_totals(cancel_data.side, cancel_data.wager)
    logger.info(
        "BET CANCELLED: txn=%s fight=%s side=%s amount=%.2f cashier=%s",
        cancel_data.transactionid, fn, cancel_data.side,
        cancel_data.wager, cancel_data.cashier,
    )
    cancel_result['message'] = 'betcancelled'
    cancel_result['amount'] = format(cancel_data.wager, ",")
    cancel_result['transaction_id'] = cancel_data.transactionid
    cancel_data.delete()
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

