import json
import re
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from . import services
from .models import Settings, Wagers, Totals

class WagersConsumer(AsyncWebsocketConsumer):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.debug = True
            
    async def connect(self):
        # Extract the last part of the WebSocket URL
        self.page = self.scope.get("path", "").strip("/").split("/")[-1]
        
        if not self.page or not self.page.isalnum():
            print(f"Invalid WebSocket group name: '{self.page}'")
            await self.close()
            return
        
        if self.channel_layer is None:
            print("Channel layer is not available.")
            await self.close()
            return
        
        # Join the WebSocket group based on the page
        print(f"Connecting to WebSocket group: {self.page}")
        await self.channel_layer.group_add(self.page, self.channel_name)
        await self.accept()
        print(f"Connected to WebSocket group: {self.page}")

    async def disconnect(self, code):
        
        if self.channel_layer is None:
            print("Channel layer is not available during disconnect.")
            return
        # Leave the WebSocket group based on the page

        print(f"Disconnecting from WebSocket group: {self.page}")
        if re.match(r"^[a-zA-Z0-9_.-]{1,99}$", self.page):  # Ensure name is valid before removing
            await self.channel_layer.group_discard(self.page, self.channel_name)
        #await self.channel_layer.group_discard(self.page, self.channel_name)
        print(f"Disconnected from WebSocket group: {self.page}")

    async def receive(self, text_data=None, bytes_data=None):
        if text_data:
            data = json.loads(text_data)
            print("Received WebSocket data:", data)

            if self.channel_layer is None:
                print("Channel layer is not available during receive.")
                return
            
            if "fight_status" in data:
                # Handle fight status updates
                fight_status = data["fight_status"]
                print(f"Received fight status: {fight_status}")

                if fight_status == "START":
                    await self.startnewmatch()
                elif fight_status == "CLOSED":
                    await self.closematch()
                elif fight_status == "CANCEL":
                    await self.cancelmatch()
                elif fight_status == "END":
                    winner = data["Winner"]
                    await self.endmatch(winner)

                for group_name in ["index", "user", "administrator"]:
                    print(f"Sending data to group: {group_name}")
                    await self.channel_layer.group_send(group_name, {
                        'type': 'send_data',
                        'fight_status': fight_status
                    })
                
            elif "side_status" in data:
                side_status = data["side_status"]
                side = data["side"]
                await self.update_control_status(side, side_status)
                overall_status, meron_status, wala_status, fightnum = await self.get_fight_status()
                print ("side status updated: ", side_status, "for side:", side)

                for group_name in ["index", "user", "administrator"]:
                    print(f"Sending data to group: {group_name}")
                    await self.channel_layer.group_send(group_name, {
                        'type': 'send_data',
                        'side': side,
                        'side_status': side_status,
                        'overall_status': overall_status,
                        'meron_status': meron_status,
                        'wala_status': wala_status,
                        'fightnum': fightnum
                    })

            elif "barcode" in data:
                transaction_id = data["barcode"]
                payout_data = await self.payout_request(transaction_id)
                await self.channel_layer.group_send(self.page, {
                    'type': 'send_data',
                    'payout': True,
                    **payout_data
                })
            
            elif "cancel_barcode" in data:
                print ("Cancel barcode received:", data["cancel_barcode"])
                transaction_id = data["cancel_barcode"]
                cancelbet_data = await self.cancel_bet(transaction_id)
                await self.channel_layer.group_send(self.page, {
                    'type': 'send_data',
                    **cancelbet_data
                })
                
            # Fetch updated values from the database
            mtotal, mpayout, wtotal, wpayout, total_bet, fightnum = await self.get_values_from_database()

            # Broadcast updates to ALL WebSocket groups (index, user, admin)
            for group_name in ["index", "user", "administrator"]:
                #print(f"Sending data to group: {group_name}")
                await self.channel_layer.group_send(group_name, {
                    'type': 'send_data',
                    'mtotal': mtotal,
                    'mpayout': mpayout,  
                    'wtotal': wtotal,
                    'wpayout': wpayout,
                    'fightnum': fightnum
                })

    async def send_data(self, event):
        response = {}
        # print ("Sending Data to WebSocket group:", self.page)
        # print ("Event data:", event)
        # print ('fn:', event.get('fightnum'))
        # Handle left/right value updates
        if "mtotal" in event and "wtotal" in event:
            response["mtotal"] = event["mtotal"]
            response["mpayout"] = event["mpayout"]
            response["wtotal"] = event["wtotal"]
            response["wpayout"] = event["wpayout"]
            response["fightnum"] = event["fightnum"]
        
        elif "side" in event and "side_status" in event:
            response["side"] = event["side"]
            response["side_status"] = event["side_status"]
            response["overall_status"] = event["overall_status"]
            response["meron_status"] = event["meron_status"]
            response["wala_status"] = event["wala_status"]
            response["fightnum"] = event["fightnum"]

        elif 'payout' in event:
            print ("Payout event data:", event)
            #event.pop('type', None)
            response.update(event)
            # if 'error' in event:
            #     response.update(event)
            # elif 'payout_result' in event:
            #     response.update(event['payout_result'])
            print ("Payout response data:", response)
            
        elif 'cancel_bet' in event:
            #event.pop('type', None)
            response.update(event)
            print ("Cancel Bet response data:", response)

        else:
            print ("Other event data:", event)
            response.update(event)    
        
        await self.send(text_data=json.dumps(response))

    @database_sync_to_async
    def get_values_from_database(self):
        meron_total, meron_payout, wala_total, wala_payout, total_bet, fight_num = services.get_Totals() 
        return format(int(meron_total), ','), meron_payout, format(int(wala_total), ','), wala_payout, total_bet, fight_num  # Fetch mtotal and wtotal
        
    @database_sync_to_async
    def get_control_status(self):
        m_control_status, w_control_status = services.get_control_status()
        return m_control_status, w_control_status
    
    @database_sync_to_async
    def update_control_status(self, side, status):
        return services.update_control_status(side, status)

    @database_sync_to_async
    def get_fight_status(self):
        return services.get_fight_status()
    
    @database_sync_to_async
    def startnewmatch(self):
        return services.startnewmatch()
    
    @database_sync_to_async
    def closematch(self):
        return services.closematch()
    
    @database_sync_to_async
    def cancelmatch(self):
        return services.cancelmatch()
    
    @database_sync_to_async
    def endmatch(self, winner):
        return services.endmatch(winner)
    
    @database_sync_to_async
    def update_fight_status(self, fight_status, side = None):
        return services.update_fight_status(fight_status, side)
    
    @database_sync_to_async
    def get_fight_status(self):
        return services.get_fight_status()
    
    @database_sync_to_async
    def payout_request(self, transaction_id):
        return services.payout_request(transaction_id)
    
    @database_sync_to_async
    def cancel_bet(self, transaction_id):
        return services.cancel_bet(transaction_id)
 