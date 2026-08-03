# Decision — should the local database move from SQLite to Postgres?

**Date:** 2026-08-03
**Status:** decision record, awaiting owner sign-off
**Question:** the cloud is Postgres (Supabase, fronted by the Hugging Face Space).
Should the local desktop database stop being SQLite and become Postgres too, so
the two sides are "compatible"?
**Answer:** **No.** Do [Option A](DATA_ARCHITECTURE_OPTIONS_2026-08-01.md) and
the CI change in §7 instead. But the pre-production window changes what *else*
is worth doing right now, and §6 is the part of this document that matters most.

Supersedes the Option B entry in
[`DATA_ARCHITECTURE_OPTIONS_2026-08-01.md`](DATA_ARCHITECTURE_OPTIONS_2026-08-01.md) §4,
which was written assuming a live fleet.

---

## 1. The premise, corrected first

The proposal is "the cloud is Postgres, so making local Postgres too would be
easy and compatible." The compatibility half is true. The half that matters is
not:

> **Same engine does not mean same ids.**

Every synced table declares:

```python
id = Column(Integer, primary_key=True, index=True)     # database/db.py:157
```

A per-database autoincrement. **Two Postgres databases assign sequences exactly
as independently as SQLite and Postgres do.** A business is `7` locally and `42`
on the cloud today; after migrating to Postgres locally it would still be `7` and
`42`, for the same reason.

Nothing in the identity layer could be retired:

| Still required after Option B | Why |
|---|---|
| `core/identity.py`'s BizID rule | Integers still only mean something in the database that issued them |
| Re-pin at push apply (`routes/sync.py:430`) | Incoming integer is still foreign |
| Re-pin at pull apply (`sync_worker.py:2089`) | Same |
| `resolve_business_id_in_db` fail-closed on BizID | Same |
| `uid` as the sync match key | Same |

**This is engine-independent and it is the whole two-database problem.** If the
goal is "local and cloud should stop disagreeing about identity", Option B does
not move it at all — but [Option C](#63-option-c-uid-primary-keys--the-real-mover) does, and §6.3 is where that gets
interesting.

---

## 2. What Option B genuinely would fix

The 2026-08-01 document scored this "closes 1/5" and moved on. That undersells
it, and the 2026-08-03 audit found more evidence for the pro side. Dialect drift
has been the most *expensive* class of defect in this codebase even though it is
only one of the five:

* **Finding 17** — `ALTER TABLE users ADD COLUMN last_login DATETIME`. SQLite
  accepts any type name; Postgres has no `DATETIME`. The Space crash-looped at
  import, every device got HTTP 503, and **all sync stopped**. A total outage
  from one type token.
* **`_portable_ddl()` exists only to paper over this** — 13 dialect branches in
  `database/migration.py` alone.
* **`core/accounting/db_invariants.py` maintains two implementations of every
  money rule**: a Postgres `CHECK` and a SQLite trigger. The tenant FKs are worse
  — a composite `FOREIGN KEY (fk_col, business_id)` on Postgres versus a `BEFORE`
  trigger on SQLite. Two spellings of the safety-critical constraint, which is
  the "two copies of one thing" root cause named in `CLEANUP_PLAN` §6.1.
* **C-10 (2026-08-03)** — `INSERT OR IGNORE INTO sync_queue`
  (`services/sync_worker.py:1479`), SQLite-only syntax, not covered by the
  portability gate. Latent only because `run_cloud_parity_sweep` returns early
  unless the dialect is SQLite (`sync_worker.py:781`).
* **C-8 (2026-08-03)** — the **Postgres half of the tenant FK work has never
  executed anywhere**, including CI.

Measured: **52 dialect-conditional branches in runtime code** (excluding alembic
and tests). One engine would delete most of them.

So the itch is real and this document does not dismiss it. The disagreement is
about the cheapest way to scratch it (§7).

---

## 3. What Option B does not fix

Unchanged, because none of these are dialect problems:

| Defect class (from the 08-01 audit) | Fixed by Postgres locally? |
|---|---|
| §2.1 receipt on another tenant's invoice | **No** — needs the constraint, which already exists on both engines |
| §2.2 deletes never propagate | **No** — same engine, still two databases, still no tombstone |
| §2.3 `synced_at` semantics | **No** — a sync-protocol question |
| §2.5 integer ids diverge | **No** — see §1 |
| §2.4 guards that could not fail | Partly — removes the rule-58 half only |
| You still own a hand-written sync engine | **No** |

---

## 4. The costs, split by what pre-production actually removes

This is the crux. The costs divide cleanly, and only one half goes away.

### 4.1 Migration costs — **now ≈ zero** ✅

With no live installs there is no fleet to migrate, no shop that cannot bill on
Monday morning, no per-user rollback plan, no support burden during cutover.
The 08-01 document's *"migration of every live desktop"* and *"an installer
regression bricks a shop's till"* both evaporate.

**This is a genuine and large reduction.** It is why this document re-scores
Option B upward in §5 rather than simply restating the old verdict.

### 4.2 Permanent product costs — **completely unchanged** ❌

These are properties of shipping Postgres on a retail counter, not of migrating
to it. They arrive on day one of production and stay for ever:

* **Installer weight.** ~150–300 MB of Postgres on top of a bundle already
  carrying torch (~240 MB) via the PyInstaller onedir spec.
* **A database server on the till.** `initdb`, a data directory, a service or
  supervised child process, port conflicts, a superuser role, file permissions —
  on Windows machines you do not administer.
* **Major-version upgrades, and this is the serious one.** `desktop/package.json`
  ships **silent auto-updates** via `electron-updater`. When an update built
  against PG 17 reaches a machine holding a PG 16 data directory, the server
  refuses to start until `pg_upgrade` runs with *both* binaries present. A silent
  auto-update that can leave a shop unable to bill is precisely the failure
  `ARCHITECTURE.md` §8 calls an extinction event. Community Postgres has no
  in-place major upgrade that is safe to automate unattended.
* **Backup and restore stop being "copy one file."** `data_transfer`, the backup
  modal, and every support conversation currently depend on that.
* **Performance goes the wrong way.** The benchmarks in the 07-30 review
  (0.91 ms hash-chain verify, 9.92 ms balance sheet, 12.21 ms trial balance) are
  **SQLite numbers** — an in-process library call with no IPC. Postgres adds a
  socket round-trip per statement. For a single-process embedded workload SQLite
  is simply the faster engine, and "sub-second billing" is the product promise.

### 4.3 The argument that usually justifies it does not apply here

Concurrency is the normal reason to want a real server, and this deployment does
not have the problem:

* **LAN mode is many tills over HTTP against one FastAPI process** — the tills
  are HTTP clients, not database clients (`routes/discovery.py`, and the frontend
  pinning `192.168.0.102:8001`). There is exactly **one** writer process.
* In-process contention is already handled: `PRAGMA busy_timeout=30000` and
  `timeout=30.0` (`database/db.py:69`, `:117`).
* If more headroom is ever needed, `PRAGMA journal_mode=WAL` is one line. It is
  deliberately off today with the reason recorded at `db.py:121-129` (it turns
  the database into three files and the backup paths copy one).

### 4.4 And it forfeits the local-encryption story

This is the argument that decides it, and it only became visible while writing
the 08-03 audit.

**C-1** found that `ARCHITECTURE.md` §2.8 specifies **SQLCipher** for the offline
cache — *"a stolen laptop ≠ a plaintext price book"* — and that it does not
exist. The local database is plaintext: every customer, every invoice, every
payment, the whole price book.

SQLCipher is transparent page-level AES **for SQLite**. It is a drop-in.

**Community Postgres has no equivalent.** There is no transparent data encryption
in mainline; the options are third-party forks, or relying on OS-level disk
encryption (BitLocker) that you do not control on a shop's Windows machine.

> Choosing Postgres locally does not postpone C-1. It **removes the cheapest path
> to ever fixing it.**

For a product whose pitch is "your data lives with you, not in someone else's
cloud", trading away local-at-rest encryption to gain schema convenience is the
wrong trade.

---

## 5. Re-scored, for a pre-production codebase

| Option | 08-01 score | **08-03 score** | What moved |
|---|---|---|---|
| A — harden current sync | 8.5 | **8.5** | Unchanged; still required under every other option |
| B — **Postgres locally** | 3 | **4.5** | Migration cost → 0. Permanent costs and small benefit unchanged; forfeits SQLCipher |
| C — **uid primary keys** | 3 *as next step* | **7.5** | The migration objection was the whole objection, and it just disappeared |
| D — cloud-only | 2 | **2** | Still deletes the product |
| E — adopt a sync engine | 7.5 | **8.0** | No live data to migrate makes the spike materially cheaper |
| F — event sourcing | 5 | **5.5** | Tombstone half still worth lifting out on its own |

**Option B rises and still loses.** Removing a one-time cost does not create a
benefit: it still closes 1 of 5 defect classes, still leaves you owning the sync
engine, and now visibly costs the local encryption path.

---

## 6. What the pre-production window *does* make worth doing

The right question is not "is Option B cheaper now" — it is **"what disruptive
things are only affordable while there are no customers?"** Three, in order.

### 6.1 Encrypt the local database (C-1) — do it now or accept never

SQLCipher means a key-custody design, a Windows packaging change, and a one-time
conversion of the local file. With no installed base the conversion is free. With
10,000 tills it is a fleet-wide migration of the file every shop's data lives in.

**Doing this later is strictly harder than doing it now, and it is the highest-
severity item in the 08-03 audit.**

### 6.2 The data-repair backlog collapses to a wipe — *needs your confirmation*

Several open items are careful, risky, owner-in-the-loop repairs of production
data:

| Item | Current plan |
|---|---|
| A-7 / the ₹124 double payment (`LCL-OW-0037`) | The 5-step runbook in SYNC_AUDIT §7b.7 |
| 31 overfilled cloud invoices + 2 b2b orders | `repair_line_items_by_invariant.py` against the cloud |
| 47 cloud documents with no journal entry | Unscoped |
| A-8 · 8 invoices with no customer link | Script + owner memory |
| A-9 · 59 sync conflicts awaiting review | Owner review, ongoing |
| C-12 · 11 staff holding a BizID | `clear_staff_bizids.py`, which has no `--db` flag |

> **If none of that is real customer money, the correct action is not to repair
> it — it is to wipe both databases and reseed.** That closes six open items at
> once and removes the "which of two payments actually happened at the counter"
> question entirely, because nothing happened at any counter.

> ## ✅ DECIDED 2026-08-03 — **REPAIR, NOT WIPE**
>
> Owner's call: take the repair path. **This section does not apply and the wipe
> must not be run.** `SYNC_LIVENESS_AUDIT_2026-07-31.md` §7b.7 is the procedure,
> and the six data items above stay open until it is executed.
>
> **Two consequences, because they change other decisions:**
>
> 1. **Option C (§6.3) is no longer a free schema change.** Its 3 → 7.5 re-score
>    assumed an empty database. With data that must survive, a uid-PK change
>    needs a real migration again — still far cheaper than post-launch, but not
>    near-zero. **Re-rate it ≈ 6.0 as a next step**, and treat that spike as
>    genuinely optional rather than obviously worth doing.
> 2. **Every repair runs against BOTH databases, separately.** There are still no
>    tombstones (A-1), and the repair scripts delete over raw connections so
>    `Mapper.after_delete` never fires and no DELETE is queued. A row removed on
>    one side stays on the other indefinitely. The runbook's "run it on both
>    databases" is not caution — it is the missing feature written down as a
>    procedure.
>
> **Blocker list refreshed 2026-08-03 — it was stale, in the good direction:**
>
> | Script | §7b.7 said | Verified state |
> |---|---|---|
> | `clear_staff_bizids.py` | "no `--db`, cannot touch the cloud" | **Has `--db`** (added in `feb0c5f`), plus `--apply` and `--i-have-a-restorable-backup` |
> | `audit_payment_attachment.py` | listed as `--db`-less | **By design** — takes `--local` / `--cloud`, read-only on both, has no `--apply` and cannot acquire one |
> | `prune_unused_staff.py` | — | Still no `--db`. Not in the repair path; needs cloud-tombstone coordination first |
> | 4 open shifts (biz 42) | "not a script's job" | **Unchanged.** `closing_cash_actual` is a COUNT, not a calculation — close them from the register screen |
>
> The original pre-conditions below are kept for the record only.

**I have not done this and am not recommending it blind.** Two things to confirm
first, because the action is irreversible:

1. That the Supabase database behind the Space holds **no** data you need — no
   pilot shop, no demo tenant someone is showing customers.
2. That you have a restorable snapshot taken immediately before, so a wrong
   answer to (1) is recoverable.

If both hold, say so and I will write the reset procedure. If either is
uncertain, the repair runbook stays the right path and this section does not
apply.

### 6.3 Option C (uid primary keys) — the real mover

This is the one that addresses what you actually asked for.

The 08-01 document rated Option C *"6/10 as a destination, 3/10 as a next step"*,
and the entire reason for the gap was migration cost: *"a data migration on both
sides"*, *"Risk: Medium-high — a PK migration on live money tables."*

**There are no live money tables.** The objection was the cost, and the cost is
gone.

What makes it unusually tractable here — measured 2026-08-03:

* **Every synced table already has a `uid` column** (`String(36)`, UUID4 default).
* **Zero rows have a NULL or empty uid** — across 20,170 `invoice_line_items`,
  10,075 `invoices`, 4,935 `invoice_payments` and every other synced table.
* **`uid` is already the sync match key** on both apply paths.
* Payloads already carry `<fk>_uid` parent references via `_serialize_orm_obj`.

So the values exist, are populated, are unique, and are already load-bearing. The
work is schema and FK rewiring, not data invention.

What it buys that Option B does not:

* **§2.5 stops existing.** Not "is guarded against" — the integer id trap is
  gone, permanently, because there are no cross-database integers left to confuse.
* **The 9 Group-B tenant FKs become expressible.** Today `invoice_line_items` and
  friends cannot carry a composite tenant FK because they have no `business_id`;
  a uid-keyed schema changes that conversation.
* **The integer fallbacks in `routes/sync.py:450-451` and `:460` can be deleted**
  rather than left as documented backstops (item A-2).

Honest cost: still weeks, still touches every FK, index and payload, and it is
not free just because it is cheap. But it is the difference between doing it now
for weeks and never doing it at all — which is what "revisit after Option A
lands" would become once there is a fleet.

**Recommendation: scope Option C as a timeboxed spike alongside Option A, and
decide before the first paying install.** That is the opposite of the 08-01
advice, and the reason is that the fact the advice rested on has changed.

---

## 7. Do this now regardless — the cheap 80%

Whatever is decided above, the dialect-drift pain in §2 has a fix that costs
hours and touches no customer machine: **run the sync, tenant-FK and migration
suites against the Postgres that CI already starts.**

`.github/workflows/ci.yml` already provisions `postgres:15` and already re-runs
10 money suites against it. The ~25 sync/tenant/migration suites were simply not
in the list. Applied 2026-08-03 as a new step, *Run Sync & Tenant Suites on
Postgres*.

This catches the whole class of bug in §2 — including finding 17's shape and the
never-executed Postgres half of `ensure_tenant_fks` — at the point of change
rather than in production.

> ⚠ **Unverified: no Postgres was available in this session** (`docker` and
> `psql` both absent), so these suites have **not** been run against Postgres
> here. The first CI run is the verification, and it may well go red. **That is
> the finding, not a regression** — it would be the first time this code has ever
> been executed on the engine the cloud runs.
>
> If it does go red, fix the drift or skip the individual test with a written
> reason. **Do not add `continue-on-error`** — a green tick over a suite that
> cannot pass is the exact failure mode `CLEANUP_PLAN` §6.2 and rule 33 are about.

---

## 8. Recommendation

| | |
|---|---|
| **Postgres locally (Option B)** | **No.** Benefit unchanged and small; permanent costs unchanged; forfeits SQLCipher (§4.4) |
| **CI on Postgres (§7)** | **Yes, now.** Hours of work, most of the benefit, zero customer risk |
| **SQLCipher (C-1)** | **Yes, now.** Only affordable while there is no installed base |
| **Option C — uid PKs (§6.3)** | **Spike now, decide before first paying install.** This is what actually ends the divergent-id problem |
| ~~Wipe and reseed (§6.2)~~ | **REJECTED 2026-08-03 — repair instead.** Six data items stay open; §7b.7 is the path, run on both databases |
| **Option A** | **Unchanged: do it.** Required under every option |

If Postgres locally is still wanted after this, take it in two reversible steps
rather than as a migration:

1. **Make Postgres the local dev/test default.** `DATABASE_URL` already switches
   cleanly (`database/db.py:47`) and `conftest` already honours
   `BIZASSIST_TEST_DATABASE_URL`. You feel every drift immediately; customers are
   untouched; it is reversible in one environment variable.
2. **Only then**, and only for a named customer with a named problem, consider
   Postgres as an *opt-in* for large multi-till shops.

Flagging the obvious risk in step 2: supporting both engines means maintaining
both paths for ever. That is the same "two copies" trap from `CLEANUP_PLAN` §6.1,
relocated rather than solved — and it is how §2's dual `db_invariants`
implementations came to exist in the first place.

---

## 9. If Option B is chosen anyway — what the migration actually needs

Recorded so the work is not underestimated. **`backend/migrate_sqlite_to_postgres.py`
is not this tool**: it is a one-shot local→Supabase *seeding* script that copies
`users` rows including their integer ids — the exact identity collision the BizID
work exists to prevent — and it hard-codes `SQLITE_URL` and reads the cloud URL
from `DATABASE_URL`.

A real per-install migration needs:

1. **Schema parity assertion** — every column, type, index, constraint and
   trigger equivalent present on the target before a single row moves. The
   SQLite triggers in `db_invariants.py` become Postgres `CHECK`s and composite
   FKs; that translation must be proven, not assumed.
2. **Row-count and checksum reconciliation per table**, refusing to proceed on
   any mismatch (`audit_money_integrity.py` is the model).
3. **Sequence resets** after copying explicit PKs, or every subsequent insert
   collides at `id=1`.
4. **Hash-chain revalidation** — `journal_entries` carries a per-database SHA-256
   chain. It must verify on the target before the old file is trusted as
   disposable.
5. **The old `.db` file retained, not deleted**, with an automatic fallback to
   SQLite on any failure at any step. A shop must be able to bill on the old
   engine tomorrow morning.
6. **A packaged Postgres with a supervised lifecycle**, and a documented,
   *tested* `pg_upgrade` path across major versions before the first auto-update
   that changes it.
7. **Staged rollout with a kill switch**, per `ARCHITECTURE.md` §8.3.

Items 6 and 7 are the ones that do not get cheaper with scale, and item 6 is
permanent.

---

## 10. Open questions for the owner

1. ~~Is the Supabase/HF data genuinely disposable?~~ **ANSWERED 2026-08-03: no — repair, not wipe.** (§6.2)
2. **Is there a pilot or demo tenant** anyone is currently showing to customers?
3. **Does §7's CI step pass on Postgres?** Unverified here; the first run answers it.
4. **Is Option C worth a timeboxed spike now** (§6.3), given it is affordable
   only in this window?
5. **What is the local-at-rest encryption decision** (C-1)? It must be answered
   *before* Option B, because Option B forecloses the cheap answer.
