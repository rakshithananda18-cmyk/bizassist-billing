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

**Phase 1 — Delta push (kill the full refetch).** *Biggest efficiency win, low risk.*
- Extend the SSE event from `{type, entity}` to `{type, entity, uid, op, payload}` (reuse `_serialize_orm_obj`).
- Frontend: on event, **patch the local cache** (insert/update/delete by `uid`) instead of refetching; fall back to refetch only on a detected gap.
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

**Phase 4 — Presence & soft-locks.** *UX safety for shared bills.*
- Lightweight presence over the existing realtime channel: broadcast "viewing/editing entity X". Show it in the UI; warn/soft-lock before overwriting an invoice open elsewhere.

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

## 8. Net

Phases 1–2 alone bring us to **Firebase/Firestore-grade** real-time robustness (ordered, acknowledged, self-healing per-field deltas) — efficient *and* reliable — while staying simpler than Google Docs' OT. Phase 3 closes the lost-update gap; Phase 4 adds the presence polish; Phase 5 is only for future collaborative features. Sequence and priority are tracked in `SESSION_HANDOFF.md` §10.
