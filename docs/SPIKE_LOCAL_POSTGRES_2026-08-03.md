# Spike — local Postgres: a scoped branch plan

**Date:** 2026-08-03
**Status:** ready to run
**Timebox:** 5 working days, hard stop
**Companion to:** [`DECISION_LOCAL_POSTGRES_2026-08-03.md`](DECISION_LOCAL_POSTGRES_2026-08-03.md)

## 0. What this spike is for

The argument for replacing local SQLite with Postgres has one strong leg (the
dialect tax is real and compounding — 52 runtime branches, two implementations of
every money invariant) and one weak leg ("sync gets clean" — it does not; see the
decision document §3).

Neither side of that has been settled by evidence. **This spike replaces the
argument with six measurements.** Its deliverable is a *decision with numbers
attached*, not a migration.

**It is explicitly allowed to fail.** A spike that concludes "no" in two days is
a success — it cost two days and closed a question that would otherwise resurface
every quarter.

---

## 1. Rules of engagement

1. **Branch `spike/local-postgres`. Never merged.** Findings come back as a
   document and, at most, a follow-up PR written from scratch. A long-lived
   migration branch that has to be rebased onto a moving `main` is its own tax,
   and it is how "parallel work" quietly becomes the most expensive option.
2. **Hard stop at 5 days.** If Q1–Q5 are not answered, the answer is "not now" —
   that is a real result, not a failure to finish.
3. **Questions run in the given order.** Q1 is a gate. Do not spend a day on
   installer size before knowing whether upgrades are automatable.
4. **Every answer is a number or a yes/no with a command attached.** "Feels
   faster" is not an answer. If a question cannot be measured, record that it
   could not be measured — do not estimate it (rule 33).
5. **No production data. No Supabase credentials on the branch.** Use a seeded
   local cluster.
6. **Do not touch `main`.** The three one-liners and the CI step from the audit
   ship independently — they are valuable under every outcome of this spike.

---

## 2. Q1 — Can a major-version upgrade run unattended? · **THE GATE** · Day 1

### Why this is first

`desktop/package.json` ships **silent auto-updates** via `electron-updater`. If
an update built against PG *N* reaches a machine holding a PG *N−1* data
directory, the server will not start until the cluster is upgraded. On a billing
product that means a shop opens on Monday and cannot take money.

`ARCHITECTURE.md` §8.3 already names the rule: *"the daily money flow is
sacrosanct."* An unattended, unsupervised cluster upgrade on a customer's Windows
machine is the single largest risk in this whole proposal, and it is **permanent**
— it does not get cheaper with scale or with time.

### Be fair to the proposal — there are three candidate answers

Do not test only `pg_upgrade`. Test all three; the middle one is the most likely
to work:

| Strategy | Mechanism | Watch for |
|---|---|---|
| **A · `pg_upgrade`** | Ship old + new binaries; stop cluster; `pg_upgrade --check` then run | Needs both binary sets (installer size ×2 for the PG part); `--link` failure can leave the old cluster unusable; fiddly on Windows |
| **B · dump → restore** | `pg_dump` old cluster → initdb new → restore | Much simpler and more robust at these data sizes. Cost is downtime proportional to DB size — measure it |
| **C · pin the major version** | Ship one PG major and never move it | Genuinely viable for years. Ends at EOL and the problem returns, larger |

Strategy B is the realistic candidate for a few-hundred-MB shop database. **Give
it the honest test** — if B works reliably and its downtime is acceptable, Q1
passes and the spike continues.

### Procedure

```bash
# 1. Build a PG (N-1) cluster, seed it with a realistic shop
#    (use backend/seed_load_test.py for volume)
# 2. Snapshot the data directory
# 3. Attempt each strategy unattended — no human at the keyboard
# 4. Kill the process mid-upgrade. Reboot the VM mid-upgrade.
#    Fill the disk mid-upgrade.
```

Step 4 is the real test. A power cut during an upgrade is a normal event in
Indian retail, and it is what the desktop app's auto-updater will eventually walk
into.

### Pass / fail

| | |
|---|---|
| **PASS** | At least one strategy completes unattended, is idempotent on retry, and **leaves a working billable database after an interrupted run** — either upgraded or cleanly rolled back |
| **FAIL** | Every strategy needs a human, or an interruption can leave a cluster that will not start |

> **KILL CONDITION.** If Q1 fails, **stop the spike and close the question.**
> Do not proceed to Q2–Q6. The remaining benefits cannot outweigh "an auto-update
> can stop a shop from billing", and no amount of deleted dialect code buys that
> back.

Record the answer in one line, with the command that produced it.

---

## 3. Q2 — Does the suite pass on Postgres? · Day 1–2

Partly free: the CI step added on 2026-08-03 (*Run Sync & Tenant Suites on
Postgres*) already answers a large part of this on `main`, and **its first run is
itself a finding** — the Postgres half of `ensure_tenant_fks` has never executed
anywhere.

On the branch, go further and run **everything**:

```bash
cd backend
BIZASSIST_TEST_DATABASE_URL=postgresql://postgres:pass@localhost:5432/spike_test \
JWT_SECRET=dev-test-secret-please-change-0123456789abcdef \
GROQ_API_KEY=mock \
python -m pytest -q -p no:randomly
```

Baseline to beat, measured 2026-08-03 on SQLite: **2,032 passed · 6 skipped · 0
failed** (2,038 collected, 209 s with `-n auto`).

### Record

- Pass/fail/error counts, and **the list of failures grouped by cause**
- For each failure: is it (a) a genuine dialect bug in product code — *the
  point of the exercise*, (b) a test that hard-codes SQLite behaviour, or (c) a
  fixture/isolation problem?
- Wall-clock time vs the 209 s SQLite baseline

### Pass / fail

| | |
|---|---|
| **PASS** | ≤ 25 failures and every one classified; no unexplained failure in the money or sync layers |
| **CONCERN** | Failures concentrated in `core/accounting` or `core/sync` — that is drift that has been live all along, and it is a finding worth having regardless of the outcome |

Category (a) failures are **valuable output even if the spike is rejected** —
they are latent cloud bugs. Log them as separate issues immediately, on `main`,
before the branch is discarded.

---

## 4. Q3 — Installer size and first-run cost · Day 2

The bundle already carries torch (~240 MB) through the PyInstaller onedir spec.

### Measure

```bash
cd desktop && npm run dist:win
```

- Installer size before vs after, in MB
- **First-run time**: `initdb` + schema creation + service start, on a cold
  low-end Windows machine — not your dev box
- Idle RSS of the Postgres process (a till may have 4 GB total)
- Whether it needs Administrator to install a service, or can run supervised as
  a child process of the Electron main process

### Pass / fail

| | |
|---|---|
| **PASS** | Installer delta < 250 MB, first run < 60 s, idle RSS < 200 MB, **no Administrator requirement** |
| **FAIL** | Needs Admin (kills unattended install on managed shop machines) or first run > 3 min |

---

## 5. Q4 — Performance against the published numbers · Day 3

The benchmarks the product currently advertises are **SQLite numbers** — an
in-process library call, no socket. Postgres adds a round-trip per statement.

Baseline (from `SECURITY_AND_FINANCIAL_REVIEW_2026-07-30.md` §4, avg / min):

| Operation | SQLite avg | min |
|---|---|---|
| SHA-256 hash chain verification | 0.91 ms | 0.52 |
| Stock movement (1 yr, 2,000 items) | 2.29 ms | 1.99 |
| Day book (today, 200 items) | 3.03 ms | 2.64 |
| Audit journal (1 yr, 2,000 items) | 3.69 ms | 2.45 |
| Balance sheet | 9.92 ms | 6.64 |
| P&L (1 yr) | 9.93 ms | 8.38 |
| Trial balance | 12.21 ms | 9.90 |
| Self-healing diagnostic | 15.41 ms | 10.19 |

```bash
cd backend && python benchmark_reports_enhanced.py
```

Run it against both engines on the same machine with the same seeded data. Report
**p50 and p95**, not just the average — the counter cares about the slow bill,
not the median one.

Also measure the one that matters most and is not in that table: **end-to-end POS
checkout latency** (the `/sales` path with stock deduction, row locking, journal
posting and the outbox write).

### Pass / fail

| | |
|---|---|
| **PASS** | p95 checkout regression < 2× and still comfortably inside "sub-second billing" |
| **CONCERN** | Any report crossing 100 ms, or checkout p95 > 250 ms |

If Postgres wins on the large-table reports (likely — better planner, real
indexes on 20k+ row scans), **record that too.** It is a legitimate point in
favour and this spike is not looking for a predetermined answer.

---

## 6. Q5 — How much code actually disappears? · Day 3–4

This is the **benefit measurement**. The entire honest case for the migration
rests here, so measure it rather than estimating it.

Baseline, measured 2026-08-03:

```bash
# 52 dialect branches in runtime code (excludes alembic + tests)
grep -rn 'dialect.name\|is_sqlite\|is_postgres\|startswith("sqlite")\|startswith("postgres")' \
  --include=*.py backend/ | grep -v "/tests/\|/alembic/" | wc -l
```

Candidates for deletion — confirm each on the branch:

| Target | What it is |
|---|---|
| `core/accounting/db_invariants.py` — the SQLite trigger half | Two implementations of every money rule become one. **The single most valuable deletion on this list** — it is the safety-critical layer |
| `database/migration.py::_portable_ddl()` + 13 branches | Exists only to translate types |
| `backend/scripts/_dbcompat.py` | The compat layer |
| `tests/test_dbcompat_and_sql_portability.py` | The gate that exists because of the split |
| `database/db.py` — pragma/pool block | `PRAGMA foreign_keys`, `busy_timeout`, NullPool |
| `services/sync_worker.py:1479` | `INSERT OR IGNORE` → `ON CONFLICT DO NOTHING` |

### Record

- Net lines deleted vs added (**be honest about added** — cluster lifecycle
  management, supervision, health checks and the upgrade path from Q1 are all new
  code that has to be written and maintained)
- Dialect branches: 52 → **?**
- Whether `db_invariants.py` genuinely collapses to one implementation, or just
  trades triggers for a different conditional

### Pass / fail

| | |
|---|---|
| **PASS** | Net deletion, dialect branches < 10, and `db_invariants` is single-implementation |
| **FAIL** | Net *addition* once cluster management is counted — at which point the maintainability argument has inverted and the case is gone |

---

## 7. Q6 — Local at-rest encryption on Postgres · Day 4

C-1 in the audit: `ARCHITECTURE.md` §2.8 specifies SQLCipher, it does not exist,
and the local database is plaintext — every customer, every invoice, the whole
price book.

SQLCipher is a drop-in for SQLite. Community Postgres has no mainline TDE, so
this needs a real answer rather than an assumption:

1. Encrypted container for the data directory (e.g. a VeraCrypt/BitLocker-backed
   volume) — how is the key held, and what happens on an unclean shutdown?
2. OS-level (BitLocker) — **not controllable** on a shop's machine; is that
   acceptable as the answer?
3. `pgcrypto` on the crown-jewel columns only — partial, and it breaks indexing
   and search on those columns
4. A third-party TDE fork — licensing, support, and it means you no longer ship
   stock Postgres

### Record

Which option, its key-custody design, and the honest gap versus what SQLCipher
would have given for a day's work.

### Pass / fail

| | |
|---|---|
| **PASS** | A concrete option with a written key-custody design |
| **CONCERN** | The answer is "rely on BitLocker" — that is a decision to *not* encrypt at rest, and it must be made deliberately and in writing, not inherited as a side effect of an engine choice |

---

## 8. Combining the answers

| Outcome | Decision |
|---|---|
| **Q1 fails** | **Reject.** Close the question permanently. Record it in the decision doc so it is not re-proposed |
| Q1 passes, Q5 shows net addition | **Reject.** The maintainability case was the case |
| Q1–Q5 pass, Q6 is "BitLocker only" | **Owner call.** You are trading local at-rest encryption for schema convenience. Decide it explicitly |
| All six pass | **Proceed — but as a rewrite, not a migration.** With no production data there is nothing to migrate: change the models, squash alembic to a new baseline, recreate. See decision doc §9 for what a *real* migration would need if data ever does exist |

### Regardless of outcome, these are kept

* Every category-(a) failure from Q2 — latent cloud bugs, valuable on `main` today
* The benchmark comparison — you currently publish SQLite numbers with no
  counterpart
* The Q5 line count — it sizes the dialect tax honestly, and if the answer is
  "stay on SQLite", it tells you how much a *better compat layer* is worth
* The Q6 answer — C-1 needs deciding either way, and the window for the cheap
  version closes as soon as there are installs

---

## 9. What this spike is deliberately not asking

Kept out of scope so the timebox holds. All three are separate decisions:

* **Option C (uid primary keys).** Different problem, and the one that actually
  ends the divergent-id issue. Decision doc §6.3.
* **Option E (PowerSync / ElectricSQL / Turso).** Would make the engine question
  partly moot. Its own spike.
* **Whether the local install is an appliance or a shop server.** This is the
  variable that most changes the answer, and it is a **product** decision, not an
  engineering one. Answer it before reading the spike results — a Postgres
  service is unremarkable on a shop's server machine and disproportionate on a
  single till. If the LAN-master direction is real, weight Q3 much less heavily.

---

## 10. Owner sign-off before starting

- [ ] Appliance or shop server? (§9 — changes how Q3 is weighted)
- [ ] Is 5 days the right timebox?
- [ ] Who runs it, and do they have a spare Windows machine for Q1 and Q3?
      (Q1's interrupted-upgrade test must not run only in a VM on a dev box.)
- [ ] Confirm: findings return as a document; the branch is never merged.
