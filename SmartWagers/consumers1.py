# bets/consumers.py

import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from .models import Totals
from .models import Wagers
from django.db.models import Sum

class WagersConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        print("Connecting WebSocket...")
        if self.channel_layer is None:
            print("Error: channel_layer is None! Check Django Channels settings.")
        else:
            await self.channel_layer.group_add("bet_updates", self.channel_name)
            await self.accept()

    async def disconnect(self, code):
        print ('disconnect')
        # Leave the group
        if self.channel_layer is None:
            print("Error: channel_layer is None! Check Django Channels settings.")
        else:
            await self.channel_layer.group_discard("bet_updates", self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        print('receive')
        if text_data:
            data = json.loads(text_data)
            print(data)
            if data.get('action') == 'update':
                total = await self.get_total_bet_amount()
                if self.channel_layer == None:
                    print ("Receive error")
                else:

                    await self.channel_layer.group_send("bet_updates", {
                        'type': 'send_total',
                        'totalpot': total
                    })

    async def send_total(self, event):
        total_amount = event['totalpot']
        await self.send(text_data=json.dumps({
            'totalpot': total_amount
        }))

    @database_sync_to_async
    def get_total_bet_amount(self):
        return Totals.objects.aggregate(Sum('totalpot')).get('totalpot__sum', 0)  # Correct key lookup