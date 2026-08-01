# Data architecture — the two-database problem

**Date:** 2026-08-01
**Status:** decision document, awaiting owner sign-off
**Scope:** the local SQLite ↔ cloud Postgres split, and what to do about it
**Author's note:** every number in §2 was measured on the databases themselves during
the 2026-08-01 session. Where something is inferred rather than measured it is
labelled. Where it is a vendor claim I have not verified, it says so.

---

## 1. Why this document exists

The product's selling point is that a shop can bill offline on the desktop and
have the same books in the cloud. That is not a feature of the application, it
is a **claim about two databases agreeing**. On 2026-08-01 that claim was false
in three different ways at once, and every dashboard read green.

Repairing the rows does not address this. A repair fixes an instance; the
question is what stops the class.

---

## 2. What was measured

### 2.1 A receipt on another tenant's books

```
uid e10f6d92-e55a-4b49-9fcb-b4679bdc56dd    ₹45.00 cash, 2026-07-06
  local : invoice 457, business 8  (BA-W9J21Y)  total  45.00   → settles it exactly
  cloud : invoice 786, business 7  (BA-JABXGD)  total 424.00   → overpays by 45.00
```

One receipt. Two tenants' invoices. Both databases audited **clean** —
`audit_money_integrity` sections A (mis-attached) and D2 (cross-tenant) returned
0 on each side, correctly, because the cloud row carries `business_id = 7`
matching the invoice it hangs off. It is self-consistent on arrival.

Structural cause, measured:

```
invoice_payments.invoice_id  →  invoices.id       tenant is NOT part of the FK
invoices  UNIQUE (business_id, invoice_id)        invoice numbers unique PER business
```

`LCL-OW-0003` names a different document in every tenant. Anything resolving a
parent by number rather than by `uid` can land in the wrong one. The same shape
exists on **13 foreign keys** across the schema.

### 2.2 Delete has never propagated

```
sync_queue operations ever recorded:  INSERT 3059   UPDATE 227   DELETE 0
tombstone tables:                     none
```

Across 3,286 sync rows, not one deletion. Raw-SQL repairs bypass
`Mapper.after_delete`; there is no tombstone table for any entity. **The two
databases are structurally guaranteed to diverge over time and the system has no
mechanism to converge them.** Every repair in the runbook says "run it on both
databases" — that instruction is this defect, written down as a procedure.

### 2.3 `synced_at` does not mean applied

```
uid 6503e4bc…   ₹39.00   outbox q=43   synced_at 2026-07-05 20:45:45   NOT on cloud
```

The outbox recorded delivery. The row is not there. `synced_at` is stamped on
transport acceptance, not on apply outcome. The pull side learned this already
(findings #4, #13 → `_Applied` + inbox); the push side never did.

### 2.4 Guards that could not fail

`clear_staff_bizids.py` shipped with four reference probes against
`b2b_connections.seller_public_id` and siblings. **None of those columns has ever
existed on either database.** A bare `except: continue` swallowed all four, the
guard returned an empty set, and it printed a clean plan for the whole life of
the file. On Postgres it was worse: the first failure aborts the transaction, so
the four failed as a set (rule 58).

### 2.5 The integer-id trap, live

Matched on BizID:

| BizID | local | cloud | |
|---|---|---|---|
| BA-JABXGD | 6 | **7** | SaaS Production |
| BA-Y0DAFT | 7 | **42** | Brownie Factory |
| BA-T9SVHG | 11 | **46** | Alpha Factory |
| BA-1W9FAA | 87 | **19** | Chocolate |
| BA-H2GQZZ | 1 | — | Admin Central |
| BA-YYB4V2 | — | 1 | Admin Central |
| BA-E3PBH9 | — | 11 | SAAS Monster |

`business_id = 1` is Admin Central with username `admin` on both sides — and two
different tenants. `business_id = 11` is Alpha locally and SAAS Monster on the
cloud. Any code path comparing integers across the boundary is wrong and will
look right in testing.

### 2.6 Current divergence, whole-fleet

| | |
|---|---|
| receipts on both databases | 57 |
| attached differently | **1** |
| local-only | 2 (both benign — tenant absent on cloud) |
| cloud-only | 3 (1 real gap, 2 benign — tenants absent locally) |
| cloud invoices whose lines don't foot | 31 + 2 b2b orders |
| cloud documents with no journal entry | **47** |

---

## 3. The root property

Every defect above shares one cause:

> **The system has never been able to state, or check, that the two databases
> agree.** Sync reports that it *ran*, not that it *worked*. Every audit,
> constraint and guard was scoped to a single database, and the defects live in
> the difference between them.

Any option below should be judged on whether it makes agreement *statable and
checkable*, not on whether it makes sync faster.

---

## 4. Options

Scored 1–10. **Closes** = how many of the five measured defect classes (§2.1–2.5)
it eliminates rather than detects. **Offline** = preserves billing with no
network, which is non-negotiable for a counter product.

---

### Option A — Harden the current dual-write sync

Composite tenant FKs, tombstones, apply-by-uid-only, push outcomes, continuous
cross-database reconciliation, guard hygiene. Keeps SQLite + Postgres + the
hand-written sync worker.

| | |
|---|---|
| Closes | 5 / 5 (§2.1 by constraint, §2.2 by tombstones, §2.3 by outcomes, §2.4 by CI, §2.5 by uid-only resolution) |
| Offline | 10 — unchanged |
| Cost | Medium. Weeks, incremental, each piece shippable alone |
| Risk | Low. Every change is additive and independently revertible |
| Time to value | Days for the first piece (tenant FKs) |
| Ongoing burden | **High** — you continue to own a bidirectional sync engine forever |

**Rating: 8.5 / 10.** Highest certainty per unit of effort, and every piece is
needed regardless of what else is chosen. Its weakness is the last row: sync
engines are hard, this one has produced 17 findings, and hardening does not
change who maintains it.

---

### Option B — Same engine on both sides (Postgres locally)

Run Postgres on the desktop instead of SQLite.

| | |
|---|---|
| Closes | 1 / 5 — removes dialect drift only (§2.4's rule-58 half) |
| Offline | 8 — works, but a desktop Postgres is a support burden on Windows |
| Cost | High — installer, service management, migration of every live desktop |
| Risk | High — an installer regression bricks a shop's till |
| Time to value | Months |
| Ongoing burden | Higher than today |

**Rating: 3 / 10.** It fixes the *symptom I found least often* — dialect drift —
and touches the riskiest surface, the customer's machine. The tenant leak, the
missing tombstones and the false acks are all unaffected: they are sync-logic
defects, not dialect defects. Not recommended.

---

### Option C — UUID/ULID primary keys everywhere

Retire integer PKs on synced tables; `uid` becomes the primary key.

| | |
|---|---|
| Closes | 2 / 5 (§2.1 partly, §2.5 fully) |
| Offline | 10 |
| Cost | High — every FK, every index, every payload, a data migration on both sides |
| Risk | Medium-high — a PK migration on live money tables |
| Time to value | Months |
| Ongoing burden | Lower — the id trap stops existing |

**Rating: 6 / 10 as a destination, 3 / 10 as a next step.** Architecturally this
is the *right* end state and it is what removes §2.5 permanently. But `uid` is
already present on every synced table and is already the sync match key — the
practical benefit over "resolve by uid, constrain by tenant" is smaller than the
migration cost. Revisit after Option A lands; do not lead with it.

---

### Option D — Cloud as sole source of truth, local becomes a read cache

Drop local writes. Desktop reads a cache and queues nothing.

| | |
|---|---|
| Closes | 5 / 5 — trivially, by removing the second writer |
| Offline | **1** — the shop cannot bill when the internet is down |
| Cost | Medium |
| Risk | Existential |
| Time to value | Months |
| Ongoing burden | Lowest of all options |

**Rating: 2 / 10.** It is the cleanest engineering answer and it deletes the
product. Indian retail counters lose connectivity routinely; "bill offline" is
why this is bought. Recorded here so it is not re-proposed as an obvious
simplification later.

---

### Option E — Adopt a purpose-built sync engine

Replace the hand-written worker with a product whose entire job is
Postgres ↔ local-SQLite bidirectional sync.

The topology this product already has — a local SQLite per site, one Postgres in
the cloud, writes on both sides — is **exactly** PowerSync's stated design
target; it is described as a bi-directional sync layer for keeping a local SQLite
database in sync with a remote Postgres. ElectricSQL syncs subsets of Postgres
into local apps in real time, with more of its emphasis historically on the read
path. Turso's embedded replicas solve local-first SQLite with automatic sync but
are SQLite-centric rather than Postgres-backed.

| | |
|---|---|
| Closes | 4 / 5 — §2.2, §2.3, §2.5 become the vendor's problem; §2.4 stays yours; §2.1 still needs the DB constraint |
| Offline | 10 — this is what they are for |
| Cost | High — schema/permission model rework, a real migration, vendor cost |
| Risk | Medium-high — a hard dependency at the centre of the product |
| Time to value | Months |
| Ongoing burden | **Much lower** — you stop owning conflict resolution, tombstones, cursors, backoff |

**Rating: 7.5 / 10, rising to 9 if a spike goes well.** The single biggest
reduction in permanent maintenance surface. It does **not** remove the need for
Option A's tenant constraint — a sync engine will faithfully replicate a
cross-tenant write; only the database can refuse one.

> ⚠ **Unverified.** The vendor characterisations above come from a web search on
> 2026-08-01 and vendor documentation, not from a spike against this codebase.
> Multi-tenant row filtering, Python/FastAPI server-side integration, and cost at
> this scale are all unconfirmed. **Do not select on this section alone.**

---

### Option F — Make the sync unit an append-only ledger with tombstones

Stop syncing table rows; sync immutable events. Deletes become tombstone events.
Convergence becomes a property of the log rather than of a reconciler.

| | |
|---|---|
| Closes | 4 / 5 (§2.1 still needs the constraint) |
| Offline | 10 |
| Cost | Very high — a rewrite of the write path |
| Risk | High |
| Time to value | Many months |
| Ongoing burden | Low once done |

**Rating: 5 / 10 whole, 9 / 10 for its tombstone half.** The full event-sourcing
rewrite is not justified. **The tombstone table is, on its own, and should be
lifted out of this option and into Option A immediately** — §2.2 is unfixable
without it and it is a day of work, not a rewrite.

---

## 5. Recommendation

**Do Option A now. Spike Option E in parallel. Defer C. Reject B and D.**

| Rank | Option | Rating | Verdict |
|---|---|---|---|
| 1 | **A — harden current sync** | **8.5** | Start immediately; needed under every other option |
| 2 | E — adopt a sync engine | 7.5 → 9 | Spike now, decide in a quarter |
| 3 | C — UUID primary keys | 6 | Right destination, wrong next step |
| 4 | F — event sourcing | 5 | Take the tombstones, leave the rewrite |
| 5 | B — Postgres locally | 3 | Cost and risk on the customer's machine for the least valuable fix |
| 6 | D — cloud-only | 2 | Deletes the product's reason to exist |

The reasoning in one line: **A is the only option that is required no matter what
you choose next**, because a sync engine — however good — will replicate a
cross-tenant write faithfully, and only a database constraint can refuse one.

---

## 6. Sequenced plan

### Phase 0 — done / in flight (this session)

- [x] `TenantFK` + `ensure_tenant_fks` in `core/accounting/db_invariants.py`:
      composite `(id, business_id)` FK on Postgres, BEFORE-triggers on SQLite,
      13 references declared, refuses to install over existing violations.
- [x] `tests/test_tenant_fk_invariants.py` — 16 tests, enforcement proved
      behaviourally, including a reconstruction of the exact `e10f6d92` rows.
- [x] Fixed a latent bug found by that test: an apostrophe in a rule's `why`
      string terminated the trigger's SQL literal, so the guard failed to
      install and the app booted without it. Present in the CHECK installer too.
- [x] `scripts/audit_payment_attachment.py` — cross-database comparison by uid,
      tenants matched on BizID.
- [x] `scripts/inspect_invoice.py` — read any invoice from either database
      without a cloud token.
- [ ] Repair `e10f6d92` (cloud only) and `6326fb2a` (both) — **owner**
- [ ] Confirm `ensure_tenant_fks` installs on the next cloud boot

### Phase 1 — sync tells the truth (2–3 weeks)

- [ ] `sync_tombstones` table, written by `Mapper.after_delete` **and**
      explicitly by every repair script. Without this §2.2 stays open forever.
- [ ] Push returns per-uid outcomes; `synced_at` set only on `applied`.
      Mirror `_Applied` and the inbox onto the push side.
- [ ] Apply resolves parents by `uid` only. `invoice_id_uid` is already in the
      payload. Delete every number/integer fallback; test that an unresolvable
      parent inboxes with zero rows touched.

### Phase 2 — divergence is continuously visible (1–2 weeks)

- [ ] Fold `audit_payment_attachment` into `run_cloud_parity_sweep`; add
      `wrong_tenant` / `wrong_invoice` to the parity summary keys so "parity OK"
      cannot be logged over them.
- [ ] Written contract: *no money row may differ in tenant, parent or amount
      between databases; divergence is detected within N minutes.*

### Phase 3 — guards cannot lie (1 week)

- [ ] Every probe/declaration list validated against the schema in CI
      (`test_every_declared_reference_names_columns_that_actually_exist` is the
      template — it is the test that would have caught §2.4 instantly).
- [ ] No swallowed query failures; unreadable ≠ empty (rule 33).
- [ ] Every all-clear prints its denominator.
- [ ] Cross-database fixtures in the repo so these are testable without a live
      Postgres.

### Phase 4 — sell the property (1–2 weeks)

- [ ] Ops panel: **"Books verified identical to cloud · 0 divergences · 4 min ago"**,
      divergence list one click away.

If cloud sync is the USP, the feature is not sync — it is **provable agreement**.
This phase is what turns an invisible property into the thing customers are
buying, and it means the next `e10f6d92` is caught by the product, by the
customer, in minutes.

### Phase 5 — the Option E spike (timeboxed, 1 week, parallel)

- [ ] Multi-tenant row filtering by BizID
- [ ] Server-side integration with FastAPI/SQLAlchemy
- [ ] Migration path for existing desktops with live data
- [ ] Cost at 10 / 100 / 1000 shops
- [ ] What happens to `journal_entries`' per-DB hash chain, which is deliberately
      not synced today

---

## 7. Exit criteria

This is finished when all of the following hold, measured and not asserted:

1. `audit_payment_attachment.py` reports **0** in all four categories.
2. `ensure_tenant_fks` reports every rule `installed` on **both** databases.
3. A deletion on one database is observable on the other without human action.
4. No row is marked `synced_at` that is absent on the far side.
5. `audit_money_integrity` sections B, C1, H, I and J are all `[ ok ]` on the cloud.
6. Every guard in the tree has a test that goes red when its fix is reverted.

---

## 8. Open unknowns — stated, not papered over

- **How `e10f6d92` reached the cloud is unproven.** No outbox row records
  sending it. The local database was renumbered at some point (the surviving
  payload for a sibling row carries `id=1, invoice_id=455` where the row today
  is `id=12, invoice_id=787`), so `sync_queue` is not a complete history. The
  tenant FK closes the *outcome* regardless of the path, which is precisely why
  a constraint is preferable to a root-cause fix here.
- **47 documents with no journal entry** on the cloud is unscoped and is larger
  in rupee terms than every other open item combined. Trial balance, P&L and
  party ledger all read from `journal_entries`.
- **Option E's vendor claims are unverified** against this codebase.
- **Option A leaves you owning a sync engine.** That is a strategic cost, not a
  technical defect, and it should be an explicit decision rather than a default.

---

## Sources

- [Alternatives | Electric](https://electric-sql.com/docs/reference/alternatives)
- [Local-First SQLite, Cloud-Connected with Turso Embedded Replicas](https://turso.tech/blog/local-first-cloud-connected-sqlite-with-turso-embedded-replicas)
- [Introducing Embedded Replicas: Deploy Turso anywhere](https://turso.tech/blog/introducing-embedded-replicas-deploy-turso-anywhere-2085aa0dc242)
- [Tech Stack Analysis for a Cross-Platform Offline-First AI Chat Client](https://docs.boltai.com/blog/tech-stack-analysis-for-a-cross-platform-offline-first-ai-chat-client)
- [From WAL to WASM — High-Performance Local-First Sync with Postgres & SQLite](https://dev.to/rafacalderon/from-wal-to-wasm-high-performance-local-first-sync-with-postgres-sqlite-50h0)
