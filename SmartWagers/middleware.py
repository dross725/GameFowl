"""HTTP middleware that enforces the SmartWagers master lock."""

from __future__ import annotations

import logging

from django.http import JsonResponse, HttpResponseRedirect
from django.urls import reverse

from . import masterlock

logger = logging.getLogger('SmartWagers.middleware')


def _wants_json(request) -> bool:
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return True
    accept = request.headers.get('Accept', '')
    if 'application/json' in accept and 'text/html' not in accept:
        return True
    if request.method not in ('GET', 'HEAD'):
        return True
    return False


def _is_allowlisted(path: str) -> bool:
    if path.startswith('/static/'):
        return True
    if path.startswith('/master-lock'):
        return True
    if path.rstrip('/') == '/logout':
        return True
    if path.rstrip('/') == '/health':
        return True
    return False


class MasterLockMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or '/'
        if _is_allowlisted(path):
            return self.get_response(request)

        try:
            locked = masterlock.is_app_locked(touch_heartbeat=True)
        except Exception as exc:  # noqa: BLE001 — fail closed
            logger.exception('MASTER LOCK middleware fail-closed: %s', exc)
            locked = True

        if not locked:
            return self.get_response(request)

        logger.info(
            'MASTER LOCK blocked path=%s method=%s',
            path,
            request.method,
        )

        if _wants_json(request):
            response = JsonResponse(
                {'ok': False, 'error': 'app_locked', 'locked': True},
                status=503,
            )
            response['Cache-Control'] = 'no-store'
            return response

        if request.method in ('GET', 'HEAD'):
            response = HttpResponseRedirect(reverse('master-lock'))
            response['Cache-Control'] = 'no-store'
            return response

        response = JsonResponse(
            {'ok': False, 'error': 'app_locked', 'locked': True},
            status=503,
        )
        response['Cache-Control'] = 'no-store'
        return response
