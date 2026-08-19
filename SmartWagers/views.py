from django.shortcuts import render, redirect
from django.urls import reverse
from django.http import JsonResponse, HttpResponseForbidden
from django.db import transaction as db_transaction
from django.db.models import Sum, Count, Q, F
from django.views.decorators.http import require_GET, require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie
from . import services as services
from . import masterlock
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.contrib.auth.decorators import login_required
from .models import (
    AdminBankTransaction, Event, Fight_Results, SessionLog, Settings,
    TellerCloseOut, TellerStatus, TellerTransaction, Wagers,
)
from django.contrib.auth.models import Group, User
from django.contrib.auth.views import LoginView
from django.contrib.auth.views import LogoutView
from django.utils.timezone import now
import logging
import math

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


def role_home_url(user):
    """Return the landing URL for this user's primary role, or None."""
    groups = set(user.groups.values_list('name', flat=True))
    if 'admin' in groups:
        return reverse('admin-page')
    if 'teller' in groups:
        return reverse('user-page')
    if 'display' in groups:
        return reverse('index')
    return None


def unauthorized(request):
    """Shown when a user has no admin/teller/display group."""
    return render(request, '403.html', status=403)


@require_GET
def health(request):
    """Process readiness probe — always 200 while Daphne is up."""
    status = masterlock.get_status(touch_heartbeat=False)
    response = JsonResponse({
        'ok': True,
        'locked': bool(status.get('locked')),
        'enabled': bool(status.get('enabled')),
        'valid_until': status.get('valid_until'),
    })
    response['Cache-Control'] = 'no-store'
    return response


@ensure_csrf_cookie
@require_http_methods(['GET', 'POST'])
def master_lock_page(request):
    """
    Standalone activation page (accessible while locked).
    GET renders the form; POST enable/extend/disable with the master key.
    """
    client_id = _get_client_ip(request)
    status = masterlock.get_status(touch_heartbeat=False)

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip().lower()
        # Disable is only available to logged-in superusers (Settings page).
        # The locked recovery page may only enable/extend with the master key.
        if action == 'disable':
            if not (request.user.is_authenticated and request.user.is_superuser):
                return JsonResponse(
                    {'ok': False, 'error': 'Only superusers can disable the master lock.'},
                    status=403,
                )
        master_key = request.POST.get('master_key') or ''
        try:
            if action == 'enable':
                status = masterlock.enable_lock(master_key=master_key, client_id=client_id)
            elif action == 'extend':
                status = masterlock.extend_lock(master_key=master_key, client_id=client_id)
            elif action == 'disable':
                status = masterlock.disable_lock(master_key=master_key, client_id=client_id)
            else:
                return JsonResponse({'ok': False, 'error': masterlock.GENERIC_AUTH_ERROR}, status=400)

            logger.info(
                'MASTER LOCK UI action=%s ok=1 locked=%s ip=%s',
                action, status.get('locked'), client_id,
            )
            payload = {'ok': True, **{k: status.get(k) for k in (
                'locked', 'enabled', 'valid_until', 'extension_count', 'extension_days',
            )}}
            # Prefer JSON for fetch; form posts without Accept still get JSON.
            return JsonResponse(payload)
        except masterlock.MasterLockAuthError:
            logger.warning('MASTER LOCK UI action=%s rejected ip=%s', action, client_id)
            return JsonResponse({'ok': False, 'error': masterlock.GENERIC_AUTH_ERROR}, status=403)
        except masterlock.MasterLockError as exc:
            logger.warning('MASTER LOCK UI action=%s failed ip=%s err=%s', action, client_id, exc)
            return JsonResponse({'ok': False, 'error': masterlock.GENERIC_AUTH_ERROR}, status=400)
        finally:
            # Avoid retaining the submitted key in locals longer than needed.
            master_key = ''

    # If already unlocked, send operators back to login / home.
    if not status.get('locked'):
        if request.user.is_authenticated:
            home = role_home_url(request.user)
            if home:
                return redirect(home)
        return redirect('login')

    response = render(request, 'SmartWagers/master_lock.html', {
        'lock_status': status,
        'extension_days': masterlock.EXTENSION_DAYS,
    })
    response['Cache-Control'] = 'no-store'
    return response


@require_GET
def master_lock_status(request):
    """Return current master lock status (JSON)."""
    status = masterlock.get_status(touch_heartbeat=False)
    response = JsonResponse({
        'ok': True,
        'locked': bool(status.get('locked')),
        'enabled': bool(status.get('enabled')),
        'valid_until': status.get('valid_until'),
        'extension_days': masterlock.EXTENSION_DAYS,
    })
    response['Cache-Control'] = 'no-store'
    return response


def teller_is_online(user):
    """Return True if the teller's admin-controlled online flag is set."""
    ts, _ = TellerStatus.objects.get_or_create(user=user, defaults={'is_online': True})
    return ts.is_online


def teller_offline_response():
    """JSON response when an offline teller attempts a restricted action."""
    return JsonResponse({'ok': False, 'error': 'teller_offline'}, status=403)


def teller_station_closed_response():
    """JSON response when a teller with a closed station attempts a restricted action."""
    return JsonResponse({'ok': False, 'error': 'station_closed'}, status=403)


def teller_action_blocked_response(user):
    """Return the appropriate 403 when a teller action is blocked."""
    if services.teller_station_is_closed(user):
        return teller_station_closed_response()
    if not teller_is_online(user):
        return teller_offline_response()
    return None


def notify_teller_online_status(teller_id, is_online):
    """Broadcast a teller's online/offline change to all teller WebSocket clients."""
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(
        'user',
        {
            'type': 'send_data',
            'teller_online': is_online,
            'teller_id': teller_id,
        },
    )


class RoleBasedLoginView(LoginView):
    # If the session cookie is still valid (browser closed without logout),
    # send the user straight to their role page instead of showing login again.
    redirect_authenticated_user = True

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
        # Intentionally ignore ?next= so a teller cannot be sent to /administrator
        # (or any other path) via the login redirect parameter.
        url = role_home_url(self.request.user)
        if url:
            return url
        logger.warning(
            "LOGIN: user=%s has no recognized group — redirecting to unauthorized",
            self.request.user.username,
        )
        return reverse('unauthorized')


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

            # Wrong role: show Access Denied modal for browser navigations
            # (e.g. teller clicks Main/Admin). APIs get a JSON 403.
            logger.warning(
                "FORBIDDEN: user=%s requires group=%s method=%s path=%s",
                request.user.username, group_name, request.method, request.path,
            )
            if (
                request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                or 'application/json' in request.headers.get('Accept', '')
                or request.method not in ('GET', 'HEAD')
            ):
                return JsonResponse({'ok': False, 'error': 'Forbidden'}, status=403)
            return render(request, '403.html', status=403)
        return _wrapped_view
    return decorator

def get_teller_information(request):
    user = request.user
    username = user.username
    full_name = f"{user.first_name} {user.last_name}"
    email = user.email
    logger.debug("get_teller_information: user=%s", username)

@login_required
def get_button_state_view(request):
    mstate, wstate = services.get_control_status()
    return JsonResponse({"mstate": mstate, "wstate": wstate})

@login_required
def get_fight_results_view(request):
    results = services.get_fight_results('fightnum', 'side', 'odds')
    return JsonResponse(list(results), safe=False)

@login_required
def get_fight_status_view(request):
    overall_status, meron_status, wala_status, fightnum = services.get_fight_status()
    active_event = services.get_active_event()
    return JsonResponse({
        "overall_status": overall_status,
        "meron_status": meron_status,
        "wala_status": wala_status,
        "fightnum": fightnum,
        "event_active": active_event is not None,
        "event_name": active_event.name if active_event else "",
    })

@login_required
def get_pot_values(request):
    m_total_pot, m_payout, w_total_pot, w_payout, total_pot, fight_num = services.get_Totals()
    return JsonResponse({"M_total_bet": m_total_pot, "M_payout": m_payout, "W_total_bet": w_total_pot, "W_payout": w_payout, "Total_pot": total_pot, "fight_num": fight_num})

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

    if request.user.groups.filter(name='teller').exists():
        blocked = teller_action_blocked_response(request.user)
        if blocked is not None:
            return blocked

    transaction_id = request.POST.get('transaction_id', '').strip()
    if not transaction_id:
        return JsonResponse({'ok': False, 'error': 'missing_transaction_id'}, status=400)

    # Tellers may only reprint their own tickets; admins may reprint any.
    cashier_filter = None
    remit_user_filter = None
    is_admin = request.user.groups.filter(name='admin').exists()
    is_teller = request.user.groups.filter(name='teller').exists()
    if is_teller and not is_admin:
        cashier_filter = str(request.user)
        remit_user_filter = request.user

    print_required = services.is_wager_receipt_printing_enabled()

    if transaction_id.lower() == 'test':
        event_scope, apply_end_bound = services.get_event_scope()
        if is_admin:
            current_total = services.get_admin_fund_summary(
                event=event_scope,
                apply_end_bound=apply_end_bound,
            )['balance']
        else:
            current_total, _ = _compute_teller_balance(
                request.user,
                event=event_scope,
                apply_end_bound=apply_end_bound,
            )
        return JsonResponse({
            'ok': True,
            'receipt_type': 'test',
            'print_required': print_required,
            'receipt': {
                # Keep wager compatibility so older local print agents still
                # produce a usable test slip and barcode.
                'receipt_type': 'wager',
                'test_print': True,
                'transaction_id': 'test',
                'fightnum': 'TEST',
                'side': 'PRINTER TEST',
                'cashier': str(request.user),
                'amount': current_total,
                'date': now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        })

    receipt = services.lookup_wager_for_reprint(
        transaction_id, cashier=cashier_filter,
    )
    if receipt is not None:
        return JsonResponse({
            'ok': True,
            'receipt_type': 'wager',
            'print_required': print_required,
            'receipt': receipt,
        })

    remit_receipt = services.lookup_remit_for_reprint(
        transaction_id, user=remit_user_filter,
    )
    if remit_receipt is not None:
        return JsonResponse({
            'ok': True,
            'receipt_type': 'remit',
            'print_required': print_required,
            'receipt': remit_receipt,
        })

    return JsonResponse({'ok': False, 'error': 'notfound'})

def notify_bet_updates():
    """Broadcast current pot values to all live UI groups after a wager changes."""
    channel_layer = get_channel_layer()
    if channel_layer is None:
        logger.error("notify_bet_updates: channel layer is None — WebSocket broadcast skipped")
        return

    mtotal, mpayout, wtotal, wpayout, _total_bet, fightnum = services.get_Totals()
    payload = {
        'type': 'send_data',
        'mtotal': format(int(mtotal), ','),
        'mpayout': mpayout,
        'wtotal': format(int(wtotal), ','),
        'wpayout': wpayout,
        'fightnum': fightnum,
    }
    for group in ["index", "user", "administrator"]:
        async_to_sync(channel_layer.group_send)(group, payload)

def notify_event_change():
    """Broadcast an event-state change to all connected clients so they re-poll get_fight_status_view."""
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    overall_status, meron_status, wala_status, fightnum = services.get_fight_status()
    for group in ["administrator", "user", "index"]:
        async_to_sync(channel_layer.group_send)(
            group,
            {
                'type': 'send_data',
                'fight_status': 'event_changed',
                'overall_status': overall_status,
                'meron_status': meron_status,
                'wala_status': wala_status,
                'fightnum': fightnum,
            }
        )

def wager_ajax_response(saved_wager, duplicate=False):
    meron_total, meron_payout, wala_total, wala_payout, total_bet, fightnum = services.get_Totals()
    notify_bet_updates()
    return JsonResponse({
        'ok': True,
        'pending': False,
        'duplicate': duplicate,
        'transaction_id': saved_wager.transactionid,
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
    admin_fund = services.get_admin_fund_summary()

    logger.debug("Main_admin page: user=%s", request.user)

    if request.method == 'POST':
        try:
            wager = int(request.POST.get('wager_value', 0))
        except (ValueError, TypeError):
            wager = 0
        wager_id = request.POST.get('wager_id', None)

        if wager <= 0:
            return JsonResponse({'ok': False, 'error': 'invalid_amount'}, status=400)

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
                'admin_fund': admin_fund,
            })

        if request.headers.get('x-requested-with') != 'XMLHttpRequest':
            return HttpResponseForbidden("AJAX submission is required to place a bet.")

        # Register first, then let the client print. Failed prints can be reprinted.
        # require_side_open=False: admins may bet on a per-side-closed market.
        try:
            saved_wager, created = services.add_wager(
                wager, wager_id, current_fn,
                cashier=str(request.user),
                require_side_open=False,
                client_request_id=request.POST.get('client_request_id'),
            )
        except services.BettingClosedError:
            return JsonResponse({
                'ok': False,
                'error': 'betting_closed',
                'blocked_betting_side': wager_id,
            }, status=409)
        return wager_ajax_response(saved_wager, duplicate=not created)

    return render( request, 'SmartWagers/administrator.html', {
        'M_total_bet' : format(int(meron_total), ','),
        'M_payout' : meron_payout,
        'W_total_bet' : format(int(wala_total), ','),
        'W_payout' : wala_payout,
        'admin_fund': admin_fund,
    })


def _admin_fund_payload(event):
    summary = services.get_admin_fund_summary(event=event)
    transactions = AdminBankTransaction.objects.filter(
        event=event,
    ).select_related('admin')[:20]
    return {
        'ok': True,
        'active': True,
        'event_id': event.pk,
        'event_name': event.name,
        **summary,
        'transactions': [
            {
                'id': txn.pk,
                'transaction_type': txn.transaction_type,
                'amount': round(txn.amount, 2),
                'admin': (
                    f"{txn.admin.first_name} {txn.admin.last_name}".strip()
                    or txn.admin.username
                ),
                'created_at': txn.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            }
            for txn in transactions
        ],
    }


@group_required('admin')
def admin_fund_status(request):
    if request.method != 'GET':
        return JsonResponse(
            {'ok': False, 'error': 'method_not_allowed'},
            status=405,
        )
    event = services.get_active_event()
    if event is None:
        return JsonResponse({
            'ok': True,
            'active': False,
            'balance': 0.0,
            'bank_borrowed': 0.0,
            'bank_remitted': 0.0,
            'net_bank_funding': 0.0,
            'transactions': [],
        })
    return JsonResponse(_admin_fund_payload(event))


@group_required('admin')
def admin_bank_transaction(request):
    if request.method != 'POST':
        return JsonResponse(
            {'ok': False, 'error': 'method_not_allowed'},
            status=405,
        )

    transaction_type = request.POST.get(
        'transaction_type', '',
    ).strip().upper()
    if transaction_type not in (
        AdminBankTransaction.BORROW,
        AdminBankTransaction.REMIT,
    ):
        return JsonResponse(
            {'ok': False, 'error': 'invalid_type'},
            status=400,
        )
    try:
        amount = round(float(request.POST.get('amount', '')), 2)
    except (ValueError, TypeError):
        return JsonResponse(
            {'ok': False, 'error': 'invalid_amount'},
            status=400,
        )
    if amount <= 0:
        return JsonResponse(
            {'ok': False, 'error': 'invalid_amount'},
            status=400,
        )

    with db_transaction.atomic():
        Event.objects.filter(is_active=True).update(
            is_active=F('is_active'),
        )
        event = Event.objects.filter(is_active=True).order_by(
            '-started_at',
        ).first()
        if event is None:
            return JsonResponse(
                {'ok': False, 'error': 'no_active_event'},
                status=409,
            )

        if transaction_type == AdminBankTransaction.REMIT:
            balance = services.get_admin_fund_summary(event=event)['balance']
            if amount > balance:
                return JsonResponse({
                    'ok': False,
                    'error': 'exceeds_admin_fund',
                    'balance': balance,
                }, status=400)

        txn = AdminBankTransaction.objects.create(
            event=event,
            admin=request.user,
            transaction_type=transaction_type,
            amount=amount,
        )

    logger.info(
        "ADMIN BANK TXN: id=%s type=%s amount=%.2f admin=%s event=%s",
        txn.pk, transaction_type, amount, request.user.username, event.pk,
    )
    payload = _admin_fund_payload(event)
    payload.update({
        'print_required': services.is_wager_receipt_printing_enabled(),
        'created_transaction': {
            'id': txn.pk,
            'transaction_id': f"B{txn.pk:06d}",
            'transaction_type': txn.transaction_type,
            'amount': round(txn.amount, 2),
            'admin': (
                f"{txn.admin.first_name} {txn.admin.last_name}".strip()
                or txn.admin.username
            ),
            'created_at': txn.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        },
    })
    return JsonResponse(payload)

   
@group_required('teller')
def Teller(request):
    #initialize
    meron_total, meron_payout, wala_total, wala_payout, total_bet , fightnum= services.get_Totals() 
    #comm = services.get_comm_val()
    current_fn = services.get_fightnum()
    is_online = teller_is_online(request.user)
    station_closed = services.teller_station_is_closed(request.user)

    def user_page_context(**extra):
        ctx = {
            'M_total_bet': format(int(meron_total), ','),
            'M_payout': meron_payout,
            'W_total_bet': format(int(wala_total), ','),
            'W_payout': wala_payout,
            'teller_is_online': is_online,
            'teller_station_closed': station_closed,
            'teller_id': request.user.pk,
        }
        ctx.update(extra)
        return ctx

    if request.method == 'POST':
        blocked = teller_action_blocked_response(request.user)
        if blocked is not None:
            return blocked

        try:
            wager = int(request.POST.get('wager_value', 0))
        except (ValueError, TypeError):
            wager = 0
        wager_id = request.POST.get('wager_id', None)

        if wager <= 0:
            return JsonResponse({'ok': False, 'error': 'invalid_amount'}, status=400)

        if not services.is_betting_open(wager_id):
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'ok': False,
                    'error': 'betting_closed',
                    'blocked_betting_side': wager_id,
                }, status=409)
            return render(request, 'SmartWagers/user.html', user_page_context(
                blocked_betting_side=wager_id,
            ))

        if request.headers.get('x-requested-with') != 'XMLHttpRequest':
            return HttpResponseForbidden("AJAX submission is required to place a bet.")

        # Register first, then let the client print. Failed prints can be reprinted.
        try:
            saved_wager, created = services.add_wager(
                wager, wager_id, current_fn,
                cashier=str(request.user),
                require_side_open=True,
                client_request_id=request.POST.get('client_request_id'),
            )
        except services.BettingClosedError:
            return JsonResponse({
                'ok': False,
                'error': 'betting_closed',
                'blocked_betting_side': wager_id,
            }, status=409)
        return wager_ajax_response(saved_wager, duplicate=not created)

    return render(request, 'SmartWagers/user.html', user_page_context())


@group_required('teller')
def teller_report(request):
    active_event = services.get_active_event()

    wager_qs = Wagers.objects.filter(cashier=str(request.user), registered=True)
    if active_event is not None:
        wager_qs = wager_qs.filter(created_at__gte=active_event.started_at)

    wagers = wager_qs.order_by('-created_at')
    active_wagers = wagers.filter(cancelled=False)
    total_amount = active_wagers.aggregate(total=Sum('wager'))['total'] or 0.0
    total_count = active_wagers.count()

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

    close_out = services.get_teller_close_out(request.user, event=active_event)
    balance_breakdown = services.compute_teller_balance_breakdown(
        request.user, event=active_event, apply_end_bound=True,
    ) if active_event else None

    return render(request, 'SmartWagers/teller_report.html', {
        'wagers': wagers,
        'total_amount': total_amount,
        'total_count': total_count,
        'teller_name': str(request.user),
        'active_event': active_event,
        'completed_fights': completed_fights,
        'allowed_reprint': allowed_reprint,
        'station_closed': close_out is not None,
        'close_out': close_out,
        'expected_balance': balance_breakdown['balance'] if balance_breakdown else 0.0,
        'balance_breakdown': balance_breakdown,
        'current_fightnum': current_fightnum,
    })


@group_required('teller')
def teller_close_station(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'method_not_allowed'}, status=405)

    if services.teller_station_is_closed(request.user):
        return JsonResponse({'ok': False, 'error': 'already_closed'}, status=409)

    try:
        close_out = services.close_teller_station(request.user)
    except services.NoActiveEventError:
        return JsonResponse({'ok': False, 'error': 'no_active_event'}, status=409)
    except services.StationAlreadyClosedError:
        return JsonResponse({'ok': False, 'error': 'already_closed'}, status=409)

    notify_teller_online_status(request.user.pk, False)

    return JsonResponse({
        'ok': True,
        'close_out': {
            'id': close_out.pk,
            'event_name': close_out.event.name,
            'fightnum': close_out.fightnum,
            'closed_at': close_out.closed_at.isoformat(),
            'expected_cash_on_hand': close_out.expected_cash_on_hand,
            'grand_total': close_out.grand_total,
            'remit_total': close_out.remit_total,
            'collect_total': close_out.collect_total,
            'payout_total': close_out.payout_total,
        },
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
    wager_qs = Wagers.objects.filter(cashier=username, registered=True, cancelled=False)
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


def _build_event_user_stats(user, event, unclaimed_by_cashier, close_out=None):
    """Aggregate bet and transaction stats for one user within an event."""
    balance, grand_total = _compute_teller_balance(user, event=event)
    username = str(user)

    wager_qs = Wagers.objects.filter(
        cashier=username, registered=True, cancelled=False,
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

    txn_qs = TellerTransaction.objects.filter(
        user=user,
        created_at__gte=event.started_at,
    )
    if event.ended_at:
        txn_qs = txn_qs.filter(created_at__lte=event.ended_at)

    txn_stats = txn_qs.aggregate(
        remit_total=Sum('amount', filter=Q(transaction_type=TellerTransaction.REMIT)),
        collect_total=Sum('amount', filter=Q(transaction_type=TellerTransaction.COLLECT)),
        payout_total=Sum('amount', filter=Q(transaction_type=TellerTransaction.PAYOUT)),
        initial_fund=Sum(
            'amount',
            filter=Q(
                transaction_type=TellerTransaction.COLLECT,
                affects_admin_fund=False,
            ),
        ),
    )

    unclaimed_info = unclaimed_by_cashier.get(username, {'count': 0, 'total': 0.0})
    initial_fund = txn_stats['initial_fund'] or 0.0
    reporting_coh = None
    if close_out is not None:
        reporting_coh = close_out.expected_cash_on_hand + initial_fund

    return {
        'user': user,
        'display_name': (f"{user.first_name} {user.last_name}".strip() or user.username),
        'bet_count': bet_stats['bet_count'] or 0,
        'meron_count': bet_stats['meron_count'] or 0,
        'wala_count': bet_stats['wala_count'] or 0,
        'grand_total': grand_total,
        'meron_total': bet_stats['meron_total'] or 0.0,
        'wala_total': bet_stats['wala_total'] or 0.0,
        'payout_total': txn_stats['payout_total'] or 0.0,
        'remit_total': txn_stats['remit_total'] or 0.0,
        'collect_total': txn_stats['collect_total'] or 0.0,
        'initial_fund': initial_fund,
        'reporting_coh': reporting_coh,
        'unclaimed_count': unclaimed_info['count'],
        'unclaimed_total': unclaimed_info['total'],
        'balance': balance,
        'close_out': close_out,
    }


def _remit_exceeds_cash_on_hand(user, amount, event=None, apply_end_bound=True):
    """Return (exceeds, balance, grand_total) for a proposed REMIT amount.

    Amounts are compared at 2 decimal places (currency precision).
    """
    balance, grand_total = _compute_teller_balance(
        user, event=event, apply_end_bound=apply_end_bound,
    )
    exceeds = round(amount, 2) > round(balance, 2)
    return exceeds, balance, grand_total


@group_required('teller')
def get_teller_balance(request):
    event_scope, apply_end_bound = services.get_event_scope()
    if request.user.groups.filter(name='admin').exists():
        summary = services.get_admin_fund_summary(
            event=event_scope,
            apply_end_bound=apply_end_bound,
        )
        return JsonResponse({
            'ok': True,
            'balance': summary['balance'],
            'grand_total': summary['admin_wagers'],
            'shared_admin_fund': True,
        })
    balance, grand_total = _compute_teller_balance(request.user, event=event_scope, apply_end_bound=apply_end_bound)
    return JsonResponse({
        'ok': True,
        'balance': balance,
        'grand_total': grand_total,
        'shared_admin_fund': False,
    })


@group_required('teller')
def get_pending_payouts(request):
    """Return the count and total amount of this teller's unclaimed winning/refund tickets."""
    username = str(request.user)
    active_event = services.get_active_event()

    # Base: registered, uncashed, non-cancelled wagers by this teller in the active event
    pending_qs = Wagers.objects.filter(
        cashier=username, registered=True, cashed_out=False, cancelled=False,
    )
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
        cancelled=False,
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

    blocked = teller_action_blocked_response(request.user)
    if blocked is not None:
        return blocked

    transaction_type = request.POST.get('transaction_type', '').strip().upper()
    if transaction_type != TellerTransaction.REMIT:
        return JsonResponse({'ok': False, 'error': 'invalid_type'}, status=400)

    try:
        amount = float(request.POST.get('amount', 0))
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'invalid_amount'}, status=400)

    if amount <= 0:
        return JsonResponse({'ok': False, 'error': 'invalid_amount'}, status=400)

    event_scope, apply_end_bound = services.get_event_scope()
    with db_transaction.atomic():
        # Serialize remits for this teller so concurrent requests cannot both
        # pass the cash-on-hand check and overdraw.
        User.objects.select_for_update().get(pk=request.user.pk)
        exceeds, balance, grand_total = _remit_exceeds_cash_on_hand(
            request.user, amount, event=event_scope, apply_end_bound=apply_end_bound,
        )
        if exceeds:
            logger.warning(
                "REMIT REJECTED (exceeds_cash_on_hand): amount=%.2f balance=%.2f teller=%s",
                amount, balance, request.user.username,
            )
            return JsonResponse({
                'ok': False,
                'error': 'exceeds_cash_on_hand',
                'balance': balance,
                'grand_total': grand_total,
            }, status=400)

        txn = TellerTransaction.objects.create(
            user=request.user,
            transaction_type=transaction_type,
            amount=amount,
        )
    logger.info(
        "TELLER TXN: txn_id=%s type=%s amount=%.2f teller=%s",
        txn.transaction_id, transaction_type, amount, request.user.username,
    )

    balance, grand_total = _compute_teller_balance(
        request.user, event=event_scope, apply_end_bound=apply_end_bound,
    )
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
        admin_ids = User.objects.filter(
            groups__name='admin',
        ).values_list('pk', flat=True)
        tellers = teller_group.user_set.exclude(
            pk__in=admin_ids,
        ).order_by('username')
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
        transactions = txn_qs.exclude(
            transaction_type=TellerTransaction.PAYOUT,
        ).order_by('-created_at')

        ts, _ = TellerStatus.objects.get_or_create(user=teller)
        is_online = ts.is_online

        wager_qs = Wagers.objects.filter(cashier=str(teller), registered=True)
        if event_scope is not None:
            wager_qs = wager_qs.filter(created_at__gte=event_scope.started_at)
            if apply_end_bound and event_scope.ended_at:
                wager_qs = wager_qs.filter(created_at__lte=event_scope.ended_at)
        has_activity = not is_online and wager_qs.exists()

        close_out = services.get_teller_close_out(teller, event=event_scope)

        teller_data.append({
            'user': teller,
            'display_name': (f"{teller.first_name} {teller.last_name}".strip() or teller.username),
            'balance': balance,
            'grand_total': grand_total,
            'transactions': transactions,
            'is_online': is_online,
            'has_activity': has_activity,
            'close_out': close_out,
        })

    teller_data.sort(key=lambda td: (-td['balance'], td['user'].username.lower()))

    setting = Settings.objects.order_by('-id').first()
    teller_max_balance = setting.teller_max_balance if setting else 0.0
    teller_min_balance = setting.teller_min_balance if setting else 0.0
    teller_initial_fund = setting.teller_initial_fund if setting else 10000.0
    admin_initial_fund = setting.admin_initial_fund if setting else 100000.0
    online_teller_count = sum(1 for td in teller_data if td['is_online'])
    planned_teller_funds = online_teller_count * teller_initial_fund
    planned_bank_funds = admin_initial_fund + planned_teller_funds

    return render(request, 'SmartWagers/admin_tellers.html', {
        'teller_data': teller_data,
        'active_event': active_event,
        'teller_max_balance': teller_max_balance,
        'teller_min_balance': teller_min_balance,
        'teller_initial_fund': teller_initial_fund,
        'admin_initial_fund': admin_initial_fund,
        'online_teller_count': online_teller_count,
        'planned_teller_funds': planned_teller_funds,
        'planned_bank_funds': planned_bank_funds,
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
        admin_ids = User.objects.filter(
            groups__name='admin',
        ).values_list('pk', flat=True)
        teller = teller_group.user_set.exclude(
            pk__in=admin_ids,
        ).get(pk=teller_id)
    except (Group.DoesNotExist, User.DoesNotExist):
        return JsonResponse({'ok': False, 'error': 'teller_not_found'}, status=404)

    scope, apply_end_bound = services.get_event_scope()
    if transaction_type == TellerTransaction.COLLECT:
        with db_transaction.atomic():
            Event.objects.filter(is_active=True).update(
                is_active=F('is_active'),
            )
            active_event = Event.objects.filter(is_active=True).order_by(
                '-started_at',
            ).first()
            if active_event is None:
                return JsonResponse(
                    {'ok': False, 'error': 'no_active_event'},
                    status=409,
                )
            admin_balance = services.get_admin_fund_summary(
                event=active_event,
            )['balance']
            if amount > admin_balance:
                return JsonResponse({
                    'ok': False,
                    'error': 'exceeds_admin_fund',
                    'admin_fund_balance': admin_balance,
                }, status=400)
            txn = TellerTransaction.objects.create(
                user=teller,
                transaction_type=transaction_type,
                amount=amount,
                affects_admin_fund=True,
            )
    else:
        # REMIT — lock teller row so check + create cannot race.
        with db_transaction.atomic():
            User.objects.select_for_update().get(pk=teller.pk)
            exceeds, balance, grand_total = _remit_exceeds_cash_on_hand(
                teller, amount, event=scope, apply_end_bound=apply_end_bound,
            )
            if exceeds:
                logger.warning(
                    "ADMIN REMIT REJECTED (exceeds_cash_on_hand): amount=%.2f balance=%.2f teller=%s by_admin=%s",
                    amount, balance, teller.username, request.user.username,
                )
                return JsonResponse({
                    'ok': False,
                    'error': 'exceeds_cash_on_hand',
                    'balance': balance,
                    'grand_total': grand_total,
                }, status=400)
            txn = TellerTransaction.objects.create(
                user=teller,
                transaction_type=transaction_type,
                amount=amount,
                affects_admin_fund=True,
                # An admin-entered REMIT/Advance is a direct physical handoff,
                # so it is received immediately and increases the shared fund.
                received=True,
            )
    logger.info(
        "ADMIN TXN: txn_id=%s type=%s amount=%.2f teller=%s by_admin=%s",
        txn.transaction_id, transaction_type, amount, teller.username, request.user.username,
    )

    balance, grand_total = _compute_teller_balance(
        teller, event=scope, apply_end_bound=apply_end_bound,
    )
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
        'admin_fund_balance': services.get_admin_fund_summary()['balance'],
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
        'admin_fund_balance': services.get_admin_fund_summary(
            event=active_event,
        )['balance'],
    })


@group_required('admin')
def start_event_view(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'method_not_allowed'}, status=405)

    event_name = request.POST.get('event_name', '').strip()
    if not event_name:
        return JsonResponse({'ok': False, 'error': 'event_name_required'}, status=400)

    if masterlock.is_app_locked(touch_heartbeat=True):
        logger.info(
            "EVENT START blocked (master lock): admin=%s",
            request.user.username,
        )
        return JsonResponse(
            {'ok': False, 'error': 'app_locked', 'locked': True},
            status=403,
        )

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

    try:
        actual_admin_cash = _parse_currency_amount(
            request.POST.get('actual_admin_cash'),
        )
    except (ValueError, TypeError):
        return JsonResponse(
            {'ok': False, 'error': 'invalid_actual_admin_cash'},
            status=400,
        )
    if not math.isfinite(actual_admin_cash) or actual_admin_cash < 0:
        return JsonResponse(
            {'ok': False, 'error': 'invalid_actual_admin_cash'},
            status=400,
        )

    event = services.end_event(actual_admin_cash, request.user)
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
        admin_ids = User.objects.filter(
            groups__name='admin',
        ).values_list('pk', flat=True)
        tellers = teller_group.user_set.exclude(
            pk__in=admin_ids,
        ).order_by('username')
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

    # Build payable outcomes for outstanding payout detection.  Winning
    # MERON/WALA tickets are payable, while every ticket from a DRAW or
    # CANCELLED fight is payable as a full refund.
    payable_results = {
        r.fightnum: r.side
        for r in fight_results_qs
    }

    # Fetch all outstanding winning and refund tickets for this event.
    # Build both an aggregate dict (for the summary table) and a full list
    # (for the detailed transaction-ID breakdown at the bottom).
    unclaimed_by_cashier: dict = {}
    unclaimed_detail_list: list = []
    outstanding_payout_count_all = 0
    outstanding_payout_total_all = 0.0
    if payable_results:
        payable_filter = Q()
        for fightnum, result_side in payable_results.items():
            if result_side in ('CANCELLED', 'DRAW'):
                payable_filter |= Q(fightnum=fightnum)
            else:
                payable_filter |= Q(fightnum=fightnum, side=result_side)

        unclaimed_qs = Wagers.objects.filter(
            payable_filter,
            cashed_out=False,
            registered=True,
            cancelled=False,
            created_at__gte=event.started_at,
        ).exclude(cashier='System').order_by('cashier', 'fightnum', 'transactionid')

        if event.ended_at:
            unclaimed_qs = unclaimed_qs.filter(created_at__lte=event.ended_at)

        outstanding_totals = unclaimed_qs.order_by().aggregate(
            count=Count('id'),
            total=Sum('wager'),
        )
        outstanding_payout_count_all = outstanding_totals['count'] or 0
        outstanding_payout_total_all = outstanding_totals['total'] or 0.0

        # Aggregate totals per cashier for the summary table
        for row in unclaimed_qs.order_by().values('cashier').annotate(
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
            w['result_side'] = payable_results.get(w['fightnum'])
            unclaimed_detail_list.append(w)

    # Per-teller aggregates
    show_all_tellers = request.GET.get('show_all_tellers') == '1'
    teller_data = []
    grand_total_all = 0.0
    total_payout_all = 0.0
    total_remit_all = 0.0
    total_unclaimed_all = 0.0
    total_bets_count_all = 0
    total_reporting_coh_all = 0.0
    total_initial_fund_all = 0.0
    total_expected_all = 0.0
    total_actual_all = 0.0
    total_variance_all = 0.0

    close_outs = {
        co.user_id: co
        for co in TellerCloseOut.objects.filter(event=event).select_related('user')
    }

    for teller in tellers:
        stats = _build_event_user_stats(
            teller, event, unclaimed_by_cashier,
            close_out=close_outs.get(teller.pk),
        )
        if not show_all_tellers and stats['bet_count'] == 0:
            continue
        teller_data.append(stats)
        grand_total_all += stats['grand_total']
        total_payout_all += stats['payout_total']
        total_remit_all += stats['remit_total']
        total_unclaimed_all += stats['unclaimed_total']
        total_bets_count_all += stats['bet_count']
        total_initial_fund_all += stats['initial_fund']
        if stats['reporting_coh'] is not None:
            total_reporting_coh_all += stats['reporting_coh']
        close_out = stats['close_out']
        if close_out is not None:
            total_expected_all += close_out.expected_cash_on_hand
            if close_out.actual_cash_counted is not None:
                total_actual_all += close_out.actual_cash_counted
            if close_out.variance is not None:
                total_variance_all += close_out.variance

    event_closed = not event.is_active or event.ended_at is not None
    admin_data = []
    admin_grand_total_all = 0.0
    admin_unclaimed_all = 0.0
    admin_bets_count_all = 0
    admin_payout_all = 0.0
    admin_bank_remitted_all = 0.0
    admin_fund_summary = None
    final_reconciliation_rows = []
    final_reconciliation_totals = None

    if event_closed:
        admins = User.objects.filter(groups__name='admin').order_by('username')
        admin_bank_remits = {
            row['admin_id']: row['total'] or 0.0
            for row in AdminBankTransaction.objects.filter(
                event=event,
                transaction_type=AdminBankTransaction.REMIT,
            ).values('admin_id').annotate(total=Sum('amount'))
        }
        for admin in admins:
            stats = _build_event_user_stats(admin, event, unclaimed_by_cashier)
            stats['bank_remitted'] = admin_bank_remits.get(admin.pk, 0.0)
            if not (
                stats['bet_count'] or stats['payout_total']
                or stats['unclaimed_count'] or stats['bank_remitted']
            ):
                continue
            admin_data.append(stats)
            admin_grand_total_all += stats['grand_total']
            admin_unclaimed_all += stats['unclaimed_total']
            admin_bets_count_all += stats['bet_count']
            admin_payout_all += stats['payout_total']
            admin_bank_remitted_all += stats['bank_remitted']
        admin_fund_summary = services.get_admin_fund_summary(
            event=event, apply_end_bound=True,
        )
        admin_fund_summary.update({
            'expected_cash_on_hand': (
                event.expected_admin_cash_on_hand
                if event.expected_admin_cash_on_hand is not None
                else admin_fund_summary['balance_before_closeouts']
            ),
            'actual_cash_counted': event.actual_admin_cash_counted,
            'variance': event.admin_cash_variance,
            'counted_by': event.admin_cash_counted_by,
            'counted_by_name': (
                event.admin_cash_counted_by.get_full_name()
                or event.admin_cash_counted_by.username
                if event.admin_cash_counted_by
                else ''
            ),
            'counted_at': event.admin_cash_counted_at,
        })

        final_reconciliation_rows.append({
            'name': 'Admin',
            'coh': (
                admin_fund_summary['opening_fund']
                + admin_fund_summary['expected_cash_on_hand']
            ),
            'petty': admin_fund_summary['opening_fund'],
            'expected': admin_fund_summary['expected_cash_on_hand'],
            'actual': admin_fund_summary['actual_cash_counted'],
            'variance': admin_fund_summary['variance'],
        })
        for stats in teller_data:
            close_out = stats['close_out']
            final_reconciliation_rows.append({
                'name': stats['display_name'],
                'coh': stats['reporting_coh'],
                'petty': stats['initial_fund'],
                'expected': (
                    close_out.expected_cash_on_hand
                    if close_out is not None
                    else None
                ),
                'actual': (
                    close_out.actual_cash_counted
                    if close_out is not None
                    else None
                ),
                'variance': (
                    close_out.variance
                    if close_out is not None
                    else None
                ),
            })

        def total_recorded(field):
            return round(sum(
                row[field]
                for row in final_reconciliation_rows
                if row[field] not in (None, 0)
            ), 2)

        final_reconciliation_totals = {
            'coh': total_recorded('coh'),
            'petty': total_recorded('petty'),
            'expected': total_recorded('expected'),
            'actual': total_recorded('actual'),
            'variance': total_recorded('variance'),
        }

    commission_20 = round(total_commission * 0.20, 2)
    commission_80 = round(total_commission * 0.80, 2)
    commission_4_of_80 = round(commission_80 * 0.04, 2)

    return render(request, 'SmartWagers/event_report.html', {
        'event': event,
        'all_events': all_events,
        'event_closed': event_closed,
        'show_all_tellers': show_all_tellers,
        'teller_data': teller_data,
        'grand_total_all': grand_total_all,
        'total_payout_all': total_payout_all,
        'total_remit_all': total_remit_all,
        'total_unclaimed_all': total_unclaimed_all,
        'total_bets_count_all': total_bets_count_all,
        'total_reporting_coh_all': total_reporting_coh_all,
        'total_initial_fund_all': total_initial_fund_all,
        'total_expected_all': total_expected_all,
        'total_actual_all': total_actual_all,
        'total_variance_all': total_variance_all,
        'admin_data': admin_data,
        'admin_grand_total_all': admin_grand_total_all,
        'admin_unclaimed_all': admin_unclaimed_all,
        'admin_bets_count_all': admin_bets_count_all,
        'admin_payout_all': admin_payout_all,
        'admin_bank_remitted_all': admin_bank_remitted_all,
        'admin_fund_summary': admin_fund_summary,
        'final_reconciliation_rows': final_reconciliation_rows,
        'final_reconciliation_totals': final_reconciliation_totals,
        'unclaimed_detail_list': unclaimed_detail_list,
        'outstanding_payout_count_all': outstanding_payout_count_all,
        'outstanding_payout_total_all': outstanding_payout_total_all,
        'fight_commissions': fight_commissions,
        'total_pot_all': total_pot_all,
        'total_commission': total_commission,
        'commission_20': commission_20,
        'commission_80': commission_80,
        'commission_4_of_80': commission_4_of_80,
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

    active_wagers = wager_qs.filter(cancelled=False)
    total_amount = active_wagers.aggregate(total=Sum('wager'))['total'] or 0.0
    total_count = active_wagers.count()

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
        admin_ids = User.objects.filter(
            groups__name='admin',
        ).values_list('pk', flat=True)
        tellers = teller_group.user_set.exclude(pk__in=admin_ids)
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
        admin_ids = User.objects.filter(
            groups__name='admin',
        ).values_list('pk', flat=True)
        teller = teller_group.user_set.exclude(
            pk__in=admin_ids,
        ).get(pk=teller_id)
    except (Group.DoesNotExist, User.DoesNotExist):
        return JsonResponse({'ok': False, 'error': 'teller_not_found'}, status=404)

    close_out = services.get_teller_close_out(teller, event=services.get_active_event())
    if is_online and close_out is not None and close_out.actual_cash_counted is None:
        return JsonResponse({
            'ok': False,
            'error': 'awaiting_cash_count',
            'message': 'Cannot bring teller online until cash has been counted.',
        }, status=409)

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
                    affects_admin_fund=False,
                )
                fund_issued = True

    notify_teller_online_status(teller_id, is_online)

    return JsonResponse({
        'ok': True,
        'teller_id': teller_id,
        'is_online': is_online,
        'fund_issued': fund_issued,
    })


def _parse_currency_amount(raw, default=None):
    """Parse a currency string that may include comma grouping."""
    if raw is None or str(raw).strip() == '':
        if default is not None:
            return default
        raise ValueError('missing amount')
    cleaned = str(raw).strip().replace(',', '')
    return float(cleaned)


@group_required('admin')
def admin_register_teller_cash_count(request):
    """Admin endpoint: register physically counted cash for a teller close-out."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'method_not_allowed'}, status=405)

    # #region agent log
    import json as _json, time as _time
    _raw_close_out_id = request.POST.get('close_out_id')
    _raw_actual_amount = request.POST.get('actual_amount')
    try:
        with open('/home/dross725/projects/Tabora/GameFowl/.cursor/debug-752381.log', 'a') as _dbg:
            _dbg.write(_json.dumps({
                'sessionId': '752381', 'hypothesisId': 'H1-H3',
                'location': 'views.py:admin_register_teller_cash_count:entry',
                'message': 'cash count POST received',
                'data': {
                    'close_out_id_raw': _raw_close_out_id,
                    'actual_amount_raw': _raw_actual_amount,
                    'post_keys': list(request.POST.keys()),
                },
                'timestamp': int(_time.time() * 1000),
            }) + '\n')
    except Exception:
        pass
    # #endregion

    try:
        close_out_id = int(str(request.POST.get('close_out_id', '')).strip())
        actual_amount = _parse_currency_amount(request.POST.get('actual_amount'))
    except (ValueError, TypeError) as exc:
        # #region agent log
        try:
            with open('/home/dross725/projects/Tabora/GameFowl/.cursor/debug-752381.log', 'a') as _dbg:
                _dbg.write(_json.dumps({
                    'sessionId': '752381', 'hypothesisId': 'H1-H3',
                    'location': 'views.py:admin_register_teller_cash_count:invalid_params',
                    'message': 'parse failed',
                    'data': {
                        'error_type': type(exc).__name__,
                        'error': str(exc),
                        'close_out_id_raw': _raw_close_out_id,
                        'actual_amount_raw': _raw_actual_amount,
                    },
                    'timestamp': int(_time.time() * 1000),
                }) + '\n')
        except Exception:
            pass
        # #endregion
        return JsonResponse({'ok': False, 'error': 'invalid_params'}, status=400)

    if actual_amount < 0:
        # #region agent log
        try:
            with open('/home/dross725/projects/Tabora/GameFowl/.cursor/debug-752381.log', 'a') as _dbg:
                _dbg.write(_json.dumps({
                    'sessionId': '752381', 'hypothesisId': 'H2',
                    'location': 'views.py:admin_register_teller_cash_count:negative_amount',
                    'message': 'negative amount rejected',
                    'data': {'actual_amount': actual_amount},
                    'timestamp': int(_time.time() * 1000),
                }) + '\n')
        except Exception:
            pass
        # #endregion
        return JsonResponse({'ok': False, 'error': 'invalid_amount'}, status=400)

    try:
        close_out = services.register_teller_cash_count(
            close_out_id, actual_amount, request.user,
        )
    except services.CloseOutNotFoundError:
        return JsonResponse({'ok': False, 'error': 'close_out_not_found'}, status=404)
    except services.CloseOutAlreadyCountedError:
        return JsonResponse({'ok': False, 'error': 'already_counted'}, status=409)
    except ValueError as exc:
        # #region agent log
        try:
            with open('/home/dross725/projects/Tabora/GameFowl/.cursor/debug-752381.log', 'a') as _dbg:
                import json as _json, time as _time
                _dbg.write(_json.dumps({
                    'sessionId': '752381', 'hypothesisId': 'H4',
                    'location': 'views.py:admin_register_teller_cash_count:service_value_error',
                    'message': 'register_teller_cash_count ValueError',
                    'data': {
                        'close_out_id': close_out_id,
                        'actual_amount': actual_amount,
                        'error': str(exc),
                    },
                    'timestamp': int(_time.time() * 1000),
                }) + '\n')
        except Exception:
            pass
        # #endregion
        if 'sequence is exhausted' in str(exc):
            return JsonResponse({'ok': False, 'error': 'transaction_id_exhausted'}, status=503)
        return JsonResponse({'ok': False, 'error': 'invalid_amount'}, status=400)

    # #region agent log
    try:
        with open('/home/dross725/projects/Tabora/GameFowl/.cursor/debug-752381.log', 'a') as _dbg:
            import json as _json, time as _time
            _dbg.write(_json.dumps({
                'sessionId': '752381', 'hypothesisId': 'success',
                'location': 'views.py:admin_register_teller_cash_count:success',
                'message': 'cash count registered',
                'data': {
                    'close_out_id': close_out.pk,
                    'variance': close_out.variance,
                },
                'timestamp': int(_time.time() * 1000),
            }) + '\n')
    except Exception:
        pass
    # #endregion

    return JsonResponse({
        'ok': True,
        'close_out_id': close_out.pk,
        'actual_cash_counted': close_out.actual_cash_counted,
        'expected_cash_on_hand': close_out.expected_cash_on_hand,
        'variance': close_out.variance,
        'remit_transaction_id': (
            close_out.remit_transaction.transaction_id
            if close_out.remit_transaction else None
        ),
    })


@group_required('admin')
def admin_reopen_teller_station(request):
    """Admin endpoint: cancel an uncounted close-out and reopen the station."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'method_not_allowed'}, status=405)

    try:
        close_out_id = int(str(request.POST.get('close_out_id', '')).strip())
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'invalid_close_out_id'}, status=400)

    try:
        teller = services.reopen_teller_station(close_out_id, request.user)
    except services.CloseOutNotFoundError:
        return JsonResponse({'ok': False, 'error': 'close_out_not_found'}, status=404)
    except services.CloseOutAlreadyCountedError:
        return JsonResponse({
            'ok': False,
            'error': 'already_counted',
            'message': 'A reconciled close-out cannot be reopened.',
        }, status=409)

    notify_teller_online_status(teller.pk, True)
    return JsonResponse({
        'ok': True,
        'teller_id': teller.pk,
        'is_online': True,
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

        if action == 'update_admin_initial_fund':
            try:
                new_fund = float(request.POST.get('admin_initial_fund', ''))
                if new_fund < 0:
                    return JsonResponse({'ok': False, 'error': 'Initial fund must be 0 or greater'}, status=400)
            except (ValueError, TypeError):
                return JsonResponse({'ok': False, 'error': 'Invalid initial fund value'}, status=400)

            setting = Settings.objects.order_by('-id').first()
            if setting is None:
                setting = Settings(admin_initial_fund=new_fund)
            else:
                setting.admin_initial_fund = new_fund
            setting.save()
            logger.info(
                "SETTINGS: admin initial fund updated to %.2f by admin=%s",
                new_fund, request.user.username,
            )
            return JsonResponse({'ok': True, 'admin_initial_fund': new_fund})

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

        if action in ('master_lock_enable', 'master_lock_extend', 'master_lock_disable'):
            if not request.user.is_superuser:
                logger.warning(
                    'MASTER LOCK admin action=%s denied (not superuser) by=%s',
                    action, request.user.username,
                )
                return JsonResponse(
                    {'ok': False, 'error': 'Only superusers can manage the master lock.'},
                    status=403,
                )
            client_id = _get_client_ip(request)
            master_key = request.POST.get('master_key') or ''
            try:
                if action == 'master_lock_enable':
                    status = masterlock.enable_lock(master_key=master_key, client_id=client_id)
                elif action == 'master_lock_extend':
                    status = masterlock.extend_lock(master_key=master_key, client_id=client_id)
                else:
                    status = masterlock.disable_lock(master_key=master_key, client_id=client_id)
                logger.info(
                    'MASTER LOCK admin action=%s by=%s locked=%s',
                    action, request.user.username, status.get('locked'),
                )
                return JsonResponse({
                    'ok': True,
                    'locked': status.get('locked'),
                    'enabled': status.get('enabled'),
                    'valid_until': status.get('valid_until'),
                    'extension_count': status.get('extension_count'),
                    'extension_days': masterlock.EXTENSION_DAYS,
                })
            except masterlock.MasterLockAuthError:
                logger.warning(
                    'MASTER LOCK admin action=%s rejected by=%s',
                    action, request.user.username,
                )
                return JsonResponse({'ok': False, 'error': masterlock.GENERIC_AUTH_ERROR}, status=403)
            except masterlock.MasterLockError:
                return JsonResponse({'ok': False, 'error': masterlock.GENERIC_AUTH_ERROR}, status=400)
            finally:
                master_key = ''

        return JsonResponse({'ok': False, 'error': 'Unknown action'}, status=400)

    plasada = services.get_comm_val()
    fight_results = Fight_Results.objects.all().order_by('-fightnum')
    if active_event is not None:
        fight_results = fight_results.filter(event=active_event)

    setting = Settings.objects.order_by('-id').first()
    admin_initial_fund  = setting.admin_initial_fund  if setting else 100000.0
    teller_max_balance  = setting.teller_max_balance  if setting else 0.0
    teller_initial_fund = setting.teller_initial_fund if setting else 10000.0
    teller_min_balance  = setting.teller_min_balance  if setting else 0.0
    lock_status = masterlock.get_status(touch_heartbeat=False)

    return render(request, 'SmartWagers/admin_settings.html', {
        'plasada': plasada,
        'plasada_pct': plasada * 100,
        'fight_results': fight_results,
        'active_event': active_event,
        'admin_initial_fund': admin_initial_fund,
        'teller_max_balance': teller_max_balance,
        'teller_initial_fund': teller_initial_fund,
        'teller_min_balance': teller_min_balance,
        'lock_status': lock_status,
        'extension_days': masterlock.EXTENSION_DAYS,
    })
