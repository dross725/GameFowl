# SmartWagers Print (Chrome OS USB extension)

Manifest V3 companion for Chromebooks **without Google Play**. Tellers keep using
the SmartWagers website in Chrome. This extension signs in as the same teller,
claims `/api/print-jobs/`, and writes the server’s 58 mm ESC/POS bytes to a
**USB** thermal printer.

Classic Bluetooth printers are not supported from a Chrome extension.

## Lab install (unpacked)

1. Plug the 58 mm USB ESC/POS printer into the Chromebook.
2. Open `chrome://extensions`, enable **Developer mode**.
3. **Load unpacked** → select this `chrome_print_extension` folder.
4. Open the extension popup → enter the SmartWagers LAN URL → sign in as the teller.
5. **Choose printer** → allow the USB device → **Test print**.
6. Place bets in Chrome as the same teller. Receipts queue to the server and print here.

If `claimInterface` fails, remove the printer under **Settings → Printers** so
Chrome OS releases the USB interface.

## Managed fleets

1. Download `SmartWagers-ChromePrint.zip` from **Admin → Print Agent**.
2. Upload / package for force-install via Google Admin
   (Devices → Chrome → Apps & extensions), or distribute the unpacked folder
   for developer-mode lab devices.
3. Force-install on the teller OU. No signing key is stored in this repository.

## Notes

- Password is never stored; only the companion bearer token is kept in
  `chrome.storage.local`.
- Host access is requested for the server origin at sign-in; a content script on
  that origin wakes the extension when the betting page queues a job.
- A one-minute alarm polls as a backup if the page message is missed.
