# GameFowl — SmartWagers

A real-time sabong (cockfighting) wagering management system built with Django and Django Channels.  
It supports three distinct user roles, live WebSocket-driven pot updates, PDF receipt generation, and a full fight lifecycle from open to payout.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Models](#models)
- [User Roles](#user-roles)
- [Fight Lifecycle](#fight-lifecycle)
- [WebSocket Events](#websocket-events)
- [Setup and Installation](#setup-and-installation)
- [Running the Server](#running-the-server)
- [Known Limitations](#known-limitations)

---

## Overview

GameFowl / SmartWagers manages live cockfight betting sessions. Two sides — **MERON** and **WALA** — each accumulate a pot from individual wagers placed by tellers. The admin controls the fight state (open, close, cancel, end with winner). Payouts are processed via a barcoded receipt system and multipliers (Llamado/Dehado) calculated from pool totals, with a configurable commission (plasada).

---

## Features

- **Role-based access** — `admin`, `teller`, and `display` roles with group-restricted views
- **Live updates** — WebSocket push (Django Channels + Redis) for pot values, fight status, and side open/close state
- **Fight lifecycle** — Start → Open Betting → Close Betting → Declare Winner → Payout
- **Per-side control** — Meron and Wala sides can be independently opened or closed
- **Bet management** — Place, confirm, and cancel individual bets (cancellation allowed while fight is open)
- **Receipts** — Barcoded bet receipts generated with ReportLab; payout receipts can be printed silently on each cashier's local Windows USB printer through the local print agent
- **Session logging** — Login/logout timestamps recorded per user
- **Fight results history** — Each completed fight is archived with totals, payouts, odds, and date
- **Django Admin** — All models registered for back-office inspection

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python / Django 5.1 |
| Async / WebSockets | Django Channels + Daphne |
| Channel layer | Redis (`127.0.0.1:6379`) |
| Database | SQLite (`db.sqlite3`) |
| PDF generation | ReportLab |
| Barcode generation | python-barcode |
| Static files | WhiteNoise |
| Frontend | Vanilla JS, HTML/CSS templates |

---

## Project Structure

```
GameFowl/               # Django project package
├── settings.py         # Configuration (DEBUG=True, SQLite, Redis channel layer)
├── urls.py             # Root URL conf (admin/ + SmartWagers/)
├── asgi.py             # ASGI entrypoint; routes HTTP and WebSocket
└── wsgi.py

SmartWagers/            # Main application
├── models.py           # Wagers, Totals, Settings, Fight_Results, Fight_Status, SessionLog
├── views.py            # HTTP views: login, index, teller, admin, JSON helpers
├── consumers.py        # WebSocket consumer (WagersConsumer)
├── services.py         # Domain logic: fight flow, totals, payouts, receipt printing
├── utils.py            # Utility stubs (trends)
├── admin.py            # Django admin registrations
├── routing.py          # WebSocket URL patterns
├── urls.py             # HTTP URL patterns for this app
├── signals.py          # Signal handlers (currently unregistered)
├── migrations/         # Database migrations
├── templates/SmartWagers/
│   ├── index.html          # Display board (read-only live view)
│   ├── user.html           # Teller interface (place bets, payout)
│   └── administrator.html  # Admin interface (fight control + teller UI)
└── static/SmartWagers/
    ├── administrator.js     # WebSocket client shared by all pages
    ├── submit_wagers.js     # Bet keypad and modal confirm logic
    ├── signals.js           # Signal/status helpers
    ├── user.js              # Teller-specific JS
    ├── index.css / user.css / admin.css / modal.css
    └── images/

templates/
└── base.html           # Shared layout: nav, pot blocks, WebSocket status

static/
└── app.css             # Global styles

local_print_agent/      # Windows localhost print agent for remote cashier USB printers
```

---

## Models

### `Wagers`
Individual bet records.

| Field | Description |
|-------|-------------|
| `transactionid` | Auto-generated ID (year + 6-digit counter) |
| `fightnum` | Fight number this bet belongs to |
| `side` | `MERON` or `WALA` |
| `wager` | Bet amount |
| `cashier` | Teller name who placed the bet |
| `created_at` | Timestamp |
| `cashed_out` | Whether payout has been collected |

Saving a `Wagers` instance automatically triggers `services.print_wager_reciept()` to generate a PDF receipt.

### `Totals`
Running pot snapshot per fight (append-only; latest row = current state).

| Field | Description |
|-------|-------------|
| `fightnum` | Fight number |
| `mtotal` / `wtotal` | Meron / Wala total bets |
| `mpayout` / `wpayout` | Computed payout multipliers |
| `totalpot` | Combined pool |

### `Settings`
Single-row global configuration.

| Field | Description |
|-------|-------------|
| `plasada` | Commission rate |
| `M_control_status` / `W_control_status` | Per-side open/close flag |

### `Fight_Status`
Current fight state (keyed by `id=1`).

| Field | Description |
|-------|-------------|
| `fightnum` | Active fight number |
| `overall_status` | `OPEN`, `CLOSED`, `CANCEL`, `END` |
| `meron_status` / `wala_status` | Per-side status |
| `date` | Date of the session |

### `Fight_Results`
Historical archive of completed fights.

| Field | Description |
|-------|-------------|
| `fightnum` | Fight number |
| `side` | Winning side |
| `totals / mpayout / wpayout / mtotal / wtotal` | Snapshot at end of fight |
| `odds` | Odds string |
| `date` | Date |

### `SessionLog`
Login/logout audit trail per user.

---

## User Roles

Access is controlled via Django **Groups**. Users must be assigned to one of these groups:

| Group | Redirected to | Capabilities |
|-------|--------------|--------------|
| `admin` | `/administrator/` | Fight lifecycle control, per-side open/close, bet placement, payout, cancel |
| `teller` | `/user/` | Bet placement, payout by barcode, bet cancellation |
| `display` | `/index/` | Read-only live view of pot totals and fight status |

Users not in any of these groups receive a 403 or are redirected to `/unauthorized/`.

---

## Fight Lifecycle

```
startnewmatch()
    └── Initializes Fight_Status (OPEN), creates new Totals row

── Tellers place bets ──────────────────────────────────────────
    add_wager()  →  creates Wagers row  →  receipt PDF printed
    compute_payout()  →  recalculates Llamado/Dehado multipliers

closematch()
    └── Sets overall_status = CLOSED (no new bets accepted)

endmatch(winner)
    └── update_fightresults()  →  archives to Fight_Results
    └── Payouts ready for processing

── Tellers scan receipts ───────────────────────────────────────
    payout_request(transactionid)
        └── Validates bet, checks winner, sets cashed_out=True
        └── Sends payout receipt data to the browser for local cashier printing

cancelmatch()
    └── Sets overall_status = CANCEL
    └── All bets eligible for refund

cancel_bet(transactionid)
    └── Only allowed while overall_status = OPEN
    └── Deducts from Totals, deletes Wagers row
```

Payout multipliers are only computed when a side's total exceeds **20,000**; below that threshold the displayed multiplier remains unchanged.

---

## WebSocket Events

All pages connect to `ws://localhost:8000/ws/{page}/` where `{page}` is `index`, `user`, or `administrator`.

### Client → Server (JSON)

| `type` | Payload | Description |
|--------|---------|-------------|
| `fight_status` | `{ status: "START"\|"CLOSED"\|"CANCEL"\|"END", Winner?: "MERON"\|"WALA" }` | Advance fight state |
| `side_status` | `{ side: "meron"\|"wala", status: "OPEN"\|"CLOSED" }` | Toggle per-side betting |
| `barcode` | `{ transactionid: "..." }` | Request payout for a bet |
| `cancel_barcode` | `{ transactionid: "..." }` | Cancel a bet |

### Server → Client (JSON broadcast)

After any state change the server broadcasts to all connected pages:

```json
{
  "mtotal": "12,500.00",
  "mpayout": "1.85",
  "wtotal": "9,300.00",
  "wpayout": "2.34",
  "fightnum": 42
}
```

Fight and side status changes are also broadcast so each page can update its UI without a page reload.

---

## Setup and Installation

### Prerequisites

- Python 3.10+
- Redis server running on `127.0.0.1:6379`

### Install dependencies

```bash
pip install django channels daphne channels-redis reportlab python-barcode whitenoise
```

> A `requirements.txt` is not currently included in the repository. Install from the above list or generate one with `pip freeze > requirements.txt` after setting up your environment.

### Database setup

```bash
python manage.py migrate
```

### Create roles and a superuser

```bash
python manage.py createsuperuser
```

Then in the Django admin (`/admin/`):
1. Create three **Groups**: `admin`, `teller`, `display`
2. Assign users to the appropriate group

### Collect static files (for production)

```bash
python manage.py collectstatic
```

---

## Running the Server

Start Redis first, then run the Django development server via Daphne (required for WebSocket support):

```bash
# Start Redis (if not already running)
redis-server

# Run the ASGI server
python manage.py runserver
```

The app will be available at `http://localhost:8000/`.

- **Login:** `http://localhost:8000/`
- **Display board:** `http://localhost:8000/index/`
- **Teller panel:** `http://localhost:8000/user/`
- **Admin panel:** `http://localhost:8000/administrator/`
- **Django admin:** `http://localhost:8000/admin/`

---

## Local Payout Receipt Printing

Remote cashier devices cannot silently print to USB printers through the browser alone. Each Windows cashier PC should run the local print agent in `local_print_agent/`.

On each cashier PC:

```bat
py -m pip install pywin32
copy config.example.json config.json
run_print_agent.bat
```

Set `printer_name` in `local_print_agent/config.json` to the exact Windows printer queue name, or leave it empty to use the Windows default printer. With the agent running, use these local URLs on the cashier PC:

```text
http://127.0.0.1:8765/health
http://127.0.0.1:8765/printers
```

When a bet is placed, the SmartWagers page sends receipt JSON to `http://127.0.0.1:8765/print-wager`. When a payout is approved, it sends receipt JSON to `http://127.0.0.1:8765/print-payout`. The agent accepts only localhost requests, renders the receipt with barcode text, and sends it to the cashier's configured USB printer.

---

## Known Limitations

- **Development-only config:** `DEBUG = True`, empty `ALLOWED_HOSTS`, and a hardcoded `SECRET_KEY` — do not deploy as-is.
- **WebSocket URLs are hardcoded** to `ws://localhost:8000/` in the frontend JS files; update these for any other host or HTTPS deployment.
- **SQLite** is not suitable for concurrent production load; migrate to PostgreSQL for production use.
- **`Fight_Status` assumes `id=1`** — the app expects a single row to always exist; it will error if the row is missing or there are multiple rows.
- **Bet receipt PDFs use a fixed filename** (`receipt_with_barcode.pdf`) and will be overwritten on each print; concurrent users on the same server can collide.
- **Silent local payout printing requires the Windows local print agent** to be running on every cashier PC.
- **`signals.py` is not connected** — it references a model table (`bets_bet`) that does not match current models and is not imported in `apps.py`, so its handlers never fire.
- **`USE_TZ = False`** with timezone set to `Asia/Manila` — be aware of DST edge cases if the app runs across midnight.
- **Session expires after 15 minutes** of inactivity (`SESSION_COOKIE_AGE = 900`).
