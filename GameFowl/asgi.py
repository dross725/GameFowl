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
import SmartWagers.routing

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": AuthMiddlewareStack(
        URLRouter(
            SmartWagers.routing.websocket_urlpatterns
        )
    ),
})

# application = ProtocolTypeRouter({
#     "http": get_asgi_application(),
#     "websocket": URLRouter(websocket_urlpatterns),
# })
#application = get_asgi_application()