"""Server-mediated print queue for mobile Bluetooth companion apps."""
from __future__ import annotations

import base64
import json
import secrets
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import escpos_receipts
from .models import PrintDevice, PrintJob


VALID_PLATFORMS = {PrintDevice.PLATFORM_ANDROID, PrintDevice.PLATFORM_IOS}
VALID_ENDPOINTS = {
    PrintJob.ENDPOINT_WAGER,
    PrintJob.ENDPOINT_PAYOUT,
    PrintJob.ENDPOINT_REMIT,
}


def _json_body(request) -> dict[str, Any]:
    if not request.body:
        return {}
    try:
        data = json.loads(request.body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _bearer_token(request) -> str:
    header = request.META.get('HTTP_AUTHORIZATION', '')
    if header.lower().startswith('bearer '):
        return header[7:].strip()
    return str(request.headers.get('X-Print-Token') or '').strip()


def _device_from_token(request) -> PrintDevice | None:
    token = _bearer_token(request)
    if not token:
        return None
    try:
        return PrintDevice.objects.select_related('user').get(auth_token=token)
    except PrintDevice.DoesNotExist:
        return None


def _require_device(request):
    device = _device_from_token(request)
    if device is None:
        return None, JsonResponse({'ok': False, 'error': 'unauthorized'}, status=401)
    device.last_seen = timezone.now()
    device.save(update_fields=['last_seen', 'updated_at'])
    return device, None


def _job_channel(user_id: int) -> str:
    return f'print_jobs_user_{user_id}'


def _notify_print_job(job: PrintJob) -> None:
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    try:
        async_to_sync(channel_layer.group_send)(
            _job_channel(job.user_id),
            {
                'type': 'print.job',
                'job': _job_payload(job, include_bytes=True),
            },
        )
    except Exception:
        # Polling remains the reliable fallback.
        pass


def _job_payload(job: PrintJob, *, include_bytes: bool = False) -> dict[str, Any]:
    payload = {
        'id': job.pk,
        'endpoint': job.endpoint,
        'receipt_type': job.receipt_type,
        'transaction_id': job.transaction_id,
        'status': job.status,
        'created_at': job.created_at.isoformat() if job.created_at else None,
        'error_text': job.error_text,
    }
    if include_bytes:
        payload['escpos_base64'] = base64.b64encode(bytes(job.escpos_bytes)).decode('ascii')
        payload['payload'] = job.payload_json
    return payload


def enqueue_print_job(user: User, receipt: dict[str, Any], endpoint: str | None = None) -> PrintJob:
    kind = escpos_receipts.infer_endpoint(receipt, endpoint)
    if kind not in VALID_ENDPOINTS:
        kind = PrintJob.ENDPOINT_WAGER
    escpos_bytes = escpos_receipts.render_escpos_bytes(kind, receipt)
    job = PrintJob.objects.create(
        user=user,
        endpoint=kind,
        receipt_type=str(receipt.get('receipt_type') or receipt.get('transaction_type') or kind),
        transaction_id=escpos_receipts.normalize_receipt_transaction_id(
            receipt.get('transaction_id', ''),
        ),
        payload_json=receipt,
        escpos_bytes=escpos_bytes,
        status=PrintJob.STATUS_PENDING,
    )
    _notify_print_job(job)
    return job


@login_required
@require_POST
def enqueue_print_job_view(request):
    """Browser enqueues a receipt for the mobile companion."""
    body = _json_body(request)
    receipt = body.get('receipt') if isinstance(body.get('receipt'), dict) else body
    if not isinstance(receipt, dict) or not receipt:
        return JsonResponse({'ok': False, 'error': 'missing_receipt'}, status=400)

    endpoint = body.get('endpoint') if 'endpoint' in body else None
    job = enqueue_print_job(request.user, receipt, endpoint=endpoint)
    return JsonResponse({
        'ok': True,
        'job_id': job.pk,
        'status': job.status,
        'message': 'Receipt queued for mobile print companion.',
    })


@login_required
@require_GET
def print_job_status_view(request, job_id: int):
    try:
        job = PrintJob.objects.get(pk=job_id, user=request.user)
    except PrintJob.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'not_found'}, status=404)
    return JsonResponse({'ok': True, 'job': _job_payload(job)})


@csrf_exempt
@require_POST
def print_device_login(request):
    """Companion login: username/password + device metadata → auth token."""
    body = _json_body(request)
    username = str(body.get('username') or '').strip()
    password = str(body.get('password') or '')
    device_id = str(body.get('device_id') or '').strip()
    platform = str(body.get('platform') or '').strip().lower()
    printer_name = str(body.get('printer_name') or '').strip()
    printer_address = str(body.get('printer_address') or '').strip()

    if not username or not password:
        return JsonResponse({'ok': False, 'error': 'missing_credentials'}, status=400)
    if not device_id:
        return JsonResponse({'ok': False, 'error': 'missing_device_id'}, status=400)
    if platform not in VALID_PLATFORMS:
        return JsonResponse({'ok': False, 'error': 'invalid_platform'}, status=400)

    user = authenticate(request, username=username, password=password)
    if user is None or not user.is_active:
        return JsonResponse({'ok': False, 'error': 'invalid_credentials'}, status=401)
    if not user.groups.filter(name__in=('teller', 'admin')).exists():
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)

    token = secrets.token_urlsafe(32)
    device, _created = PrintDevice.objects.update_or_create(
        user=user,
        device_id=device_id,
        defaults={
            'platform': platform,
            'auth_token': token,
            'printer_name': printer_name,
            'printer_address': printer_address,
            'last_seen': timezone.now(),
        },
    )
    return JsonResponse({
        'ok': True,
        'token': device.auth_token,
        'user': user.username,
        'device_id': device.device_id,
        'platform': device.platform,
    })


@csrf_exempt
@require_POST
def print_device_register(request):
    """Refresh printer pairing metadata for an authenticated companion."""
    device, error = _require_device(request)
    if error:
        return error

    body = _json_body(request)
    fields = []
    if 'printer_name' in body:
        device.printer_name = str(body.get('printer_name') or '').strip()
        fields.append('printer_name')
    if 'printer_address' in body:
        device.printer_address = str(body.get('printer_address') or '').strip()
        fields.append('printer_address')
    if fields:
        fields.extend(['updated_at', 'last_seen'])
        device.last_seen = timezone.now()
        device.save(update_fields=fields)
    return JsonResponse({
        'ok': True,
        'device_id': device.device_id,
        'printer_name': device.printer_name,
        'printer_address': device.printer_address,
    })


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def print_jobs_pending(request):
    """Companion claims the next pending jobs for its user."""
    device, error = _require_device(request)
    if error:
        return error

    limit = 5
    if request.method == 'POST':
        body = _json_body(request)
        try:
            limit = max(1, min(int(body.get('limit') or 5), 20))
        except (TypeError, ValueError):
            limit = 5
    else:
        try:
            limit = max(1, min(int(request.GET.get('limit') or 5), 20))
        except (TypeError, ValueError):
            limit = 5

    jobs_out = []
    with transaction.atomic():
        base_qs = (
            PrintJob.objects
            .filter(user=device.user, status=PrintJob.STATUS_PENDING)
            .order_by('created_at')
        )
        try:
            qs = list(base_qs.select_for_update(skip_locked=True)[:limit])
        except Exception:
            qs = list(base_qs.select_for_update()[:limit])
        now = timezone.now()
        for job in qs:
            job.status = PrintJob.STATUS_SENT
            job.device = device
            job.claimed_at = now
            job.save(update_fields=['status', 'device', 'claimed_at'])
            jobs_out.append(_job_payload(job, include_bytes=True))

    return JsonResponse({'ok': True, 'jobs': jobs_out})


@csrf_exempt
@require_POST
def print_job_ack(request, job_id: int):
    device, error = _require_device(request)
    if error:
        return error

    body = _json_body(request)
    status = str(body.get('status') or '').strip().lower()
    error_text = str(body.get('error') or body.get('error_text') or '').strip()

    try:
        job = PrintJob.objects.get(pk=job_id, user=device.user)
    except PrintJob.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'not_found'}, status=404)

    if status == PrintJob.STATUS_PRINTED:
        job.status = PrintJob.STATUS_PRINTED
        job.error_text = ''
    elif status == PrintJob.STATUS_FAILED:
        job.status = PrintJob.STATUS_FAILED
        job.error_text = error_text or 'print_failed'
    else:
        return JsonResponse({'ok': False, 'error': 'invalid_status'}, status=400)

    job.finished_at = timezone.now()
    if job.device_id is None:
        job.device = device
    job.save(update_fields=['status', 'error_text', 'finished_at', 'device'])
    return JsonResponse({'ok': True, 'job': _job_payload(job)})


@csrf_exempt
@require_GET
def print_device_health(request):
    device, error = _require_device(request)
    if error:
        return error
    pending = PrintJob.objects.filter(
        user=device.user,
        status=PrintJob.STATUS_PENDING,
    ).count()
    return JsonResponse({
        'ok': True,
        'user': device.user.username,
        'device_id': device.device_id,
        'platform': device.platform,
        'pending_jobs': pending,
        'printer_name': device.printer_name,
        'printer_address': device.printer_address,
    })
