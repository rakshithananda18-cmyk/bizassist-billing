# Implementation Plan

## Overview

This plan fixes the defects that the move from Hugging Face to Cloud Run exposed, using the bug condition methodology: exploration tests that fail on the unfixed code (task 1), preservation tests that pass on it (task 2), then one fix task per component in priority order. Tasks 1–2 are the tests, tasks 3–11 the P0 fixes with checkpoint 12, tasks 13–14 the P1 fixes with checkpoint 15 and tasks 16–18 the P2 fixes; task 19 is the final verification, task 20 the final checkpoint, and the operator actions come last.

## Notes

- Inputs: `bugfix.md` (clauses 1.x defect, 2.x expected, 3.x preserved) and `design.md` (components C1–C13, Properties 1–14). Tasks reference those IDs instead of restating them.
- Test commands (always run in parallel):
  - Billing backend, from `backend/`: `$env:GROQ_API_KEY='mock_groq_api_key'; python -m pytest tests/ -q -n auto --dist loadscope`. For a single file pass its path, and keep `-n auto --dist loadscope` when the file has many tests.
  - Field Team backend, from `backend-task/`: `python -m pytest tests/ -q -n auto --dist loadscope`.
  - Frontends (`frontend-billing`, `frontend-task`, `frontend-ai`, `frontend-admin`): `npx vitest run --pool=threads --reporter=dot`, plus the Playwright screenshot checks. These run on the user's machine only: Vitest hangs in the agent sandbox, and `frontend-admin`, `frontend-ai` and `frontend-task` have no `node_modules` there.
- Frontend work in automation: the execution agent still writes and updates the frontend tests, then syntax-checks every touched JS/JSX file with `@babel/parser` from `frontend-billing/node_modules`: `node --preserve-symlinks --preserve-symlinks-main C:\Users\91957\AppData\Local\Temp\kiro-syntax-check.cjs <parserDir> <files…>`. The user runs the frontend suites locally and reports results.
- Never run `run_tests.ps1` in automation: it starts a dashboard server and blocks on `Read-Host`.
- Known environment-only failure, ignored by every checkpoint: `tests/test_intent_router.py::test_semantic_router_eval_accuracy`.
- Baseline before this spec:
  - Billing backend: 2526 passed, 27 skipped, 3 failed. The failures are `test_tenant_scope::test_no_unscoped_tenant_reads` and `test_session_invalidation` (regressions this spec fixes in tasks 7 and 8) plus the environment-only test above.
  - Field Team backend (`backend-task`): all passed.
- Property-based tests: `hypothesis` is not installed. Write properties as `pytest.mark.parametrize` tables, with generated cases drawn from `random.Random(<fixed seed>)` so every run is reproducible. Frontend properties use `it.each` tables.
- Test conventions:
  - New backend test modules copy the existing headers (`DATABASE_URL` on SQLite, mock `GROQ_API_KEY`, `CLOUD_API_URL=http://127.0.0.1:9`) and reset module state (`realtime_manager`, `_REGISTRY`, `_used_tickets`, caches) in fixtures, so `-n auto --dist loadscope` stays isolated. Postgres-only cases use the existing testcontainers setup and skip without Docker.
  - Preservation tests are named after their clause (`test_c3_01_…` to `test_c3_22_…`) so a fix task can re-run one clause with `-k`.
  - Exploration files whose fix lands in part 2 (C2, C7, C8, the rest of C12) get `pytestmark = pytest.mark.xfail(strict=True, reason="bug condition <Cn>, fixed in part 2")` once task 1 has recorded their counterexamples. The P0 checkpoint stays green, and an early pass still shows up as a failure. The part 2 fix task removes the marker first.
- Deploy-script settings owned by P0 components (C5.2 `SUBSCRIPTION_ENFORCED=0`, C6.6 `--max-instances 1`, C12.1 `CLOUD_RUN_REGION`) are applied together with the other deploy-script changes in C13 (part 2), so each script is edited in one task.
- Priority: tasks 1–2 are the tests; tasks 3–11 fix the P0 symptoms, with checkpoint 12; tasks 13–14 are P1 (C2, C7), with checkpoint 15; tasks 16–18 are P2 (C8, the rest of C12, C13); task 19 is the final verification and task 20 the final checkpoint; the operator actions come last.

## Task Dependency Graph

Rules behind the waves: two leaves that run pytest in the same backend directory never share a wave (two concurrent runs there can collide on SQLite files and xdist worker names), leaves that edit the same file never share a wave, and frontend leaves of different apps run side by side once their backend dependencies are done.

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.5", "1.6", "1.7"] },
    { "id": 1, "tasks": ["1.2", "2.3", "2.4"] },
    { "id": 2, "tasks": ["1.3"] },
    { "id": 3, "tasks": ["1.4"] },
    { "id": 4, "tasks": ["2.1"] },
    { "id": 5, "tasks": ["2.2"] },
    { "id": 6, "tasks": ["3.1"] },
    { "id": 7, "tasks": ["3.2"] },
    { "id": 8, "tasks": ["3.3"] },
    { "id": 9, "tasks": ["3.4"] },
    { "id": 10, "tasks": ["3.5"] },
    { "id": 11, "tasks": ["3.6"] },
    { "id": 12, "tasks": ["3.7"] },
    { "id": 13, "tasks": ["4.1"] },
    { "id": 14, "tasks": ["4.2"] },
    { "id": 15, "tasks": ["4.3"] },
    { "id": 16, "tasks": ["4.4"] },
    { "id": 17, "tasks": ["4.5"] },
    { "id": 18, "tasks": ["4.6"] },
    { "id": 19, "tasks": ["4.7"] },
    { "id": 20, "tasks": ["4.8"] },
    { "id": 21, "tasks": ["5.1"] },
    { "id": 22, "tasks": ["5.2"] },
    { "id": 23, "tasks": ["5.3"] },
    { "id": 24, "tasks": ["5.4"] },
    { "id": 25, "tasks": ["5.5"] },
    { "id": 26, "tasks": ["5.6"] },
    { "id": 27, "tasks": ["6.1"] },
    { "id": 28, "tasks": ["6.2"] },
    { "id": 29, "tasks": ["6.3"] },
    { "id": 30, "tasks": ["7.1"] },
    { "id": 31, "tasks": ["7.2"] },
    { "id": 32, "tasks": ["7.3"] },
    { "id": 33, "tasks": ["7.4"] },
    { "id": 34, "tasks": ["7.5"] },
    { "id": 35, "tasks": ["7.6"] },
    { "id": 36, "tasks": ["7.7"] },
    { "id": 37, "tasks": ["8.1", "9.1", "10.1"] },
    { "id": 38, "tasks": ["8.2", "9.2", "10.2"] },
    { "id": 39, "tasks": ["8.3", "9.3", "10.3"] },
    { "id": 40, "tasks": ["8.4", "9.4", "10.4"] },
    { "id": 41, "tasks": ["8.5", "9.5", "10.5"] },
    { "id": 42, "tasks": ["8.6", "10.6"] },
    { "id": 43, "tasks": ["8.7", "10.7"] },
    { "id": 44, "tasks": ["8.8"] },
    { "id": 45, "tasks": ["8.9"] },
    { "id": 46, "tasks": ["11.1"] },
    { "id": 47, "tasks": ["11.2"] },
    { "id": 48, "tasks": ["11.3", "11.4"] },
    { "id": 49, "tasks": ["11.5"] },
    { "id": 50, "tasks": ["11.6"] },
    { "id": 51, "tasks": ["12"] },
    { "id": 52, "tasks": ["13.1"] },
    { "id": 53, "tasks": ["13.2"] },
    { "id": 54, "tasks": ["13.3"] },
    { "id": 55, "tasks": ["13.4"] },
    { "id": 56, "tasks": ["13.5"] },
    { "id": 57, "tasks": ["13.6"] },
    { "id": 58, "tasks": ["13.7"] },
    { "id": 59, "tasks": ["13.8"] },
    { "id": 60, "tasks": ["13.9"] },
    { "id": 61, "tasks": ["13.10"] },
    { "id": 62, "tasks": ["13.11"] },
    { "id": 63, "tasks": ["14.1"] },
    { "id": 64, "tasks": ["14.2"] },
    { "id": 65, "tasks": ["14.3"] },
    { "id": 66, "tasks": ["14.4"] },
    { "id": 67, "tasks": ["14.5"] },
    { "id": 68, "tasks": ["14.6"] },
    { "id": 69, "tasks": ["14.7", "14.8"] },
    { "id": 70, "tasks": ["14.9"] },
    { "id": 71, "tasks": ["14.10"] },
    { "id": 72, "tasks": ["14.11"] },
    { "id": 73, "tasks": ["14.12"] },
    { "id": 74, "tasks": ["15"] },
    { "id": 75, "tasks": ["16.1"] },
    { "id": 76, "tasks": ["16.2"] },
    { "id": 77, "tasks": ["16.3"] },
    { "id": 78, "tasks": ["16.4"] },
    { "id": 79, "tasks": ["16.5"] },
    { "id": 80, "tasks": ["16.6"] },
    { "id": 81, "tasks": ["16.7"] },
    { "id": 82, "tasks": ["16.8"] },
    { "id": 83, "tasks": ["17.1"] },
    { "id": 84, "tasks": ["17.2"] },
    { "id": 85, "tasks": ["17.3"] },
    { "id": 86, "tasks": ["17.4"] },
    { "id": 87, "tasks": ["17.5", "17.6"] },
    { "id": 88, "tasks": ["17.7"] },
    { "id": 89, "tasks": ["17.8"] },
    { "id": 90, "tasks": ["17.9"] },
    { "id": 91, "tasks": ["17.10"] },
    { "id": 92, "tasks": ["17.11"] },
    { "id": 93, "tasks": ["18.1", "18.7"] },
    { "id": 94, "tasks": ["18.2"] },
    { "id": 95, "tasks": ["18.3"] },
    { "id": 96, "tasks": ["18.4"] },
    { "id": 97, "tasks": ["18.5"] },
    { "id": 98, "tasks": ["18.6"] },
    { "id": 99, "tasks": ["18.8", "18.9", "18.10"] },
    { "id": 100, "tasks": ["18.11"] },
    { "id": 101, "tasks": ["18.12"] },
    { "id": 102, "tasks": ["18.13"] },
    { "id": 103, "tasks": ["19"] },
    { "id": 104, "tasks": ["20"] }
  ]
}
```

## Tasks

- [ ] 1. Write bug condition exploration tests (BEFORE the fix)
  - **Property 1: Bug Condition** - Post-migration interactions behave as specified
  - **CRITICAL**: These tests MUST FAIL on the unfixed code. A failure confirms the bug. A pass means the root cause in design.md is wrong; stop and report it before any fix.
  - **DO NOT fix the tests or the code when they fail.** Each test asserts `expectedBehavior(X, result)` for inputs where `isBugCondition(X)` holds, so the same test validates the fix later.
  - **Scoped PBT approach**: the bugs are deterministic, so scope each property to the concrete failing cases of design.md "Exploratory Bug Condition Checking" (cases 1–23). The wide generated tables belong to the fix tasks.
  - Two counterexamples already exist in the baseline; leave them untouched: `test_session_invalidation.py::test_staff_cannot_run_owner_sync_pull_or_discover_accounts_anonymously` (1.17) and `test_tenant_scope.py::test_no_unscoped_tenant_reads` (1.44).
  - Record the observed counterexamples in a short comment block at the top of each test file. Where the frontend helpers named by design do not exist yet, test through today's entry points (`openFieldTeam`, `openAiDashboard`, `request()`, the auth contexts).
  - **EXPECTED OUTCOME**: every new test FAILS on the unfixed code (backend files of part 2 components then carry the strict xfail marker from the notes).
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.12, 1.13, 1.14, 1.15, 1.16, 1.17, 1.18, 1.19, 1.20, 1.21, 1.22, 1.23, 1.24, 1.25, 1.26, 1.27, 1.28, 1.29, 1.30, 1.31, 1.32, 1.33, 1.34, 1.35, 1.36, 1.37, 1.38, 1.39, 1.40, 1.41, 1.42, 1.43, 1.44, 1.45, 1.46, 1.47, 1.48, 1.50, 1.56_

  - [-] 1.1 Billing API: cloud endpoint, tickets, sessions and plan gates (C1, C4, C5)
    - **Property 1: Bug Condition** - Billing API endpoint, tickets, sessions and gates
    - In `backend/tests/`:
      - `test_cloud_endpoint.py`: in a subprocess with `CLOUD_API_URL`, `VITE_API_URL`, `CLOUD_URL` and `BIZASSIST_CLOUD_URL` removed (keep the test `DATABASE_URL` and `GROQ_API_KEY`), import the modules and assert that `services.sync_worker.CLOUD_URL`, `routes.b2b_proxy.CLOUD_URL` and `services.realtime._CLOUD_URL` equal `https://staterbill-api-1076771386585.asia-south1.run.app`. A subprocess is needed because the suite sets `CLOUD_API_URL` before import. Fails today: hf.space.
      - `test_no_retired_host_defaults.py`: scan `.py`, `.js`, `.jsx`, `.mjs` and `.cjs` files for hf.space and bizassist-billing.vercel.app used as defaults (URL constants and fallbacks), ignoring comments and test files. An explicit allow-list covers transition trust lists (CORS origin lists, Billing-origin trust lists) and documentation; C13 checks the CORS and deploy-script lists in part 2. Parametrize one case per tree with ids `backend`, `desktop`, `scripts`, `dev`, `frontend_billing`, `frontend_task`, `frontend_ai`, `frontend_admin`. The `dev` and `frontend_*` cases take `xfail(strict=False, reason="may also need C13, part 2")`. If the run shows a `backend` hit that no P0 task (3.2, 7.3) removes, move that file into its own case with `xfail(strict=False)` that names the owning component.
      - `test_hf_forwarder_config.py`: `ops/hf-forwarder/default.conf` proxies to the Cloud Run URL with `proxy_buffering off`, and `README.md` has `sdk: docker` and `app_port: 7860`. Fails today: no forwarder.
      - `test_handoff_ticket_purpose.py`: `POST /handoff-ticket` with `{"purpose": "field_team"}` gives a 90 s ticket with `aud`; `/redeem-ticket` refuses an `aud=field_team` ticket (on the unfixed code, put `aud` in the payload dict); a ticket minted before a token-version bump is refused with 401. Fails today: 200.
      - `test_spent_tickets_durable.py`: redeem, clear `services.auth._used_tickets` to simulate a restart, redeem again; expect the `already_used` refusal.
      - `test_session_rejection_marker.py`: expired and revoked tokens get 401 with `WWW-Authenticate: Bearer error="invalid_token"`; the "user not found" 404s of `GET /profile` and `GET /settings` carry the same header; a CORS response for an allowed origin exposes it.
      - `test_logout_revokes_dashboard.py`: login, `ai_dashboard` ticket, `/redeem-ticket`, `POST /auth/logout` with the Billing token, then a dashboard request gets a marked 401. Fails today: no route, token still valid.
      - `test_settings_gates.py`: with `SUBSCRIPTION_ENFORCED=0`, a free account's `subscription.gates` has `web_preview` and `field_team` true and `hybrid_sync` false; a Pro account has all four false. Fails today: no `gates`.
    - Run: `$env:GROQ_API_KEY='mock_groq_api_key'; python -m pytest <files> -q -n auto --dist loadscope` from `backend/`.
    - _Properties: Property 1, Property 3, Property 4, Property 6, Property 7_
    - _Requirements: 1.5, 1.7, 1.14, 1.16, 1.27, 1.28, 1.30, 1.32, 1.33, 1.34, 1.40, 1.56_

  - [~] 1.2 Billing API: real-time streams and admin routes (C6, C12 P0 part)
    - **Property 1: Bug Condition** - Billing API streams and admin routes
    - In `backend/tests/`:
      - `test_sse_rotation_replay.py`: with `SSE_MAX_STREAM_SECONDS=1`, a TestClient stream on `/realtime/events` ends with `event: rotate`, frames carry `id:`, and a reconnect with `last_event_id` replays the events broadcast in between.
      - `test_cloud_listener_timeouts.py`: `_Listener.run` in `services/cloud_listener.py` uses a stream timeout with `read=45`, and the backoff returns to `_RECONNECT_BASE_SEC` after an established stream drops. Fails today: `read=None`, no reset.
      - `test_admin_routes_json_500.py`: with `ADMIN_API_ENABLED=1` and `svc.require_admin` patched to raise `RuntimeError`, every `/admin/*` route in `app.routes` (path parameters filled, minimal valid bodies) answers a JSON 500 with `access-control-allow-origin` for an allowed origin. Fails today for `GET /admin/rate-limits/{user_id}` and `GET /admin/usage-stats`.
      - `test_infrastructure_metrics.py`: with `sys.modules["psutil"] = None`, `GET /admin/infrastructure-metrics` returns 200 and lists the process metrics in `unavailable`; without `HF_STANDBY_URL` no Hugging Face probe is made.
    - _Properties: Property 1, Property 9, Property 12_
    - _Requirements: 1.38, 1.39, 1.40, 1.43, 1.44, 1.46_

  - [~] 1.3 Billing API: boot, change feed, sync worker and B2B proxy (C2, C7; fixed in part 2)
    - **Property 1: Bug Condition** - Billing API boot and cold-cloud sync
    - In `backend/tests/`:
      - `test_boot_fast_path.py`: a `before_cursor_execute` listener counts statements. On SQLite, `install_change_feed` issues no per-row existence SELECT (fails: one per row). On Postgres (testcontainers), a second `run_migrations_and_seed()` issues no CREATE, DROP or ALTER (fails).
      - `test_change_feed_errors.py`: an injected `OperationalError` with `pgcode = "40P01"` is retried and raises no `NameError` (fails: `NameError`); an unrelated error whose message contains "transaction block" is raised, not logged as "peer completed" (fails).
      - `test_sync_worker_cold_cloud.py`: an HTML 503 with `Retry-After: 120` sets `busy` with no attempt before 120 s; a probe time-out sets `waking`; token refresh starts 12 h before expiry and retries after 1 minute.
      - `test_b2b_proxy_cold_cloud.py`: an upstream 503 on a B2B read serves the local mirror; an upstream 401 on a write returns 424 `cloud_sign_in_required`. Fails today: pass-through.
    - After recording the counterexamples, add the strict xfail marker from the notes to these four files.
    - _Properties: Property 1, Property 8, Property 10_
    - _Requirements: 1.35, 1.36, 1.37, 1.41_

  - [~] 1.4 Billing API: scheduled jobs, discovery and durable admin state (C8, rest of C12; fixed in part 2)
    - **Property 1: Bug Condition** - Billing API scheduled jobs and durable state
    - In `backend/tests/`:
      - `test_internal_cron.py`: with `K_SERVICE` set, `start_scheduler()` registers no cron job; `POST /internal/cron/{job}` returns 404 without `BILLING_CRON_SECRET`, 403 for a wrong secret, and `already_ran` on a second delivery. Fails today: jobs registered, no route.
      - `test_discovery_persistence.py`: register with `DISCOVERY_PERSIST=1`, clear `_REGISTRY`, look up again; the entry is found.
      - `test_router_mode_persisted.py`: `set_mode()`, clear the in-process value, and `get_mode()` still returns the set mode.
      - `test_feedback_archive_durable.py`: upload a feedback log archive, delete its file on disk, and `GET /admin/feedback/logs/{id}` still returns it.
      - `test_admin_query_counts.py`: statement counts for `list_businesses`, `sync_doctor` and the usage stats are equal for 2 and 6 businesses. Fails today: queries per business.
    - After recording the counterexamples, add the strict xfail marker from the notes to these five files.
    - _Properties: Property 1, Property 11, Property 12_
    - _Requirements: 1.40, 1.42, 1.47, 1.48_

  - [-] 1.5 Field Team API: hand-off, boot and origins (C3)
    - **Property 1: Bug Condition** - Field Team API hand-off, boot and origins
    - In `backend-task/tests/`:
      - `test_ticket_refusal_reasons.py`: a bad signature, an expiry, a reuse and a wrong audience each return their own `detail` and log `reason=`; a 90 s ticket redeemed at 100 s (frozen clock) is accepted. Mint with billing's `create_sse_ticket` as `test_billing_contract.py` does, putting `iat` and `aud` in the payload dict (the unfixed function has no `aud` argument). Fails today: one message, 90 s tickets refused.
      - `test_boot_skips_upgrade_at_head.py`: with the database at head, `run_migrations()` does not call `alembic.command.upgrade`.
      - `test_default_origins.py`: without `ALLOWED_ORIGINS`, a CORS preflight from https://bizassist-task.vercel.app succeeds; with `ALLOWED_ORIGINS` set, the defaults stay allowed next to the listed origins. Reload the app config in a subprocess.
    - Run: `python -m pytest <files> -q -n auto --dist loadscope` from `backend-task/`.
    - _Properties: Property 1, Property 4_
    - _Requirements: 1.4, 1.5, 1.6_

  - [-] 1.6 Billing web app: launch, session, gates, login and live sync (C9, C6 client; run by the user)
    - **Property 1: Bug Condition** - Billing web app
    - In `frontend-billing/src/__tests__/`:
      - `fieldTeamLaunch.test.js`: the production Field Team URL is used without `VITE_FIELD_TEAM_URL`; the anchor `href` has `from_billing=1`, `billing_origin` and `billing_business` and no ticket; toasts appear for a blocked window and a failed ticket (1.1, 1.8).
      - `aiDashboardOpen.test.js`: `window.open` is called before the ticket promise resolves and the request sends `purpose: "ai_dashboard"`; a user sign-out posts `AUTH_LOGOUT` to the dashboard window and calls `POST /auth/logout` before discarding the token (1.12, 1.14).
      - `sessionRejection.test.js`: an unmarked 401 and a 404 keep the session; a marked 401 ends it; an unmarked 401 triggers one `POST /auth/refresh`; with less than 6 h left, the session refresh calls `/auth/refresh` (1.28, 1.29, 1.30).
      - `httpErrors.test.js`: an HTML 503 becomes "The server is starting. Trying again…", and a GET retries after `Retry-After` (1.22).
      - `planGates.test.jsx`: no Pro alert, PRO badge or preview timer while settings are null; the timer key `bizassist_preview_start:<BizID>:<userId>` is reset on login and logout (1.7, 1.27, 1.56).
      - `authBudget.test.js`: the 65 s web budget, the waking message at 4 s, the sign-in fallback after a signup time-out, and no request to `/api/biz_id/check` or `/api/auth/check-username` (1.17 to 1.21).
      - `realtimeRotate.test.js`: a silent reconnect on `rotate`, `sync.reconnect` only after a `gap` hello, and no toast within 30 s (1.38).
    - `frontend-billing/e2e/login-layout.spec.js` (Playwright): at 360×640, 844×390, 768×1024 and 1366×768, the card top is reachable after scrolling to the top, `scrollWidth <= innerWidth`, the footer edges are within 1 px of the card edges, and `elementFromPoint` at the System check centre is the trigger. Save screenshots (1.23 to 1.26).
    - Syntax-check every new file with the helper. The user runs `npx vitest run --pool=threads --reporter=dot` and `npx playwright test e2e/login-layout.spec.js` in `frontend-billing` on the unfixed code and reports the failures; record them in each file's header comment.
    - _Properties: Property 1, Property 6, Property 7, Property 9, Property 13_
    - _Requirements: 1.1, 1.7, 1.8, 1.12, 1.14, 1.17, 1.18, 1.19, 1.20, 1.21, 1.22, 1.23, 1.24, 1.25, 1.26, 1.27, 1.28, 1.29, 1.30, 1.38, 1.56_

  - [ ] 1.7 Field Team, AI dashboard and admin console web apps (C10, C11; run by the user)
    - **Property 1: Bug Condition** - Field Team, AI dashboard and admin console sign-in
    - Put each file next to the app's existing tests (create `src/__tests__/` where none exist):
      - `frontend-task`: `theme.test.js` (`sanitizeBillingUrl` trusts https://staterbill.com, https://www.staterbill.com and each origin of a comma-separated `VITE_BILLING_URL`; `BILLING_CLOUD_URL` is https://staterbill.com); `auth.test.jsx` (a launch from https://staterbill.com without `sso` clears the stored session and shows "Sign in with the Billing account for <BizID> to continue."); `api.test.js` (a failed fetch while online shows "Could not reach the Field Team server. It may be starting up."; `POST /api/auth/exchange` retries a 503 within the ticket's `exp - iat + 10` window).
      - `frontend-ai`: `handoff.test.js` (`trustedHandoff` accepts the three default Billing origins, only from the opener); `authContext.test.jsx` (a failed `?sso=` redemption clears the session and shows the "Billing could not sign you in…" message).
      - `frontend-admin`: `handoff.test.js` (as for the AI dashboard); `authContext.test.jsx` (`adminUser` is set only after `GET /admin/session` returns 200; `?logout=true` clears `user`, `admin_user`, `biz_name` and every token; an unmarked 401 keeps the session; the return path is kept); `AdminInfrastructure.test.jsx` (a null metric shows "unavailable", no auto-refresh by default, the error banner shows the status and `detail`).
    - Syntax-check every new file with the helper. The user runs vitest in `frontend-task`, `frontend-ai` and `frontend-admin`, plus `npm run lint` in `frontend-admin`, on the unfixed code and reports the failures.
    - _Properties: Property 1, Property 5, Property 6, Property 12_
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.13, 1.15, 1.31, 1.45, 1.50_

- [ ] 2. Write preservation property tests (BEFORE implementing the fix)
  - **Property 2: Preservation** - Interactions outside the bug condition are unchanged
  - **IMPORTANT**: Follow observation-first methodology. Run each scenario on the UNFIXED code for inputs where `isBugCondition(X)` is false, record the actual status codes, `detail` texts and payloads, and pin those observed values.
  - `hypothesis` is not installed and no frontend has `fast-check`: generate cases with `pytest.mark.parametrize` over `itertools.product` tables and `random.Random(seed)` with fixed seeds, and with `it.each` in vitest. Add no dependency.
  - Keep bug-condition inputs out of every table (task 1 owns them), so each test passes before and after the fix. Name tests after their clause (`test_c3_05_…`).
  - Do not edit existing tests here. The full existing suites stay the main preservation check.
  - **EXPECTED OUTCOME**: every new test PASSES on the unfixed code.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14, 3.15, 3.16, 3.17, 3.18, 3.19, 3.20, 3.21, 3.22_

  - [~] 2.1 Billing API: sessions, tickets, CORS, admin, streams and secrets
    - **Property 2: Preservation** - Billing API sessions, tickets, CORS, admin and streams
    - `backend/tests/test_preservation_billing_api.py`:
      - 3.1: expired, malformed, token-version-revoked and deleted-user tokens on a fixed table of authenticated routes keep today's status and `detail`.
      - 3.2: `GET /staff-counters?owner=` stays 404. Every unauthenticated route in `app.routes` must appear in a list pinned now, each entry noting that it returns no account fields; the two lookup routes are marked "removed by task 8.5", and removing a route is allowed. A new unauthenticated route fails until it is added with that note (part 2 adds `POST /internal/cron/{job}`).
      - 3.3: a fake stale `tenant_scope.ALLOWED` entry is still rejected by the guard.
      - 3.5: `POST /handoff-ticket` without a body returns a 30 s ticket without `aud`; `redeem_sse_ticket` returns the payload of a fresh ticket once, and `None` on reuse or 60 s after expiry (the first 15 s after expiry gain a leeway in task 4.5, so they stay out); a `/realtime/ticket` ticket opens `/realtime/events`.
      - 3.6: `/ask*` keeps refusing non-Pro accounts with today's status and message.
      - 3.10: CORS preflights from https://bizassist-billing.vercel.app and the other vercel.app origins in `_default_origins` succeed.
      - 3.17: every `/admin/*` route returns 404 without `ADMIN_API_ENABLED`; with it, a non-admin gets 403 on every GET route.
      - 3.20: the 21st stream for one business gets 429, and a revoked session's stream closes.
      - 3.21: `caplog` records from ticket refusals and sync-worker start-up never contain the test `JWT_SECRET` or `DATABASE_URL`.
    - Existing tests that must stay green and stay unmodified: `test_local_only_stays_local` and the cross-database identity tests (3.4), `test_realtime_sync.py`, `test_sse_hardening.py`, `test_b2b_proxy_test_isolation.py`, the admin 2FA and audit tests (3.17). `test_semantic_router_eval_accuracy` stays exempt (3.22).
    - _Properties: Property 2_
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.10, 3.17, 3.20, 3.21, 3.22_

  - [~] 2.2 Billing API: local start-up, replication and warm-cloud B2B
    - **Property 2: Preservation** - Local start-up, replication and warm cloud
    - `backend/tests/test_preservation_boot_seed.py`:
      - 3.11: on SQLite, two `run_migrations_and_seed()` calls both run the backfill steps; the constrained-runtime refusal still raises "Database migration required".
      - 3.12: copy today's per-row seeder from `database/change_feed.py` into the test as `_reference_seed`. For 25 fixed seeds, generate businesses, parent, child and B2B rows plus a random subset of existing events. The production seeder and `_reference_seed` must give the same `(business_id, entity, row_uid)` set and the same per-business revision counts.
    - `backend/tests/test_preservation_b2b_warm.py` (3.13): over method × upstream outcome {2xx, 4xx other than 401 and 429, network error, 401 on a read}, the proxy passes through, serves the mirror, drops the stale token, or answers the "B2B is offline" 503 exactly as observed. Time-outs, 429 and 5xx reads, and 401 writes are bug conditions and stay out.
    - _Properties: Property 2_
    - _Requirements: 3.4, 3.11, 3.12, 3.13_

  - [~] 2.3 Field Team API: hand-off and access rules
    - **Property 2: Preservation** - Field Team API hand-off and access rules
    - `backend-task/tests/test_preservation_handoff.py`: legacy 30 s tickets without `aud`, minted with billing's `create_sse_ticket` and redeemed at ages 0, 10 and 29 s, are accepted; staff tickets get 403; tickets minted before a token-version bump get 401; non-Pro businesses get 402; all with the messages observed today. An origin passed in `ALLOWED_ORIGINS` and localhost and LAN origins (through `allow_origin_regex`) stay allowed.
    - `test_billing_contract.py` stays unmodified and green.
    - _Properties: Property 2_
    - _Requirements: 3.5, 3.6, 3.10_

  - [~] 2.4 Web apps: trust, routing, free plans and launch guards (run by the user)
    - **Property 2: Preservation** - Web apps outside the bug condition
    - `frontend-billing/src/__tests__/preservation.test.jsx` (`it.each` tables):
      - 3.1: a marked 401 from the own API base signs out.
      - 3.8, 3.15, 3.16: localhost and LAN hosts resolve to the local backend; desktop sign-in fails within 8 s with the local-service message; the desktop opens 127.0.0.1:8451 for the AI dashboard and never locks.
      - 3.9, 3.14: with fake timers, a known free plan locks after 5 minutes; a lapsed trial shows the trial-ended screen; a known non-Pro plan shows the PRO badges; cashiers and supply adders see neither app.
      - 3.18: the local-fixture rule of `getFieldTeamUrl()` is unchanged.
    - `frontend-task` `preservation.test.js`: messages from a non-opener, or from an unlisted origin (look-alikes such as `https://staterbill.com.evil.example`, `http://staterbill.com`, port 3000, a LAN address), are refused; https://bizassist-billing.vercel.app and local ports 5174 and 8450 are trusted from the opener; appearance tokens with `url(` are dropped; the different-business guard in `startBillingBridge` still refuses another business.
    - `frontend-ai` and `frontend-admin` `handoff.preservation.test.js`: the same origin × source table for `trustedHandoff`, with `event.source === opener` still required.
    - Syntax-check every new file with the helper. The user runs them on the unfixed code; any failure means the table pinned an assumption, so adjust it to the observed behaviour before task 3.
    - _Properties: Property 2, Property 5_
    - _Requirements: 3.1, 3.7, 3.8, 3.9, 3.10, 3.14, 3.15, 3.16, 3.18, 3.19_

- [ ] 3. Fix C1: one cloud endpoint (P0)

  - [~] 3.1 Add the cloud endpoint resolver
    - New `backend/core/cloud_endpoint.py` with `DEFAULT_CLOUD_URL`, `resolve_cloud_url(environ=os.environ) -> tuple[str, str]`, and `CLOUD_URL` and `CLOUD_URL_SOURCE` computed at import, per design C1.1: order `CLOUD_API_URL`, `VITE_API_URL`, `CLOUD_URL`, `BIZASSIST_CLOUD_URL`, then the default; trim and drop trailing slashes; skip a non-http(s) value with a warning that names the variable; log an explicit hf.space value once as the retired Space.
    - Extend `backend/tests/test_cloud_endpoint.py` with the Property 3 table: the product of the four variables over {unset, "", "  ", "https://a.example/", "not a url", "https://x.hf.space"} (1,296 cases) against an oracle that takes the first valid value in order. Add unit cases for trimming, invalid values and the retired-host warning, and assert `caplog` never contains the test `JWT_SECRET` or `DATABASE_URL`.
    - _Bug_Condition: isBugCondition(X) for C1: a cloud caller resolves its URL with no explicit variable_
    - _Expected_Behavior: Property 1 and Property 3_
    - _Preservation: Property 2 (3.21)_
    - _Requirements: 1.32, 1.34, 2.32, 2.34, 3.21_

  - [~] 3.2 Route every backend cloud caller through the resolver
    - `backend/services/sync_worker.py`: `CLOUD_URL = cloud_endpoint.CLOUD_URL`, keeping the attribute that `cloud_listener`, `routes/auth.py`, `routes/feedback.py`, `routes/admin.py`, `control_outbox` and `log_uploader` import.
    - `backend/routes/b2b_proxy.py` keeps its `CLOUD_URL` attribute, now taken from the resolver.
    - `services/realtime.py` (`_CLOUD_URL`), `_discovery_registration_loop` in `main_groq.py`, `services/telemetry_relay.py`, `scripts/cloud_cleanup_counters.py` and `check_cloud_api.py` read the resolver.
    - The lifespan in `backend/main_groq.py` logs `[CLOUD] cloud API = <url> (from <source>)` once.
    - Tests: the subprocess default case of `test_cloud_endpoint.py` and the `scripts` case of `test_no_retired_host_defaults.py` pass. The `backend` case lists no file changed here; a remaining hit must belong to a later task (the Hugging Face probe in `routes/admin.py` is task 7.3). `test_b2b_proxy_test_isolation.py` still passes.
    - _Bug_Condition: isBugCondition(X) for C1: a backend caller falls back to hf.space_
    - _Expected_Behavior: Property 1 and Property 3_
    - _Preservation: Property 2 (3.8, 3.10)_
    - _Requirements: 1.32, 1.34, 2.32, 2.34, 3.8, 3.10_

  - [~] 3.3 Add `GET /api/sync/status`
    - New owner-only route in `backend/routes/sync.py` returning `{cloud_url, cloud_url_source, cloud_state, last_probe_at, retry_after}`. Until C7 adds `_CLOUD_STATE` (part 2), the last three fields come from the worker's existing status or are `null`.
    - Test `backend/tests/test_sync_status_route.py`: the owner gets the resolved URL and its source; staff and anonymous callers are refused with the status codes the other owner-only sync routes use; the body holds no token or secret.
    - _Bug_Condition: isBugCondition(X) for C1: the effective cloud URL cannot be seen_
    - _Expected_Behavior: Property 3_
    - _Preservation: Property 2 (3.21)_
    - _Requirements: 2.34, 3.21_

  - [~] 3.4 Pass the endpoint to the desktop backend
    - New `desktop/src/cloudEndpoint.js` exporting `DEFAULT_CLOUD_API_URL` and `resolveCloudApiUrl(env)`, with the order and validation of 3.1.
    - `desktop/src/backend.js` adds `CLOUD_API_URL: resolveCloudApiUrl(process.env)` to the spawn environment; `desktop/src/telemetry.js` uses `resolveCloudApiUrl`. The installer still ships without `.env`.
    - Test `backend/tests/test_cloud_endpoint_parity.py`: run `node --preserve-symlinks --preserve-symlinks-main` on `desktop/src/cloudEndpoint.js` over the 1,296-case table and compare with `resolve_cloud_url`; skip when `node` is not on PATH. The `desktop` case of `test_no_retired_host_defaults.py` passes. Syntax-check the three JS files with the helper.
    - _Bug_Condition: isBugCondition(X) for C1: the packaged desktop backend syncs to hf.space_
    - _Expected_Behavior: Property 3_
    - _Preservation: Property 2 (3.21)_
    - _Requirements: 1.32, 2.32, 3.21_

  - [~] 3.5 Add the Hugging Face forwarder
    - New `ops/hf-forwarder/Dockerfile` (`nginxinc/nginx-unprivileged:1.27-alpine`), `README.md` with the Space header (`sdk: docker`, `app_port: 7860`) and `default.conf` exactly as design C1.5 lists (`/__forwarder`, `proxy_pass` with the run.app `Host`, `proxy_ssl_server_name on`, HTTP/1.1, no buffering either way, `proxy_read_timeout 130s`, `proxy_connect_timeout 10s`, forwarded headers, `client_max_body_size 30m`). CORS stays with the billing API.
    - Extend `test_hf_forwarder_config.py` to check each directive. The operator pushes the folder to the Space (runbook, part 2).
    - _Bug_Condition: isBugCondition(X) for C1: an installed desktop app calls the retired Space_
    - _Expected_Behavior: Property 3_
    - _Preservation: Property 2 (3.21)_
    - _Requirements: 1.33, 2.33_

  - [~] 3.6 Verify the C1 exploration tests now pass
    - **Property 1: Expected Behavior** - One cloud endpoint
    - **IMPORTANT**: Re-run the SAME tests from task 1.1. Do NOT write new tests.
    - Run `test_cloud_endpoint.py`, `test_hf_forwarder_config.py` and `test_no_retired_host_defaults.py -k "desktop or scripts"`. The `backend` case may still list files owned by task 7.3; it must list none of the files changed in 3.2.
    - **EXPECTED OUTCOME**: Tests PASS (confirms the bug is fixed).
    - _Requirements: 2.32, 2.33, 2.34_

  - [~] 3.7 Verify the preservation tests still pass
    - **Property 2: Preservation** - One cloud endpoint
    - **IMPORTANT**: Re-run the SAME tests from task 2. Do NOT write new tests.
    - Run `test_preservation_billing_api.py -k "c3_10 or c3_21"`, `test_cloud_endpoint_parity.py`, `test_b2b_proxy_test_isolation.py` and the existing sync, B2B proxy and feedback test files.
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions).
    - _Requirements: 3.8, 3.10, 3.21_

- [ ] 4. Fix C4: billing API tickets, sessions and logout (P0)

  - [~] 4.1 Add the `spent_tickets` and `revoked_sessions` tables (do this first)
    - `backend/database/models.py`: `SpentTicket` (`spent_tickets`: `digest` String(64) primary key, `expires_at` indexed) and `RevokedSession` (`revoked_sessions`: `sid` primary key, `expires_at` indexed). Neither goes into `MODEL_MAP`, so neither gets a capture trigger or reaches the sync protocol.
    - New Alembic revision in `backend/alembic/versions/` with `down_revision` set to the current head (`python -m alembic heads` from `backend/`): creates both tables and indexes; `downgrade()` drops them.
    - Runtime-role grants for both tables in `backend/database/security.py`, following the existing pattern. Update any schema-contract list that names the required tables.
    - Rollback note, written into the revision docstring: the tables are additive and older revisions ignore them, so moving traffic back to the previous Cloud Run revision needs no downgrade; `alembic downgrade -1` removes them if they must go.
    - Test `backend/tests/test_auth_state_tables.py`: both tables exist after `create_all`, are absent from `MODEL_MAP`, and are granted by `security.py`. Run the existing Alembic and schema tests (`-k "alembic or schema or migration"`).
    - _Bug_Condition: isBugCondition(X) for C4: single use and logout live only in process memory_
    - _Expected_Behavior: Property 4 (durable single use)_
    - _Preservation: Property 2 (3.11)_
    - _Requirements: 1.14, 1.40, 2.14, 2.40, 3.11_

  - [~] 4.2 Add the session-rejection marker and CORS headers
    - `backend/services/auth.py`: `session_rejected(detail)` returns `HTTPException(401, detail, headers={"WWW-Authenticate": 'Bearer error="invalid_token"'})`. Use it for the 401 raises in `decode_access_token`, `_validate_token_version`, `get_active_user` and `get_active_user_or_ticket`, and in `refresh_session` (`backend/routes/auth.py`). Status codes and `detail` texts stay as they are.
    - `backend/routes/auth.py`: the "user not found" 404s of `GET /profile`, `GET /settings` and the business-config route carry the same header.
    - `backend/main_groq.py` CORS: `expose_headers=["X-Total-Count", "WWW-Authenticate", "Retry-After"]`; `allow_headers` adds `Last-Event-ID`.
    - Tests: `test_session_rejection_marker.py` passes; `test_preservation_billing_api.py -k c3_01` still passes.
    - _Bug_Condition: isBugCondition(X) for C4: a client cannot tell a rejected session from any other 401 or 404_
    - _Expected_Behavior: Property 6_
    - _Preservation: Property 2 (3.1)_
    - _Requirements: 1.28, 1.30, 2.28, 2.30, 3.1_

  - [~] 4.3 Build every session's claims in one helper
    - `backend/routes/auth.py`: `_session_claims(user_row, *, sid, psid=None)` builds the claims for `login`, `staff_login`, `signup`, `redeem_ticket` and `refresh_session`. Login, staff login and signup create a random `sid`; `refresh_session` copies `sid` and `psid` from the presented token; `redeem_ticket` creates a new `sid` (its `psid` is wired in 4.5).
    - Test `backend/tests/test_session_claims.py`: each call site's token carries the helper's claims; `refresh_session` keeps `sid` and `psid`; the existing login, signup, staff and refresh tests pass.
    - _Bug_Condition: isBugCondition(X) for C4: a dashboard session cannot be tied to the Billing session that opened it_
    - _Expected_Behavior: Property 1 (2.14)_
    - _Preservation: Property 2 (3.1)_
    - _Requirements: 1.14, 2.14, 3.1_

  - [~] 4.4 Mint tickets with a purpose, an audience and `iat`
    - `create_sse_ticket(user_payload, expires_in_seconds, *, aud=None)` in `backend/services/auth.py` adds `iat`, and `aud` when given, inside the signed payload. The format does not change.
    - `POST /handoff-ticket` (`handoff_ticket` in `backend/routes/auth.py`) accepts an optional body `{"purpose": "field_team" | "ai_dashboard" | "admin_console"}`: `field_team` lives 90 s (`HANDOFF_TTL_FIELD_TEAM`, capped at 120); `ai_dashboard` and `admin_console` live 60 s; an `ai_dashboard` ticket carries `psid` = the caller's `sid`. No body gives today's legacy ticket: no `aud`, 30 s.
    - `POST /realtime/ticket` (`generate_sse_ticket` in `backend/core/api/realtime.py`) mints with `aud="sse"`.
    - Tests: the minting cases of `test_handoff_ticket_purpose.py` pass; add `HANDOFF_TTL_FIELD_TEAM` cases (55, 90 and 500, which is capped to 120); `test_preservation_billing_api.py -k c3_05` still passes.
    - _Bug_Condition: isBugCondition(X) for C4: a 30 s ticket expires during a Field Team cold start_
    - _Expected_Behavior: Property 4_
    - _Preservation: Property 2 (3.5)_
    - _Requirements: 1.5, 2.5, 3.5_

  - [~] 4.5 Verify tickets by audience, once, with the token-version check on `/redeem-ticket`
    - `backend/services/auth.py`: `verify_ticket(ticket, *, audiences, leeway=15) -> TicketCheck(claims, reason)` with the reasons and order of the C3 table. `redeem_sse_ticket(ticket)` keeps its `dict | None` signature as a wrapper with `audiences={None, "sse"}`; `get_active_user_or_ticket` accepts `{None, "sse"}`.
    - `redeem_ticket` (`backend/routes/auth.py`) accepts `{None, "ai_dashboard", "admin_console"}`, refuses `field_team` and `sse` with 401, calls `_validate_token_version(claims)` before it issues a session, passes the ticket's `psid` to `_session_claims` for `ai_dashboard`, logs each refusal reason, and returns a reason-specific `detail`.
    - Durable single use: once the other checks pass, insert SHA-256(ticket) into `spent_tickets` with insert-if-absent (`on_conflict_do_nothing` on Postgres and SQLite) in a short transaction of its own; no row inserted means `already_used`. `_used_tickets` stays as the fast first check. If the table cannot be written, fall back to the in-memory set and log a warning. Every 100 inserts, delete rows past `expires_at + 1 h` in bounded batches (the retention-job purge comes with C8 in part 2).
    - Tests: `test_handoff_ticket_purpose.py` and `test_spent_tickets_durable.py` pass. Add `test_ticket_lifecycle_property.py`: signature {valid, invalid} × age {0, 30, 89, 104, 105, 106, 200} × lifetime {30, 60, 90, 120, 121} × `aud` {none, field_team, ai_dashboard, admin_console, sse} × `iat` {present, absent} × spent {no, yes}, against an oracle that implements the C3 order, for the `/redeem-ticket` and SSE audience sets, plus the leeway edges `exp + 15` and `exp + 16`.
    - _Bug_Condition: isBugCondition(X) for C4: a ticket is redeemed after a force logout, by the wrong redeemer, or again after a restart_
    - _Expected_Behavior: Property 4_
    - _Preservation: Property 2 (3.5)_
    - _Requirements: 1.16, 1.40, 2.16, 2.40, 3.5_

  - [~] 4.6 Add `POST /auth/logout` and revoke dashboard sessions
    - New `POST /auth/logout` in `backend/routes/auth.py` (authenticated, idempotent) inserts the caller's `sid` into `revoked_sessions` with `expires_at` = the token's `exp`. A token without `sid` gets 200 and no row.
    - `get_active_user` (`backend/services/auth.py`) checks `revoked_sessions` only for tokens that carry `psid`, next to the token-version check; a revoked `psid` or `sid` gives `session_rejected(...)`. Expired rows are purged with the spent-ticket purge of 4.5.
    - Tests: `test_logout_revokes_dashboard.py` passes. Add a statement-count case (`before_cursor_execute`): a token without `psid` adds no query to `get_active_user`.
    - _Bug_Condition: isBugCondition(X) for C4: Billing sign-out leaves the dashboard session valid_
    - _Expected_Behavior: Property 1 (2.14) and Property 6_
    - _Preservation: Property 2 (3.1)_
    - _Requirements: 1.14, 2.14, 3.1_

  - [~] 4.7 Verify the C4 exploration tests now pass
    - **Property 1: Expected Behavior** - Tickets, sessions and logout
    - **IMPORTANT**: Re-run the SAME tests from task 1.1. Do NOT write new tests.
    - Run `test_handoff_ticket_purpose.py`, `test_spent_tickets_durable.py`, `test_session_rejection_marker.py` and `test_logout_revokes_dashboard.py`.
    - **EXPECTED OUTCOME**: Tests PASS (confirms the bug is fixed).
    - _Requirements: 2.5, 2.14, 2.16, 2.28, 2.30, 2.40_

  - [~] 4.8 Verify the preservation tests still pass
    - **Property 2: Preservation** - Tickets, sessions and logout
    - **IMPORTANT**: Re-run the SAME tests from task 2. Do NOT write new tests.
    - Run `test_preservation_billing_api.py -k "c3_01 or c3_05 or c3_20"` and the existing auth, session, staff, SSE and realtime test files with `-n auto --dist loadscope`. `test_session_invalidation.py` keeps its one baseline failure until task 8.5.
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions).
    - _Requirements: 3.1, 3.5, 3.20_

- [ ] 5. Fix C3: Field Team API (P0)

  - [~] 5.1 Skip the upgrade when the schema is at head
    - `run_migrations()` in `backend-task/app/main.py` reads the current heads with `MigrationContext` (as `_unknown_revisions` already does) and returns `True` without calling `command.upgrade` when they equal `script.get_heads()`, logging `[BOOT] ft schema at head <rev>, upgrade skipped`. A new head still upgrades once.
    - Tests: `test_boot_skips_upgrade_at_head.py` passes; add a case where a database one revision behind upgrades exactly once.
    - _Bug_Condition: isBugCondition(X) for C3: a cold start with a current schema repeats the upgrade_
    - _Expected_Behavior: Property 1 (2.5)_
    - _Preservation: Property 2 (3.5, 3.6)_
    - _Requirements: 1.5, 2.5_

  - [~] 5.2 Allow the production origin by default
    - `backend-task/app/config.py`: `_default_origins = "https://bizassist-task.vercel.app"`, and `ALLOWED_ORIGINS` becomes the order-preserving union of `parse_origins(_default_origins)` and `parse_origins(os.environ.get("ALLOWED_ORIGINS", ""))`. The localhost entries leave the default list, because `allow_origin_regex` already covers localhost and LAN.
    - Tests: `test_default_origins.py` passes; `test_preservation_handoff.py` (origin cases) still passes.
    - _Bug_Condition: isBugCondition(X) for C3: the CORS preflight from the production Field Team origin fails without `-AllowedOrigins`_
    - _Expected_Behavior: Property 1 (2.4) and Property 14 (2.53)_
    - _Preservation: Property 2 (3.10)_
    - _Requirements: 1.4, 2.4, 2.53, 3.10_

  - [~] 5.3 Give each ticket refusal its own reason
    - `redeem_billing_ticket(ticket)` in `backend-task/app/security.py` keeps its name and return value and raises `TicketRefused(reason)` (an `HTTPException` 401), with `_TICKET_MAX_LIFETIME_S = 120` and `_TICKET_LEEWAY_S = 15`. Checks run in the order of the C3 table (`malformed`, `bad_signature`, `expired`, `lifetime`, `audience`, `already_used`), each with the table's `detail` text.
    - Each refusal logs `[AUTH] hand-off ticket refused reason=<reason> exp_delta=<seconds>`, never the ticket, claims or key. A ticket without `aud` is accepted and logged as `legacy_no_aud`. Spent entries are kept until `exp + 15`. The staff 403, token-version 401 and Pro 402 checks after verification stay unchanged.
    - Tests: `test_ticket_refusal_reasons.py` passes. Add `test_ticket_property_table.py` with the Property 4 table of task 4.5 against the same C3-order oracle, and the cross-service vector: a ticket minted with billing's `create_sse_ticket(..., aud="field_team")` for 90 s and redeemed at 100 s with a frozen clock is accepted. `caplog` never contains the ticket or `JWT_SECRET`.
    - _Bug_Condition: isBugCondition(X) for C3: a valid 90 s ticket is refused, or every refusal shows the same message_
    - _Expected_Behavior: Property 4_
    - _Preservation: Property 2 (3.5, 3.6, 3.21)_
    - _Requirements: 1.5, 1.6, 2.5, 2.6, 3.5, 3.6, 3.21_

  - [~] 5.4 Harden the Field Team deploy script
    - `backend-task/deploy_cloudrun.ps1`: `-AllowedOrigins` defaults to `https://bizassist-task.vercel.app` and is always applied with `--update-env-vars`. After the deploy, poll `/api/health` until it reports `pro_required`, `billing_mirror` and `cloud_only`, and exit non-zero otherwise.
    - Check: parse the script with `[System.Management.Automation.Language.Parser]::ParseFile` and expect no errors. Do not run the deploy.
    - _Bug_Condition: isBugCondition(X) for C3: a redeploy without `-AllowedOrigins` or a stale revision passes unnoticed_
    - _Expected_Behavior: Property 14_
    - _Preservation: Property 2 (3.10)_
    - _Requirements: 1.9, 2.9, 2.53_

  - [~] 5.5 Verify the C3 exploration tests now pass
    - **Property 1: Expected Behavior** - Field Team API hand-off, boot and origins
    - **IMPORTANT**: Re-run the SAME tests from task 1.5. Do NOT write new tests.
    - From `backend-task/`: run `test_ticket_refusal_reasons.py`, `test_boot_skips_upgrade_at_head.py` and `test_default_origins.py`.
    - **EXPECTED OUTCOME**: Tests PASS (confirms the bug is fixed).
    - _Requirements: 2.4, 2.5, 2.6_

  - [~] 5.6 Verify the preservation tests still pass
    - **Property 2: Preservation** - Field Team API hand-off and access rules
    - **IMPORTANT**: Re-run the SAME tests from task 2.3. Do NOT write new tests.
    - From `backend-task/`: run `test_preservation_handoff.py` and `test_billing_contract.py`, then the whole suite with `python -m pytest tests/ -q -n auto --dist loadscope`.
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions).
    - _Requirements: 3.5, 3.6, 3.10_

- [ ] 6. Fix C5: plan gates on the server (P0)

  - [~] 6.1 Return per-feature gates from the subscription view
    - `_subscription_view` in `backend/routes/auth.py` adds `gates` with `ai`, `field_team`, `hybrid_sync` and `web_preview`, using the formulas of design C5.1: `exempt` is true for an admin caller, `pro` is `effective_plan(plan_holder) == "pro"`, and only `hybrid_sync` depends on `subscription_enforced()`. `enforced` stays in the response for older clients; staff inherit the owner's plan through `plan_holder`.
    - Tests: `test_settings_gates.py` passes. Extend it with the Property 7 server table: plan {pro, free, missing} × status {trial, active, none} × `SUBSCRIPTION_ENFORCED` {0, 1} × role {owner, staff, cashier, supply adder, admin} against the C5.1 formulas.
    - The `SUBSCRIPTION_ENFORCED=0` deploy parameter (C5.2) is set with the deploy-script changes of C13 (part 2).
    - _Bug_Condition: isBugCondition(X) for C5: the client infers gates from `enforced` and an unknown plan_
    - _Expected_Behavior: Property 7_
    - _Preservation: Property 2 (3.6, 3.9, 3.14)_
    - _Requirements: 1.7, 1.27, 1.56, 2.7, 2.27, 2.56, 3.6, 3.9, 3.14_

  - [~] 6.2 Verify the C5 exploration test now passes
    - **Property 1: Expected Behavior** - Plan gates follow the server
    - **IMPORTANT**: Re-run the SAME test from task 1.1. Do NOT write a new test.
    - Run `test_settings_gates.py`.
    - **EXPECTED OUTCOME**: Tests PASS (confirms the bug is fixed).
    - _Requirements: 2.7, 2.27, 2.56_

  - [~] 6.3 Verify the preservation tests still pass
    - **Property 2: Preservation** - Plan gates
    - **IMPORTANT**: Re-run the SAME tests from task 2. Do NOT write new tests.
    - Run `test_preservation_billing_api.py -k c3_06` and the existing subscription, settings and `/ask` test files.
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions).
    - _Requirements: 3.6, 3.9, 3.14_

- [ ] 7. Fix C12, P0 subset: admin API infrastructure metrics and JSON errors (P0)

  - [~] 7.1 Declare and guard `psutil`
    - Add `psutil` to the requirements file that `backend/Dockerfile` installs (`backend/requirements_hf.txt` unless the Dockerfile names another) and to the root `requirements.txt`.
    - `backend/routes/admin.py`: import `psutil` once at module level inside `try`. Without it, process metrics are `null` and listed in `unavailable`. Prime a module-level `psutil.Process()` with `cpu_percent(None)` at import, so later readings are real.
    - Tests: the `psutil`-missing case of `test_infrastructure_metrics.py` passes.
    - _Bug_Condition: isBugCondition(X) for C12: the image lacks `psutil` and the metrics route fails_
    - _Expected_Behavior: Property 12_
    - _Preservation: Property 2 (3.17)_
    - _Requirements: 1.43, 2.43, 3.17_

  - [~] 7.2 Count rows without reading tenant tables
    - `get_admin_infrastructure_metrics` in `backend/routes/admin.py`: row counts come from `SELECT relname, reltuples::bigint FROM pg_class WHERE relname IN (...)`; negative estimates and SQLite give `null`. No tenant table is read, so remove any `tenant_scope.ALLOWED` entry that only this function needed (the guard rejects stale entries). Region comes from `CLOUD_RUN_REGION`, else `null`.
    - Tests: `test_tenant_scope.py::test_no_unscoped_tenant_reads` passes (baseline regression fixed). Add a SQLite case with `null` row counts and a Postgres case (testcontainers) that reads `reltuples`.
    - _Bug_Condition: isBugCondition(X) for C12: the metrics route counts rows across tenants_
    - _Expected_Behavior: Property 12_
    - _Preservation: Property 2 (3.3)_
    - _Requirements: 1.44, 2.44, 3.3_

  - [~] 7.3 Probe only configured hosts and cache the response
    - Same function: probe https://staterbill.com and the Field Team API concurrently with a 2 s timeout each; probe Hugging Face only when `HF_STANDBY_URL` is set. Cache the whole response in process for 45 s; `?refresh=1` bypasses the cache at most once per 10 s.
    - Tests: `test_infrastructure_metrics.py` passes. Add cache cases with a monkeypatched clock and probes: a second call within 45 s is served from the cache, and two `?refresh=1` calls within 10 s refresh once. Reset the cache in a fixture.
    - _Bug_Condition: isBugCondition(X) for C12: every page load probes the retired Space and recomputes all metrics_
    - _Expected_Behavior: Property 12_
    - _Preservation: Property 2 (3.17)_
    - _Requirements: 1.43, 1.44, 2.43, 2.44_

  - [~] 7.4 Return JSON 500s from the rate-limits and usage-stats routes
    - `get_rate_limits` (`GET /admin/rate-limits/{user_id}`) and `get_all_usage_stats` (`GET /admin/usage-stats`) in `backend/routes/admin.py` adopt the error handling of the other admin routes: `HTTPException` passes through, and any other `Exception` becomes `HTTPException(500)`, so the error reaches the browser through CORS as JSON.
    - Tests: `test_admin_routes_json_500.py` passes for every `/admin/*` route.
    - _Bug_Condition: isBugCondition(X) for C12: an unexpected error gives a plain-text 500 without CORS headers_
    - _Expected_Behavior: Property 12_
    - _Preservation: Property 2 (3.17)_
    - _Requirements: 1.46, 2.46, 3.17_

  - [~] 7.5 Add `GET /admin/session` for the console's SSO check (needed by task 10.3)
    - New route in `backend/routes/admin.py`: runs `svc.require_admin(current_user["id"], db)` and returns the admin's `id`, `username` and `role`. It inherits the router's `ADMIN_API_ENABLED` gate and uses the error handling of 7.4.
    - Test `backend/tests/test_admin_session_route.py`: an admin gets 200, a non-admin 403, a missing token a marked 401, and the route is 404 without `ADMIN_API_ENABLED`. The `test_admin_routes_json_500.py` sweep covers it.
    - _Bug_Condition: isBugCondition(X) for C12: the console trusts the role inside a redeemed ticket without asking the server_
    - _Expected_Behavior: Property 12_
    - _Preservation: Property 2 (3.17)_
    - _Requirements: 1.50, 2.50, 3.17_

  - [~] 7.6 Verify the C12 P0 exploration tests now pass
    - **Property 1: Expected Behavior** - Admin console reliability (P0 subset)
    - **IMPORTANT**: Re-run the SAME tests from task 1.2. Do NOT write new tests.
    - Run `test_infrastructure_metrics.py`, `test_admin_routes_json_500.py`, `test_tenant_scope.py` and `test_no_retired_host_defaults.py -k backend` (the `backend` case passes once C1 and 7.3 are in).
    - **EXPECTED OUTCOME**: Tests PASS (confirms the bug is fixed).
    - _Requirements: 2.43, 2.44, 2.46_

  - [~] 7.7 Verify the preservation tests still pass
    - **Property 2: Preservation** - Admin API
    - **IMPORTANT**: Re-run the SAME tests from task 2. Do NOT write new tests.
    - Run `test_preservation_billing_api.py -k "c3_03 or c3_17"` and the existing admin test files (2FA, audit, authority re-checks) with `-n auto --dist loadscope`.
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions).
    - _Requirements: 3.3, 3.17_

- [ ] 8. Fix C9: Billing web app (P0; depends on tasks 4 and 6)
  - Paths below are under `frontend-billing/src/` unless stated. After each leaf, syntax-check the changed files with the helper; the user runs the vitest and Playwright files locally.

  - [~] 8.1 Launch Field Team reliably
    - `config/fieldTeam.js`: `getFieldTeamUrl()` falls back to `FIELD_TEAM_CLOUD_URL` on every build (`VITE_FIELD_TEAM_URL` still overrides it; the local-fixture rule is unchanged). New `fieldTeamLaunchUrl(user)` returns the Field Team URL with `from_billing=1`, `billing_origin` and `billing_business` and no ticket.
    - `openFieldTeam` (plain click, after `preventDefault`): when `window.open` returns null, show the blocked-window toast; otherwise write "Opening Field Team…" into the new window, request a ticket with `{purpose: "field_team"}` within 65 s, and navigate. When the ticket fails, navigate without `sso` and show the hand-over toast (texts in design C9.1). `cloudTicket()` (desktop) sends the same purpose.
    - The sidebar item in `layouts/AppLayout.jsx` and `components/layout/WorkspaceSwitcher.jsx` use `fieldTeamLaunchUrl(user)` as the anchor `href`, so "Open in new tab" lands on Field Team's sign-in for that business.
    - Tests: `fieldTeamLaunch.test.js` (task 1.6).
    - _Bug_Condition: isBugCondition(X) for C9: the Field Team launch fails silently or uses a retired host_
    - _Expected_Behavior: Property 1 (2.1, 2.8)_
    - _Preservation: Property 2 (3.18)_
    - _Requirements: 1.1, 1.8, 2.1, 2.8, 3.18_

  - [~] 8.2 Open the AI dashboard inside the click and end its session on sign-out
    - `config/aiDashboard.js`: `openAiDashboard` opens or reuses the `ai_dashboard` window inside the click, then requests `{purpose: "ai_dashboard"}`, then sets `location.href` with `?sso=`; the blocked-window and failed-ticket toasts match Field Team's. New `notifyAiLogout()` posts `{type: "AUTH_LOGOUT"}` to a live `_aiWindow` at the dashboard origin.
    - `contexts/AuthContext.jsx`: a user-initiated sign-out calls `notifyAiLogout()` and waits up to 3 s for `POST /auth/logout` (with `keepalive: true` where supported) before discarding the token; a sign-out caused by a session rejection skips the call. The hidden frame uses `getAiDashboardUrl()`, and the port-5173 default leaves this file. The desktop path (port 8451) is unchanged.
    - Tests: `aiDashboardOpen.test.js` (task 1.6).
    - _Bug_Condition: isBugCondition(X) for C9: `window.open` runs after an `await`, and Billing sign-out leaves the dashboard signed in_
    - _Expected_Behavior: Property 1 (2.8, 2.12, 2.14)_
    - _Preservation: Property 2 (3.15)_
    - _Requirements: 1.8, 1.12, 1.14, 2.8, 2.12, 2.14, 3.15_

  - [~] 8.3 Sign out only on a session rejection; add sliding refresh and the settings retry
    - New `api/httpErrors.js` with `isSessionRejection(res)`: true when the response comes from the current API base and `WWW-Authenticate` contains `invalid_token`.
    - `api/client.js` (`request()`, `authFetch`) and `contexts/AuthContext.jsx` (`fetchProfile`, `fetchSettings`, the business-config fetch): a marked 401 or 404 signs out, as today. An unmarked 401 from the own backend triggers one `POST /auth/refresh`: a 401 from the refresh signs out; otherwise the request is retried once and the session stays. Every other 401 or 404 shows its error and keeps the session.
    - New `hooks/useSessionRefresh.js` (web only), mounted from `AuthContext.jsx`: every 5 minutes and on `focus` or `visibilitychange`, read `exp` (unverified decode) and call `POST /auth/refresh` when fewer than 6 h remain. Store the new token through `utils/tokenStorage.js`, so a `storage` event reaches the other tabs. Network errors and 5xx retry on the next tick.
    - `fetchSettings` retries after 2, 4, 8 and 16 s and then every 30 s, and on `focus` and `online`; `planKnown` stays false meanwhile.
    - Tests: `sessionRejection.test.js` (task 1.6). Add the Property 6 `it.each` table: status {200, 401, 403, 404, 429, 500, 503, 504} × marker {present, absent} × origin {own base, other} × body {JSON, HTML}, against `signsOut = ownBase AND (marked OR (status = 401 AND refresh returns 401))`.
    - _Bug_Condition: isBugCondition(X) for C9: an unmarked 401 or 404 signs the owner out, and sessions are never extended_
    - _Expected_Behavior: Property 6_
    - _Preservation: Property 2 (3.1)_
    - _Requirements: 1.28, 1.29, 1.30, 2.28, 2.29, 2.30, 3.1_

  - [~] 8.4 Gate on a known plan and key the preview timer per BizID and user
    - `layouts/AppLayout.jsx`: `planKnown = typeof settings?.subscription?.plan === 'string'`; `gate(name) = planKnown && (subscription.gates?.[name] ?? legacyGate(name))`, where `legacyGate` keeps today's rule for a server without `gates`. `EXTERNAL_APPS` entries name their gate (`field_team` or `ai`); `handleOpenExternal` and the PRO badges use `gate(app.gate)` instead of `aiGated`; the preview lock uses `gate('web_preview')` instead of `isFreePlan`. Cashiers and supply adders still return early.
    - Preview timer: key `bizassist_preview_start:<BizID>:<userId>` in sessionStorage. Login, logout and account switch (`contexts/AuthContext.jsx`) remove every key with that prefix and the legacy `bizassist_session_start_time`. The timer starts only when `gate('web_preview')` is true and the trial-ended screen is not due; the desktop never locks.
    - Tests: `planGates.test.jsx` (task 1.6). Add the Property 7 client table for `gate()`: plan × status × enforcement × role, with and without `gates`.
    - _Bug_Condition: isBugCondition(X) for C9: a Pro alert, PRO badge or preview lock appears before the plan is known, or a timer carries over between accounts_
    - _Expected_Behavior: Property 7_
    - _Preservation: Property 2 (3.8, 3.9, 3.14)_
    - _Requirements: 1.7, 1.27, 1.56, 2.7, 2.27, 2.56, 3.8, 3.9, 3.14_

  - [~] 8.5 Remove the account lookups before sign-in (web app and API)
    - `backend/routes/auth.py`: delete `biz_id_check` (`POST /api/biz_id/check`) and the `/api/auth/check-username` routes (`check_username_get` and any POST twin), with request models that become unused. Old bundles get 404, which the old Login page treats as "no result". Existing tests that pin these lookups encode the defect of 1.17 to 1.19: change them to expect 404 and list them in the task's completion note.
    - `pages/Login.jsx`: drop the `/api/biz_id/check` effect, `bizLookup` and `noBizFound`; `handleOwnerContinue` goes straight to the credential step; a failed sign-in shows one message, "Wrong username or password." The desktop's cloud-verified recovery inside `login` is unchanged.
    - `pages/Register.jsx`: drop the live username check; a taken username is reported from the signup response.
    - Tests: `test_session_invalidation.py::test_staff_cannot_run_owner_sync_pull_or_discover_accounts_anonymously` passes (baseline regression fixed) and `test_preservation_billing_api.py -k c3_02` still passes; the lookup cases of `authBudget.test.js` (task 1.6).
    - _Bug_Condition: isBugCondition(X) for C9: anonymous callers can test whether a BizID or username exists_
    - _Expected_Behavior: Property 13_
    - _Preservation: Property 2 (3.2)_
    - _Requirements: 1.17, 1.18, 1.19, 2.17, 2.18, 2.19, 3.2_

  - [~] 8.6 Wait out cold starts on sign-in and show readable errors
    - `api/httpErrors.js`: add `readableError(status, contentType, bodyText)` and `retryDelayMs(attempt, retryAfter)` with the messages of design C9.4.
    - `api/client.js`: `request()` and `authFetch` retry GET, HEAD and requests that carry `X-Client-Request-Id` on 429, 502, 503, 504 and network errors, at most three times within 60 s, honouring `Retry-After` up to 30 s. None of these statuses signs the user out.
    - On the web, `login`, staff login and `signup` (`contexts/AuthContext.jsx`, through the failover helper) use `WEB_AUTH_BUDGET_MS = 65000`. After 4 s the form shows "Waking up the server… this can take up to a minute."; a time-out shows "The server did not respond. Check your connection and try again." The desktop keeps 8 s and its local-service message.
    - `pages/Login.jsx` sends one `fetch(API_BASE + '/health', { mode: 'no-cors' })` on mount on the web and ignores the result.
    - Signup sends `X-Client-Request-Id`. After a time-out or network error it signs in with the same credentials: success continues as a successful signup; 401 retries the signup once with the same request id; anything else shows the server's message.
    - Tests: `authBudget.test.js` and `httpErrors.test.js` (task 1.6). Add unit tables for `retryDelayMs` (seconds, HTTP dates, garbage, values above the cap) and `readableError`.
    - _Bug_Condition: isBugCondition(X) for C9: sign-in gives up after 6 s during a cold start, and HTML error pages reach the user_
    - _Expected_Behavior: Property 6 (2.22) and Property 13 (2.20, 2.21)_
    - _Preservation: Property 2 (3.16)_
    - _Requirements: 1.20, 1.21, 1.22, 2.20, 2.21, 2.22, 3.16_

  - [~] 8.7 Fix the login layout
    - `index.css`: one `.login-card` rule (`width: 100%; max-width: var(--login-card-width, 420px); box-sizing: border-box`), a `.login-card--wide` modifier (440 px) for Register, and `.login-footer` at the same width. `.login-container`: `width: 100%` instead of `100vw`, `min-height: 100vh` followed by `min-height: 100dvh`, `overflow-y: auto`, and a column flex layout with `justify-content: flex-start`; the card wrapper uses `margin-block: auto`. `.login-backdrop-grid` has 4, 2 and 1 columns at 1024 px and wider, 600 px and wider, and below.
    - `pages/Login.jsx` and `pages/Register.jsx`: move the inline layout styles to these classes; move the "⚙ System check" trigger inside the login container, with its panel on the modal layer.
    - Extend `e2e/login-layout.spec.js` with 320×568 and 1920×1080 and with the Register page. The user runs it locally and reviews the screenshots.
    - _Bug_Condition: isBugCondition(X) for C9: the card top, footer or System check is unreachable or misaligned at common viewports_
    - _Expected_Behavior: Property 13_
    - _Preservation: Property 2 (3.16)_
    - _Requirements: 1.23, 1.24, 1.25, 1.26, 2.23, 2.24, 2.25, 2.26_

  - [~] 8.8 Verify the C9 exploration tests now pass
    - **Property 1: Expected Behavior** - Billing web app
    - **IMPORTANT**: Re-run the SAME tests from task 1.6. Do NOT write new tests.
    - Agent: run `test_session_invalidation.py` from `backend/` and syntax-check every file changed in 8.1 to 8.7.
    - User, locally in `frontend-billing`: `npx vitest run --pool=threads --reporter=dot` and `npx playwright test e2e/login-layout.spec.js`; the task 1.6 tests pass.
    - **EXPECTED OUTCOME**: Tests PASS (confirms the bug is fixed).
    - _Requirements: 2.1, 2.7, 2.8, 2.12, 2.14, 2.17, 2.18, 2.19, 2.20, 2.21, 2.22, 2.23, 2.24, 2.25, 2.26, 2.27, 2.28, 2.29, 2.30, 2.56_

  - [~] 8.9 Verify the preservation tests still pass
    - **Property 2: Preservation** - Billing web app
    - **IMPORTANT**: Re-run the SAME tests from task 2. Do NOT write new tests.
    - Agent: run `test_preservation_billing_api.py -k "c3_01 or c3_02"`. User, locally: the full `frontend-billing` vitest run, including `preservation.test.jsx` (task 2.4).
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions).
    - _Requirements: 3.1, 3.2, 3.8, 3.9, 3.14, 3.15, 3.16, 3.18_

- [ ] 9. Fix C10: Field Team web app (P0; depends on task 5)
  - Paths below are under `frontend-task/src/`. After each leaf, syntax-check the changed files with the helper; the user runs vitest locally.

  - [~] 9.1 Trust the Billing origins and fall back to staterbill.com
    - `lib/theme.js`: `DEFAULT_BILLING_ORIGINS = ['https://staterbill.com', 'https://www.staterbill.com', 'https://bizassist-billing.vercel.app']`. `sanitizeBillingUrl` accepts these, every origin in the comma-separated `VITE_BILLING_URL`, and local hosts on ports 5174 and 8450, as today. `BILLING_CLOUD_URL`, the fallback for "Back to Billing" and Register links, becomes https://staterbill.com. Appearance tokens are still sanitized.
    - Tests: `theme.test.js` (task 1.7). Add the Property 5 `it.each` table: the candidate origins of design "Property-Based Tests" × `VITE_BILLING_URL` lists.
    - _Bug_Condition: isBugCondition(X) for C10: Field Team distrusts staterbill.com and links back to a retired host_
    - _Expected_Behavior: Property 5_
    - _Preservation: Property 2 (3.7, 3.10, 3.19)_
    - _Requirements: 1.2, 2.2, 3.7, 3.10, 3.19_

  - [~] 9.2 Ask for the named business when a launch has no ticket
    - `lib/auth.jsx`: for a trusted origin without a usable ticket, the existing path clears the stored session; its notice becomes "Sign in with the Billing account for <BizID> to continue." The different-business guard in `startBillingBridge` is unchanged.
    - Tests: `auth.test.jsx` (task 1.7).
    - _Bug_Condition: isBugCondition(X) for C10: a launch without a ticket restores another session silently_
    - _Expected_Behavior: Property 1 (2.3, 2.8)_
    - _Preservation: Property 2 (3.18)_
    - _Requirements: 1.3, 1.8, 2.3, 2.8, 3.18_

  - [~] 9.3 Explain connection failures and retry the ticket exchange
    - `lib/api.js`: a failed fetch while `navigator.onLine === false` keeps "No connection — check mobile data / Wi-Fi."; otherwise the message is "Could not reach the Field Team server. It may be starting up."
    - `POST /api/auth/exchange` (`lib/api.js`, called from `lib/auth.jsx`) gets a 70 s timeout and retries network errors and 429, 502, 503 and 504 after 2, 4 and 8 s while the sign-in screen shows "Field Team is starting…". The retry window is `exp - iat + 10` seconds (legacy tickets: 30) from page start, taken from the ticket's own fields, so a wrong phone clock does not shorten it.
    - Tests: `api.test.js` (task 1.7).
    - _Bug_Condition: isBugCondition(X) for C10: an online failure reads as "No connection", and the exchange gives up during a cold start_
    - _Expected_Behavior: Property 1 (2.4) and Property 4 (2.5)_
    - _Preservation: Property 2 (3.18)_
    - _Requirements: 1.4, 1.5, 2.4, 2.5_

  - [~] 9.4 Verify the C10 exploration tests now pass
    - **Property 1: Expected Behavior** - Field Team web app
    - **IMPORTANT**: Re-run the SAME tests from task 1.7. Do NOT write new tests.
    - Agent: syntax-check every file changed in 9.1 to 9.3. User, locally in `frontend-task`: `npx vitest run --pool=threads --reporter=dot`.
    - **EXPECTED OUTCOME**: Tests PASS (confirms the bug is fixed).
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.8_

  - [~] 9.5 Verify the preservation tests still pass
    - **Property 2: Preservation** - Field Team web app
    - **IMPORTANT**: Re-run the SAME tests from task 2.4. Do NOT write new tests.
    - User, locally: the full `frontend-task` vitest run, including `preservation.test.js`.
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions).
    - _Requirements: 3.7, 3.10, 3.18, 3.19_

- [ ] 10. Fix C11: AI dashboard and admin console web apps (P0; depends on tasks 4 and 7)
  - After each leaf, syntax-check the changed files with the helper; the user runs vitest and `npm run lint` locally.

  - [~] 10.1 Trust the Billing origins in both hand-off helpers
    - `frontend-ai/src/utils/handoff.js` and `frontend-admin/src/utils/handoff.js`: `trustedHandoff` accepts `window.location.origin`, the three default Billing origins, every origin in the comma-separated `VITE_BILLING_URL`, and the existing local rule. The `event.source === opener` check is unchanged.
    - Tests: both `handoff.test.js` files (task 1.7). Add the Property 5 table (origin × `VITE_BILLING_URL` list × source {opener, other window}) to each.
    - _Bug_Condition: isBugCondition(X) for C11: hand-off messages from staterbill.com are dropped_
    - _Expected_Behavior: Property 5_
    - _Preservation: Property 2 (3.7, 3.10)_
    - _Requirements: 1.13, 2.13, 3.7, 3.10_

  - [~] 10.2 Handle AI dashboard sign-in failures and session rejections
    - `frontend-ai/src/contexts/AuthContext.jsx`: a failed `?sso=` or `SSO_TICKET` redemption calls `clearSession()` and shows "Billing could not sign you in. Open Dashboard BIZASSIST from Billing again, or sign in here." with a sign-in button. A marked 401 clears the session; an unmarked one does not. An `AUTH_LOGOUT` message from the trusted opener clears the session (keep the existing handler, or add one if missing).
    - New `frontend-ai/src/utils/httpErrors.js` with copies of Billing's `readableError` and `isSessionRejection`, used for these errors.
    - Tests: `frontend-ai` `authContext.test.jsx` (task 1.7).
    - _Bug_Condition: isBugCondition(X) for C11: a failed hand-off keeps a stale session, and a revoked dashboard session stays open_
    - _Expected_Behavior: Property 6 (2.14, 2.15)_
    - _Preservation: Property 2 (3.1)_
    - _Requirements: 1.14, 1.15, 2.14, 2.15, 3.1_

  - [~] 10.3 Confirm the admin role with the server and clear everything on logout
    - `frontend-admin/src/contexts/AuthContext.jsx`: after `/redeem-ticket` returns `role === 'admin'`, call `GET /admin/session` (task 7.5) and set `adminUser` only when it returns 200. `?logout=true` removes `user`, `admin_user`, `biz_name` and every stored token.
    - Tests: the SSO and logout cases of `frontend-admin` `authContext.test.jsx` (task 1.7).
    - _Bug_Condition: isBugCondition(X) for C11: the console sets an admin session from the ticket alone, and logout leaves tokens behind_
    - _Expected_Behavior: Property 12 (2.50)_
    - _Preservation: Property 2 (3.17)_
    - _Requirements: 1.50, 2.50, 3.17_

  - [~] 10.4 Keep the admin session alive and return to the same page
    - `frontend-admin`: `authFetch` signs out only on a marked 401, using a copy of `isSessionRejection` in new `src/utils/httpErrors.js`. New `src/hooks/useSessionRefresh.js` refreshes the admin token within 6 h of expiry and on focus; if the refresh fails, a banner warns 10 minutes before expiry.
    - Before any redirect to `/admin/login`, store the current path in sessionStorage; `src/pages/admin/AdminLogin.jsx` returns to it when it is a same-origin path under `/admin/`, otherwise to `/admin/dashboard`.
    - Tests: the session and return-path cases of `frontend-admin` `authContext.test.jsx` (task 1.7).
    - _Bug_Condition: isBugCondition(X) for C11: the admin console signs out on any 401 and forgets the page_
    - _Expected_Behavior: Property 6 (2.31)_
    - _Preservation: Property 2 (3.1)_
    - _Requirements: 1.31, 2.31, 3.1_

  - [~] 10.5 Fix the Infrastructure page and the admin lint error
    - `frontend-admin/src/pages/admin/AdminInfrastructure.jsx` and the stylesheet it imports: each missing metric shows "unavailable" (no invented values); the error banner shows the HTTP status and `detail`, with the console's existing retry button; auto-refresh is off by default, with an opt-in 60 s interval that pauses while `document.hidden` and skips a tick while a request is in flight.
    - Remove the unused `useDialog` import, replace "alert-triangle" with an icon that the icon map defines, and add the `@keyframes` rule for `.spinning`.
    - Tests: `AdminInfrastructure.test.jsx` (task 1.7) and a clean `npm run lint` in `frontend-admin`.
    - _Bug_Condition: isBugCondition(X) for C11: the page invents values, hides the error, and polls while hidden_
    - _Expected_Behavior: Property 12 (2.45)_
    - _Preservation: Property 2 (3.17)_
    - _Requirements: 1.45, 2.45_

  - [~] 10.6 Verify the C11 exploration tests now pass
    - **Property 1: Expected Behavior** - AI dashboard and admin console
    - **IMPORTANT**: Re-run the SAME tests from task 1.7. Do NOT write new tests.
    - Agent: syntax-check every file changed in 10.1 to 10.5 and run `test_admin_session_route.py` from `backend/`. User, locally: `npx vitest run --pool=threads --reporter=dot` in `frontend-ai` and `frontend-admin`, and `npm run lint` in `frontend-admin`.
    - **EXPECTED OUTCOME**: Tests PASS (confirms the bug is fixed).
    - _Requirements: 2.13, 2.14, 2.15, 2.31, 2.45, 2.50_

  - [~] 10.7 Verify the preservation tests still pass
    - **Property 2: Preservation** - AI dashboard and admin console
    - **IMPORTANT**: Re-run the SAME tests from task 2. Do NOT write new tests.
    - Agent: run `test_preservation_billing_api.py -k c3_17`. User, locally: the full vitest runs in `frontend-ai` and `frontend-admin`, including `handoff.preservation.test.js`.
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions).
    - _Requirements: 3.1, 3.7, 3.10, 3.17_

- [ ] 11. Fix C6: real-time streams (P0; depends on tasks 3 and 4)
  - The `--max-instances 1` setting (C6.6) is applied with the deploy-script changes of C13 (part 2).

  - [~] 11.1 Keep a per-business event history in `RealtimeManager`
    - `backend/services/realtime.py`: `epoch` (8 hex characters from `uuid4` at construction), a per-business sequence, and a per-business history `deque` of `(seq, event)` with `maxlen = SSE_REPLAY_BUFFER` (default 256). `broadcast()` assigns the sequence number and appends to the history before its first `await`, then queues the same event object as today; queue items stay plain event dicts. Presence events are delivered but not buffered.
    - `subscribe(business_id)` keeps its signature and its 429 cap. New `subscribe_from(business_id, last_event_id) -> (queue, replay, status)` returns `none` without an id, `complete` when the epoch matches and the history holds every later event, and `gap` otherwise; it subscribes and copies the history in the same event-loop step.
    - Tests: unit tests for the three statuses and for identity-based sequence lookup with duplicate coalescing. Add `test_realtime_replay_property.py`: fixed seeds generate broadcasts over three businesses with buffer sizes 4 and 256, random cut points and restarts (a new manager); the delivered sequence equals the broadcast sequence without duplicates, or `gap` is reported exactly when the buffer cannot cover the cut. `test_realtime_sync.py` and `test_sse_hardening.py` pass unchanged.
    - _Bug_Condition: isBugCondition(X) for C6: events published while a stream is down are lost_
    - _Expected_Behavior: Property 9_
    - _Preservation: Property 2 (3.20)_
    - _Requirements: 1.38, 1.40, 2.38, 2.40, 3.20_

  - [~] 11.2 Rotate streams with ids, `hello` and replay
    - `sse_realtime_feed` in `backend/core/api/realtime.py` takes `last_event_id` from the query string or the `Last-Event-ID` header, calls `subscribe_from`, and sends `retry: 5000`; `event: hello` with `{"epoch": ..., "replay": status}`; the replayed frames, then live frames, each with `id: <epoch>-<seq>`; keep-alive comments every 15 s, as today; and after `SSE_MAX_STREAM_SECONDS` (default 100) `event: rotate` with `data: {}`, then it returns. The token-version check on every loop stays.
    - Tests: `test_sse_rotation_replay.py` passes; `test_preservation_billing_api.py -k c3_20` still passes.
    - _Bug_Condition: isBugCondition(X) for C6: the platform cuts streams at 120 s with no ids to resume from_
    - _Expected_Behavior: Property 9_
    - _Preservation: Property 2 (3.20)_
    - _Requirements: 1.38, 1.40, 2.38, 2.40, 3.20_

  - [~] 11.3 Reconnect quietly in the Billing web app
    - New `frontend-billing/src/sync/sseConnection.js` with `createSseConnection({ fetchTicket, onEvent, onStatus, onGap })`, per design C6.4: on `rotate`, close the `EventSource` at once and reconnect after 0 to 1 s with a new ticket and no status change; on a `gap` hello, call `onGap()`; on an error or a close without `rotate`, back off from 1 s, doubling to 30 s with ±30 % jitter, reset by the next `hello`; report `degraded` only after 30 s without a connection.
    - `frontend-billing/src/hooks/useRealtimeLeader.js` uses the helper: no toasts for connecting or reconnecting; one "Live sync interrupted. Retrying…" toast after 30 s down, and "Live sync restored" only after that; `sync.reconnect` only from `onGap`; the session pause counts only failures that were not rotations.
    - `frontend-billing/src/b2b/useB2BRealtime.js` replaces its fixed 5 s retry with the helper; its `onGap` refetches the B2B lists once.
    - Tests: `realtimeRotate.test.js` (task 1.6). Add an `sseConnection` backoff and jitter table with fake timers. Syntax-check the three files.
    - _Bug_Condition: isBugCondition(X) for C6: every rotation shows toasts and triggers a full reconnect_
    - _Expected_Behavior: Property 9_
    - _Preservation: Property 2 (3.20)_
    - _Requirements: 1.38, 2.38, 3.20_

  - [~] 11.4 Detect dead streams in the desktop cloud listener
    - `_Listener.run` in `backend/services/cloud_listener.py`: `httpx.Timeout(connect=10.0, read=45.0, write=10.0, pool=10.0)`; reset the backoff to `_RECONNECT_BASE_SEC` once a stream answers 200 and delivers its first line; treat `event: rotate` as a clean end and reconnect after 1 s; count a read timeout as a drop; after every reconnect, run one pull that respects `_MIN_PULL_GAP_SEC`.
    - Tests: `test_cloud_listener_timeouts.py` passes. Add cases for the 1 s reconnect after `rotate` and the single catch-up pull.
    - _Bug_Condition: isBugCondition(X) for C6: a silent stream hangs forever and the backoff never resets_
    - _Expected_Behavior: Property 9_
    - _Preservation: Property 2 (3.20)_
    - _Requirements: 1.39, 2.39_

  - [~] 11.5 Verify the C6 exploration tests now pass
    - **Property 1: Expected Behavior** - Real-time continuity
    - **IMPORTANT**: Re-run the SAME tests from tasks 1.2 and 1.6. Do NOT write new tests.
    - Agent: run `test_sse_rotation_replay.py` and `test_cloud_listener_timeouts.py`. User, locally: `realtimeRotate.test.js` in `frontend-billing`.
    - **EXPECTED OUTCOME**: Tests PASS (confirms the bug is fixed).
    - _Requirements: 2.38, 2.39, 2.40_

  - [~] 11.6 Verify the preservation tests still pass
    - **Property 2: Preservation** - Streams
    - **IMPORTANT**: Re-run the SAME tests from task 2. Do NOT write new tests.
    - Run `test_preservation_billing_api.py -k c3_20`, `test_realtime_sync.py`, `test_sse_hardening.py` and the cloud-listener and B2B realtime test files.
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions).
    - _Requirements: 3.20_

- [~] 12. Checkpoint - P0 fixes: ensure all tests pass
  - Start both backend suites at the same time (for example as two background processes) and wait for both:
    - from `backend/`: `$env:GROQ_API_KEY='mock_groq_api_key'; python -m pytest tests/ -q -n auto --dist loadscope`
    - from `backend-task/`: `python -m pytest tests/ -q -n auto --dist loadscope`
  - Expected:
    - No failures except `tests/test_intent_router.py::test_semantic_router_eval_accuracy`.
    - `test_staff_cannot_run_owner_sync_pull_or_discover_accounts_anonymously` and `test_no_unscoped_tenant_reads` now pass.
    - The task 1.3 and 1.4 files report xfailed. Note which `test_no_retired_host_defaults.py` cases (`dev`, `frontend_*`) still xfail; part 2 (C13) clears them.
    - Billing passes at least 2526 tests plus the new ones; backend-task passes fully.
  - Syntax-check every JS/JSX file added or changed in tasks 1 to 11 with the helper.
  - Ask the user to run these locally (after `npm install` where `node_modules` is missing) and report the results:
    - `frontend-billing`: `npx vitest run --pool=threads --reporter=dot` and `npx playwright test e2e/login-layout.spec.js` (review the saved screenshots)
    - `frontend-task`: `npx vitest run --pool=threads --reporter=dot`
    - `frontend-ai`: `npx vitest run --pool=threads --reporter=dot`
    - `frontend-admin`: `npx vitest run --pool=threads --reporter=dot` and `npm run lint`
  - Do not run `run_tests.ps1`. Ask the user if questions arise; part 2 starts after the user confirms the local results.

- [ ] 13. Fix C2: billing API boot fast path and change-feed fixes (P1)

  - [~] 13.1 Remove the C2 xfail markers
    - Delete the module-level `pytestmark = pytest.mark.xfail(strict=True, reason="bug condition C2, fixed in part 2")` from `backend/tests/test_boot_fast_path.py` and `backend/tests/test_change_feed_errors.py`. Change nothing else in either file.
    - Run both files. They must FAIL with the counterexamples task 1.3 recorded: a per-row existence SELECT on SQLite, DDL on the second Postgres boot (when Docker is available), the `NameError`, and the "transaction block" error logged as "peer completed". If a case passes, stop and report it: its counterexample no longer reproduces.
    - _Bug_Condition: isBugCondition(X) for C2, as recorded by the task 1.3 counterexamples_
    - _Expected_Behavior: Property 1 and Property 8_
    - _Preservation: Property 2 (3.11, 3.12); this leaf changes tests only_
    - _Requirements: 1.36, 1.37_

  - [~] 13.2 Add the `schema_state` table, its Alembic revision and grants
    - `backend/database/models.py`, per design C2.1: new `SchemaState` (`__tablename__ = "schema_state"`; `key` String primary key, `signature` String not null, `applied_at` timezone-aware DateTime, `applied_by` String). It is part of `Base.metadata`, so the conftest `drop_all`/`create_all` cycle resets it.
    - Event-key index for 13.5: if the `sync_feed_events` model has no index on `(business_id, entity, row_uid)` (check its `__table_args__` and the revisions), add `Index("ix_sync_feed_events_business_entity_row_uid", "business_id", "entity", "row_uid")`. `create_all` does not add indexes to existing tables, so if `migration.py` adds other indexes through a boot step, add this one there as well.
    - New revision `backend/alembic/versions/<rev>_add_schema_state.py`, with `down_revision` set to the output of `alembic heads`:
      - creates `schema_state`, and the index when it was added above; on Postgres the index uses `CREATE INDEX CONCURRENTLY IF NOT EXISTS` inside `op.get_context().autocommit_block()`, because `sync_feed_events` is written while a revision deploys;
      - on Postgres, enables RLS on `schema_state` and gives `anon` and `authenticated` no privilege, as `aea3a6d76429_enable_rls_and_restrict_api.py` and `9c2f4b8a1d3e_fail_closed_rls_policies.py` do for other tables, and grants `SELECT` to the runtime role those revisions grant to, so the unprivileged signature check in 13.3 can read the row. If the boot security step in `migration.py` lists tables explicitly, add `schema_state` there too;
      - skips the Postgres-only statements on SQLite.
    - Rollback note, in the revision docstring: the table and index are additive and older revisions ignore them (design "Backward Compatibility"), so an application rollback needs no downgrade. `downgrade()` drops the index (when this revision added it) and the table. To force one full migration after a rollback, set `BIZASSIST_FORCE_MIGRATIONS=1` or delete the `schema_state` row.
    - New `backend/tests/test_schema_state_model.py`: `schema_state` is in `Base.metadata` with the four columns and `key` as primary key. On Postgres (testcontainers, skipped without Docker), upgrading to the new revision creates the table and the index, RLS is on, `anon` and `authenticated` hold no privilege, and the runtime role holds `SELECT`; `downgrade -1` removes the table. Re-run the existing Alembic and startup-schema contract tests (`-k "alembic or schema"`).
    - _Bug_Condition: isBugCondition(X) for C2: boot has nowhere to record that the schema is current, so every boot runs every step_
    - _Expected_Behavior: Property 1 and Property 8_
    - _Preservation: Property 2 (3.11): the table is additive and SQLite creates it like any other table_
    - _Requirements: 1.36, 2.36, 3.11_

  - [~] 13.3 Add the schema-signature fast path (Postgres only)
    - `backend/database/migration.py`, per design C2.2 and C2.3:
      - `MIGRATION_REVISION` constant (bumped by hand when a backfill changes without a model change) and `compute_schema_signature(dialect) -> str`: SHA-256 over `MIGRATION_REVISION`, the `CreateTable` and `CreateIndex` DDL of `Base.metadata` compiled for `dialect` and sorted by name, and the build id (`BIZASSIST_BUILD_ID`, else `K_REVISION`, else empty).
      - `run_migrations_and_seed` on Postgres with the privileged role: `SELECT to_regclass('public.schema_state')`, then one query that reads the stored signature and `to_regprocedure('bizassist_feed_emit(integer,text,jsonb,text)')`. A matching signature with the function present logs `[Migration] schema current, skipped` and returns. With the role check, the fast path issues three statements.
      - Otherwise the existing steps run, and the signature is written only when no step recorded a failure: `_rollback_quietly` appends to a module-level `_STEP_FAILURES` list, which each run clears first.
      - `BIZASSIST_FORCE_MIGRATIONS=1` always takes the slow path.
      - Unprivileged role: the existing readiness check is unchanged (3.11); a differing signature only logs a warning.
      - SQLite runs every step on each start, as today (3.11).
    - `backend/main_groq.py`: the module-level `Base.metadata.create_all(bind=engine)` moves into `_create_tables_at_import(engine)`, which returns early on Postgres; there `create_all` runs inside the slow path. SQLite keeps creating tables at import.
    - New `backend/tests/test_schema_signature.py`:
      - the signature is stable across calls and changes with `MIGRATION_REVISION`, a model column, `K_REVISION` or `BIZASSIST_BUILD_ID`; `BIZASSIST_BUILD_ID` wins over `K_REVISION`;
      - Postgres (testcontainers, skipped without Docker): after one full boot, a second `run_migrations_and_seed()` issues at most three statements and no DDL; `BIZASSIST_FORCE_MIGRATIONS=1` runs the steps; a failure caught by `_rollback_quietly` leaves the stored signature unchanged; the unprivileged role with a stale signature logs the warning and issues no DDL;
      - `_create_tables_at_import` calls a patched `create_all` for a SQLite engine and not for a stub engine whose dialect name is `postgresql`.
    - Re-run `test_boot_fast_path.py` (its Postgres case now passes; the SQLite case fails until 13.5) and `test_preservation_boot_seed.py -k c3_11`.
    - _Bug_Condition: isBugCondition(X) for C2: a Postgres boot with an unchanged schema runs every DDL and backfill step again_
    - _Expected_Behavior: Property 1 and Property 8_
    - _Preservation: Property 2 (3.11)_
    - _Requirements: 1.36, 2.36, 3.11_

  - [~] 13.4 Serialise the slow path under one advisory lock
    - `run_migrations_and_seed` in `backend/database/migration.py`, per design C2.3: the Postgres slow path opens a dedicated connection, runs `SET lock_timeout = '90s'` (module constant `_BOOT_LOCK_TIMEOUT`), takes `pg_advisory_lock(724839101)` and reads the signature again. If a peer wrote the current signature meanwhile, it releases the lock and returns. Otherwise it runs the steps, writes the signature under the 13.3 rule, and calls `pg_advisory_unlock(724839101)` in a `finally` before closing the connection. A lock wait that times out raises, so the revision fails its startup probe (2.37).
    - Boot takes exactly this one advisory lock. If `migration.py` or `change_feed.py` take another advisory lock during boot today (search `pg_advisory`), boot stops taking it and that code runs under this lock. Advisory locks used outside boot stay as they are.
    - New `backend/tests/test_migration_advisory_lock.py` (testcontainers, skipped without Docker):
      - two threads boot at the same time against a stale signature; exactly one runs the steps (count calls of a patched step), and the other returns after its second read;
      - afterwards `pg_locks` holds no advisory lock with `objid = 724839101`, also when a step raises;
      - a statement listener sees one `pg_advisory_lock` per slow-path boot and none on the fast path;
      - with the lock held by another session and `_BOOT_LOCK_TIMEOUT` patched to `'1s'`, boot raises a lock-timeout `OperationalError`.
    - Re-run `test_schema_signature.py` and `test_boot_fast_path.py` (only the SQLite case may still fail, until 13.5).
    - _Bug_Condition: isBugCondition(X) for C2: instances that boot together run the migration steps at the same time_
    - _Expected_Behavior: Property 1 and Property 8_
    - _Preservation: Property 2 (3.11): SQLite takes no lock_
    - _Requirements: 1.36, 2.36, 3.11_

  - [~] 13.5 Seed the change feed with set-based statements
    - The seed step of `install_change_feed` in `backend/database/change_feed.py` (the per-row loop that task 2.2 copied as `_reference_seed`), per design C2.6:
      - Postgres: one statement per table and owner expression, exactly as the design lists it: `SELECT bizassist_feed_emit((<owner expr>), :entity, s.body, 'INSERT')` over `(SELECT to_jsonb(t) AS body, t.id AS _id FROM "<name>" t) s`, where the owner expression is not null and no `sync_feed_events` row has the same business, entity and `COALESCE(s.body->>'uid', s.body->>'id')`, ordered by `s._id`. Each (business, entity, UID) is seeded at most once, and the payload uses the capture trigger's encoding.
      - SQLite: one query per table loads that entity's existing `(business_id, row_uid)` keys into a set, and the loop inserts only the missing rows with today's statements.
      - No per-row SELECT remains on either dialect. The Postgres statement relies on the event-key index from 13.2.
    - New `backend/tests/test_change_feed_seed_pg.py` (testcontainers, skipped without Docker): import `_reference_seed` and the row generator from `test_preservation_boot_seed.py`. For its 25 seeds, the Postgres seed gives the same `(business_id, entity, row_uid)` set and the same per-business revision counts as `_reference_seed` run on SQLite over the same rows; a second seed run emits no event; a statement listener counts one seed statement per table and owner expression.
    - Re-run `test_boot_fast_path.py` (now passes in full) and `test_preservation_boot_seed.py -k c3_12`.
    - _Bug_Condition: isBugCondition(X) for C2: seeding issues one existence SELECT per row_
    - _Expected_Behavior: Property 1 and Property 8_
    - _Preservation: Property 2 (3.12): the same events as `_reference_seed`, and commit ordering unchanged_
    - _Requirements: 1.36, 2.36, 3.12_

  - [~] 13.6 Leave unchanged change-feed functions and triggers alone
    - `install_change_feed` in `backend/database/change_feed.py`, per design C2.5, for each synced table:
      - when `pg_proc.prosrc` of `bizassist_feed_<name>` equals the rendered body after whitespace normalisation, and the table's `bizassist_feed_capture` trigger exists and calls that function (`pg_trigger.tgfoid`), nothing is executed;
      - a different body gets `CREATE OR REPLACE FUNCTION` only, which takes no table lock;
      - a missing or different trigger gets `CREATE OR REPLACE TRIGGER` when `server_version_num` is 140000 or more, else `DROP TRIGGER IF EXISTS` plus `CREATE TRIGGER`.
    - New `backend/tests/test_change_feed_ddl_idempotent.py` (testcontainers, skipped without Docker), with a statement listener:
      - on an installed database, `install_change_feed` issues no CREATE or DROP;
      - a stored body that differs only in whitespace counts as unchanged;
      - after one function body is changed, only that function is replaced; after one trigger is dropped, only that trigger is created;
      - with the server version patched to 130000, the missing trigger is created through `DROP TRIGGER IF EXISTS` plus `CREATE TRIGGER`.
    - Re-run `test_boot_fast_path.py`, `test_change_feed_seed_pg.py` and `test_preservation_boot_seed.py -k c3_12`.
    - _Bug_Condition: isBugCondition(X) for C2: `install_change_feed` re-creates functions and triggers that have not changed, taking table locks on every boot_
    - _Expected_Behavior: Property 1 and Property 8_
    - _Preservation: Property 2 (3.12): the installed functions and triggers capture the same events_
    - _Requirements: 1.36, 2.36, 3.12_

  - [~] 13.7 Add the change-feed logger and classify errors by SQLSTATE
    - This leaf comes before the retry in 13.8 because the retry needs `_sqlstate` and the logger.
    - `backend/database/change_feed.py`, per design C2.5 and C2.7:
      - `logger = logging.getLogger("bizassist.change_feed")`, which removes the `NameError`;
      - `_sqlstate(exc) -> str | None` reads `exc.orig.pgcode` (psycopg2) or `exc.orig.sqlstate` (psycopg 3), else returns `None`;
      - `_change_feed_installed(conn) -> bool`: `bizassist_feed_emit` and every synced table's `bizassist_feed_capture` trigger exist;
      - the per-table substring handler is removed, so errors leave the table loop;
      - in `install_change_feed`, a 40P01 or 55P03 runs `_change_feed_installed` on a fresh connection: installed logs "peer completed" at WARNING and returns, otherwise the error is raised. Any other error is logged with `exc_info` and raised.
    - `backend/database/migration.py`: every `"lock"`/`"deadlock"` substring check (search for the literals) is replaced by `_sqlstate(exc) in {"40P01", "55P03"}`, keeping each handler's action for real lock conflicts. A change-feed error propagates out of `run_migrations_and_seed`, so the revision fails its startup probe and the previous revision keeps serving (2.37, 2.49).
    - New `backend/tests/test_change_feed_sqlstate.py`:
      - `_sqlstate` table: error shape {psycopg2 `orig.pgcode`, psycopg 3 `orig.sqlstate`, no `orig`, SQLite `OperationalError`} × code {"40P01", "55P03", "25001", "42P01", None} × message {"deadlock detected", "canceling statement due to lock timeout", "cannot run inside a transaction block", "boom"}; the classification depends on the code only;
      - an injected 25001 "transaction block" error is raised and logged at ERROR with `exc_info`, never as "peer completed"; an injected 40P01 logs "peer completed" when `_change_feed_installed` is patched to True and raises when it is False;
      - `run_migrations_and_seed` re-raises a change-feed error.
    - Re-run `test_change_feed_errors.py`: the "transaction block" case passes, and the 40P01 case raises no `NameError` (its retry assertion passes after 13.8).
    - _Bug_Condition: isBugCondition(X) for C2: a change-feed error is classified by message substring and logged through an undefined logger_
    - _Expected_Behavior: Property 1 and Property 8_
    - _Preservation: Property 2 (3.11, 3.12)_
    - _Requirements: 1.37, 2.37, 2.49_

  - [~] 13.8 Bound change-feed lock waits and retry lock conflicts
    - `install_change_feed` in `backend/database/change_feed.py`, per design C2.5 and C2.7:
      - on Postgres the change-feed transaction starts with `SET LOCAL lock_timeout = '5s'` (module constant `_FEED_LOCK_TIMEOUT`), so a lock that cannot be granted fails fast instead of queueing requests behind it;
      - a 40P01 or 55P03 retries the whole transaction up to three times, after 2, 4 and 8 s plus `random.uniform(0, 1)` s of jitter, sleeping through a module-level `_sleep` that tests replace; the 13.7 `_change_feed_installed` check runs only after the last attempt;
      - each retry logs at WARNING with the SQLSTATE and the next delay.
    - Extend `backend/tests/test_change_feed_sqlstate.py`:
      - a transaction that fails n times (n = 0 to 4) with 40P01 or 55P03 makes min(n, 3) + 1 attempts, with delays of 2, 4 and 8 s plus jitter in [0, 1), and then succeeds, logs "peer completed" or raises as 13.7 decides;
      - any other error is not retried;
      - Postgres (testcontainers, skipped without Docker): `SET LOCAL lock_timeout` is the first statement of the change-feed transaction; with one table's trigger dropped and another session holding `ACCESS EXCLUSIVE` on that table, `_FEED_LOCK_TIMEOUT` patched to `'200ms'` and `_sleep` patched to a no-op, the install makes four attempts and then raises 55P03.
    - Re-run `test_change_feed_errors.py` (now passes in full) and `test_change_feed_ddl_idempotent.py`.
    - _Bug_Condition: isBugCondition(X) for C2: a change-feed DDL statement waits behind a table lock with no bound, and a lock conflict is not retried_
    - _Expected_Behavior: Property 1 and Property 8_
    - _Preservation: Property 2 (3.11, 3.12): SQLite runs the change feed without `lock_timeout` or retries, as today_
    - _Requirements: 1.37, 2.37_

  - [~] 13.9 Load the embedding model lazily on Cloud Run
    - `backend/main_groq.py`, per design C2.8: the lifespan calls `preload_model_async()` only when `_should_preload_embeddings(environ=os.environ)` is true, that is when `K_SERVICE` is unset or empty (desktop). On Cloud Run the model loads on first use through the existing on-demand path.
    - New `backend/tests/test_embedding_preload.py`: `_should_preload_embeddings` over `K_SERVICE` in {unset, "", "staterbill-api"}; one `TestClient(app)` start-up with `K_SERVICE` set and `preload_model_async` patched with a counter makes no call; with `K_SERVICE` set and the model loader patched, the first embedding call still loads the model.
    - _Bug_Condition: isBugCondition(X) for C2: a Cloud Run boot loads the embedding model before it can serve_
    - _Expected_Behavior: Property 1 and Property 8_
    - _Preservation: Property 2 (3.11): the desktop app still preloads the model at start-up_
    - _Requirements: 1.36, 2.36, 3.11_

  - [~] 13.10 Verify the C2 exploration tests now pass
    - **Property 1: Expected Behavior** - Billing API boot and change feed
    - **IMPORTANT**: Re-run the SAME tests from task 1.3. Do NOT write new tests.
    - From `backend/`: `$env:GROQ_API_KEY='mock_groq_api_key'; python -m pytest tests/test_boot_fast_path.py tests/test_change_feed_errors.py -q -n auto --dist loadscope`. The Postgres cases must run, not skip; if Docker is unavailable, report the skipped cases to the user.
    - **EXPECTED OUTCOME**: Tests PASS (confirms the bug is fixed).
    - _Requirements: 2.36, 2.37_

  - [~] 13.11 Verify the preservation tests still pass
    - **Property 2: Preservation** - Local start-up and replication
    - **IMPORTANT**: Re-run the SAME tests from task 2. Do NOT write new tests.
    - From `backend/`: `$env:GROQ_API_KEY='mock_groq_api_key'; python -m pytest tests/ -q -n auto --dist loadscope -k "preservation_boot_seed or migration or schema or change_feed or sync_feed or embedding_preload"`. This covers `test_preservation_boot_seed.py` (3.11, 3.12), the files added in 13.2 to 13.9, and the existing migration, schema-contract and change-feed tests.
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions).
    - _Requirements: 3.11, 3.12_

- [ ] 14. Fix C7: sync worker and B2B proxy (P1)

  - [~] 14.1 Remove the C7 xfail markers
    - Delete the module-level `pytestmark = pytest.mark.xfail(strict=True, reason="bug condition C7, fixed in part 2")` from `backend/tests/test_sync_worker_cold_cloud.py` and `backend/tests/test_b2b_proxy_cold_cloud.py`. Change nothing else in either file.
    - Run both files. They must FAIL with the counterexamples task 1.3 recorded: the HTML 503 is retried before `Retry-After`, a probe time-out is not reported as `waking`, the token refresh starts late and waits 15 minutes, an upstream 503 on a B2B read passes through, and an upstream 401 on a write passes through. If a case passes, stop and report it: its counterexample no longer reproduces.
    - _Bug_Condition: isBugCondition(X) for C7, as recorded by the task 1.3 counterexamples_
    - _Expected_Behavior: Property 1 and Property 10_
    - _Preservation: Property 2 (3.13); this leaf changes tests only_
    - _Requirements: 1.35, 1.41_

  - [~] 14.2 Track the cloud state per business
    - `backend/services/sync_worker.py`, per design C7.1 and C7.2:
      - module-level `_CLOUD_STATE: dict[int, CloudState]`, where the `CloudState` dataclass holds `state` (`online`, `waking`, `busy` or `offline`), `retry_after`, `last_probe_at` and `last_success_at`; `get_cloud_state(business_id)` returns a copy or `None` before the first probe;
      - the health probe in `_sync_business_impl` uses a 45 s read timeout when the last successful contact is more than 10 minutes old or missing, otherwise 10 s;
      - a time-out sets `waking`, logs at INFO, writes no failed `SyncLog` row, and retries on the next tick;
      - a 429, 502, 503 or 504 (HTML or JSON body), or a 200 whose body is not the expected JSON, sets `busy` with `retry_after` 30 s ahead (14.3 reads the header);
      - connection and DNS errors set `offline`, with today's logging and `SyncLog` behaviour; a good probe sets `online`.
    - New `backend/tests/test_sync_cloud_state.py`, whose fixture clears `_CLOUD_STATE`: a table over probe outcome {time-out, 429, 502, 503 and 504 each with an HTML and a JSON body, 200 with an HTML body, 200 with the expected JSON, `ConnectError`, DNS failure} × last success {never, 5 min ago, 11 min ago} checks the state, the read timeout used, the log level and the `SyncLog` rows.
    - Re-run `test_sync_worker_cold_cloud.py`: the `waking` case passes.
    - _Bug_Condition: isBugCondition(X) for C7: a cold or busy cloud is recorded as a failed sync_
    - _Expected_Behavior: Property 1 and Property 10_
    - _Preservation: Property 2: a reachable cloud syncs as today, and connection errors still mean `offline`_
    - _Requirements: 1.35, 2.35_

  - [~] 14.3 Honour `Retry-After` with jitter
    - `backend/services/sync_worker.py`, per design C7.2:
      - `_parse_retry_after(value, now) -> float` accepts delta-seconds or an HTTP date (`email.utils.parsedate_to_datetime`), returns 0 for a date in the past, caps the result at 300 s, and returns 30 s when the header is absent or invalid;
      - `busy` stores `retry_after = now + delay × (1 + _rng.uniform(0, 0.2))`, where `_rng` is a module-level `random.Random()` that tests replace with `random.Random(<fixed seed>)`;
      - `_sync_business_impl` sends no cloud request for that business before `retry_after`.
    - New `backend/tests/test_sync_retry_after.py`: header values {absent, "", "0", "30", "120", "300", "301", "86400", "-5", "abc", HTTP date 60 s ahead, HTTP date 60 s ago} → expected base delay; over 200 draws from a seeded `random.Random`, the stored wait stays within [base, 1.2 × base]; a tick before `retry_after` makes no request.
    - Re-run `test_sync_worker_cold_cloud.py` and `test_sync_cloud_state.py`: the HTML 503 with `Retry-After: 120` case passes.
    - _Bug_Condition: isBugCondition(X) for C7: the worker calls a busy cloud again before its `Retry-After`_
    - _Expected_Behavior: Property 1 and Property 10_
    - _Preservation: Property 2: a reachable cloud syncs as today_
    - _Requirements: 1.35, 2.35_

  - [~] 14.4 Refresh the cloud token 12 h early and retry with backoff
    - `ensure_fresh_cloud_token` in `backend/services/sync_worker.py`, per design C7.3: `_REFRESH_WHEN_UNDER = timedelta(hours=12)`; request timeout 45 s; after a failure the next attempt waits 1, 2, 4 and 8 minutes, then 15 minutes each time (`_REFRESH_RETRY_DELAYS`), instead of a flat 15 minutes; a 429 or 503 waits for `_parse_retry_after` from 14.3. A 401 still drops the token (unchanged).
    - New `backend/tests/test_cloud_token_refresh.py`:
      - remaining token lifetime {13 h, 12 h + 1 s, 12 h − 1 s, 1 h, expired} → refresh attempted or not;
      - consecutive failures 1 to 7 → next attempt after 60, 120, 240, 480, 900, 900 and 900 s;
      - a 429 or 503 with `Retry-After: 200` → next attempt after 200 s; the request uses the 45 s timeout;
      - a 401 drops the token, as today.
    - Re-run `test_sync_worker_cold_cloud.py`: the token refresh case passes.
    - _Bug_Condition: isBugCondition(X) for C7: the token refresh starts too late and retries only every 15 minutes_
    - _Expected_Behavior: Property 1 and Property 10_
    - _Preservation: Property 2: a 401 still drops the token_
    - _Requirements: 1.35, 2.35_

  - [~] 14.5 Fit pushes inside the request limit and key each chunk
    - First check that the cloud-side apply is UID-idempotent. New `backend/tests/test_sync_push_replay.py`: POST the same chunk to `/api/sync/push` three times (twice with the same `X-Client-Request-Id`, once with a different one), with one row of each entity type the route accepts; the second and third posts leave row counts and values unchanged. If the test fails on today's code, add `core/sync/idempotency.replay_guard` to the push route, keyed by business id and `X-Client-Request-Id`, and re-run. If it passes, change no server code; the test pins the guarantee either way (design C7.4).
    - `backend/services/sync_worker.py`: `_PUSH_TIMEOUT` read becomes 100 s, inside the 120 s request limit. New `_chunk_request_id(business_id, outbox_ids, payload) -> str`: SHA-256 hex of the business id, the sorted outbox ids and the SHA-256 of `json.dumps(payload, sort_keys=True, separators=(",", ":"))`. Every push request sends it as `X-Client-Request-Id`, so a retried chunk carries the same key.
    - New `backend/tests/test_sync_push_chunk_id.py`: over 50 chunks from `random.Random(<fixed seed>)`, the id is stable for the same chunk, ignores outbox id order, and changes when the business id, an outbox id or the payload changes; a mocked transport sees the header on every push and a 100 s read timeout.
    - _Bug_Condition: isBugCondition(X) for C7: a push read timeout does not fit a cold start inside the 120 s request limit, and a retried chunk carries no stable key_
    - _Expected_Behavior: Property 1 and Property 10_
    - _Preservation: Property 2: pushes to a warm cloud apply rows as today_
    - _Requirements: 1.35, 2.35_

  - [~] 14.6 Run the parity sweep over protocol-2 pages
    - `_cloud_parity_check` in `backend/services/sync_worker.py`, per design C7.5: the single legacy pull (`last_sync_at=1970-01-01`, 180 s read) becomes the protocol-2 pull the worker already uses, paged from cursor 0 with `_PULL_TIMEOUT` (60 s) per page, within an overall budget `_PARITY_BUDGET_S = 600` measured with `time.monotonic` (patchable). When the budget runs out, the summary says `incomplete`. The sweep stays detection-only.
    - New `backend/tests/test_sync_parity_sweep.py` with a mocked transport: pages are followed from cursor 0 until the last page; each request uses a 60 s read timeout and the previous page's cursor; no request carries `last_sync_at=1970-01-01`; a clock that passes 600 s mid-sweep gives `incomplete`; local row counts are unchanged afterwards.
    - _Bug_Condition: isBugCondition(X) for C7: the parity check makes one legacy pull that needs up to 180 s, beyond the 120 s request limit_
    - _Expected_Behavior: Property 1 and Property 10_
    - _Preservation: Property 2: the sweep still only detects and reports differences_
    - _Requirements: 1.35, 2.35_

  - [~] 14.7 Make the B2B proxy degrade on a cold cloud
    - `b2b_cloud_proxy` in `backend/routes/b2b_proxy.py`, per design C7.6:
      - reads (`_READ_METHODS`) serve the local mirror on network errors, time-outs, any 5xx and 429, and keep the 12 s `_TIMEOUT`;
      - writes use `_WRITE_TIMEOUT = httpx.Timeout(connect=10, read=70, write=30, pool=10)` and keep the "B2B is offline" 503 for network errors (3.13); 429 and 5xx pass through with their `Retry-After`;
      - an upstream 401 still drops the stale token and serves reads from the mirror; on a write it returns 424 `{"detail": "Sign in to BizAssist cloud again to change B2B data.", "code": "cloud_sign_in_required"}`.
    - New `backend/tests/test_b2b_proxy_cloud_outcomes.py`: method {GET, POST, PUT, PATCH, DELETE} × upstream outcome {time-out, 429 with `Retry-After`, 500, 502, 503, 504, 401} → mirror, pass-through with `Retry-After`, 424 or the "B2B is offline" 503; reads are sent with `_TIMEOUT` and writes with `_WRITE_TIMEOUT`.
    - Re-run `test_b2b_proxy_cold_cloud.py` (now passes in full), `test_preservation_b2b_warm.py` and `test_b2b_proxy_test_isolation.py`.
    - _Bug_Condition: isBugCondition(X) for C7: a B2B read during a cold start or overload, or a B2B write after the cloud token expired, passes the upstream failure through_
    - _Expected_Behavior: Property 1 and Property 10_
    - _Preservation: Property 2 (3.13)_
    - _Requirements: 1.41, 2.41, 3.13_

  - [~] 14.8 Give the renderer's B2B writes a 75 s timeout
    - `frontend-billing/src/b2b/`: export `B2B_WRITE_TIMEOUT_MS = 75000` from the module that issues the B2B API calls, and pass it to every POST, PUT, PATCH and DELETE call there (the HTTP client's timeout option, or `AbortSignal.timeout(B2B_WRITE_TIMEOUT_MS)` for plain `fetch`). Reads keep their current timeout. 75 s is longer than the proxy's 70 s write read timeout from 14.7, so the proxy answers first.
    - New Vitest file `b2bWriteTimeout.test.js` next to the existing B2B tests: `it.each` over the write calls asserts the 75 s timeout, and over the read calls asserts the unchanged one.
    - Syntax-check the touched JS/JSX files with the helper from the notes. The user runs `npx vitest run --pool=threads --reporter=dot` in `frontend-billing` at checkpoint 15.
    - _Bug_Condition: isBugCondition(X) for C7: the renderer gives up on a B2B write before a cloud cold start ends_
    - _Expected_Behavior: Property 1 and Property 10_
    - _Preservation: Property 2 (3.13): B2B reads and their timeouts are unchanged_
    - _Requirements: 1.41, 2.41, 3.13_

  - [~] 14.9 Fill the cloud-state fields of `GET /api/sync/status`
    - The status route in `backend/routes/sync.py` (task 3.3) fills `cloud_state`, `last_probe_at` and `retry_after` from `sync_worker.get_cloud_state(business_id)`, in the formats task 3.3 uses. They stay `null` only before the first probe.
    - Extend `backend/tests/test_sync_status_route.py`: a table over {no probe yet, `online`, `waking`, `busy` with `retry_after`, `offline`} checks the three fields; the body still holds no token or secret; staff and anonymous callers are still refused.
    - _Bug_Condition: isBugCondition(X) for C7: `GET /api/sync/status` cannot show whether the cloud is waking, busy or offline_
    - _Expected_Behavior: Property 1 and Property 10_
    - _Preservation: Property 2 (3.21)_
    - _Requirements: 2.34, 2.35, 3.21_

  - [~] 14.10 Show the cloud state in the Billing sync popover
    - `frontend-billing/src/layouts/AppLayout.jsx`, in the sync popover and the halt-reason display:
      - `cloud_state` `waking` shows "The cloud is starting…";
      - `busy` shows "Cloud busy — retrying at <time>", where `<time>` is `retry_after` as a local time (hours and minutes);
      - neither state is shown as offline, in the text or in the sync indicator; `online`, `offline` and `null` (no probe yet) display as today.
    - The layout reads `cloud_state` and `retry_after` from `GET /api/sync/status` (filled in by 14.9) through the existing API client, for owner sessions only, because the route refuses staff. When the request is refused or fails, the popover shows what it shows today.
    - Vitest: an `it.each` table over `cloud_state` {`online`, `waking`, `busy` with `retry_after`, `offline`, `null`} plus a staff session, in the existing `AppLayout` test file or a new `AppLayout.cloudState.test.jsx` next to `AppLayout.jsx`. It checks the popover and halt-reason text, that `waking` and `busy` never show the offline label, and that a staff session sends no `/api/sync/status` request.
    - Syntax-check the touched JS/JSX files with the helper from the notes. The user runs `npx vitest run --pool=threads --reporter=dot` in `frontend-billing` at checkpoint 15.
    - _Bug_Condition: isBugCondition(X) for C7: the sync popover shows a waking or busy cloud as offline_
    - _Expected_Behavior: Property 1 and Property 10_
    - _Preservation: Property 2 (3.13): a cloud that cannot be reached is still shown as offline, and `online` displays as today_
    - _Requirements: 2.41, 3.13_

  - [~] 14.11 Verify the C7 exploration tests now pass
    - **Property 1: Expected Behavior** - Cold-cloud sync worker and B2B proxy
    - **IMPORTANT**: Re-run the SAME tests from task 1.3. Do NOT write new tests.
    - From `backend/`: `$env:GROQ_API_KEY='mock_groq_api_key'; python -m pytest tests/test_sync_worker_cold_cloud.py tests/test_b2b_proxy_cold_cloud.py -q -n auto --dist loadscope`.
    - **EXPECTED OUTCOME**: Tests PASS (confirms the bug is fixed).
    - _Requirements: 2.35, 2.41_

  - [~] 14.12 Verify the preservation tests still pass
    - **Property 2: Preservation** - Warm-cloud sync and B2B
    - **IMPORTANT**: Re-run the SAME tests from task 2. Do NOT write new tests.
    - From `backend/`: `$env:GROQ_API_KEY='mock_groq_api_key'; python -m pytest tests/ -q -n auto --dist loadscope -k "preservation_b2b_warm or b2b_proxy or sync_worker or sync_status or sync_push or sync_cloud_state or sync_retry_after or sync_parity or cloud_token"`. This covers `test_preservation_b2b_warm.py` (3.13), `test_b2b_proxy_test_isolation.py`, the files added in 14.2 to 14.9, and the existing sync worker and B2B proxy tests.
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions).
    - _Requirements: 3.13, 3.21_

- [~] 15. Checkpoint - P1 fixes: ensure all tests pass
  - Start both backend suites at the same time (for example as two background processes) and wait for both:
    - from `backend/`: `$env:GROQ_API_KEY='mock_groq_api_key'; python -m pytest tests/ -q -n auto --dist loadscope`
    - from `backend-task/`: `python -m pytest tests/ -q -n auto --dist loadscope`
  - Expected:
    - No failures except `tests/test_intent_router.py::test_semantic_router_eval_accuracy`.
    - The four task 1.3 files pass and carry no xfail marker. The task 1.4 files still report xfailed until their part 2 fix tasks, and the `test_no_retired_host_defaults.py` cases noted at task 12 still xfail until C13.
    - The Postgres (testcontainers) cases added in task 13 ran instead of skipping. If Docker was unavailable, list the skipped cases for the user.
    - Billing passes at least the count recorded at task 12 plus the tests added in tasks 13 and 14; backend-task passes fully.
  - Syntax-check every JS/JSX file added or changed in tasks 13 and 14 with the helper.
  - Ask the user to run this locally (after `npm install` if `node_modules` is missing) and report the results; tasks 13 and 14 change no other frontend:
    - `frontend-billing`: `npx vitest run --pool=threads --reporter=dot`
  - Do not run `run_tests.ps1`. Ask the user if questions arise; the P2 tasks start after the user confirms the local results.

- [ ] 16. Fix C8: scheduled jobs and LAN discovery (P2)

  - [~] 16.1 Remove the C8 xfail markers
    - Delete the module-level `pytestmark = pytest.mark.xfail(strict=True, reason="bug condition C8, fixed in part 2")` from `backend/tests/test_internal_cron.py` and `backend/tests/test_discovery_persistence.py`. Change nothing else in either file.
    - Run both files. They must FAIL with the counterexamples task 1.4 recorded: with `K_SERVICE` set, `start_scheduler()` registers cron jobs; `POST /internal/cron/{job}` does not exist; a registration made with `DISCOVERY_PERSIST=1` is not found once `_REGISTRY` is cleared. If a case passes, stop and report it: its counterexample no longer reproduces.
    - _Bug_Condition: isBugCondition(X) for C8, as recorded by the task 1.4 counterexamples_
    - _Expected_Behavior: Property 1 and Property 11_
    - _Preservation: Property 2 (3.11); this leaf changes tests only_
    - _Requirements: 1.40, 1.42_

  - [~] 16.2 Add the `scheduled_job_runs` and `discovery_registrations` tables (before the code that uses them)
    - `backend/database/models.py`, per design C8.3 and C8.5:
      - `ScheduledJobRun` (`scheduled_job_runs`): `job` and `period` as the composite primary key; `status` (`running`, `partial` or `done`), `cursor` (nullable integer: the last business id processed), `lease_until`, `started_at`, `finished_at` and `error` (nullable text);
      - `DiscoveryRegistration` (`discovery_registrations`): `biz_id`, `ip` and `port` as the composite primary key; `url`, `registered_at` and `last_seen`;
      - neither goes into `MODEL_MAP`, so neither gets a capture trigger or reaches the sync protocol.
    - New Alembic revision in `backend/alembic/versions/` with `down_revision` set to the current head (`python -m alembic heads` from `backend/`): creates both tables; `downgrade()` drops them.
    - RLS and runtime-role grants for both tables, as in task 13.2 (the grants live in `backend/database/security.py`). Update any schema-contract list that names the required tables.
    - Rollback note, written into the revision docstring: the tables are additive and older revisions ignore them, so moving traffic back to the previous Cloud Run revision needs no downgrade; `alembic downgrade -1` removes them if they must go.
    - Test `backend/tests/test_cron_discovery_tables.py`: both tables exist after `create_all` with the keys above, are absent from `MODEL_MAP`, and get the RLS and grants of 13.2. Run it and the existing Alembic and schema tests (`-k "alembic or schema or migration"`).
    - _Bug_Condition: isBugCondition(X) for C8: on Cloud Run nothing records which scheduled runs happened, and LAN registrations exist only in process memory_
    - _Expected_Behavior: Property 11 (durable run record and registrations)_
    - _Preservation: Property 2 (3.11)_
    - _Requirements: 1.40, 1.42, 2.40, 2.42, 3.11_

  - [~] 16.3 Add `POST /internal/cron/{job}` and the job runner
    - New `backend/services/cron_runner.py`, per design C8.2 and C8.3:
      - `JOBS` maps the eight job ids (`daily_summary`, `overdue_alerts`, `low_stock_alerts`, `expiry_alerts`, `books_integrity_audit`, `telemetry_retention`, `memory_distillation`, `telemetry_db_maintenance`) to their job function and period kind. The kind follows the job's current trigger in `services/scheduler.py`: a daily job's period is the IST date (`YYYY-MM-DD`), a weekly job's the ISO week (`YYYY-Www`). `period_for(job, now)` computes it.
      - `run(job, period, budget_s=95)` claims the `(job, period)` row with insert-if-absent (`ON CONFLICT DO NOTHING`), or takes over a `partial` row or an expired lease with a conditional UPDATE that must change exactly one row. The lease lasts `budget_s + 30` s. A `done` row gives `already_ran` and a live lease gives `busy`, both without calling the job.
      - The runner calls the job with `after_business_id=<cursor>` and `deadline=<time.monotonic() + budget_s>`. The job returns `None` when it finished, which marks the row `done`, or the last business id it processed, which marks the row `partial` with that cursor. An exception stores `error`, leaves the row `partial` at its last cursor, and is re-raised.
    - New `backend/routes/internal_cron.py`, following backend-task's `purge_pings_now`: `POST /internal/cron/{job}` with `include_in_schema=False` and no user session.
      - Checks, in this order: `BILLING_CRON_SECRET` (read per request) unset or empty → 404; `X-Cron-Secret` missing or different (`hmac.compare_digest` on bytes) → 403; job not in `JOBS` → 404. Neither the secret nor the header value is ever logged.
      - The route computes `period_for(job, now)` and calls `run`. Responses: `done` → 200 `{"status": "done", "job", "period"}`; `already_ran` → 200 with the same keys; `busy` → 409; `partial` → 503 with `Retry-After: 30`, so Cloud Scheduler retries and the run resumes from the cursor; a job exception → 500 with a generic `detail`. No body holds account fields.
      - Register the router in `backend/main_groq.py` and check that no app-wide middleware asks this path for a user session. The deploy `--setup` step that creates the Cloud Scheduler jobs and mounts the secret (design C8.4) belongs to the C13 task.
    - New `backend/tests/test_cron_runner.py`, whose fixture empties `scheduled_job_runs` and replaces `JOBS` with fake jobs over 5 fake businesses:
      - secret {unset, "", set} × header {absent, wrong, right} × job {known, unknown} → 404 when the secret is unset or empty, else 403 for a missing or wrong header, else 404 for an unknown job, else 200;
      - a second delivery returns `already_ran` without calling the job; a live lease returns 409; an expired lease is taken over;
      - a fake clock that ends the budget after business 2 gives 503 with `Retry-After: 30` and a `partial` row at cursor 2; the retry resumes after business 2 and ends `done`, and no business runs twice;
      - `period_for` on both sides of IST midnight (18:29 and 18:31 UTC) and across the ISO year boundary (2026-12-31 → `2026-W53`, 2027-01-04 → `2027-W01`);
      - the route is absent from `app.openapi()`, and `caplog` never contains the secret;
      - a Postgres (testcontainers) case makes two claims at once and exactly one wins; it skips without Docker.
    - `backend/tests/test_preservation_billing_api.py`: add `POST /internal/cron/{job}` to the pinned list of unauthenticated routes in the 3.2 test, with the note that it returns no account fields (only `status`, `job` and `period`, and only with `X-Cron-Secret`). Change nothing else in the file. Pinning the route in the leaf that adds it keeps the 3.2 case green throughout.
    - Re-run `test_internal_cron.py`: the 404 and 403 cases pass; the scheduler case waits for 16.4, and a case that runs a real job may wait for 16.5. Run `test_preservation_billing_api.py`: the 3.2 case passes with the new route pinned, and the other cases still pass.
    - _Bug_Condition: isBugCondition(X) for C8: on Cloud Run a scheduled job runs only while an instance happens to be up, and a run cut short at the request limit is lost_
    - _Expected_Behavior: Property 1 and Property 11_
    - _Preservation: Property 2 (3.2, 3.11): every unauthenticated route stays pinned and returns no account fields, and the desktop scheduler does not use the runner_
    - _Requirements: 1.40, 2.40, 3.2, 3.11_

  - [~] 16.4 Leave the scheduled jobs to Cloud Scheduler on Cloud Run
    - `start_scheduler()` in `backend/services/scheduler.py`, per design C8.1: when `K_SERVICE` is set and not empty, register no APScheduler job, cron or interval, and log once at INFO that Cloud Scheduler owns the jobs through `POST /internal/cron/{job}`. The desktop-only jobs (`daily_log_upload`, `telemetry_relay`, `hybrid_sync`, `cloud_parity_sweep`) stay off there too. Without `K_SERVICE` (the desktop on SQLite), every job registers as today, with today's trigger (3.11).
    - New `backend/tests/test_scheduler_cloud_run.py`: first record today's job ids and triggers on the unfixed code; then a table over `K_SERVICE` {unset, "", "staterbill-api"} expects that recorded set for the first two values, and no job plus the single INFO line for the third.
    - Rollback note for the C13 runbook: a revision from before this change runs the jobs in process and answers Cloud Scheduler with 404, so pause the Scheduler jobs while traffic is on such a revision.
    - Re-run `test_internal_cron.py` (the scheduler case passes), the existing scheduler tests (`-k scheduler`) and the 3.11 preservation case (`-k c3_11`).
    - _Bug_Condition: isBugCondition(X) for C8: with `K_SERVICE` set, `start_scheduler()` registers in-process jobs that run only while an instance is up, once per running instance_
    - _Expected_Behavior: Property 1 and Property 11_
    - _Preservation: Property 2 (3.11): the desktop keeps every job, including the interval jobs_
    - _Requirements: 1.40, 2.40, 3.11_

  - [~] 16.5 Run the existing jobs through the runner
    - Per design C8.3, the functions that `start_scheduler()` registers today for the eight job ids of 16.3 (in `backend/services/scheduler.py` and the alert, summary, audit, telemetry, memory and maintenance modules it imports) gain optional `after_business_id: int | None = None` and `deadline: float | None = None`:
      - a job that loops over businesses takes them in ascending id order after the cursor and checks `time.monotonic()` against the deadline after each one, so every call makes progress; it returns `None` when no business is left, otherwise the last id it processed;
      - a job that does not loop over businesses ignores both and returns `None`;
      - called without arguments, as APScheduler does on the desktop, every job processes everything as today.
    - Point `cron_runner.JOBS` at these functions. Keep or move their `tenant_scope.ALLOWED` entries with the same justification.
    - New `backend/tests/test_cron_job_cursor.py`, with each job's outbound effect (notification, message, audit or telemetry write) patched to a recorder:
      - first, on the unfixed code, record what each job does when called without arguments over 5 seeded businesses; the changed jobs must reproduce it;
      - for each looping job, a deadline that passes during business k ∈ {1, 3, 5} returns that business's id (`None` for 5), and resuming from it processes the rest with no business twice;
      - end to end, with a fake clock that ends the first call's budget after 2 businesses: `POST /internal/cron/daily_summary` with the right secret returns 503, the retry 200 `done`, and a third call `already_ran`.
    - Re-run `test_internal_cron.py` (now passes in full), `test_cron_runner.py`, `test_tenant_scope.py`, the existing job tests (`-k "alert or summary or audit or telemetry or distill or scheduler"`) and `-k c3_11`.
    - _Bug_Condition: isBugCondition(X) for C8: a job run that the request limit cuts short is lost, or repeats from the first business_
    - _Expected_Behavior: Property 1 and Property 11_
    - _Preservation: Property 2 (3.11): called without arguments, every job does what it does today_
    - _Requirements: 1.40, 2.40, 3.11_

  - [~] 16.6 Persist LAN discovery registrations
    - `backend/routes/discovery.py`, per design C8.5: `_persist_enabled()` is true on Postgres or with `DISCOVERY_PERSIST=1`. While it is, register upserts the `(biz_id, ip, port)` row with its `url` and `last_seen`, and unregister deletes it. A lookup that finds no live entry in `_REGISTRY` reloads that BizID's rows with `last_seen` within `TTL_SECONDS` into `_REGISTRY` and answers from them; it deletes the expired rows it meets. `_REGISTRY` keeps its shape and stays the in-process cache, so the tests that clear or seed it keep their meaning. Without persistence (SQLite without the flag), discovery behaves as today.
    - New `backend/tests/test_discovery_store.py`, whose fixture clears `_REGISTRY` and `discovery_registrations`: persistence {off, on} × entry {fresh, older than `TTL_SECONDS`, unregistered} × `_REGISTRY` {kept, cleared} → found or not; an entry seeded straight into `_REGISTRY` is still found with persistence off; two BizIDs never see each other's entries.
    - Re-run `test_discovery_persistence.py` (now passes) and the existing discovery tests (`-k discovery`).
    - _Bug_Condition: isBugCondition(X) for C8: a LAN registration held by one Cloud Run instance is lost when it restarts and unknown to any other instance_
    - _Expected_Behavior: Property 1 and Property 11_
    - _Preservation: Property 2: discovery on SQLite without `DISCOVERY_PERSIST` behaves as today, and the tests that seed `_REGISTRY` keep their meaning_
    - _Requirements: 1.42, 2.42_

  - [~] 16.7 Verify the C8 exploration tests now pass
    - **Property 1: Expected Behavior** - Scheduled jobs and LAN discovery
    - **IMPORTANT**: Re-run the SAME tests from task 1.4. Do NOT write new tests.
    - From `backend/`: `$env:GROQ_API_KEY='mock_groq_api_key'; python -m pytest tests/test_internal_cron.py tests/test_discovery_persistence.py -q -n auto --dist loadscope`.
    - **EXPECTED OUTCOME**: Tests PASS (confirms the bug is fixed).
    - _Requirements: 2.40, 2.42_

  - [~] 16.8 Verify the preservation tests still pass
    - **Property 2: Preservation** - Desktop scheduler, unauthenticated routes and discovery
    - **IMPORTANT**: Re-run the SAME tests from task 2. Do NOT write new tests.
    - From `backend/`: `$env:GROQ_API_KEY='mock_groq_api_key'; python -m pytest tests/ -q -n auto --dist loadscope -k "c3_02 or c3_11 or scheduler or cron or discovery or tenant_scope or alert or summary or audit or telemetry or distill"`. This covers the 3.2 and 3.11 preservation cases, the files added in 16.2 to 16.6, and the existing scheduler, job and discovery tests.
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions).
    - _Requirements: 3.2, 3.11_

- [ ] 17. Fix C12, the rest: admin data access and durable admin state (P2)

  - [~] 17.1 Remove the C12 xfail markers
    - Delete the module-level `pytestmark = pytest.mark.xfail(strict=True, reason="bug condition C12, fixed in part 2")` from `backend/tests/test_router_mode_persisted.py`, `backend/tests/test_feedback_archive_durable.py` and `backend/tests/test_admin_query_counts.py`. Change nothing else in these files.
    - Run the three files. They must FAIL with the counterexamples task 1.4 recorded: `get_mode()` loses the set mode once the in-process value is cleared; the feedback log archive is gone once its file on disk is deleted; the statement counts of `list_businesses`, `sync_doctor` and the usage stats grow with the number of businesses. If a case passes, stop and report it: its counterexample no longer reproduces.
    - _Bug_Condition: isBugCondition(X) for C12, as recorded by the task 1.4 counterexamples_
    - _Expected_Behavior: Property 1 and Property 12_
    - _Preservation: Property 2 (3.3, 3.17); this leaf changes tests only_
    - _Requirements: 1.47, 1.48_

  - [~] 17.2 Add the `platform_settings` and `client_log_archives` tables (before the code that uses them)
    - `backend/database/models.py`, per design C12.4:
      - `PlatformSetting` (`platform_settings`): `key` primary key, `value`, `updated_at` and `updated_by`;
      - `ClientLogArchive` (`client_log_archives`): `id` primary key, `business_id`, nullable `feedback_id`, `kind` (`feedback` or `daily`), `filename`, `content` (`LargeBinary`), `size` and `created_at`, with an index on (`business_id`, `created_at`) for the caps and the downloads;
      - neither goes into `MODEL_MAP`.
    - New Alembic revision in `backend/alembic/versions/` with `down_revision` set to the current head (16.2's revision, per `python -m alembic heads`): creates both tables and the index; `downgrade()` drops them.
    - RLS and runtime-role grants for both tables, as in task 13.2 (the grants live in `backend/database/security.py`). Update any schema-contract list that names the required tables.
    - Rollback note, written into the revision docstring: the tables are additive and older revisions ignore them, so moving traffic back needs no downgrade. An older revision ignores the stored router mode and cannot serve archives uploaded while the new one ran; both come back when traffic does. `alembic downgrade -1` drops the tables together with those archives and the stored router mode.
    - Test `backend/tests/test_admin_state_tables.py`: both tables exist after `create_all` with the columns above, are absent from `MODEL_MAP`, and get the RLS and grants of 13.2. Run it and the existing Alembic and schema tests (`-k "alembic or schema or migration"`).
    - _Bug_Condition: isBugCondition(X) for C12: the router mode and the log archives live in process memory or on one instance's disk_
    - _Expected_Behavior: Property 12 (durable admin state)_
    - _Preservation: Property 2 (3.3)_
    - _Requirements: 1.48, 2.48, 3.3_

  - [~] 17.3 Group the fleet queries
    - `backend/services/admin_service.py`, per design C12.3: `list_businesses`, `sync_doctor` and `all_usage_stats` (behind the `get_all_usage_stats` route) compute each metric with one grouped query over all businesses (`GROUP BY business_id`) and join the results in Python by business id, so the number of statements no longer depends on the number of businesses. A business with no rows gets the value it gets today; the keys, order and values of the responses do not change.
    - Functions that change or move update their `tenant_scope.ALLOWED` entries with the same justification, because the guard rejects stale entries (3.3).
    - New `backend/tests/test_admin_fleet_results.py`, written and run on the unfixed code first: fleets of 1, 4 and 9 businesses with rows drawn from `random.Random(<fixed seed>)`; the three functions must match an oracle computed in Python from the seeded rows, before and after the change.
    - Re-run `test_admin_query_counts.py` (now passes), `test_tenant_scope.py` and the existing admin tests (`-k admin`).
    - _Bug_Condition: isBugCondition(X) for C12: the fleet views run queries for each business, so their cost grows with the fleet_
    - _Expected_Behavior: Property 1 and Property 12_
    - _Preservation: Property 2 (3.3, 3.17): the same results, a passing tenant-scope guard, and admin-only routes_
    - _Requirements: 1.47, 2.47, 3.3, 3.17_

  - [~] 17.4 Add single-business admin routes and page the business details
    - `backend/routes/admin.py` and `backend/services/admin_service.py`, per design C12.3:
      - new `GET /admin/businesses/{id}` returns the row that `list_businesses` returns for that business, or 404; declare it after any static `/admin/businesses/...` route so none is shadowed;
      - the sync doctor accepts `?business_id=` and then reports that business only;
      - `business_details` takes `section`, `limit` (default 50, from 1 to 200) and `offset` (0 or more) and returns `has_more`; values outside those ranges return 422;
      - each route runs `svc.require_admin` like the other admin routes (3.17), and gets or updates its `tenant_scope.ALLOWED` entry with a justification (3.3).
    - New `backend/tests/test_admin_single_business.py`:
      - for every business of a seeded fleet, `GET /admin/businesses/{id}` equals its `list_businesses` row, and the sync doctor with `?business_id=` equals its entry in the full report; an unknown id gives 404;
      - `limit` {omitted, 1, 50, 200, 201, 0} × `offset` {0, 49, past the end, -1} → the rows and `has_more`, or 422;
      - non-admin callers (owner, staff, anonymous) are refused as on the other admin routes;
      - the statement counts of the three single-business calls are equal for 2 and 6 businesses.
    - Re-run `test_admin_query_counts.py`, `test_tenant_scope.py` and `-k admin`.
    - _Bug_Condition: isBugCondition(X) for C12: the business detail page has to load the whole fleet to show one business_
    - _Expected_Behavior: Property 12_
    - _Preservation: Property 2 (3.3, 3.17)_
    - _Requirements: 1.47, 2.47, 3.3, 3.17_

  - [~] 17.5 Load one business on the admin detail page
    - `frontend-admin/src/pages/admin/AdminBusinessDetail.jsx`: load the business from `GET /admin/businesses/{id}`, its sync doctor entry with `?business_id={id}`, and each `business_details` section with `section`, `limit=50` and `offset`, with a "Load more" button while `has_more` is true. The page no longer requests the fleet list or the full sync doctor, and it shows the same fields as today.
    - Vitest, with the API mocked, in the page's existing test file or a new `AdminBusinessDetail.test.jsx` next to it: `it.each` over the sections checks that only single-business URLs are requested, that the first request sends `limit=50&offset=0`, and that "Load more" requests `offset=50` and appends the rows.
    - Syntax-check the touched JS/JSX files with the helper from the notes. The user runs `npx vitest run --pool=threads --reporter=dot` in `frontend-admin` locally (after `npm install` if `node_modules` is missing) and reports the result.
    - _Bug_Condition: isBugCondition(X) for C12: the business detail page loads the whole fleet to show one business_
    - _Expected_Behavior: Property 12_
    - _Preservation: Property 2: the page shows the same fields for a business as today_
    - _Requirements: 1.47, 2.47_

  - [~] 17.6 Store the router mode in `platform_settings`
    - `backend/services/router_mode.py`, per design C12.4:
      - `set_mode()` writes the `platform_settings` row (`value`, `updated_at`, `updated_by`) and updates the local cache at once;
      - `get_mode()` reads the row through a 30 s cache (`_CACHE_TTL_S`, timed with `time.monotonic` so tests can patch it) and falls back to the `LLM_ROUTER` variable when no row exists;
      - `reset_mode()` deletes the row and clears the cache;
      - when the table cannot be read, the in-process value applies, as today, and one WARNING is logged.
    - The admin route in `backend/routes/admin.py` that calls `set_mode()` passes the admin's id as `updated_by`. Add a `tenant_scope.ALLOWED` entry if the guard flags the new reads.
    - New `backend/tests/test_router_mode_store.py`, whose fixture clears the cache and the table: stored row {none, set, reset} × cache {fresh, older than 30 s} × table {readable, unreadable} → the mode `get_mode()` returns; after `set_mode()` the same process sees the new mode at once, and a cleared cache, standing in for a second instance, reads it from the table; with no row, `LLM_ROUTER` applies.
    - Re-run `test_router_mode_persisted.py` (now passes), `test_tenant_scope.py` and the existing router-mode tests (`-k router_mode`).
    - _Bug_Condition: isBugCondition(X) for C12: the router mode an admin sets lives only in the process that handled the request_
    - _Expected_Behavior: Property 1 and Property 12_
    - _Preservation: Property 2 (3.3, 3.17): `LLM_ROUTER` still applies when no mode is set, and only admins change the mode_
    - _Requirements: 1.48, 2.48, 3.3, 3.17_

  - [~] 17.7 Keep client log archives in `client_log_archives`
    - Uploads, per design C12.4: `submit_merchant_feedback` in `backend/routes/feedback.py` and the daily log upload route (the endpoint the `log_uploader` module posts to) store the archive in `client_log_archives` instead of on instance disk, with `kind` `feedback` and its `feedback_id`, or `daily`. The existing upload bound still applies. After each insert, keep the newest 5 archives per business and 200 MB in total, deleting the oldest first (`_ARCHIVES_PER_BUSINESS = 5` and `_ARCHIVE_TOTAL_BYTES = 200 * 1024 * 1024`, which tests may lower).
    - Downloads in `backend/routes/admin.py`: `GET /admin/feedback/logs/{id}` and `GET /admin/business-logs/{id}` stream the row with today's filename and content type. For archives uploaded before this release they fall back to the file on instance disk; with neither, they return 404. Add `tenant_scope.ALLOWED` entries for these cross-tenant admin reads, with their justification (3.3).
    - New `backend/tests/test_client_log_archives.py`:
      - an upload followed by a download returns the same bytes, and an archive over the bound is refused with today's status;
      - after 7 uploads for one business only the newest 5 remain; with the total cap lowered, the oldest archives across businesses go first;
      - a pre-release file with no row still downloads, and with neither the route returns 404;
      - non-admin callers are refused.
    - Re-run `test_feedback_archive_durable.py` (now passes), `test_tenant_scope.py` and the existing feedback and log tests (`-k "feedback or business_logs or log_upload"`).
    - _Bug_Condition: isBugCondition(X) for C12: feedback and daily log archives live on one instance's disk and vanish with it_
    - _Expected_Behavior: Property 1 and Property 12_
    - _Preservation: Property 2 (3.3, 3.17): the upload bound, the download responses and admin-only access stay as they are_
    - _Requirements: 1.48, 2.48, 3.3, 3.17_

  - [~] 17.8 Point the server log to Cloud Logging and name the instance
    - `server_log_tail` behind the `server-log` admin view (`backend/routes/admin.py`, `backend/services/admin_service.py`), per design C12.4: when `K_SERVICE` is set, the response keeps its keys and adds `note` ("Server logs for this service are in Cloud Logging.") and `cloud_logging_filter` (`resource.type="cloud_run_revision" AND resource.labels.service_name="<K_SERVICE>"`), instead of a bare empty list. Without `K_SERVICE` (the desktop) the tail is unchanged.
    - The `cache-stats`, `flush-all-cache` and `server-log` views also return `instance: {service, revision, started_at, boot_id}` (`K_SERVICE`, `K_REVISION`, the process start time, and a UUID made at import), so the console can tell which instance answered.
    - New `backend/tests/test_admin_instance_views.py`: `K_SERVICE` {unset, "staterbill-api"} → today's tail, or the note with a filter that names the service; the three views carry the four `instance` fields; non-admin callers are refused.
    - Re-run `-k admin`.
    - _Bug_Condition: isBugCondition(X) for C12: on Cloud Run `server-log` returns an empty list with no explanation, and the per-instance views do not say which instance answered_
    - _Expected_Behavior: Property 12_
    - _Preservation: Property 2 (3.17): the desktop log tail is unchanged, and the views stay admin-only_
    - _Requirements: 1.48, 2.48, 3.17_

  - [~] 17.9 Write the admin audit to `action_logs`
    - Per design C12.4: the admin audit writer in `backend/routes/admin.py` (and in `backend/services/admin_service.py` where it is called) writes an `ActionLog` row for each audited admin mutation, with the action type and fields that the audit read path already reads first. The JSONL file becomes the fallback for when that write fails, and the read path labels JSONL entries "this instance only".
    - New `backend/tests/test_admin_audit_action_log.py`: a table over the admin mutations that write an audit entry today, plus the router-mode set and reset of 17.6 → one `action_logs` row each, with the admin and the action; with the database write failing, the JSONL entry is written and the audit view labels it "this instance only"; the audit view still reads `action_logs` first; non-admin callers are refused.
    - Re-run `test_tenant_scope.py` and `-k "admin or audit"`.
    - _Bug_Condition: isBugCondition(X) for C12: the admin audit trail is written to one instance's disk_
    - _Expected_Behavior: Property 12_
    - _Preservation: Property 2 (3.3, 3.17): the audit view still prefers `action_logs`, and only admins see it_
    - _Requirements: 1.48, 2.48, 3.3, 3.17_

  - [~] 17.10 Verify the C12 exploration tests now pass
    - **Property 1: Expected Behavior** - Admin data access and durable admin state
    - **IMPORTANT**: Re-run the SAME tests from task 1.4. Do NOT write new tests.
    - From `backend/`: `$env:GROQ_API_KEY='mock_groq_api_key'; python -m pytest tests/test_router_mode_persisted.py tests/test_feedback_archive_durable.py tests/test_admin_query_counts.py -q -n auto --dist loadscope`.
    - **EXPECTED OUTCOME**: Tests PASS (confirms the bug is fixed).
    - _Requirements: 2.47, 2.48_

  - [~] 17.11 Verify the preservation tests still pass
    - **Property 2: Preservation** - Tenant scope and admin-only access
    - **IMPORTANT**: Re-run the SAME tests from task 2. Do NOT write new tests.
    - From `backend/`: `$env:GROQ_API_KEY='mock_groq_api_key'; python -m pytest tests/ -q -n auto --dist loadscope -k "c3_03 or c3_17 or tenant_scope or admin or router_mode or feedback or log_archives or audit"`. This covers the 3.3 and 3.17 preservation cases, the files added in 17.2 to 17.9, and the existing admin, feedback and router-mode tests.
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions).
    - _Requirements: 3.3, 3.17_

- [ ] 18. Fix C13: deploy scripts, release check, configuration and documentation (P2)
  - Each file is edited in one leaf, except `backend/tests/test_no_retired_host_defaults.py`: 18.8 adds its `landing` case and 18.11 removes its last markers, in different waves.

  - [~] 18.1 Add the billing deploy-script check (before the script changes)
    - New `backend/tests/test_deploy_scripts.py`: a static check of `backend/deploy_cloudrun.sh` and `backend/deploy_cloudrun.ps1`, parametrized with ids `sh` and `ps1`. It reads each script as text with full-line comments removed (`#` lines in both, `<# … #>` blocks in the .ps1) and asserts, per design C13.1:
      - update semantics: `--update-env-vars` and `--update-secrets` are used, and `--set-env-vars` and `--set-secrets` do not appear (2.49);
      - `--max-instances 1` (C6.6);
      - a `SUBSCRIPTION_ENFORCED` parameter that defaults to 0 (`${SUBSCRIPTION_ENFORCED:-0}` in the .sh, `-SubscriptionEnforced` with default `'0'` in the .ps1) and reaches `--update-env-vars` (C5.2);
      - `CLOUD_RUN_REGION=` set from the region variable (C12.1);
      - an `ADMIN_SERVICE_URL=ADMIN_SERVICE_URL:latest` secret mount that is added only after `gcloud secrets describe ADMIN_SERVICE_URL` succeeds;
      - `BILLING_CRON_SECRET=BILLING_CRON_SECRET:latest` in the secrets, and a setup step (`--setup` in the .sh, `-Setup` in the .ps1) that creates `BILLING_CRON_SECRET` when it is missing and holds `gcloud scheduler jobs create http` and `update http` with a job list naming every key of `services.cron_runner.JOBS` (design C8.4);
      - the `ALLOWED_ORIGINS` value is exactly the C13.1 list (https://staterbill.com, https://www.staterbill.com, https://admin.staterbill.com, https://bizassist-billing.vercel.app, https://bizassist-task.vercel.app, https://bizassist-dev-workspace-ai.vercel.app), so it has no `http://localhost:5174`, team.staterbill.com, ai.staterbill.com or hf.space (2.53);
      - the rollout order: a deploy with `--no-traffic --tag rc`, then the probe of the `rc` tag URL's `/health` (`wait_for_rc_health` in the .sh, `Wait-RcHealth` in the .ps1), then `gcloud run services update-traffic … --to-latest`;
      - a failed health check exits non-zero: the probe's failure branch ends in `exit 1`, and `update-traffic` runs only after a passing probe.
    - One more case compares the two scripts: the same variable names in `--update-env-vars` and the same secret names in `--update-secrets` (2.49: both scripts apply the same settings).
    - Run on the unfixed scripts: from `backend/`, `$env:GROQ_API_KEY='mock_groq_api_key'; python -m pytest tests/test_deploy_scripts.py -q`. Both scripts FAIL. Record the counterexamples; expected: the .sh uses `--set-env-vars` and `--set-secrets` and prints "LIVE" without a health check; the .ps1 uses `--set-secrets`, adds `http://localhost:5174` and only warns when its check fails; both allow two instances, set neither `SUBSCRIPTION_ENFORCED` nor `CLOUD_RUN_REGION`, mount neither `ADMIN_SERVICE_URL` nor `BILLING_CRON_SECRET`, create no Scheduler job, and list team.staterbill.com and ai.staterbill.com.
    - The file fails until 18.2 and 18.3 land. Record that, and do not add an xfail marker.
    - _Bug_Condition: isBugCondition(X) for C13: a billing deploy replaces variables and secrets it does not manage, omits the C5.2, C6.6, C8.4 and C12.1 settings, deploys development or unresolvable origins, or moves traffic to a revision whose health check failed_
    - _Expected_Behavior: Property 14_
    - _Preservation: Property 2 (3.10): the vercel.app transition origins stay in the list; this leaf changes tests only_
    - _Requirements: 1.49, 1.53, 1.56, 2.49, 2.53, 2.56, 3.10_

  - [~] 18.2 Apply the C13.1 settings to `backend/deploy_cloudrun.sh`
    - Parameters: the project id stays the positional argument (`bash backend/deploy_cloudrun.sh [--setup] [PROJECT_ID]`); `MIN_INSTANCES` (default 0) and `SUBSCRIPTION_ENFORCED` (default 0; only 0 or 1 accepted) come from the environment as `${NAME:-default}`.
    - `gcloud run deploy`: `--min-instances "${MIN_INSTANCES}"`, `--max-instances 1` and `--timeout 120`. Directly above the command, because a comment cannot follow a `\` continuation, add: `# --max-instances 1: real-time events and rate limits live in process (design C6, C8.6); raising it needs Postgres LISTEN/NOTIFY first.`
    - `--set-env-vars` becomes `--update-env-vars` with `ADMIN_API_ENABLED=1`, `TZ`, `BIZ_TIMEZONE`, `WEB_CONCURRENCY=1`, `SUBSCRIPTION_ENFORCED=${SUBSCRIPTION_ENFORCED}`, `CLOUD_RUN_REGION=${REGION}`, `SSE_MAX_STREAM_SECONDS=100` and `ALLOWED_ORIGINS` set to the C13.1 list. Keep the `^;^` delimiter, because the origin list contains commas.
    - `--set-secrets` becomes `--update-secrets`. `SECRETS_PARAM` adds `BILLING_CRON_SECRET=BILLING_CRON_SECRET:latest`, and `ADMIN_SERVICE_URL=ADMIN_SERVICE_URL:latest` when `gcloud secrets describe ADMIN_SERVICE_URL` succeeds, the way the script already adds `GROQ_API_KEY`. Without that secret the script says that the admin console stays unavailable until it exists (1.49). A missing `BILLING_CRON_SECRET` stops the script before the deploy with "run with --setup first".
    - Rollout, with a new function `wait_for_rc_health`:
      - when the service exists, deploy with `--no-traffic --tag rc`; poll `https://rc---<service host>/health` (the host of `status.url`) with `curl` every 5 s for up to 120 s, expecting 200 and `"status": "ok"`; then run `gcloud run services update-traffic "${SERVICE}" --to-latest`;
      - on failure, print the new revision's name and `exit 1`, which leaves traffic on the previous revision;
      - Cloud Run refuses `--no-traffic` when it creates a service, so the first deploy runs without `--no-traffic --tag rc`, probes `status.url` instead, and still exits 1 on failure;
      - the "LIVE" banner prints only after a passing probe.
    - `--setup` adds the following; the existing API, service-account and IAM steps stay as they are:
      - `cloudscheduler.googleapis.com` joins the enabled APIs;
      - `BILLING_CRON_SECRET` is created when missing, from `openssl rand -hex 32` piped to `gcloud secrets create … --data-file=-`;
      - after the traffic move, one Cloud Scheduler HTTP job per entry of a job list that names every key of `cron_runner.JOBS` with that job's current time from `services/scheduler.py`. The script creates a job with `gcloud scheduler jobs create http … --headers` or updates it with `update http … --update-headers`, POSTing to `<status.url>/internal/cron/<job>` with `--time-zone Asia/Kolkata`, `--attempt-deadline 120s`, `--max-retry-attempts 5` and `--min-backoff 30s` (design C8.4);
      - the `X-Cron-Secret` value is read with `gcloud secrets versions access` into a variable and never echoed (3.21).
    - Check: `bash -n backend/deploy_cloudrun.sh` when bash is on PATH. `test_deploy_scripts.py -k sh` passes; the `ps1` and cross-script cases still fail until 18.3. Do not run the deploy.
    - _Bug_Condition: isBugCondition(X) for C13: `deploy_cloudrun.sh` replaces every variable and secret on each deploy, sets neither `SUBSCRIPTION_ENFORCED` nor `CLOUD_RUN_REGION`, mounts neither `ADMIN_SERVICE_URL` nor `BILLING_CRON_SECRET`, allows two instances, lists unresolvable origins and reports the service live without a health check_
    - _Expected_Behavior: Property 14_
    - _Preservation: Property 2 (3.10, 3.21): the vercel.app origins stay listed, and secrets still come only from Secret Manager without being printed_
    - _Requirements: 1.49, 1.53, 1.56, 2.49, 2.53, 2.56, 3.10, 3.21_

  - [~] 18.3 Apply the same settings to `backend/deploy_cloudrun.ps1`
    - The settings of 18.2 in PowerShell, so the cross-script case of 18.1 holds:
      - parameters: `-MinInstances` keeps its default 0; new `-SubscriptionEnforced` with `[ValidateSet('0','1')]` and default `'0'`; the `-AllowedOrigins` default becomes the C13.1 list, without `https://team.staterbill.com`, `https://ai.staterbill.com` and `http://localhost:5174`;
      - `--max-instances 1` with the LISTEN/NOTIFY comment of 18.2 above the command, and `--timeout 120`;
      - `$envVars` adds `SUBSCRIPTION_ENFORCED=$SubscriptionEnforced`, `CLOUD_RUN_REGION=$Region` and `SSE_MAX_STREAM_SECONDS=100`;
      - `--set-secrets $secretsFlag` becomes `--update-secrets`; `$secretsFlag` adds `BILLING_CRON_SECRET`, and `ADMIN_SERVICE_URL` when `Test-Secret 'ADMIN_SERVICE_URL'` is true, with the same optional mounts as the .sh;
      - a new `Wait-RcHealth` function and the tagged rollout of 18.2 replace today's "Running health verification" block, which only warns. A failed probe prints the revision name and runs `exit 1`.
    - `-Setup` keeps its current steps and adds:
      - `cloudscheduler.googleapis.com` in its `services enable` list;
      - `BILLING_CRON_SECRET` through `Set-SecretValue` when `Test-Secret` is false, from 32 random bytes of `[Security.Cryptography.RandomNumberGenerator]::Create()` as hex (this also works in Windows PowerShell 5.1);
      - the Scheduler jobs of 18.2 after the traffic move.
      - Neither the secret nor the header value is written to the console.
    - With 18.2, this leaf applies the deploy-script settings that the Notes defer to C13: C5.2 `SUBSCRIPTION_ENFORCED=0`, C6.6 `--max-instances 1` and C12.1 `CLOUD_RUN_REGION`. It also covers the Scheduler `-Setup` step and the `BILLING_CRON_SECRET` mount that 16.3 hands to C13 (design C8.4).
    - Check: parse the script with `[System.Management.Automation.Language.Parser]::ParseFile` and expect no errors. `test_deploy_scripts.py` now passes in full. Do not run the deploy.
    - _Bug_Condition: isBugCondition(X) for C13: `deploy_cloudrun.ps1` replaces every secret on each deploy, deploys `http://localhost:5174` and unresolvable origins to production, sets neither `SUBSCRIPTION_ENFORCED` nor `CLOUD_RUN_REGION`, allows two instances and only warns when the health check fails_
    - _Expected_Behavior: Property 14_
    - _Preservation: Property 2 (3.10, 3.21): the vercel.app origins stay listed, and secrets still come only from Secret Manager without being printed_
    - _Requirements: 1.49, 1.53, 1.56, 2.49, 2.53, 2.56, 3.10, 3.21_

  - [~] 18.4 Add `ALLOWED_ORIGINS` to the billing CORS defaults instead of replacing them
    - `backend/main_groq.py`, per design C13.2:
      - `_default_origins` keeps https://staterbill.com, https://www.staterbill.com, https://admin.staterbill.com and the current vercel.app origins: https://bizassist-billing.vercel.app, https://bizassist-task.vercel.app, https://bizassist-dev-workspace-ai.vercel.app, https://bizassist-react.vercel.app and https://bizassist.vercel.app (3.10);
      - https://team.staterbill.com, https://ai.staterbill.com and https://rakshit-dev-bizassist.hf.space leave the list (2.53), and so do the `localhost` and `127.0.0.1` entries, because `allow_origin_regex` already covers localhost and LAN. The "null" origin stays out;
      - `_allowed_origins` becomes the order-preserving union of the defaults and `ALLOWED_ORIGINS`, as `backend-task/app/config.py` does after 5.2, so setting the variable adds origins instead of replacing the defaults.
    - New `backend/tests/test_billing_default_origins.py`. `_allowed_origins` is computed at import, so for each `ALLOWED_ORIGINS` row the test imports the app in a subprocess (keeping the test `DATABASE_URL` and `GROQ_API_KEY`, as `test_cloud_endpoint.py` does) and sends the preflights there with `TestClient`:
      - first, on the unfixed code, record today's `_default_origins` entries; they become the preservation rows;
      - `ALLOWED_ORIGINS` {unset, `https://extra.example`} × origin {the eight kept origins, the three removed hosts, `http://localhost:5174`, `http://192.168.1.20:5173`, `https://extra.example`}: the kept origins, localhost and LAN succeed in both rows, the removed hosts fail in both, and `https://extra.example` succeeds only when listed;
      - every recorded entry other than the three removed hosts still succeeds (3.10).
    - Run the file on the unfixed code first: the removed-host rows and the defaults in the `https://extra.example` row fail (record them). After the change, run it with `test_preservation_billing_api.py -k c3_10` and the existing CORS tests (`-k cors`).
    - _Bug_Condition: isBugCondition(X) for C13: the billing API's built-in CORS list names hosts that do not resolve and the retired Space, and setting `ALLOWED_ORIGINS` drops every built-in origin_
    - _Expected_Behavior: Property 14 (2.53)_
    - _Preservation: Property 2 (3.10): bizassist-billing.vercel.app, the other vercel.app origins, and localhost and LAN through the regex stay allowed_
    - _Requirements: 1.53, 2.53, 3.10_

  - [~] 18.5 Keep unmanaged secrets in `backend-task/deploy_cloudrun.ps1`
    - Task 5.4 already covers the C13 items for this script: the `-AllowedOrigins` default applied with `--update-env-vars`, and the `/api/health` readiness gate with a non-zero exit. The script already has `--max-instances 1` and no localhost origin.
    - One item is left. `gcloud run deploy` passes `--set-secrets "DATABASE_URL=…,JWT_SECRET=…,TASK_CRON_SECRET=…"`, which drops every secret mounted by hand. Change it to `--update-secrets` with the same three mappings.
    - New `backend-task/tests/test_deploy_script.py`, a static check with full-line comments removed: no `--set-env-vars` or `--set-secrets`, and `--update-secrets` maps `DATABASE_URL`, `JWT_SECRET` and `TASK_CRON_SECRET` to their Secret Manager secrets. Run it before the edit (it fails on `--set-secrets`; record that) and after (it passes): from `backend-task/`, `python -m pytest tests/test_deploy_script.py -q`.
    - Check: parse the script with `[System.Management.Automation.Language.Parser]::ParseFile` and expect no errors. Do not run the deploy.
    - _Bug_Condition: isBugCondition(X) for C13: a Field Team redeploy removes every secret that the script does not list_
    - _Expected_Behavior: Property 14_
    - _Preservation: Property 2 (3.21): the 5.4 origin default and readiness gate are unchanged, and secrets still come only from Secret Manager_
    - _Requirements: 1.9, 2.9, 3.21_

  - [~] 18.6 Point the release check at the current production hosts
    - `dev/check_cloud_release.py`, per design C13.4:
      - Defaults: `DEFAULT_BILLING_API` becomes `https://staterbill-api-1076771386585.asia-south1.run.app` and `DEFAULT_BILLING_WEB` becomes https://staterbill.com; `DEFAULT_FIELD_API` and `DEFAULT_FIELD_WEB` stay. New options with defaults: `--www-web` https://www.staterbill.com, `--ai-web` https://bizassist-dev-workspace-ai.vercel.app, `--admin-web` https://admin.staterbill.com and `--forwarder` https://rakshit-dev-bizassist.hf.space, probed at `/__forwarder` and `/health` (3.10).
      - Cold starts: the health check of each API (billing, Field Team, forwarder) runs first, with a new `--cold-start-timeout` (default 75 s). That API's other checks start after it and use `--timeout`, which keeps its 1–45 s range.
      - New failures: a redirect to `vercel.com/login` or `vercel.com/sso-api` (`vercel_sign_in`, which `_SafeRedirects` reports instead of following); a certificate or other TLS error (`tls_invalid`); https://www.staterbill.com not redirecting to https://staterbill.com (2.52); a Field Team health without `pro_required`, `billing_mirror` or `cloud_only`, now by default instead of only with `--require-field-flags`.
      - build-info.json (written by 18.7): each frontend's `/build-info.json` must exist and parse. Every non-null URL in `urls` must equal the host the check expects for that app and variable, taken from the check's own target options. A `null` entry means the project leaves that variable unset and the app uses its production default (2.54), so it passes and is listed in the report.
      - Shared secrets (2.9): new `--jwt-sha256-billing`, `--jwt-sha256-field`, `--db-sha256-billing` and `--db-sha256-field` take SHA-256 hex digests that the operator computes (the runbook, 18.10, gives the commands). Each pair prints only `match` or `mismatch`; a value that is not 64 hex characters is a usage error; a pair not given is reported as `not_checked`. The script never reads a secret itself (no `gcloud secrets versions access`), and stdout and `--report` never contain a digest, a token or a response body (3.21).
      - `--owner-token` (optional): mint a ticket with `{"purpose": "field_team"}` at the billing API's `/handoff-ticket` and exchange it at the Field Team API's `/api/auth/exchange`. The result replaces `authenticated_handoff` in `not_verified`. The token and the ticket are never printed or written.
    - Tests: new `backend/tests/test_check_cloud_release.py` loads the script by path with `importlib.util.spec_from_file_location`, as `dev/tests/test_check_cloud_release.py` does. The script uses `urllib.request`, not httpx, so the tests patch the module's `request()` and drive `_SafeRedirects` directly for the redirect cases; no test opens a socket.
      - Move every case of `dev/tests/test_check_cloud_release.py` into the new file, then delete the dev copy, so the backend runs cover the script. `test_field_flags_are_optional_until_new_api_is_deployed` changes to the new rule: the flags are required by default.
      - New tables: the defaults name no hf.space host except `--forwarder` and no bizassist-billing.vercel.app; each API's first call gets the cold-start timeout and later calls get `--timeout`; redirects to `vercel.com/login` and `vercel.com/sso-api` give `vercel_sign_in`; www passes only when it redirects to the apex; `ssl.SSLCertVerificationError` gives `tls_invalid`; build-info {missing, not JSON, retired host, production host, `null`} → fail, fail, fail, pass, pass; digests {equal, different, malformed, absent} → `match`, `mismatch`, usage error, `not_checked`.
      - `capsys` output and the `--report` file never contain the digests, the owner token or the test `JWT_SECRET`.
    - Run the new file on the unfixed script first: the moved cases pass except the changed field-flags case, and the new tables fail (record them). After the change, from `backend/`: `$env:GROQ_API_KEY='mock_groq_api_key'; python -m pytest tests/test_check_cloud_release.py -q`.
    - _Bug_Condition: isBugCondition(X) for C13: the release check probes the retired Space and bizassist-billing.vercel.app, gives up during a cold start, and cannot see a Vercel sign-in page, an invalid certificate, stale build URLs or differing secrets_
    - _Expected_Behavior: Property 14_
    - _Preservation: Property 2 (3.10, 3.21): the forwarder stays a check target, and no secret is read, printed or written_
    - _Requirements: 1.9, 1.10, 1.52, 1.54, 2.9, 2.10, 2.52, 2.54, 3.10, 3.21_

  - [~] 18.7 Emit build-info.json from each frontend build
    - `frontend-billing/vite.config.js`, `frontend-task/vite.config.js`, `frontend-ai/vite.config.js` and `frontend-admin/vite.config.js`, per design C13.3: a small inline plugin `buildInfo()` (`apply: 'build'`) whose `generateBundle` hook emits `build-info.json`, which Vite writes to `dist/build-info.json`. The file holds:
      - `app`: the project folder name;
      - `commit`: `VERCEL_GIT_COMMIT_SHA`, else `git rev-parse HEAD` when git is available, else `null`;
      - `built_at`: the UTC time in ISO 8601;
      - `urls`: for each of `VITE_API_URL`, `VITE_FIELD_TEAM_URL`, `VITE_AI_DASHBOARD_URL`, `VITE_BILLING_URL` and `VITE_PUBLIC_WEB_URL` that the app reads (grep its `src/` for `import.meta.env`), the value the build resolved with `loadEnv(mode, process.cwd(), 'VITE_')`, or `null` when the project leaves it unset.
      - Nothing else: no other environment variable is copied, so no secret can reach the file (3.21).
    - Search the four files for `hf.space` and `bizassist-billing.vercel.app`, and replace any such default with the production host here, so 18.11 does not edit them again.
    - Check: syntax-check the four files with the helper from the Notes. The user runs `npm run build` in each project locally and confirms that `dist/build-info.json` holds only `app`, `commit`, `built_at` and `urls`.
    - _Bug_Condition: isBugCondition(X) for C13: nothing records which cross-app URLs a deployed frontend was built with, so a missing `VITE_*` setting goes unnoticed_
    - _Expected_Behavior: Property 14_
    - _Preservation: Property 2 (3.21): the file holds public URLs only_
    - _Requirements: 1.54, 2.54, 3.21_

  - [~] 18.8 Point the landing page's legal links at staterbill.com
    - `bizassist-landing/src/App.jsx`: the footer's Terms, Privacy, Refunds and Contact links (today `https://bizassist-billing.vercel.app/terms`, `/privacy`, `/refund-policy` and `/contact`) go to https://staterbill.com/terms, /privacy, /refund-policy and /contact (design C13.5). Nothing else changes.
    - `backend/tests/test_no_retired_host_defaults.py`: add a `landing` case for `bizassist-landing/src`, without an xfail marker. Run it on the unfixed App.jsx first: it must list the four links (record them). If it does not, widen that case to URL literals in JSX attributes before changing App.jsx. After the change the `landing` case passes, and the other cases keep their status.
    - Check: syntax-check App.jsx with the helper; from `backend/`, `$env:GROQ_API_KEY='mock_groq_api_key'; python -m pytest tests/test_no_retired_host_defaults.py -q`.
    - _Bug_Condition: isBugCondition(X) for C13: the landing page's legal links go to bizassist-billing.vercel.app_
    - _Expected_Behavior: Property 14 (2.51)_
    - _Preservation: Property 2: the rest of the landing page is unchanged_
    - _Requirements: 1.51, 2.51_

  - [~] 18.9 Describe Cloud Run and staterbill.com in the setup documents
    - Per design C13.6 (2.55):
      - `.env.example`: the Hugging Face instructions (the header, the `CHAT_MEMORY_ENABLED` note and the `DATABASE_URL` note) describe Cloud Run instead: secrets in Secret Manager, mounted by the deploy scripts; variables through `--update-env-vars`; the Cloud Run service (one instance, `WEB_CONCURRENCY=1`) as the single-process server. The CORS comment describes the 18.4 defaults: the production list plus the vercel.app origins, `ALLOWED_ORIGINS` added to them, localhost and LAN by pattern.
      - `backend-task/.env.example`: the `ALLOWED_ORIGINS` comment says that the value is added to the default https://bizassist-task.vercel.app (task 5.2) instead of replacing the defaults.
      - `backend/README.md`: keep the Space front matter (lines 1–9), so a restored Space still builds (3.10). The body describes the Cloud Run service, its deploy scripts and health check, staterbill.com, and the forwarder that the Space now runs from `ops/hf-forwarder/`.
      - `docs/SETUP_AND_DEPLOYMENT.md`: the Vercel steps set `VITE_API_URL` to the Cloud Run billing API instead of the hf.space placeholder; a table lists each project's `VITE_API_URL`, `VITE_FIELD_TEAM_URL`, `VITE_AI_DASHBOARD_URL`, `VITE_BILLING_URL` and `VITE_PUBLIC_WEB_URL` (2.54); the domains are staterbill.com, www.staterbill.com and admin.staterbill.com; the Field Team note says 90-second `field_team` tickets instead of 30-second ones; the backend section points at the Cloud Run scripts and at the runbook of 18.10.
    - Excluded and left unchanged, as historical records: `docs/STRATEGIC_REVIEW_JUL2026.md`, `docs/plans/HOSTING_MODE_MASTER_PLAN.md`, `docs/archive/deployment_guide.md`, `docs/archive/MANUAL_TEST_PLAN.md`, `docs/archive/REVIEW_1_DESIGN_BUGS_GAPS_ADMIN_PORTAL.md` and `docs/archive/SESSION_HANDOFF.md`.
    - Check: in the edited files, `Select-String -Pattern 'hf\.space'` finds only mentions of the forwarder or the retired Space. Docs only; no test run.
    - _Bug_Condition: isBugCondition(X) for C13: the setup documents and `.env.example` describe a Hugging Face and Vercel-only setup, including an hf.space `VITE_API_URL`_
    - _Expected_Behavior: Property 14 (2.55)_
    - _Preservation: Property 2 (3.10, 3.21): the documents keep the forwarder path for installed desktop apps and keep secrets in Secret Manager only_
    - _Requirements: 1.55, 2.55, 3.10, 3.21_

  - [~] 18.10 Write the Cloud Run migration runbook
    - New `docs/runbooks/cloud-run-migration.md` (design C13.6). Its steps are the `Operator actions` section of this plan, in the same order and with the same commands and verification commands. That section is the source: when either changes, change the other in the same commit.
    - Order: Field Team API → billing API → HF forwarder → frontends → desktop release (design "Backward Compatibility and Deploy Order"). Each step gives the exact command or console path and a verification command with its expected result.
    - The steps cover the design C13.6 items:
      - the www.staterbill.com domain and certificate (2.52);
      - Deployment Protection off for the production AI dashboard (2.11);
      - each project's `VITE_*` values (2.54);
      - the Field Team API redeploy and its readiness gate (2.9);
      - shared `JWT_SECRET` and `DATABASE_URL`, with the commands that compute the SHA-256 digests for `dev/check_cloud_release.py` without printing a secret;
      - `SUBSCRIPTION_ENFORCED`;
      - `BILLING_CRON_SECRET` and the Scheduler jobs (`-Setup`, 18.3), with the 16.4 note to pause the jobs while traffic is on a revision from before 16.4;
      - the forwarder (2.33);
      - optional `--min-instances 1`;
      - optional custom subdomains with their DNS.
    - If the section lacks one of these items, report it instead of adding the item to the runbook alone.
    - Check: compare the runbook with the section step by step before marking this leaf done. Docs only; no test run.
    - _Bug_Condition: isBugCondition(X) for C13: no document lists the operator steps of the migration in deploy order with a way to verify each_
    - _Expected_Behavior: Property 14 (2.55)_
    - _Preservation: Property 2 (3.10, 3.21): the forwarder step keeps installed desktop apps working, and every secret step uses Secret Manager without printing a value_
    - _Requirements: 1.9, 1.52, 1.54, 1.55, 1.56, 2.9, 2.52, 2.54, 2.55, 2.56, 3.10, 3.21_

  - [~] 18.11 Remove the last xfail markers from `test_no_retired_host_defaults.py`
    - Delete the `xfail(strict=False)` markers of the `dev` and `frontend_*` cases, and of any per-file `backend` case that task 1.1 split off. Then run the file and resolve each remaining hit:
      - the `--forwarder` default in `dev/check_cloud_release.py` (18.6) is a check target, not a fallback for an API call: add it to the allow-list with that reason;
      - any other hit is a retired-host fallback in a file that no other 18.x leaf edits (task 12 recorded which cases still failed): replace it with the production host of design C13.3 (2.54), and syntax-check each changed JS/JSX file with the helper;
      - a hit in a file that another 18.x leaf edits (the four `vite.config.js`, `dev/check_cloud_release.py`, `bizassist-landing/src/App.jsx`) means that leaf is unfinished: fix it there.
    - Run from `backend/`: `$env:GROQ_API_KEY='mock_groq_api_key'; python -m pytest tests/test_no_retired_host_defaults.py -q`. Every case passes, and no xfail marker is left in the file.
    - _Bug_Condition: isBugCondition(X) for C13: a frontend or dev tool falls back to hf.space or bizassist-billing.vercel.app when its setting is missing_
    - _Expected_Behavior: Property 14 (2.54)_
    - _Preservation: Property 2 (3.10): the allow-listed transition trust lists stay as they are_
    - _Requirements: 1.54, 2.54, 3.10_

  - [~] 18.12 Verify the C13 exploration tests now pass
    - **Property 1: Expected Behavior** - Release configuration
    - **IMPORTANT**: Re-run the SAME tests from task 1.1 and the C13 tests written in 18.1, 18.4, 18.5 and 18.6. Do NOT write new tests.
    - From `backend/`: `$env:GROQ_API_KEY='mock_groq_api_key'; python -m pytest tests/test_no_retired_host_defaults.py tests/test_deploy_scripts.py tests/test_billing_default_origins.py tests/test_check_cloud_release.py -q -n auto --dist loadscope`. From `backend-task/`: `python -m pytest tests/test_deploy_script.py -q`.
    - **EXPECTED OUTCOME**: Tests PASS (confirms the bug is fixed), and `test_no_retired_host_defaults.py` reports no xfail.
    - _Requirements: 2.9, 2.10, 2.49, 2.51, 2.52, 2.53, 2.54, 2.56_

  - [~] 18.13 Verify the preservation tests still pass
    - **Property 2: Preservation** - Transition hosts and secret handling
    - **IMPORTANT**: Re-run the SAME tests from task 2. Do NOT write new tests.
    - From `backend/`: `$env:GROQ_API_KEY='mock_groq_api_key'; python -m pytest tests/ -q -n auto --dist loadscope -k "c3_10 or c3_21 or cors or origin or cloud_endpoint or hf_forwarder"`. This covers the 3.10 and 3.21 preservation cases, the CORS tests and the forwarder configuration. From `backend-task/`: `python -m pytest tests/test_preservation_handoff.py tests/test_default_origins.py -q`.
    - Ask the user to run `npm run build` and the Vitest suites in the four frontends, and `npm run build` in `bizassist-landing`, because 18.7 and 18.8 changed their files.
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions).
    - _Requirements: 3.10, 3.21_

- [~] 19. Final fix verification
  - Re-run every exploration test file from task 1 and every preservation test file from task 2; the leaves of tasks 1 and 2 name each path.
  - The backend files run in the agent sandbox. Start both runs at the same time and wait for both:
    - from `backend/`: `$env:GROQ_API_KEY='mock_groq_api_key'; python -m pytest <the task 1 and 2 files under tests/> -q -n auto --dist loadscope`
    - from `backend-task/`: `python -m pytest <the task 1 and 2 files under tests/> -q -n auto --dist loadscope`
  - The frontend files run on the user's machine. List them for the user by app, each app with its command: `npx vitest run <files> --pool=threads --reporter=dot`.
  - Confirm that no xfail marker from this spec remains: search `backend/tests` and `backend-task/tests` for `fixed in part 2`, the marker reason text from the Notes. Expect no matches.
  - **EXPECTED OUTCOME:** all pass.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11, 2.12, 2.13, 2.14, 2.15, 2.16, 2.17, 2.18, 2.19, 2.20, 2.21, 2.22, 2.23, 2.24, 2.25, 2.26, 2.27, 2.28, 2.29, 2.30, 2.31, 2.32, 2.33, 2.34, 2.35, 2.36, 2.37, 2.38, 2.39, 2.40, 2.41, 2.42, 2.43, 2.44, 2.45, 2.46, 2.47, 2.48, 2.49, 2.50, 2.51, 2.52, 2.53, 2.54, 2.55, 2.56, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14, 3.15, 3.16, 3.17, 3.18, 3.19, 3.20, 3.21, 3.22_

- [~] 20. Final checkpoint - ensure all tests pass
  - Start both backend suites at the same time (for example as two background processes) and wait for both:
    - from `backend/`: `$env:GROQ_API_KEY='mock_groq_api_key'; python -m pytest tests/ -q -n auto --dist loadscope`
    - from `backend-task/`: `python -m pytest tests/ -q -n auto --dist loadscope`
  - Expected:
    - No failures except `tests/test_intent_router.py::test_semantic_router_eval_accuracy`.
    - Billing passes at least the baseline of 2526 tests plus the tests this spec added; backend-task passes fully.
  - Syntax-check every JS/JSX file added or changed in tasks 16 to 18 with the helper.
  - Ask the user to run these locally, in this order (after `npm install` where `node_modules` is missing), and report the results:
    - `npx vitest run --pool=threads --reporter=dot` in `frontend-billing`, `frontend-task`, `frontend-ai` and `frontend-admin`
    - `npx playwright test e2e/login-layout.spec.js` in `frontend-billing` (review the saved screenshots)
    - `npm run lint` in `frontend-admin`
    - `npm run build` in `frontend-billing`, `frontend-task`, `frontend-ai`, `frontend-admin` and `bizassist-landing`
    - a desktop build smoke test: build the installer with the steps in `.github/workflows/release.yml`, install it, start the app and sign in
  - Do not run `run_tests.ps1`. Ask the user if questions arise; the operator actions start after the user confirms the local results.

## Operator actions (performed by the user)

The user runs these steps after the code tasks are merged, in deploy order, from the repository root in Windows PowerShell; `docs/runbooks/cloud-run-migration.md` (leaf 18.10) mirrors them.

1. Field Team API redeploy and its readiness gate (2.9)
   - Command: `.\backend-task\deploy_cloudrun.ps1 -Project <field-team-project-id> -AllowedOrigins "https://bizassist-task.vercel.app"`
   - Verify: `curl.exe -s https://bizassist-task-qyfsbxu27a-el.a.run.app/api/health` shows `pro_required: true`, `billing_mirror: false` and `cloud_only: true`.
   - Verify: `curl.exe -si -X OPTIONS https://bizassist-task-qyfsbxu27a-el.a.run.app/api/auth/exchange -H "Origin: https://bizassist-task.vercel.app" -H "Access-Control-Request-Method: POST"` returns status 200 with the header `access-control-allow-origin: https://bizassist-task.vercel.app`.
   - Rollback: if this API is rolled back after step 3, it refuses the 90 s tickets that the billing API mints. Run `gcloud run services update staterbill-api --project staterbill --region asia-south1 --update-env-vars HANDOFF_TTL_FIELD_TEAM=55`.

2. Shared `JWT_SECRET` and `DATABASE_URL`
   - Command: compute the SHA-256 digest of both secrets in each project. Run the snippet once as written and once with `$project = '<field-team-project-id>'`. It prints only the digests and clears each value after hashing it.

     ```powershell
     $project = 'staterbill'
     foreach ($name in 'JWT_SECRET', 'DATABASE_URL') {
         $secret = gcloud secrets versions access latest --secret $name --project $project
         $digest = [Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($secret))
         Remove-Variable secret
         $hex = ([BitConverter]::ToString($digest) -replace '-', '').ToLower()
         "$project $name $hex"
     }
     ```

   - Verify: `python dev/check_cloud_release.py --jwt-sha256-billing <staterbill JWT_SECRET digest> --jwt-sha256-field <field-team JWT_SECRET digest> --db-sha256-billing <staterbill DATABASE_URL digest> --db-sha256-field <field-team DATABASE_URL digest>` reports `match` for both pairs.

3. Billing API deploy, `BILLING_CRON_SECRET` and the Scheduler jobs (18.3)
   - Command: `.\backend\deploy_cloudrun.ps1 -Project staterbill -Setup`. The first run creates `BILLING_CRON_SECRET` and the Cloud Scheduler jobs; later deploys run the same command without `-Setup`.
   - Optional, only if the runtime database role is moved to a constrained role: before the deploy, create the `ADMIN_SERVICE_URL` secret in the Google Cloud console (project `staterbill` → Security → Secret Manager → Create secret). Verify: `gcloud secrets describe ADMIN_SERVICE_URL --project staterbill` shows the secret's metadata, not its value.
   - Verify: `curl.exe -s https://staterbill-api-1076771386585.asia-south1.run.app/health` returns ok.
   - Verify: `gcloud scheduler jobs list --project staterbill --location asia-south1` lists the jobs that `-Setup` created, each `ENABLED`.
   - Verify: `gcloud run services describe staterbill-api --project staterbill --region asia-south1` shows max instances 1 and `SUBSCRIPTION_ENFORCED=0`.
   - Rollback: move traffic back with `gcloud run services update-traffic staterbill-api --to-revisions <rev>=100 --project staterbill --region asia-south1`. If `<rev>` is from before task 16.4, first pause each Scheduler job with `gcloud scheduler jobs pause <job> --project staterbill --location asia-south1`, and resume it with `gcloud scheduler jobs resume <job> --project staterbill --location asia-south1` once traffic is on a revision with 16.4 again.

4. Hugging Face forwarder (2.33)
   - Command: replace the Space's contents with `ops/hf-forwarder/`. When Git asks for a password, give a Hugging Face access token with write access.

     ```powershell
     $space = "$env:TEMP\hf-bizassist"
     git clone https://huggingface.co/spaces/rakshit-dev/bizassist $space
     git -C $space rm -r -q .
     Copy-Item -Recurse -Force .\ops\hf-forwarder\* $space
     git -C $space add -A
     git -C $space commit -m "Replace the Space with the Cloud Run forwarder"
     git -C $space push
     ```

   - Verify, once the Space shows Running: `curl.exe -s https://rakshit-dev-bizassist.hf.space/__forwarder` answers, and `curl.exe -s https://rakshit-dev-bizassist.hf.space/health` returns the Cloud Run health JSON (`"db_type":"postgresql"`).
   - Rollback: `git -C $space revert --no-edit HEAD`, then `git -C $space push`.

5. Vercel frontends
   - (a) www domain and certificate (2.52): Vercel dashboard → billing project → Settings → Domains → add `www.staterbill.com`, redirecting to `staterbill.com`, then add the DNS record that Vercel shows at the DNS provider. Verify: `curl.exe -sI https://www.staterbill.com` shows a 308 to `https://staterbill.com` with no certificate error.
   - (b) Deployment Protection (2.11): Vercel dashboard → AI dashboard project → Settings → Deployment Protection → turn off Vercel Authentication for Production. Verify: `curl.exe -sI https://bizassist-dev-workspace-ai.vercel.app/` returns 200, not a 302 to `vercel.com/sso-api`.
   - (c) Production environment variables (2.54): in each project, Settings → Environment Variables, scoped to Production. A comma-separated `VITE_BILLING_URL` works only after tasks 9 and 10 are deployed.

     | Project | Variable | Value |
     |---|---|---|
     | frontend-billing | `VITE_API_URL` | `https://staterbill-api-1076771386585.asia-south1.run.app` |
     | frontend-billing | `VITE_FIELD_TEAM_URL` | `https://bizassist-task.vercel.app` |
     | frontend-billing | `VITE_AI_DASHBOARD_URL` | `https://bizassist-dev-workspace-ai.vercel.app` |
     | frontend-billing | `VITE_PUBLIC_WEB_URL` | `https://staterbill.com` |
     | frontend-task | `VITE_API_URL` | `https://bizassist-task-qyfsbxu27a-el.a.run.app` |
     | frontend-task | `VITE_BILLING_URL` | `https://staterbill.com,https://www.staterbill.com` |
     | frontend-ai | `VITE_API_URL` | `https://staterbill-api-1076771386585.asia-south1.run.app` |
     | frontend-ai | `VITE_BILLING_URL` | `https://staterbill.com,https://www.staterbill.com` |
     | frontend-admin | `VITE_API_URL` | `https://staterbill-api-1076771386585.asia-south1.run.app` |
     | frontend-admin | `VITE_BILLING_URL` | `https://staterbill.com,https://www.staterbill.com` |

   - (d) Redeploy each project: Deployments → latest production deployment → ⋯ → Redeploy. Verify: `curl.exe -s https://<host>/build-info.json` on `staterbill.com`, `bizassist-task.vercel.app`, `bizassist-dev-workspace-ai.vercel.app` and the admin console's host shows that project's values from the table.
   - Rollback: promote the previous production deployment (Deployments → ⋯ → Instant Rollback).

6. Desktop release
   - Command: build and publish the installer through the existing release workflow, `.github/workflows/release.yml`.
   - Verify on an installed app, signed in as the owner: Settings shows the sync status from `GET http://127.0.0.1:8001/api/sync/status`, with `cloud_url` = `https://staterbill-api-1076771386585.asia-south1.run.app`.

7. Decisions, each with its current default
   - `--min-instances 1` on `staterbill-api` removes cold starts but costs an always-on instance. Default: 0. To adopt: `gcloud run services update staterbill-api --project staterbill --region asia-south1 --min-instances 1`. Verify: `gcloud run services describe staterbill-api --project staterbill --region asia-south1` shows min instances 1.
   - `SUBSCRIPTION_ENFORCED`. Default: 0. To enforce: `.\backend\deploy_cloudrun.ps1 -Project staterbill -SubscriptionEnforced 1`. Verify: the same `describe` command shows `SUBSCRIPTION_ENFORCED=1`.
   - `team.staterbill.com` and `ai.staterbill.com`. Default: not adopted. To adopt one: add its DNS record and the domain in the Vercel project, add the new origin to the APIs' CORS and trust settings (for the Field Team API, the `-AllowedOrigins` value from step 1), and point `VITE_FIELD_TEAM_URL` or `VITE_AI_DASHBOARD_URL` from step 5 (c) at it. Verify: `curl.exe -sI https://team.staterbill.com` (or `ai.staterbill.com`) returns 200 with no certificate error.
   - Retiring the Hugging Face Space. Default: keep it until installed desktop apps have updated (design assumption 6).

8. Release check and smoke test
   - Command: `python dev/check_cloud_release.py --report release-report.json`. Expected: every check passes, and `release-report.json` records the results.
   - Then check by hand:
     - web sign-in on a phone, including a cold start;
     - Field Team opened from https://staterbill.com signs in as the right business;
     - Dashboard → BIZASSIST opens the AI dashboard with no Vercel page;
     - the admin console's Infrastructure page shows real values or "unavailable";
     - desktop sync status shows the Cloud Run URL and the outbox drains;
     - a web tab left open for more than 5 minutes shows no sync toasts and no sign-out.
