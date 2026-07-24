import json
import logging
import re
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from . import services
from .models import Settings, Wagers, Totals

logger = logging.getLogger('SmartWagers.consumers')

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

    @database_sync_to_async
    def _teller_is_online(self):
        """Return True if the connected teller is marked online by admin."""
        from .models import TellerStatus
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            return False
        ts, _ = TellerStatus.objects.get_or_create(user=user, defaults={"is_online": True})
        return ts.is_online

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self):
        # Extract the last part of the WebSocket URL
        self.page = self.scope.get("path", "").strip("/").split("/")[-1]

        if not self.page or not self.page.isalnum():
            logger.warning("WS REJECTED: invalid group name %r", self.page)
            await self.close()
            return

        if self.channel_layer is None:
            logger.error("WS CONNECT: channel layer unavailable — closing connection")
            await self.close()
            return

        # --- Authentication check ---
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            logger.warning("WS REJECTED (unauthenticated): path=/%s/", self.page)
            await self.close(code=4401)
            return

        # --- Authorization check ---
        allowed_groups = ENDPOINT_ALLOWED_GROUPS.get(self.page.lower(), set())
        user_groups = await self._get_user_groups()
        if allowed_groups and not (user_groups & allowed_groups):
            logger.warning(
                "WS REJECTED (unauthorized): user=%s groups=%s endpoint=/%s/",
                user.username, user_groups, self.page,
            )
            await self.close(code=4403)
            return

        logger.info("WS CONNECTED: user=%s endpoint=/%s/", user.username, self.page)
        await self.channel_layer.group_add(self.page, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if self.channel_layer is None:
            logger.error("WS DISCONNECT: channel layer unavailable")
            return

        user = self.scope.get("user")
        username = getattr(user, 'username', '?') if user else '?'
        logger.debug("WS DISCONNECTED: user=%s endpoint=/%s/ code=%s", username, self.page, code)
        if re.match(r"^[a-zA-Z0-9_.-]{1,99}$", self.page):
            await self.channel_layer.group_discard(self.page, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        if text_data:
            data = json.loads(text_data)

            if self.channel_layer is None:
                logger.error("WS RECEIVE: channel layer unavailable — message dropped")
                return

            # --- Per-action authorization ---
            action_key = next((k for k in ADMIN_ONLY_ACTIONS | TELLER_OR_ADMIN_ACTIONS if k in data), None)

            if action_key in ADMIN_ONLY_ACTIONS:
                if not await self._is_admin():
                    user = self.scope.get("user")
                    logger.warning(
                        "WS UNAUTHORIZED ACTION: action=%s user=%s endpoint=/%s/",
                        action_key, getattr(user, 'username', '?'), self.page,
                    )
                    await self.send(text_data=json.dumps({"error": "unauthorized"}))
                    return

            if action_key in TELLER_OR_ADMIN_ACTIONS:
                if not await self._is_teller_or_admin():
                    user = self.scope.get("user")
                    logger.warning(
                        "WS UNAUTHORIZED ACTION: action=%s user=%s endpoint=/%s/",
                        action_key, getattr(user, 'username', '?'), self.page,
                    )
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
                if self.page == "user" and not await self._teller_is_online():
                    await self.send(text_data=json.dumps({
                        "payout": True,
                        "error": "You are tagged as offline. Please report to the admin office.",
                    }))
                    return
                transaction_id = data["barcode"]
                # Tellers may only pay out bets made at their own terminal
                requesting_cashier = str(self.scope["user"]) if self.page == "user" else None
                payout_data = await self.payout_request(transaction_id, requesting_cashier)
                # Send payout result only to this connection, not the whole group,
                # so other terminals don't trigger duplicate prints.
                await self.send(text_data=json.dumps({'payout': True, **payout_data}))

            elif "cancel_barcode" in data:
                if self.page == "user" and not await self._teller_is_online():
                    await self.send(text_data=json.dumps({
                        "cancel_bet": True,
                        "error": "You are tagged as offline. Please report to the admin office.",
                    }))
                    return
                transaction_id = data["cancel_barcode"]
                cancelbet_data = await self.cancel_bet(transaction_id)
                # Same as above — reply only to the connection that submitted the scan.
                await self.send(text_data=json.dumps(cancelbet_data))
                
            # Fetch updated values from the database
            mtotal, mpayout, wtotal, wpayout, total_bet, fightnum = await self.get_values_from_database()

            # Broadcast updates to ALL WebSocket groups (index, user, admin)
            for group_name in ["index", "user", "administrator"]:
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
            logger.debug("WS send_data PAYOUT: %s", event)
            response.update(event)

        elif 'cancel_bet' in event:
            logger.debug("WS send_data CANCEL_BET: %s", event)
            response.update(event)

        else:
            logger.debug("WS send_data OTHER: %s", event)
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
    def payout_request(self, transaction_id, requesting_cashier=None):
        return services.payout_request(transaction_id, requesting_cashier=requesting_cashier)
    
    @database_sync_to_async
    def cancel_bet(self, transaction_id):
        return services.cancel_bet(transaction_id)
 