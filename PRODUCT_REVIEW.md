# BizAssist — Product, Architecture & Security Review

*Review date: 2026-06-26 · Reviewer: AI engineering review pass · Scope: `bizassist-billing/` (backend ~43k LOC Python, 2 React frontends, 70 test files / 541 test fns, 24 Alembic migrations).*

**Linked docs:** [Lean core plan → `MASTER_PLAN_CORE.md`](MASTER_PLAN_CORE.md) · [Full plan → `BIZASSIST_ECOSYSTEM_MASTER_PLAN.md`](BIZASSIST_ECOSYSTEM_MASTER_PLAN.md) · [Hosting modes → `HOSTING_MODE_MASTER_PLAN.md`](HOSTING_MODE_MASTER_PLAN.md) · [DoD gate → `PHASE_COMPLETION_CHECKLIST.md`](PHASE_COMPLETION_CHECKLIST.md)

---

## Part A — High-Level (Startup) Review

### Verdict
A genuinely strong, well-disciplined codebase for this stage. The accounting core (posted double-entry + hash chain + period locks), multi-tenant isolation, and offline-first sync are built to a standard most seed-stage billing startups never reach. The product is **buildable and largely built through Phase 4**; the open risk is not "is the code good" but "is the depth proven" (live QA + a clean test run) and "does the network USP get adoption."

| Dimension | Rating | One-line |
|---|---|---|
| Architecture | 🟢 Strong | Clean modular monolith, honest seams, documented trade-offs. |
| Security | 🟢 Strong (1 caveat) | Layered auth + RBAC + RLS + idempotency; RLS is *fail-open* — see S-1. |
| Functionality vs plan | 🟢 On-track | Phases 1–4 done; offline-sync + hosting modes built, depth-QA pending. |
| Data integrity (money) | 🟢 Excellent | Double-entry, tamper-evident chain, two-wall idempotency, period locks. |
| Test coverage | 🟡 Good, unverified here | 541 test fns; could not execute in this sandbox (see note). |
| Scalability (today) | 🟡 Single-worker | Process-local cache/scheduler/rate-limit; needs Redis to scale out. |
| Maintainability | 🟡 Mostly good | `Sales.jsx` god-component + duplicated sync model-maps are the debt. |

### What's impressive
- **Money is deterministic and auditable.** Real posted journal (`journal_entries`/`journal_lines`), SHA-256 hash chain with `verify_chain`, append-only period locks gating all six write paths. This is the moat foundation and it's real, not derived-on-read.
- **Exactly-once by design.** Two-wall idempotency (HTTP `X-Client-Request-Id` replay guard + per-command keys), offline outbox, delta-pull cursor. Built for flaky retail networks.
- **Tenant isolation in depth.** App-layer `business_id` filters *plus* Postgres RLS (`FORCE ROW LEVEL SECURITY`, per-table policies, child tables via `EXISTS`), with explicit cross-tenant negative tests.
- **Honest engineering culture.** The build tracker distinguishes ✅ done vs 🟡 "exists in code, depth unverified"; security/money features ship with negative tests; the "Definition of Done" gate is strict. This discipline is the real asset.

### Top risks (startup lens)
1. **Adoption of the network USP is unproven** — the moat (BizID + private ordering network + shared ledger) rests on retailer behaviour, not tech. Validate the manual flow with the pilot before deep Phase 5/6 spend. *(Already flagged in plan §12 — agreed.)*
2. **Single-worker scaling ceiling** — fine for pilots, but caches/scheduler/rate-limiter are process-local. Horizontal scale needs shared state (Redis). Plan it before signing multi-store customers.
3. **RLS fail-open** (S-1 below) — a latent cross-tenant exposure if any future code path forgets to set the tenant context. Cheap to harden now.
4. **Test-count drift / unverified green** — docs cite "555", "431", and code has 541 test fns. Reconcile and produce one CI-stamped pass before claiming "production-proven."

### Recommended next moves (priority order)
1. Run `run_tests.ps1` and pin a single, dated green-suite number into the tracker (closes DoD Gate 1).
2. Harden RLS to **fail-closed** for tenant tables (deny when `app.current_business_id` is unset; allowlist admin/migration paths explicitly).
3. Burn down the 🟡 "needs live QA" items (offline POS save, print/preview, sticky UI) — they're the gap between "built" and "shippable."
4. Schedule the `Sales.jsx` decomposition and de-duplicate the sync `_MODEL_MAP` (single shared module) before they calcify.

---

## Part B — Detailed Review

### B1. Architecture

**Shape:** Modular monolith. `main_groq.py` is a thin wiring entrypoint (app + CORS + RLS middleware + routers). Business logic lives in `services/` and `routes/` (AI/advisor + ops) and `core/` (billing ecosystem domain, split by area: `accounting`, `billing`, `purchase`, `order`, `stock`, `catalog`, `compliance`, `connection`, `sync`, `api`). Two model modules (`database/models.py`, `core/models.py`) share one SQLAlchemy `Base` via neutral mixins in `database/db.py` to avoid an import cycle.

**Hosting modes (per `HOSTING_MODE_MASTER_PLAN.md`):** local (SQLite), cloud (Postgres/Supabase, source of truth — D5), hybrid (local cache + background sync). Engine selection is `DATABASE_URL`-driven; Postgres uses `NullPool` (deliberate, to avoid Supabase connection exhaustion). `/health` dynamically reports `local|cloud|hybrid`.

**AI layer:** 4-tier cost-gated router (conversational → direct/intent SQL → … → LLM) to minimise token spend; grounded over local data; advisory-only (actions gated + audited). Sound separation of "AI advises, money is deterministic."

**Data model decisions (all settled in plan §2):** `business_id` tenancy with no separate `tenants` table (D1); relational line items not JSONB (D3); `stock_ledger` as source of truth with `inventory.stock` as cached projection (D4); hybrid LWW conflict resolution (D2).

**Strengths:** clear seams; domain-split `core/`; honest single-worker guard (warns loudly if `WEB_CONCURRENCY>1`); deterministic Alembic naming convention (needed for SQLite batch migrations).

**Concerns / debt:**
| # | Item | Impact | Recommendation |
|---|---|---|---|
| A-1 | `frontend-billing/src/.../Sales.jsx` god-component (~3,600 lines) | Maintainability, regression risk on the money path | Continue the in-progress extraction (`usePaymentFlow` → `<PaymentPanel>`); it's already underway. |
| A-2 | Sync `_MODEL_MAP` duplicated in `routes/sync.py` **and** `services/sync_worker.py` | Drift risk — a new synced table added in one place only | Hoist to one shared module imported by both. |
| A-3 | Integer autoincrement IDs as cross-DB sync cursor/identity | Fragile across SQLite↔Postgres; ID remapping already needed a fix (commit `37d4169`) | Keep the remapping well-tested; consider UUID/business-scoped keys for synced entities long-term. |
| A-4 | Single-worker constraint (process-local cache/scheduler/rate-limiter) | Hard horizontal-scale ceiling | Move shared state to Redis before multi-instance deploy (already Phase 5). |
| A-5 | Two model modules on one `Base` | Cognitive overhead; must stay aligned | Acceptable; document the boundary in `core/README.md`. |

### B2. Security

**Authentication:** JWT HS256, secret **required** from env (`JWT_SECRET`; padded with a warning if <32 bytes), 24h expiry. Passwords bcrypt-hashed. SSE access via single-use, 30s-TTL random tickets. No hardcoded secrets, no `.env` tracked in git.

**Authorization (RBAC):** Single-source `restrict_cashier`/`require_owner` guard in `services/auth.py`. Owner-only routes (all reports, credit/debit notes, imports, config writes, purchases, connection mutations, manual stock adjust) return 403 for cashiers; frontend hides owner nav as defense-in-depth (backend is authoritative). Covered by `test_roles.py`.

**Multi-tenancy:** Two layers. (1) App-layer `business_id == current_user["id"]` filters on queries. (2) Postgres RLS: `ENABLE`+`FORCE ROW LEVEL SECURITY`, per-table `tenant_isolation` policies, child tables scoped via `EXISTS` on parent, B2B tables scoped on buyer/seller. Privileges revoked from `anon`/`authenticated`/`public`. Identity resolution is correct: at login the JWT `id` is set to `parent_business_id or user.id`, so staff/cashier tokens carry the **owner's** business_id and all routes scope consistently. Cross-tenant negative tests exist (`test_rls_policies.py`, `test_connections_security.py`, isolation tests across modules).

**Data integrity:** Tamper-evident journal hash chain (`post_entry`, 2dp-stable, GENESIS root, per-business), `verify_chain` endpoint; append-only period locks reject posting into closed periods (422); two-wall idempotency.

**Hygiene:** No `eval`/`exec`/`shell=True`/`verify=False`/`debug=True`; CORS is an explicit allowlist with `allow_credentials=False` and a tight header/method set; the GUC set uses `int(business_id)` (no SQL injection).

**Findings:**
| # | Severity | Finding | Detail & recommendation |
|---|---|---|---|
| S-1 | 🟠 Medium | **RLS is fail-open** | Policies pass when `app.current_business_id` is unset (`... IS NULL OR business_id = ...`). `get_db()` only sets the GUC when a `business_id` is present (postgres). Today this is safe because the HTTP middleware sets it from the JWT and app-layer filters exist — but any future route using `SessionLocal()` directly, or any path that forgets the contextvar, runs with **no tenant filter**. Recommend fail-closed for tenant tables (deny when unset) with an explicit allowlist for migration/admin/scheduler contexts. |
| S-2 | 🟡 Low | **SQLite (local/hybrid) has no RLS** | Isolation there is purely app-layer. Fine for single-merchant local; just ensure the hybrid *push* target (cloud Postgres) is where RLS enforces — it is. Document that local mode trusts the app layer. |
| S-3 | 🟡 Low | **No token refresh / revocation** | 24h JWTs can't be revoked early (e.g., after removing a cashier). Consider a short access token + refresh, or a token-version claim checked against the user row. |
| S-4 | 🔵 Info | **JWT decoded twice** | Once in RLS middleware, once in `get_active_user`. Minor CPU; not a security issue. Could pass the decoded payload via request state. |
| S-5 | 🔵 Info | **Best-effort silent decode in middleware** | Middleware swallows JWT errors (`except: pass`) and lets the route dependency 401. Intentional and correct, but pairs with S-1 — an unset context must not mean "see everything." |

### B3. Functionality vs Plan

Mapped against the master-plan §10 Build Status Tracker and verified against code presence:

| Phase / Area | Plan status | Code evidence | Notes |
|---|---|---|---|
| Phase 1 — Billing/POS/Reports | ✅ | `core/api/sales.py`, `billing/commands.py`, `Reports.jsx`, report endpoints | POS, GST split, tiers, multi-tab. |
| Accounting depth | ✅ | posted journal, hash chain, period locks, trial balance, balance sheet, party ledger | Accountant-grade; strong. |
| Phase 2 — Purchase + OCR | ✅ | `purchases.py`, `purchase_ocr.py`, `purchase_commit` tests | Detect→Map→Confidence→Review→Commit. |
| Phase 3 — B2B connections | ✅ (security gate passed) | `connections.py`, `orders.py`, `test_connections_security.py` | Catalog hides cost/margin; revoke closes pipe. |
| Phase 4 — B2B invoice sync | ✅ core | `order/service.sync_completed_order`, `test_phase4_sync.py` | Exactly-once both-sides post. |
| Hardening — RLS | ✅ (new) | migrations `aea3a6d76429`, `d7e3a9c6f8b1` (Jun 24–25) | See S-1 (fail-open). |
| R7b — Offline sync (client) | 🟡 built, live-QA pending | `frontend-billing/src/sync/*`, `core/api/sync.py`, idempotency | Needs offline `npm run dev` proof. |
| Hosting modes (local/cloud/hybrid) | 🟡→✅ building | recent commits (routing, migration remap, hybrid sync engine) | Mode switching + sync engine landed; depth QA pending. |
| Many UI items (print/preview, sticky bars) | 🟡 | present | Flagged "needs visual QA" honestly. |

**Gaps to close before "production-proven":** the 🟡 items are mostly *depth verification* (live QA + a green test run), not missing features. The plan's own DoD gate (tests named + green, loggers, plan updated) is the right bar; Gate 1 is the one currently open here.

### B4. Verification status (important)

The full backend suite **could not be executed in this review sandbox**: PyPI is network-blocked (no `pip install`) and the committed `venv/` is Windows-only, so heavy deps (torch, chromadb, groq, anthropic, langgraph) can't be provisioned on Linux. This review is therefore **static/structural**, cross-checked against the test files (541 test functions across 70 files) and the build tracker.

**Action for you:** run `run_tests.ps1` (or `run_tests.bat`) locally, confirm all-green, and record the exact count + date in the tracker. Note the doc inconsistency: README/tracker cite both **555** and **431** while the code currently has **541** test functions — reconcile to one number.

---

## Appendix — Evidence index
- Auth/RBAC: `backend/services/auth.py`, `backend/routes/auth.py`, `core/api/staff.py`, `tests/test_roles.py`
- RLS: `backend/alembic/versions/aea3a6d76429_*`, `d7e3a9c6f8b1_*`; `database/db.py` (GUC), `main_groq.py` (middleware); `tests/test_rls_policies.py`
- Money integrity: `core/accounting/posting.py` (hash chain), `period_lock.py`, `core/sync/idempotency.py`
- Sync: `routes/sync.py`, `services/sync_worker.py`, `core/api/sync.py`, `frontend-billing/src/sync/*`
- Plans: `BIZASSIST_ECOSYSTEM_MASTER_PLAN.md` §10/§12/§13, `HOSTING_MODE_MASTER_PLAN.md`, `PHASE_COMPLETION_CHECKLIST.md`
