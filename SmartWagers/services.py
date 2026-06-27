from .models import Wagers
from .models import Totals
from .models import Settings
from .models import Fight_Results
from .models import Fight_Status
from .models import Event
from .models import TellerTransaction
from django.contrib.auth.models import User
from datetime import timedelta
from django.conf import settings
from django.utils.timezone import now
from django.db import transaction as db_transaction
import barcode
import os
import shutil
import subprocess
import tempfile
from barcode.writer import ImageWriter
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode import code128
from reportlab.lib.units import mm


debug = False

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

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        error_message = exc.stderr.strip() or exc.stdout.strip() or str(exc)
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

    if debug:
        print ('compute payout')
        print ('comm ' +str(comm))
        print ('m_total ' + str(m_total))
        print ('w_total ' + str(w_total))
        print ('total_pot ' + str(total_pot))

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

    if debug:
        print ("updated payouts")
        print ('m_payout ' + str(m_payout))
        print ('w_payout ' + str(w_payout))

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
    return addwager

def is_wager_receipt_printing_enabled():
    return getattr(settings, "WAGER_RECEIPT_PRINTING_ENABLED", True)

def reserve_wager_receipt(amount, side, fightnum, cashier="Juan DelaCruz"):
    pending_wager = Wagers(fightnum=fightnum, side=side, wager=amount, cashier=cashier, registered=False)
    pending_wager.save()
    return pending_wager

def confirm_wager_receipt(transaction_id):
    active_event = get_active_event()
    with db_transaction.atomic():
        qs = Wagers.objects.select_for_update().filter(transactionid=transaction_id, registered=False)
        if active_event:
            qs = qs.filter(created_at__gte=active_event.started_at)
        pending_wager = qs.first()
        if pending_wager is None:
            return None

        if not is_betting_open(pending_wager.side):
            pending_wager.delete()
            return None

        pending_wager.registered = True
        pending_wager.save(update_fields=['registered'])
        add_total(pending_wager.wager, pending_wager.side)
    return pending_wager

def cancel_wager_receipt(transaction_id):
    active_event = get_active_event()
    qs = Wagers.objects.filter(transactionid=transaction_id, registered=False)
    if active_event:
        qs = qs.filter(created_at__gte=active_event.started_at)
    pending_wager = qs.first()
    if pending_wager is not None:
        pending_wager.delete()

    return pending_wager is not None

def get_active_event():
    """Return the currently active Event, or None."""
    return Event.objects.filter(is_active=True).order_by('-started_at').first()


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


def start_event(name):
    """Deactivate any running event, create a new one, and reset the fight counter to 0
    so the first call to startnewmatch() produces fight #1.

    Teller balances are settled before the new event opens so every teller
    starts the new event at zero and the outgoing event's report is clean.
    """
    # Settle all outstanding teller balances against the closing event FIRST,
    # before we change is_active.  This ensures the transactions fall inside
    # the old event's time window and are excluded from the new event.
    _reset_teller_balances()

    Event.objects.filter(is_active=True).update(is_active=False, ended_at=now())

    event = Event.objects.create(name=name, is_active=True)

    fight_status = Fight_Status.objects.filter(id=1).first()
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
        return None
    event.is_active = False
    event.ended_at = now()
    event.save(update_fields=['is_active', 'ended_at'])
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
    fight_status = Fight_Status.objects.filter(id=1).first()
    if fight_status is None:
        return False

    if fight_status.overall_status != "OPEN":
        return False

    if side == "MERON":
        return fight_status.meron_status == "OPEN"
    if side == "WALA":
        return fight_status.wala_status == "OPEN"

    return False

def print_wager_reciept(amount, side, fightnum, transaction_id, date, cashier="Juan DelaCruz"):
    if debug:
        print('Printing wager receipt')
        print('Transaction id: ' +str(transaction_id))
        print('Amount: ' + str(amount))
        print('Side: ' + str(side))
        print('Fight Number: ' + str(fightnum))
        print('Cashier: ' + cashier)

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
    if debug:
        print('Printing payout receipt')
        print(payout_data)

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
    if debug:
        print('Updating control status')
        print('side: ' +str(side))
        print('status: ' +str(status))
    update_status = Fight_Status.objects.filter(id=1).first()
    if update_status is None:
        if debug:
            print("Fight status object not found, creating a new one")
        update_status = Fight_Status(meron_status='Open', wala_status='Open')
        update_status.save()

    if side == 'MERON':
        update_status.meron_status = status
    elif side == 'WALA':
        update_status.wala_status = status
    elif side == 'BOTH':
        update_status.meron_status = status
        update_status.wala_status = status
    else:
        if debug:
            print("Error updating control status")

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
    if debug:
        print('Starting new match')

    fn = get_fightnum()
    if fn == 0:
        fightnum = initialize_fightnum()
    else:
        fightnum = fn + 1

    if debug:
        print('New fight number: ' + str(fightnum))
    
    update_wagers('START', fightnum)
    initialize_totals()
    update_fight_status("START")
    return

def closematch():
    if debug:
        print("Closing Match")
    update_wagers("CLOSED")
    update_fight_status("CLOSED", "BOTH")

def cancelmatch():
    if debug:
        print("Canceling Match")
    
    update_wagers("CANCELLED")
    update_fight_status("CANCEL")
    update_fightresults("CANCELLED")

def endmatch(winner):
    if debug:
        print("Ending Match")

    update_wagers("END")
    update_fight_status("END")
    update_fightresults(winner)

def get_fight_status():
    if debug:
        print('Getting fight status')
    fight_status = Fight_Status.objects.filter(id=1).first()
    if fight_status is None:
        if debug:
            print("Fight_Status object not found, creating a new one")
        fightnum = get_fightnum()
        fight_status = Fight_Status(fightnum=fightnum, overall_status='CLOSE', meron_status='CLOSE', wala_status='CLOSE')
        fight_status.save()
    return (fight_status.overall_status, fight_status.meron_status, fight_status.wala_status, fight_status.fightnum)

def initialize_totals():
    if debug:
        print('Initializing totals')
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
    if debug:
        print('Initializing fight number')
    fight_num = 1
    addwager = Wagers(fightnum=fight_num, side='INIT', wager=0, cashier='System')
    addwager.save()
    return fight_num

def update_fight_status(fightstatus, side = None):
    if debug:
        print('Updating fight status ' +fightstatus )
        print('side ' +str(side))
    fight_status = Fight_Status.objects.filter(id=1).first()
    fn = get_fightnum()
    overall_status = ''
    meron_status = ''
    wala_status = ''

    if fn == None:
        fn = 1

    if fight_status is None:
        if debug:
            print("Settings object not found, creating a new one")
        fight_status = Fight_Status(fightnum=fn, overall_status='CLOSED', meron_status='CLOSE', wala_status='CLOSE')
        fight_status.save()
        return
    
    elif fightstatus == 'START':
        if debug:
            print ("Fight started, initializing new match")
        # Start a new fight
        overall_status = 'OPEN'
        meron_status = 'OPEN'
        wala_status = 'OPEN'
    
    elif fightstatus == 'CLOSED':
        # Close both sides
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
        if debug:
            print("Error updating fight status")

    update_fight_status = Fight_Status.objects.get(id=1)

    update_fight_status.overall_status=overall_status
    update_fight_status.meron_status=meron_status
    update_fight_status.wala_status=wala_status
    update_fight_status.fightnum=fn
    update_fight_status.save()
    return


def payout_request(transaction_id):
    from django.db.models import Q

    payout_result = {'payout': True}
    comm = get_comm_val()
    active_event = get_active_event()

    with db_transaction.atomic():
        # Lock the wager row so two simultaneous barcode scans cannot both
        # pass the cashed_out check and issue a double payout.
        qs = Wagers.objects.select_for_update().filter(
            transactionid=transaction_id, registered=True
        )
        if active_event:
            qs = qs.filter(created_at__gte=active_event.started_at)
        payout_data = qs.first()

        if payout_data is None or payout_data.transactionid is None:
            payout_result['error'] = 'notfound'
            return payout_result

        if payout_data.cashed_out:
            payout_result['error'] = 'alreadypaid'
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
            pass

    receipt_date = now().strftime("%Y-%m-%d %H:%M:%S")
    payout_result.update({
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
    debug = True
    active_event = get_active_event()
    qs = Wagers.objects.filter(transactionid=transaction_id, registered=True)
    if active_event:
        qs = qs.filter(created_at__gte=active_event.started_at)
    cancel_data = qs.first()
    cancel_result = {}
    cancel_result["cancel_bet"] = True
    print ("cancel bet" , transaction_id)
    print (cancel_data)
    if cancel_data == None:
        if debug:
            print("No cancel data found for transaction ID: " + str(transaction_id))
        cancel_result['error'] = 'notfound'
        return (cancel_result)
    
    if cancel_data.transactionid == None:
        if debug:
            print("No cancel data found for transaction ID: " + str(transaction_id))
        cancel_result['error'] = 'notfound'
        return (cancel_result)
    fn = cancel_data.fightnum

    fight_status = Fight_Status.objects.filter(fightnum=fn).first()
    if fight_status is None:
        if debug:
            print("Fight_Status object not found.")
        fight_result = Fight_Results.objects.filter(fightnum=cancel_data.fightnum).first()
        if fight_result is not None:
            if debug:
                print("Match already completed, cannot cancel bet.")
            cancel_result['error'] = 'matchcomplete'
            return (cancel_result)

        cancel_result['error'] = 'systemerror'
        return (cancel_result)

    overall_status = fight_status.overall_status

    if overall_status != "OPEN":
        if debug:
            print("Bets can only be cancelled when the match is OPEN.")
        cancel_result['error'] = 'matchnotopen'
        return (cancel_result)

    else:
        #Bet is valid to be cancelled
        deduct_totals(cancel_data.side, cancel_data.wager)
        print ("BET CANCELLED ", cancel_data)
        cancel_result['message'] = 'betcancelled'
        cancel_result['amount'] = format(cancel_data.wager, ",")
        cancel_result['transaction_id'] = cancel_data.transactionid
        cancel_data.delete()
        return (cancel_result)

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

