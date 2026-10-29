# Chromebook acceptance test (wager / payout / remit)

Use after installing companion **v1.1.0+** with Bluetooth and/or USB.

## Setup

1. Chromebook with Play Store; companion installed (managed Play or ADB — see README Distribution).
2. SmartWagers server reachable on LAN; teller account ready.
3. Pair Bluetooth printer **or** plug USB ESC/POS and allow USB access.
4. Companion: server URL → sign in → Scan → select printer → Test print → **Start service**.
5. Chrome (same Chromebook): open SmartWagers as the **same teller**.

Optional browser override:

```javascript
localStorage.setItem("smartwagersPrintMode", "server");
```

Auto mode on CrOS should queue to the companion when `127.0.0.1:8765` is absent.

## Matrix

| Receipt | Action in Chrome | Expected | USB | Bluetooth | Pass? |
| --- | --- | --- | --- | --- | --- |
| Wager | Place a bet | Bet receipt prints | | | |
| Payout | Pay a winning ticket | Payout receipt prints | | | |
| Remit | Advance / borrow (teller or admin) | Dual-copy remit prints | | | |
| Cancel / refund | Cancel / refund flow if used | Matching slip prints | | | |

## Routing smoke (no Chromebook)

```bash
node SmartWagers/static/SmartWagers/print_client_routing.test.mjs
```

## Notes

- Keep the companion service notification visible; if ARC kills background work, leave the app window open.
- USB and Bluetooth can be tested on separate passes — select the transport in the companion before each row.
