# Platform state, BizID spine, and the pending-work ledger
**2026-08-03** · commit `9fed23f` · working tree clean

Follow-up to [`DATA_ARCHITECTURE_OPTIONS_2026-08-01.md`](DATA_ARCHITECTURE_OPTIONS_2026-08-01.md),
[`SYNC_LIVENESS_AUDIT_2026-07-31.md`](SYNC_LIVENESS_AUDIT_2026-07-31.md) and
[`CLEANUP_PLAN_2026-07-31.md`](CLEANUP_PLAN_2026-07-31.md).

---

## 0. What this document is, and what it is not

Three questions were asked and are answered in order:

1. **The BizID spine** — is the "integer ids differ, BizID is common" rule actually
   enforced, or only written down? (§2)
2. **How solid is this as a billing operating system**, rated per dimension. (§3)
3. **What work is still pending that the existing documents do not record.** (§4)

Plus recommendations for the public website. (§5)

### 0.1 Method, and its limits — read this before trusting a number

Everything below is either **read from the code in this repository at `9fed23f`**,
or **measured by a script run during this session**. Where a claim is inferred
rather than measured, it says so. Reproduction commands are in §6.

Two limits, stated up front because the whole hybrid design punishes vagueness
about which side you measured:

* **I did not have access to the production databases.** The audits of 27 Jul –
  01 Aug measured the owner's live desktop install and the Hugging Face Space's
  Postgres. Neither is in this repository. The only database I could read is
  `backend/bizassist.db`, and it is **a development / load-test database**, not
  the production install — it holds `business_id 9999 "Load Test Shop 9999"`
  with 10,000 invoices, and its business ids do not match the ones the earlier
  audits recorded:

  | BizID | id in the 01-Aug audit | id in `backend/bizassist.db` |
  |---|---|---|
  | BA-JABXGD (SaaS Production) | 6 | **126** |
  | BA-Y0DAFT (Brownie Factory) | 7 | **133** |
  | BA-1W9FAA (Chocolate) | 87 | **132** |

  So **§5.1 of the sync audit — the 31 overfilled cloud invoices, the 47
  journal-less cloud documents, the ₹124 double payment — could not be
  re-verified here, and nothing in this document should be read as closing
  them.** They remain open until someone runs the audit scripts against the
  real two databases.

> ### ⚠ CORRECTION — 2026-08-03, later the same day
>
> The paragraph above is **partly wrong and partly still right**, and the
> difference matters.
>
> **Wrong:** I called `backend/bizassist.db` "not the production install". It
> **is** the paired install — four businesses match on BizID (JABXGD, Y0DAFT,
> E3PBH9, 1W9FAA). What misled me was the 10,000 synthetic `Load Test Shop 9999`
> invoices sitting alongside 75 real ones, and the fact that the local integer
> ids had been renumbered since the 01-Aug audit (6/7/11/87 → 126/133/125/132).
> Renumbering is exactly what the BizID spine exists to survive, so I read a
> renumbered pair as an unrelated database.
>
> **Still right, for a different reason:** it is a **stale secondary**. The file
> was last written **2026-07-23**; the live install is on **another laptop** and
> the cloud carries invoices through 30 July. So it was still the wrong database
> to measure — just not the wrong *fleet*.
>
> **What changed as a result:** the cloud items are now **measured**, not open.
> `audit_money_integrity` against Supabase returns 81 issues — 47 journal-less
> documents, 31 line-item overfills, 2 b2b orders, 4 open shifts — and both the
> ₹124 double payment (`LCL-OW-0037`) and the cross-tenant receipt (`e10f6d92`)
> are **already resolved**. The *local* side remains genuinely unmeasured.
>
> Full detail, and the procedure for the correct laptop, in
> [`DATA_REPAIR_STATE_2026-08-03.md`](DATA_REPAIR_STATE_2026-08-03.md).

* **Code claims are verified; data claims are not.** Every statement about what
  the code does was checked by reading it. Every statement about production data
  is quoted from the earlier documents and labelled as such.

### 0.2 Test suites — run in full during this session

| Suite | Result |
|---|---|
| Backend `pytest -n auto` (2,038 collected) | **2,032 passed · 6 skipped · 0 failed** (209 s) |
| `frontend-billing` vitest (52 files) | **392 passed · 1 skipped · 0 failed** |
| `frontend-ai` vitest | **13 passed · 0 failed** |
| `frontend-admin` vitest | **COULD NOT RUN — see §4.3 item C-9** |

The backend suite has grown from the 1,882 recorded on 2026-07-30 to 2,038. The
three runnable suites are fully green. That is a real and unusually good result
for a codebase carrying this much money logic, and it is the main reason the
ratings in §3 are as high as they are.

---

## 1. Executive summary

**The BizID spine is real, correctly designed, and enforced on every path I could
find.** The rule in `core/identity.py` is not aspirational — it is implemented at
both apply paths, at token resolution, and fail-closed on the cloud. §2 walks the
proof.

**As a billing operating system this is strong and unusually well-tested:
overall 7.8 / 10.** Double-entry accounting, idempotency, auditability and test
discipline are at or near best-in-class for an SMB product. The weak dimension is
not billing at all — it is **convergence between the two databases (6.0)**, and
secondarily **the encryption/moat layer that the architecture document specifies
but which does not exist in code (§4.3 C-1 … C-4)**.

**The single most important finding in this document** is that the system's only
continuous divergence detector — the cloud parity sweep — **covers 2 of 25 synced
tables**. `CHILD_SPECS` in `services/sync_worker.py:1220` is exactly
`invoice_line_items` and `invoice_payments`. Phase 4 of the architecture plan
proposes to *sell* the property "Books verified identical to cloud · 0
divergences". The current implementation cannot support that sentence, and
shipping it would be the product asserting the one thing that has repeatedly
turned out to be untrue. (§4.3 C-5.)

---

## 2. The BizID spine — local `business_id` ≠ cloud `business_id`

### 2.1 The rule

From `backend/core/identity.py`, which is the single written statement of it:

> An integer business id is meaningful ONLY inside the database that issued it.
> The BizID (`users.public_id`, "BA-XXXXXX") is the ONLY business identifier that
> may cross a database boundary.

This is correct and it is the right design. A business is a `users` row with
`parent_business_id IS NULL` in **two** databases that assign autoincrement ids
independently. There is no mechanism by which they could agree, and trying to
make them agree would be worse than accepting the difference.

### 2.2 Verified enforcement — four gates, all present

| # | Gate | Location | Verified |
|---|---|---|---|
| 1 | Token → local id resolution refuses an unknown BizID (403) and **forces `require_public_id=True` whenever the dialect is Postgres** | `services/auth.py:224-283` | ✅ read |
| 2 | Push apply re-pins the incoming `business_id` to the receiving database's own id | `routes/sync.py:430-431` | ✅ read |
| 3 | Pull apply re-pins the same way, with the boundary explained at the call site | `services/sync_worker.py:2089-2090` | ✅ read |
| 4 | Cloud sync is refused outright for a business with no BizID | `services/sync_worker.py:2236-2239` | ✅ read |

Gate 1 is the load-bearing one and it is well built. The legacy username/JWT-id
fallback still exists, but it is unreachable on the cloud — `is_cloud` sets
`require_public_id = True` before any fallback is considered, so a token without
a `public_id` claim gets a 403 rather than a guessed tenant. On the local SQLite
side the fallback is retained deliberately for legacy tokens, where every id is
local anyway and the failure mode does not exist.

**Verdict on the spine itself: solid.** I could not find a path on which a
foreign integer is written as a tenant.

### 2.3 Where the spine holds but the *relationships underneath it* do not

The spine answers "which tenant is this row?". It does not answer "does this
row's parent belong to the same tenant?" — that is what `TENANT_FKS` in
`core/accounting/db_invariants.py` was added for on 01 Aug.

I enumerated every foreign key on every synced table and compared it against the
13 declared rules. **Measured, not estimated** (script in §6.1):

```
MODEL_MAP tables: 28    TENANT_FKS declared: 13
FKs whose parent is tenant-scoped:        27
  guarded by a declared TenantFK:         13
  UNGUARDED:                              14
```

The 14 unguarded ones split into two very different groups:

**Group A — 5 that could be declared today, no schema change needed.** The child
already carries `business_id`; the rule was simply not written:

```
invoices.parent_invoice_id           -> invoices
invoices.shift_id                    -> register_shifts
payments.shift_id                    -> register_shifts
invoice_payments.shift_id            -> register_shifts
purchase_invoices.parent_invoice_id  -> purchase_invoices
```

`invoice_payments.shift_id` is the notable omission: `shift_cash_movements.shift_id`
**is** guarded, with the reason recorded as *"a drawer that does not reconcile is
a cashier accused"* — and `invoice_payments` feeds the same drawer tally.

**Group B — 9 that cannot be guarded as the schema stands.** The child is a
line-item table with no `business_id` column, so a composite `(id, business_id)`
FK is structurally impossible:

```
invoice_line_items.invoice_id / .product_id
purchase_invoice_line_items.purchase_invoice_id / .product_id
purchase_order_line_items.purchase_order_id / .product_id
stock_transfer_line_items.transfer_id / .product_id
b2b_order_line_items.product_id
```

### 2.4 The residual hole, and why it is latent rather than live

There is one complete, unbroken chain by which a line item could attach to
another tenant's invoice. All three controls miss the same case:

1. `services/sync_worker.py:2105` calls `resolve_parent_fk_uids(...)` **without
   `business_id=`**, unlike the push path at `routes/sync.py:593-594` which
   passes it. So on the pull path the uid-based parent lookup runs without the
   `AND business_id = :business_id` clause (`database/sync_map.py:286`).
2. For a line-item table the raw-FK fallback is also unscoped, because it derives
   the owner from `data.get("business_id")` (`sync_map.py:322`) and a line item
   has no such column.
3. No `TenantFK` covers it (Group B above).

**But it is latent, not live, and the reason is measurable.** The raw-FK fallback
only fires when the payload carries no parent uid, and `_serialize_orm_obj`
(`database/models.py:1129`) omits the uid only when the parent's own `uid` is
NULL. Across every synced table in `backend/bizassist.db`:

```
TOTAL rows with NULL/empty uid: 0
```

Zero. Including 20,170 `invoice_line_items`, 10,075 `invoices` and 4,935
`invoice_payments`. So the uid path always wins today and the unscoped fallback
is genuinely a backstop.

**The fix is one keyword** and it removes the asymmetry rather than relying on a
data property staying true:

```python
# services/sync_worker.py:2105
if resolve_parent_fk_uids(db, model_cls, data,
                          business_id=business_id,          # ← add this
                          log_prefix="[SYNC_WORKER]"):
```

Both apply paths are then scoped identically, which is the rule
`resolve_parent_fk_uids` states about itself in its own docstring.

> ### ✅ APPLIED 2026-08-03
>
> Both apply paths are now scoped identically. Full backend suite after the
> change: **2,032 passed · 6 skipped · 0 failed** — unchanged from baseline.
>
> **One risk was checked before applying, and it is worth recording.**
> `b2b_order_line_items.product_id → products` is `NOT NULL` and points at a
> **cross-tenant** product: a buyer mirrors a B2B order whose product belongs to
> the *seller*. Scoping the lookup could in principle have deferred those rows
> for ever.
>
> It does not, because the buyer's local database never held those products in
> the first place — `get_supplier_catalog` (`core/order/service.py:87-90`)
> queries `Product.business_id == seller_business_id` and runs **on the cloud**,
> where both tenants exist. Those line items already deferred on the buyer side
> before this change; on the seller side the product is their own and resolves
> either way. Verified by `test_b2b_transfer.py`,
> `test_b2b_transfer_internals.py`, `test_line_item_invariant.py` and
> `test_pull_partial.py` — 149 tests green.
>
> **Residual uncertainty, stated rather than papered over:** if a future feature
> ever mirrors a seller's catalogue into the buyer's local database, that FK
> becomes a genuine cross-tenant reference and this scoping will defer it. The
> correct fix at that point is a per-table exemption, not removing the guard.

### 2.5 Sync registration symmetry — clean

The "three registrations" trap (`MODEL_MAP`, `_SYNC_TABLES`,
`APPEND_ONLY_DELETE_BLOCKLIST`) that the architecture doc warns about is
currently **not** violated:

```
MODEL_MAP (apply/pull): 28     _SYNC_TABLES (push gate): 25
In MODEL_MAP but not push-gated:  b2b_connections, b2b_orders,
                                  b2b_order_line_items  — all 3 declared PULL_ONLY ✅
In _SYNC_TABLES but not MODEL_MAP: (none) ✅
```

Every asymmetry is declared and intentional.

---

## 3. How solid is this as a billing operating system

Rated against what a billing/accounting OS actually has to guarantee. Each score
carries the evidence it rests on and the specific thing holding it below 10.

| # | Dimension | Rating | Holding it back |
|---|---|---|---|
| 1 | Double-entry accounting integrity | **9.0** | 47 journal-less cloud documents still open (unverified here) |
| 2 | Idempotency & replay safety | **9.0** | Rejected rows are acked by design — exit criterion 4 unmet |
| 3 | Auditability & tamper evidence | **8.5** | Hash chain is per-database; no cross-database attestation |
| 4 | Offline-first billing | **9.0** | Local SQLite is **plaintext** — no SQLCipher |
| 5 | Stock & inventory | **8.5** | `stock_transfer_line_items` in the Group-B tenant gap |
| 6 | Multi-tenant isolation | **7.5** | 14 unguarded FKs; tenant FK never exercised on Postgres in CI |
| 7 | Testing & CI discipline | **8.5** | `frontend-admin` never run; sync suites not run on Postgres |
| 8 | Observability / ops console | **8.0** | Parity result is not surfaced as a headline number |
| 9 | Security & auth | **7.5** | No field encryption, no Ed25519 signing, no SQLCipher |
| 10 | GST / statutory compliance | **7.0** | Payload generation only — no IRP or e-way API integration |
| 11 | **Cloud ↔ local convergence** | **6.0** | **No row tombstones; parity covers 2 of 25 tables** |
| 12 | Code hygiene | **6.5** | 4 orphan route modules + 19 orphan frontend files still present |

### Overall: **7.8 / 10**

**What genuinely impressed me, with evidence:**

* **The accounting core is not a CRUD app wearing accounting vocabulary.**
  `core/accounting/posting.py` maintains a real SHA-256 hash chain
  (`prev_hash`/`GENESIS`), `db_invariants.py` pushes money rules down to
  Postgres `CHECK` constraints and SQLite triggers so *no* code path can bypass
  them, and `period_locks` replicate as append-only events rather than mutable
  state. 25 report endpoints including GSTR-1 B2B/B2CS/HSN, GSTR-3B, trial
  balance, balance sheet, general ledger and `verify-chain`.
* **The rejected `CHECK (paid_amount <= total_amount)` is the single clearest
  sign of engineering maturity in the repository.** The constraint is refused,
  in writing, because overpayment is a real counter event that must be
  recordable. That is domain judgement, not checklist compliance — and when a
  later reviewer re-proposed it, the rejection was found and the re-proposal
  recorded as the failure mode rather than quietly deleted.
* **CI runs money suites on real Postgres**, not just SQLite: `.github/workflows/ci.yml`
  spins up `postgres:15` and re-runs 10 money-layer suites against it as a
  cross-dialect drift guard, plus a flaky-guard job that runs the sync/relay
  modules 10× in fixed and randomised order.
* **The documentation practice is exceptional.** Multiple documents contain
  signed corrections of their own earlier claims — "I measured the wrong
  database", "I overstated this finding's blast radius", "one outage traded for
  another". Documents that correct themselves are rarer and more valuable than
  documents that are right the first time.

**The honest counterweight:** almost every score above 8 is about **one
database**. Score 11 is what happens **between two**, and it is where every
serious incident in the last fortnight originated. The gap between 9.0 on
accounting integrity and 6.0 on convergence *is* the product risk.

---

## 4. Pending work

Three groups: what the documents say is pending and still is (§4.1), what the
documents say is pending but is actually **done** (§4.2), and what is pending and
**appears in no document** (§4.3).

### 4.1 Documented and still open — confirmed by reading the code

| ID | Item | Source | Verified state |
|---|---|---|---|
| A-1 | **`sync_tombstones` table** — deletes never propagate | DATA_ARCH Phase 1 | **Open.** No such table. `sync_queue` shows `INSERT 44 · UPDATE 91 · DELETE 0`. See the important refinement in §4.4. |
| A-2 | Apply resolves parents **by uid only**; delete every integer fallback | DATA_ARCH Phase 1 | **Open.** Integer fallbacks remain at `routes/sync.py:450-451` and `:460`, and the raw-FK path at `sync_map.py:305-382`. Now *safe to remove* — 0 rows have a NULL uid (§2.4). |
| A-3 | Fold `audit_payment_attachment` into the parity sweep; add a `wrong_tenant` key | DATA_ARCH Phase 2 | **Partly done.** `wrong_invoice`, `cloud_only`, `cloud_only_withheld`, `over_paid` exist; **`wrong_tenant` does not** (`sync_worker.py:1185-1194`). |
| A-4 | Written contract: no money row may differ in tenant/parent/amount; divergence detected within N minutes | DATA_ARCH Phase 2 | **Open.** Not written anywhere. |
| A-5 | Ops panel: "Books verified identical to cloud · 0 divergences · 4 min ago" | DATA_ARCH Phase 4 | **Open — and see C-5 before building it.** |
| A-6 | Option E spike (PowerSync / ElectricSQL / Turso), timeboxed 1 week | DATA_ARCH Phase 5 | **Not started.** |
| A-7 | Repair `e10f6d92` and `6326fb2a` on the cloud; run §7b.7 runbook | SYNC_AUDIT §7b.7 | **Unknown — could not verify.** Needs the real databases (§0.1). |
| A-8 | 8 invoices with no customer link (4 relinkable, 4 need a human) | CLEANUP §0a-1 | **Unknown — could not verify.** Production data. |
| A-9 | 59 sync conflicts awaiting owner review | CLEANUP §0a-3 | **Unknown — could not verify.** Production data. |
| A-10 | Delete the 4 orphan route modules + 19 orphan frontend files | CLEANUP §1, §1b, §1c | **Open.** All still present: `routes/{migrate,insights,smart_insights,sales}.py`; `pages/B2BNetwork.jsx` (599 L), `pages/B2BOrders.jsx` (697 L), `components/b2b/CatalogOrderModal.jsx` (215 L), `pages/Staff.jsx` (379 L), `components/Money.jsx`, `api/b2bClient.js`. |
| A-11 | Root-level ad-hoc scripts (`check_db.py`, `debug_*.py`, `repair_line_items.py`) | CLEANUP §4 | **Open.** All still at repo root. |
| A-12 | `create_direct_connection` — decide against the B2B flow | CLEANUP §2 | **Open.** Still defined, still 0 callers outside its definition. |
| A-13 | Promote `register_shifts` to `FINANCIAL_ENTITIES` (policy call) | SYNC_AUDIT §5.3 | **Open.** Deliberately left to the owner. |

### 4.2 Documented as pending, but actually **done** — update the docs

Correcting these matters: a stale open item costs the next reader the same
investigation twice.

| ID | Item | Recorded as | Actual state |
|---|---|---|---|
| B-1 | Push returns outcomes; `synced_at` only on applied | DATA_ARCH Phase 1, open | **Done.** `PushOutcome` + `should_hold()` (`sync_worker.py:288-347`, applied at `:2511-2527`) keeps deferred *and* unaccounted rows queued, and **fails closed** when the arithmetic `received == applied + deferred + skipped` does not close. |
| B-2 | `_resolve_owner_id_legacy` / `_resolve_business_id_by_username_legacy` | CLEANUP §2, open | **Done.** Both deleted; only the explanatory NOTE remains. |
| B-3 | `owner_bizid` — wire in or delete | CLEANUP §2, open | **Done.** Deleted 2026-07-31 with the reasoning kept in place. |
| B-4 | Stale `.git/index.lock` | CLEANUP §0a-5, open | **Done.** No lock file. |
| B-5 | `frontend-admin` test **dependencies** | CLEANUP §0a-4, open | **Half done — see C-9.** `package.json` + `package-lock.json` now declare vitest/jsdom/testing-library, and `vite.config.js` has the `test` block. They are **not installed**, so the test has still never run. |

### 4.3 Pending, and in **no** document — new findings from this session

These are the answer to "what are we missing that isn't written down".

---

**C-1 · SQLCipher is specified but does not exist. The local database is plaintext.**
`ARCHITECTURE.md` §2.8 and §6 both name SQLCipher as the at-rest control for the
offline cache, with the rationale *"a stolen laptop ≠ a plaintext price book"*.
Grep across the backend and both requirements files returns **zero** references
to sqlcipher/pysqlcipher. The local SQLite file holds complete customer records,
every invoice, every payment and the full price book, unencrypted. For a product
sold to Indian retail counters on Windows machines, this is the largest
unrecorded gap in the security story.
**Severity: HIGH.** *Effort: medium — SQLCipher on Windows is a real packaging
task, and key custody has to be designed before it is worth starting.*

---

**C-2 · Ed25519 transaction signing does not exist.**
`ARCHITECTURE.md` §2.8 and §5 specify a per-business Ed25519 keypair, the public
key published on the BizID, and buyer-side signature verification — described in
the document as *"the differentiator … a real moat, not a checkbox"* and the
basis of the dispute-resolution story. No `nacl` / `PyNaCl` / `ed25519` anywhere
in the tree; `bcrypt` is the only crypto dependency. The SHA-256 hash chain **is**
built and works, but it proves *"this database's history is internally
unaltered"*, not *"this invoice came from that business"*. Those are different
claims and only the second one is a moat.
**Severity: MEDIUM (strategic, not operational).**

---

**C-3 · No field-level encryption for the crown-jewel columns.**
`ARCHITECTURE.md` §2.8 specifies `pgcrypto` / AES-256-GCM for GSTIN, phone, UPI
and KYC. No `pgcrypto`, no AES, no `encrypt(` in `core/` or `services/`. Postgres
storage encryption and RLS are in place, so this is defence-in-depth rather than
an open door — but it is specified and absent.
**Severity: LOW-MEDIUM.**

---

**C-4 · There is no single `SharingSerializer`.**
`ARCHITECTURE.md` §4 specifies **one** server-side gate that every cross-business
endpoint must pass through, on the explicit grounds that *"no endpoint hand-rolls
this"*. What exists is the *policy data* — `price_tier`, `stock_visibility`
(`exact|band|hidden`), `discount_pct`, `credit_limit` on `B2BConnection` — and
enforcement in **one** place, `core/order/service.py:153-155`, inside
`get_supplier_catalog`. That single site is correct. But the architectural
property being claimed is "provably leak-proof because there is one gate", and
one *call site* is not one *gate*: the next cross-business endpoint has nothing
forcing it through. This is the "two copies of one thing" root cause from
CLEANUP §6.1, in advance of the second copy existing.
**Severity: MEDIUM.** *Effort: low if done now, high after the third endpoint.*

---

**C-5 · The parity sweep covers 2 of 25 synced tables. ⚠ Most important item here.**
`services/sync_worker.py:1220`:

```python
CHILD_SPECS = [
    ("invoice_line_items", "invoice_id", "invoices", "invoice_id_uid"),
    ("invoice_payments",   "invoice_id", "invoices", "invoice_id_uid"),
]
```

Plus a paid-state and over-payment check on `invoices`. **Nothing else is
compared, in either direction.** Not `products`, `customers`, `vendors`,
`inventory`, `stock_ledger`, `expenses`, `godowns`, `purchase_invoices` and their
line items, `stock_transfers`, `register_shifts`, `shift_cash_movements`, or the
b2b tables. A whole **invoice** present on one side and absent on the other is
not detected as missing — only its children are.

This matters more than its size suggests, for three reasons:

1. The sweep is the **only** continuous cross-database check that exists. Boot-time
   checks fire once, into a log, on a Space that restarts rarely — the sync audit
   makes exactly that point about the M-7 check.
2. Its summary already reports `wrong_invoice: 0 · missing: 0 · cloud_only: 0`,
   which reads as *"the databases agree"* and means *"these two child tables
   agree"*. That is the rule-33 confusion — absent vs not-looked-at — in the one
   component whose entire job is to distinguish them.
3. **Phase 4 proposes to put this on screen and sell it**: *"Books verified
   identical to cloud · 0 divergences · 4 min ago"*. On the current
   implementation that sentence would be false for 23 of 25 tables.

**Recommendation: do not build A-5 until C-5 is closed.** Selling an unverified
property is strictly worse than not advertising a verified one. When it is built,
the panel must print its denominator — *"14 of 25 tables compared"* — which is
CLEANUP §6.4's own rule applied to itself.
**Severity: HIGH.**

---

**C-6 · A local bulk delete silently and permanently diverges the two databases.**
`routes/upload.py:427-437`, `DELETE /upload/{file_id}?cascade=true`:

```python
deleted_all = db.query(Invoice).filter(Invoice.business_id == active_user_id).delete()
```

`Query.delete()` is a **bulk** delete. It does not emit `Mapper.after_delete`, so
`_queue_change` never runs and nothing is queued. Every invoice for that business
disappears locally and **all of them remain on the cloud, for ever**. The same
shape applies to `Inventory` and `LegacyPayment` on the adjacent branches, and to
the `services/admin_service.py:897-948` purge block.

The system then behaves *correctly and unhelpfully*: the cloud-only scan sees
them, `_cloud_only_row_fits` withholds them (their invoice does not exist
locally), and the divergence is logged as withheld on every sweep, indefinitely.

This is the same class as the raw-SQL repair scripts that motivated A-1, but it
is reachable **from the product UI** rather than from a maintenance script — and
that is what makes it worth separating from A-1. It is also the strongest
argument for tombstones that the codebase contains.
**Severity: MEDIUM-HIGH.**

---

**C-7 · An append-only DELETE reaching the outbox would 422 the entire push, for ever.**
`routes/sync.py:370-383` raises `HTTPException(422)` for the **whole batch** if
any change is a DELETE on an `APPEND_ONLY_DELETE_BLOCKLIST` entity. The worker
treats any non-200 as a raised exception (`sync_worker.py:2350-2351`), so the
chunk is not acked and is retried unchanged on the next cycle — a permanent
poison pill that stalls **all** sync for that business, including every unrelated
sale behind it.

**Currently unreachable, and only by luck.** Every local delete of a blocklisted
entity found in the tree goes through bulk `Query.delete()` (C-6) or raw SQL,
neither of which fires the ORM event. The day someone writes
`db.delete(invoice)` — the obvious, natural spelling — sync stops for that
business and the log says `422`.

The fix is small and matches how every other bad row is already handled: reject
the offending **rows** into `rejected[]` rather than raising for the batch. The
module already establishes that principle two hundred lines further down —
*"the ack STAYS: refusing it would stall the outbox behind a row that can never
apply"*.
**Severity: MEDIUM (latent), HIGH (if it fires).**

---

**C-8 · The tenant FK work — the centrepiece of `feb0c5f` — is never exercised on Postgres in CI.**
`.github/workflows/ci.yml` already runs a `postgres:15` service and already
re-runs 10 money suites against it. `tests/test_tenant_fk_invariants.py` is **not**
in that list, nor are `test_migration_ddl_is_portable.py`,
`test_migration_step_isolation.py`, `test_sync_inbox.py`,
`test_parity_is_bidirectional.py` or the other ~20 sync suites.

This is exactly the shape of finding 17 (the `DATETIME` column that crash-looped
the Space): SQLite accepts almost anything, so a SQLite-only pass proves very
little about the cloud. `ensure_tenant_fks` emits **different DDL per dialect** —
composite FOREIGN KEYs on Postgres, BEFORE-triggers on SQLite — and only the
SQLite half has ever run in CI. Exit criterion 2 of the architecture document is
*"`ensure_tenant_fks` reports every rule installed on **both** databases"*.

**This is the cheapest high-value item in this document**: the Postgres service is
already running in that job. Adding the file names to the existing step is a
few-line change.
**Severity: MEDIUM. Effort: trivial.**

> ### ✅ APPLIED 2026-08-03
>
> New step *Run Sync & Tenant Suites on Postgres (finding-17 class guard)* in
> `.github/workflows/ci.yml`, covering 14 suites: tenant FKs, DB invariants,
> both migration suites, the portability gate, and the sync/parity/tenancy set.
> YAML validated; the same selection passes on SQLite (**276 tests**).
>
> **The Postgres run is still unverified** — no `docker` and no `psql` in this
> session. The first CI run is the verification and **may go red**. That is the
> finding, not a regression: it would be the first time this code has executed
> on the engine the cloud runs. `continue-on-error` was deliberately **not**
> added — see the comment in the step.

---

**C-9 · `frontend-admin` test dependencies are declared but not installed.**
CLEANUP §0a-4 recorded this as needing "a dependency decision". The decision was
made — `feb0c5f` added vitest, jsdom and `@testing-library/*` to `package.json`
and updated `package-lock.json` (both verified present in the lockfile). But
`frontend-admin/node_modules/vitest` **does not exist**, so `npm ci` was never
run and `src/__tests__/Chat.components.test.jsx` has still never executed.
`frontend-admin` is also absent from the CI `frontend-tests` job, which covers
only `frontend-billing` and `frontend-ai`.
**Severity: LOW. Effort: `npm ci` + 6 lines of CI.**

---

**C-10 · The SQL portability gate protects 8 hard-coded files and nothing else.**
`tests/test_dbcompat_and_sql_portability.py:627` is a literal list of 8 script
paths. Anything outside it is unchecked, including all of `services/` and
`routes/`. One example already exists: `services/sync_worker.py:1478-1481` issues
`INSERT OR IGNORE INTO sync_queue`, which is SQLite-only syntax and a hard error
on Postgres.

**Not a live bug** — `run_cloud_parity_sweep` returns immediately unless
`engine.dialect.name == "sqlite"` (`sync_worker.py:781`), so it never executes on
the cloud. But it is the identical latent shape to finding 17, sitting in the
module the last three audits were about, and the gate that exists to catch it
does not look there.
**Severity: LOW (latent). Fix: make the gate walk a directory, not a list.**

---

**C-11 · Exit criterion 4 contradicts a deliberate design decision.**
The architecture document's exit criterion 4 is *"No row is marked `synced_at`
that is absent on the far side."* But `routes/sync.py:753` acks rejected rows on
purpose — `processed_count += 1  # ack either way` — with the reasoning recorded
directly above it: refusing would stall the outbox behind a row that can never
apply. A rejected row therefore **is** marked `synced_at` while absent on the
cloud, by design, and is reported to the device in `rejected[]` and logged at
ERROR.

The design decision is right. The exit criterion needs rewording, otherwise it
can never be signed off:

> No row is marked `synced_at` that is absent on the far side **and unreported**.
> Rejected rows are acked by design and must appear in `rejected[]`, in the
> ConflictLog, and on the Ops console.

**Severity: LOW (documentation), but it blocks sign-off.**

---

**C-12 · 11 staff rows hold a BizID in the development database.**
`CLEANUP` records *"all 32 stray BizIDs cleared"* and the sync audit's §5.1 table
shows LOCAL = 0. In `backend/bizassist.db` the count is **11**. This is almost
certainly because `clear_staff_bizids.py` was run against the production install
and not this one — and per §0.1 this database is a load-test copy, so **this is
not evidence that production regressed**. Recorded for one reason only: it shows
the repair has to be run per-database, which is A-1's argument restated. Note
also that `clear_staff_bizids.py` still has no `--db` flag and so cannot be
pointed at the cloud at all (SYNC_AUDIT §7b.7 says the same).
**Severity: LOW.**

---

**C-13 · The cloud token store is only gitignored at one path, and it is CWD-relative.**
`services/sync_worker.py:409`:

```python
_TOKEN_FILE = _Path("cloud_sync_tokens.json")     # CWD-relative
```

The comment above it is explicit: *"File lives in CWD: the app-data dir
(packaged) / backend/ (dev)."* But `.gitignore:14` ignores exactly one path:

```
backend/cloud_sync_tokens.json
```

So the file is protected **only** when the process happens to run with
`cwd == backend/`. Any backend module imported from the repository root — which
is how several of the audit and repair scripts get invoked — writes
`./cloud_sync_tokens.json` at the root, where it is **not ignored** and is one
`git add -A` away from committing live cloud bearer JWTs.

**This is not hypothetical: I reproduced it accidentally during this session.**
Running the FK-coverage script from the repo root created a root-level
`cloud_sync_tokens.json`, and `git status` listed it as untracked rather than
ignored. In my case the map was empty (`{}`, 2 bytes) and I deleted it; on the
owner's machine, with a provisioned device, it would not have been empty.

There is a second, quieter consequence: because `_load_token_map()` is
CWD-relative too, a script run from the wrong directory reads an **empty** token
map and reports *"no cloud token — skipping"* rather than "wrong directory".
That is rule 33 again — unreadable presented as absent — on the exact scripts the
cloud repair runbook depends on.

*Fix, in order of value:*
1. `.gitignore` — replace the anchored path with a bare `cloud_sync_tokens.json`
   so it matches at any depth. One line, do it now.
2. Resolve `_TOKEN_FILE` against an explicit app-data / backend path rather than
   CWD, so the file has one location instead of one per invocation directory.
3. Have the scripts state which token file they read and whether it existed.

**Severity: MEDIUM (a credential can reach a commit). Effort: item 1 is one line.**

> ### ✅ APPLIED 2026-08-03 — item 1 only
>
> `.gitignore` now carries a bare `cloud_sync_tokens.json` (was
> `backend/cloud_sync_tokens.json`), with the reason recorded inline.
> Verified by reproducing the original condition: `git check-ignore` now matches
> **both** `cloud_sync_tokens.json` and `backend/cloud_sync_tokens.json` from the
> single rule, and `git status` no longer lists a root-level token file.
>
> **Items 2 and 3 remain open** — `_TOKEN_FILE` is still CWD-relative
> (`sync_worker.py:409`), so the file still has one location per invocation
> directory, and a script run from the wrong directory still reads an *empty*
> token map and reports "no cloud token" rather than "wrong directory". The
> credential-exposure half is closed; the rule-33 half is not.

---

### 4.4 An important refinement to A-1 (tombstones)

The architecture document says the two databases are *"structurally guaranteed to
diverge over time"* because `DELETE` has never been recorded. That is true as an
observation but the mechanism is narrower than it reads, and the distinction
changes what needs building:

* **12 tables refuse DELETE by design** (`APPEND_ONLY_DELETE_BLOCKLIST`) —
  invoices, all line items, payments, expenses, stock ledger, b2b ledgers, period
  locks. For these, non-propagation is **correct**: a reversal is a new row, not
  a deletion. Tombstones are *not* wanted here, and adding them would be a bug.
* **13 tables would propagate a DELETE** if the ORM event fired: `customers`,
  `products`, `vendors`, `godowns`, `inventory`, `product_barcodes`,
  `business_settings`, `alert_configs`, `rate_limit_configs`, `register_shifts`,
  `shift_cash_movements`, `stock_transfers`, `stock_transfer_line_items`. The
  machinery exists and works; it has simply never fired, because every deletion
  in the tree is either a bulk `Query.delete()` (C-6) or raw SQL.
* **The pull direction has no delete channel at all.** A row deleted on the cloud
  is invisible to the local install, because pull only ever sends rows that
  exist. This half is unconditionally missing and is the strongest argument for
  the table.

**So the tombstone requirement is: master data + repair-script deletions +
cloud→local propagation.** Scoping it that way makes it a genuine day of work, as
the architecture document estimates, rather than a redesign of the money path.

---

## 5. Recommendations for the website

`bizassist-landing` is a 437-line single-page React/Vite/Tailwind app, version
1.1.5. The copy and visual design are good — the positioning ("Billing at the
speed of your counter", "Power cut the internet, not your counter") is sharp and
the feature framing is honest. What is missing is almost entirely
**infrastructure**, and most of it is cheap.

### 5.1 Fix first — these are defects, not enhancements

**W-1 · The download buttons depend on an unauthenticated GitHub API call.**
`src/useLatestRelease.js:12` fetches `api.github.com/repos/.../releases/latest`
from the browser with no token. Unauthenticated GitHub API is rate-limited to
**60 requests per hour per IP**. Shared office IPs, mobile carrier NAT, or any
traffic spike will exhaust it, and `.catch(() => {})` then silently degrades every
visitor to the generic releases page. **The download button is the only
conversion event on the site and it is rate-limited by a third party.**
*Fix:* resolve the release at build time, or cache it in a tiny serverless
function / edge KV with a 10-minute TTL. Keep the client fetch as the fallback,
not the primary.

**W-2 · There is no `public/` directory at all** — no `robots.txt`, no
`sitemap.xml`, no `favicon.ico`, no `og:image`. A social share of this URL renders
a bare text card today.

**W-3 · Missing meta.** Present: `description`, `og:title`, `og:description`,
`og:type`. Missing: `og:image`, `og:url`, `twitter:card`, `twitter:image`,
`canonical`, `theme-color`, `lang` variants. Add JSON-LD
`SoftwareApplication` with `offers`, `operatingSystem` and
`aggregateRating` — for a downloadable app this is what produces a rich result.

**W-4 · Google Fonts is loaded from a third-party origin** (`index.html:16-19`),
render-blocking on first paint and a GDPR/DPDP consideration. Self-host Inter as
woff2 with `font-display: swap`. On the connections these shops actually have,
this is a visible improvement.

### 5.2 Content the site needs to convert a shop owner

**W-5 · A pricing page.** There is none. The app has plan gating (`sync_business`
returns 402 without Pro), so a paid tier exists and is invisible to a visitor.

**W-6 · A trust / security page — and this is the biggest opportunity.**
The single strongest differentiator this product has is one no competitor can
easily claim, and the site does not mention it: **the books are verifiable.**
SHA-256 hash-chained journal entries, a `verify-chain` endpoint, database-level
money constraints, append-only ledgers, per-tenant RLS. "Your books can prove
they were not altered" is a page, and it is the page a serious retailer or their
CA reads before switching.
*Caveat, and it matters:* write it against what is **built** (hash chain, DB
constraints, RLS, offline-first), not against `ARCHITECTURE.md`'s roadmap. Do not
claim encrypted-at-rest local storage until C-1 ships, and do not claim signed
invoices until C-2 does.

**W-7 · Do not put "verified identical to cloud" on the site until C-5 is
closed.** The same rule as A-5, for the same reason.

**W-8 · A public changelog.** The release workflow already publishes GitHub
Releases; render them. "Silent auto-updates" is a headline feature and a visible
changelog is what makes it credible rather than unnerving.

**W-9 · Docs / help.** `docs/USER_GUIDE.md` exists in the repo. A static docs
route is the cheapest long-tail SEO this project can buy — every "how to file
GSTR-1 from …" query is a shop owner with intent.

### 5.3 Measurement

**W-10 · There is no analytics of any kind.** Ship privacy-friendly analytics
(Plausible/Umami) and instrument one funnel: *page view → download click →
first launch*. Without it, every one of the recommendations above is unfalsifiable.

### 5.4 Suggested order

| Order | Item | Effort | Why first |
|---|---|---|---|
| 1 | W-1 rate-limited downloads | S | It breaks conversion under exactly the traffic you want |
| 2 | W-2 + W-3 SEO/social assets | S | Blocks every share and every crawl |
| 3 | W-10 analytics | S | Nothing after this is measurable without it |
| 4 | W-6 trust page | M | The differentiator, currently unstated |
| 5 | W-5 pricing | M | A paid tier exists and is invisible |
| 6 | W-4 self-host fonts | S | Perf + privacy |
| 7 | W-8 changelog, W-9 docs | M | Compounding SEO |

---

## 6. Reproducing every measurement in this document

### 6.1 Tenant-FK coverage (§2.3)

```python
# from repo root, with backend/ on sys.path
from database.sync_map import MODEL_MAP
from core.accounting.db_invariants import TENANT_FKS
declared = {(t.child, t.fk_column) for t in TENANT_FKS}
for table, model in MODEL_MAP.items():
    for fk in model.__table__.foreign_keys:
        parent_cols = {c.name for c in fk.column.table.columns}
        if "business_id" in parent_cols and (table, fk.parent.name) not in declared:
            print(f"UNGUARDED {table}.{fk.parent.name} -> {fk.column.table.name}")
```

### 6.2 NULL-uid audit (§2.4) and sync_queue operations (§4.1 A-1)

```bash
python - <<'PY'
import sqlite3
c = sqlite3.connect("backend/bizassist.db").cursor()
for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'"):
    cols = {r[1] for r in c.execute(f'PRAGMA table_info("{t}")')}
    if "uid" in cols:
        n = c.execute(f'SELECT COUNT(*) FROM "{t}" WHERE uid IS NULL OR uid=""').fetchone()[0]
        if n: print(t, n)
print(list(c.execute("SELECT operation, COUNT(*) FROM sync_queue GROUP BY operation")))
PY
```

### 6.3 Test suites (§0.2)

```bash
python -m pytest backend/tests -q -n auto
```

```bash
cd frontend-billing && ./node_modules/.bin/vitest run
```

> Use the **local** binary. `npx vitest` resolves a newer global vitest whose
> rolldown dependency requires Node ≥ 20.19 and fails at startup on Node 21.1.

### 6.4 Parity coverage (§4.3 C-5)

```bash
grep -n "CHILD_SPECS" -A 6 backend/services/sync_worker.py
```

---

## 7. Position

The engineering here is better than the open-item list makes it look. 2,032
backend tests green, money invariants pushed down to the database, a hash-chained
ledger, real Postgres in CI, and a documentation culture that corrects itself in
writing — that is a genuinely well-built system, and the BizID spine specifically
is designed and enforced correctly.

The risk is concentrated in one place and it has not moved: **the system still
cannot state, or check, that the two databases agree.** §4.3 C-5 is that sentence
measured — the only continuous checker covers 8% of the synced tables. Every
other convergence item (A-1 tombstones, C-6 bulk deletes, C-7 the poison pill)
feeds the same gap from a different direction.

**Do this one before anything else**, because it is one line and it protects a
credential: **C-13** — change `.gitignore:14` from `backend/cloud_sync_tokens.json`
to a bare `cloud_sync_tokens.json`. The token store is CWD-relative, so today it
is only ignored when a process happens to run from `backend/`.

Then, if only three things are done from this document:

1. **C-5** — widen parity coverage, and make it print its denominator.
2. **C-8** — add the sync and tenant-FK suites to the Postgres CI step that
   already exists. Hours of work against the class of bug that took the cloud
   down.
3. **C-1** — decide, in writing, whether the local database is encrypted. It is
   currently plaintext and the architecture document says it is not.

And one thing **not** to do: do not ship A-5 / W-7 — the "books verified
identical" claim — until C-5 is closed. The whole value of that panel is that it
is true.
