# Data repair — measured state, and what must be re-run on the shop laptop

**Date:** 2026-08-03
**Decision:** repair, **not** wipe (see [`DECISION_LOCAL_POSTGRES_2026-08-03.md`](DECISION_LOCAL_POSTGRES_2026-08-03.md) §6.2)
**Status:** step 0 (measure) complete on the CLOUD. **Nothing has been written to any database.**
**Runbook:** [`SYNC_LIVENESS_AUDIT_2026-07-31.md`](SYNC_LIVENESS_AUDIT_2026-07-31.md) §7b.7

---

## 0. ⚠ READ THIS FIRST — which machine this was measured from

> **The local database used for these measurements is NOT the shop's live
> install. The live local install is on a DIFFERENT LAPTOP.**

Everything below is split accordingly, because the single most repeated mistake
in this project's history is establishing a fact on one database and believing it
holds for the other. `SYNC_LIVENESS_AUDIT` §5.1 opens with a correction titled
*"I measured the wrong database"*; this section exists so that does not happen a
third time.

### The machine these numbers came from

| | |
|---|---|
| Hostname | **`Salma_B`** |
| Local DB | `backend/bizassist.db` (90 MB) |
| File last modified | **2026-07-23 21:47** |
| Newest real invoice | **2026-07-23 10:50** |
| Owners | 9 |
| Invoices | 10,075 — of which **10,000 are synthetic** (`Load Test Shop 9999`), leaving **75 real** |
| `sync_queue` rows | 135 |

### Why this matters, concretely

The cloud holds invoices created **30 July** (`LCL-OW-0037`, `LCL-OW-0039`). This
laptop's local database stopped being written on **23 July**. It is **7+ days
stale**, and the shop kept billing on the other machine throughout.

**It is still the paired install** — four businesses match on BizID, so this is
not an unrelated database:

| BizID | id on THIS laptop | id on cloud | Business |
|---|---|---|---|
| BA-JABXGD | 126 | 7 | SaaS Production |
| BA-Y0DAFT | 133 | 42 | Brownie Factory |
| BA-E3PBH9 | 125 | 11 | SAAS Monster |
| BA-1W9FAA | 132 | 19 | Chocolate |

(Local ids were renumbered at some point — the 01-Aug audit recorded 6 / 7 / 11 /
87 for these same BizIDs. The BizID spine is what makes the pairing legible at
all, which is the point of `core/identity.py`.)

Two further identity notes, both real:

* **`Admin Central` has a DIFFERENT BizID on each side** — `BA-3XZTWS` (local
  id 1) vs `BA-YYB4V2` (cloud id 1). Same name, same username `admin`, same
  integer id, **two different tenants**. This is exactly the trap §2.5 of the
  data-architecture document describes, live.
* **`Load Test Shop 9999` HAS a BizID as of 2026-08-03** — `BA-Z3Z5BD`, handed to
  it by the migration's legacy-owner backfill on the 19:32 boot
  (*"Backfilled BizID for 1 legacy owner(s)"*). It is now registered in the
  **cloud LAN discovery registry** alongside the real businesses.

  **It does not sync, and the reason is one field.** Its `hosting_mode` is
  `None`, so `run_hybrid_sync` skips it and `_queue_change` declines every row
  (*"has no settings at all — hosting_mode is unknown and the row is NOT
  queued"*). Only businesses **126** and **133** are `hybrid`.

  **This is a loaded gun, not a live defect.** Flip that one field — a stray
  Settings save, a seeded fixture, a future backfill that defaults it — and
  10,000 invoices, 20,170 line items and 20,226 stock-ledger rows push to the
  production cloud. Worth deleting the business outright, or pinning
  `hosting_mode: "local"` on it so the value is explicit rather than absent.

  Its 10,000 invoices and 4,897 payments remain noise in any local↔cloud
  comparison and must be excluded from every count.

---

## 1. What IS trustworthy — cloud-only measurements

These were taken against the Supabase Postgres directly. They are properties of
**one** database and are unaffected by which laptop asked. **These stand.**

### 1.1 `audit_money_integrity.py --db <cloud>` → **81 issues**

| Section | Result |
|---|---|
| A. Mis-attached payments (M-9) | ✅ **0** |
| B. Documents with no journal entry (M-2) | ❌ **47** |
| C1. Payment rows exceed invoice total | ✅ **0** |
| C2. Invoice records MORE paid than rows show | ✅ **0** |
| C3. Invoice records LESS paid than rows show (M-7) | ✅ **0** |
| D1. Orphan payments · D2. Cross-tenant payments | ✅ **0 · 0** |
| E. Duplicate invoice numbers | ✅ **0** |
| F. Journal entries that do not foot | ✅ **0** |
| G. Foreign-key violations | ✅ **0** |
| H. Overlapping open shifts (M-11) | ❌ **4** — biz 42 operator 42, ids 8/12/14/30, floats ₹30,905 |
| I. Line items do not foot (M-16) | ❌ **31** |
| J. B2B order lines do not foot (M-18) | ❌ **2** |

### 1.2 Two items from the old runbook are now CLOSED

* **`LCL-OW-0037` (the ₹124 double payment) is resolved on the cloud.** It now
  holds exactly one ₹124 **Bank** payment (`0656a848…`), `paid_amount = 124.00`,
  status `Paid`. The duplicate cheque is gone. This matches the owner's 01-Aug
  decision that the Bank transfer was the real event. **Runbook §7b.7 steps 1–4
  need no further action on the cloud.**
* **The cross-tenant receipt `e10f6d92…` is gone** — section A and D2 both 0, and
  the cross-database sweep reports **0 wrong-tenant**.

### 1.3 Line-item repair, dry run against the cloud

```
scripts/repair_line_items_by_invariant.py --db <cloud>          [DRY RUN]

  scanned              89 invoices (213 line items), 3 b2b_orders (15 line items)
  repairable invoices  15   →  37 rows to delete, phantom line value ₹9,897.52
  needing review       18   →  "no prefix of the line items reconciles to the
                               header — the header may be the wrong side"
```

**The 18 are not a script's decision.** The audit says it plainly: *"the header
may be right and the lines wrong, or the reverse, and only the printed/filed
copy settles it."* Deleting those lines moves the P&L on a guess.

### 1.4 Journal backfill, dry run against the cloud

`scripts/backfill_journals.py` **could not reach the cloud at all** until
2026-08-03: it had no `--db`, so it could only ever open whatever the
application was pointed at. This is the same gap `clear_staff_bizids.py` had.
Fixed — see §1.5 — and then run:

```
scripts/backfill_journals.py --db <cloud>                        [DRY RUN]
target: postgresql://postgres.…:***@aws-1-ap-south-1.pooler.…   engine: postgresql

  business  7: 21 invoices
  business 42: 24 invoices
  business 53:  2 invoices

  47 document(s) total
```

Exactly the 47 from section B, and it accounts for **all** of them — including
the 18 `OPEN-31 … OPEN-50` rows, which the collector classes as invoices rather
than as a separate shift-float case. The script posts through the same
`core/accounting/posting` builders the counter uses (so a backfilled entry is
byte-identical to one posted at sale time) and is idempotent on
`(business_id, source_type, source_id)`, so re-running posts nothing twice.

**Not applied.** This is the one repair on the list with no ambiguity — it
*adds* missing journal entries rather than deleting anything, and until it runs
the trial balance, P&L and party ledger for businesses 7, 42 and 53 are short by
exactly these documents. It is the strongest candidate to go first once §4's
backup gate is answered.

### 1.5 `backfill_journals.py` gained `--db` (2026-08-03)

Unlike the raw-SQL repair scripts it needs a real ORM `Session`, so it cannot use
`_dbcompat.connect`. The flag is therefore resolved **before** `database.db` is
imported, because that module reads `DATABASE_URL` at import time and builds the
engine — and, for SQLite, attaches the `PRAGMA foreign_keys=ON` /
`busy_timeout` listeners. Setting it afterwards would leave the engine bound to
the original target: the script would print the database you asked for and write
to the one it had already opened.

It now also prints the target it actually opened, password redacted via
`_dbcompat._redact` (verified against a synthetic credential). Every serious
mistake in this project's repair history has been a correct answer about the
wrong database, so the target is not optional output.

---

## 2. What is NOT trustworthy — anything comparing local ↔ cloud

Every cross-database number below was computed against a **7-day-stale secondary
laptop**. Re-run all of it on the shop machine before acting on any of it.

### 2.1 Almost certainly just staleness, NOT corruption

| Observation | Why it is probably not a defect |
|---|---|
| 20 payments on cloud, absent locally | Includes `0656a848` (30 Jul) — created *after* this laptop stopped syncing on 23 Jul |
| Brownie Factory: 44 cloud invoices vs 34 local | Same reason |
| `LCL-OW-0037` missing locally | Created 30 Jul |
| 4,897 "local-only" payments | All `Load Test Shop 9999` — no BizID, cannot sync, pure noise |

Reporting these as divergence would be reading a stale replica as data loss.

### 2.2 Genuinely suspicious — must be re-checked, do not act yet

```
uid fab17765-edc4-4397-8fce-43e1be104689     ₹310.00 cash   2026-07-08
  local (Salma_B) : LCL-OW-0006  row 795   biz 133  BA-Y0DAFT  total 310.00
  cloud           : LCL-OW-0024  row 821   biz 42   BA-Y0DAFT  total 310.00
```

Same receipt uid, **same business**, **different invoice** — classic M-9. Both
invoices total ₹310.00, so each database reads as correctly settled and neither
can detect it alone.

It is dated **08 Jul**, i.e. *before* this laptop went stale, so it is not
explained by staleness. But this laptop's database was rebuilt/renumbered at some
point, and a re-import can re-attach a payment, so **the attachment on this
machine is not evidence about the shop's machine.**

> ### ✅ RESOLVED 2026-08-03 — and the original diagnosis was WRONG
>
> The backend was started on this laptop, migrations ran, and its boot log named
> the real defect:
>
> ```
> [Migration] M-3: cannot enforce invoice-number uniqueness — 1 duplicate
> number(s) already exist … biz 133 'LCL-OW-0006' x2
> ```
>
> Matched by **uid** — the only valid cross-database identity — the payment was
> never misattached:
>
> | invoice uid | LOCAL | CLOUD |
> |---|---|---|
> | `29325381…` | `LCL-OW-0006` ₹310 | `LCL-OW-0006` ₹310 ✅ |
> | `66db68e4…` | **`LCL-OW-0006`** ₹310 ❌ duplicate | `LCL-OW-0024` ₹310 |
> | `32723a94…` | `LCL-OW-0024` ₹424 | **absent on the cloud** |
>
> Both receipts follow their invoice uid correctly on **both** databases —
> `8855d3e1` → `29325381`, `fab17765` → `66db68e4`. **The money is on the right
> document.** What differs is that document's *number* on the local side.
>
> So this is a **numbering defect, not a misattachment**, and it needs no
> recollection from anyone. Two local rows to settle:
>
> * uid `66db68e4` is numbered `LCL-OW-0006` locally and `LCL-OW-0024` on the
>   cloud. The cloud is right; the local number is the duplicate blocking M-3.
> * uid `32723a94` (₹424) holds `LCL-OW-0024` locally and **has never reached
>   the cloud**, so it is squatting on the number `66db68e4` should carry.
>   Renumbering naively would collide — `scripts/resolve_duplicate_invoice_numbers.py`
>   is the tool for this, and it must run with the owner present because a number
>   printed on a customer's copy must not be silently reassigned.
>
> **The audit tool was fixed, because it could not have told these apart.**
> `audit_payment_attachment.py` compared parent invoices by *number* and its SQL
> never selected `i.uid`, so "same document, different label" was indistinguishable
> from "money on the wrong document" — and it reported the second. It now compares
> the parent **uid** first and has a separate `NUMBER DRIFT` bucket. Re-run:
>
> ```
> [ ok ] WRONG INVOICE — the receipt hangs off a DIFFERENT document (uid)   (0)
> [FAIL] NUMBER DRIFT — same document (uid), the invoice NUMBER differs      (1)
> ```
>
> This is the "guards that could not fail" class (§2.4 of the data-architecture
> document): a diagnostic that reports the wrong finding sends the owner to
> answer a question that was never asked.

### 2.3 This laptop's schema WAS behind the models — fixed by a boot

> **✅ CLOSED 2026-08-03.** The backend was started on this machine and the
> migration runner added every missing column in one pass:
>
> ```
> [Migration] Added users.last_login · table_alterations.public_id
> [Migration] Added invoices.parent_invoice_id · purchase_invoices.parent_invoice_id
> [Migration] Added invoice_line_items.returned_qty · b2b_*.uid …
> [N4-T] tenant-integrity references enforced: 13 rules
> ```
>
> So the schema gap below is gone, and all 13 tenant FKs installed cleanly on
> SQLite. The section is kept because the *reason* it mattered still holds — a
> database that has not been booted recently is not a database you can measure.
>
> The boot also re-confirmed, on this machine, what the audit reported:
> 13 overfilled invoices, 11 staff holding a BizID, the duplicate
> `LCL-OW-0006`, and two M-7 anomalies (`C1-0002` recorded ₹2,533 paid against
> ₹104 of payment rows; `OW-0003` total ₹124 against ₹311 of rows). All are on
> businesses 126/133 — this laptop's copies — and none is auto-corrected, which
> is correct: guessing invents either a debt or a credit.

### 2.3b The original schema-drift finding, for the record

Running `backfill_journals.py` against this laptop's own database fails
immediately:

```
sqlite3.OperationalError: no such column: invoices.parent_invoice_id
```

`parent_invoice_id` is genuinely absent — `invoices` here has 41 columns and the
models expect more. So this database has not had migrations applied since before
that column was added, which is consistent with it being last written on 23 July
and abandoned. It is further confirmation that it is a stale secondary, and one
more reason not to measure or repair anything from it.

The cloud has the column and the same script runs there without complaint.

### 2.4 This laptop's own local audit — recorded, not actionable

`audit_money_integrity.py --db bizassist.db` → **85 issues** (A: 2, B: 53, C1: 1,
C2: 1, E: 1, G: 1, I: 26). These describe a stale secondary containing 10,000
load-test rows. **Do not repair this database.** Kept only so it is not
re-measured and mistaken for the shop's state.

---

## 3. Procedure for the shop laptop

Run on the machine holding the live install. Everything here is **read-only** —
no `--apply` anywhere in this section.

### Step A — confirm you are on the right machine

```bash
cd backend
python - <<'PY'
import sqlite3
c = sqlite3.connect("bizassist.db").cursor()
print("owners      :", c.execute("SELECT COUNT(*) FROM users WHERE parent_business_id IS NULL").fetchone()[0])
print("real invoices:", c.execute("SELECT COUNT(*) FROM invoices WHERE business_id != 9999").fetchone()[0])
print("newest      :", c.execute("SELECT MAX(created_at) FROM invoices").fetchone()[0])
print("outbox      :", c.execute("SELECT COUNT(*) FROM sync_queue WHERE synced_at IS NULL").fetchone()[0])
for r in c.execute("SELECT id, public_id, business_name FROM users WHERE parent_business_id IS NULL ORDER BY id"):
    print("   ", r)
PY
```

**You are on the right machine if** the newest invoice is on/after **2026-07-30**
and `LCL-OW-0037` exists. If the newest is 2026-07-23, you are on `Salma_B` again.

### Step B — let it catch up first

Do **not** compare a laptop that has not synced. Bring it online, let the worker
drain, and confirm:

* Settings → Ops & Health → outbox depth **0**, inbox held **0**
* `LCL-OW-0037` is present and shows one ₹124 Bank payment

Comparing before this step will re-report §2.1 as corruption.

### Step C — measure this machine

```bash
python scripts/audit_money_integrity.py --db bizassist.db
```

### Step D — the cross-database comparison that actually counts

```bash
python scripts/audit_payment_attachment.py \
    --local bizassist.db \
    --cloud "$BIZASSIST_AUDIT_DATABASE_URL"
```

Note `--local` takes a **path**, not a `sqlite:///` URL — the script refuses to
guess, correctly.

Then check whether `fab17765` still disagrees:

```bash
python scripts/inspect_invoice.py LCL-OW-0006 --db bizassist.db
python scripts/inspect_invoice.py LCL-OW-0024 --db "$BIZASSIST_AUDIT_DATABASE_URL"
```

### Step E — dry-run the repairs, read them, then decide

```bash
python scripts/repair_line_items_by_invariant.py --db bizassist.db
python scripts/backfill_journals.py --db bizassist.db
```

---

## 4. Gates before ANY `--apply`

Nothing has been written. These three are open and are the owner's to answer:

1. **A restorable Supabase snapshot exists.** Every repair script requires
   `--i-have-a-restorable-backup`, which is an *attestation*, deliberately built
   so a human asserts it. It is not a flag anyone else can supply on your behalf.
2. **The 18 review-needed invoices** (§1.3) — header wrong, or lines wrong? Only
   the printed/filed copy settles it.
3. **`fab17765`** (§2.2), *if* it survives step D — which invoice did the customer
   actually pay against?

Two standing constraints that apply to every repair:

* **Run each repair on BOTH databases, separately.** There are still no
  tombstones, and these scripts delete over raw connections, so
  `Mapper.after_delete` never fires and no DELETE is ever queued. A row removed
  on one side stays on the other indefinitely.
* **The 4 open shifts are not scriptable.** `closing_cash_actual` is a COUNT, not
  a calculation. Close them from the register screen.

---

## 5. Credential hygiene

The Supabase connection string was pasted into a chat transcript on 2026-08-03 to
run the measurements above. **Rotate that password.** Nothing in this document
requires the old one.

When rotating, note that the runbook deliberately uses
`BIZASSIST_AUDIT_DATABASE_URL` and **not** `DATABASE_URL`, so a money script can
never inherit whatever the application happens to be pointed at:

```bash
export BIZASSIST_AUDIT_DATABASE_URL="postgresql://…"
```

---

## 5b. Worked example — `synced_at` does not mean applied (2026-08-03 20:25–21:00)

The clearest demonstration this project has of `DATA_ARCHITECTURE` §2.3, observed
live on business 133 (BA-Y0DAFT) while restoring sync after the token expiry.

### The stall

72 outbox rows, all `invoice_line_items`, retrying every ~45 s behind an HTTP 500:

```
overfill guard: line items for invoices 821 would total 565.65,
exceeding the billed amount 310.22
```

The guard was **right** — the row is a phantom line on a locally-overfilled
invoice. The defect is that refusing one row killed the batch: see C-7 in
[`PLATFORM_STATE_AND_PENDING_WORK_2026-08-03.md`](PLATFORM_STATE_AND_PENDING_WORK_2026-08-03.md),
where this is recorded as a **dialect** bug (`RaiseException` is `InternalError`
on Postgres, `IntegrityError` on SQLite, and only the latter is caught per row).

### What was done, and what each step proved

| Action | Result |
|---|---|
| Marked **25** rows refused (line items on the 8 overfilled invoices), with a reason on each | Unblocked the queue; **47** pushed, **37** delivered |
| Queued `register_shifts#2` (uid `c7704bac…`) — **never queued in its life** | ✅ Landed on the cloud as id 31. A genuine M-20a gap, now closed |
| Queued `customers#58` — also never queued | ✅ Landed |
| Re-queued the 6 parent invoices 821–826 | ❌ **Acked and lost — again** |

### The finding

The six invoices are stamped `synced_at` locally and are **absent on the cloud**,
verified by querying Supabase directly rather than trusting the flag. The cause
is a numbering collision — both sides minted the same numbers for *different*
documents while sync was down:

| Number | LOCAL uid | CLOUD uid |
|---|---|---|
| LCL-OW-0024 | `32723a94…` | `66db68e4…` |
| LCL-OW-0025 | `772b4130…` | `ee441452…` |
| LCL-OW-0026 … 0029 | all differ | all differ |

`invoices UNIQUE (business_id, invoice_id)` rejects the local row; the rejection
is **acked on purpose** (`routes/sync.py:753`, *"ack either way so it isn't
re-sent every cycle"* — M-13, because refusing would stall the outbox behind an
unappliable row); `synced_at` is stamped; the row leaves the outbox; the invoice
is silently absent on the cloud. Its line items then defer for ever on a parent
that will never arrive.

**Nothing here is a new bug.** It is the documented M-13 trade-off meeting a real
divergence, and the outcome is exactly what §2.3 predicted.

### The blind spot worth remembering

An **acked-but-absent parent** is invisible to every recovery path:

* `find_unqueued_syncable_rows` / `POST /api/sync/heal` — defines missing as
  *never queued*. These were queued. **It cannot see them.** (It *did* correctly
  find the shift and the customer.)
* `CHILD_SPECS` parity — compares `invoice_line_items` and `invoice_payments`
  only. Never invoices.
* The **presence sweep** added 2026-08-03 (C-5) — *does* detect it, and
  deliberately does not repair.

So today the only thing that would have surfaced these six is a detection-only
sweep. That is the argument for finishing C-5's repair story, carefully.

### Resolution

`scripts/resolve_duplicate_invoice_numbers.py`, with the owner present — a number
printed on a customer's copy must not be silently reassigned, and here there are
documents on **both** sides holding each number. It also clears the `LCL-OW-0006`
duplicate blocking the M-3 unique index, which is the same divergence one step
earlier.

**State at the end:** 62 of 72 delivered; 10 line items correctly held and
visible; 6 invoices blocked on the numbering decision; sync otherwise healthy.

---

## 6. One-line summary

**The cloud is measured and mostly healthy** — 47 journal-less documents, 31
line-item overfills, 2 b2b orders and 4 open shifts, with the old ₹124 double
payment and the cross-tenant receipt both already resolved. **The local side has
not been measured at all**, because the laptop used was a stale secondary. Step 3
is the real starting point, and nothing should be applied until §4 is answered.
