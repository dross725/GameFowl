from django.shortcuts import render, redirect
from django.urls import reverse
from django.http import JsonResponse, HttpResponseForbidden
from django.db.models import Sum, Count, Q
from . import services as services
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.contrib.auth.decorators import login_required
from .models import SessionLog, TellerTransaction, Wagers, Event, Fight_Results, Settings, TellerStatus
from django.contrib.auth.models import Group, User
from django.contrib.auth.views import LoginView
from django.contrib.auth.views import LogoutView
from django.utils.timezone import now
import logging

logger = logging.getLogger('SmartWagers.views')

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

        logger.info("LOGOUT: user=%s ip=%s", request.user.username, _get_client_ip(request))
        return super().post(request, *args, **kwargs)


class RoleBasedLoginView(LoginView):
    def form_valid(self, form):
        response = super().form_valid(form)
        SessionLog.objects.create(user=self.request.user, login_time=now())
        groups = list(self.request.user.groups.values_list('name', flat=True))
        logger.info(
            "LOGIN: user=%s groups=%s ip=%s",
            self.request.user.username, groups, _get_client_ip(self.request),
        )
        return response

    def get_success_url(self):
        user = self.request.user
        groups = user.groups.values_list('name', flat=True)

        if 'admin' in groups:
            return reverse('admin-page')
        elif 'teller' in groups:
            return reverse('user-page')
        elif 'display' in groups:
            return reverse('index')
        else:
            logger.warning("LOGIN: user=%s has no recognized group — redirecting to /unauthorized/", user.username)
            return '/unauthorized/'


def _get_client_ip(request):
    """Return the best-effort client IP from request headers."""
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '?')

def group_required(group_name):
    def decorator(view_func):
        @login_required
        def _wrapped_view(request, *args, **kwargs):
            if request.user.groups.filter(name=group_name).exists():
                return view_func(request, *args, **kwargs)
            return render(request, '403.html', status=403)
        return _wrapped_view
    return decorator

def get_teller_information(request):
    user = request.user
    username = user.username
    full_name = f"{user.first_name} {user.last_name}"
    email = user.email
    logger.debug("get_teller_information: user=%s", username)

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

    return JsonResponse({'ok': True, 'print_required': services.is_wager_receipt_printing_enabled(), 'receipt': receipt})

def notify_bet_updates():
    channel_layer = get_channel_layer()
    if channel_layer is None:
        logger.error("notify_bet_updates: channel layer is None — WebSocket broadcast skipped")
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

    logger.debug("Main_admin page: user=%s", request.user)

    if request.method == 'POST':
        action = request.POST.get('action', 'reserve')
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' and action == 'cancel_pending':
            services.cancel_wager_receipt(request.POST.get('transaction_id', ''))
            return JsonResponse({'ok': True})

        if request.headers.get('x-requested-with') == 'XMLHttpRequest' and action == 'confirm_print':
            saved_wager = services.confirm_wager_receipt(request.POST.get('transaction_id', ''), admin=True)
            if saved_wager is None:
                return JsonResponse({
                    'ok': False,
                    'error': 'wager_not_registered',
                }, status=409)
            return wager_ajax_response(saved_wager)

        wager = int(request.POST.get('wager_value', 0))
        wager_id = request.POST.get('wager_id', None)

        if not services.is_match_open():
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'ok': False,
                    'error': 'betting_closed',
                    'blocked_betting_side': wager_id,
                }, status=409)
            return render(request, 'SmartWagers/administrator.html', {
                'M_total_bet': format(int(meron_total), ','),
                'M_payout': meron_payout,
                'W_total_bet': format(int(wala_total), ','),
                'W_payout': wala_payout,
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

    # Allow reprint for the current live fight and the 2 most recently
    # completed fights so tellers can still reprint recent tickets.
    _, _, _, current_fightnum = services.get_fight_status()
    recent_completed = list(
        result_qs.order_by('-fightnum').values_list('fightnum', flat=True)[:2]
    )
    allowed_reprint = set(recent_completed) | {current_fightnum}

    return render(request, 'SmartWagers/teller_report.html', {
        'wagers': wagers,
        'total_amount': total_amount,
        'total_count': total_count,
        'teller_name': str(request.user),
        'active_event': active_event,
        'completed_fights': completed_fights,
        'allowed_reprint': allowed_reprint,
    })


def _compute_teller_balance(user, event=None, apply_end_bound=True):
    """Return (balance, grand_total) for a teller, optionally scoped to an event.

    When *event* is supplied, only wagers and transactions created within the
    event's time window are counted.  This allows grand totals to restart with
    each new event.

    apply_end_bound controls whether the event's ended_at timestamp is used as
    an upper bound.  Pass False when the system is between events so that
    post-event settlement transactions (REMIT/COLLECT issued after ended_at)
    are still counted in the last event's totals.

    grand_total = raw sum of registered bets in scope.
    balance     = grand_total − remits + collects (in scope).
    """
    username = str(user)
    wager_qs = Wagers.objects.filter(cashier=username, registered=True)
    txn_qs = TellerTransaction.objects.filter(user=user)

    if event is not None:
        wager_qs = wager_qs.filter(created_at__gte=event.started_at)
        txn_qs = txn_qs.filter(created_at__gte=event.started_at)
        if apply_end_bound and event.ended_at:
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
    event_scope, apply_end_bound = services.get_event_scope()
    balance, grand_total = _compute_teller_balance(request.user, event=event_scope, apply_end_bound=apply_end_bound)
    return JsonResponse({'ok': True, 'balance': balance, 'grand_total': grand_total})


@group_required('teller')
def get_pending_payouts(request):
    """Return the count and total amount of this teller's unclaimed winning/refund tickets."""
    username = str(request.user)
    active_event = services.get_active_event()

    # Base: registered, uncashed wagers by this teller in the active event
    pending_qs = Wagers.objects.filter(cashier=username, registered=True, cashed_out=False)
    if active_event is not None:
        pending_qs = pending_qs.filter(created_at__gte=active_event.started_at)
        if active_event.ended_at:
            pending_qs = pending_qs.filter(created_at__lte=active_event.ended_at)

    # Collect fight results within the event so we know which fights are decided
    results_qs = Fight_Results.objects.all()
    if active_event is not None:
        results_qs = results_qs.filter(event=active_event)

    # Build a filter that matches only payable unclaimed tickets:
    #   MERON/WALA result  → only the winning side for that fight
    #   DRAW/CANCELLED     → all bets for that fight (full refund)
    payable_q = Q()
    for r in results_qs.values('fightnum', 'side'):
        fn, side = r['fightnum'], r['side'].upper()
        if side in ('DRAW', 'CANCELLED'):
            payable_q |= Q(fightnum=fn)
        else:
            payable_q |= Q(fightnum=fn, side=side)

    if not payable_q:
        return JsonResponse({'ok': True, 'count': 0, 'total': 0})

    payable_qs = pending_qs.filter(payable_q)
    agg = payable_qs.aggregate(count=Count('id'), total=Sum('wager'))
    return JsonResponse({
        'ok': True,
        'count': agg['count'] or 0,
        'total': agg['total'] or 0,
    })


@group_required('teller')
def get_teller_fight_totals(request):
    """Return this teller's MERON and WALA bet totals for the current active fight only."""
    username = str(request.user)
    _, _, _, fightnum = services.get_fight_status()

    if fightnum is None:
        return JsonResponse({'ok': True, 'fightnum': None, 'meron_total': 0, 'wala_total': 0})

    base_qs = Wagers.objects.filter(
        cashier=username,
        fightnum=fightnum,
        registered=True,
    )

    # Scope to the active event's time window so bets from a previous event
    # with the same fight number are never counted.
    active_event = services.get_active_event()
    if active_event is not None:
        base_qs = base_qs.filter(created_at__gte=active_event.started_at)
        if active_event.ended_at:
            base_qs = base_qs.filter(created_at__lte=active_event.ended_at)

    meron_total = base_qs.filter(side='MERON').aggregate(total=Sum('wager'))['total'] or 0
    wala_total  = base_qs.filter(side='WALA').aggregate(total=Sum('wager'))['total'] or 0

    return JsonResponse({
        'ok': True,
        'fightnum': fightnum,
        'meron_total': meron_total,
        'wala_total': wala_total,
    })


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
    logger.info(
        "TELLER TXN: txn_id=%s type=%s amount=%.2f teller=%s",
        txn.transaction_id, transaction_type, amount, request.user.username,
    )

    event_scope, apply_end_bound = services.get_event_scope()
    balance, grand_total = _compute_teller_balance(request.user, event=event_scope, apply_end_bound=apply_end_bound)
    return JsonResponse({
        'ok': True,
        'print_required': services.is_wager_receipt_printing_enabled(),
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
    event_scope, apply_end_bound = services.get_event_scope()

    teller_data = []
    for teller in tellers:
        balance, grand_total = _compute_teller_balance(teller, event=event_scope, apply_end_bound=apply_end_bound)
        txn_qs = TellerTransaction.objects.filter(user=teller)
        if event_scope is not None:
            txn_qs = txn_qs.filter(created_at__gte=event_scope.started_at)
            if apply_end_bound and event_scope.ended_at:
                txn_qs = txn_qs.filter(created_at__lte=event_scope.ended_at)
        transactions = txn_qs.order_by('-created_at')

        ts, _ = TellerStatus.objects.get_or_create(user=teller)
        is_online = ts.is_online

        wager_qs = Wagers.objects.filter(cashier=str(teller), registered=True)
        if event_scope is not None:
            wager_qs = wager_qs.filter(created_at__gte=event_scope.started_at)
            if apply_end_bound and event_scope.ended_at:
                wager_qs = wager_qs.filter(created_at__lte=event_scope.ended_at)
        has_activity = not is_online and wager_qs.exists()

        teller_data.append({
            'user': teller,
            'display_name': (f"{teller.first_name} {teller.last_name}".strip() or teller.username),
            'balance': balance,
            'grand_total': grand_total,
            'transactions': transactions,
            'is_online': is_online,
            'has_activity': has_activity,
        })

    setting = Settings.objects.order_by('-id').first()
    teller_max_balance = setting.teller_max_balance if setting else 0.0
    teller_min_balance = setting.teller_min_balance if setting else 0.0

    return render(request, 'SmartWagers/admin_tellers.html', {
        'teller_data': teller_data,
        'active_event': active_event,
        'teller_max_balance': teller_max_balance,
        'teller_min_balance': teller_min_balance,
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
    logger.info(
        "ADMIN TXN: txn_id=%s type=%s amount=%.2f teller=%s by_admin=%s",
        txn.transaction_id, transaction_type, amount, teller.username, request.user.username,
    )

    scope, apply_end_bound = services.get_event_scope()
    balance, grand_total = _compute_teller_balance(teller, event=scope, apply_end_bound=apply_end_bound)
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
    logger.info("EVENT START (view): id=%s name=%r admin=%s", event.id, event.name, request.user.username)

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
        logger.warning("END EVENT (view): no active event found — admin=%s", request.user.username)
        return JsonResponse({'ok': False, 'error': 'no_active_event'}, status=404)

    notify_event_change()
    logger.info("EVENT END (view): id=%s name=%r admin=%s", event.id, event.name, request.user.username)

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

    # Commission / fight results
    plasada = services.get_comm_val()
    fight_results_qs = Fight_Results.objects.filter(event=event).order_by('fightnum')
    fight_commissions = [
        {
            'fightnum': r.fightnum,
            'side': r.side,
            'mtotal': r.mtotal,
            'wtotal': r.wtotal,
            'mpayout': r.mpayout,
            'wpayout': r.wpayout,
            'totalpot': r.totalpot,
            'commission': 0 if r.side in ('CANCELLED', 'DRAW') else r.totalpot * plasada,
            'date': r.date,
        }
        for r in fight_results_qs
    ]
    total_pot_all = sum(fc['totalpot'] for fc in fight_commissions if fc['side'] not in ('CANCELLED', 'DRAW'))
    total_commission = sum(fc['commission'] for fc in fight_commissions)

    # Build map of winning fights {fightnum: winning_side} for unclaimed bet detection.
    # DRAW and CANCELLED are paid out immediately, so only MERON/WALA produce unclaimed tickets.
    winning_fights = {
        r.fightnum: r.side
        for r in fight_results_qs
        if r.side not in ('CANCELLED', 'DRAW')
    }

    # Fetch all unclaimed winning wagers for this event in one DB hit.
    # Build both an aggregate dict (for the summary table) and a full list
    # (for the detailed transaction-ID breakdown at the bottom).
    unclaimed_by_cashier: dict = {}
    unclaimed_detail_list: list = []
    if winning_fights:
        winning_filter = Q()
        for fn, ws in winning_fights.items():
            winning_filter |= Q(fightnum=fn, side=ws)

        unclaimed_qs = Wagers.objects.filter(
            winning_filter,
            cashed_out=False,
            registered=True,
            created_at__gte=event.started_at,
        ).exclude(cashier='System').order_by('cashier', 'fightnum', 'transactionid')

        if event.ended_at:
            unclaimed_qs = unclaimed_qs.filter(created_at__lte=event.ended_at)

        # Aggregate totals per cashier for the summary table
        for row in unclaimed_qs.values('cashier').annotate(
            count=Count('id'), total=Sum('wager')
        ):
            unclaimed_by_cashier[row['cashier']] = {
                'count': row['count'],
                'total': row['total'] or 0.0,
            }

        # Full row-level detail for the transaction-ID breakdown section
        for w in unclaimed_qs.values(
            'transactionid', 'fightnum', 'side', 'wager', 'cashier', 'created_at'
        ):
            unclaimed_detail_list.append(w)

    # Per-teller aggregates
    teller_data = []
    grand_total_all = 0.0
    total_unclaimed_all = 0.0
    total_bets_count_all = 0

    for teller in tellers:
        balance, grand_total = _compute_teller_balance(teller, event=event)
        username = str(teller)

        wager_qs = Wagers.objects.filter(
            cashier=username, registered=True,
            created_at__gte=event.started_at,
        )
        if event.ended_at:
            wager_qs = wager_qs.filter(created_at__lte=event.ended_at)

        bet_stats = wager_qs.aggregate(
            bet_count=Count('id'),
            meron_total=Sum('wager', filter=Q(side='MERON')),
            wala_total=Sum('wager', filter=Q(side='WALA')),
            meron_count=Count('id', filter=Q(side='MERON')),
            wala_count=Count('id', filter=Q(side='WALA')),
        )
        bet_count = bet_stats['bet_count'] or 0
        meron_total = bet_stats['meron_total'] or 0.0
        wala_total = bet_stats['wala_total'] or 0.0
        meron_count = bet_stats['meron_count'] or 0
        wala_count = bet_stats['wala_count'] or 0

        txn_qs = TellerTransaction.objects.filter(
            user=teller,
            created_at__gte=event.started_at,
        )
        if event.ended_at:
            txn_qs = txn_qs.filter(created_at__lte=event.ended_at)

        txn_stats = txn_qs.aggregate(
            remit_total=Sum('amount', filter=Q(transaction_type=TellerTransaction.REMIT)),
            collect_total=Sum('amount', filter=Q(transaction_type=TellerTransaction.COLLECT)),
            payout_total=Sum('amount', filter=Q(transaction_type=TellerTransaction.PAYOUT)),
        )
        remit_total   = txn_stats['remit_total']   or 0.0
        collect_total = txn_stats['collect_total'] or 0.0
        payout_total  = txn_stats['payout_total']  or 0.0

        unclaimed_info = unclaimed_by_cashier.get(username, {'count': 0, 'total': 0.0})

        teller_data.append({
            'user': teller,
            'display_name': (f"{teller.first_name} {teller.last_name}".strip() or teller.username),
            'bet_count':      bet_count,
            'meron_count':    meron_count,
            'wala_count':     wala_count,
            'grand_total':    grand_total,
            'meron_total':    meron_total,
            'wala_total':     wala_total,
            'payout_total':   payout_total,
            'remit_total':    remit_total,
            'collect_total':  collect_total,
            'unclaimed_count': unclaimed_info['count'],
            'unclaimed_total': unclaimed_info['total'],
            'balance':        balance,
        })
        grand_total_all       += grand_total
        total_unclaimed_all   += unclaimed_info['total']
        total_bets_count_all  += bet_count

    return render(request, 'SmartWagers/event_report.html', {
        'event': event,
        'all_events': all_events,
        'teller_data': teller_data,
        'grand_total_all': grand_total_all,
        'total_unclaimed_all': total_unclaimed_all,
        'total_bets_count_all': total_bets_count_all,
        'unclaimed_detail_list': unclaimed_detail_list,
        'fight_commissions': fight_commissions,
        'total_pot_all': total_pot_all,
        'total_commission': total_commission,
        'plasada': plasada,
        'plasada_pct': plasada * 100,
    })


@group_required('admin')
def admin_claim_old_ticket(request):
    """Admin-only: pay out a winning ticket from a specified past event and teller.

    Accepts POST with: event_id, teller_username, transaction_id.
    Returns JSON with the payout result or an error code.
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'method_not_allowed'}, status=405)

    event_id       = request.POST.get('event_id', '').strip()
    teller_username = request.POST.get('teller_username', '').strip()
    transaction_id = request.POST.get('transaction_id', '').strip()

    if not event_id or not teller_username or not transaction_id:
        return JsonResponse({'ok': False, 'error': 'missing_params'}, status=400)

    event = Event.objects.filter(pk=event_id).first()
    if event is None:
        return JsonResponse({'ok': False, 'error': 'event_not_found'}, status=404)

    # Zero-pad to 6 digits to match stored format, but also allow the raw
    # value in case the admin typed it without leading zeros.
    padded_id = transaction_id.zfill(6)
    result = services.payout_old_ticket(event, teller_username, padded_id)
    if not result['ok'] and result.get('error') == 'notfound':
        # Try without padding in case the stored ID is different.
        result = services.payout_old_ticket(event, teller_username, transaction_id)

    return JsonResponse(result)


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
        commission = 0 if result.side in ('CANCELLED', 'DRAW') else result.totalpot * plasada
        fight_commissions.append({
            'fightnum': result.fightnum,
            'side': result.side,
            'totalpot': result.totalpot,
            'commission': commission,
            'date': result.date,
        })
        total_commission += commission
        if result.side not in ('CANCELLED', 'DRAW'):
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
def admin_teller_alerts(request):
    """Lightweight JSON endpoint: returns tellers whose balance is out of range."""
    try:
        teller_group = Group.objects.get(name='teller')
        tellers = teller_group.user_set.all()
    except Group.DoesNotExist:
        tellers = []

    active_event = services.get_active_event()
    event_scope, apply_end_bound = services.get_event_scope()
    setting = Settings.objects.order_by('-id').first()
    threshold   = setting.teller_max_balance  if setting else 0.0
    min_balance = setting.teller_min_balance  if setting else 0.0

    alerts = []
    for teller in tellers:
        name = f"{teller.first_name} {teller.last_name}".strip() or teller.username
        ts, _ = TellerStatus.objects.get_or_create(user=teller)

        if not ts.is_online:
            # Check if this offline teller has any wager activity in the current scope
            wager_qs = Wagers.objects.filter(cashier=str(teller), registered=True)
            if event_scope is not None:
                wager_qs = wager_qs.filter(created_at__gte=event_scope.started_at)
                if apply_end_bound and event_scope.ended_at:
                    wager_qs = wager_qs.filter(created_at__lte=event_scope.ended_at)
            if wager_qs.exists():
                alerts.append({
                    'name': name,
                    'teller_id': teller.pk,
                    'balance': 0,
                    'alert': 'offline_active',
                })
            continue

        balance, _ = _compute_teller_balance(teller, event=active_event)
        if threshold > 0 and balance > threshold:
            alerts.append({'name': name, 'teller_id': teller.pk, 'balance': round(balance, 2), 'alert': 'remit'})
        elif balance < min_balance:
            alerts.append({'name': name, 'teller_id': teller.pk, 'balance': round(balance, 2), 'alert': 'borrow'})

    return JsonResponse({
        'ok': True,
        'threshold': threshold,
        'min_balance': min_balance,
        'alert_count': len(alerts),
        'alerts': alerts,
    })


@group_required('admin')
def toggle_teller_online(request):
    """Admin endpoint: toggle a teller's online/offline status."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'method_not_allowed'}, status=405)

    try:
        teller_id = int(request.POST.get('teller_id', 0))
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'invalid_teller_id'}, status=400)

    is_online_raw = request.POST.get('is_online', 'true').strip().lower()
    is_online = is_online_raw in ('true', '1', 'yes')

    try:
        teller_group = Group.objects.get(name='teller')
        teller = teller_group.user_set.get(pk=teller_id)
    except (Group.DoesNotExist, User.DoesNotExist):
        return JsonResponse({'ok': False, 'error': 'teller_not_found'}, status=404)

    ts, _ = TellerStatus.objects.get_or_create(user=teller)
    was_online = ts.is_online
    ts.is_online = is_online
    ts.save(update_fields=['is_online'])

    # When a previously-offline teller is brought online mid-event, issue their
    # initial fund as a COLLECT (borrow) so their ledger starts correctly.
    fund_issued = False
    if is_online and not was_online:
        active_event = services.get_active_event()
        if active_event is not None:
            setting = Settings.objects.order_by('-id').first()
            initial_fund = setting.teller_initial_fund if setting else 10000.0
            if initial_fund > 0:
                TellerTransaction.objects.create(
                    user=teller,
                    transaction_type=TellerTransaction.COLLECT,
                    amount=round(initial_fund, 2),
                )
                fund_issued = True

    return JsonResponse({
        'ok': True,
        'teller_id': teller_id,
        'is_online': is_online,
        'fund_issued': fund_issued,
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
            logger.info("SETTINGS: plasada updated to %.4f by admin=%s", new_plasada, request.user.username)
            return JsonResponse({'ok': True, 'plasada': new_plasada, 'plasada_pct': new_plasada * 100})

        if action == 'update_teller_max_balance':
            try:
                new_max = float(request.POST.get('teller_max_balance', ''))
                if new_max < 0:
                    return JsonResponse({'ok': False, 'error': 'Threshold must be 0 or greater (0 = no limit)'}, status=400)
            except (ValueError, TypeError):
                return JsonResponse({'ok': False, 'error': 'Invalid threshold value'}, status=400)

            setting = Settings.objects.order_by('-id').first()
            if setting is None:
                setting = Settings(teller_max_balance=new_max)
            else:
                setting.teller_max_balance = new_max
            setting.save()
            return JsonResponse({'ok': True, 'teller_max_balance': new_max})

        if action == 'update_teller_initial_fund':
            try:
                new_fund = float(request.POST.get('teller_initial_fund', ''))
                if new_fund < 0:
                    return JsonResponse({'ok': False, 'error': 'Initial fund must be 0 or greater'}, status=400)
            except (ValueError, TypeError):
                return JsonResponse({'ok': False, 'error': 'Invalid initial fund value'}, status=400)

            setting = Settings.objects.order_by('-id').first()
            if setting is None:
                setting = Settings(teller_initial_fund=new_fund)
            else:
                setting.teller_initial_fund = new_fund
            setting.save()
            return JsonResponse({'ok': True, 'teller_initial_fund': new_fund})

        if action == 'update_teller_min_balance':
            try:
                new_min = float(request.POST.get('teller_min_balance', ''))
                if new_min < 0:
                    return JsonResponse({'ok': False, 'error': 'Min on-hand must be 0 or greater (0 = no warning)'}, status=400)
            except (ValueError, TypeError):
                return JsonResponse({'ok': False, 'error': 'Invalid min on-hand value'}, status=400)

            setting = Settings.objects.order_by('-id').first()
            if setting is None:
                setting = Settings(teller_min_balance=new_min)
            else:
                setting.teller_min_balance = new_min
            setting.save()
            return JsonResponse({'ok': True, 'teller_min_balance': new_min})

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

            old_side = result.side
            result.side = new_side
            result.save(update_fields=['side'])
            logger.info(
                "SETTINGS: fight_result id=%s fight=%s side changed %s→%s by admin=%s",
                result_id, result.fightnum, old_side, new_side, request.user.username,
            )

            channel_layer = get_channel_layer()
            if channel_layer is not None:
                for group_name in ['index', 'user', 'administrator']:
                    async_to_sync(channel_layer.group_send)(group_name, {
                        'type': 'send_data',
                        'refresh_trends': True,
                    })

            return JsonResponse({'ok': True, 'result_id': result_id, 'side': new_side})

        return JsonResponse({'ok': False, 'error': 'Unknown action'}, status=400)

    plasada = services.get_comm_val()
    fight_results = Fight_Results.objects.all().order_by('-fightnum')
    if active_event is not None:
        fight_results = fight_results.filter(event=active_event)

    setting = Settings.objects.order_by('-id').first()
    teller_max_balance  = setting.teller_max_balance  if setting else 0.0
    teller_initial_fund = setting.teller_initial_fund if setting else 10000.0
    teller_min_balance  = setting.teller_min_balance  if setting else 0.0

    return render(request, 'SmartWagers/admin_settings.html', {
        'plasada': plasada,
        'plasada_pct': plasada * 100,
        'fight_results': fight_results,
        'active_event': active_event,
        'teller_max_balance': teller_max_balance,
        'teller_initial_fund': teller_initial_fund,
        'teller_min_balance': teller_min_balance,
    })
