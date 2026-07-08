import json
import re
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from . import services
from .models import Settings, Wagers, Totals

# Maps each WebSocket endpoint to the groups that are allowed to connect.
# An empty set means any authenticated user is permitted.
ENDPOINT_ALLOWED_GROUPS = {
    "administrator": {"admin"},
    "user":          {"teller"},
    "index":         {"admin", "teller", "display"},
    "smartwagers":   {"admin"},
}

# Actions that only admins may trigger via WebSocket
ADMIN_ONLY_ACTIONS = {"fight_status", "side_status"}

# Actions that tellers or admins may trigger
TELLER_OR_ADMIN_ACTIONS = {"barcode", "cancel_barcode"}

class WagersConsumer(AsyncWebsocketConsumer):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.debug = False

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    @database_sync_to_async
    def _get_user_groups(self):
        """Return the set of group names the connected user belongs to."""
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            return set()
        return set(user.groups.values_list("name", flat=True))

    async def _is_admin(self):
        return "admin" in await self._get_user_groups()

    async def _is_teller_or_admin(self):
        groups = await self._get_user_groups()
        return bool(groups & {"teller", "admin"})

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

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

        # --- Authentication check ---
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            print(f"Unauthenticated WebSocket connection attempt to /{self.page}/ — rejected.")
            await self.close(code=4401)
            return

        # --- Authorization check ---
        allowed_groups = ENDPOINT_ALLOWED_GROUPS.get(self.page.lower(), set())
        user_groups = await self._get_user_groups()
        if allowed_groups and not (user_groups & allowed_groups):
            print(
                f"User '{user.username}' (groups={user_groups}) not authorized "
                f"for WebSocket /{self.page}/."
            )
            await self.close(code=4403)
            return

        print(f"User '{user.username}' connected to WebSocket group: {self.page}")
        await self.channel_layer.group_add(self.page, self.channel_name)
        await self.accept()

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

            if self.channel_layer is None:
                print("Channel layer is not available during receive.")
                return

            # --- Per-action authorization ---
            action_key = next((k for k in ADMIN_ONLY_ACTIONS | TELLER_OR_ADMIN_ACTIONS if k in data), None)

            if action_key in ADMIN_ONLY_ACTIONS:
                if not await self._is_admin():
                    user = self.scope.get("user")
                    print(f"Unauthorized action '{action_key}' by user '{getattr(user, 'username', '?')}' — ignored.")
                    await self.send(text_data=json.dumps({"error": "unauthorized"}))
                    return

            if action_key in TELLER_OR_ADMIN_ACTIONS:
                if not await self._is_teller_or_admin():
                    user = self.scope.get("user")
                    print(f"Unauthorized action '{action_key}' by user '{getattr(user, 'username', '?')}' — ignored.")
                    await self.send(text_data=json.dumps({"error": "unauthorized"}))
                    return

            if "fight_status" in data:
                fight_status = data["fight_status"]

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
                    await self.channel_layer.group_send(group_name, {
                        'type': 'send_data',
                        'fight_status': fight_status
                    })

            elif "side_status" in data:
                side_status = data["side_status"]
                side = data["side"]
                await self.update_control_status(side, side_status)
                overall_status, meron_status, wala_status, fightnum = await self.get_fight_status()

                for group_name in ["index", "user", "administrator"]:
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
                # Tellers may only pay out bets made at their own terminal
                requesting_cashier = str(self.scope["user"]) if self.page == "user" else None
                payout_data = await self.payout_request(transaction_id, requesting_cashier)
                # Send payout result only to this connection, not the whole group,
                # so other terminals don't trigger duplicate prints.
                await self.send(text_data=json.dumps({'payout': True, **payout_data}))

            elif "cancel_barcode" in data:
                transaction_id = data["cancel_barcode"]
                cancelbet_data = await self.cancel_bet(transaction_id)
                # Same as above — reply only to the connection that submitted the scan.
                await self.send(text_data=json.dumps(cancelbet_data))
                
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
    def payout_request(self, transaction_id, requesting_cashier=None):
        return services.payout_request(transaction_id, requesting_cashier=requesting_cashier)
    
    @database_sync_to_async
    def cancel_bet(self, transaction_id):
        return services.cancel_bet(transaction_id)
 