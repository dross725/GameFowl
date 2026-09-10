"""WebSocket consumer for low-latency mobile print job push."""
from __future__ import annotations

import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from .models import PrintDevice

logger = logging.getLogger('SmartWagers.print_jobs')


def print_jobs_group(user_id: int) -> str:
    return f'print_jobs_user_{user_id}'


class PrintJobsConsumer(AsyncWebsocketConsumer):
    """Companion connects with ?token=<device auth_token>."""

    async def connect(self):
        query = self.scope.get('query_string', b'').decode('utf-8')
        token = ''
        for part in query.split('&'):
            if part.startswith('token='):
                token = part[6:].strip()
                break

        device = await self._device_for_token(token)
        if device is None:
            await self.close(code=4401)
            return

        self.device_id = device.pk
        self.user_id = device.user_id
        self.group_name = print_jobs_group(self.user_id)

        if self.channel_layer is None:
            await self.close()
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send(text_data=json.dumps({
            'type': 'connected',
            'device_id': device.device_id,
            'user': device.user.username,
        }))

    async def disconnect(self, close_code):
        group = getattr(self, 'group_name', None)
        if group and self.channel_layer is not None:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        # Companion may ping; ignore payload content.
        if text_data:
            try:
                data = json.loads(text_data)
            except json.JSONDecodeError:
                return
            if data.get('type') == 'ping':
                await self.send(text_data=json.dumps({'type': 'pong'}))

    async def print_job(self, event):
        await self.send(text_data=json.dumps({
            'type': 'print_job',
            'job': event.get('job'),
        }))

    @database_sync_to_async
    def _device_for_token(self, token: str):
        if not token:
            return None
        try:
            return PrintDevice.objects.select_related('user').get(auth_token=token)
        except PrintDevice.DoesNotExist:
            return None
