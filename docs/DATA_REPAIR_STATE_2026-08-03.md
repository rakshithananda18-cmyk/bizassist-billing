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
* **`Load Test Shop 9999` has no BizID at all**, so it cannot sync and never has.
  Its 10,000 invoices and 4,897 payments are noise in any local↔cloud comparison
  and must be excluded from every count.

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

### 1.4 Still to dry-run on the cloud

`scripts/backfill_journals.py` exists and is the named fix for section B's 47
journal-less documents. **Not yet run, not even dry.** Note that 18 of the 47 are
`OPEN-31 … OPEN-50` shift-opening floats (₹15,000 / ₹2,000, biz 7), which may be
a different question from the 29 real sale documents — worth reading the dry run
before assuming one fix covers both.

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

**Action: re-run §3 on the shop laptop. If `fab17765` still disagrees there, it
is real and needs the owner's memory** — which invoice did that customer actually
pay against, `LCL-OW-0006` or `LCL-OW-0024`?

### 2.3 This laptop's own local audit — recorded, not actionable

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

## 6. One-line summary

**The cloud is measured and mostly healthy** — 47 journal-less documents, 31
line-item overfills, 2 b2b orders and 4 open shifts, with the old ₹124 double
payment and the cross-tenant receipt both already resolved. **The local side has
not been measured at all**, because the laptop used was a stale secondary. Step 3
is the real starting point, and nothing should be applied until §4 is answered.
