# Sync Liveness & Post-Push Audit — 2026-07-31

Follow-up to [`SECURITY_AND_FINANCIAL_REVIEW_2026-07-30.md`](SECURITY_AND_FINANCIAL_REVIEW_2026-07-30.md).

Scope: commits `5058dfc` and `9c45cf9` (the last push), read against the Hugging
Face Space log for the `2026-07-30 11:38` boot and the local `192.168.0.102:8001`
backend log for `2026-07-31 14:05`.

The 2026-07-30 review closed all 10 security/financial items and recorded **Zero
Deviations** across six audited subsystems. That assessment holds for the domains
it examined — correctness of money, stock, tenancy and idempotency. This audit
covers a domain it did not: **liveness**. Whether the sync engine is still
*running* is a separate question from whether it computes the right answer, and
all three defects below are invisible to a correctness audit because none of them
produces a wrong value, an exception, or a failed status. They produce silence.

---

## 1. Findings

| # | Severity | Defect | Evidence | Status |
|---|----------|--------|----------|--------|
| 1 | ~~CRITICAL~~ **MEDIUM** | A web session overwrites the account's `hosting_mode` on the cloud record | Code path — **see the correction in §2, the blast radius was overstated** | **FIXED** |
| 2 | **HIGH** | The cloud parity audit runs on the 15 s push tick and starves it | HF/local log: unbroken `Hybrid Sync Engine skipped` from 14:05:49 to end of log | **FIXED** |
| 3 | **HIGH** | Instant Pull triggers a sync run on the echo of this device's own push | Code path; `sync.trigger` in `_PULL_EVENTS` + unconditional broadcast on push | **FIXED** |
| 4 | **CRITICAL** | Deferred pull rows were dropped silently — M-20 on the read side | `sync_worker.py`: `if resolve_parent_fk_uids(...): continue`, recorded nowhere | **FIXED** |
| 5 | HIGH | Pull cursor did not survive a restart; fell back to a `SyncLog` proxy | `_PULL_CURSOR: Dict[int,str] = {}` | **FIXED** |
| 6 | HIGH | A rejected pull row froze all 29 tables, then was abandoned | `_PULL_MAX_FAILED_STREAK` → `logger.critical("They need a human")` | **FIXED** |
| 7 | HIGH | Unbounded worker pull could never complete on a wide window | 10 s client timeout vs 180 s on the same endpoint from parity | **FIXED** |
| 8 | ~~MEDIUM~~ | Pre-existing data corruption flagged at migration | Boot log M-7, M-11, overfill ×33 | **RESOLVED — re-measured, see §5.1** |
| 9 | LOW | Repeated client SSE drops on the cloud Space | `SSE connection failure count: n/5` across 3 devices | **Open — expected for HF, see §5** |
| 10 | **HIGH** | Sales lost their customer before reaching the DB (`parseInt(name) → NaN → null`) | invoice + payment + journal all recorded the absence at the same instant | **FIXED** |
| 11 | MEDIUM | Pull-sourced ConflictLogs labelled local/cloud backwards | conflict 61 stored cloud ids under `local_payload` | **FIXED** |
| 12 | **CRITICAL** | A cloud payment was never delivered, so the same invoice was settled twice — ₹248 against a ₹124 invoice | LCL-OW-0037; cloud's own audit row for the insert + 55 min of `Pull failed: read operation timed out` | **FIXED (code) / data repair pending** |
| 13 | **HIGH** | Two of five pull "skip" paths dropped a real cloud row with no record, while the cursor advanced past it | `_apply_pulled_row` → bare `_Applied("skipped")` for `no-uid` and `clock-skew` | **FIXED** |
| 14 | **HIGH** | The parity sweep only ever asked "what is the cloud missing?" — a cloud row absent locally was invisible to it | `_cloud_parity_check` iterates `local_child[table]` only | **FIXED** |
| 15 | MEDIUM | Parity's paid-state check cannot see a double payment; `total_amount` was read and never used | Cloud stored 248.00 == cloud actual 248.00 on a 124.00 invoice → "parity OK" | **FIXED** |
| 16 | **HIGH** | The parity sweep sends a query parameter the endpoint does not declare, so its window has never been applied | `params={"since": ...}` vs `pull_changes(last_sync_at, limit, ...)`; request timed out at 180 s against the live Space | **FIXED** |
| 17 | **CRITICAL** | `ALTER TABLE users ADD COLUMN last_login DATETIME` — a SQLite type Postgres does not have — crash-looped the cloud Space | Space boot log: `type "datetime" does not exist` → `RuntimeError` at import → `Exit code: 1`, HTTP 503 | **FIXED — redeploy required** |

Findings 4–7 came out of a second pass asking a different question: *push has an
outbox, retries, and Ops visibility — what does pull have?* The answer was
"a cursor", and findings 4–7 are what that costs. They are addressed together in
§9 by giving pull an inbox.

Findings 12–15 came out of one invoice the owner noticed looked wrong, and they
are the same question asked once more. Findings 4–7 gave pull an inbox and then
exempted the `skipped` branch from it on the grounds that every skip was
deliberate. Two of the five were not. §7b is the full reconstruction.

---

## 2. CRITICAL — `hosting_mode` is written by devices that cannot observe it

### What happens

`general.hosting_mode` describes **how the owner's local install is hosted**. It
is stored on `users.settings`, and `users` is in `_SYNC_TABLES` — so it is an
**account-scoped field that LWW-syncs to every device**.

`resolveHostingMode` (added in `9c45cf9`) answers a **device** question, and it
answers it correctly: rule 1 returns `'cloud'` for any non-localhost origin,
because a browser tab genuinely has no local backend. The defect is that
`AuthContext` then persisted that device answer into the account field:

```
owner opens the web dashboard
  → web session derives 'cloud'                    (true of that tab)
  → PUT /settings writes 'cloud' onto the cloud `users` row, now the newest copy
  → desktop pulls it, overwriting its own 'hybrid'
  → sync_worker.run_hybrid_sync:  if hosting_mode != "hybrid": continue
  → the desktop stops syncing, and models._queue_change stops queueing rows
  → the desktop's next Settings load re-derives 'hybrid' and writes it back
  → the two devices now flip the field on every single page load
```

`shouldPersistMode(resolved, savedMode)` returned `true` for any disagreement, so
nothing stopped step 2.

### Why this is the same outage as before

`backend/tests/test_hosting_mode_gate.py` already documents the consequence,
measured on the real database on 2026-07-28: **business 7 wrote 42 syncable rows
and queued none of them** — 6 invoices, 11 invoice_payments, 1 customer, 21
stock_ledger, 3 register_shifts — logging nothing. Those 3 stranded
`register_shifts` are M-20's missing parents, and every sale rung on them sat
deferred cloud-side.

`resolveHostingMode.js` was written to end exactly that. Its own header says the
old behaviour "made the backend stop queueing rows entirely … emptied the outbox".
It closed the desktop door and left the web door open.

Business 42 in the log is precisely the exposed shape: browser devices
`web-c3189b9e`, `web-7b6ff2a3`, `web-30a8c790`, `web-2b23e957` **and** a local
backend registering `192.168.0.102:8001`.

### Fix

Two layers, both fail-closed.

> ## ⚠ CORRECTION — I overstated this finding's blast radius
>
> The chain I described below has a broken link. I wrote:
>
>   > `users` is in `_SYNC_TABLES`, so this field LWW-syncs to every device …
>   > the desktop pulls it over its own 'hybrid' … that install stops syncing
>
> **The middle step does not happen.** `users` was in `_SYNC_TABLES` (the outbox
> gate) but is **not** in `MODEL_MAP` (the apply set). So:
>
> * local → cloud: `push_changes` does `_MODEL_MAP.get("users") -> None` and
>   skips the row as *"unknown entity on this server"*. Verified on the live
>   database — **31 `users` rows queued, 31 acked, 0 ever applied.**
> * cloud → local: the pull iterates `MODEL_MAP`, so `users` is never sent.
> * the only cloud→local settings read is `_sync_subscription_from_cloud`, which
>   takes `cloud_settings.get("subscription")` and nothing else.
>
> `users.settings` therefore does not sync in either direction, and a web
> session's write **cannot** reach the desktop or stop its sync worker.
>
> **What the defect actually is.** A web session writes `hosting_mode: 'cloud'`
> onto the *cloud* `users` row, which is read by `core/api/biz_id.py`
> (`reachable`), `core/api/connections.py` (B2B connection active status) and
> `admin_service.py` (admin console reporting). So it corrupts cloud-side
> reachability and reporting for that business, and the two devices still
> overwrite each other's view of the field on every load. Real, worth fixing —
> but **not** an outage. Severity: MEDIUM, not CRITICAL.
>
> The outage that `test_hosting_mode_gate.py` documents (42 rows written, 0
> queued) is real and unchanged. Its cause was the desktop's *own* reconcile loop
> writing the wrong value locally. Attributing a second route to it was my error.
>
> Both fixes stand on their own merits: a web tab should not author an
> account-scoped field it cannot observe, and a cloud instance should not accept
> a `hosting_mode` downgrade. Neither is load-bearing against an outage.
>
> Found while investigating an unrelated question about sync volume — the same
> lesson as the T5 correction below: I verified the mechanism I had reasoned
> about, not the one the data would have shown me.
>
> ---
>
> **Correction, after the suites ran.** The first version of this fix also
> removed the `: 'pro'` fallback in `AuthContext`'s plan expression, so an
> unreadable plan resolved as *not Pro*. That was wrong, and `hostingAuth.test.jsx`
> (T5) caught it: `resolveHostingMode` drives what the UI **renders**, not just
> what gets persisted, so a Pro owner whose settings response lacked a
> `subscription` block resolved to `'local'`, lost the hybrid controls, and had
> the downgraded value read straight back out of `settings.general.hosting_mode`
> by `App.jsx` — the same visible outage this whole section is about, entered
> from the other side. One outage traded for another.
>
> The rule is now asymmetric on purpose: an unknown plan is **optimistic to
> render, never optimistic to persist**. Rendering hybrid for a free account
> grants nothing (`sync_business` 402s cloud-side, and `shouldPersistMode` still
> refuses the write), whereas rendering local for a Pro account switches a
> working device off in the UI.

**Client** — `frontend-billing/src/utils/resolveHostingMode.js`

`shouldPersistMode` now takes a context and refuses to write when the session is
not entitled to author the field:

- a **web session never persists** — it cannot observe a local backend, so it has
  nothing to say about one;
- **losing `hybrid` requires a known plan** — if the plan was not actually read,
  the resolver is guessing, and a wrong guess writes `'local'`, which stops the
  sync worker exactly as dead as `'cloud'` did.

`AuthContext.jsx` additionally stops defaulting the plan to `'pro'`. The old
expression ended `: 'pro'`, so a settings response with no `subscription` block
silently promoted the session. It now tracks whether the plan was read at all and
declines to persist on a guess.

The two questions are now separated explicitly:

- **How does this session behave?** — always the resolved mode, applied in memory.
  A web tab must prefix invoices `CLD-`, not `LCL-` (`getCounterPrefix` reads this
  field). This is unconditional and costs nothing.
- **What does the account record?** — written only when entitled.

**Server** — `backend/routes/auth.py`, `PUT /settings`

A cloud (Postgres) instance now refuses a `hosting_mode` downgrade away from
`hybrid`. The client guard protects a compliant frontend; this protects against an
old build, a different frontend, or a direct API call — which is the population
still running the version that caused the problem.

Only the downgrade direction is gated. `_provisionCloudSyncToken` PUTs `'hybrid'`
to the cloud on purpose, from a local install that knows it is hybrid, so the
Admin Console keeps reporting the truth. The rest of the patch is preserved —
only the `hosting_mode` key is stripped.

### If a business is already stuck

The stored value is recoverable from the desktop: open Settings on the local
install once, and the derivation re-persists `hybrid`. To confirm which businesses
are affected before touching anything:

```
python backend/scripts/reconcile_local_vs_cloud.py
```

It prints `hosting_mode` per business from both sides. Any business whose cloud
row says `cloud` while a local backend is registered for it in `[DISCOVER]` was
hit.

---

## 3. HIGH — the parity audit starved the push tick

### Evidence

```
14:05:38 [PARITY] biz=7: starting cloud parity check
14:05:49 WARN Execution of job "Hybrid Sync Engine" … skipped:
              maximum number of running instances reached (1)
14:06:04 … skipped     14:06:19 … skipped     14:06:34 … skipped
14:06:49 … skipped     14:07:04 … skipped     14:07:19 … skipped
14:07:34 … skipped     14:07:49 … skipped     14:08:04 … skipped
14:08:19 … skipped     (still going at end of log)
```

Eleven consecutive skips — over two and a half minutes in which **no business
pushed or pulled anything at all**.

### Cause

`_cloud_parity_check` issues a full `since=2020-01-01` pull of every synced table
with `read=180.0`. It was called inline from `run_hybrid_sync`, a job registered
at `seconds=15` with `max_instances=1`. One slow parity therefore blocks every
following tick for as long as it runs.

The comment at the call site read:

> Independent of the normal push so a parity failure never stalls outbox delivery.

Being a blocking call on the same thread, it was the exact opposite. `_LAST_PARITY`
is in-process, so **every restart re-arms it** — which is why this reproduces on
every boot, and why `--reload` in development makes it near-constant.

### Fix

Parity moved to its own scheduler job, `run_cloud_parity_sweep`, with its own
session and its own `max_instances=1`, at a 30-minute cadence against the
unchanged 6-hour per-business rate limit. A slow parity now delays only the next
parity. The old call site carries a comment explaining why it must not come back.

---

## 4. HIGH — Instant Pull answered its own echo

### Cause

`routes/sync.py` broadcasts `sync.trigger` (per entity) and `sync.pull_ping` to a
business's SSE subscribers on **every accepted push** — including the pushing
device's own listener. Both are in `cloud_listener._PULL_EVENTS`, and the event
carries no origin:

```
local push → cloud broadcasts sync.trigger → this listener sees it
  → trigger_sync_run(pull=True) → that run pushes → cloud broadcasts → …
```

a cycle driven entirely by this device's own writes. `_MIN_PULL_GAP_SEC = 3.0`
does not break it; it only sets the period. The log shows the broadcast fanout
this feeds on — `17:12:58` emits `sync.trigger`, `sync.trigger`, `sync.pull_ping`
for a single 2-change push.

### Fix

`sync_worker` calls `cloud_listener.note_local_push()` on every successful push,
and events arriving within `_ECHO_WINDOW_SEC` (8 s) are read as our own echo and
ignored. A genuine concurrent edit from another device landing inside that window
is not lost — the periodic `cloud_pull_interval` pull (default 120 s) is still
running and remains the guaranteed convergence path. Instant Pull is an
accelerator, never the only route.

Adding a device id to the push payload would be exact rather than heuristic, but
it is a protocol change requiring both sides to deploy together. Worth doing later;
the window is the correct fix to ship now.

### Two further defects in the same module, also fixed

**402 reconnected forever.** The raise site said "Stop trying", but the exception
went to the generic handler in `run()`, which reconnected on backoff indefinitely.
A lapsed Pro plan cannot change until the plan does. Now terminal — the scheduler
restarts the listener if eligibility returns.

**`stop()` then `start()` could produce two listeners.** `stop()` popped the
registry entry immediately, but a listener parked in `iter_lines()` on a
`read=None` stream may not observe the stop flag until the cloud sends something —
possibly never. The next `start()` saw an empty slot and spawned a second thread:
two SSE connections, two pull triggers per event, and the first unreachable. The
entry is now kept until the thread is actually dead, and reaped on a later call.
`get_state()` also no longer reports a stopping listener as running, which would
have hidden the pull countdown for a channel on its way out.

---

## 4b. CRITICAL — the pull side had no outbox (findings 4–7)

Push has had `sync_queue` from the start: an un-deliverable row **stays queued**,
is visible in Ops, retries on its own, and blocks nothing else. Pull had a cursor
and nothing else. Four defects follow directly from that asymmetry.

### The asymmetry, before

| | Push | Worker pull |
|---|---|---|
| Durable state | `sync_queue` table | `_PULL_CURSOR` module dict — lost on restart |
| Failure granularity | per row | per window — one bad row held all 29 tables |
| Retry | `POST /api/sync/outbox/{id}/retry` | none |
| Give-up | row stays queued, visible in Ops | `logger.critical(... "They need a human")` |
| Ops visibility | queue depth, outbox details | none |
| Pagination | chunked | none |

### 4b.1 Deferred pull rows were dropped (CRITICAL)

`resolve_parent_fk_uids` returns `True` when a child's parent is not local yet.
Its own docstring states the contract:

> Returns `True` if the row must be **deferred** … it re-applies on a later sync
> once the parent lands.

The pull-apply loop honoured the deferral and not the contract:

```python
if resolve_parent_fk_uids(db, model_cls, data, log_prefix="[SYNC_WORKER]"):
    continue                       # ← recorded NOWHERE
```

Nothing recorded ⇒ `_pull_row_failures` stayed empty ⇒ the cursor advanced ⇒ the
cloud never re-offered the row, because its `updated_at` had not changed and the
cursor was already past it. **The row was gone**, and `_pull_done` counted it as
applied.

This is M-20, which the push path already fixed, on the read side. The push
comment still describes it exactly: *"the row is DEFERRED, the client MUST be
told … The outbox row was gone, so the 'later sync' could never happen."*

Deferrals are not rare — they are the normal state whenever a child arrives in
the same batch as, or before, its parent.

### 4b.2 A rejected row froze everything behind it

The only recovery was to HOLD the global cursor, blocking all 29 tables, bounded
by `_PULL_MAX_FAILED_STREAK`, after which the row was abandoned with a CRITICAL
log line. A forced choice between stalling everything and losing one row —
resolved in a log nobody was reading. Push is never forced to choose.

### 4b.3 The cursor did not survive a restart

`_PULL_CURSOR` was a module dict. On restart the cursor was re-derived from:

```python
SyncLog.filter(status == "success").order_by(synced_at.desc())
       .offset(1 if queue_items else 0)
```

a *proxy* for what was applied, over a table that also holds push rows. Whenever
that proxy resolved **later** than the last row actually applied, everything in
between was skipped permanently. M-12, reintroduced by any restart, on a path
that only runs when something has already gone wrong.

### 4b.4 An unbounded pull could never complete

A first pull has no cursor → `last_sync_at` resolves to 1970 → every row of all
29 tables in one response, against a **10 second** client timeout. The parity
audit calls the *same endpoint* with a 180 s timeout, which is the tell that 10 s
was never sized for a wide window. Not data loss — a livelock: time out,
correctly decline to advance the cursor, repeat forever.

### The fix — `sync_inbox`

A durable inbox mirroring the outbox (`core/sync/inbox.py`, `SyncInbox` model):

* A row that cannot apply — deferred **or** rejected — is stored with its full
  payload and retried per row with backoff.
* **The cursor can therefore always advance.** Nothing is lost by moving on, so
  later rows are no longer held hostage. The abandon-after-N branch is gone.
* Parents drain before children, and each row applies in its own SAVEPOINT so one
  poison row does not roll back its neighbours.
* Nothing is ever deleted. A drained row is stamped `applied_at`; an exhausted
  one stops auto-retrying but is **counted and shown** rather than logged.

Supporting changes:

* **`SyncCursor` table** — the pull cursor is now write-through to disk, per
  business. The `SyncLog` proxy fallback is no longer the restart path.
* **Pagination** — `/api/sync/pull` accepts `limit`, returns `has_more` and
  `truncated_tables`. The worker sends a limit; **parity deliberately does not**,
  because it judges absence and a truncated page would make it invent MISSING
  rows. Parity now also refuses any snapshot carrying `has_more`.
* **The watermark rule** — after a truncated page the cursor advances only to the
  *minimum, across truncated tables, of the newest `updated_at` actually
  received*. Advancing to `pulled_at` would skip everything the cap cut off,
  turning a slow pull into silent data loss — strictly worse than the livelock.
  If no usable timestamp exists, the cursor is held.
* **Immediate follow-up** — a truncated pull re-pulls on the next tick instead of
  waiting a full `cloud_pull_interval`, so a backlog drains in seconds rather
  than one page every two minutes.
* **Ops parity** — inbox depth in `queue-depth`, a paginated Sync Inbox card, and
  a per-row Retry that also schedules the run (the outbox shipped that button
  once *without* the trigger, and it did nothing).

### The console is now live, and reports both directions

Two things the panel lacked, both of which made it quietly misleading:

**It only ever showed the outbox.** A device could report a clean, empty queue
while rows the cloud had sent sat un-applied and invisible — which is precisely
how §4b.1 went unnoticed. The Sync Inbox card is the missing half: per-row
reason (`waiting for its parent` vs `rejected`), attempt count, the actual error,
pagination at 10, and Retry. Two stats join the header row — *Held from cloud*
and *Needs attention* — and the green banner no longer trusts `health.ok` alone,
because that value is computed server-side from the outbox and knows nothing
about the inbox. Claiming "All systems healthy" over stuck rows would be the
banner asserting the exact thing that was untrue for months.

**It loaded exactly once.** The queues drain on backend timers — the 15 s sync
tick, per-row inbox backoff — none of which the frontend hears about, so the
numbers froze at whatever was true when Settings was opened. For a console whose
entire job is live queue depth, a snapshot is close to useless. It now refreshes
on `sync-event` (debounced 800 ms, because one invoice with eight line items
emits eight events), on a 10 s poll while the tab is visible, and on returning to
the tab after being away.

The details are where this gets it wrong or right:

| Concern | Handling |
|---|---|
| Flashing empty every 10 s | Background loads are `silent` — they never flip `loading`, so the placeholder does not reappear |
| Stacked requests | An in-flight guard refuses overlap; a sequence number means a superseded response cannot overwrite a newer one |
| Reader on page 4 when rows drain | Page indices are clamped to the new length, so a shrinking list cannot strand you on a dead page that reads as data loss |
| Copying an error out of a moving row | A **Pause** control stops the poll, the events *and* the foreground refresh. "Paused" has to mean the rows hold still |
| Trusting a stale number | The badge shows state and age (`Live · 12s ago`), on its own ticker so the age keeps counting between fetches |
| Background tabs polling | Paused while hidden — on a hybrid setup those queries land on the owner's own machine |

### One apply path, not two

`_apply_pulled_row` was extracted from the pull loop and is now called by **both**
the loop and the inbox drain. This is the rule `resolve_parent_fk_uids` states for
itself — *"single source of truth for both apply paths … so the resolution/
deferral logic can never drift"*. A separate implementation for the drain would
mean a second copy of the dedup fallbacks, the LWW rules and the conflict hooks,
and they would not stay in step.

The extraction was performed mechanically and verified: the 317-line body is
preserved verbatim apart from six `continue` statements becoming explicit
outcomes, and an AST pass confirms no unresolved names in either the new function
or its callers.

---

## 5. Open items — your call, not mine

### 5.1 Pre-existing data corruption — RESOLVED (re-measured 2026-08-01)

The boot log of 2026-07-30 reported 31 overfilled invoices, 2 b2b_orders, one
M-7 payment overrun and four M-11 open shifts. **Re-measured against the live
database using the system's own invariant** — `SUM(line_total) == total_amount +
cash_discount - round_off`, from `scripts/repair_line_items_by_invariant.py`:

| Check | Boot log 30 Jul | Now |
|---|---|---|
| Invoice overfill | 31 | **3** (2 over by ₹0.02, 1 under) |
| b2b_orders overfill | 2 | **none** |
| M-7 payments > total | 1 | **0** |
| M-11 multiple open shifts | 4 | **none** |

Nothing to repair. The three remaining rows sit on the script's own ±0.02
tolerance boundary — rounding, not corruption.

> **Correction worth recording.** An earlier pass of this section reported *39
> invoices, ₹718.68 overstated* and recommended running the repair script. That
> number came from an ad-hoc query I wrote that compared `SUM(line_total)`
> against `total_amount` alone, ignoring `cash_discount` and `round_off` — it
> was not the system's definition of the invariant. Using the real one gives 3
> rows and ₹0.04. I would have sent you to run a repair against clean data.

### 5.2 SSE drops on the Space (LOW)

`SSE connection failure count: 1/5 … Reconnecting` recurs across `web-c3189b9e`,
`web-7b6ff2a3` and `web-a17a22ff`. The client reconnects and the counter resets,
so this is working as designed — Hugging Face Spaces terminate idle streamed
responses. Not worth code changes unless you see counts reaching 5/5.

### 5.3 Confirmed NOT a bug

`sync/push: master-data LWW overwrite logged (local_won) — register_shifts.id=9
(incoming 2026-07-30 14:48:03, existing 2026-07-26 21:50:24)`

The label reads inverted at a glance — "local_won" alongside a *newer* incoming
timestamp. It is correct: `local` is the **pushing device's** perspective, and the
newer incoming row did win. LWW is intact.

One observation rather than a defect: `register_shifts` is not in
`FINANCIAL_ENTITIES`, so a shift overwrite is logged as master data rather than
raised for owner review. A register shift carries opening and closing cash. Given
M-11 above shows shifts already going wrong on this exact business, promoting
`register_shifts` to review-needed is worth considering — but it is a policy
change with UI consequences, so I have left it for you.

---

## 6. Verification performed

| Check | Result |
|---|---|
| `resolveHostingMode` / `shouldPersistMode` — 27 assertions incl. all 10 pre-existing | **27/27 pass** |
| `cloud_listener` echo suppression, expiry, duplicate-thread, reaping, state reporting — 8 assertions | **8/8 pass** |
| `core/sync/inbox` against a real SQLite DB — persistence, dedup, backoff, SAVEPOINT isolation, drain ordering, stuck handling, Ops retry — 18 assertions | **18/18 pass** |
| Truncated-page watermark rule — 5 assertions | **5/5 pass** |
| Structural: parity off the tick, sweep registered, echo stamped, page limit sent, parity sends none, apply path shared, abandon-branch removed, partial-pull hold retained — 24 assertions | **24/24 pass** |
| `agoLabel` — 6 assertions incl. null and future-clock | **6/6 pass** |
| `OpsHealthPanel` structure: hook ordering, pause honoured in all three paths, no request stacking, guarded state writes, silent refresh, page clamping, listener cleanup, banner logic — 18 assertions | **18/18 pass** |
| `ast.parse` + unresolved-name sweep on every modified backend module | pass |
| `esbuild` compile of `OpsHealthPanel.jsx` and its test file | pass |

Executed in an isolated Linux sandbox against copies of the modified modules.

**Not executed here, and you should run both before pushing:**

```
run_tests.ps1                      # backend pytest — 1,836 tests
cd frontend-billing && npx vitest run
```

The sandbox has no `fastapi`/`sqlalchemy`, and the repo `venv/` is a Windows
build. Vitest against the mounted Windows filesystem did not complete within the
available window. The logic each new test asserts has been verified directly, but
the suites themselves have not been run end to end.

### New regression gates

- `backend/tests/test_sync_liveness_regressions.py` — 20 tests across findings 1–3
- `backend/tests/test_sync_inbox.py` — 24 tests across findings 4–7
- `frontend-billing/src/__tests__/resolveHostingMode.test.js` — 6 tests appended
- `frontend-billing/src/__tests__/OpsHealthPanel.test.jsx` — 12 tests appended
  (5 on the Sync Inbox card, 7 on live refresh: event-driven, debounced,
  polled, pause honoured, no background blanking, age reported)

### Test changes

`backend/tests/test_pull_partial.py` — updated, not weakened. Two assertions
searched for the literal `_PULL_CURSOR[business_id] = _cloud_cursor`, which the
durable-cursor change replaced with `_set_pull_cursor(...)`. One failed outright;
the other would have started passing *vacuously*, matching nothing and therefore
catching nothing. Both now check both spellings — the old one so a revert is
caught, the new one so the test cannot go quietly hollow again.

### Suite results

Run locally after the fixes above:

- **Backend:** 1,882 passed, 6 skipped.
- **Frontend (`frontend-billing`):** 380 passed across 51 files.
- **Frontend (`frontend-ai`):** 13 passed.

The first run surfaced three failures, all mine: the two `hostingAuth.test.jsx`
T5 cases described in the correction in §2, and the `test_pull_partial.py` string
mismatch above.

---

## 7. Files changed

| File | Change |
|---|---|
| `frontend-billing/src/utils/resolveHostingMode.js` | `shouldPersistMode` gains the entitlement gate |
| `frontend-billing/src/contexts/AuthContext.jsx` | Passes persist context; plan no longer defaults to `pro`; session behaviour separated from account record |
| `frontend-billing/src/components/settings/OpsHealthPanel.jsx` | Sync Inbox card — depth, per-row status, pagination, retry |
| `backend/routes/auth.py` | Cloud-side `hosting_mode` downgrade guard |
| `backend/routes/sync.py` | `limit`/`has_more`/`truncated_tables` on pull; inbox depth in queue-depth; `/api/sync/inbox/details` + `/retry` |
| `backend/services/sync_worker.py` | Parity off the tick; `run_cloud_parity_sweep`; `note_local_push`; `_apply_pulled_row` extracted; inbox wired; durable cursor; pagination + watermark |
| `backend/services/scheduler.py` | `cloud_parity_sweep` job registered |
| `backend/services/cloud_listener.py` | Echo suppression; 402 terminal; `stop`/`start` race closed; state reporting |
| `backend/core/sync/inbox.py` | New — the pull-side outbox |
| `backend/database/models.py` | New `SyncInbox` and `SyncCursor` tables (picked up by `create_all`; no manual migration) |
| `backend/tests/test_sync_liveness_regressions.py` | New |
| `backend/tests/test_sync_inbox.py` | New |
| `frontend-billing/src/__tests__/resolveHostingMode.test.js` | Extended |

Added 2026-08-01 for findings 12–15 (§7b):

| File | Change |
|---|---|
| `backend/services/sync_worker.py` | `_Applied` gains `reason` + `is_lost`; all five skip sites tagged; pull inboxes the two recoverable ones; parity gains the cloud-only scan and the over-payment check; summary counts both; parity's request uses `last_sync_at` (was the undeclared `since`) and warms `/health` first |
| `backend/core/sync/inbox.py` | `_HELD_OUTCOMES` replaces the literal `"deferred"` comparison in `drain`; `stats()` gains open-ended `reason_counts` |
| `backend/scripts/inspect_cloud_invoice.py` | New — read-only, prints both sides' rows for one invoice with `uid` and `updated_at` |
| `backend/tests/test_pull_skip_is_not_loss.py` | New — 11 tests |
| `backend/tests/test_parity_is_bidirectional.py` | New — 9 tests, including a gate comparing parity's query params against `inspect.signature(pull_changes)` |
| `backend/database/migration.py` | `_portable_ddl()` — dialect-aware type token for every `ADD COLUMN` |
| `backend/tests/test_migration_ddl_is_portable.py` | New — 12 tests; every migration must name a type Postgres has |

---

## 7b. CRITICAL — one invoice paid twice (findings 12–15, added 2026-08-01)

The owner noticed that LCL-OW-0037 showed **one** cheque payment on the desktop
and **two** payments (Bank + Cheque, ₹248) on the cloud, on an invoice for ₹124.
Everything below is reconstructed from the live database — no inference where a
row could be read instead.

### 10.1 What happened, with timestamps

All times UTC. IST is +5:30.

| When | Where | What |
|---|---|---|
| 30 Jul 09:42:23 | local | LCL-OW-0037 created, ₹124, customer *Rakshith Mom*, unpaid. Pushes to cloud as cloud invoice **835**. |
| 30 Jul 09:40:51 | cloud | An earlier settlement (LCL-OW-**0036**, cloud invoice 834, UPI ₹124) is recorded on the cloud. It **pulls down cleanly** — it is local payment 69 today. |
| **30 Jul 11:43:09** | **cloud** | **₹124 settled by Bank against cloud invoice 835.** `idempotency_key = settle-62-1785411785605::835`. |
| **30 Jul 11:43:26** | local | `Pull failed: The read operation timed out`. Then again at 11:45, 11:47, 11:48, 11:51 … every attempt through 12:38, the last entry in that log. |
| 08 Jul 19:13 → 31 Jul 19:38 | local | **No successful `SyncLog` for this business at all.** |
| 31 Jul 18:58:56 | local | The invoice still reads `paid_amount 0.0`, `status Pending` — so it is settled **again**, by cheque. Pushes up. |
| → | cloud | The cloud now holds **₹248 against a ₹124 invoice.** |
| 31 Jul 19:00:16 | local | The pull brings the cloud invoice header down. LWW writes `paid_amount 248 / Bank`; 8 ms later a recompute drops it back to 124 from the single local payment row. Conflict **#61** is logged — with the sides labelled backwards (finding 11, fixed the same day). |

The 10-second HTTP timeout on the worker's pull (finding 7) is what made the
window this wide: `timeout=10.0` on `GET /api/sync/pull` in commit `9c45cf9`,
against the same endpoint parity calls with 180 s. It is 60 s now.

### 10.2 How this was provable at all

The cloud's *own* audit row for that INSERT is sitting in the **local**
`table_alterations` table, payload and all:

```json
{"business_id": 42, "invoice_id": 835, "customer_id": 62,
 "amount_paid": 124.0, "payment_mode": "Bank",
 "idempotency_key": "settle-62-1785411785605::835"}
```

`business_id 42` is Varshini's **cloud** id (she is `7` locally), and `835` is the
cloud's integer for LCL-OW-0037. So this row was written on the cloud and
replicated down — which was only possible because `table_alterations` had no
`updated_at`, so it ignored the incremental filter and came down **in full on
every pull**. That was itself a defect and has since been removed from the sync
map.

The uncomfortable version: *the only reason this incident is reconstructable is a
bug we fixed.* Every future occurrence of it would be silent.

### 10.3 The three code defects behind it

**Finding 13 — two of five "skip" paths were silent losses.**
`_apply_pulled_row` returns `_Applied("skipped")` on five paths, and the class
docstring asserted all five were deliberate: *"Nothing is lost, so this is NOT
inbox material."* Three are decisions taken with both copies in hand
(`no-identity`, `lww-local-newer`, `no-updated-at`). Two are delivery failures:

* `no-uid` — the row cannot be matched, so we decline to write it. The row is
  real and still on the cloud.
* `clock-skew` — the cloud timestamp is >5 min ahead. That is a clock problem;
  the same row applies cleanly once the clocks agree, if anyone still has it.

In both, the cursor advances past a row this database never received and the
cloud never offers it again — its `updated_at` has not changed and the cursor is
now past it. **That is M-12, in the branch that claimed exemption from it.**
`_Applied` now carries a `reason`, `is_lost` names the two, and the pull inboxes
them. The same gap existed one layer in: `inbox.drain` treated any outcome other
than the literal `"deferred"` as success and stamped `applied_at`, so a
re-declined row would have been recorded and *then* discarded.

**Finding 14 — parity only ever asked half the question.** `_cloud_parity_check`
iterates `local_child[table]` — local rows — and asks what the cloud is missing.
All three of its findings (WRONG_INVOICE, MISSING, PAID_STATE) point the same
way. A row created on the cloud that never reached this device was outside every
question it asked. It now enumerates the cloud side too and hands what it finds
to the **inbox**, so the row applies through `_apply_pulled_row` — the one apply
path — rather than through a second INSERT written inside the sweep. (Writing it
there would be a second, untested apply path for financial rows, which is how M-9
happened.)

**Finding 15 — the paid-state check cannot see a double payment.** It compares
the cloud's *stored* `paid_amount` against the cloud's *own* payment sum. When
one invoice is settled twice those two numbers agree perfectly: stored 248.00,
actual 248.00, invoice total 124.00, verdict `cloud parity OK — no drift
detected`. `total_amount` was read into a variable on the line above and never
referenced again. There is now an explicit over-payment check, reported and
deliberately **not** auto-repaired — which of two payments is the real one is a
question about what happened at the counter, and voiding a payment row is not a
decision a background sweep gets to make.

### 10.3b Finding 16 — the sweep's window was never a window

Found by running the diagnostic script, which had copied parity's request
verbatim and timed out at 180 s against the live Space.

`_cloud_parity_check` sent:

```python
params={"since": "2020-01-01T00:00:00"}
```

`/api/sync/pull` has no `since` parameter. Its signature is
`pull_changes(last_sync_at, limit, ...)`, and **FastAPI drops unknown query
parameters without complaint** — so `last_sync_at` arrived as `None`, the
endpoint fell through to `datetime(1970, 1, 1)`, and the `"2020"` in that string
has never had any effect in the lifetime of the function.

The behaviour was accidentally what parity wants — it *does* need a full
snapshot, because it judges whether a local row is **absent** from the cloud and
absence cannot be read off a truncated page. That is why nothing caught it. It
matters anyway for two reasons:

* the next person to narrow that window would have watched their edit do
  nothing; and
* it means the sweep has only ever made the single largest request the API can
  serve — the same unbounded shape that was timing out on 30 Jul when the
  payment was lost. It timed out again on 2026-08-01.

Fixed by sending the parameter the endpoint declares, still with no `limit`
(deliberate — the endpoint's own docstring says parity must not send one), and by
pinging `/health` first so a sleeping Space wakes on a cheap call instead of
spending the read budget on a cold start. *"The Space was asleep"* and *"the
endpoint cannot answer"* are different problems and were indistinguishable.

The regression gate compares what parity sends against
`inspect.signature(pull_changes)` rather than against a hard-coded string, so it
keeps working when the endpoint gains a parameter. It was verified to fail when
the old line is put back.

### 10.3c Finding 17 — I took the cloud down (CRITICAL)

This one is mine, introduced in this audit's own work and found only because the
diagnostic script above got an HTTP 503 instead of an answer.

`users.last_login` was added to the `User` model and registered as:

```sql
ALTER TABLE users ADD COLUMN last_login DATETIME
```

`DATETIME` is a SQLite spelling. **Postgres has no such type.** The Space boot
log:

```
[Migration] Failed to add users.last_login:
    (psycopg2.errors.UndefinedObject) type "datetime" does not exist
CRITICAL: Database schema mismatch! … missing from the database: users.last_login
RuntimeError: CRITICAL: Database schema mismatch!
Exit code: 1
```

`_check_schema_integrity` then raised at **import time**, so uvicorn could not
load the app at all and the Space crash-looped. Every device got 503 — which
also means the sync that this whole audit is about had stopped completely.

**Why the reviews did not catch it.** SQLite has no real type system: it accepts
*any* type name in `ADD COLUMN`, including ones that do not exist. So the
statement is correct-looking and works perfectly for as long as it only runs
locally. And there are about a hundred earlier `DATETIME` entries in
`_COLUMN_MIGRATIONS` that have never failed — because `create_all` had already
made those columns on the fresh Postgres database, so the ALTER was skipped.

> `create_all` creates missing **tables**. It never adds a missing **column** to
> a table that already exists.

So the landmine arms only for a column added to an existing table after the
cloud moved to Postgres. `users.last_login` was the first one in that position.
Every future one would have done the same thing.

**Fix.** `_portable_ddl()` translates the type token per dialect at execution
time (`DATETIME` → `TIMESTAMP` on Postgres), rewriting only the type — not the
column name, not a trailing `DEFAULT`. The existing ~150 entries are untouched:
rewriting them would be a large diff for no behaviour change, and the property
worth holding is not "no entry says DATETIME" but "every entry, as executed,
names a type Postgres has".

`tests/test_migration_ddl_is_portable.py` asserts exactly that across the whole
list, and was verified to fail (5 tests red) when the translation is removed.

**A note on the blast radius.** One bad DDL string became a total outage because
`_check_schema_integrity` raises rather than warns. That is the right call —
serving traffic against a schema that does not match the models is how silent
corruption starts — but it does mean the safety margin has to sit *before*
deploy. That is what the new gate is for.

### 10.4 What is still owed, and to whom

The code is fixed and gated. **The data is not.** The cloud is holding ₹124 that
was never taken twice at the counter, and nothing in the fixes removes it — by
design, per finding 15.

To confirm the last unknown (does the cloud's Bank row carry a `uid`? that
decides whether the inbox can now replay it, or whether it needs a manual void),
run on the machine with the backend:

```
cd backend
python scripts/inspect_cloud_invoice.py LCL-OW-0037 --business-id 7
```

Read-only, prints both sides' raw rows with `uid` and `updated_at`, and states a
verdict. It anchors its cloud window on the invoice's own creation date rather
than asking for a full snapshot — see finding 16 for why that distinction is the
difference between an answer and a timeout. Then the repair is one of:

* **duplicate settlement** (most likely) — void one ₹124 payment on the cloud;
  the remaining one matches the invoice on both sides.
* **cloud row is real and local is the duplicate** — the reverse, decided by
  which payment the customer actually made (Bank on 30 Jul, or Cheque on 31 Jul).

Either way it is a two-row decision that wants the owner's memory, not a script's
guess.

---

## 8. Position

Seven defects are closed and gated. The 2026-07-30 review's correctness findings
are unaffected — nothing here contradicts them; they simply did not cover whether
the engine was still turning, or what happens to a row the pull could not apply.

Two things to be clear about before this ships:

1. **The suites have not been run end to end.** The sandbox lacks the backend
   dependencies and the repo `venv/` is a Windows build. Every behavioural claim
   above was verified directly against the real modules, but `run_tests.ps1` and
   `npx vitest run` are yours to run. The `_apply_pulled_row` extraction is the
   largest single change and the one most worth watching in the pull tests.
2. **§5.1 is still open.** Thirty-three rows of known financial corruption sit in
   the database with a repair script that has not been run, on the same business
   that was writing to a closed outbox gate. That needs you at the keyboard for
   the dry run, and until it is settled I would not call the platform bulletproof.
