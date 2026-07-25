"""
ASGI config for GameFowl project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/howto/deployment/asgi/
"""

import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'GameFowl.settings')

import django
django.setup()

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
import SmartWagers.routing
from SmartWagers import masterlock

http_application = get_asgi_application()


class MasterLockWebsocketMiddleware:
    """Reject new WebSocket connections when the application master lock is active."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'websocket':
            locked = await database_sync_to_async(masterlock.is_app_locked)(touch_heartbeat=False)
            if locked:
                # Deny before AuthMiddlewareStack / consumer.
                while True:
                    message = await receive()
                    if message['type'] == 'websocket.connect':
                        await send({'type': 'websocket.close', 'code': masterlock.WS_CLOSE_LOCKED})
                        return
                    if message['type'] == 'websocket.disconnect':
                        return
        return await self.inner(scope, receive, send)


application = ProtocolTypeRouter({
    "http": http_application,
    "websocket": MasterLockWebsocketMiddleware(
        AuthMiddlewareStack(
            URLRouter(
                SmartWagers.routing.websocket_urlpatterns
            )
        )
    ),
})
