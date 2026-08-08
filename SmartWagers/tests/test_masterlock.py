"""Tests for SmartWagers master lock core, middleware, and HTTP enforcement."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client, override_settings

from SmartWagers import masterlock
from SmartWagers.models import Event

TEST_KEY = 'test-master-key-only-for-unit-tests'
TEST_HASH = make_password(TEST_KEY)
TEST_SIGNING = 'unit-test-master-lock-signing-key'


@pytest.fixture
def lock_env(tmp_path, settings):
    state = tmp_path / 'master_lock.state'
    settings.MASTER_LOCK_REQUIRED = True
    settings.MASTER_LOCK_SIGNING_KEY = TEST_SIGNING
    settings.MASTER_LOCK_PASSWORD_HASH = TEST_HASH
    settings.MASTER_LOCK_STATE_PATH = str(state)
    masterlock._rate_failures.clear()
    masterlock.initialize_state()
    return state


@pytest.mark.django_db
class TestMasterLockCore:

    def test_initial_state_is_disabled_unlocked(self, lock_env):
        status = masterlock.get_status(touch_heartbeat=False)
        assert status['ok'] is True
        assert status['enabled'] is False
        assert status['locked'] is False

    def test_enable_grants_thirty_days(self, lock_env):
        before = datetime.now(timezone.utc)
        status = masterlock.enable_lock(master_key=TEST_KEY, client_id='t1')
        assert status['enabled'] is True
        assert status['locked'] is False
        until = masterlock._parse_iso(status['valid_until'])
        assert until is not None
        delta = until - before
        assert timedelta(days=29, hours=23) < delta <= timedelta(days=30, minutes=1)

    def test_extend_from_future_valid_until(self, lock_env):
        first = masterlock.enable_lock(master_key=TEST_KEY, client_id='t1')
        first_until = masterlock._parse_iso(first['valid_until'])
        second = masterlock.extend_lock(master_key=TEST_KEY, client_id='t1')
        second_until = masterlock._parse_iso(second['valid_until'])
        assert second_until == first_until + timedelta(days=30)
        assert second['extension_count'] == 2

    def test_disable(self, lock_env):
        masterlock.enable_lock(master_key=TEST_KEY, client_id='t1')
        status = masterlock.disable_lock(master_key=TEST_KEY, client_id='t1')
        assert status['enabled'] is False
        assert status['locked'] is False
        assert status['valid_until'] is None

    def test_bad_key_rejected(self, lock_env):
        with pytest.raises(masterlock.MasterLockAuthError):
            masterlock.enable_lock(master_key='wrong-key', client_id='t1')
        status = masterlock.get_status(touch_heartbeat=False)
        assert status['enabled'] is False

    def test_expiry_locks_app(self, lock_env):
        masterlock.enable_lock(master_key=TEST_KEY, client_id='t1')
        past = datetime.now(timezone.utc) - timedelta(days=1)
        payload = masterlock._read_envelope(lock_env)
        payload['valid_until'] = masterlock._to_iso(past)
        payload['last_seen'] = masterlock._to_iso(past)
        masterlock._write_payload(payload)
        status = masterlock.get_status(touch_heartbeat=False)
        assert status['locked'] is True
        assert status['enabled'] is True

    def test_tampered_signature_fails_closed(self, lock_env):
        masterlock.enable_lock(master_key=TEST_KEY, client_id='t1')
        raw = json.loads(lock_env.read_text(encoding='utf-8'))
        raw['payload']['enabled'] = False
        lock_env.write_text(json.dumps(raw), encoding='utf-8')
        status = masterlock.get_status(touch_heartbeat=False)
        assert status['locked'] is True
        assert status['ok'] is False

    def test_missing_state_fails_closed_when_required(self, tmp_path, settings):
        settings.MASTER_LOCK_REQUIRED = True
        settings.MASTER_LOCK_SIGNING_KEY = TEST_SIGNING
        settings.MASTER_LOCK_PASSWORD_HASH = TEST_HASH
        settings.MASTER_LOCK_STATE_PATH = str(tmp_path / 'missing.state')
        status = masterlock.get_status(touch_heartbeat=False)
        assert status['locked'] is True

    def test_clock_rollback_fails_closed(self, lock_env):
        masterlock.enable_lock(master_key=TEST_KEY, client_id='t1')
        payload = masterlock._read_envelope(lock_env)
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        payload['last_seen'] = masterlock._to_iso(future)
        masterlock._write_payload(payload)
        status = masterlock.get_status(touch_heartbeat=False)
        assert status['locked'] is True

    def test_init_refuses_overwrite(self, lock_env):
        with pytest.raises(masterlock.MasterLockStateError):
            # Corrupt then refuse overwrite
            lock_env.write_text('not-json', encoding='utf-8')
            masterlock.initialize_state(force=False)


@pytest.mark.django_db
class TestMasterLockHttp:

    def test_health_ok_while_locked(self, lock_env):
        masterlock.enable_lock(master_key=TEST_KEY, client_id='t1')
        past = datetime.now(timezone.utc) - timedelta(days=1)
        payload = masterlock._read_envelope(lock_env)
        payload['valid_until'] = masterlock._to_iso(past)
        payload['last_seen'] = masterlock._to_iso(past)
        masterlock._write_payload(payload)

        client = Client()
        with override_settings(
            MASTER_LOCK_REQUIRED=True,
            MASTER_LOCK_SIGNING_KEY=TEST_SIGNING,
            MASTER_LOCK_PASSWORD_HASH=TEST_HASH,
            MASTER_LOCK_STATE_PATH=str(lock_env),
        ):
            response = client.get('/health/')
        assert response.status_code == 200
        data = response.json()
        assert data['ok'] is True
        assert data['locked'] is True
        assert response['Cache-Control'] == 'no-store'

    def test_locked_html_allows_login(self, lock_env):
        masterlock.enable_lock(master_key=TEST_KEY, client_id='t1')
        past = datetime.now(timezone.utc) - timedelta(days=1)
        payload = masterlock._read_envelope(lock_env)
        payload['valid_until'] = masterlock._to_iso(past)
        payload['last_seen'] = masterlock._to_iso(past)
        masterlock._write_payload(payload)

        client = Client()
        with override_settings(
            MASTER_LOCK_REQUIRED=True,
            MASTER_LOCK_SIGNING_KEY=TEST_SIGNING,
            MASTER_LOCK_PASSWORD_HASH=TEST_HASH,
            MASTER_LOCK_STATE_PATH=str(lock_env),
        ):
            response = client.get('/login')
        assert response.status_code == 200

    def test_locked_api_not_blocked(self, lock_env, teller_user):
        masterlock.enable_lock(master_key=TEST_KEY, client_id='t1')
        past = datetime.now(timezone.utc) - timedelta(days=1)
        payload = masterlock._read_envelope(lock_env)
        payload['valid_until'] = masterlock._to_iso(past)
        payload['last_seen'] = masterlock._to_iso(past)
        masterlock._write_payload(payload)

        client = Client()
        client.force_login(teller_user)
        with override_settings(
            MASTER_LOCK_REQUIRED=True,
            MASTER_LOCK_SIGNING_KEY=TEST_SIGNING,
            MASTER_LOCK_PASSWORD_HASH=TEST_HASH,
            MASTER_LOCK_STATE_PATH=str(lock_env),
        ):
            response = client.get(
                '/get_pot_values/',
                HTTP_ACCEPT='application/json',
                HTTP_X_REQUESTED_WITH='XMLHttpRequest',
            )
        assert response.status_code == 200

    def test_start_event_blocked_when_locked(self, lock_env, admin_user, default_settings):
        masterlock.enable_lock(master_key=TEST_KEY, client_id='t1')
        past = datetime.now(timezone.utc) - timedelta(days=1)
        payload = masterlock._read_envelope(lock_env)
        payload['valid_until'] = masterlock._to_iso(past)
        payload['last_seen'] = masterlock._to_iso(past)
        masterlock._write_payload(payload)

        client = Client()
        client.force_login(admin_user)
        with override_settings(
            MASTER_LOCK_REQUIRED=True,
            MASTER_LOCK_SIGNING_KEY=TEST_SIGNING,
            MASTER_LOCK_PASSWORD_HASH=TEST_HASH,
            MASTER_LOCK_STATE_PATH=str(lock_env),
        ):
            response = client.post('/administrator/start-event/', {'event_name': 'Night Derby'})
        assert response.status_code == 403
        assert response.json()['error'] == 'app_locked'
        assert Event.objects.filter(is_active=True).count() == 0

    def test_teller_can_logout_while_locked(self, lock_env, teller_user):
        masterlock.enable_lock(master_key=TEST_KEY, client_id='t1')
        past = datetime.now(timezone.utc) - timedelta(days=1)
        payload = masterlock._read_envelope(lock_env)
        payload['valid_until'] = masterlock._to_iso(past)
        payload['last_seen'] = masterlock._to_iso(past)
        masterlock._write_payload(payload)

        client = Client()
        client.force_login(teller_user)
        with override_settings(
            MASTER_LOCK_REQUIRED=True,
            MASTER_LOCK_SIGNING_KEY=TEST_SIGNING,
            MASTER_LOCK_PASSWORD_HASH=TEST_HASH,
            MASTER_LOCK_STATE_PATH=str(lock_env),
        ):
            response = client.post('/logout')

        assert response.status_code in (301, 302)
        assert response['Location'] == '/login'
        assert '_auth_user_id' not in client.session

    def test_activation_enable_unlocks(self, lock_env):
        # Force expired enabled state
        masterlock.enable_lock(master_key=TEST_KEY, client_id='t1')
        past = datetime.now(timezone.utc) - timedelta(days=1)
        payload = masterlock._read_envelope(lock_env)
        payload['valid_until'] = masterlock._to_iso(past)
        payload['last_seen'] = masterlock._to_iso(past)
        masterlock._write_payload(payload)

        client = Client()
        with override_settings(
            MASTER_LOCK_REQUIRED=True,
            MASTER_LOCK_SIGNING_KEY=TEST_SIGNING,
            MASTER_LOCK_PASSWORD_HASH=TEST_HASH,
            MASTER_LOCK_STATE_PATH=str(lock_env),
        ):
            response = client.post(
                '/master-lock/',
                {'action': 'enable', 'master_key': TEST_KEY},
                HTTP_ACCEPT='application/json',
                HTTP_X_REQUESTED_WITH='XMLHttpRequest',
            )
        assert response.status_code == 200
        data = response.json()
        assert data['ok'] is True
        assert data['locked'] is False


@pytest.mark.django_db
def test_admin_settings_master_lock_requires_superuser(lock_env, admin_user, default_settings):
    """Group admins who are not superusers cannot enable/disable via Settings."""
    assert not admin_user.is_superuser
    client = Client()
    client.force_login(admin_user)
    with override_settings(
        MASTER_LOCK_REQUIRED=True,
        MASTER_LOCK_SIGNING_KEY=TEST_SIGNING,
        MASTER_LOCK_PASSWORD_HASH=TEST_HASH,
        MASTER_LOCK_STATE_PATH=str(lock_env),
    ):
        response = client.post(
            '/administrator/settings/',
            {
                'action': 'master_lock_enable',
                'master_key': TEST_KEY,
            },
            HTTP_ACCEPT='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
    assert response.status_code == 403
    assert 'superuser' in response.json()['error'].lower()
    status = masterlock.get_status(touch_heartbeat=False)
    assert status['enabled'] is False


@pytest.mark.django_db
def test_admin_settings_master_lock_allows_superuser(lock_env, admin_user, default_settings):
    admin_user.is_superuser = True
    admin_user.save()
    client = Client()
    client.force_login(admin_user)
    with override_settings(
        MASTER_LOCK_REQUIRED=True,
        MASTER_LOCK_SIGNING_KEY=TEST_SIGNING,
        MASTER_LOCK_PASSWORD_HASH=TEST_HASH,
        MASTER_LOCK_STATE_PATH=str(lock_env),
    ):
        response = client.post(
            '/administrator/settings/',
            {
                'action': 'master_lock_enable',
                'master_key': TEST_KEY,
            },
            HTTP_ACCEPT='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
    assert response.status_code == 200
    assert response.json()['ok'] is True
    assert masterlock.get_status(touch_heartbeat=False)['enabled'] is True


@pytest.mark.django_db
def test_locked_page_rejects_disable_without_superuser(lock_env):
    masterlock.enable_lock(master_key=TEST_KEY, client_id='t1')
    past = datetime.now(timezone.utc) - timedelta(days=1)
    payload = masterlock._read_envelope(lock_env)
    payload['valid_until'] = masterlock._to_iso(past)
    payload['last_seen'] = masterlock._to_iso(past)
    masterlock._write_payload(payload)

    client = Client()
    with override_settings(
        MASTER_LOCK_REQUIRED=True,
        MASTER_LOCK_SIGNING_KEY=TEST_SIGNING,
        MASTER_LOCK_PASSWORD_HASH=TEST_HASH,
        MASTER_LOCK_STATE_PATH=str(lock_env),
    ):
        response = client.post(
            '/master-lock/',
            {'action': 'disable', 'master_key': TEST_KEY},
            HTTP_ACCEPT='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
    assert response.status_code == 403


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_websocket_allowed_when_locked(lock_env, teller_user, settings):
    """WebSocket connections stay open while locked (enforcement is at event start)."""
    settings.CHANNEL_LAYERS = {
        'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'},
    }
    masterlock.enable_lock(master_key=TEST_KEY, client_id='ws1')
    past = datetime.now(timezone.utc) - timedelta(days=1)
    payload = masterlock._read_envelope(lock_env)
    payload['valid_until'] = masterlock._to_iso(past)
    payload['last_seen'] = masterlock._to_iso(past)
    masterlock._write_payload(payload)

    from channels.testing import WebsocketCommunicator
    from GameFowl.asgi import application

    communicator = WebsocketCommunicator(application, '/ws/user/')
    communicator.scope['user'] = teller_user
    connected, _code = await communicator.connect()
    assert connected
    await communicator.disconnect()
