# Phase / Task Completion Checklist — BizAssist "Definition of Done"
*Run this every time a phase **or** a task is completed (or before recommending it as done). A feature is not "done" until all three gates pass. Keep it strict — this is what keeps the ecosystem solid as it grows.*

---

## Gate 1 — Tests (run them; if none exist, create them)

- [ ] **Run the full suite** before claiming done: `run_tests.bat` (backend `pytest` + `frontend-billing` & `frontend-ai` `vitest`). Must be **all green**.
- [ ] **No tests for the thing you built? Write them first.** A new endpoint, command/service, money calculation, or logic-heavy component ships *with* its test, not "later."
  - Backend: unit test the command/service (the math, the state change) **and** an API test via `TestClient` (auth + scoping).
  - Frontend: unit/smoke the logic (formatting, totals, reducers) and the one critical flow (e.g. save-a-bill).
- [ ] **Security & money get negative tests.** Anything tenant-scoped: prove business A **cannot** read business B's data. Anything financial: prove idempotency and exact ledger postings.
- [ ] **Name the test in the master-plan tracker.** A roadmap item is only ✅ once its named test passes — `🟡 exists in code` ≠ done.
- [ ] Fix flakiness at the root (e.g. seeded/stale test DB), don't paper over it.

## Gate 2 — Logging (info + debug, traceable)

- [ ] **Every module has a named logger:** `logging.getLogger("bizassist.<area>")` (backend) / the `logger` util (frontend). No bare `print`.
- [ ] **INFO on every state change** with the keys needed to trace it: `business_id`, invoice no., ids, amounts, movement type. Keep the aligned `[AREA] ...` prefix style (`[BILLING]`, `[STOCK]`, `[CONNECTION]`) so a log line can be traced end-to-end.
- [ ] **DEBUG on the flow**: inputs received, computed values, which branch was taken, what was skipped — enough to reconstruct *why* without a debugger. (DEBUG is off in prod, so be generous.)
- [ ] **Errors are logged with context + `exc_info`** and re-raised or handled — **never** a silent `except: pass`.
- [ ] **Frontend:** log key user actions and **every API failure** (`logger.error` with status + detail) so a counter problem is traceable from the browser.
- [ ] One action = one traceable story across layers (UI → API → command → ledger).

## Gate 3 — Master plan alignment + "make it the smartest"

- [ ] **Update `BIZASSIST_ECOSYSTEM_MASTER_PLAN.md` §10.0 Build Status Tracker** — flip ✅/🟡/⬜, date it, note what changed. Keep it the single source of truth.
- [ ] **Re-check alignment to the 4 goals** (easy to use · secure & unbreakable · addictive & sticky · makes money) **and the ecosystem** (one connected B2B chain — distributor→wholesaler→retailer, "share the deal, not the books"). If the work drifted from these, say so and correct course.
- [ ] **Add to §10.1 "Smartest-App Recommendations"** — at least one concrete idea this work unlocks to make BizAssist *the smartest* billing app: zero-typing automation, proactive nudges, predictive stock/price/credit, AI-assisted entry, one-tap actions. Pull the strongest into a phase.
- [ ] Confirm the change is **smart, easy, fully synced, automated, and solid** — the product bar. If it's none of those, it's not done.

---

### How to use
- When I (or any agent) report a phase/task complete, the report must show these three gates addressed — tests named + green, loggers added, master plan updated with a smartest-app note.
- If a gate can't be satisfied (e.g. tests can't run in an env), say so explicitly and what's needed to close it — don't mark done.
