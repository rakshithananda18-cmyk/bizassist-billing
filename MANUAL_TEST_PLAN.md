# Manual Test Plan — Login · Migration · Multi-System Sync · Cross-DB uid · Security

*Created 2026-06-26; expanded 2026-06-27 with the Step 3 uid + cloud-nudge scenarios, Phase C, and security/RLS + production go-live cross-refs. Run after the sync/migration hardening pass (see [`SYNC_MIGRATION_AUDIT.md`](SYNC_MIGRATION_AUDIT.md)). Goal: prove the flow end-to-end and capture clean Hugging Face + local logs so any issue is traceable.*

**Sections:** §0 pre-flight · §1 local→cloud migration · §2 multi-system real-time sync · §2c fresh-device login + cloud nudge · §2d durable-uid no-collision · §3 logs to share · §4 pass/fail checklist · §4b backup button · §5 known limits · **§6 security & RLS (incl. the deferred S-1 plan)** · §7 production go-live.*

> **Trust rule for multi-system use:** for two or more terminals running **at the same time**, put **every terminal in Cloud mode** (all writing directly to the HF Space). The cloud assigns every id, so there is no cross-database id collision, and each write broadcasts a real-time `sync.trigger` to the others. Hybrid mode is for **one** local primary + offline resilience — do not run two offline writers in hybrid yet (that's the deferred R-3 item).

---

## 0. Pre-flight — do this once before testing

| Check | Why it matters |
|---|---|
| **`JWT_SECRET` is identical** in local `backend/.env` **and** HF Space → Settings → Secrets | If they differ, every sync call returns **HTTP 401** and silently fails. This is the #1 cause of "sync doesn't work." |
| Local `.env`: `CLOUD_API_URL` (or `VITE_API_URL`) = your `https://<space>.hf.space` | Tells the local sync worker where the cloud is. |
| Local `.env`: `DATABASE_URL=sqlite:///./bizassist.db`, `LOG_LEVEL=DEBUG` | Local = SQLite; DEBUG gives the full flow in logs. |
| HF Space: `DATABASE_URL` = your Supabase Postgres URL | Cloud = Postgres (RLS + sequences live here). |
| HF Space runs a **single worker** | SSE connections + caches are process-local; >1 worker splits subscribers and drops events. |
| **Run Alembic on the cloud once:** `alembic upgrade head` against the Supabase DB | Ensures RLS policies + all migration tables exist before import. |

**Clear logs for a fresh run** (stop the local server first — a running server keeps writing):

```powershell
# PowerShell, from repo root, with the local backend STOPPED
Clear-Content backend\logs\bizassist.log -ErrorAction SilentlyContinue
Clear-Content logs\bizassist.log -ErrorAction SilentlyContinue
```

Then start the backend + frontend fresh.

---

## 1. Scenario A — Fresh login + Local→Cloud migration

**Steps**

1. Start local (SQLite) backend + `frontend-billing`. **Sign up / log in** as the owner.
2. Create a little seed data so the migration has content: ~3 products, ~2 customers, 1–2 invoices, 1 payment.
3. Go to **Settings → Hosting / Backup** and trigger **Migrate to Cloud** (or use the API below).
4. Confirm the success summary shows a non-zero `total` (and an `id_remap` if local/cloud ids differ).
5. Switch this terminal's **hosting mode to Cloud** and reload — your data should now load from the cloud.

**API fallback (if you prefer curl/Postman):**

```bash
# (a) export from LOCAL  → returns {"tables": {...}}
curl -s http://localhost:8000/api/migrate/export \
  -H "Authorization: Bearer <LOCAL_JWT>" > export.json

# (b) import into CLOUD (HF)  → returns {"imported":{...},"total":N,"id_remap":{...}}
curl -s -X POST https://<space>.hf.space/api/migrate/import \
  -H "Authorization: Bearer <CLOUD_JWT>" \
  -H "Content-Type: application/json" \
  --data @export.json

# (c) verify counts match on the cloud
curl -s https://<space>.hf.space/api/migrate/count -H "Authorization: Bearer <CLOUD_JWT>"
```

> Get `<CLOUD_JWT>` by logging into the HF Space app once (or `POST /login` against the Space) with the same username.

**What to look for**

| Where | ✅ Expect | ❌ Red flag |
|---|---|---|
| Local log | `migrate/export` activity; clean auth line | — |
| HF log | `migrate/import: user=… source_owner_id=X dest_owner_id=Y` then `migrate/import: dest_owner_id=Y imported={…} total=N remap={'from':X,'to':Y}` | `row skip in <table>` (a row failed — now isolated, but tell me which table), `sequence reset skipped`, `HTTP 401`, `fatal error` |
| Cloud count | `/api/migrate/count` equals what you created | counts lower than local |

**Post-fix behaviour to confirm (the bugs we fixed):**
- If one row fails, **the rest still import** and `total` is truthful (M-1).
- After import, **create a brand-new invoice on the cloud** — it must save without an id-conflict error (M-2: sequences realigned).

---

## 2. Scenario B — Multi-system real-time sync (the trust test)

**Topology:** Terminal **A** and Terminal **B**, both logged into the **same business**, both in **Cloud mode** → same HF Space.

**B1 — Live propagation**
1. Open the app on A and B. In each, confirm the SSE stream connected.
   - HF log: `[REALTIME] Business <id> subscribed. Active connections: …`
2. On **A**: create an invoice (also try: add a product, record a payment).
3. On **B**: the relevant list should **auto-refresh within ~1s, no manual reload**.
   - HF log: `[REALTIME] Broadcasting to Business <id>: sync.trigger`
   - B's browser receives `data: {"type":"sync.trigger","entity":"invoice"}` (visible in DevTools → Network → the `realtime/events` EventStream).

**B2 — Concurrency (no corruption)**
4. Edit the **same product** on A and B within a second of each other → last save wins, both converge to the same value, **no 500 / no duplicate / no half-written row**.

**B3 — POS counter isolation**
5. Open POS on A and B → each cart stays **independent** (cart sync is timestamped LWW; they must not bleed into each other).

**B4 — Offline → reconnect (single hybrid terminal)**
6. Put **one** terminal in **Hybrid** mode. Take it **offline** (DevTools → Network → Offline, or pull the cable). Create **2 bills**.
   - They print from local state and queue. Local log: bills saved; `[SYNC_WORKER] Cloud unreachable for business <id>` logged **once** (not every cycle — H-2).
7. Go back **online**. Within the sync interval:
   - Local log: `[SYNC_WORKER] Successfully pushed N changes`, then `[SYNC_WORKER] Pulling M changes`.
   - HF log: `sync/push: business_id=… received N changes`.
   - The **"N unsynced" badge clears** and open tabs refresh (R-1 fix: the worker's broadcast now reaches the browser).
8. **Exactly-once check:** the 2 offline bills have **distinct invoice numbers** and appear **once** on the cloud — no duplicates.

---

## 2c. Scenario C — Fresh-device login + Cloud-data nudge (Step 3, verified 2026-06-27)

*Proves the cross-DB identity + the "Cloud data available" sync nudge that the `/api/migrate/count` scoping fix unblocked.*

1. **On the web (cloud):** register a new owner (e.g. `Rakshith_Dev`) and add **≥1 record** (a customer/invoice). *(An empty cloud account produces no nudge — by design.)*
2. **On the downloaded local app:** log in as the **same** username/password.
   - Local log: local `/login` 401 → `[LOGIN] Fresh device — local mirror created (BizID …)`.
   - The local mirror is created with the **same BizID**; integer ids differ (cloud `business=12`, local `business=127`) — that's expected and the whole point of uid.
3. Watch the browser console: `[LOGIN-IDENTITY] BizID consistent (BA-…)` then **`[LOGIN-SENSE] Cloud has more data than this device (cloud=N, local=1)`** → the **"Cloud data available"** modal appears.
   - Modal dismiss is **× only** (no backdrop/accidental close); **Sync now** runs the merge.
4. Click **Sync now**:
   - Console: `[SYNC] cloud-to-local complete: N records merged`.
   - HF log: `migrate/export: resolved business_id=12 for username=… (JWT id=127)`.
   - Local log: `migrate/import: … remap={'from':12,'to':127}` and `imported={…}`.
5. Verify the cloud records now appear in the **local** Contacts/Invoices, scoped to the local owner.

| ✅ Expect | ❌ Red flag |
|---|---|
| Nudge fires only when cloud > local; merges under the local owner; no dupes | No `[LOGIN-SENSE]` despite cloud having data (→ count scoping / JWT_SECRET), or merged rows land under the wrong owner |

## 2d. Scenario D — Durable uid: cross-DB no-collision + idempotent re-sync (Step 3 / R-3)

*Proves sync/migration match on `uid`, not the per-DB integer `id`, and that re-syncing never duplicates.*

1. After Scenario C, **run "Sync now" a second time** (or re-login → nudge → Sync now).
   - Expect: it reports the same merge but creates **zero duplicates** — the customer count stays the same. Matches are by `uid` (or natural key for pre-uid rows), not `id`.
2. **Same-id, different-row check (optional, advanced):** create a record on cloud and a *different* record on local that happen to share an integer `id`; sync. Each must remain its **own** row (no wrong-row overwrite) — they're distinguished by `uid`.
3. **Child-FK check:** an invoice + its line items synced together must keep the line items attached to the **correct** invoice on the destination (FK resolved via the parent's `uid`; the worker applies parents before children).
   - Watch for `deferring … parent … not local yet` in logs — acceptable (rare, re-applies next cycle), but the child must **eventually** attach, never orphan.
4. **Phase C unique indexes (applied 2026-06-27):** attempting to insert a duplicate `(business_id, uid)` must fail at the DB — confirms the uniqueness guarantee is enforced, not just convention.

| ✅ Expect | ❌ Red flag |
|---|---|
| Re-sync = no new rows; children attach to right parent; `(business_id, uid)` unique enforced | Duplicate rows after re-sync, orphaned/mis-parented children, or a wrong-row overwrite |

## 3. What to share from Hugging Face (so I can confirm it went well)

Open the Space → **Logs** (container logs) and copy the window covering your test. The lines that matter (grep for these):

```
migrate/import           # migration result
sync/push:               # local → cloud
sync/pull:               # cloud → local
[REALTIME] Broadcasting  # real-time fan-out
[REALTIME] ... subscribed / unsubscribed
```

…and especially any of these **warning/error** lines if present:

```
HTTP 401            tenant mismatch        Corrupt payload
LWW conflict        row skip in            fatal error        sequence reset skipped
```

Share that HF window **plus** the matching local window from `backend\logs\bizassist.log` for the same minutes. With both sides I can trace any action UI → API → cloud → back.

---

## 4. Pass / fail checklist

| # | Check | Pass? |
|---|---|---|
| 1 | Login works; auth line in local log | ☐ |
| 2 | Migration `total` matches seed data; no `row skip` | ☐ |
| 3 | Cloud `/migrate/count` == local counts | ☐ |
| 4 | New invoice created on cloud **after** migration saves with no id conflict | ☐ |
| 5 | A→B live update within ~1s (SSE `sync.trigger`) | ☐ |
| 6 | Concurrent edit on same record → converges, no error | ☐ |
| 7 | POS carts on A and B stay isolated | ☐ |
| 8 | Offline 2 bills → reconnect → pushed, badge clears, tabs refresh | ☐ |
| 9 | Offline bills have distinct numbers, appear once (exactly-once) | ☐ |
| 10 | No `401` / `tenant mismatch` / `Corrupt payload` in either log | ☐ |
| 11 | Fresh-device login builds local mirror; `[LOGIN-SENSE]` fires when cloud has more (Scenario C) | ☐ |
| 12 | "Cloud data available" nudge appears; × is the only dismiss; **Sync now** merges N records | ☐ |
| 13 | Re-running Sync now creates **zero duplicates**; children attach to correct parent (Scenario D) | ☐ |
| 14 | Duplicate `(business_id, uid)` insert is rejected by the DB (Phase C unique index) | ☐ |
| 15 | RLS cross-tenant negative tests run **against Postgres** and pass (§6) | ☐ |

---

## 4b. Manual "Backup cloud → local" button (new)

In the **downloaded local app**, Settings → Hosting now has a **Back up now** button (cloud → local). It copies cloud data down to the local DB **without** switching hosting mode — local becomes an offline mirror/backup. Cloud stays the source of truth.

To test:
1. Run the **local app** (localhost), logged in. Make sure the cloud has data and `JWT_SECRET` matches.
2. Settings → Hosting → **Back up now**.
3. Expect: "Reading data from cloud" → "Writing backup to local" → "Verifying" → "N records backed up". Hosting mode is unchanged.
4. Verify locally (e.g. switch to Local mode briefly, or query the local DB) that the cloud's records are present.

Notes: the button only appears on the downloaded app (it must reach `localhost:8001`). One JWT works on both backends (shared `JWT_SECRET`). It uses the **mirror** (id-preserving) import so local is an exact copy; BizID is unified automatically (local owner adopts the cloud BizID).

## 5. Known limits & status

- **R-3 (durable uid) — NOW LIVE (2026-06-27), soaking.** Sync/migration match on `uid`, not integer `id`; Phase C part-1 unique indexes are applied on both DBs. Two offline Hybrid writers should no longer collide — but **soak this under real two-device use** (Scenarios C/D) before relying on it; Phase C parts 2 (`uid NOT NULL`) and 3 (retire the id/remap fallbacks) are still pending. Until soak passes, **Cloud mode on all terminals** remains the safest multi-writer config.
- **Posted journal / hash chain is not replicated in Hybrid** (R-4) — `GET /reports/verify-chain` may differ between local and cloud after a hybrid sync. Books on the **cloud** (source of truth) are authoritative.
- **HF Space must run one worker** — with more, SSE subscribers split across workers and some real-time events are missed.

---

## 6. Security & RLS testing (tenant isolation)

- **Run the existing cross-tenant negative tests against Postgres**, not just SQLite: `tests/test_rls_policies.py`, `tests/test_connections_security.py`, and the per-module isolation tests. SQLite has no RLS, so a SQLite-only green run does **not** prove cloud tenant isolation.
- **S-1 — RLS is currently FAIL-OPEN** (a connection with no `app.current_business_id` set sees all tenants). The fix (fail-closed) is **deliberately deferred** and has its own dedicated, robust plan:

  > 📄 **See [`RLS_FAIL_CLOSED_TEST_PLAN.md`](RLS_FAIL_CLOSED_TEST_PLAN.md).**
  > **⚠️ S-1 is held on purpose** — it is a live-Postgres access-control change that **cannot be tested anywhere in the current dev/sandbox** (no Postgres locally; the local app is SQLite, which has no RLS). **If the predicate or the system-context exemption is wrong it can `deny-all` and take the cloud app down.** It must be validated on a **dedicated Postgres staging DB** with every MUST-PASS case green before it touches production. Until then, RLS fail-open is mitigated only by the app-layer `business_id` filters + the per-request GUC.

---

## 7. Production go-live validation (cross-ref)

Before charging real merchants, also run the **MUST** items in `SESSION_HANDOFF.md` §8 (Production Readiness): green test-suite stamp, RLS fail-closed (§6 above), secrets hygiene + **rotate the exposed Supabase password**, backups/PITR on, offline-sync two-device QA (Scenarios B/C/D), and CA-validated GST/e-way. Security gap register: `SESSION_HANDOFF.md` §9.

If any checklist row fails, send me the two log windows (HF + local) for that step and I'll pinpoint it.
