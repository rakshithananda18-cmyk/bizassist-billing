# BizAssist — Windows App Testing, Fixes & Recommendations

_Date: 2026-07-04 · Scope: continuation of "Windows app testing and fixes"_

This covers (a) recovery of files left half-written when the previous session
hit its usage limit, (b) the seven-item task list, (c) root-cause analysis of
the field issues you reported, and (d) recommendations to make the product
stand out. Nothing here could be run against the live Windows app from this
environment — the `node_modules`/Python deps are Windows-native — so items are
marked **[verify on Windows]** where a rebuild + manual test is required.

---

## 1. Recovery — files were truncated mid-write

The prior session was cut off (Fable-5 limit) **while writing files**, leaving
9 files truncated on disk (syntax errors / dangling JSX). All were repaired and
re-validated (Python `compileall`, JS/JSX `esbuild` parse):

| File | Was broken at | Fixed |
|---|---|---|
| backend/routes/telemetry.py | unterminated string + dropped line | ✅ |
| backend/services/admin_service.py | unclosed `reset_chroma_docs()` | ✅ |
| backend/services/scheduler.py | unclosed `add_job(` | ✅ |
| backend/services/sync_worker.py | dangling `if` in pull loop | ✅ |
| frontend-billing/src/utils/loginSync.js | mid-`fetch` | ✅ |
| frontend-billing/.../HostingOnboardingModal.jsx | mid-JSX footer | ✅ |
| frontend-billing/src/contexts/AuthContext.jsx | mid-`return` | ✅ |
| frontend-billing/src/pages/Register.jsx | mid feature-list JSX | ✅ |
| frontend-billing/src/pages/Settings.jsx | mid remove-cashier modal | ✅ |

---

## 2. Seven-item task list — status

| # | Item | Status |
|---|---|---|
| 1 | Cloud onboarding silent failure (token rejected) | ✅ Root-caused + fixed (see §3) |
| 2 | App registration vs web (category dropdown) | ✅ Fixed (see §4) — **[verify on Windows: rebuild]** |
| 3 | Per-user / bizid telemetry in admin | ✅ Backend + admin UI now wired (see §5) |
| 4 | Telemetry persistence pipeline | ✅ Complete + verified (see §6) |
| 5 | Admin user/business data visibility | ✅ Present + extended (see §5, §7) |
| 6 | Verify changes + recommendations | ✅ This document |
| 7 | Move hosting choice into registration | ✅ Implemented (see §8) — **[verify on Windows]** |

---

## 3. Silent cloud-switch failure — root cause & fix

**What you saw:** registered `varshini` on cloud → logged into the desktop app
→ onboarding asked local/cloud → chose **Cloud** → nothing happened, no error.

**Root cause (code):** the onboarding modal deep-links to
`/settings?tab=advanced&switch=cloud`, which opens the guarded switch flow.
That flow gates each mode on readiness probes (`localProbe`, `cloudProbe`,
`internetProbe`). In `Settings.jsx → HostingModeSection`:

- `handleCardClick()` did `if (state === 'locked' || 'unavailable') return` —
  a **silent no-op** with zero feedback.
- The deep-link `useEffect` opened the preflight **without** checking the probe,
  so an unreachable cloud produced a dead/empty preflight.

In the packaged app the cloud probe commonly reports `cors` or `offline`
because the HF Space either isn't reachable or its CORS allow-list doesn't
include the app's origin — so Cloud was `locked`/`unavailable` and the click
was swallowed.

**Fix applied (`Settings.jsx`):** added `explainBlocked()` — every blocked path
now raises a specific toast ("Cloud mode is blocked: the cloud server rejected
this app's request (CORS)…" / "…cloud is offline/unreachable. Press Re-check…").
The deep-link only opens the preflight when the target is actually `ready`;
otherwise it explains why.

**[verify on Windows] — the real backend issue to confirm:**
1. Confirm the HF Space CORS `allow_origins` includes the desktop app origin
   (Electron/Tauri origin, e.g. `app://.` / `http://localhost:<port>` / `file://`).
   If not, cloud/hybrid can never work from the app — the toast will now say so.
2. Confirm `varshini` exists in the **cloud** DB and the login after switch
   succeeds against `CLOUD_URL`. `switchMode()` logs out by design (local & cloud
   assign different integer PKs to the same user; the JWT must be reissued).

---

## 4. Category dropdown — app vs web

**Root cause:** `/business/templates` (served by `core/api/business.py`) reads the
JSON configs in `backend/core/templates/configs/*.json`. The **packaged**
desktop backend didn't bundle those files, so the app got an empty list while
the web (which has the source tree) got all 10.

**Fixes:**
- `bizassist-backend.spec` now bundles `core/templates/configs` into the build
  (already committed). **A rebuild of the Windows backend is required for this
  to take effect. [verify on Windows]**
- `Register.jsx` fallback list expanded from 1 → all 10 categories, so even an
  un-rebuilt app shows the full dropdown (fetch order stays: local backend →
  cloud → built-in).

---

## 5. Per-bizid telemetry & admin visibility

Field debugging is now keyed on **bizid** (the business `public_id`, stable
across cloud & local DBs).

**Backend (already present):** `/admin/telemetry?bizid=&device=&event=&level=`
(DB-first, JSONL fallback), plus `/admin/telemetry/{businesses,devices,stats,archive}`.
Ingestion stamps `bizid` and mirrors per-business JSONL.

**Admin UI (`AdminTelemetry.jsx`) — added this session:**
- **Storage-health banner:** rows, size vs 200 MB cap (progress bar),
  retention window, oldest→newest, and an **over-cap** warning.
- **bizid filter** on Events + a clickable **Business** column (jump to that
  business's events).
- **Businesses tab:** per-bizid rollup (event count, last write) → "View events".
- **Devices tab:** now shows each device's bizid(s) and flags shared devices.
- **Archive controls:** "Download (.gz)" and "Archive & purge" (gzip the whole
  table to your machine, then delete archived rows — new rows survive).

**Why HF logs looked incomplete:** the HF Space container filesystem is wiped on
every restart, so JSONL under `logs/` is ephemeral and the console only shows
the current process. The durable source of truth is the **`telemetry_events`
table** (Supabase); the admin viewer is DB-first, which is what makes logs
survive restarts. **[verify on Windows/cloud]** confirm the migration
`a9c4e7f1d2b8_add_telemetry_events` has been applied on Supabase.

---

## 6. Telemetry persistence pipeline — verified

Matches your intended design end-to-end:

1. **Ingest** (`routes/telemetry.py`): `/api/telemetry/log` + `/api/telemetry/import`
   write to JSONL **and** persist to the `telemetry_events` table (`_persist_records_to_db`).
2. **Relay** (`services/telemetry_relay.py`, scheduler every 3 h): local installs
   ship new JSONL rows to the cloud `/api/telemetry/import` → Supabase.
3. **Weekly maintenance** (`services/telemetry_maintenance.py`, Sun 03:00):
   purge rows older than `TELEMETRY_DB_RETENTION_DAYS` (30) **plus** a size guard —
   if the table exceeds `TELEMETRY_MAX_MB` (200) it force-trims the oldest rows
   to ~80 % of the cap and logs loudly.
4. **Archive**: `build_archive()` streams the whole table as gzip JSONL;
   `purge_archived()` deletes exactly what was archived (max-id watermark).

**Note on your "convert to gzip + download + clean at 200 MB" spec:** the
*automatic* 200 MB guard trims oldest rows (a server can't push a download to
your machine unattended). The **offline archive** is the admin "Archive & purge"
button (now surfaced with the over-cap warning). If you want it fully hands-off,
see §9.

---

## 7. Clearer people/business data for testing

`AdminBusinesses` already exposes per-business inspection (uploads, invoices,
inventory, payments, chat history) with the bizid column. Combined with the new
telemetry Businesses tab, you can now go **user → their telemetry → their data**
in a couple of clicks. Suggested additions in §9.

---

## 8. Hosting choice moved into registration (#7)

`Register.jsx` now shows a **Local / Hybrid / Cloud** selector at signup
(desktop app only — web always runs on cloud). On submit:
- **Local** → straight to the dashboard.
- **Cloud/Hybrid** → routed into the guarded switch flow
  (`/settings?tab=advanced&switch=<mode>`), reusing the connection-checked path
  and the new error surfacing — so the choice can never fail silently.

This replaces the "choose after first login" onboarding step with a choice at
the moment of signup, while keeping the safe, re-login-aware switch machinery.

---

## 9. Recommendations — make it stand out

**Reliability / trust (do first)**
- **Fix cloud CORS for the app origin** — this is almost certainly why cloud/
  hybrid fails in the app. Add the packaged app's origin to the HF Space
  `allow_origins`. Without it, §3/§8 can't complete.
- **Surface a health/self-test panel at first run** (backend reachable? cloud
  reachable? migration applied? clock skew?) so field installs diagnose
  themselves instead of failing silently.
- **Auto-report boot failures** — you already have pre-login telemetry; add a
  one-line "Send diagnostics" button that attaches the last N telemetry rows.

**Telemetry / ops**
- **Optional hands-off archive:** on the 200 MB guard, instead of only trimming,
  upload the gzip archive to object storage (S3/R2/Supabase Storage) before
  purging, so nothing is lost without manual action.
- **Error-rate alerting:** a daily scheduled digest ("N installs, M error events,
  top 5 failing events by bizid") to your inbox — turns telemetry into signal.
- **Per-bizid retention override** for businesses you're actively debugging.

**Product polish / differentiation**
- **Offline-first as the headline:** sub-second local POS with transparent
  background sync is a real edge over cloud-only competitors — make the mode
  badge and sync status always visible.
- **One-click "Move my data" between modes** with a dry-run preview (counts to
  be migrated) — reduces fear of switching.
- **Admin "impersonate/read-only view"** of a business's dashboard for support.
- **GST/tax report exports** (P&L, tax summary) surfaced as first-class buttons.

**Engineering hygiene**
- Add a **CI smoke test** that boots the packaged backend and asserts
  `/business/templates` returns all categories and `/health` reports DB
  connected — this would have caught the bundled-configs regression automatically.
- Add a tiny **`node --run build` gate** in CI for both frontends.

---

## 10. Windows verification checklist

- [ ] Rebuild the desktop backend with the updated `bizassist-backend.spec`.
- [ ] App registration → Business Category shows all 10 categories.
- [ ] Register a business in the app choosing **Cloud** → guarded switch runs,
      any failure shows a clear toast (no silent dead-end).
- [ ] Confirm HF Space CORS allows the app origin.
- [ ] Confirm Supabase migration `a9c4e7f1d2b8_add_telemetry_events` applied.
- [ ] Admin → Telemetry → Businesses/Events by bizid shows field data;
      Archive & purge downloads a `.gz` and drops the cap.

---

## 11. Startup blockers hit during your test run (fixed / action needed)

Two errors stopped the app from booting. **Neither was caused by the feature
changes** — both are environment/dependency issues.

### 11a. Backend crash — `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`
`database/models.py:877` (and 4 other spots) used PEP 604 unions (`int | None`).
That syntax is evaluated at function-definition time and **requires Python 3.10+**,
but your dev venv runs **Python 3.9** (`WindowsApps ... Python 3.9`). Production
targets **3.11** (`Dockerfile: FROM python:3.11-slim`), which is why CI/HF never
saw this.

**Fixed:** added `from __future__ import annotations` to the 5 affected files
(`database/models.py`, `main_groq.py`, `server_entry.py`, `routes/data_transfer.py`,
`routes/migrate.py`). This makes annotations lazy, so they no longer evaluate at
import — works on 3.9 and 3.11 alike. Verified safe: these are plain function
signatures (no pydantic union fields), and the ORM uses classic `Column()` (no
`Mapped[]`), so nothing evaluates the annotations at runtime.

**Recommended:** for local dev, use a **Python 3.11** venv to match production
exactly (`py -3.11 -m venv venv`), so you don't diverge from the HF/Docker build.

### 11b. Frontend crash — `qrcode.react` could not be resolved
`ThermalCompact.jsx` imports `QRCodeSVG` from `qrcode.react`, which **is** declared
in `package.json` (`^4.2.0`) but isn't in `node_modules` — the lockfile changed
and dependencies are out of sync. **No code fix needed.**

**Action (you, on Windows):**
```
cd frontend-billing
npm install
```
(Do the same in `frontend-admin` if it errors similarly.)
