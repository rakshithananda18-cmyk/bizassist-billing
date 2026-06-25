# BizAssist Hosting Mode Master Plan
> **Version**: 1.0 | **Status**: Planning | **Scope**: Full Product Lifecycle

---

## 1. Vision

BizAssist must work for three kinds of merchants:

| Merchant Type | Need | Mode |
|---|---|---|
| Small shop, no internet, privacy-first | Fully offline, data never leaves PC | **Local** |
| Multi-branch, mobile access, team use | Cloud DB, real-time sync everywhere | **Cloud** |
| Mixed: works offline, syncs when online | Local primary, cloud backup | **Hybrid** |

The mode selector is **not just a UI toggle** — it is the **data residency and sync policy** of the entire app.

---

## 2. Mode Definitions (Precise)

### 🖥️ Local Mode
```
Merchant PC
├── Frontend (React — Electron or localhost browser)
├── Backend  (FastAPI on localhost:8000)
└── Database (SQLite file: bizassist.db on disk)

No internet required. Data never leaves the device.
Real-time sync: OFF (no SSE, no cloud calls)
```

**What works:**
- Full billing, invoicing, inventory, reports
- PDF generation
- AI assistant (if local LLM or API key set)
- All data operations

**What doesn't work:**
- Access from phone/browser remotely
- Multi-device or multi-user access
- Cloud backup
- Real-time sync indicator

---

### ☁️ Cloud Mode
```
Browser / Mobile (any device)
        │  HTTPS
        ▼
Cloud Backend (Hugging Face / VPS / Railway)
        │  SQLAlchemy
        ▼
Cloud DB (Supabase PostgreSQL / Managed PG)
        │
        └── SSE endpoint → real-time push to all connected clients
```

**What works:**
- Access from anywhere (phone, browser, team)
- Real-time sync between all devices
- Cloud backup (automatic via Supabase)
- Multi-user with roles

**What doesn't work:**
- Offline operation (no internet = no app)
- Data privacy for offline-sensitive merchants

---

### 🔀 Hybrid Mode
```
Merchant PC
├── Frontend (Electron or localhost)
├── Local Backend (FastAPI localhost:8000)
├── Local DB (SQLite — primary write target)
│         │
│         │  Sync Engine (background thread)
│         │  ├── On save: queue change to sync buffer
│         │  ├── When online: push deltas to cloud
│         │  └── On startup: pull missed cloud changes
│         ▼
Cloud Backend (HF Space / VPS)
        │
        ▼
Cloud DB (Supabase PostgreSQL — mirror/backup)
```

**What works:**
- Full offline operation (local SQLite primary)
- When online: auto-sync to cloud
- Access from phone/browser via cloud endpoint
- Conflict resolution on reconnect

**What doesn't work:**
- Real-time sync when offline (queued, deferred)
- Conflict resolution is complex (last-write-wins or manual merge)

---

## 3. Data Architecture Per Mode

### SQLite (Local/Hybrid local side)
```
bizassist.db
├── users
├── businesses
├── invoices
├── invoice_items
├── parties
├── products
├── settings
├── sync_queue          ← NEW: pending changes to push to cloud
└── sync_log            ← NEW: audit of what was synced and when
```

### PostgreSQL (Cloud/Hybrid cloud side)
```
supabase: bizassist schema
├── (same tables as SQLite)
├── sync_vector         ← NEW: vector clock / last_synced_at per record
└── change_log          ← NEW: append-only change history for conflict resolution
```

### Sync Queue Table (for Hybrid)
```sql
CREATE TABLE sync_queue (
    id          INTEGER PRIMARY KEY,
    entity      TEXT,        -- 'invoice', 'party', 'product', etc.
    entity_id   INTEGER,
    operation   TEXT,        -- 'INSERT', 'UPDATE', 'DELETE'
    payload     TEXT,        -- JSON of the changed record
    created_at  DATETIME,
    synced_at   DATETIME,    -- NULL if not yet pushed
    error       TEXT         -- error message if push failed
);
```

---

## 4. Mode Switching — The Critical Part

> **Switching mode is not just toggling a setting. It is a data migration event.**

---

### 4.0 Pre-Flight Checks & Readiness System

> **Grey-out is NOT based on where you're hosted.**
> It is based on **what actually connects right now** — live probe results only.

The only source of truth is: **can this endpoint be reached from this browser, right now?**

---

#### 4.0.1 The 3 Probes (The Real Checks)

On Settings page load, and every 30 seconds after, run these 3 probes **in parallel**:

| # | Probe | What it checks | Timeout |
|---|---|---|---|
| P1 | `GET http://localhost:8000/health` | Is a local BizAssist backend running on this machine? | 500ms |
| P2 | `GET {CLOUD_URL}/health` | Is the cloud backend reachable from this browser? | 2000ms |
| P3 | `navigator.onLine` + `HEAD https://1.1.1.1` | Is there a working internet connection at all? | 1000ms |

Each probe produces exactly one of **4 results**:

| Result | Meaning |
|---|---|
| `PASS (Xms)` | Got a valid `{ status: "ok" }` response in time |
| `FAIL:TIMEOUT` | No response within the timeout window |
| `FAIL:CORS` | Browser blocked the request (security boundary — not retryable) |
| `FAIL:ERROR` | Got a response but it was an error (5xx, bad JSON, etc.) |

> **`FAIL:CORS` is special.** It means a web browser is trying to reach `localhost` from a cloud-hosted page. This is a browser security rule — no amount of retrying or reconfiguring will fix it without the Desktop App. It must be shown as a permanent block, not a retryable error.

---

#### 4.0.2 Grey-Out Decision Engine

**The mode cards get their state from probe results — nothing else.**

```
Probe Results → Mode Card State

P1 (local)    P2 (cloud)    P3 (internet)   │  Local    Cloud    Hybrid
─────────────────────────────────────────────┼──────────────────────────
PASS          PASS          PASS             │  ✅ Ready  ✅ Ready  ✅ Ready
FAIL:CORS     PASS          PASS             │  🔒 Locked ✅ Ready  🔒 Locked
FAIL:TIMEOUT  PASS          PASS             │  ⚠️ Retry  ✅ Ready  ⚠️ Retry
PASS          FAIL:TIMEOUT  PASS             │  ✅ Ready  ⚠️ Retry  ⚠️ Retry
PASS          PASS          FAIL:TIMEOUT     │  ✅ Ready  ⚠️ Retry  ⚠️ Retry
FAIL:CORS     FAIL:TIMEOUT  FAIL:TIMEOUT     │  🔒 Locked ⚠️ Retry  🔒 Locked
FAIL:TIMEOUT  FAIL:TIMEOUT  FAIL:TIMEOUT     │  ⚠️ Retry  ⚠️ Retry  ⚠️ Retry
(checking)    (checking)    (checking)       │  🔄 ...    🔄 ...    🔄 ...
```

- `✅ Ready` → card is fully clickable, shows green "Ready" badge
- `🔒 Locked` → card is grey, `pointer-events: none`, shows "Desktop App Required" — **no retry button**
- `⚠️ Retry` → card is grey-red, `pointer-events: none`, shows exact failure reason + **[Retry Check]** button
- `🔄 ...` → card shows pulsing shimmer, disabled until probes finish (max ~2s)

---

#### 4.0.3 Why CORS Is a Permanent Block (Not Retryable)

When the browser tries `GET http://localhost:8000/health` from `https://bizassist.vercel.app`:

1. Browser sees: cloud page (HTTPS) → local request (HTTP) = **mixed content** → blocked
2. Even if HTTP is allowed: cross-origin to `localhost` without proper CORS headers → blocked
3. The backend can't even receive the request to send CORS headers — it's blocked before leaving the browser

**This is not a network problem. It is not a configuration problem. It cannot be retried.**

The only fix: run the frontend on `localhost` too (dev mode) or install the Desktop App.

---

#### 4.0.4 Live Readiness Panel (Always Visible)

Above the mode cards in Settings, always show this panel — updating live:

```
┌──────────────────────────────────────────────────────┐
│  Connection Readiness                      [↻ Recheck]│
├──────────────────────────────────────────────────────┤
│  🌐  Internet           🟢  Connected                │
│  🖥️  Local Backend      🔴  Unreachable              │
│                         ↳ CORS block — browser limit │
│  ☁️  Cloud Backend      🟢  Online  (312ms)          │
└──────────────────────────────────────────────────────┘
```

**Dot states and their exact meaning shown to the user:**

| Dot | Label shown | Sub-label shown |
|---|---|---|
| 🟡 pulsing | Checking… | (blank) |
| 🟢 solid | Online (Xms) | (blank) |
| 🟠 solid | Slow (Xms) | "May affect performance" |
| 🔴 solid | Unreachable | One of: "Timed out" / "CORS block — browser limit" / "Server error" |
| ⚫ solid | N/A | "Not needed for current mode" |

---

#### 4.0.5 Grey-Out Visual Anatomy (3 Distinct States)

**State 1 — 🔒 Locked (CORS / permanent browser block)**
```
┌──────────────────────────────────────────────┐
│  🖥️ Local Mode                    🔒 LOCKED  │
│  ─────────────────────────────────────────── │
│  opacity: 0.30                               │
│  filter: grayscale(100%)                     │
│  pointer-events: none                        │
│  border: 1px dashed var(--border-muted)      │  ← neutral grey dash, not red
│                                              │
│  Reason shown inside card:                   │
│  "Requires Desktop App                       │
│   (browser cannot reach localhost)"          │
│                                              │
│  Link always visible at bottom of card:      │
│  ↓  Download Desktop App                     │
│                                              │
│  NO retry button (it will never help)        │
└──────────────────────────────────────────────┘
```

**State 2 — ⚠️ Unavailable (probe failed, but retryable)**
```
┌──────────────────────────────────────────────┐
│  🖥️ Local Mode               ⚠️ UNAVAILABLE  │
│  ─────────────────────────────────────────── │
│  opacity: 0.50                               │
│  filter: grayscale(40%)                      │
│  pointer-events: none                        │
│  border: 1px dashed var(--danger)            │  ← red dash
│                                              │
│  Reason shown inside card:                   │
│  "localhost:8000 not responding              │
│   (timed out after 500ms)"                   │
│                                              │
│  Button below card:  [↻ Retry Check]         │
└──────────────────────────────────────────────┘
```

**State 3 — ✅ Ready (probe passed)**
```
┌──────────────────────────────────────────────┐
│  ☁️ Cloud Mode                   ✅ READY    │
│  ─────────────────────────────────────────── │
│  opacity: 1.0                                │
│  pointer-events: auto                        │
│  border: 1px solid var(--accent)             │
│  cursor: pointer                             │
│  hover: box-shadow glow, scale(1.01)         │
│                                              │
│  Response time shown: "312ms"               │
└──────────────────────────────────────────────┘
```

**State 4 — ● ACTIVE (currently running mode)**
```
┌──────────────────────────────────────────────┐
│  ☁️ Cloud Mode              ● ACTIVE         │  ← pulsing green dot
│  ─────────────────────────────────────────── │
│  border: 2px solid var(--success)            │
│  background: var(--success-tint)             │
│  Cannot be clicked (already selected)        │
└──────────────────────────────────────────────┘
```

---

#### 4.0.6 Informational Context Banner

A **non-dismissible banner** always shows above the mode cards — derived from probe results, not from URL:

| Probe P1 Result | Probe P2 Result | Banner shown |
|---|---|---|
| `FAIL:CORS` | `PASS` | `🌐 Running in web browser. Local & Hybrid require the Desktop App — browser cannot reach localhost.` |
| `FAIL:TIMEOUT` | `PASS` | `⚠️ Local backend not found. Start it on port 8000 to enable Local / Hybrid mode.` |
| `PASS` | `PASS` | `✅ All systems reachable. Choose any mode.` |
| `PASS` | `FAIL:TIMEOUT` | `⚠️ Cloud backend unreachable. Cloud / Hybrid mode unavailable until it responds.` |
| any | any (P3=FAIL) | `📵 No internet connection. Cloud and Hybrid modes unavailable.` |

---

#### 4.0.7 Probe Failure UIs (On Click of a Greyed Card — Should Not Happen)

If somehow a user reaches a click on a grey card (e.g. focus + enter key), show:

**Probe returned CORS (permanent)**
```
╔══════════════════════════════════════════════════╗
║  🔒  Cannot Reach Local Backend                  ║
╠══════════════════════════════════════════════════╣
║  Your browser blocked the connection to          ║
║  http://localhost:8000                           ║
║                                                  ║
║  This is a browser security rule — web pages     ║
║  cannot connect to software on your local        ║
║  machine. Retrying will not help.                ║
║                                                  ║
║  To use Local or Hybrid mode:                    ║
║  → Download the BizAssist Desktop App            ║
║    (it bundles the backend inside the app)       ║
║                                                  ║
║  [ ↓ Download ]              [ Stay on Cloud ]   ║
╚══════════════════════════════════════════════════╝
```

**Probe returned TIMEOUT (retryable)**
```
╔══════════════════════════════════════════════════╗
║  ⚠️  Local Backend Not Responding                ║
╠══════════════════════════════════════════════════╣
║  Probe:  GET http://localhost:8000/health        ║
║  Result: Timed out after 500ms                   ║
║                                                  ║
║  The backend is not running. To start it:        ║
║  ① cd backend/                                  ║
║  ② uvicorn main:app --reload --port 8000         ║
║  ③ Click Retry below                            ║
║                                                  ║
║  [ ↻ Retry Check ]              [ Cancel ]       ║
╚══════════════════════════════════════════════════╝
```

---

#### 4.0.1 Environment Detection (On Page Load, Once)

When the Settings page loads, the app immediately detects its environment — **before the user touches anything**:

| Signal | Detection Method | Meaning |
|---|---|---|
| Cloud-hosted URL | `hostname` is not `localhost` / `127.0.0.1` | Running in browser via Vercel/HF |
| Localhost | `hostname === 'localhost'` or `127.0.0.1` | Dev mode or local server |
| Electron | `navigator.userAgent` contains `'Electron'` | Desktop app |
| Internet | `navigator.onLine` (live, event-driven) | Network availability |

**Mode availability matrix — computed on load, locked in:**

| Environment | 🖥️ Local | ☁️ Cloud | 🔀 Hybrid |
|---|---|---|---|
| Web browser (Vercel/HF URL) | ❌ Permanently blocked | ✅ | ❌ Permanently blocked |
| localhost browser | ✅ (if backend up) | ✅ (if cloud up) | ✅ (if both up) |
| Electron desktop app | ✅ (if backend up) | ✅ (if cloud up) | ✅ (if both up) |

> A web browser **physically cannot** reach `localhost:8000` on a merchant's machine. This is not a setting — it is a browser security boundary. No retry will ever fix it.

---

#### 4.0.2 Always-On Live Readiness Panel

The mode selector section in Settings must show a **live readiness panel** — always visible, always up-to-date, auto-refreshing every 30 seconds:

```
┌─────────────────────────────────────────────────────┐
│  System Readiness                          [↻ Recheck]
├─────────────────────────────────────────────────────┤
│  🌐  Internet           ●  Connected                │
│  🖥️  Local Backend      ●  Online   (12ms)          │
│  ☁️  Cloud Backend      ●  Online   (340ms)         │
│  📦  App Context        ●  Electron Desktop         │
└─────────────────────────────────────────────────────┘
```

Each row can be in one of **5 states**:

| State | Dot Color | Label | Meaning |
|---|---|---|---|
| `checking` | 🟡 pulsing | Checking… | Probe in flight |
| `online` | 🟢 solid | Online (Xms) | Responded within timeout |
| `slow` | 🟠 solid | Slow (Xms) | Responded but >1000ms |
| `offline` | 🔴 solid | Offline | No response / timed out |
| `n/a` | ⚫ solid | N/A | Not applicable for this environment |

---

#### 4.0.3 Exact Probe Specifications

| Probe | Endpoint | Timeout | Retry | Interval |
|---|---|---|---|---|
| Local backend | `GET http://localhost:8000/health` | **500ms** | 1x on fail | Every 30s |
| Cloud backend | `GET {CLOUD_URL}/health` | **2000ms** | 1x on fail | Every 30s |
| Internet | `navigator.onLine` + optional `HEAD https://1.1.1.1` | **1000ms** | — | Event-driven (`online`/`offline`) |

`/health` must return `{ "status": "ok", "db": "connected", "mode": "cloud|local" }`.
Response time is measured and displayed (e.g. `12ms`, `340ms`).

---

#### 4.0.4 Grey-Out Anatomy (Precise Visual Spec)

**When a mode card is blocked (environment reason — permanent):**
```
┌──────────────────────────────────────┐
│  🖥️  Local Mode              LOCKED  │  ← badge: "Web Only — Not Available"
│                                      │
│  CSS: opacity: 0.35                  │
│       pointer-events: none           │
│       cursor: not-allowed            │
│       filter: grayscale(100%)        │
│       border: 1px dashed #555        │
│                                      │
│  Hover tooltip (title attr):         │
│  "Local mode requires the Desktop    │
│   App. You are in a web browser."    │
│                                      │
│  Bottom link (always visible):       │
│  ↓ Download Desktop App              │
└──────────────────────────────────────┘
```

**When a mode card is blocked (probe failure — temporary, retryable):**
```
┌──────────────────────────────────────┐
│  🖥️  Local Mode           UNAVAILABLE│  ← badge: "Backend Offline"
│                                      │
│  CSS: opacity: 0.55                  │
│       pointer-events: none           │
│       cursor: not-allowed            │
│       border: 1px dashed #e55        │  ← red dashed (vs grey dashed above)
│                                      │
│  Inline message (below card):        │
│  "⚠ localhost:8000 not responding.   │
│   Start your backend to enable."     │
│                                      │
│  Action: [Retry Check]               │
└──────────────────────────────────────┘
```

**When a mode card is fully available:**
```
┌──────────────────────────────────────┐
│  ☁️  Cloud Mode                      │
│                                      │
│  CSS: opacity: 1.0                   │
│       cursor: pointer                │
│       border: 1px solid accent       │
│       hover: scale(1.02), glow       │
│                                      │
│  Inline badge: "✅ Ready"            │
└──────────────────────────────────────┘
```

**Currently active mode:**
```
┌──────────────────────────────────────┐
│  ☁️  Cloud Mode          ● ACTIVE    │  ← pulsing green dot
│                                      │
│  CSS: border: 2px solid green        │
│       background: green tint         │
└──────────────────────────────────────┘
```

---

#### 4.0.5 Pre-Flight Check Sequence (When User Clicks a Mode Card)

```
User clicks an available mode card
        │
        ▼
[1] Instantly show inline spinner on card: "Verifying…"
        │
        ▼
[2] Run targeted probes for the selected mode (parallel):
    ├── Local needed?  → GET localhost:8000/health  (500ms timeout)
    ├── Cloud needed?  → GET {CLOUD_URL}/health     (2000ms timeout)
    └── Both probes fire simultaneously, wait for slowest
        │
        ▼
[3] Evaluate results:
    ├── ALL pass   → remove spinner → show Consequence Alert Modal (Section 4.2)
    ├── SOME fail  → remove spinner → show specific Blocked UI (Section 4.0.6)
    └── TIMEOUT    → remove spinner → show Timeout UI with Retry
        │
[4] After blocking UI shown:
    ├── User clicks [Retry Check] → go back to step [2]
    └── User clicks [Cancel]      → reset card to previous selection
```

---

#### 4.0.6 Blocked Switch UIs (Precise Copy)

**🚫 Web browser → Local or Hybrid (permanent block)**
```
╔══════════════════════════════════════════════════════╗
║  🚫  Local Mode Requires the Desktop App             ║
╠══════════════════════════════════════════════════════╣
║  You are using BizAssist in a web browser.           ║
║                                                      ║
║  Web browsers cannot connect to software running    ║
║  on your local machine — this is a browser          ║
║  security boundary, not a setting.                  ║
║                                                      ║
║  What each mode needs:                               ║
║  🖥️  Local  → Desktop App + local backend           ║
║  🔀  Hybrid → Desktop App + local + cloud           ║
║  ☁️  Cloud  → Just a browser (you already have it)  ║
║                                                      ║
║  [ ↓ Download Desktop App ]     [ Stay on Cloud ]   ║
╚══════════════════════════════════════════════════════╝
```

**⚠️ Localhost → Local (backend not running)**
```
╔══════════════════════════════════════════════════════╗
║  ⚠️  Local Backend Not Responding                    ║
╠══════════════════════════════════════════════════════╣
║  Probe: GET http://localhost:8000/health             ║
║  Result: ✗ Timed out after 500ms                     ║
║                                                      ║
║  The local backend server is not running.            ║
║                                                      ║
║  To fix this:                                        ║
║  ① Open a terminal in your project folder            ║
║  ② Run:  uvicorn main:app --reload --port 8000       ║
║  ③ Click [Retry Check] below                         ║
║                                                      ║
║  Or: use the Desktop App — it starts the             ║
║  backend automatically.                              ║
║                                                      ║
║  [ Retry Check ]                    [ Cancel ]       ║
╚══════════════════════════════════════════════════════╝
```

**⚠️ Cloud backend unreachable**
```
╔══════════════════════════════════════════════════════╗
║  ⚠️  Cloud Server Not Responding                     ║
╠══════════════════════════════════════════════════════╣
║  Probe: GET https://yourspace.hf.space/health        ║
║  Result: ✗ Timed out after 2000ms                    ║
║                                                      ║
║  Possible reasons:                                   ║
║  • No internet connection (check your network)       ║
║  • HF Space is waking up — wait 30 seconds           ║
║  • Server URL is outdated                            ║
║                                                      ║
║  Current configured URL:                             ║
║  https://yourspace.hf.space                          ║
║                                                      ║
║  [ Retry ]   [ Update Server URL ]   [ Cancel ]      ║
╚══════════════════════════════════════════════════════╝
```

**⚠️ Hybrid — one endpoint down (live status shown)**
```
╔══════════════════════════════════════════════════════╗
║  ⚠️  Hybrid Mode — Requirements Not Met              ║
╠══════════════════════════════════════════════════════╣
║  Both servers must be reachable for Hybrid mode.     ║
║                                                      ║
║  Check results:                                      ║
║  ✅  Local backend   localhost:8000    12ms          ║
║  ❌  Cloud backend   hf.space/…        Timeout       ║
║                                                      ║
║  Fix: Resolve the ❌ item above, then retry.         ║
║                                                      ║
║  [ Retry Both ]                     [ Cancel ]       ║
╚══════════════════════════════════════════════════════╝
```

---

#### 4.0.7 Informational Banner (Always Visible in Settings)

A **non-dismissible banner** always shows above the mode cards — derived from probe results, not from URL:

| Probe P1 Result | Probe P2 Result | Banner shown |
|---|---|---|
| `FAIL:CORS` | `PASS` | `🌐 Running in web browser. Local & Hybrid require the Desktop App — browser cannot reach localhost.` |
| `FAIL:TIMEOUT` | `PASS` | `⚠️ Local backend not found. Start it on port 8000 to enable Local / Hybrid mode.` |
| `PASS` | `PASS` | `✅ All systems reachable. Choose any mode.` |
| `PASS` | `FAIL:TIMEOUT` | `⚠️ Cloud backend unreachable. Cloud / Hybrid mode unavailable until it responds.` |
| any | any (P3=FAIL) | `📵 No internet connection. Cloud and Hybrid modes unavailable.` |

---

#### 4.0.8 Pre-Flight Check Modal (Full UI Design)

When the user clicks a mode card that is ✅ Ready, a **full-screen centred modal** opens immediately — showing exactly what is being verified before the consequences alert appears. This builds trust and transparency.

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│                  🔍  Verifying Requirements                 │
│              Checking if Cloud Mode is available…           │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   Step 1 of 3                                               │
│   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━   │
│                                                             │
│   🌐  Internet Connection                                   │
│       ┌──────────────────────────────────────────┐         │
│       │  🟡  Checking…                           │         │
│       └──────────────────────────────────────────┘         │
│                                                             │
│   ☁️  Cloud Backend  (https://yourspace.hf.space)          │
│       ┌──────────────────────────────────────────┐         │
│       │  🟡  Checking…                           │         │
│       └──────────────────────────────────────────┘         │
│                                                             │
│   🗄️  Cloud Database                                       │
│       ┌──────────────────────────────────────────┐         │
│       │  🟡  Checking…                           │         │
│       └──────────────────────────────────────────┘         │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                    [ Cancel ]                               │
└─────────────────────────────────────────────────────────────┘
```

**After checks complete — ALL PASS:**
```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│                  ✅  All Systems Ready                      │
│              Cloud Mode is available to switch              │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   🌐  Internet Connection                                   │
│       ┌──────────────────────────────────────────┐         │
│       │  🟢  Connected                           │         │
│       └──────────────────────────────────────────┘         │
│                                                             │
│   ☁️  Cloud Backend                                         │
│       ┌──────────────────────────────────────────┐         │
│       │  🟢  Online  ·  312ms  ·  DB connected   │         │
│       └──────────────────────────────────────────┘         │
│                                                             │
│   🗄️  Cloud Database                                       │
│       ┌──────────────────────────────────────────┐         │
│       │  🟢  PostgreSQL reachable                │         │
│       └──────────────────────────────────────────┘         │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│            [ Cancel ]        [ Continue → ]                 │
└─────────────────────────────────────────────────────────────┘
```

**After checks complete — ONE FAILS (TIMEOUT, retryable):**
```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│                  ⚠️  Check Failed                           │
│           Cannot switch mode — fix the issue below          │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   🌐  Internet Connection                                   │
│       ┌──────────────────────────────────────────┐         │
│       │  🟢  Connected                           │         │
│       └──────────────────────────────────────────┘         │
│                                                             │
│   ☁️  Cloud Backend                                         │
│       ┌──────────────────────────────────────────┐         │
│       │  🔴  Timed out after 2000ms              │         │
│       │                                          │         │
│       │  Possible reasons:                       │         │
│       │  • HF Space is still waking up           │         │
│       │  • Server URL may have changed           │         │
│       │  • Check https://yourspace.hf.space      │         │
│       └──────────────────────────────────────────┘         │
│                                                             │
│   🗄️  Cloud Database                                       │
│       ┌──────────────────────────────────────────┐         │
│       │  ⚫  Skipped (backend unreachable)       │         │
│       └──────────────────────────────────────────┘         │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│    [ Cancel ]   [ Update Server URL ]   [ ↻ Retry All ]    │
└─────────────────────────────────────────────────────────────┘
```

**After checks — CORS block (permanent):**
```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│                  🔒  Not Possible Here                      │
│         Local Mode cannot be used in a web browser          │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   🖥️  Local Backend  (http://localhost:8000)               │
│       ┌──────────────────────────────────────────┐         │
│       │  🔒  Blocked by browser security         │         │
│       │                                          │         │
│       │  Web browsers cannot connect to          │         │
│       │  software on your local machine.         │         │
│       │  This is not a network issue —           │         │
│       │  it is a permanent browser rule.         │         │
│       └──────────────────────────────────────────┘         │
│                                                             │
│   ┌─────────────────────────────────────────────────┐      │
│   │  💡  To use Local or Hybrid mode:               │      │
│   │      Download the BizAssist Desktop App.        │      │
│   │      It runs the backend inside the app         │      │
│   │      so no browser limit applies.               │      │
│   └─────────────────────────────────────────────────┘      │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│        [ ↓ Download Desktop App ]     [ Close ]            │
└─────────────────────────────────────────────────────────────┘
```

**Visual design of the modal:**
- Backdrop: dark overlay, `backdrop-filter: blur(4px)`
- Modal: rounded card, `border-radius: 16px`, max-width `480px`, centered
- Header: icon + title + subtitle, large and clear
- Each check row: labelled box with coloured status, sub-text explanation
- Animated entry: slides up + fades in over 200ms
- Cannot be dismissed by clicking backdrop during checking phase
- After result: backdrop click closes (except on CORS — must read the message)

---

#### 4.0.9 Migration / Switch Progress Modal (Full UI Design)

Once pre-flight passes and the user confirms the consequence alert, this modal takes over — full-screen, non-dismissible until complete or cancelled.

**Stage 1 — Preparing (before data moves)**
```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│              ⏳  Switching to Cloud Mode                    │
│         Please wait — do not close this window              │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  0%          │
│                                                             │
│   ✅  Step 1 of 6:  Creating local backup                  │
│       bizassist_backup_20240625.db saved                    │
│                                                             │
│   🔄  Step 2 of 6:  Counting records to migrate            │
│       Scanning tables…                                      │
│                                                             │
│   ○   Step 3 of 6:  Uploading data to cloud                │
│   ○   Step 4 of 6:  Verifying record counts                │
│   ○   Step 5 of 6:  Switching API endpoint                  │
│   ○   Step 6 of 6:  Final validation                        │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                    [ Cancel & Rollback ]                    │
└─────────────────────────────────────────────────────────────┘
```

**Stage 2 — Uploading (data in flight)**
```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│              ⬆️  Uploading Your Data                        │
│              Securely transferring to cloud…                │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  58%        │
│                                                             │
│   ✅  Step 1 of 6:  Backup created                         │
│   ✅  Step 2 of 6:  Counted 4,821 records                  │
│   🔄  Step 3 of 6:  Uploading data                         │
│       ┌───────────────────────────────────────────┐        │
│       │  ✅ businesses      12 / 12               │        │
│       │  ✅ users           8  / 8                │        │
│       │  ✅ parties         340 / 340             │        │
│       │  ✅ products        218 / 218             │        │
│       │  🔄 invoices        1,823 / 3,100  ████░  │        │
│       │  ○  invoice_items   —                     │        │
│       └───────────────────────────────────────────┘        │
│       2,401 of 4,821 records uploaded  ·  ~45 sec left      │
│                                                             │
│   ○   Step 4 of 6:  Verifying record counts                │
│   ○   Step 5 of 6:  Switching API endpoint                  │
│   ○   Step 6 of 6:  Final validation                        │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                    [ Cancel & Rollback ]                    │
└─────────────────────────────────────────────────────────────┘
```

**Stage 3 — Complete (success)**
```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│                  🎉  Switch Complete!                       │
│              You are now running in Cloud Mode              │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100%        │
│                                                             │
│   ✅  Step 1:  Backup created                              │
│       📁 bizassist_backup_20240625.db (saved locally)       │
│   ✅  Step 2:  4,821 records counted                       │
│   ✅  Step 3:  4,821 records uploaded                      │
│   ✅  Step 4:  Counts verified  (local = cloud ✓)          │
│   ✅  Step 5:  API switched to cloud endpoint              │
│   ✅  Step 6:  Cloud responded — all data accessible       │
│                                                             │
│   ┌─────────────────────────────────────────────────┐      │
│   │  📦  Your local backup is kept for 30 days.     │      │
│   │  If anything seems wrong, you can rollback      │      │
│   │  from Settings → Hosting → Rollback Backup.     │      │
│   └─────────────────────────────────────────────────┘      │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                    [ Done — Go to Dashboard ]               │
└─────────────────────────────────────────────────────────────┘
```

**Stage 4 — Error mid-migration (safe state)**
```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│                  ❌  Migration Failed                       │
│         Your data is safe — nothing was deleted             │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  41%        │
│                                                             │
│   ✅  Step 1:  Backup created                              │
│   ✅  Step 2:  4,821 records counted                       │
│   ❌  Step 3:  Upload failed at invoice batch 4            │
│       Error: Connection reset by server                     │
│       (2,001 of 4,821 records were uploaded)               │
│   ○   Step 4–6: Not reached                                │
│                                                             │
│   ┌─────────────────────────────────────────────────┐      │
│   │  ✅  Safe to retry — the partial cloud upload   │      │
│   │      will be automatically cleaned up.          │      │
│   │  ✅  Your local database is unchanged.          │      │
│   └─────────────────────────────────────────────────┘      │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│          [ Back to Settings ]       [ ↻ Retry ]            │
└─────────────────────────────────────────────────────────────┘
```

**Visual design of the migration modal:**
- Full-screen modal, `z-index: 9999`, cannot be dismissed by clicking outside
- Top: animated icon (spinning for in-progress, ✅/❌ on complete)
- Progress bar: smooth animated fill, percentage shown right-aligned
- Steps: sequential with icons — ✅ done, 🔄 current (spinning), ○ pending
- Sub-table for table-by-table upload: row per entity with mini progress bar
- ETA shown in plain language ("~45 sec left")
- Error state: clearly says data is safe, shows exactly where it stopped
- Rollback button always visible during migration — becomes "Retry" on failure

---



### 4.1 Transition Matrix

| From → To | Data Action | Alert Level | Reversible? |
|---|---|---|---|
| Local → Cloud | Export SQLite → Import to PostgreSQL | 🔴 CRITICAL | ✅ Yes (keep local backup) |
| Local → Hybrid | Export SQLite → Import to PostgreSQL + enable sync | 🔴 CRITICAL | ✅ Yes |
| Cloud → Local | Export PostgreSQL → Import to SQLite | 🟡 WARNING | ✅ Yes (keep cloud copy) |
| Cloud → Hybrid | Enable local SQLite mirror + pull cloud data | 🟡 WARNING | ✅ Yes |
| Hybrid → Cloud | Flush sync queue → disable local writes | 🟡 WARNING | ✅ Yes |
| Hybrid → Local | Disable cloud sync → local becomes sole source | 🔴 CRITICAL | ⚠️ Cloud data diverges |

---

### 4.2 Alert System (Before Mode Switch)

Every mode switch must show a **blocking modal** (not a toast) with:

#### Local → Cloud Alert
```
╔══════════════════════════════════════════════════════╗
║  ⚠️  Switching to Cloud Mode                         ║
╠══════════════════════════════════════════════════════╣
║  This will:                                          ║
║  • Upload all your local data to the cloud           ║
║  • Your data will be stored on remote servers        ║
║  • Internet required for all future access           ║
║                                                      ║
║  Before switching:                                   ║
║  ✓ A backup of your local database will be saved     ║
║  ✓ Migration progress will be shown                  ║
║  ✓ You can rollback within 7 days                    ║
║                                                      ║
║  Estimated time: ~2 min for 10,000 records           ║
║                                                      ║
║  [ Cancel ]          [ I Understand, Proceed ]       ║
╚══════════════════════════════════════════════════════╝
```

#### Cloud → Local Alert
```
╔══════════════════════════════════════════════════════╗
║  ⚠️  Switching to Local Mode                         ║
╠══════════════════════════════════════════════════════╣
║  This will:                                          ║
║  • Download all cloud data to this PC only           ║
║  • Other devices will lose access                    ║
║  • No internet = fully offline from now on           ║
║                                                      ║
║  ❗ Your cloud data will NOT be deleted               ║
║     but it will stop receiving updates               ║
║                                                      ║
║  [ Cancel ]          [ Download & Switch ]           ║
╚══════════════════════════════════════════════════════╝
```

#### Hybrid → Local Alert
```
╔══════════════════════════════════════════════════════╗
║  🔴  Warning: Disconnecting Cloud Sync               ║
╠══════════════════════════════════════════════════════╣
║  • All unsynced changes will be LOST                 ║
║  • Cloud copy will become stale                      ║
║  • Cannot access from other devices after this       ║
║                                                      ║
║  Pending sync queue: 47 items not yet pushed         ║
║                                                      ║
║  [ Cancel ]   [ Sync Now Then Switch ]   [ Force ]  ║
╚══════════════════════════════════════════════════════╝
```

---

### 4.3 Migration Flow (Local → Cloud)

```
Step 1: Pre-flight check
  ├── Verify cloud DB is reachable
  ├── Check cloud DB is empty or mergeable
  └── Estimate record count

Step 2: Create local backup
  ├── Copy bizassist.db → bizassist_backup_YYYYMMDD.db
  └── Log backup path in settings

Step 3: Export SQLite → JSON chunks
  ├── Read all tables in dependency order
  │   (businesses → users → parties → products → invoices → invoice_items)
  └── Chunk into 500-record batches

Step 4: Import to PostgreSQL via API
  ├── POST /api/migrate/import  (batch endpoint)
  ├── Show progress bar (records uploaded / total)
  ├── On error: retry 3x, then halt and report
  └── Verify checksums (record counts match)

Step 5: Switch active mode
  ├── Update settings.general.hosting_mode = 'cloud'
  ├── Update API_BASE_URL to point to cloud backend
  └── Restart SSE connection

Step 6: Validation
  ├── Fetch invoice count from cloud
  ├── Compare with local count
  └── Show success or mismatch warning
```

---

### 4.4 Migration Flow (Cloud → Local)

```
Step 1: Download all data from cloud
  ├── GET /api/migrate/export  (full dump as JSON)
  └── Stream to local file

Step 2: Initialize local SQLite
  ├── Create new bizassist.db if not exists
  └── Run Alembic migrations to set up schema

Step 3: Import JSON → SQLite
  ├── Insert in dependency order
  └── Preserve all IDs (don't re-sequence)

Step 4: Switch API_BASE_URL to localhost
Step 5: Stop SSE, disable cloud sync
Step 6: Show confirmation with record counts
```

---

## 5. Sync Engine (Hybrid Mode)

### 5.1 Architecture
```
Local Write → DB Trigger / ORM hook → sync_queue INSERT
                                             │
                              Background worker (every 30s when online)
                                             │
                                    Pull from sync_queue WHERE synced_at IS NULL
                                             │
                                    POST /api/sync/push  (cloud backend)
                                             │
                                    Mark synced_at = NOW()
```

### 5.2 Conflict Resolution Strategy
**Last-Write-Wins (simple, v1):**
- Every record has `updated_at` timestamp
- On conflict: whichever has the newer `updated_at` wins
- Log the losing version to `conflict_log` table

**Manual Merge (v2, future):**
- Show conflict UI: "This invoice was edited on 2 devices. Which version to keep?"
- Side-by-side diff view
- User picks winner or merges fields manually

### 5.3 Sync Status States
```
IDLE        → no pending items, fully synced
SYNCING     → actively pushing/pulling records
PENDING     → items queued but not sent (offline)
CONFLICT    → merge conflict detected, needs resolution
ERROR       → push/pull failed, showing last error
```

---

## 6. Frontend — What Changes

### 6.1 Settings Page (Mode Selector)
- Mode selector shows current mode with icon
- Clicking a different mode → triggers alert modal (Section 4.2)
- After confirmation → triggers migration wizard

### 6.2 API Base URL Management
```javascript
// Currently hardcoded / env var
const API_BASE = import.meta.env.VITE_API_URL

// Should become dynamic from settings
const API_BASE = settings.hosting.apiUrl
  ?? (settings.hosting.mode === 'local'
        ? 'http://localhost:8000'
        : import.meta.env.VITE_API_URL)
```

### 6.3 Sync Health Indicator (Already Built)
Extend to show Hybrid sync queue depth:
```
[🟢 Synced] → all pushed
[🟡 47 pending] → queue has items
[🔴 Error] → last push failed
[📴 Offline] → no connection
```

### 6.4 Migration Progress UI
- Full-screen progress overlay during migration
- Cannot be dismissed (to prevent partial migration)
- Shows: current table, records done / total, ETA
- Cancel button → rolls back and stays on current mode

---

## 7. Backend — What Changes

### 7.1 New API Endpoints Needed

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/migrate/export` | GET | Dump full DB as JSON for download |
| `/api/migrate/import` | POST | Receive JSON batch and insert to DB |
| `/api/migrate/status` | GET | Progress of ongoing migration |
| `/api/sync/push` | POST | Hybrid: receive local changes |
| `/api/sync/pull` | GET | Hybrid: get cloud changes since timestamp |
| `/api/sync/queue-depth` | GET | How many items pending in sync queue |

### 7.2 Database Abstraction Layer
```python
# Instead of directly using SQLite or PG in routes,
# all routes use a unified Repository that abstracts the backend

class InvoiceRepository:
    def get_all(self, db: Session) -> List[Invoice]: ...
    def create(self, db: Session, data: dict) -> Invoice: ...
    # On hybrid: also writes to sync_queue after every write
```

### 7.3 Sync Worker (Hybrid)
```python
# background_tasks/sync_worker.py
# Runs every 30 seconds when in hybrid mode
# Reads sync_queue WHERE synced_at IS NULL
# Pushes to cloud API
# Marks synced_at on success
```

---

## 8. Desktop Packaging (Phase 3)

For true Local mode (offline, zero browser dependency):

| Component | Tool |
|---|---|
| Frontend wrapper | **Electron** or **Tauri** |
| Backend bundling | **PyInstaller** (packages FastAPI + uvicorn) |
| Local DB | SQLite (bundled) |
| Auto-update | Electron's built-in updater |
| Installer | NSIS (Windows), DMG (Mac), AppImage (Linux) |

```
BizAssist.exe
├── /resources/app/      (React frontend)
├── /resources/backend/  (PyInstaller bundle)
│   ├── bizassist_server.exe
│   └── bizassist.db
└── electron.js          (launcher: starts backend, opens browser window)
```

---

## 9. Implementation Phases

> All 3 phases are committed deliverables, executed in order.

---

### Phase 1 — Mode Foundation & Data Migration
**Goal**: Mode switching actually moves data. Alerts inform the user. API URL is dynamic.

| Task | Description |
|---|---|
| ✅ Mode selector UI | Already in settings page |
| ✅ SSE health indicator | Already in sidebar |
| ✅ Dynamic API Base URL | Read `apiUrl` from settings instead of hardcoded env var |
| ✅ Mode-switch alert modals | Blocking modal per transition (6 variants) with full consequences |
| ✅ `GET /api/migrate/export` | Dump entire DB (all tables) as ordered JSON |
| ✅ `POST /api/migrate/import` | Accept JSON batches, insert to target DB |
| ✅ `GET /api/migrate/status` | SSE stream of migration progress (%) |
| ✅ Migration progress UI | Full-screen overlay, non-dismissible, with cancel + rollback |
| ✅ Post-migration validation | Compare record counts source vs destination |
| ✅ Auto local backup | Before any migration, snapshot `bizassist.db` with timestamp |
| ✅ Rollback button | In Settings → restore last backup |

---

### Phase 2 — Hybrid Sync Engine
**Goal**: Local SQLite and cloud PostgreSQL stay in sync automatically.

| Task | Description |
|---|---|
| ✅ `sync_queue` table | New table in SQLite: captures every local write |
| ✅ `sync_log` table | Audit trail of every sync operation |
| ✅ ORM write hooks | After every INSERT/UPDATE/DELETE → push to sync_queue |
| ✅ Background sync worker | Python thread: every 30s, flush sync_queue to cloud |
| ✅ `POST /api/sync/push` | Cloud endpoint: receive local changes, apply to PostgreSQL |
| ✅ `GET /api/sync/pull` | Cloud endpoint: return changes since `last_sync_at` |
| ✅ Conflict detection | Compare `updated_at` timestamps on conflict |
| ✅ Last-write-wins (v1) | Newer `updated_at` always wins, loser goes to `conflict_log` |
| 🔲 Manual merge UI (v2) | Side-by-side diff, user picks winner per field |
| ✅ Sync health indicator | Extend sidebar indicator: queue depth, last sync time, conflict count |
| ✅ Offline queue persistence | Sync queue survives app restart; resumes on reconnect |

---

### Phase 3 — Desktop App (Electron + Bundled Backend)
**Goal**: True offline-first installed app. Works with zero browser. Full Local mode.

| Task | Description |
|---|---|
| 🔲 Electron shell | Wrap React frontend in Electron window |
| 🔲 PyInstaller bundle | Package FastAPI + uvicorn as `bizassist_server.exe` |
| 🔲 Electron main process | On launch: start backend exe, open browser window to localhost |
| 🔲 Graceful shutdown | On Electron close: terminate backend process cleanly |
| 🔲 SQLite bundled | Include `bizassist.db` in app resources |
| 🔲 Offline AI (Ollama) | Local LLM for AI assistant, no API key needed |
| 🔲 Auto-updater | Electron's built-in update mechanism (GitHub releases) |
| 🔲 Windows installer | NSIS `.exe` installer |
| 🔲 Mac installer | `.dmg` package |
| 🔲 Linux installer | `.AppImage` package |
| 🔲 Desktop mode detection | App auto-detects it's running in Electron, locks to Local/Hybrid only |

---

## 10. Data Safety Guarantees

> **No migration should ever result in data loss.**

| Rule | How Enforced |
|---|---|
| Always backup before migration | Auto-backup step before any mode switch |
| Migration is atomic | DB transaction: all-or-nothing |
| Verify after migration | Record count comparison (source vs destination) |
| Rollback available | Keep backup for 30 days, rollback button in settings |
| User must confirm | Blocking modal with typed confirmation for destructive actions |
| Show consequences | Every alert lists exactly what will change |

---

## 11. Open Questions & Decided Architecture

1. **Conflict resolution in Hybrid**: **Last-Write-Wins (LWW) Decided for v1**. Discarded items (local timestamp older than cloud) are logged silently to the `conflict_logs` table for tracking and resolution.
2. **Who owns cloud DB schema?**: Supabase hosted or self-hosted PostgreSQL? (Currently runs Supabase PostgreSQL).
3. **Sync interval**: **Adjustable in Advanced Settings**. Options: 10s, 30s, 60s, 5m.
4. **Multi-user conflict in Hybrid**: Resolved via LWW on PostgreSQL `updated_at` column.
5. **Electron vs Tauri**: Electron is heavier but more mature; Tauri is lighter (Rust-based).
6. **Offline AI**: Should local mode support AI features via Ollama?
7. **Data retention on Cloud → Local switch**: How long should cloud data stay active after switching?

---

*This master plan should be revisited and updated as each phase is completed.*

