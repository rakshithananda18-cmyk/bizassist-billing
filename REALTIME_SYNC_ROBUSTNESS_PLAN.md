# Real-Time Sync Robustness Plan — toward Google/Firebase-grade reliability

*Created 2026-06-27. How our POS live-sync compares to Google Sheets / Microsoft co-authoring / Firebase, what's genuinely worth adopting for a **transactional billing** app, and a phased plan to get there. Companion: [`HOSTING_MODE_MASTER_PLAN.md`](HOSTING_MODE_MASTER_PLAN.md), [`SYNC_MIGRATION_AUDIT.md`](SYNC_MIGRATION_AUDIT.md), [`STEP3_UID_PLAN.md`](STEP3_UID_PLAN.md).*

---

## 1. How our sync works today (honest)

A **notify-and-refetch + Last-Write-Wins** model:

1. A client writes via HTTP to the cloud (Cloud mode) or to a local outbox that pushes to the cloud (Hybrid).
2. The server broadcasts a coarse **`{type:"sync.trigger", entity:"invoice"}`** SSE event to the other clients of that business (`services/realtime.py`). Consecutive duplicate triggers are coalesced.
3. Each client **refetches the whole affected list** from the API.
4. Conflicts resolve **row-level Last-Write-Wins by `updated_at`** (`ON CONFLICT … WHERE EXCLUDED.updated_at > table.updated_at`).
5. Resilience: offline **outbox**, **delta-pull cursor** (`last_sync_at`), **idempotency keys**, per-row **SAVEPOINT**, and (Step 3) durable **`uid`** cross-DB identity.

**Strengths:** simple, robust against flaky retail networks, exactly-once writes, no cross-DB id collisions (uid), money path is deterministic. **Limits:** coarse (full-list refetch = bandwidth + flicker), LWW can silently drop a concurrent field edit, SSE is one-way with **no event sequencing / resume / ack**, no presence/awareness, conflict resolution leans on wall-clock `updated_at` (clock-skew sensitive).

## 2. How the "gold standard" systems actually work

| System | Model | Granularity | Conflict handling | Fit for POS |
|---|---|---|---|---|
| **Google Docs/Sheets** | **Operational Transformation (OT)** — every keystroke is an op, transformed against concurrent ops by a server sequencer | character / cell | converge, preserve intent; nobody's edit is lost | ❌ overkill — billing rows aren't co-typed |
| **Figma / Linear / Yjs / Automerge** | **CRDTs** — conflict-free replicated types merge without a central sequencer | object / field | automatic, offline-first, P2P-capable | 🟡 useful only for collaborative surfaces (notes/catalog), not core billing |
| **Microsoft 365 co-authoring** | server-mediated merge (OT-like) | paragraph / cell | merge on save/sync | ❌ same as Google |
| **Firebase / Firestore · Realm** | **server-authoritative change-log + real-time listeners push per-field deltas**; offline cache; transactions / optimistic concurrency | document / field | field-level LWW **+ transactions** for atomic invariants | ✅ **this is our north star** |

**Key insight:** OT/CRDT exist to solve *concurrent free-text co-authoring*. A POS rarely has two people editing the **same invoice line** at the same instant. What we actually need is **Firestore-grade transactional sync**: ordered, acknowledged, per-field deltas; fast; offline-durable; with optimistic concurrency for the rare real conflict. That's robust *and* efficient without the OT/CRDT complexity.

## 3. Gap analysis (us → Firestore-grade)

| # | Today | Gold standard | Impact |
|---|---|---|---|
| G1 | SSE sends a **trigger**; client refetches the whole list | server pushes the **changed record (delta)**; client patches its cache | bandwidth, flicker, latency at scale |
| G2 | LWW overwrites the **whole row** by `updated_at` | **field-level** merge; last writer per *field* | a concurrent edit to a different field is silently lost |
| G3 | No global ordering / event id; refetch hides gaps | **monotonic per-business sequence** + client `last_seen_seq` → gap detection & exact catch-up | missed SSE events can leave a client stale until next write |
| G4 | Conflicts resolved by **wall clock** | **version/etag** optimistic concurrency; logical clock | clock skew between devices can pick the wrong winner |
| G5 | No **presence / locks** | "who's viewing/editing this invoice" + soft-lock | two cashiers can clobber the same open bill |
| G6 | SSE one-way, no **resume** | reconnect with `Last-Event-ID` replays missed events | a dropped connection = silent stale window |

## 4. Target architecture (incremental, on top of what we have)

Keep the cloud as source of truth and reuse the outbox/uid/idempotency machinery. Add:

- **Per-business change log** — every write appends a row to `sync_changes(seq BIGSERIAL, business_id, entity, uid, op, payload, version, created_at)`. `seq` is a **monotonic per-business sequence** (the logical clock). This *is* the event stream.
- **Delta push** — the SSE event carries `{seq, entity, uid, op, payload}` (the actual record), so clients **apply the delta** to their local cache instead of refetching.
- **Client cursor = `last_seen_seq`** — on every event the client checks for a seq gap; if gapped (missed events / reconnect), it calls `GET /api/sync/changes?since=<seq>` to replay exactly the missed deltas. Reconnect uses SSE `Last-Event-ID = last_seen_seq`.
- **Optimistic concurrency** — rows carry a `version` (int, bumped per write). Writes send the base `version`; the server rejects a stale write with **409** (client refetches + reapplies), or **field-merges** for entities flagged mergeable.
- **Field-level merge** for chosen entities (e.g. `products`: price vs stock; `business_settings`) — merge non-overlapping fields instead of whole-row LWW.
- **Presence / soft-lock** (optional, later) — a lightweight `entity_presence` channel so the UI can show "open on another terminal" and warn before overwrite.

This is the Firestore/Linear pattern: an ordered, acknowledged change feed with deltas + optimistic concurrency — not OT.

## 5. Phased plan (each phase independently shippable)

> Prerequisite: Step 3 uid is done (durable cross-DB keys) — the change log keys on `uid`, so this builds directly on it.

**Phase 1 — Delta push (kill the full refetch).** *Biggest efficiency win, low risk.* 🟡 **IN PROGRESS (2026-06-27): parties slice landed.**
- Extend the SSE event from `{type, entity}` to `{type, entity, op, kind, rid, uid, payload}` — **DONE** via `services/realtime.py::delta_event()` (backward compatible: keeps `type:"sync.trigger"` + `entity`, so un-migrated pages and older bundles keep refetching). The `payload` is the **page DTO** (e.g. `_customer_out(c)`), not the raw ORM row, so the client splices in an item identical to what `load()` produces — avoids the ORM-row↔DTO shape mismatch.
- Frontend: on event, **patch the cache** (`src/sync/applyDelta.js`, upsert/delete by `rid`/`uid`) instead of refetching; fall back to refetch when no payload or a gap is detected. **DONE for Parties** (customers + vendors).
- **Mode gate (important):** delta-patch the UI **only in cloud mode** — there every client reads the same cloud DB, so the row id is a stable shared key and the cloud delta is authoritative. In **hybrid/local** the UI reads the **local** DB (which the SSE delta hasn't written yet), so those keep the existing refetch-after-`syncManager.pull()` path. This is the low-risk cut that keeps the money path untouched.
- **Landed so far:** backend `delta_event` + dedup fix (payloaded deltas are never coalesced — `test_realtime_delta.py`); `core/api/parties.py` (4 sites: create/update customer + vendor) emit DTO deltas; `Parties.jsx` patches in cloud mode.
- **Rollout remaining (per-entity, each independently shippable):** `products` → Stock/Sales product lists; then the **money entities** — `invoices` (sales.py), `payments`, `purchases` — migrated only alongside the two-device soak in `MANUAL_TEST_PLAN.md`, since they're the untestable-here money path. The frontend `applyDelta` path is generic, so each money page auto-upgrades the moment its backend call sites emit a DTO payload.
- Result: far less bandwidth, no list flicker, sub-second updates. No schema change.

**Phase 2 — Ordered change log + gap recovery.** *Reliability — the core "Google-grade" piece.*
- Add `sync_changes` table + `seq` BIGSERIAL per business (or a global seq with a business index).
- Write path appends to it (in the same txn as the entity write — atomic).
- New `GET /api/sync/changes?since=<seq>`; SSE carries `seq` and supports `Last-Event-ID` resume; client tracks `last_seen_seq` and back-fills gaps.
- Result: no silent stale windows; reconnect/missed-event is self-healing and exact (not a full resync).

**Phase 3 — Optimistic concurrency + field merge.** *Stop silent lost-updates.*
- Add `version` to mergeable entities; bump on write; reject stale writes (409) or field-merge per a per-entity policy.
- Replace whole-row `updated_at` LWW with version+field merge where it matters; keep `updated_at` LWW as the default for append-only/transactional rows.
- Result: a concurrent edit to a *different field* is preserved; true conflicts surface instead of vanishing.

**Phase 4 — Presence & soft-locks.** *UX safety for shared bills + the real cart-handoff USP.*
- Lightweight presence over the existing realtime channel: broadcast "viewing/editing entity X". Show it in the UI; warn/soft-lock before overwriting an invoice open elsewhere.
- **Productised cart hand-off (the actual USP):** an *intentful* "send this open bill to terminal 2 / from waiter tablet → counter" action, with presence + soft-lock so a bill open on one terminal can't be silently clobbered by another. This replaces the old blind business-wide `pos.cart_sync` (which caused the G5 cross-terminal clobber found in the 2026-06-27 soak — see `SESSION_HANDOFF.md`). The live POS cart is now **per-terminal** by default (`Sales.jsx::POS_CROSS_DEVICE_CART_SYNC=false`) until this lands; committed-data real-time sync (Phases 1–3) is unaffected.

**Phase 5 (optional, future) — CRDT for genuinely collaborative surfaces only.**
- If/when collaborative notes, a shared catalog editor, or multi-user order drafts appear, use **Yjs** (`y-websocket`) for *those specific surfaces*. **Do not** retrofit CRDT onto billing rows — Phases 1–3 already give billing the robustness it needs.

## 6. Efficiency & robustness specifics (build-time guardrails)

- **Transport:** SSE is fine for server→client deltas (keep it — simpler than WebSocket, works through proxies). Add `Last-Event-ID` resume. Consider WebSocket only if/when presence needs frequent client→server chatter.
- **Batching / backpressure:** coalesce bursts (e.g. a 50-row import) into one batched delta event; cap event size and fall back to "refetch entity" beyond a threshold.
- **Atomicity:** append to `sync_changes` in the **same transaction** as the entity write so the log can never diverge from the data.
- **Ordering:** `seq` is the single ordering authority — clients apply strictly in seq order; out-of-order deltas wait for the gap fill.
- **Idempotency:** keep the existing idempotency keys; delta-apply must be idempotent (apply-by-uid, ignore `seq <= last_seen`).
- **Single-worker today:** the in-memory subscriber registry is process-local (`PRODUCT_REVIEW` A-4). Multi-worker realtime needs **Redis pub/sub** for fan-out + the change log for catch-up — fold into Phase 2/scale work.
- **Money invariants stay server-authoritative & deterministic** — journal/hash-chain/period-locks are never CRDT/LWW-merged; they post on the cloud (source of truth).

## 7. What we deliberately DON'T do (and why)

- **No full OT / character-level merge** — billing records aren't co-typed text; the complexity/maintenance cost isn't justified.
- **No CRDT on core billing rows** — field-level LWW + optimistic concurrency + the ordered log already prevent the lost-update/stale problems for transactional data; CRDT is reserved for true collaborative-editing surfaces (Phase 5).
- **No client-authoritative money** — convergence is for cached/projected data; the books remain server-posted and deterministic.

---

## 9. Multi-terminal POS design (decided 2026-06-27)

*Surfaced during the 2-device cloud soak. Covers what happens when ONE business runs several POS terminals (two cashiers + the owner), and the design we settled on. Companion bug record: `SESSION_HANDOFF.md` (POS cart clobber).*

### 9.1 The live cart is PER-TERMINAL (not shared)
- Two cashiers ringing up two customers must have independent open bills. A silently-shared live cart can only ever let one terminal erase another's in-progress sale (the clobber observed in the soak — gap **G5**).
- **Shipped:** `Sales.jsx::POS_CROSS_DEVICE_CART_SYNC = false` — a terminal no longer broadcasts its cart to, nor applies a cart from, any other terminal. Per-device localStorage restore (minimized tabs) is untouched. Backstop: an empty remote cart can never overwrite a non-empty local cart (`cartHasItems` + `tabsRef`).
- The owner can also run their **own** POS — they're just another session/terminal, same rules apply.

### 9.2 Owner oversight = a SEPARATE, read-only feed (not cart sync)
The genuinely useful feature isn't cashier↔cashier cart sharing; it's the **owner watching (and occasionally editing) what each counter is doing, from the owner's screen.** Build it as a one-directional read feed so it can't clobber anything:

- **Stage 1 — "Live Counters" (read-only).** Each active POS session publishes a cart *snapshot* tagged with cashier + counter label; the owner (role-gated) subscribes and watches live tiles ("Counter 1 (Asha): 2 items, ₹240"). Nothing the owner's screen does writes back into a cashier's cart → zero clobber risk, no dependency on the concurrency work. Reuses the existing `pos.cart_sync` broadcast, redirected to owner-only consumers. **This alone delivers the requested feature.**
- **Stage 2 — owner take-over / edit (later).** The moment the owner can *edit* a cashier's open bill you have concurrent edits → needs the soft-lock + version safety (§9.4 / Phases 3–4). A contextual **"Take over"** action (counter goes view-only) is the only button worth having; there is **no** global "sync now"/"grant access" button beside Settings (manual locks rot and a global cart-sync button just re-creates the clobber).

### 9.3 Invoice numbering across counters (MONEY-CORRECTNESS) — 🟢 IMPLEMENTED 2026-06-27 (pending user test)
**Problem (today).** `core/billing/commands.py::_next_invoice_number` = `INV-{count(existing)+1}` per DB; the number is client-supplied or server-counted. With two terminals this collides:
- *Local/offline:* each device counts its **own** SQLite → both mint `INV-1001` for different sales.
- *Cloud:* two near-simultaneous sales both read the same count → both try `INV-1001`.

And `create_sale_invoice` treats *same business + same invoice_no* as a **retry** and returns the existing invoice → the second, genuinely-different sale is **silently swallowed (lost sale)**. Quiet data loss, not a loud error.

**Decided fix (both modes, no coordination needed):**
1. **Per-counter number space** — give each terminal its own prefix/range (already have `device_id` on the request): Counter 1 → `C1-0001…`, Counter 2 → `C2-0001…`, owner → `OW-0001…`. Unique **by construction**, works offline + online, never collides on sync. A one-time "counter label/prefix" set per terminal in settings.
2. **Idempotency on request-id, not the human number** — retry-dedupe must key on `X-Client-Request-Id` (the outbox's outer wall already sends it), **not** on `invoice_no`. So "same bill retried" dedupes correctly while "two different bills that clashed on a number" can never be merged.

> Mental model: **per-counter prefix = no collisions; request-id idempotency = safe retries.** This is a prerequisite before enabling real multi-counter billing.

**Landed (2026-06-27):**
- Backend: `_next_invoice_number(db, business_id, counter_prefix)` is prefix-aware (counts only its own series); `counter_prefix` threaded through `create_sale_invoice` + both routes (`SaleRequest`, `FrontendInvoiceRequest`). The `X-Client-Request-Id` outer wall stays the authoritative retry guard; the `invoice_no` wall is now a benign secondary (per-prefix numbers are unique → no cross-counter merge). **No schema change** (prefix lives in the `invoice_id` string). Tests: `tests/test_billing.py::test_counter_prefix_separates_series`, `::test_two_counters_first_sale_no_collision`, `::test_blank_prefix_defaults_to_inv_series`.
- Frontend: `Sales.jsx` `getCounterPrefix()` resolves the prefix (now **login-based** — see §9.3a); `syncTabNames`/`getNextInvoiceNo` number **within that series** (also fixes the old bug where the prefix was derived from the global-max-numbered invoice, scrambling multi-counter).
- **Manual test:** assign cashier A `C1`, cashier B `C2` (Staff page); each bills → `C1-0001`, `C2-0001` (no collision, no swallowed sale). Owner with none set → `OW-` series.

### 9.3a Counter identity — STAFF-ASSIGNED (login-bound) — 🟢 IMPLEMENTED 2026-06-28 (pending user test)
**Model (FINAL — supersedes the earlier terminal-bound/localStorage attempt):** a *counter* is **assigned to a login**, owner-controlled and server-stored. Rationale: this is a **browser app with no reliable device/terminal ID**, so any "this machine is C1" tag is a local value that can be cleared or edited (tamperable). The **login** is the only identity the server can trust and a cashier cannot manipulate at the till. So the counter follows the *account*, set by the owner in Staff management.
- **Three layers stay distinct:** **business** (one tenant; owner + staff share `business_id`), **login** (owner vs cashier — *who*), **counter** (the invoice-number series, now = the login's assigned prefix).
- **Storage:** `users.counter_prefix` column (nullable). Owner-assigned per staff; owner sets their own (default `OW`). Registered in `_COLUMN_MIGRATIONS` + alembic `b3c1d5e7f9a2`. Returned on `/login` + `/profile`.
- **Who sets it:** owner only — `POST/PATCH /staff` (`counter_prefix`, normalised to a short alnum token) and the owner's own via `PUT /profile`. Cashiers are blocked from `/staff` entirely, so they can't self-assign (no till-side manipulation).
- **Billing:** `Sales.jsx::getCounterPrefix()` reads `user.counter_prefix` from the auth user (fallback: owner→`OW-`, else `INV-`); `syncTabNames`/`getNextInvoiceNo` number within that series. The POS shows a **read-only** badge (`components/sales/CounterMenu.jsx` → `Counter: C1`) — no picking/adding at the till. The old per-device dropdown + `PosCounterSettingsModal` prefix field were **retired**.
- **Owner UI:** Staff page (`Staff.jsx`) — owner defines **named counters** (`{name, prefix}`, stored in owner `settings.transactions.counters`, cashier-write-blocked); each cashier is **assigned via a dropdown** (add-form + per-row `<select>`), not free-typed. The POS read-only `Counter:` badge is **clickable for owners** → navigates to `/staff` (counter setup lives in Staff management; no add-at-till).
- **Tests:** `tests/test_staff.py::test_owner_assigns_staff_counter_prefix_carried_to_login`, `::test_cashier_cannot_change_their_counter_prefix`.
- **Caveat (documented):** prefix follows the *login*, so the **same account** signed in on two machines at once shares one series (rare; server still guards each number). One account = one counter at a time.
- **Deploy:** needs the `users.counter_prefix` migration on both DBs (runtime migrator auto-adds on startup; alembic rev for parity), HF redeploy, Vercel redeploy.

### 9.3b Local↔cloud number namespacing (avoids cross-DB clash) — 🟢 IMPLEMENTED 2026-06-28 (pending user test)
**Problem:** the per-login counter prefix (§9.3a) stops collisions between two *online* logins, but **two disconnected databases** (a local SQLite + the cloud) each independently mint `C1-0001` for *different* sales. On local→cloud migrate, the importer's natural-key fallback (`_NATURAL_KEYS["invoices"]=["invoice_id"]`) would match them by number and **merge two different bills → lost sale**.

**Fix (two parts, GST-safe — number is final at issue, never re-numbered):**
1. **Mode/instance namespace** — `Sales.jsx::getCounterPrefix()` prepends **`LCL-`** to the series on a **local/hybrid** device (`hosting_mode != 'cloud'`); **cloud stays clean**. So: cloud `C1-0001` / `OW-0001`; local `LCL-C1-0001` / `LCL-OW-0001`. The two series can never share an `invoice_id`, so migrate just inserts — no merge. *(>1 local machine: give each its own tag, e.g. `LCL1-`/`LCL2-`; single local machine uses `LCL-`.)*
2. **Migrate backstop** — `routes/migrate.py::_import_with_remap` skips the natural-key fallback when the incoming row **carries a `uid`** (uid mismatch = genuinely different row → insert, never natural-merge). Covers the residual case (two local machines, or legacy dup numbers). Test: `tests/test_sync_migration_fixes.py::test_import_does_not_merge_different_uid_invoices_sharing_a_number`.

**GST note (confirm with CA):** multiple invoice series (`C1-…`, `LCL-C1-…`) are allowed if each is unique + consecutive; the number printed on the customer's tax invoice is final and is **never** re-numbered at merge/GST time — GST generation only *consolidates* cloud + local data and lists each series as-is.

### 9.4 How the concurrency layers stack (POS example)
Two cashiers Asha (T1) / Ravi (T2), same shop, cloud:
1. **Per-terminal carts (done)** — Asha's 3-item cart and Ravi's cart never touch. Removes the most common collision outright.
2. **Version / optimistic concurrency (Phase 3)** — for records BOTH can edit (a product's price/stock, a customer, a parked bill): each carries a `version`; first save wins (v7→v8), the stale save is rejected **409**, client reloads + re-applies → both edits survive. Server-authoritative — works even if the UI forgets to lock.
3. **Presence + auto soft-lock (Phase 4)** — opening a shared bill marks it "open on Terminal 1"; others see view-only + a contextual "Take over". Prevents the collision in the UI; Phase 3 guarantees correctness if it's bypassed.

Boundary: all of the above is for **editable** records (drafts, parked bills, product/customer master). A **completed** sale is an immutable posted invoice (journal + hash chain) — never merged or version-raced, only created.

### 9.5 Sequencing
Do **§9.3 invoice numbering first** (money-correctness, blocks multi-counter), then **§9.2 Stage 1 Live Counters** (high value, low risk, no concurrency dependency), then the delta-push rollout to money entities, then **Phase 3 version concurrency** → **Phase 4 presence/soft-lock + Stage 2 owner edit**.

---

## 10. Net

Phases 1–2 alone bring us to **Firebase/Firestore-grade** real-time robustness (ordered, acknowledged, self-healing per-field deltas) — efficient *and* reliable — while staying simpler than Google Docs' OT. Phase 3 closes the lost-update gap; Phase 4 adds the presence polish; Phase 5 is only for future collaborative features. Sequence and priority are tracked in `SESSION_HANDOFF.md` §10.
