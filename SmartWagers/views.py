from django.shortcuts import render, redirect
from django.urls import reverse
from django.http import JsonResponse, HttpResponseForbidden
from django.db.models import Sum
from . import services as services
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.contrib.auth.decorators import login_required
from .models import SessionLog, TellerTransaction, Wagers, Event, Fight_Results, Settings
from django.contrib.auth.models import Group, User
from django.contrib.auth.views import LoginView
from django.contrib.auth.views import LogoutView
from django.utils.timezone import now

debug = False

# views.py
class LogoutViaPost(LogoutView):
    def post(self, request, *args, **kwargs):
        session = SessionLog.objects.filter(
            user=request.user,
            logout_time__isnull=True
        ).order_by('-login_time').first()
        
        
        if session:
            session.logout_time = now()
            session.save()

        return super().post(request, *args, **kwargs)


class RoleBasedLoginView(LoginView):
    def form_valid(self, form):
        response = super().form_valid(form)
        SessionLog.objects.create(user=self.request.user, login_time=now())
        return response

    def get_success_url(self):
        user = self.request.user
        groups = user.groups.values_list('name', flat=True)

        if 'admin' in groups:
            return reverse('admin-page') 
        elif 'teller' in groups:
            return reverse ('user-page') 
        elif 'display' in groups:
            return reverse ('index') 
        else:
            return '/unauthorized/'

def group_required(group_name):
    def decorator(view_func):
        @login_required
        def _wrapped_view(request, *args, **kwargs):
            if request.user.groups.filter(name=group_name).exists():
                return view_func(request, *args, **kwargs)
            return HttpResponseForbidden("You don't have access to this page.")
        return _wrapped_view
    return decorator

def get_teller_information(request):
    user = request.user
    username = user.username
    full_name = f"{user.first_name} {user.last_name}"
    email = user.email

    # Example: log it
    print(f"User {username} accessed this page.")

def get_button_state_view (request):
    mstate, wstate = services.get_control_status()
    return JsonResponse({"mstate": mstate, "wstate": wstate})

def get_fight_results_view (request):
    results = services.get_fight_results('fightnum', 'side', 'odds')
    return JsonResponse(list(results) , safe=False)    

def get_fight_status_view (request): 
    overall_status, meron_status, wala_status, fightnum  = services.get_fight_status()
    active_event = services.get_active_event()
    return JsonResponse({
        "overall_status": overall_status,
        "meron_status": meron_status,
        "wala_status": wala_status,
        "fightnum": fightnum,
        "event_active": active_event is not None,
        "event_name": active_event.name if active_event else "",
    })

def get_pot_values (request):
    m_total_pot, m_payout, w_total_pot, w_payout, total_pot, fight_num = services.get_Totals()
    return JsonResponse({"M_total_bet" : m_total_pot, "M_payout": m_payout, "W_total_bet": w_total_pot, "W_payout": w_payout, "Total_pot": total_pot, "fight_num": fight_num})

# Create your views here.
@group_required('display')
def index(request):
    meron_total, meron_payout, wala_total, wala_payout, total_bet, fightnum = services.get_Totals() 

    return render( request, 'SmartWagers/index.html', {
        'M_total_bet' : format(int(meron_total), ','),
        'M_payout' : meron_payout,
        'W_total_bet' : format(int(wala_total), ','),
        'W_payout' : wala_payout
    })

def SuperUser(request):
    return None

def Reports(request):
    return None

@login_required
def reprint_wager(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'method_not_allowed'}, status=405)

    transaction_id = request.POST.get('transaction_id', '').strip()
    if not transaction_id:
        return JsonResponse({'ok': False, 'error': 'missing_transaction_id'}, status=400)

    receipt = services.lookup_wager_for_reprint(transaction_id)
    if receipt is None:
        return JsonResponse({'ok': False, 'error': 'notfound'})

    return JsonResponse({'ok': True, 'receipt': receipt})

def notify_bet_updates():
    channel_layer = get_channel_layer()
    if channel_layer == None:
        print ("Channel Layer is None")
    else:
        async_to_sync(channel_layer.group_send)(
            "bet_updates", 
            {
                'type': 'send_data', 
                'action': 'update'
            }
        )

def notify_event_change():
    """Broadcast an event-state change to all connected clients so they re-poll get_fight_status_view."""
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    for group in ["administrator", "user", "index"]:
        async_to_sync(channel_layer.group_send)(
            group,
            {
                'type': 'send_data',
                'fight_status': 'event_changed',
            }
        )

def wager_ajax_response(saved_wager):
    meron_total, meron_payout, wala_total, wala_payout, total_bet, fightnum = services.get_Totals()
    notify_bet_updates()
    return JsonResponse({
        'ok': True,
        'pending': False,
        'print_required': services.is_wager_receipt_printing_enabled(),
        'receipt': services.build_wager_receipt_payload(saved_wager),
        'M_total_bet': format(int(meron_total), ','),
        'M_payout': meron_payout,
        'W_total_bet': format(int(wala_total), ','),
        'W_payout': wala_payout,
        'fightnum': fightnum,
    })

@group_required('admin')
def Main_admin(request):
    #initialize
    meron_total, meron_payout, wala_total, wala_payout, total_bet, fightnum = services.get_Totals() 
    current_fn = services.get_fightnum()

    print ("USER: " +str(request.user))
    
    if request.method == 'POST':
        action = request.POST.get('action', 'reserve')
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' and action == 'cancel_pending':
            services.cancel_wager_receipt(request.POST.get('transaction_id', ''))
            return JsonResponse({'ok': True})

        if request.headers.get('x-requested-with') == 'XMLHttpRequest' and action == 'confirm_print':
            saved_wager = services.confirm_wager_receipt(request.POST.get('transaction_id', ''))
            if saved_wager is None:
                return JsonResponse({
                    'ok': False,
                    'error': 'wager_not_registered',
                }, status=409)
            return wager_ajax_response(saved_wager)

        wager = int(request.POST.get('wager_value', 0))
        wager_id = request.POST.get('wager_id', None)

        if request.headers.get('x-requested-with') != 'XMLHttpRequest':
            return HttpResponseForbidden("Receipt printer confirmation is required before registering a bet.")

        if not services.is_wager_receipt_printing_enabled():
            saved_wager = services.add_wager(wager, wager_id, current_fn, cashier=str(request.user))
            return wager_ajax_response(saved_wager)

        pending_wager = services.reserve_wager_receipt(wager, wager_id, current_fn, cashier=str(request.user))
        return JsonResponse({
            'ok': True,
            'pending': True,
            'print_required': True,
            'receipt': services.build_wager_receipt_payload(pending_wager),
        })

    return render( request, 'SmartWagers/administrator.html', {
        'M_total_bet' : format(int(meron_total), ','),
        'M_payout' : meron_payout,
        'W_total_bet' : format(int(wala_total), ','),
        'W_payout' : wala_payout
    })

   
@group_required('teller')
def Teller(request):
    #initialize
    meron_total, meron_payout, wala_total, wala_payout, total_bet , fightnum= services.get_Totals() 
    #comm = services.get_comm_val()
    current_fn = services.get_fightnum()

    if request.method == 'POST':
        action = request.POST.get('action', 'reserve')
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' and action == 'cancel_pending':
            services.cancel_wager_receipt(request.POST.get('transaction_id', ''))
            return JsonResponse({'ok': True})

        if request.headers.get('x-requested-with') == 'XMLHttpRequest' and action == 'confirm_print':
            saved_wager = services.confirm_wager_receipt(request.POST.get('transaction_id', ''))
            if saved_wager is None:
                return JsonResponse({
                    'ok': False,
                    'error': 'wager_not_registered',
                }, status=409)
            return wager_ajax_response(saved_wager)

        wager = int(request.POST.get('wager_value', 0))
        wager_id = request.POST.get('wager_id', None)

        if not services.is_betting_open(wager_id):
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'ok': False,
                    'error': 'betting_closed',
                    'blocked_betting_side': wager_id,
                }, status=409)
            return render( request, 'SmartWagers/user.html', {
                'M_total_bet' : format(int(meron_total), ','),
                'M_payout' : meron_payout,
                'W_total_bet' : format(int(wala_total), ','),
                'W_payout' : wala_payout,
                'blocked_betting_side': wager_id,
            })

        if request.headers.get('x-requested-with') != 'XMLHttpRequest':
            return HttpResponseForbidden("Receipt printer confirmation is required before registering a bet.")

        if not services.is_wager_receipt_printing_enabled():
            saved_wager = services.add_wager(wager, wager_id, current_fn, cashier=str(request.user))
            return wager_ajax_response(saved_wager)

        pending_wager = services.reserve_wager_receipt(wager, wager_id, current_fn, cashier=str(request.user))
        return JsonResponse({
            'ok': True,
            'pending': True,
            'print_required': True,
            'receipt': services.build_wager_receipt_payload(pending_wager),
        })

    return render( request, 'SmartWagers/user.html', {
        'M_total_bet' : format(int(meron_total), ','),
        'M_payout' : meron_payout,
        'W_total_bet' : format(int(wala_total), ','),
        'W_payout' : wala_payout
         })


@group_required('teller')
def teller_report(request):
    active_event = services.get_active_event()

    wager_qs = Wagers.objects.filter(cashier=str(request.user), registered=True)
    if active_event is not None:
        wager_qs = wager_qs.filter(created_at__gte=active_event.started_at)

    wagers = wager_qs.order_by('-created_at')
    total_amount = wagers.aggregate(total=Sum('wager'))['total'] or 0.0
    total_count = wagers.count()

    # Build the set of fight numbers that have a recorded result so the
    # template can disable the reprint button for completed fights.
    result_qs = Fight_Results.objects.all()
    if active_event is not None:
        result_qs = result_qs.filter(event=active_event)
    completed_fights = set(result_qs.values_list('fightnum', flat=True))

    return render(request, 'SmartWagers/teller_report.html', {
        'wagers': wagers,
        'total_amount': total_amount,
        'total_count': total_count,
        'teller_name': str(request.user),
        'active_event': active_event,
        'completed_fights': completed_fights,
    })


def _compute_teller_balance(user, event=None):
    """Return (balance, grand_total) for a teller, optionally scoped to an event.

    When *event* is supplied, only wagers and transactions created within the
    event's time window are counted.  This allows grand totals to restart with
    each new event.

    grand_total = raw sum of registered bets in scope.
    balance     = grand_total − remits + collects (in scope).
    """
    username = str(user)
    wager_qs = Wagers.objects.filter(cashier=username, registered=True)
    txn_qs = TellerTransaction.objects.filter(user=user)

    if event is not None:
        wager_qs = wager_qs.filter(created_at__gte=event.started_at)
        txn_qs = txn_qs.filter(created_at__gte=event.started_at)
        if event.ended_at:
            wager_qs = wager_qs.filter(created_at__lte=event.ended_at)
            txn_qs = txn_qs.filter(created_at__lte=event.ended_at)

    grand_total = wager_qs.aggregate(total=Sum('wager'))['total'] or 0.0
    remit_total = txn_qs.filter(
        transaction_type=TellerTransaction.REMIT
    ).aggregate(total=Sum('amount'))['total'] or 0.0
    collect_total = txn_qs.filter(
        transaction_type=TellerTransaction.COLLECT
    ).aggregate(total=Sum('amount'))['total'] or 0.0
    payout_total = txn_qs.filter(
        transaction_type=TellerTransaction.PAYOUT
    ).aggregate(total=Sum('amount'))['total'] or 0.0

    balance = grand_total - remit_total + collect_total - payout_total
    return balance, grand_total


@group_required('teller')
def get_teller_balance(request):
    active_event = services.get_active_event()
    balance, grand_total = _compute_teller_balance(request.user, event=active_event)
    return JsonResponse({'ok': True, 'balance': balance, 'grand_total': grand_total})


@group_required('teller')
def teller_transaction(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'method_not_allowed'}, status=405)

    transaction_type = request.POST.get('transaction_type', '').strip().upper()
    if transaction_type != TellerTransaction.REMIT:
        return JsonResponse({'ok': False, 'error': 'invalid_type'}, status=400)

    try:
        amount = float(request.POST.get('amount', 0))
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'invalid_amount'}, status=400)

    if amount <= 0:
        return JsonResponse({'ok': False, 'error': 'invalid_amount'}, status=400)

    txn = TellerTransaction.objects.create(
        user=request.user,
        transaction_type=transaction_type,
        amount=amount,
    )

    active_event = services.get_active_event()
    balance, grand_total = _compute_teller_balance(request.user, event=active_event)
    return JsonResponse({
        'ok': True,
        'balance': balance,
        'grand_total': grand_total,
        'cashier': str(request.user),
        'transaction_type': transaction_type,
        'amount': amount,
        'transaction_id': txn.transaction_id,
    })


@group_required('admin')
def admin_tellers(request):
    """Admin view: shows all tellers with balances and TellerTransaction history."""
    try:
        teller_group = Group.objects.get(name='teller')
        tellers = teller_group.user_set.all().order_by('username')
    except Group.DoesNotExist:
        tellers = []

    active_event = services.get_active_event()

    teller_data = []
    for teller in tellers:
        balance, grand_total = _compute_teller_balance(teller, event=active_event)
        txn_qs = TellerTransaction.objects.filter(user=teller)
        if active_event is not None:
            txn_qs = txn_qs.filter(created_at__gte=active_event.started_at)
            if active_event.ended_at:
                txn_qs = txn_qs.filter(created_at__lte=active_event.ended_at)
        transactions = txn_qs.order_by('-created_at')
        teller_data.append({
            'user': teller,
            'display_name': (f"{teller.first_name} {teller.last_name}".strip() or teller.username),
            'balance': balance,
            'grand_total': grand_total,
            'transactions': transactions,
        })

    return render(request, 'SmartWagers/admin_tellers.html', {
        'teller_data': teller_data,
        'active_event': active_event,
    })


@group_required('admin')
def admin_teller_txn(request):
    """Admin endpoint: issue a REMIT or COLLECT transaction for any teller."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'method_not_allowed'}, status=405)

    transaction_type = request.POST.get('transaction_type', '').strip().upper()
    if transaction_type not in (TellerTransaction.REMIT, TellerTransaction.COLLECT):
        return JsonResponse({'ok': False, 'error': 'invalid_type'}, status=400)

    try:
        teller_id = int(request.POST.get('teller_id', 0))
        amount = float(request.POST.get('amount', 0))
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'invalid_params'}, status=400)

    if amount <= 0:
        return JsonResponse({'ok': False, 'error': 'invalid_amount'}, status=400)

    try:
        teller_group = Group.objects.get(name='teller')
        teller = teller_group.user_set.get(pk=teller_id)
    except (Group.DoesNotExist, User.DoesNotExist):
        return JsonResponse({'ok': False, 'error': 'teller_not_found'}, status=404)

    txn = TellerTransaction.objects.create(
        user=teller,
        transaction_type=transaction_type,
        amount=amount,
    )

    balance, grand_total = _compute_teller_balance(teller, event=services.get_active_event())
    display_name = (f"{teller.first_name} {teller.last_name}".strip() or teller.username)

    return JsonResponse({
        'ok': True,
        'transaction_id': txn.transaction_id,
        'balance': balance,
        'grand_total': grand_total,
        'cashier': str(teller),
        'teller_name': display_name,
        'teller_id': teller.pk,
        'amount': amount,
        'transaction_type': transaction_type,
        'created_at': txn.created_at.strftime('%Y-%m-%d %H:%M:%S'),
    })


@group_required('admin')
def admin_mark_received(request):
    """Admin endpoint: mark a REMIT transaction as received by the admin."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'method_not_allowed'}, status=405)

    transaction_id = request.POST.get('transaction_id', '').strip().upper()
    if not transaction_id:
        return JsonResponse({'ok': False, 'error': 'missing_transaction_id'}, status=400)

    active_event = services.get_active_event()
    qs = TellerTransaction.objects.select_related('user').filter(transaction_id=transaction_id)
    if active_event:
        qs = qs.filter(created_at__gte=active_event.started_at)
    txn = qs.first()
    if txn is None:
        return JsonResponse({'ok': False, 'error': 'not_found'}, status=404)

    if txn.transaction_type != TellerTransaction.REMIT:
        return JsonResponse({'ok': False, 'error': 'not_a_remit'}, status=400)

    if txn.received:
        return JsonResponse({
            'ok': False,
            'error': 'already_received',
            'transaction_id': txn.transaction_id,
            'teller_id': txn.user.pk,
        }, status=409)

    txn.received = True
    txn.save(update_fields=['received'])

    return JsonResponse({
        'ok': True,
        'transaction_id': txn.transaction_id,
        'teller_id': txn.user.pk,
    })


@group_required('admin')
def start_event_view(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'method_not_allowed'}, status=405)

    event_name = request.POST.get('event_name', '').strip()
    if not event_name:
        return JsonResponse({'ok': False, 'error': 'event_name_required'}, status=400)

    event = services.start_event(event_name)
    notify_event_change()

    return JsonResponse({
        'ok': True,
        'event_id': event.id,
        'event_name': event.name,
        'started_at': event.started_at.strftime('%Y-%m-%d %H:%M:%S'),
    })


@group_required('admin')
def end_event_view(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'method_not_allowed'}, status=405)

    event = services.end_event()
    if event is None:
        return JsonResponse({'ok': False, 'error': 'no_active_event'}, status=404)

    notify_event_change()

    return JsonResponse({
        'ok': True,
        'event_id': event.id,
        'event_name': event.name,
        'ended_at': event.ended_at.strftime('%Y-%m-%d %H:%M:%S'),
        'report_url': reverse('admin-event-report') + f'?event_id={event.id}',
    })


@group_required('admin')
def admin_event_report(request):
    event_id = request.GET.get('event_id')
    if event_id:
        event = Event.objects.filter(id=event_id).first()
    else:
        event = Event.objects.order_by('-started_at').first()

    all_events = Event.objects.order_by('-started_at')

    if event is None:
        return render(request, 'SmartWagers/event_report.html', {
            'event': None,
            'all_events': all_events,
        })

    try:
        teller_group = Group.objects.get(name='teller')
        tellers = teller_group.user_set.all().order_by('username')
    except Group.DoesNotExist:
        tellers = []

    teller_data = []
    grand_total_all = 0.0
    for teller in tellers:
        balance, grand_total = _compute_teller_balance(teller, event=event)
        txn_qs = TellerTransaction.objects.filter(
            user=teller,
            created_at__gte=event.started_at,
        )
        if event.ended_at:
            txn_qs = txn_qs.filter(created_at__lte=event.ended_at)
        remit_total = txn_qs.filter(
            transaction_type=TellerTransaction.REMIT
        ).aggregate(total=Sum('amount'))['total'] or 0.0

        teller_data.append({
            'user': teller,
            'display_name': (f"{teller.first_name} {teller.last_name}".strip() or teller.username),
            'grand_total': grand_total,
            'remit_total': remit_total,
            'balance': balance,
        })
        grand_total_all += grand_total

    # Commission totals
    plasada = services.get_comm_val()
    fight_results_qs = Fight_Results.objects.filter(event=event).order_by('fightnum')
    fight_commissions = [
        {
            'fightnum': r.fightnum,
            'side': r.side,
            'totalpot': r.totalpot,
            'commission': r.totalpot * plasada,
            'date': r.date,
        }
        for r in fight_results_qs
    ]
    total_pot_all = sum(fc['totalpot'] for fc in fight_commissions)
    total_commission = total_pot_all * plasada

    return render(request, 'SmartWagers/event_report.html', {
        'event': event,
        'all_events': all_events,
        'teller_data': teller_data,
        'grand_total_all': grand_total_all,
        'fight_commissions': fight_commissions,
        'total_pot_all': total_pot_all,
        'total_commission': total_commission,
        'plasada': plasada,
        'plasada_pct': plasada * 100,
    })


@group_required('admin')
def admin_teller_transactions(request):
    """Admin view: all teller wagers with fight number, transaction ID, amount, side."""
    active_event = services.get_active_event()

    wager_qs = Wagers.objects.filter(registered=True).exclude(cashier='System').order_by('-created_at')
    if active_event is not None:
        wager_qs = wager_qs.filter(created_at__gte=active_event.started_at)

    total_amount = wager_qs.aggregate(total=Sum('wager'))['total'] or 0.0
    total_count = wager_qs.count()

    return render(request, 'SmartWagers/admin_teller_transactions.html', {
        'wagers': wager_qs,
        'total_amount': total_amount,
        'total_count': total_count,
        'active_event': active_event,
    })


@group_required('admin')
def admin_commission(request):
    """Admin view: total commission (plasada) collected from all completed fights."""
    active_event = services.get_active_event()
    plasada = services.get_comm_val()

    result_qs = Fight_Results.objects.all().order_by('fightnum')
    if active_event is not None:
        result_qs = result_qs.filter(event=active_event)

    fight_commissions = []
    total_commission = 0.0
    total_pot_all = 0.0

    for result in result_qs:
        commission = result.totalpot * plasada
        fight_commissions.append({
            'fightnum': result.fightnum,
            'side': result.side,
            'totalpot': result.totalpot,
            'commission': commission,
            'date': result.date,
        })
        total_commission += commission
        total_pot_all += result.totalpot

    return render(request, 'SmartWagers/admin_commission.html', {
        'fight_commissions': fight_commissions,
        'total_commission': total_commission,
        'total_pot_all': total_pot_all,
        'plasada': plasada,
        'plasada_pct': plasada * 100,
        'active_event': active_event,
    })


@group_required('admin')
def admin_settings(request):
    """Admin view: adjust plasada and change fight result winners."""
    active_event = services.get_active_event()

    if request.method == 'POST':
        action = request.POST.get('action', '')

        if action == 'update_plasada':
            try:
                new_plasada = float(request.POST.get('plasada', ''))
                if not (0 < new_plasada < 1):
                    return JsonResponse({'ok': False, 'error': 'Plasada must be between 0 and 1 (e.g. 0.05 for 5%)'}, status=400)
            except (ValueError, TypeError):
                return JsonResponse({'ok': False, 'error': 'Invalid plasada value'}, status=400)

            setting = Settings.objects.order_by('-id').first()
            if setting is None:
                setting = Settings(plasada=new_plasada)
            else:
                setting.plasada = new_plasada
            setting.save()
            return JsonResponse({'ok': True, 'plasada': new_plasada, 'plasada_pct': new_plasada * 100})

        if action == 'update_fight_result':
            try:
                result_id = int(request.POST.get('result_id', 0))
                new_side = request.POST.get('side', '').strip().upper()
            except (ValueError, TypeError):
                return JsonResponse({'ok': False, 'error': 'Invalid parameters'}, status=400)

            if new_side not in ('MERON', 'WALA', 'DRAW'):
                return JsonResponse({'ok': False, 'error': 'Side must be MERON, WALA, or DRAW'}, status=400)

            try:
                result = Fight_Results.objects.get(pk=result_id)
            except Fight_Results.DoesNotExist:
                return JsonResponse({'ok': False, 'error': 'Fight result not found'}, status=404)

            result.side = new_side
            result.save(update_fields=['side'])
            return JsonResponse({'ok': True, 'result_id': result_id, 'side': new_side})

        return JsonResponse({'ok': False, 'error': 'Unknown action'}, status=400)

    plasada = services.get_comm_val()
    fight_results = Fight_Results.objects.all().order_by('-fightnum')
    if active_event is not None:
        fight_results = fight_results.filter(event=active_event)

    return render(request, 'SmartWagers/admin_settings.html', {
        'plasada': plasada,
        'plasada_pct': plasada * 100,
        'fight_results': fight_results,
        'active_event': active_event,
    })
