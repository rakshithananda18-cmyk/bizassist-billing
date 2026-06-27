# BizAssist — Test Automation Strategy

*Created 2026-06-27. The layered, all-free/open-source automation stack and how to run it. Companion to the manual plans: [`MANUAL_TEST_PLAN.md`](MANUAL_TEST_PLAN.md) (scenarios) and [`RLS_FAIL_CLOSED_TEST_PLAN.md`](RLS_FAIL_CLOSED_TEST_PLAN.md) (S-1).*

## Why layered (not one framework)

No single tool covers a 2-backend (SQLite local + Postgres cloud) + 2-frontend + real-time-sync product. Each layer tests at the cheapest level that can catch the bug:

| Layer | Tool (free/OSS) | Scope | Status |
|---|---|---|---|
| Unit / component (FE) | **Vitest + Testing Library** | React components, hooks, invoice math | ✅ in use (`frontend-*/src/__tests__`) |
| API / logic (BE) | **pytest** | routes, sync/migration logic, accounting | ✅ in use (693 passing) |
| **E2E browser** | **Playwright** (Apache-2.0) | login → nudge → sync, multi-terminal real-time, POS | 🆕 scaffolded here (`frontend-billing/e2e/`) |
| **Postgres / RLS** | **pytest + testcontainers[postgres]** (Apache-2.0) | tenant isolation, RLS fail-closed (S-1) on real Postgres | 🆕 scaffolded here (`backend/tests/test_rls_postgres.py`) |

All four are MIT/Apache-licensed and free, run locally and in GitHub Actions.

## Why Playwright (over Cypress/Selenium)

- **Multi-context** — `browser.newContext()` ×2 gives two independent "terminals" in one test, so the A→B real-time sync scenario (the trust test) is a few lines, not a second machine.
- Auto-waiting (no flaky `sleep`), trace viewer for debugging CI failures, runs Chromium/Firefox/WebKit, parallel by default.
- First-class against a Vite dev server (`webServer` auto-start).

## Why testcontainers for RLS

S-1 (RLS fail-closed) **cannot be tested on SQLite** (no RLS) and you don't want to test against prod Supabase. `testcontainers[postgres]` boots a throwaway Postgres in Docker per test session — real RLS, zero prod risk, works in CI. This is what makes the `RLS_FAIL_CLOSED_TEST_PLAN.md` matrix automatable.

---

## How to run

### 1. Backend (pytest) — already works
```powershell
cd backend
..\venv\Scripts\python.exe -m pytest -q
```

### 2. Frontend components (Vitest) — already works
```powershell
cd frontend-billing
npm test
```

### 3. E2E (Playwright) — new
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

### 4. Postgres / RLS (pytest + Docker) — new
```powershell
# Requires Docker running locally (or a CI service container).
pip install "testcontainers[postgres]" psycopg2-binary --break-system-packages
cd backend
..\venv\Scripts\python.exe -m pytest tests/test_rls_postgres.py -v
# Or point at an existing throwaway PG instead of Docker:
$env:TEST_PG_URL = "postgresql://user:pass@localhost:5432/rls_test"; pytest tests/test_rls_postgres.py -v
```
These tests **skip automatically** if neither Docker nor `TEST_PG_URL` is available, so they never block the normal suite.

---

## CI (GitHub Actions sketch)

```yaml
jobs:
  backend:
    runs-on: ubuntu-latest
    services:
      postgres: { image: postgres:15, env: { POSTGRES_PASSWORD: pass, POSTGRES_DB: rls_test }, ports: ['5432:5432'] }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: pip install -r backend/requirements.txt pytest "testcontainers[postgres]" psycopg2-binary
      - run: cd backend && pytest -q                       # 693 logic tests (SQLite)
      - run: cd backend && TEST_PG_URL=postgresql://postgres:pass@localhost:5432/rls_test pytest tests/test_rls_postgres.py -v
  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
      - run: cd frontend-billing && npm ci && npx playwright install --with-deps
      - run: cd frontend-billing && npm run e2e   # spins the vite server via playwright webServer
```

---

## Mapping: manual scenarios → automated tests

| Manual (`MANUAL_TEST_PLAN.md`) | Automated by |
|---|---|
| §1 local→cloud migration (logic) | pytest `test_sync_migration_fixes.py`, `test_uid_cross_db.py` |
| §2 multi-system real-time sync | Playwright `e2e/realtime-sync.spec.js` (two contexts) |
| §2c fresh-device login + nudge | Playwright `e2e/auth-nudge.spec.js` |
| §2d durable-uid no-collision | pytest `test_uid_cross_db.py` (+ E2E re-sync assertion) |
| §6 RLS / tenant isolation, S-1 | pytest `test_rls_postgres.py` (testcontainers) |

**Net:** the logic + RLS layers can be fully green in CI today; the E2E specs are scaffolds — confirm selectors/seed accounts against your running stack, then wire into CI.
