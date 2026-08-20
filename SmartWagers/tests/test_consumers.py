"""
Tests for the WagersConsumer WebSocket consumer.

Uses channels.testing.WebsocketCommunicator with an InMemoryChannelLayer
so no Redis is required.

NOTE: Django Channels consumers run in async context; pytest-asyncio handles
the event loop via asyncio_mode = auto (set in pytest.ini).
"""

import json
import pytest
from channels.testing import WebsocketCommunicator
from channels.layers import get_channel_layer
from django.contrib.auth.models import AnonymousUser
from unittest.mock import patch, AsyncMock

from GameFowl.asgi import application
from SmartWagers.models import (
    Event, Fight_Results, Fight_Status, TellerStatus, Totals, Wagers,
)


# ---------------------------------------------------------------------------
# Helpers to build a minimal ASGI scope
# ---------------------------------------------------------------------------

def _ws_scope(path, user=None):
    return {
        'type': 'websocket',
        'path': path,
        'query_string': b'',
        'headers': [],
        'user': user or AnonymousUser(),
        'session': {},
        'subprotocols': [],
    }


def _open_fight(fightnum=1):
    Fight_Status.objects.all().delete()
    Fight_Status.objects.create(
        fightnum=fightnum, overall_status='OPEN',
        meron_status='OPEN', wala_status='OPEN',
    )
    Totals.objects.create(fightnum=fightnum, mtotal=0, wtotal=0,
                           mpayout=0, wpayout=0, totalpot=0)
    Wagers.objects.create(fightnum=fightnum, side='START', wager=0,
                           cashier='System', registered=True)


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_unauthenticated_connection_rejected(settings):
    """Anonymous users must be rejected with close code 4401."""
    settings.CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        }
    }
    communicator = WebsocketCommunicator(application, '/ws/user/')
    connected, code = await communicator.connect()
    assert not connected or code == 4401
    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_admin_connects_to_administrator_endpoint(admin_user, settings, default_settings):
    """Authenticated admin can connect to /ws/administrator/."""
    settings.CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        }
    }
    communicator = WebsocketCommunicator(application, '/ws/administrator/')
    communicator.scope['user'] = admin_user
    connected, code = await communicator.connect()
    assert connected, f"Expected connection, got close code {code}"
    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_teller_connects_to_user_endpoint(teller_user, settings, default_settings):
    """Authenticated teller can connect to /ws/user/."""
    settings.CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        }
    }
    communicator = WebsocketCommunicator(application, '/ws/user/')
    communicator.scope['user'] = teller_user
    connected, code = await communicator.connect()
    assert connected, f"Expected connection, got close code {code}"
    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_teller_rejected_from_administrator_endpoint(teller_user, settings):
    """Teller must not be allowed to connect to /ws/administrator/."""
    settings.CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        }
    }
    communicator = WebsocketCommunicator(application, '/ws/administrator/')
    communicator.scope['user'] = teller_user
    connected, code = await communicator.connect()
    assert not connected or code == 4403
    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_malformed_json_returns_error_without_disconnect(admin_user, settings):
    settings.CHANNEL_LAYERS = {
        'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}
    }
    communicator = WebsocketCommunicator(application, '/ws/administrator/')
    communicator.scope['user'] = admin_user
    connected, _ = await communicator.connect()
    assert connected

    await communicator.send_to(text_data='{not valid json')
    assert await communicator.receive_json_from(timeout=3) == {'error': 'invalid_json'}

    await communicator.send_json_to({'fight_status': 'END'})
    assert await communicator.receive_json_from(timeout=3) == {'error': 'missing_winner'}
    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_side_status_requires_valid_side(admin_user, settings):
    settings.CHANNEL_LAYERS = {
        'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}
    }
    communicator = WebsocketCommunicator(application, '/ws/administrator/')
    communicator.scope['user'] = admin_user
    connected, _ = await communicator.connect()
    assert connected

    await communicator.send_json_to({'side_status': 'OPEN'})
    assert await communicator.receive_json_from(timeout=3) == {'error': 'invalid_side'}
    await communicator.disconnect()


# ---------------------------------------------------------------------------
# fight_status message (admin only)
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_fight_status_start_message_accepted_by_admin(
        admin_user, settings, default_settings):
    settings.CHANNEL_LAYERS = {
        'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}
    }
    communicator = WebsocketCommunicator(application, '/ws/administrator/')
    communicator.scope['user'] = admin_user
    connected, _ = await communicator.connect()
    assert connected

    await communicator.send_json_to({'fight_status': 'START'})
    # Drain any broadcast messages; no error response expected
    response = await communicator.receive_json_from(timeout=3)
    # The response is the pot broadcast (mtotal, wtotal, …) — not an error
    assert 'error' not in response
    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_fight_status_rejected_for_non_admin(teller_user, settings, default_settings):
    """Teller sending fight_status must receive an 'unauthorized' error."""
    settings.CHANNEL_LAYERS = {
        'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}
    }
    communicator = WebsocketCommunicator(application, '/ws/user/')
    communicator.scope['user'] = teller_user
    connected, _ = await communicator.connect()
    assert connected

    await communicator.send_json_to({'fight_status': 'START'})
    response = await communicator.receive_json_from(timeout=3)
    assert response.get('error') == 'unauthorized'
    await communicator.disconnect()


# ---------------------------------------------------------------------------
# barcode / payout message
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_barcode_nonexistent_returns_notfound(teller_user, settings, active_event):
    """Scanning a non-existent barcode returns error='notfound'.
    DB seed is done via sync_to_async so it is safe in async context."""
    from asgiref.sync import sync_to_async
    settings.CHANNEL_LAYERS = {
        'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}
    }
    # Seed minimal Totals so the post-message broadcast does not fail
    await sync_to_async(Totals.objects.create)(
        fightnum=0, mtotal=0, wtotal=0, mpayout=0, wpayout=0, totalpot=0
    )
    communicator = WebsocketCommunicator(application, '/ws/user/')
    communicator.scope['user'] = teller_user
    connected, _ = await communicator.connect()
    assert connected

    await communicator.send_json_to({'barcode': '999999'})
    response = await communicator.receive_json_from(timeout=3)
    assert response.get('payout') is True
    assert response.get('error') == 'notfound'
    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_offline_teller_barcode_returns_stable_error_code(
        teller_user, settings, active_event):
    from asgiref.sync import sync_to_async

    settings.CHANNEL_LAYERS = {
        'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}
    }
    await sync_to_async(TellerStatus.objects.update_or_create)(
        user=teller_user, defaults={'is_online': False},
    )

    communicator = WebsocketCommunicator(application, '/ws/user/')
    communicator.scope['user'] = teller_user
    connected, _ = await communicator.connect()
    assert connected

    await communicator.send_json_to({'barcode': '123456'})
    response = await communicator.receive_json_from(timeout=3)

    assert response == {'payout': True, 'error': 'teller_offline'}
    await communicator.disconnect()


# ---------------------------------------------------------------------------
# cancel_barcode message
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_cancel_barcode_nonexistent_returns_notfound(teller_user, settings, active_event):
    """Scanning a non-existent cancel barcode returns an error.
    DB seed via sync_to_async to remain safe in async context."""
    from asgiref.sync import sync_to_async
    settings.CHANNEL_LAYERS = {
        'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}
    }
    await sync_to_async(Totals.objects.create)(
        fightnum=0, mtotal=0, wtotal=0, mpayout=0, wpayout=0, totalpot=0
    )
    await sync_to_async(Fight_Status.objects.create)(
        fightnum=0, overall_status='OPEN', meron_status='OPEN', wala_status='OPEN'
    )
    communicator = WebsocketCommunicator(application, '/ws/user/')
    communicator.scope['user'] = teller_user
    connected, _ = await communicator.connect()
    assert connected

    await communicator.send_json_to({'cancel_barcode': '999999'})
    response = await communicator.receive_json_from(timeout=3)
    assert 'error' in response
    await communicator.disconnect()


# ---------------------------------------------------------------------------
# send_data broadcast helper
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_fight_status_closed_broadcast_includes_full_status(
        admin_user, teller_user, settings, default_settings):
    """Close Betting must broadcast CLOSED plus overall/side statuses to tellers."""
    from asgiref.sync import sync_to_async

    settings.CHANNEL_LAYERS = {
        'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}
    }
    await sync_to_async(Fight_Status.objects.all().delete)()
    await sync_to_async(Fight_Status.objects.create)(
        fightnum=1, overall_status='OPEN', meron_status='OPEN', wala_status='OPEN'
    )
    await sync_to_async(Totals.objects.create)(
        fightnum=1, mtotal=0, wtotal=0, mpayout=0, wpayout=0, totalpot=0
    )

    admin = WebsocketCommunicator(application, '/ws/administrator/')
    admin.scope['user'] = admin_user
    teller = WebsocketCommunicator(application, '/ws/user/')
    teller.scope['user'] = teller_user

    assert (await admin.connect())[0]
    assert (await teller.connect())[0]

    await admin.send_json_to({'fight_status': 'CLOSED'})

    closed_msg = None
    for _ in range(5):
        msg = await teller.receive_json_from(timeout=3)
        if msg.get('fight_status') == 'CLOSED':
            closed_msg = msg
            break

    assert closed_msg is not None
    assert closed_msg['overall_status'] == 'CLOSED'
    assert closed_msg['meron_status'] in ('CLOSE', 'CLOSED')
    assert closed_msg['wala_status'] in ('CLOSE', 'CLOSED')
    assert 'fightnum' in closed_msg

    await admin.disconnect()
    await teller.disconnect()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_pot_broadcast_received_after_fight_start(
        admin_user, settings, default_settings):
    """After a fight_status=START message the consumer broadcasts pot values."""
    settings.CHANNEL_LAYERS = {
        'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}
    }
    communicator = WebsocketCommunicator(application, '/ws/administrator/')
    communicator.scope['user'] = admin_user
    connected, _ = await communicator.connect()
    assert connected

    await communicator.send_json_to({'fight_status': 'START'})
    response = await communicator.receive_json_from(timeout=3)
    # The broadcast contains pot values
    assert 'mtotal' in response or 'fight_status' in response
    await communicator.disconnect()
