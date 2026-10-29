# Chromebook hardware spike checklist

Run this once on a real Chromebook with **Google Play / ARC enabled** before relying on USB or Classic Bluetooth in production. Results decide whether USB host works under ARC, or whether Bluetooth (and optional TCP 9100) is enough.

## Prerequisites

- Chromebook with Play Store available (not policy-blocked).
- Current companion APK installed (Admin → Print Agent, or `mobile_print_agent/dist/SmartWagers-PrintCompanion.apk`).
- Same LAN as the SmartWagers server.
- One Classic Bluetooth ESC/POS printer (e.g. XP-58) and/or one USB ESC/POS printer.

## Checklist

| # | Check | Pass? | Notes |
| --- | --- | --- | --- |
| 1 | Install APK / Play private app; app launches in a resizable window | | |
| 2 | Sign in with teller credentials + server URL | | |
| 3 | Pair Classic BT printer in Chrome OS / Android settings | | |
| 4 | **Scan printers** lists the bonded Classic SPP device | | |
| 5 | **Test print** over Bluetooth succeeds | | |
| 6 | **Start service**; sticky notification stays visible | | |
| 7 | Open Chrome, place a bet as the same teller; receipt prints while Chrome is foreground | | |
| 8 | Plug USB thermal printer; Chrome OS / Android prompts for USB access | | |
| 9 | **Scan printers** lists a USB device (`transport: usb`) | | |
| 10 | **Test print** over USB succeeds | | |
| 11 | Bet / payout / remit via Chrome while USB selected | | |

## Decision guide

- **BT pass, USB fail:** ship Bluetooth for Chromebooks; keep USB code for devices that support host mode; document OTG/USB-host limitation.
- **USB pass, BT fail:** prefer USB on Chromebooks; investigate ARC Classic SPP; BLE dual-mode printers as fallback.
- **Both fail:** fall back to network printers (TCP 9100) or browser WebUSB — out of current companion scope.
- **Foreground service killed when Chrome is up:** keep the companion window open / pinned; check ARC battery restrictions.

## Assumed outcome for this implementation

Code proceeds with **Classic Bluetooth + USB host** both wired in the companion. Live spike results should be pasted into this file by the operator when available.
