from .models import Wagers
from .models import Totals
from .models import Settings
from .models import Fight_Results
from .models import Fight_Status
from datetime import timedelta
from django.conf import settings
from django.utils.timezone import now
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

    if m_total > 20000:
        m_payout = total_pot / m_total
        m_payout = m_payout - (m_payout * comm)
        m_payout = format(m_payout * 100, '.2f')
    else:
        m_payout = 0

    if w_total > 20000:
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
    m_total, m_payout, w_total, w_payout, total_pot, fn = get_Totals()

    if side.upper() == "MERON":
        m_total += amount
    elif side.upper() == "WALA":
        w_total += amount

    total_pot += amount
    
    m_payout, w_payout = compute_payout(m_total, w_total, total_pot)
    addtotal = Totals(fightnum=fn, mtotal=m_total, wtotal=w_total, mpayout=m_payout, wpayout=w_payout, totalpot=total_pot)
    addtotal.save()
    return

def add_wager(amount, side, fightnum, cashier="Juan DelaCruz"):
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
    pending_wager = Wagers.objects.filter(transactionid=transaction_id, registered=False).first()
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
    pending_wager = Wagers.objects.filter(transactionid=transaction_id, registered=False).first()
    if pending_wager is not None:
        pending_wager.delete()

    return pending_wager is not None

def build_wager_receipt_payload(wager):
    return {
        'receipt_type': 'wager',
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
    #update_status = Settings.objects.filter(id=1).first()
    update_status = Fight_Status.objects.filter(id=1).first()
    if update_status is None:
        if debug:
            print("Fight status object not found, creating a new one")
        update_status = Fight_Status(meron_status='Open', wala_status='Open')
        update_status.save()

    if side == 'MERON':
        update_status.meron_status = status
    elif side == 'WALA':
        update_status.wala_status=status
    elif side == 'BOTH':
        update_status.meron_status = status
        update_status.wala_status = status
    else:
        if debug: 
            print("Error updating control status")

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
        #Match cancelled, refund bet 
        odds = "CANCELLED"
        side = "CANCELLED"
    
    if side == "DRAW":
        odds = "DRAW"
        side = "DRAW"

    add_fight_result = Fight_Results(fightnum=fightnum, side=side, mtotal=m_total, wtotal=w_total,
                                     mpayout=m_payout, wpayout=w_payout, totalpot=total_pot, odds=odds)
    add_fight_result.save()
    endmatch = Wagers(fightnum=fightnum, side=side, wager=0, cashier='System')
    endmatch.save()
    initialize_totals()
    return

def startnewmatch():
    if debug:
        print('Starting new match')

    last_match_datetime = Wagers.objects.order_by('-created_at').first()
    fightnum = 0
    fn = 0
    if last_match_datetime:
        time_diff = now() - last_match_datetime.created_at
        print(time_diff)
        if time_diff > timedelta(hours=24):
            #New Derby
            fightnum=initialize_fightnum()
        else:
            fn = get_fightnum()
            fightnum = fn + 1
    else:
        fightnum=initialize_fightnum()
    
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
    comm = get_comm_val()
    payout_data = Wagers.objects.filter(transactionid=transaction_id, registered=True).first()
    payout_result = {}
    payout_result['payout'] = True
    
    if payout_data == None:
        if debug:
            print("No payout data found for transaction ID: " + str(transaction_id))
        payout_result['error'] = 'notfound'
        return (payout_result)
    
    if payout_data.transactionid == None:
        if debug:
            print("No payout data found for transaction ID: " + str(transaction_id))
        payout_result['error'] = 'notfound'
        return (payout_result)
    
    payout_data_fn = payout_data.fightnum
    cashed_out = payout_data.cashed_out
   
    if cashed_out:
        if debug:
            print("This transaction has already been cashed out.")
        payout_result['error'] = 'alreadypaid'
        #print (str(payout_result))
        return (payout_result)
    
    payout_fightresults = Fight_Results.objects.filter(fightnum=payout_data_fn).first()
    
    if payout_fightresults is None:
        if debug:
            print("No fight results found for fight number: " + str(payout_data_fn))
        payout_result['error'] = 'notfound'
        return (payout_result)
    
    payout_fightresult_side = payout_fightresults.side

    if payout_fightresult_side.upper() == "CANCELLED":
        payout_result['side'] = "CANCELLED"
        payout_result['wager'] = format(payout_data.wager, ',')
        payout_data.cashed_out = True
        payout_data.save()
        return (payout_result)

    if payout_fightresult_side != payout_data.side:
        if debug:
            print("The side for this wager did not win.")
        payout_result['error'] = 'wrongside'
        return (payout_result)
    
    # If all checks passed, prepare payout data
    wager = payout_data.wager
    payout_result['transaction_id'] = transaction_id
    payout_result['fightnum'] = payout_data_fn
    payout_result['side'] = payout_fightresult_side
    payout_result['wager'] = wager
    payout_result['odds'] = payout_fightresults.odds
    payout_result['cashier'] = payout_data.cashier
    payout_result['receipt_date'] = now().strftime("%Y-%m-%d %H:%M:%S")

    if payout_fightresult_side == "MERON":
        payout_multiplier = payout_fightresults.mpayout
    elif payout_fightresult_side == "WALA":
        payout_multiplier = payout_fightresults.wpayout
    else:
        payout_multiplier = 100  # In case of DRAW or CANCELLED, return the original wager amount

    #Commission has been deducted from the main payout computation
    payout_multiplier = payout_multiplier/100
    
    total_payout = wager * (payout_multiplier)
    # print ("wager: " +str(wager))
    # print ("multiplier: " +str(payout_multiplier))
    # print (total_payout)

    payout_result['Total_Payout'] = format(total_payout, '.2f')
    payout_result['multiplier'] = format(payout_multiplier, '.2f')
    payout_result['receipt'] = {
        'receipt_type': 'payout',
        'transaction_id': transaction_id,
        'fightnum': payout_data_fn,
        'side': payout_fightresult_side,
        'odds': payout_fightresults.odds,
        'multiplier': payout_result['multiplier'],
        'Total_Payout': payout_result['Total_Payout'],
        'cashier': payout_data.cashier,
        'date': payout_result['receipt_date'],
    }
    payout_data.cashed_out = True
    payout_data.save()

    return (payout_result)

def get_fight_results(*args):
    results = Fight_Results.objects.values(*args).order_by('-fightnum')
    return results

def cancel_bet(transaction_id):
    debug = True
    cancel_data = Wagers.objects.filter(transactionid=transaction_id, registered=True).first()
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
    m_total, m_payout, w_total, w_payout, total_pot, fn = get_Totals()

    if side.upper() == "MERON":
        m_total -= amount
    elif side.upper() == "WALA":
        w_total -= amount

    total_pot -= amount
    m_payout, w_payout = compute_payout(m_total, w_total, total_pot)
    total = Totals(fightnum=fn, mtotal=m_total, wtotal=w_total, mpayout=m_payout, wpayout=w_payout, totalpot=total_pot)
    total.save()

