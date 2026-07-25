"""
SmartWagers master lock — offline fixed-key monthly activation.

State is an HMAC-signed JSON envelope on disk. The plaintext master key is
never stored; only a Django password hash is used for verification.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger('SmartWagers.masterlock')

SCHEMA_VERSION = 1
EXTENSION_DAYS = 30
CLOCK_ROLLBACK_TOLERANCE = timedelta(minutes=5)
HEARTBEAT_INTERVAL = timedelta(minutes=5)
GENERIC_AUTH_ERROR = 'Invalid master key or lock operation failed.'
WS_CLOSE_LOCKED = 4410

_process_lock = threading.RLock()
_rate_limit_lock = threading.Lock()
_rate_failures: dict[str, list[float]] = {}

# In-memory rate limit: N failures per window, then cooldown.
RATE_LIMIT_MAX_FAILURES = 5
RATE_LIMIT_WINDOW_SEC = 300
RATE_LIMIT_COOLDOWN_SEC = 300


class MasterLockError(Exception):
    """Base error for master-lock operations."""


class MasterLockAuthError(MasterLockError):
    """Master key rejected or rate-limited."""


class MasterLockStateError(MasterLockError):
    """State missing, tampered, or otherwise unusable."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = value.strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def state_path() -> Path:
    configured = getattr(settings, 'MASTER_LOCK_STATE_PATH', None)
    if configured:
        return Path(configured)
    return Path(settings.BASE_DIR) / 'master_lock.state'


def signing_key() -> bytes:
    key = getattr(settings, 'MASTER_LOCK_SIGNING_KEY', '') or ''
    if not key:
        if getattr(settings, 'MASTER_LOCK_REQUIRED', False):
            raise ImproperlyConfigured(
                'MASTER_LOCK_SIGNING_KEY is required when MASTER_LOCK_REQUIRED is enabled.'
            )
        # Dev/test fallback — never use in production.
        key = 'dev-only-master-lock-signing-key'
    return key.encode('utf-8')


def password_hash() -> str:
    value = getattr(settings, 'MASTER_LOCK_PASSWORD_HASH', '') or ''
    if not value and getattr(settings, 'MASTER_LOCK_REQUIRED', False):
        raise ImproperlyConfigured(
            'MASTER_LOCK_PASSWORD_HASH is required when MASTER_LOCK_REQUIRED is enabled.'
        )
    return value


def lock_required() -> bool:
    return bool(getattr(settings, 'MASTER_LOCK_REQUIRED', False))


def _canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def _sign(payload: dict[str, Any]) -> str:
    digest = hmac.new(signing_key(), _canonical_payload(payload), hashlib.sha256).hexdigest()
    return digest


def _verify_signature(payload: dict[str, Any], signature: str) -> bool:
    expected = _sign(payload)
    return hmac.compare_digest(expected, signature or '')


def _default_payload(*, action: str = 'init') -> dict[str, Any]:
    now = _utc_now()
    return {
        'schema_version': SCHEMA_VERSION,
        'enabled': False,
        'valid_until': None,
        'last_seen': _to_iso(now),
        'updated_at': _to_iso(now),
        'action': action,
        'extension_count': 0,
    }


def _acquire_file_lock(lock_file):
    if os.name == 'nt':
        import msvcrt
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)


def _release_file_lock(lock_file):
    if os.name == 'nt':
        import msvcrt
        lock_file.seek(0)
        try:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        import fcntl
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(data, indent=2, sort_keys=True) + '\n'
    fd, tmp_name = tempfile.mkstemp(prefix='.master_lock_', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as tmp:
            tmp.write(encoded)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _read_envelope(path: Path) -> dict[str, Any]:
    try:
        with path.open('r', encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise MasterLockStateError('Malformed master lock state envelope.') from exc
    if not isinstance(data, dict) or 'payload' not in data or 'sig' not in data:
        raise MasterLockStateError('Malformed master lock state envelope.')
    payload = data['payload']
    if not isinstance(payload, dict):
        raise MasterLockStateError('Malformed master lock payload.')
    if payload.get('schema_version') != SCHEMA_VERSION:
        raise MasterLockStateError('Unsupported master lock schema version.')
    if not _verify_signature(payload, data.get('sig', '')):
        raise MasterLockStateError('Master lock state signature is invalid.')
    return payload


def _write_payload(payload: dict[str, Any]) -> dict[str, Any]:
    envelope = {'payload': payload, 'sig': _sign(payload)}
    _atomic_write(state_path(), envelope)
    return payload


def initialize_state(*, force: bool = False) -> dict[str, Any]:
    """
    Create the initial disabled signed state.
    Refuses to overwrite existing/malformed/unsigned state unless force=True
    (force is reserved for explicit recovery tooling — not used by deploy).
    """
    path = state_path()
    with _process_lock:
        lock_path = path.with_suffix(path.suffix + '.lock')
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, 'a+', encoding='utf-8') as lock_file:
            _acquire_file_lock(lock_file)
            try:
                if path.exists() and not force:
                    # Validate existing; do not overwrite even if invalid.
                    try:
                        return _read_envelope(path)
                    except MasterLockError as exc:
                        raise MasterLockStateError(
                            f'Existing master lock state is unusable and will not be overwritten: {exc}'
                        ) from exc
                payload = _default_payload(action='init')
                return _write_payload(payload)
            finally:
                _release_file_lock(lock_file)


def _load_payload(*, update_heartbeat: bool = False) -> dict[str, Any]:
    path = state_path()
    if not path.exists():
        if lock_required():
            raise MasterLockStateError('Master lock state file is missing.')
        # Dev convenience: create disabled state on first access.
        return initialize_state()

    with _process_lock:
        lock_path = path.with_suffix(path.suffix + '.lock')
        with open(lock_path, 'a+', encoding='utf-8') as lock_file:
            _acquire_file_lock(lock_file)
            try:
                payload = _read_envelope(path)
                now = _utc_now()
                last_seen = _parse_iso(payload.get('last_seen'))
                if last_seen and now + CLOCK_ROLLBACK_TOLERANCE < last_seen:
                    raise MasterLockStateError('System clock rollback detected.')

                if update_heartbeat:
                    if last_seen is None or (now - last_seen) >= HEARTBEAT_INTERVAL:
                        payload = dict(payload)
                        payload['last_seen'] = _to_iso(now)
                        payload['action'] = 'heartbeat'
                        payload['updated_at'] = _to_iso(now)
                        _write_payload(payload)
                return payload
            finally:
                _release_file_lock(lock_file)


def _status_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    enabled = bool(payload.get('enabled'))
    valid_until = _parse_iso(payload.get('valid_until'))
    now = _utc_now()
    expired = bool(enabled and (valid_until is None or valid_until <= now))
    locked = expired
    return {
        'ok': True,
        'locked': locked,
        'enabled': enabled,
        'valid_until': _to_iso(valid_until),
        'last_seen': payload.get('last_seen'),
        'updated_at': payload.get('updated_at'),
        'action': payload.get('action'),
        'extension_count': int(payload.get('extension_count') or 0),
        'extension_days': EXTENSION_DAYS,
    }


def get_status(*, touch_heartbeat: bool = False) -> dict[str, Any]:
    """Return a JSON-safe status dict. Fail-closed when required."""
    try:
        payload = _load_payload(update_heartbeat=touch_heartbeat)
    except MasterLockError as exc:
        logger.warning('MASTER LOCK status fail-closed: %s', exc)
        return {
            'ok': False,
            'locked': True,
            'enabled': True,
            'valid_until': None,
            'error': 'locked',
            'detail': str(exc),
        }

    return _status_from_payload(payload)


def is_app_locked(*, touch_heartbeat: bool = True) -> bool:
    return bool(get_status(touch_heartbeat=touch_heartbeat)['locked'])


def verify_master_key(raw_key: str) -> bool:
    try:
        digest = password_hash()
    except ImproperlyConfigured:
        return False
    if not digest or not raw_key:
        return False
    return check_password(raw_key, digest)


def _client_rate_key(client_id: str) -> str:
    return client_id or 'unknown'


def check_rate_limit(client_id: str) -> bool:
    """Return True if the client is currently blocked."""
    key = f'sw:masterlock:fail:{_client_rate_key(client_id)}'
    try:
        import redis
        client = redis.Redis(host='127.0.0.1', port=6379, db=0, socket_connect_timeout=0.3)
        count = int(client.get(key) or 0)
        return count >= RATE_LIMIT_MAX_FAILURES
    except Exception:  # noqa: BLE001 — fall back to process memory
        now = time.time()
        mem_key = _client_rate_key(client_id)
        with _rate_limit_lock:
            stamps = [t for t in _rate_failures.get(mem_key, []) if now - t < RATE_LIMIT_WINDOW_SEC]
            _rate_failures[mem_key] = stamps
            if len(stamps) >= RATE_LIMIT_MAX_FAILURES:
                oldest = min(stamps)
                if now - oldest < RATE_LIMIT_COOLDOWN_SEC:
                    return True
                _rate_failures[mem_key] = []
                return False
            return False


def record_auth_failure(client_id: str) -> None:
    key = f'sw:masterlock:fail:{_client_rate_key(client_id)}'
    try:
        import redis
        client = redis.Redis(host='127.0.0.1', port=6379, db=0, socket_connect_timeout=0.3)
        pipe = client.pipeline()
        pipe.incr(key)
        pipe.expire(key, RATE_LIMIT_COOLDOWN_SEC)
        pipe.execute()
        return
    except Exception:  # noqa: BLE001
        pass
    now = time.time()
    mem_key = _client_rate_key(client_id)
    with _rate_limit_lock:
        stamps = [t for t in _rate_failures.get(mem_key, []) if now - t < RATE_LIMIT_WINDOW_SEC]
        stamps.append(now)
        _rate_failures[mem_key] = stamps


def clear_auth_failures(client_id: str) -> None:
    key = f'sw:masterlock:fail:{_client_rate_key(client_id)}'
    try:
        import redis
        client = redis.Redis(host='127.0.0.1', port=6379, db=0, socket_connect_timeout=0.3)
        client.delete(key)
    except Exception:  # noqa: BLE001
        pass
    with _rate_limit_lock:
        _rate_failures.pop(_client_rate_key(client_id), None)


def _mutate(action: str, *, master_key: str, client_id: str = '') -> dict[str, Any]:
    if check_rate_limit(client_id):
        raise MasterLockAuthError(GENERIC_AUTH_ERROR)
    if not verify_master_key(master_key):
        record_auth_failure(client_id)
        raise MasterLockAuthError(GENERIC_AUTH_ERROR)
    clear_auth_failures(client_id)

    path = state_path()
    with _process_lock:
        lock_path = path.with_suffix(path.suffix + '.lock')
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, 'a+', encoding='utf-8') as lock_file:
            _acquire_file_lock(lock_file)
            try:
                if path.exists():
                    payload = _read_envelope(path)
                elif lock_required():
                    raise MasterLockStateError('Master lock state file is missing.')
                else:
                    payload = _default_payload(action='init')

                now = _utc_now()
                last_seen = _parse_iso(payload.get('last_seen'))
                if last_seen and now + CLOCK_ROLLBACK_TOLERANCE < last_seen:
                    raise MasterLockStateError('System clock rollback detected.')

                payload = dict(payload)
                current_until = _parse_iso(payload.get('valid_until'))

                if action == 'enable':
                    payload['enabled'] = True
                    payload['valid_until'] = _to_iso(now + timedelta(days=EXTENSION_DAYS))
                    payload['extension_count'] = int(payload.get('extension_count') or 0) + 1
                elif action == 'extend':
                    if not payload.get('enabled'):
                        # Extending while disabled behaves like enable.
                        payload['enabled'] = True
                        base = now
                    else:
                        base = current_until if current_until and current_until > now else now
                    payload['valid_until'] = _to_iso(base + timedelta(days=EXTENSION_DAYS))
                    payload['extension_count'] = int(payload.get('extension_count') or 0) + 1
                elif action == 'disable':
                    payload['enabled'] = False
                    payload['valid_until'] = None
                else:
                    raise MasterLockError(f'Unknown action: {action}')

                payload['last_seen'] = _to_iso(now)
                payload['updated_at'] = _to_iso(now)
                payload['action'] = action
                payload['schema_version'] = SCHEMA_VERSION
                _write_payload(payload)
                logger.info(
                    'MASTER LOCK action=%s enabled=%s valid_until=%s extensions=%s client=%s',
                    action,
                    payload.get('enabled'),
                    payload.get('valid_until'),
                    payload.get('extension_count'),
                    client_id or '?',
                )
                return _status_from_payload(payload)
            finally:
                _release_file_lock(lock_file)


def enable_lock(*, master_key: str, client_id: str = '') -> dict[str, Any]:
    return _mutate('enable', master_key=master_key, client_id=client_id)


def extend_lock(*, master_key: str, client_id: str = '') -> dict[str, Any]:
    return _mutate('extend', master_key=master_key, client_id=client_id)


def disable_lock(*, master_key: str, client_id: str = '') -> dict[str, Any]:
    return _mutate('disable', master_key=master_key, client_id=client_id)
