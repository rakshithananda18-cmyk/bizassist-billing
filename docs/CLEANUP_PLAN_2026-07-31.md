# Cleanup Plan — superseded code, verified removable
**2026-07-31** · open items re-verified **2026-08-01**

---

## 0a. WHAT IS ACTUALLY LEFT

Re-measured against the live database and the current tree, not from memory.

### Nothing is broken. These are decisions and hygiene.

| # | Item | Why it needs you | Effort |
|---|---|---|---|
| 1 | **8 invoices have no customer link** | 4 carry a NAME and can be relinked mechanically; 4 have nothing and need someone who was there. Includes LCL-OW-0035 (₹424). | script + your answer |
| 2 | **Soak, then delete 23 commented-out files** | They are inert and allow-listed. Deletion needs your approval. | 10 min after soak |
| 3 | **59 sync conflicts awaiting review** | Real financial divergences (e.g. invoice 869: ₹124 vs ₹248). Only an owner can say which is right. | ongoing |
| 4 | **`frontend-admin` tests have never run** | 1 test file, a `test:` block in vite config, and **no vitest/jsdom/testing-library installed**. Needs a dependency decision. | `npm i -D …` |
| 5 | **Stale `.git/index.lock`** | From 2026-07-31 14:30. Blocks `git checkout`. I did not touch `.git`. | `del` one file |
| 6 | Watch the HF log after the next deploy | Confirm the three sync symptoms are gone in production. | passive |

### Closed since the first draft

* **Finding 8 (data corruption) — RESOLVED.** Overfill 31 → 3 (₹0.04, rounding),
  M-7 1 → 0, M-11 4 → none, b2b_orders 2 → none. See §5.1 of the audit for the
  correction to my own earlier measurement.
* **Staff** — 24 logins → 2; all 32 stray BizIDs cleared; DB uniqueness enforced.
* **Sync** — outbox 0 unsynced, inbox 0 held, durable cursors in place.
* **Dead code** — 7 functions removed, 23 files commented out, 2 gates added.

### The one thing I would not leave

Item 1. Four of those invoices carry a customer name that simply needs
relinking; the money is already correct, but they are invisible in the
customer's ledger until it is. LCL-OW-0035 is the one that needs a human memory,
and memories fade faster than databases.

---

Every item below was checked by comparing the actual code, not by reading the
labels on it. That distinction matters here: `routes/migrate.py` was already
marked `SUPERSEDED`, and it turned out to contain a protection the *live* module
had lost. A deprecation marker records an intention, not a fact.

---

## 0. Method

For each candidate:

1. **Static reference scan** over all 172 backend modules plus 151 test files —
   every module-level function, counted by identifier occurrence, then filtered
   to *undecorated* functions (a FastAPI handler is invoked by its decorator, so
   its name never appears again; treating that as "dead" gives ~200 false
   positives).
2. **Dynamic reference scan** — the same names as string literals, to catch
   `getattr` / registry dispatch that a name scan misses.
3. **Function-by-function comparison** of the superseded module against its
   replacement: names present in one and not the other, then a line-level
   comparison of every diverged body with comments and whitespace normalised
   away, so only *behavioural* differences surface.

What this method does **not** cover, stated plainly: a caller that builds a name
by string concatenation, and any consumer outside this repository. Neither
appears in this codebase, but neither is proven absent by the above.

---

## 1. `backend/routes/migrate.py` — SAFE TO DELETE

**Status:** deprecated, unmounted, warns on import. Retained at your request for
this pass.

### 1.1 Nothing imports it, nothing calls its endpoints

| Surface | Result |
|---|---|
| Python imports across backend + scripts + tests | **none** |
| Dynamic imports (`importlib`, `__import__`) | **none** |
| Mounted in `main_groq.py` | **no** — 23 routers, `data_transfer_router` among them |
| Frontend / desktop calls to `/api/migrate/*` | **none** |

The two modules declare **different paths**, which is why this needed checking
rather than assuming:

```
routes/migrate.py       (deprecated)  ->  /api/migrate/{export,import,count}
routes/data_transfer.py (mounted)     ->  /api/data-transfer/{export,import,count}
```

A leftover caller would not have crashed — it would have 404'd, and the feature
it drives (`loginSync.js`'s cloud-divergence nudge) would silently never fire.
All five callers — `loginSync.js`, `MigrationModal`, `BackupModal`,
`FileBackupCard`, `ConsequenceModal` — use `/api/data-transfer/*`.

### 1.2 Function-by-function: nothing would be lost

16 functions in `migrate.py`, 17 in `data_transfer.py`.

* **Missing from the replacement: none.**
* 7 identical.
* 9 diverged — every one of them in the replacement's favour:

| Function | Verdict |
|---|---|
| `export_data`, `import_data`, `count_records` | Auth upgraded: `Depends(get_active_user)` → **`Depends(require_business_owner)`**. Owner-only. |
| `_upsert_users` | Replacement matches staff on `(parent_business_id, lower(staff_login_name))`. `migrate.py` matches on the per-database `username` — the defect that put 24 cashier logins on a 2-till business. |
| `_import_with_remap` | Replacement re-pins `business_id` / `parent_business_id` / `user_id` to the destination owner **unconditionally**. `migrate.py` only re-pinned when the value equalled the source owner, leaving a foreign value untouched — its own replacement calls that "an import-file privilege leak". Also handles cross-tenant `uid` collisions, which `migrate.py` does not. |
| `_upsert_rows` | Behaviourally identical after the port in §1.3. Only difference is line wrapping. |
| `_fetch_table`, `_uid_lookup` | Docstring text only. |
| `_resolve_owner_id` | Replacement delegates to `resolve_business_id_in_db(require_public_id=True)` — fail-closed. `migrate.py` falls back to username and then the raw JWT `id`, which is the cross-database integer leak the BizID work exists to close. |

**One item deserves calling out on its own.** `migrate.py::_upsert_users`
includes `public_id` in the owner's update field list:

```python
update_fields = ["business_name", "gstin", ..., "settings", "public_id"]
```

An import payload could therefore **overwrite the destination business's BizID** —
the tenant identity spine. `data_transfer.py` excludes it. This alone means the
file must never be revived as-is, and is the strongest argument for deleting it
rather than leaving it to be found by someone in a hurry.

### 1.3 One thing WAS missing — already ported

`_free_invoice_number_on_import` (M-3 × §9.3b) existed **only** in `migrate.py`.
The mounted import path had no such guard, so a bill whose number was already
held by a different document hit the unique index and was **skipped**:

```
row skip in invoices (old_id=901999):
UNIQUE constraint failed: invoices.business_id, invoices.invoice_id
```

A lost sale on migration, invisible because the only test covering it imported
from `routes.migrate` — it exercised the dead copy and reported green.

Ported into `data_transfer.py` and wired into **both** insert paths.
`migrate.py`'s own comment had named the risk one level down: *"an invariant that
lives in only one of two paths is the exact defect M-7 was."* It lived in only
one of two **modules**.

### 1.4 Also safe

* The export-format documentation is duplicated **verbatim** in
  `data_transfer.py` — that header was a copy down to the filename, which is
  precisely how the two drifted apart unnoticed.
* Tests that imported it (`test_sync_migration_fixes.py`, `test_uid_cross_db.py`)
  were repointed to `data_transfer.py`. That is an improvement regardless of
  deletion: testing an unmounted module reports green for code that cannot run.

**Verdict: delete.** Nothing imports it, nothing calls its paths, no function is
unique to it, and it carries a live BizID-overwrite hazard.

---

## 1b. Three MORE orphaned route modules — found by the new gate

Recommendation §6.2 said a CI check should assert every route module is
reachable from the router graph. Writing it (`tests/test_no_orphaned_route_modules.py`)
found three predecessors nobody had flagged. This section did not exist when the
plan was first written.

| Orphan | Routes | Superseded by | Unmatched behavioural lines |
|---|---|---|---|
| `routes/insights.py` | 9 | `routes/ai_insights.py` | **0** |
| `routes/smart_insights.py` | 2 | `routes/ai_insights.py` | **0** |
| `routes/sales.py` | 4 | `core/api/sales.py` | 7, all accounted for below |

**Every path each declares is also declared by a mounted module** — verified by
enumerating `@router.<verb>` decorators across the whole tree, not by name
similarity. Nothing imports any of the three.

### `routes/sales.py` — the seven differences, resolved

* `expiry_date` / `mrp` / `attributes` — present in `core/api/sales.py`, only
  formatted across different lines.
* `shift_id` — the orphan used `get_open_shift(...)` and wrote
  `shift_id=(active_shift.id if active_shift else None)`. The live module calls
  **`require_open_shift`**, so a sale cannot be rung outside a shift at all. The
  live one is stricter, and it is the M-11 drawer-tally discipline.
* `customer_phone` — genuinely absent from the live response shape, which returns
  `customer`, `customer_name` and `customer_id`. A caller wanting the phone
  fetches the customer. No caller exists, since the module is unmounted.
* **`uid_token` — an active hazard.** The orphan puts it in every invoice
  response. It is the share-link secret behind
  `GET /public/invoice/{uid_token}`, which serves an invoice to anyone holding
  it, **unauthenticated**. `core/api/sales.py` does not expose it.

So `routes/sales.py` carries the same shape of latent danger as
`routes/migrate.py`'s `public_id` write: an unmounted file that would leak
something the mounted one is careful with, sitting there looking harmless.

**Verdict: all three safe to delete.** Added to `ALLOWED_UNMOUNTED` in the gate
with reasons so the suite passes until they are removed.

---

## 1c. The frontend — one duplicated file, and a set of deliberate shims

> **CORRECTION (added while commenting these out).** The table below was
> originally headed *"an entire duplicated B2B module"* and framed all twelve
> files as a stale copy. That is wrong, and it is unfair to whoever did the move.
>
> Ten of them are **13–14 line re-export shims** carrying no logic, each with a
> header that says so:
>
> > This file is a re-export shim kept only so any straggling import path keeps
> > resolving — it holds NO logic, so the two locations can never drift.
>
> That is the correct way to move a module. They are unreachable only because
> every caller was already migrated to the `../b2b` barrel, which means the shims
> did their job and can now go.
>
> **Exactly one file is a real duplicate: `components/b2b/CatalogOrderModal.jsx`
> (200 lines of logic, not a shim).** That is the one commit `5058dfc` edited,
> and the only one where work was genuinely lost. The finding stands; its scale
> does not. I read "12 unreachable files" as "12 duplicated implementations"
> without opening them.

The first version of this plan covered the backend only. The same method applied
to `frontend-billing/src` (246 files, import graph walked from `main.jsx`) finds
**19 files unreachable from the entry point**, and the bulk of them are one
coherent thing: the B2B module was moved into `src/b2b/` and the old copy was
left behind.

| Orphaned (old location) | Live replacement |
|---|---|
| `api/b2bClient.js` | `b2b/b2bClient.js` |
| `components/b2b/ConnectionsTab.jsx` | `b2b/components/ConnectionsTab.jsx` |
| `components/b2b/OrderDeskTab.jsx` | `b2b/components/OrderDeskTab.jsx` |
| `components/b2b/OrdersTab.jsx` | `b2b/components/OrdersTab.jsx` |
| `components/b2b/OrderDetailModal.jsx` | `b2b/components/OrderDetailModal.jsx` |
| `components/b2b/orderStatus.js` | `b2b/orderStatus.js` |
| `components/b2b/useOrderCart.js` | `b2b/useOrderCart.js` |
| `hooks/useB2BConnections.js` | `b2b/useB2BConnections.js` |
| `hooks/useB2BOrders.js` | `b2b/useB2BOrders.js` |
| `hooks/useB2BRealtime.js` | `b2b/useB2BRealtime.js` |
| `pages/B2BNetwork.jsx` | `pages/B2B.jsx` (tab `connections`) |
| `pages/B2BOrders.jsx` | `pages/B2B.jsx` (tab `outgoing`) |

`pages/B2B.jsx` imports the entire live module through one barrel —
`import { b2bClient, useB2BConnections, …, ConnectionsTab } from '../b2b'` —
which is why nothing reaches the old copies.

### This is not dormant. The last push edited the dead copy.

Commit `5058dfc` — *"complete UI/UX hardening, active B2B connection status
indicators"* — changed **both**:

```
 frontend-billing/src/b2b/components/ConnectionsTab.jsx        |  7 +-   ← LIVE
 frontend-billing/src/components/b2b/CatalogOrderModal.jsx     |  7 +-   ← DEAD
```

`components/b2b/CatalogOrderModal.jsx` is reachable only from
`pages/B2BOrders.jsx`, which is itself marked `⚠️ SUPERSEDED` and reachable only
from a render test. So seven lines of that push went into code the application
cannot execute. **There is no `CatalogOrderModal` in the live `src/b2b/` module
at all** — meaning if that modal is wanted, it has to be ported, and if it is not
wanted, the edit was wasted.

This is the same class as `routes/migrate.py` losing the invoice-number guard,
caught before it cost anything: two copies, work landing on the wrong one.

### The two SUPERSEDED headers are themselves out of date

`pages/B2BOrders.jsx` says it was replaced by
`components/b2b/{OrderDeskTab,OrdersTab,ConnectionsTab}.jsx` and
`hooks/{useB2BOrders,useB2BConnections,useB2BRealtime}.js` — **all six of which
are now themselves orphaned**. The module moved again after that note was
written. A deprecation note that points at another dead file is worse than none;
it sends the next reader one hop deeper into the wrong tree.

`pages/B2BOrders.jsx` also says it is "retained only so the existing render test
keeps a reference implementation to compare against; delete it once that test is
retired." That test is the only thing keeping it alive — the tail wagging the dog.

### Four unrelated orphans

| File | Note |
|---|---|
| `pages/Staff.jsx` | Staff management lives in `pages/Settings.jsx` (Staff Management tab). No importer. |
| `components/parties/PartyDetailModal.jsx` | Header says "extracted verbatim from pages/Parties.jsx (repo restructure)". No importer. |
| `components/hosting/HostingOnboardingModal.jsx` | No importer. |
| `components/Money.jsx` | No importer — the `fmt` helper it wraps is used directly. |

### Two test-only components — KEEP

`components/common/EmptyState.jsx` and `components/common/Skeleton.jsx` are
imported only by their own tests. Unlike the backend's test-only helpers, these
are *presentational components nothing renders*. They are either a shared UI kit
being built ahead of use, or dead. Worth a decision, not a deletion — check
whether the design intends them.

### A note on method

My first pass on the frontend reported **30** orphans, including all twelve live
`src/b2b/*` files. The walker followed `import … from` but not
`export … from` — the re-export barrel pattern `src/b2b/index.js` is built on.
I nearly reported the live B2B module as dead. The corrected walker resolves
both, and the frontend gate below carries a test that specifically pins barrel
resolution so the same mistake cannot silently return.

---

## 2. Functions with no caller anywhere

Verified by name scan **and** string-literal scan across backend + tests. Each
appears exactly once — at its own definition.

| Function | File | Notes |
|---|---|---|
| `_resolve_owner_id_legacy` | `routes/data_transfer.py:128` | Superseded in-file by `_resolve_owner_id`. Its own comment says it is retained "only for migration-history reference"; its username/JWT-id fallback is the exact pattern §1.2 rejects. |
| `_resolve_business_id_by_username_legacy` | `routes/sync.py:210` | Same shape, same reason. |
| `create_direct_connection` | `core/connection/service.py:482` | Check against the B2B connection flow before removing — this is the one item below where I would want a second pair of eyes, because B2B has cloud-side callers this repo cannot see. |
| `_where_biz` | `scripts/audit_money_integrity.py:104` | Helper in a diagnostic script. |
| `payments_view` | `services/insights_service.py:235` | |
| `fallback_enabled` | `services/llm_provider.py:314` | |

**Verdict:** the two `*_legacy` resolvers are safe to delete now — they are
documented as reference copies and their behaviour is the thing being moved away
from. The other four are safe on the evidence but carry no urgency; remove them
in the same pass or leave them.

### `owner_bizid` — mine, and dead

`core/identity.py::owner_bizid` is referenced only by the test I wrote for it. I
added it as part of the identity helper and nothing uses it. Either wire it into
`log_uploader` (which currently calls `bizid_for` and resolves the parent itself)
or delete it. I would not leave a helper whose only consumer is its own test.

---

## 3. Functions used only by tests — KEEP

Nine functions are called only from the test suite:
`current_value`, `unused_allowances`, `format_report`,
`_reconcile_parent_invoice_of_payment`, `_payloads_differ`, `_target`,
`is_intent`, `reset_mode`, `current_code`.

These are **not** dead. They are either extracted pure helpers whose whole
purpose is to be testable away from a database, or test-support hooks. Removing
them would delete the seam that makes the behaviour checkable. Listed here so a
future scan does not re-flag them.

---

## 4. Root-level scripts

`check_db.py`, `debug_fk.py`, `debug_lineitem.py`, `debug_remap.py`,
`repair_line_items.py`, `generate_sample_data.py`, `serve_dashboard.py`.

`repair_line_items.py` is worth a note: it is **not** superseded by
`scripts/repair_line_items_by_invariant.py`. They move in opposite directions —
the root script *copies missing* line items onto orphaned invoices, the scripts/
one *removes phantom* ones. The root script is a spent one-time repair for a bug
its own docstring says was fixed ("before the remap_ids fix").

**Verdict:** these are ad-hoc. Move the ones worth keeping into `backend/scripts/`
where the maintained repair tools live, and delete the rest. Low risk, low value —
do it last.

---

## 5. Suggested order

Each step is independently verifiable, so a problem is attributable.

1. Delete the two `*_legacy` resolvers. Run the suites.
2. Delete `routes/migrate.py`. Run the suites. *(The gates in
   `test_staff_login_name_unique.py` already assert nothing imports it and
   nothing calls `/api/migrate/*`; they will keep passing.)*
3. Resolve `owner_bizid` — wire it in or delete it.
4. The four remaining uncalled functions, after a look at
   `create_direct_connection` against the B2B flow.
5. Root-level scripts.

Run the backend suite **and** `frontend-billing` after 1 and 2 at minimum.

---

# 6. Recommendations — making the application solid

These come from what the last two days actually turned up, not from a checklist.
Ordered by how much they would have prevented.

### 6.1 Two copies of one thing is the recurring root cause

Nearly every defect found this week was a duplicated implementation drifting:

* `migrate.py` / `data_transfer.py` — one lost the invoice-number guard, the
  other kept a BizID-overwrite hazard.
* The audit log replicated between two databases carrying ids meaningful in only
  one of them.
* `_apply_pulled_row` had to be *extracted* so the pull loop and the inbox drain
  could not diverge.
* `resolve_parent_fk_uids`'s own docstring states the rule — "single source of
  truth for both apply paths … so the resolution/deferral logic can never drift"
  — and the codebase kept violating it one level up.

**Recommendation:** when a second implementation appears, delete one the same
day, or add a test that asserts they agree. A `SUPERSEDED` comment does not stop
drift; it only records that someone noticed.

### 6.2 Tests must exercise the code that runs

`test_sync_migration_fixes.py` was green against `routes/migrate.py` — an
unmounted module — while the mounted one silently dropped invoices. A test
pointed at dead code is worse than no test: it reports confidence about a path
that cannot execute.

**Recommendation:** a CI check that every module imported by the test suite is
reachable from `main_groq.py`'s router graph, or is explicitly allow-listed.

### 6.3 Application-level uniqueness is not uniqueness (rule 11, again)

`create_staff` correctly refuses duplicate login names. `data_transfer` bypassed
it and created 22. The database now has the index. The same question is worth
asking of every invariant currently enforced only in a command handler:

* invoice numbers — has an index (M-3) ✓
* one open shift per operator — has an index (M-11) ✓
* staff login name per business — **now** has an index ✓
* line-item overfill — has a trigger (M-16/M-17) ✓

> **Correction — I got the fifth one wrong.** My first draft recommended pushing
> `paid_amount <= total_amount` down to a CHECK constraint, citing the M-7
> anomaly in the boot log. That is already considered and deliberately rejected,
> and `core/accounting/db_invariants.py` says so under a heading titled *"WHAT IS
> DELIBERATELY NOT HERE"*:
>
> > The baseline review suggested `CHECK (paid_amount <= total_amount)`. That
> > constraint is **wrong for this product** … an overpayment is a real event — a
> > customer settles a round figure, the excess is booked to Customer Advances
> > … Constraining `paid_amount` would reject that receipt at the counter.
>
> The comment ends "so it is not 'fixed' later by someone reading the older
> review". I read the older review and proposed exactly that. Left in rather than
> quietly deleted, because the failure mode — a reviewer re-proposing a rejected
> constraint because the rejection lived in a file they had not opened — is
> itself worth recording.
>
> The M-7 boot-log entry is therefore **not** a violated invariant. It is one
> invoice whose receipts exceed its total, which may be a genuine overpayment
> that was never booked to advances, or a receipt attached to the wrong invoice.
> The migration is right to flag it for a human rather than constrain it.

### 6.4 Make "absent" and "not looked at" impossible to confuse

Rule 33 keeps re-earning its place. `failed_tables` on the pull exists because a
missing table looked like an empty one. The same confusion appeared in:

* the audit log, where a NULL `record_id` on every INSERT meant "we do not know
  which row" but read as "no row";
* `last_login`, where NULL had to be kept meaning *never used* rather than
  backfilled to `created_at`;
* `_NO_CURSOR`, where `None` could not distinguish "no cursor stored" from "not
  looked up yet".

**Recommendation:** when adding a nullable column or an optional response field,
write down which of the two NULL means. Half the defects here were that question
going unanswered.

### 6.5 Silence is the failure mode, not errors

Not one defect this week raised an exception. They produced: a skipped row, a
0-length list, an acked-but-discarded push, a log line nobody read, a progress
bar that reached 100%. The system is good at reporting *errors* and poor at
reporting *nothing happening*.

**Recommendation:** the Ops & Health console is now the right place for this —
it grew outbox depth, inbox depth, and stuck counts. Anything that currently
ends in `logger.critical(... "needs a human")` should become a number on that
screen instead. There is one such line left in the codebase per the sweep; it
was the pull cursor's give-up branch, and it is gone.

### 6.6 Identity: the rule is written down — keep it enforced

`core/identity.py` now states it once, and boundary comments point at it from
`models.py`, `discovery.py`, `sync.py`, `sync_worker.py`, `log_uploader.py`.
Two gates back it: no synced table may lack `updated_at`, and nothing may import
the deprecated module or call its paths.

**The gap that remains:** nothing structurally prevents a *new* cross-database
surface from carrying an integer. The discovery registry was caught by reading
logs, not by a test. If a third database or a partner integration is ever added,
that class returns.

### 6.7 Data-repair scripts have earned a shared shape

`prune_unused_staff.py`, `clear_staff_bizids.py`,
`repair_line_items_by_invariant.py`, `resolve_duplicate_invoice_numbers.py` and
the rest now follow the same pattern: dry run by default, print every row and
reason, refuse to touch anything a live reference points at, and name the
follow-up. That convention is worth stating in `scripts/README` so the next one
inherits it rather than reinventing it — the version of `prune_unused_staff.py`
I first wrote would have deleted both real tills, because it treated a NULL
`created_at` as "old" instead of "unknown".

---

## 7. What is NOT recommended

* **Do not delete `docs/archive/*`** even though it documents `/api/migrate/*`
  as live. Those are dated handoffs; rewriting an archive to match the present
  destroys the record of why things changed. `docs/plans/HOSTING_MODE_MASTER_PLAN.md`
  was corrected because it is not archived and its endpoint table would send
  someone to a 404.
* **Do not mass-delete the test-only helpers in §3.** They are the seams.
* **Do not "fix" the outbound cloud calls that pass `business_id`.** They use it
  as a local token-store key and identify the business by the token's BizID
  claim. That is the correct pattern; a test pins it so it is not mistaken for
  the bug it superficially resembles.
