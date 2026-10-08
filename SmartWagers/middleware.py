"""HTTP middleware that enforces the SmartWagers master lock.

While locked, safe reads stay available. Operational writes are rejected
unless they are login, logout, license recovery, or a superuser lock action.
"""

from __future__ import annotations

import logging

from django.http import JsonResponse

from . import masterlock

logger = logging.getLogger('SmartWagers.middleware')

_SUPERUSER_LOCK_ACTIONS = {
    'master_lock_enable',
    'master_lock_extend',
    'master_lock_disable',
    'master_lock_lock',
    'master_lock_unlock',
}


def _normalized_path(path: str) -> str:
    path = path or '/'
    if len(path) > 1:
        path = path.rstrip('/')
    return path


def _mutation_allowed(request) -> bool:
    path = _normalized_path(request.path)
    if path.startswith('/static') or path.startswith('/master-lock'):
        return True
    if path in ('/health', '/login', '/logout') or path.endswith('/login') or path.endswith('/logout'):
        return True
    if path == '/administrator/settings':
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated or not user.is_superuser:
            return False
        action = (request.POST.get('action') or '').strip()
        return action in _SUPERUSER_LOCK_ACTIONS
    return False


class MasterLockMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return self.get_response(request)

        try:
            locked = masterlock.is_app_locked(touch_heartbeat=True)
        except Exception as exc:  # noqa: BLE001 — fail closed
            logger.exception('MASTER LOCK middleware fail-closed: %s', exc)
            locked = True

        if not locked or _mutation_allowed(request):
            return self.get_response(request)

        logger.info(
            'MASTER LOCK blocked path=%s method=%s',
            request.path,
            request.method,
        )
        response = JsonResponse(
            {'ok': False, 'error': 'app_locked', 'locked': True},
            status=423,
        )
        response['Cache-Control'] = 'no-store'
        return response
