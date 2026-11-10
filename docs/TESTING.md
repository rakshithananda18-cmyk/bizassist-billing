# BizAssist — Test Automation Strategy

*Created 2026-06-27; reconciled 2026-10-28. The layered automation stack and how to run it. Companion to the archived scenario plans: [`MANUAL_TEST_PLAN.md`](archive/MANUAL_TEST_PLAN.md) and [`RLS_FAIL_CLOSED_TEST_PLAN.md`](archive/RLS_FAIL_CLOSED_TEST_PLAN.md).*

Current commands, dated suite results, skips and verification limits are recorded in [2026-10-28 release checks](release/2026-10-28-verification.md). Test counts in older reviews are historical snapshots, not current pass totals. Fail-closed RLS is implemented; its live Postgres verification is separate from SQLite/mock coverage.

## Why layered (not one framework)

No single tool covers a 2-backend (SQLite local + Postgres cloud) + 2-frontend + real-time-sync product. Each layer tests at the cheapest level that can catch the bug:

| Layer | Tool (free/OSS) | Scope | Status |
|---|---|---|---|
| Unit / component (FE) | **Vitest + Testing Library** | React components, hooks, invoice math | ✅ in use (`frontend-*/src/__tests__`) |
| API / logic (BE) | **pytest** | routes, sync/migration logic, accounting | In use; see the dated record for results and selected/full-suite scope |
| **E2E browser** | **Playwright** (Apache-2.0) | login → nudge → sync, multi-terminal real-time, POS | Specs and a CI job exist (`frontend-billing/e2e/`); credential-dependent scenarios can skip |
| **Postgres / RLS** | **pytest + testcontainers[postgres]** (Apache-2.0) | tenant isolation and fail-closed policies on real Postgres | Implemented tests and a Postgres CI service gate exist; verify the run result separately |

All four are MIT/Apache-licensed and free, run locally and in GitHub Actions.

## Why Playwright (over Cypress/Selenium)

- **Multi-context** — `browser.newContext()` ×2 gives two independent "terminals" in one test, so the A→B real-time sync scenario (the trust test) is a few lines, not a second machine.
- Auto-waiting (no flaky `sleep`), trace viewer for debugging CI failures, runs Chromium/Firefox/WebKit, parallel by default.
- First-class against a Vite dev server (`webServer` auto-start).

## Why testcontainers for RLS

S-1 (RLS fail-closed) **cannot be tested on SQLite** (no RLS) and you don't want to test against prod Supabase. `testcontainers[postgres]` boots a throwaway Postgres in Docker per test session — real RLS, zero prod risk, works in CI. This is what makes the `RLS_FAIL_CLOSED_TEST_PLAN.md` matrix automatable.

---

## How to run

### 1. Backend (pytest)

Activate a working Python virtual environment with the repository's test dependencies installed, then confirm `python --version` and `python -m pytest --version`. A copied or moved `venv` may refer to an interpreter that no longer exists; recreate that environment instead of relying on a machine-specific path.

```powershell
cd backend
python -m pytest -q
```

### 2. Frontend components (Vitest) — already works
```powershell
cd frontend-billing
npm test
```

### 3. E2E (Playwright)
```powershell
cd frontend-billing
npm install              # picks up @playwright/test (added to devDependencies)
npx playwright install   # one-time: download browsers
# Preconditions: local backend on :8001 and a seeded cloud account reachable (see spec headers)
npm run e2e              # headless
npm run e2e:headed       # watch it run
npx playwright show-report
```
Configure via env (don't hardcode creds): `E2E_BASE_URL` (default `http://localhost:5174`), `E2E_USER`, `E2E_PASS`, `E2E_CLOUD_URL`.

Use a disposable seeded account and isolated backend data for write scenarios. A green run with credential-dependent scenarios skipped does not establish two-terminal or fresh-device sync behaviour. Physical printer output, a real offline/reconnect cycle and two-server hosting transitions remain pending unless the dated record documents those checks.

### 4. Postgres / RLS (pytest + Docker)
```powershell
# Run in the working virtual environment; requires Docker or a throwaway PG.
python -m pip install "testcontainers[postgres]" psycopg2-binary
cd backend
python -m pytest tests/test_rls_postgres.py -v
# Or point at an existing throwaway PG instead of Docker:
$env:TEST_PG_URL = "postgresql://user:pass@localhost:5432/rls_test"
python -m pytest tests/test_rls_postgres.py -v
```
These tests **skip automatically** when their Postgres dependencies are unavailable. Record skips explicitly; they do not establish that live RLS checks passed. Never point this destructive test fixture at a production database.

---

## CI (GitHub Actions)

The executable configuration is [`.github/workflows/ci.yml`](../.github/workflows/ci.yml). It runs the SQLite backend logic suite, a real Postgres RLS service gate, selected financial/sync/tenant suites against Postgres, the billing and AI frontend suites, and a Playwright job with an isolated test backend. Inspect each job's current result and skips rather than treating the existence of the workflow as a pass.

The current Playwright job supplies `E2E_BASE_URL`; the cloud-account scenarios still need their documented seeded credentials and endpoints. Keep live two-server and printer checks in the dated verification record until that evidence exists.

---

## Mapping: manual scenarios → automated tests

| Manual ([archived scenario plan](archive/MANUAL_TEST_PLAN.md)) | Automated by |
|---|---|
| §1 local→cloud migration (logic) | pytest `test_sync_migration_fixes.py`, `test_uid_cross_db.py` |
| §2 multi-system real-time sync | Playwright `e2e/realtime-sync.spec.js` (two contexts) |
| §2c fresh-device login + nudge | Playwright `e2e/auth-nudge.spec.js` |
| §2d durable-uid no-collision | pytest `test_uid_cross_db.py` (+ E2E re-sync assertion) |
| §6 RLS / tenant isolation, S-1 | pytest `test_rls_postgres.py` (testcontainers) |

**Verification boundary:** isolated logic, component and Postgres gates cover different failure modes. None alone proves live two-device delivery, physical printing or deployed backup recovery. Record the actual environment and result for each layer.
