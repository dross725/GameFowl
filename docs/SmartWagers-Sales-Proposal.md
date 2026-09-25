# SmartWagers
### Sales Proposal — Arena Wagering & Cash Control Platform

**Prepared for:** Prospective arena operators and derby organizers  
**Product:** SmartWagers (GameFowl)  
**Document type:** Feature & value proposal  

---

## 1. Executive summary

**SmartWagers** is an on-premise, real-time sabong arena system built for the cashier desk—not a retail betting app. Admins run fights and events; tellers take MERON / WALA bets and pay winning tickets; a live display board mirrors pots and payouts; and dedicated print agents keep barcoded receipts on the teller station.

It replaces paper pads, radio calls, and end-of-night spreadsheet chaos with one controlled workflow: **event start → fight control → bet & payout → cash reconciliation → event report**.

---

## 2. Who it is for

| Role | What they get |
|------|----------------|
| **Arena / derby operators** | Full event lifecycle, commission (plasada) visibility, cash reconciliation, audit trail |
| **Administrators** | Fight control, side open/close, fund management, teller oversight, user & settings control |
| **Tellers / cashiers** | Fast bet entry, barcode payout/cancel, float & remittance, station closeout |
| **Floor / audience display** | Read-only live board of MERON / WALA totals and payouts |

There is no public “bettor login.” Staff place and settle tickets on behalf of patrons—matching how real arena desks operate.

---

## 3. The problem we solve

Typical arena pain points:

- Slow or inconsistent pot updates across stations  
- Ticket disputes with no barcode trail  
- Float and remittance tracked on paper  
- Weak control when a teller is over limit or offline  
- Long closeouts with unclear variance  
- Commission and event P&L assembled manually after the derby  

**SmartWagers** addresses these with live WebSocket updates, sequenced transaction IDs, role-based access, cash ledgers, and event archival.

---

## 4. Core features

### 4.1 Live fight & event control

- Fight lifecycle: **Start → Open betting → Close → End (MERON / WALA) or Cancel**
- Independent **open / close** for Meron and Wala sides
- Sequential fight numbering; resets cleanly with each new event
- Named **events** (derby days) with a single active-event model
- **Start Event / End Event** with cash-count readiness before close
- Fight results stored with winner, pots, odds, and event linkage
- Admin correction of fight winners when needed

### 4.2 Teller betting & payouts

- Fast MERON / WALA bet entry with numeric keypad and confirm step
- Automatic **transaction IDs** for every wager
- Safe re-submit protection (idempotent bet requests)
- Live pot totals, payout multipliers, and house commission (**plasada**) in the math
- Bet **cancel** while the fight is open
- **Barcode** payout and cancel workflows
- **Reprint** of wager receipts (tellers: own tickets; admins: any)
- Optional **wrong-punch guard** (e.g. reject amounts ending in 3 or 6) with teller counters
- **Over-limit bets** held pending admin **approve / reject**—receipt prints only after approval
- Claim / payout of **old tickets** across prior events

### 4.3 Cash, float & station control

- Shared **admin fund** per event (opening fund, bank borrow / remit)
- Automatic **teller float** at event start
- Teller ledger: **Advance (REMIT)**, **Borrow (COLLECT)**, **Payout**
- Pending advances: edit / cancel; admin mark-as-received
- Balance alerts when tellers hit max / min on-hand thresholds
- Admin **online / offline** toggle—offline tellers cannot bet or pay out
- **Station closeout**: expected vs counted cash, variance, reopen, edit count
- Payout blocked when teller cash-on-hand is insufficient
- Event end **archives** wagers and fund transactions for a clean audit trail

### 4.4 Live arena display

- Dedicated **display** role for a read-only board
- Real-time MERON / WALA pots and payout figures
- Synchronized with admin and teller stations over WebSockets

### 4.5 Receipts & printing

- PDF receipts with barcodes (ReportLab + barcode generation)
- **Windows local print agent** for silent USB / ESC-POS printing at the desk
- **Mobile print companion** (Android / iOS Bluetooth ESC/POS) — *SmartWagers Print*
- Print job queue with device register, health, and status (pending → printed / failed)
- Job types: wager, payout, remit
- Admin downloads for Windows agent ZIP and Android APK

### 4.6 Reporting & commission

- **Teller report** — personal fight totals, ledger, close station
- **Admin event report** — full event financials, reconciliation, surplus shares
- **Commission total** — plasada × pot by fight
- **Teller transactions** — cross-teller wager and ledger audit
- **Tellers board** — balances, alerts, closeouts, online status

### 4.7 Users, security & licensing

- In-app **user management**: create staff into admin / teller / display groups, reset password, delete, session invalidation
- Role-based login landing (prevents privilege hopping via redirect tricks)
- Access denied for wrong-role pages
- Login / logout **session audit**
- Optional **master lock** monthly licensing (enable / extend / disable) for commercial deployments
- Health endpoint and rotating application logs for operations

### 4.8 Configurable arena rules

From admin settings:

- Plasada percentage  
- Admin and teller initial funds  
- Teller max / min balance warnings  
- Bet-approval limit  
- Trailing 3 / 6 discard toggle  
- License status panel  

---

## 5. Typical event-day workflow

```
Start Event
    → Issue teller floats
    → Open fights (control Meron / Wala sides)
    → Tellers take bets & pay winners (receipts print)
    → Remits, collects, and balance alerts as needed
    → Close stations & count cash
    → End Event
    → Event Report + archived ledgers
```

One system. One cash story. One report at the end of the night.

---

## 6. Technology & deployment (buyer highlights)

| Area | What you get |
|------|----------------|
| **Platform** | Django 5.1, ASGI (Daphne), Django Channels |
| **Real-time** | Redis / Memurai channel layer for live boards and desks |
| **Database** | PostgreSQL in production; SQLite for local/dev |
| **Locale** | Asia/Manila timezone; peso (₱) cash UX |
| **Printing** | Offline-capable Windows agent; Bluetooth mobile companion |
| **Deploy kit** | Windows service (NSSM), firewall notes, Postgres backup/restore, release sync |
| **Licensing** | Optional offline monthly master lock for commercial installs |
| **Hosting model** | On-premise / LAN — arena stays in control of its data |

Built for concurrent cashier stations on a local network, not for consumer app-store gambling.

---

## 7. Role map (at a glance)

| Group | Home | Primary capabilities |
|-------|------|----------------------|
| **admin** | Administrator console | Fight control, betting, funds, tellers, users, settings, reports, print agents, wager approval |
| **teller** | Teller station | Bets, payout/cancel, remittance, personal report, station closeout |
| **display** | Live board | Read-only pots and payouts |

---

## 8. Value proposition

1. **Speed** — Live pots and status across admin, teller, and display without radio lag  
2. **Control** — Side open/close, teller online/offline, bet limits, and approval gates  
3. **Accountability** — Barcodes, sequenced IDs, ledgers, closeouts, and event archives  
4. **Cash clarity** — Floats, remits, bank transactions, and variance at station and event level  
5. **Commission visibility** — Plasada tracked per fight and rolled into event reporting  
6. **Print resilience** — Desk printers keep working with local and mobile agents  
7. **Commercial readiness** — Role security, logging, health checks, and optional license lock  

---

## 9. What’s included in a typical engagement

- SmartWagers server application (GameFowl / Django)  
- Administrator, teller, and display interfaces  
- Windows print agent package  
- Mobile print companion (as deployed)  
- Production deploy guidance for Windows + PostgreSQL + Redis/Memurai  
- Configuration of plasada, funds, thresholds, and user roles  
- Optional master-lock licensing setup  

*(Pricing, training hours, and SLA terms to be agreed per site.)*

---

## 10. Next steps

1. **Demo** — Walk through a full mock event (start → bets → payout → closeout → report)  
2. **Site survey** — Stations, printers, LAN, and display screens  
3. **Pilot day** — Soft live on a scheduled event with training  
4. **Go-live** — Production cutover, backups, and license activation if required  

---

## Contact / proposal close

**SmartWagers** turns the sabong desk into a controlled, auditable, real-time operation—from the first fight of the event to the final cash count.

We would welcome the opportunity to demonstrate the system on your network and tailor settings to your arena’s rules.

---

*Product: SmartWagers · Platform: GameFowl (Django) · Document: Sales Proposal*
