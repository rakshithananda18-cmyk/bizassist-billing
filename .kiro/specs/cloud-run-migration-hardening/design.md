# Cloud Run Migration Hardening Bugfix Design

## Overview

The billing API moved from a Hugging Face Space to Cloud Run (`staterbill-api`), the billing web app moved to https://staterbill.com, and Field Team got its own Cloud Run service (`bizassist-task`). bugfix.md records 56 defects (1.1 to 1.56). They come from old-host defaults, code that assumes one always-warm instance, decisions taken before the plan or session state is known, the regressions from 5700877 and 38b5244, and production configuration that is missing or that the deploy scripts overwrite.

The design keeps the seven assumptions of bugfix.md as they are: `--min-instances 0` with cold starts of up to 60 s, `--max-instances 1` for `staterbill-api`, Field Team and the AI dashboard on their vercel.app URLs (configurable), `SUBSCRIPTION_ENFORCED=0` set explicitly, the 5-minute preview for free web accounts with the gate reported by the server, the Hugging Face Space turned into a forwarder, and no api.staterbill.com in this release.

The fix follows five rules:

1. Every cross-service URL has one source and a production default: a backend resolver, the desktop shell, and frontend defaults. Trust lists read configuration, so adopting team.staterbill.com or ai.staterbill.com later is a configuration change.
2. Cold starts are cheap on the servers (a boot fast path that does no DDL when the schema is current) and tolerated by clients (60-second budgets, a visible "waking up" state, bounded retries that honour `Retry-After`).
3. A session rejection carries an explicit marker. Clients sign out only on that marker from their own backend, never on a 404, a gateway page or a passed-through cloud 401.
4. The single-instance assumption is explicit (`--max-instances 1`). State that must survive a restart moves to the database: spent tickets, revoked dashboard sessions, scheduled-job runs, LAN discovery, the router mode and client log archives.
5. Configuration that code cannot fix goes into deploy scripts with update semantics, a release check and an operator runbook.

Where this design departs from the recommended fixes:

| Recommendation | Design | Reason |
|---|---|---|
| Web sign-in budget of about 45 s | 65 s | Assumption 1 and 2.20 require tolerating a 60 s cold start; 45 s fails the slowest allowed start. |
| Spent tickets kept in memory | Billing API: database table. Field Team API: memory, as today | 2.40 names restarts: a deploy or crash restarts the process, and an in-memory set forgets the tickets spent during the last lifetime. 2.40 does not cover the Field Team API. |
| Field Team API default origins include team.staterbill.com | Not included | 2.53 forbids origins that serve no frontend; assumption 3 makes adoption a configuration step. |
| B2B upstream 401 mapped to 409 or 424 | 424 with `code: cloud_sign_in_required` | No route returns 424 today, so the status alone identifies the case; real 409 conflicts stay distinct. |
| Signup made idempotent, or verified by a login | Login with the same credentials after a time-out | No new server state, and it works against the API that is deployed today. |
| Forwarder as a streaming reverse proxy | nginx (unprivileged image) configuration, no application code | Streaming and SSE need only `proxy_buffering off`; there is no proxy code to maintain. |
| Feedback archives in the database or GCS | Database, with size caps | No new GCP dependency, and the SQLite test suite covers it. |
| SSE tickets unchanged | SSE tickets carry `aud=sse` | Hand-off tickets and SSE tickets share one format and key; the audience stops one being used as the other. |
| Deploy fails on a failed health check | Deploy with `--no-traffic --tag rc`, probe the tagged URL, then move traffic | A revision that fails the check never serves traffic. |

## Glossary

- **Bug_Condition (C)**: `isBugCondition(X)` below. X triggers the bug when it meets the WHEN part of some clause 1.k.
- **Property (P)**: `expectedBehavior(X, result)` below. For X in C, the matching clause 2.k holds.
- **Preservation**: for X with ¬C(X), F'(X) = F(X), and every clause 3.k holds.
- **F / F'**: the production system before and after this fix, including deploy scripts and the operator steps in the runbook.
- **Cold start**: a request that reaches a Cloud Run service while it is scaled to zero or still starting (up to 60 s, assumption 1).
- **Cloud endpoint resolver**: `resolve_cloud_url()` in the new `backend/core/cloud_endpoint.py`, the single source of the billing API URL for backend code.
- **Hand-off ticket**: `<exp>.<b64url payload>.<hex HMAC-SHA256>` minted by `create_sse_ticket` in `backend/services/auth.py`. The payload is the owner's session claims. This fix adds `aud` (purpose) and `iat` inside the signed payload.
- **Purpose / aud**: `field_team`, `ai_dashboard`, `admin_console` or `sse`. A ticket with no `aud` is a legacy ticket.
- **Session-rejection marker**: the response header `WWW-Authenticate: Bearer error="invalid_token"`, sent when the billing API rejects the session token itself.
- **sid / psid**: a random session id claim on billing session tokens, and the parent session id carried by tokens that `/redeem-ticket` issues to the AI dashboard.
- **Schema signature**: a SHA-256 value stored in the new `schema_state` table after a complete migration run, used to skip boot-time migration work.
- **Rotate event**: the SSE frame `event: rotate` that the server sends just before it ends a stream on purpose.
- **Event id**: `<epoch>-<seq>` on every SSE frame. `epoch` identifies the process; `seq` is a per-business sequence.
- **Gate flags**: `subscription.gates = {ai, field_team, hybrid_sync, web_preview}` in `GET /settings`. True means the server applies that gate to this account now.
- **planKnown**: true once `GET /settings` has returned a `subscription.plan` in this session.
- **cloud_state**: the sync worker's view of the cloud: `online`, `waking`, `busy` or `offline`.
- **Forwarder**: the Hugging Face Space after this fix, a reverse proxy from the old hf.space URL to the Cloud Run billing API.

## Bug Details

### Bug Condition

The bug manifests when a production interaction uses an old or missing host, meets a cold start or a platform time limit, relies on in-process state across restarts, acts on a plan or session state it has not learned yet, hits one of the two regressions, or depends on configuration that is not deployed. bugfix.md files every defect under those six predicates. A few defects (1.6, 1.8, 1.16, 1.23 to 1.26, 1.37, 1.45 to 1.47, 1.50) are plain code faults whose symptoms appeared after the move; the grouped form names them separately as `hasLocalDefect`. Every clause appears in at least one group, and clauses with two causes (for example 1.1, 1.11, 1.44, 1.53 and 1.56) appear in two. The union is the same as in bugfix.md, because the exact form is the disjunction of the clauses.

**Formal Specification:**
```
FUNCTION isBugCondition(X)
  INPUT: X, an interaction (request, page load, app launch, service boot, scheduled job)
  OUTPUT: boolean

  // Exact form: X meets the WHEN part of at least one defect clause.
  RETURN EXISTS k IN 1..56 : WHEN_1_k(X)
END FUNCTION

// Grouped form, equivalent to the exact form:
usesStaleOrMissingHost(X) :=                                  // 1.1-1.2, 1.10, 1.13-1.14, 1.32-1.34, 1.44, 1.51, 1.53-1.55
     resolvedCloudUrl(X) = HF_SPACE_URL
  OR X.billingOrigin IN {staterbill.com, www.staterbill.com} AND X.billingOrigin NOT IN trustedBy(X.receiver)
  OR X.target IN {bizassist-billing.vercel.app links, "http://<host>:5173", unset VITE_* fallback}
meetsColdStartOrTimeLimit(X) :=                               // 1.5, 1.11-1.12, 1.20-1.22, 1.35-1.39, 1.41
     X.service.coldStartSeconds + X.work > MIN(X.clientBudget, X.ticketLifetime)
  OR X.streamOrRequestSeconds >= platformLimit(X.service)    // 120 s billing, 60 s Field Team
  OR X.response IS Google HTML 429/5xx page
dependsOnInstanceState(X) :=                                  // 1.40, 1.42, 1.48
     X reads or writes process memory or instance disk AND (instances > 1 OR restartedSince(X.state))
  OR X IS a cron job due while CPU is not allocated
decidesOnUnknownState(X) :=                                   // 1.3, 1.7, 1.15, 1.27-1.31, 1.56
     X.decision USES plan AND NOT planKnown
  OR X.response.status IN {401, 404} AND NOT sessionRejected(X.response) AND client signs out
  OR X.handoff failed AND client restores a stored session
hitsRegression(X) :=                                          // 1.1 (38b5244), 1.17-1.19, 1.43-1.44 (5700877)
     X.route IN {POST /api/biz_id/check, GET /api/auth/check-username}
  OR X.route = GET /admin/infrastructure-metrics
  OR X IS a web Field Team launch without VITE_FIELD_TEAM_URL
dependsOnMissingConfig(X) :=                                  // 1.4, 1.9, 1.11, 1.49, 1.52-1.53, 1.56
     X.origin NOT IN deployed ALLOWED_ORIGINS OR X needs ADMIN_SERVICE_URL, SUBSCRIPTION_ENFORCED,
     the www certificate, Deployment Protection off, or a current Field Team revision
hasLocalDefect(X) :=                                          // 1.6, 1.8, 1.16, 1.23-1.26, 1.37, 1.45-1.47, 1.50
     X meets one of those WHEN parts
```

### Examples

- A packaged desktop app pushes its outbox: the bundled backend calls `https://rakshit-dev-bizassist.hf.space/api/sync/push` and gets 503. Expected: the desktop shell passes `CLOUD_API_URL`, so the push reaches Cloud Run; an older install reaches Cloud Run through the forwarder.
- An owner on https://staterbill.com opens Field Team while the Field Team API needs 45 s to start. The ticket expires 30 s after minting and the exchange arrives at 52 s, so Field Team shows "Sign-in link expired". Expected: a 90 s `field_team` ticket with 15 s leeway signs the owner in on the first attempt.
- The ticket request fails and Field Team, opened from staterbill.com, restores the stored session of another business. Expected: Field Team clears the stored session and asks the owner to sign in for the BizID that Billing named.
- A Pro owner clicks Dashboard BIZASSIST while `/settings` is still loading and sees "Pro plan feature". Expected: no alert or PRO badge until the plan is known.
- A web sign-in during a billing cold start is aborted at 6 s with "restart BizAssist". Expected: "Waking up the server…" from 4 s, and sign-in completes at 50 s.
- A web tab keeps its stream open: Cloud Run cuts it at 120 s, Billing shows three toasts and every page refetches. Expected: the server rotates at 100 s and the client reconnects silently with `last_event_id`; no page refetches when nothing was missed.
- A billing instance boots against a database with 200,000 synced rows: it drops and recreates every capture trigger and runs one existence query per row. Expected: with a current schema, boot runs three short catalog queries and no DDL.
- `POST /api/biz_id/check {"username": "alice"}` returns `exists`, `business_name`, staff status and the owner's username. Expected: 404 with no body details.
- Edge case: a ticket minted at T, a force logout at T+5 s, and a redemption at `/redeem-ticket` at T+10 s returns a fresh session. Expected: 401.
- Edge case: on the desktop app, a cloud 401 for a B2B write passes through and the renderer signs the user out. Expected: the proxy answers 424 `cloud_sign_in_required` and the session stays.

## Expected Behavior

### Expected Behavior Specification

```
FUNCTION expectedBehavior(X, result)
  INPUT: X with isBugCondition(X) = true; result = F'(X)
  OUTPUT: boolean

  RETURN FOR EVERY k IN 1..56 WHERE WHEN_1_k(X) : THEN_2_k(X, result)
      AND (signedOut(result) IMPLIES sessionRejected(result.response))      // 2.22, 2.28, 2.30, 2.31
      AND noSecretIn(result.messages, result.logs)                           // 2.6, 2.9, 3.21
END FUNCTION
```

The concrete, testable forms of `THEN_2_k` are the numbered properties in Correctness Properties.

### Preservation Requirements

**Unchanged Behaviors:**
- Session revocation and outages: 401 for revoked or deleted subjects, 503 when the database is unreachable, and sign-out when the billing API rejects the session token (3.1).
- No anonymous discovery: `GET /staff-counters?owner=` stays 404 and no lookup route is added (3.2).
- Tenant isolation: the tenant-scope guard still fails unscoped reads and stale allowances (3.3); BizID stays the only cross-database identity and Local-only businesses send nothing (3.4).
- Tickets: owner-only, HMAC over the shared `JWT_SECRET`, short-lived and single-use; Field Team still refuses staff tickets (403) and pre-logout tickets (401) (3.5).
- Plan enforcement on the servers: Field Team 402 messages and Pro-only AI chat (3.6); the cashier and supply-adder restrictions and the Local + Cloud Pro gate when enforced (3.14).
- Message trust: exact origin and opener checks; only origins are added (3.7); appearance hand-off accepts only sanitized colour tokens (3.19).
- Routing: localhost and LAN hosts use the local backend, other hosts use the cloud (3.8); the desktop opens its bundled dashboard at 127.0.0.1:8451 and prints in-app (3.15); desktop sign-in keeps its bounded wait and local-service message (3.16); the desktop gets Field Team tickets from the cloud (3.18).
- Free accounts: the 5-minute preview and lock, the trial-ended screen, and PRO badges for a known non-Pro plan (3.9).
- Transition hosts: bizassist-billing.vercel.app and the other current vercel.app origins stay trusted, and old desktop apps keep working through the forwarder (3.10).
- Local backend start-up: SQLite still creates and migrates its schema, installs the change feed and runs its in-process scheduler; a constrained cloud runtime still refuses to start on a missing schema (3.11).
- Replication: exactly-once seeding per UID and commit-ordered events (3.12); warm-cloud sync, outbox chunking and backoff, B2B proxying and the "B2B is offline" refusal (3.13).
- Admin: `ADMIN_API_ENABLED` gating, database re-checks of admin authority, audited mutations and 2FA (3.17).
- Real-time: the per-business connection cap and closing a revoked session's stream (3.20).
- Secrets come only from Secret Manager, are never printed, and the installer ships without .env (3.21).
- Every test that passes today still passes under the parallel commands (3.22).

**Scope:**
All interactions that do not meet any WHEN part of 1.1 to 1.56 must be unaffected. This includes:
- Requests to a warm cloud with valid sessions, and every desktop request served by the local backend.
- Requests from the transition hosts (bizassist-billing.vercel.app, the vercel.app frontends).
- Desktop start-up and its in-process scheduler.
- Admin, sync and B2B behaviour whenever the cloud answers normally.

## Hypothesized Root Cause

The investigation confirmed most causes in code. Items marked *to confirm* need production evidence.

1. **Old-host defaults and four variable names** (1.32 to 1.34, 1.44, 1.55): `services/sync_worker.py`, `routes/b2b_proxy.py`, `services/realtime.py`, `main_groq.py` discovery, `services/telemetry_relay.py`, `routes/admin.py` and `scripts/cloud_cleanup_counters.py` default to, or hard-code, the hf.space URL, and their overrides read four different names: `CLOUD_API_URL`, `VITE_API_URL`, `CLOUD_URL` and `BIZASSIST_CLOUD_URL`. `cloud_listener`, `auth`, `feedback`, `control_outbox` and `log_uploader` import `sync_worker.CLOUD_URL`. `desktop/src/backend.js` spawns the backend without a cloud URL, and `desktop/src/telemetry.js` defaults to hf.space.
2. **Trust lists that know only the old billing host** (1.2, 1.13, 1.14): `sanitizeBillingUrl` and `BILLING_CLOUD_URL` in `frontend-task/src/lib/theme.js`, and `trustedHandoff` in `frontend-ai` and `frontend-admin` `src/utils/handoff.js`, trust only https://bizassist-billing.vercel.app plus one `VITE_BILLING_URL`. The logout frame in `frontend-billing/src/contexts/AuthContext.jsx` builds its own URL with port 5173.
3. **Removed web fallback** (1.1, regression 38b5244): `getFieldTeamUrl()` returns `''` on the web without `VITE_FIELD_TEAM_URL`.
4. **Client budgets shorter than a cold start** (1.5, 1.12, 1.20 to 1.22, 1.35, 1.41): `authFetchWithFailover` defaults to 6 s; tickets live 30 s and the Field Team API allows no leeway (`_TICKET_MAX_LIFETIME_S = 60`, no grace after `exp`); `openAiDashboard` awaits the ticket before `window.open`; the B2B proxy uses 12 s; the sync worker probes `/health` for 10 s and refreshes tokens with 10 s and a 15-minute retry; error parsing assumes JSON bodies.
5. **Boot work that grows with the data** (1.5, 1.36, 1.37): `main_groq.py` runs `create_all` and `run_migrations_and_seed()` at import. On a privileged role this runs every step, then `install_change_feed`, which drops and recreates each capture trigger and checks every row with its own query. `change_feed.py` has no `logger`, and both handlers classify errors by the substrings "lock" and "deadlock". Whether the Supabase `postgres` role has BYPASSRLS is *to confirm*. The Field Team API calls `command.upgrade(cfg, "head")` on every boot.
6. **Streams at the platform limit** (1.38, 1.39): `sse_realtime_feed` never ends a stream on its own, frames carry no `id:`, and `RealtimeManager` keeps no history. `useRealtimeLeader` toasts on every error and dispatches `sync.reconnect` after any reconnect. `cloud_listener` uses `read=None` and resets its backoff only after a clean close.
7. **In-process state** (1.40, 1.42, 1.48): `RealtimeManager.connections`, `discovery._REGISTRY`, the `rate_limiter` windows, `_used_tickets`, `router_mode._explicit`, `logs/remote_clients/` and APScheduler cron jobs all live in one process or on instance disk.
8. **Decisions on unknown state** (1.3, 1.7, 1.15, 1.27 to 1.31, 1.56): `AppLayout.jsx` computes `aiGated` and `isFreePlan` as `!subscription?.plan || plan !== 'pro'`, starts the preview timer under `bizassist_session_start_time` without reading the server's gate, and never retries `/settings`. `api/client.js` and `authFetch` sign out on every 401; `fetchProfile`, `fetchSettings` and the business-config fetch sign out on every 404. No web app calls `POST /auth/refresh`. The admin console's `authFetch` calls `adminLogout()` on any 401 and `AdminLogin` always navigates to `/admin/dashboard`. Field Team restores a stored session when the origin is untrusted (cause 2), and the AI dashboard does so after a failed redemption.
9. **Ticket checks** (1.6, 1.16): `redeem_billing_ticket` raises one `refused` exception for every reason; `redeem_ticket` does not call `_validate_token_version`.
10. **Regressions from 5700877** (1.17 to 1.19, 1.43, 1.44): `biz_id_check` and `check_username_get` in `routes/auth.py`, their callers in `Login.jsx` and `Register.jsx`, and `get_admin_infrastructure_metrics` with its undeclared `psutil` import, unscoped ORM counts and sequential probes.
11. **Admin console code faults** (1.45 to 1.47, 1.50): invented fallback values and a 15 s auto-refresh on the Infrastructure page; `get_rate_limits` and `get_all_usage_stats` lack a generic `except`; `list_businesses`, `sync_doctor` and the usage stats run per-business queries; `business_details` returns whole tables; the SSO path in `frontend-admin/src/contexts/AuthContext.jsx` sets only `user`.
12. **Deploy scripts and configuration** (1.4, 1.9 to 1.11, 1.49, 1.52 to 1.56): `backend/deploy_cloudrun.sh` uses `--set-env-vars` and `--set-secrets`, `--max-instances 2`, and reports success without a health check; `deploy_cloudrun.ps1` adds `http://localhost:5174` and only warns on a failed check; neither sets `SUBSCRIPTION_ENFORCED` or `ADMIN_SERVICE_URL`. The Field Team deploy sets `ALLOWED_ORIGINS` only with `-AllowedOrigins`, and its built-in default lists only localhost. `dev/check_cloud_release.py` targets hf.space and bizassist-billing.vercel.app. The landing page links to the old host. The www certificate and Deployment Protection are Vercel settings.
13. **Login layout** (1.23 to 1.26): two `.login-card` rules in `frontend-billing/src/index.css`, a fixed `.login-container` at z-index 9999 with `100vw` and `100vh`, the System check trigger at z-index 50 outside that layer, and inline grid styles in `Login.jsx`.

## Correctness Properties

Property 1: Bug Condition - Post-migration interactions behave as specified

_For any_ interaction X where isBugCondition(X) holds, the fixed system F' SHALL produce a result for which expectedBehavior(X, result) holds: each matching clause 2.k is met, no client signs out without a session-rejection marker from its own backend, and no secret appears in a message or log.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11, 2.12, 2.13, 2.14, 2.15, 2.16, 2.17, 2.18, 2.19, 2.20, 2.21, 2.22, 2.23, 2.24, 2.25, 2.26, 2.27, 2.28, 2.29, 2.30, 2.31, 2.32, 2.33, 2.34, 2.35, 2.36, 2.37, 2.38, 2.39, 2.40, 2.41, 2.42, 2.43, 2.44, 2.45, 2.46, 2.47, 2.48, 2.49, 2.50, 2.51, 2.52, 2.53, 2.54, 2.55, 2.56**

Property 2: Preservation - Interactions outside the bug condition are unchanged

_For any_ interaction X where isBugCondition(X) does not hold, the fixed system SHALL produce the same result as the original system, preserving every behaviour listed in clauses 3.1 to 3.22, and every test that passes today SHALL still pass under the parallel commands.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14, 3.15, 3.16, 3.17, 3.18, 3.19, 3.20, 3.21, 3.22**

Property 3: Bug Condition - One cloud endpoint

_For any_ environment E (any subset of `CLOUD_API_URL`, `VITE_API_URL`, `CLOUD_URL`, `BIZASSIST_CLOUD_URL` set to valid or empty values), `resolve_cloud_url(E)` SHALL return the first value in that order that is a valid http(s) URL, trimmed and without trailing slashes, or the Cloud Run default when there is none, and every backend cloud caller and the desktop shell SHALL use that value; on a localhost or LAN host the apps SHALL still use the local backend.

**Validates: Requirements 2.32, 2.33, 2.34, 3.8, 3.10, 3.21**

Property 4: Bug Condition - Ticket lifecycle

_For any_ ticket t with purpose p, mint time m, redemption time r and token-version state v, the redeemer SHALL accept t at most once, and only when the signature is valid, `r <= exp + 15 s`, `exp - iat <= 120 s` (or `exp - r <= 120 s` for a ticket without `iat`), the audience matches the redeemer (or is absent during the transition), the subject is an owner, and the token version is current; each refusal SHALL return the reason's own message and log the reason.

**Validates: Requirements 2.5, 2.6, 2.16, 2.40, 3.5**

Property 5: Preservation - Trusted Billing origins

_For any_ message or launch whose origin o and source s are given, Field Team, the AI dashboard and the admin console SHALL accept it if and only if s is the opener (for messages) and o is in the default Billing set {https://staterbill.com, https://www.staterbill.com, https://bizassist-billing.vercel.app}, in the comma-separated `VITE_BILLING_URL`, or a local host on ports 5174 or 8450.

**Validates: Requirements 2.2, 2.13, 3.7, 3.10, 3.19**

Property 6: Bug Condition - Sign-out only on session rejection

_For any_ response (status, headers, body, origin) received by Billing, the AI dashboard or the admin console, the client SHALL end the session if and only if the response comes from its own API base and carries the session-rejection marker, or a refresh attempt for an unmarked 401 itself returns 401; HTML 429 and 5xx bodies SHALL become short readable messages.

**Validates: Requirements 2.22, 2.28, 2.30, 2.31, 2.35, 3.1**

Property 7: Bug Condition - Plan gates follow the server

_For any_ settings state (not loaded, failed, or loaded with plan, trial status, enforcement and gate flags) and role, Billing SHALL show a PRO badge, a Pro alert or the preview lock only when planKnown is true and the server's gate flag for that feature is true, SHALL run the preview timer only under the key for the current BizID and user, and SHALL never lock a Pro account.

**Validates: Requirements 2.7, 2.27, 2.56, 3.9, 3.14**

Property 8: Bug Condition - Boot fast path

_For any_ Postgres database state where the stored schema signature equals the computed one and the change-feed function exists, a billing boot SHALL run no DDL, no per-row query and no statement that takes a table lock; for any other state, the migration SHALL run once under one advisory lock, SHALL seed each missing UID exactly once, SHALL leave unchanged triggers alone, and SHALL fail visibly on any error that is not a confirmed concurrent-migration conflict.

**Validates: Requirements 2.5, 2.36, 2.37, 3.11, 3.12**

Property 9: Bug Condition - Real-time continuity

_For any_ sequence of events for a business and any set of stream cuts (rotation, platform cut, network drop, process restart), each connected Billing client SHALL receive every event whose sequence number is greater than its last event id, either by replay or, when replay cannot cover the gap, by one `sync.reconnect`; SHALL show no toast unless the stream stays down for more than 30 s; and the desktop listener SHALL treat 45 s without bytes as a dead stream.

**Validates: Requirements 2.38, 2.39, 2.40, 3.20**

Property 10: Bug Condition - Sync and B2B under cold starts

_For any_ cloud response sequence made of timeouts, Google HTML 429 or 503 pages with or without `Retry-After`, and successes, the sync worker SHALL report `waking` or `busy` instead of `offline`, SHALL wait at least the `Retry-After` value, SHALL keep its token unless the cloud rejects it with 401, and SHALL start token refresh 12 h before expiry; B2B reads SHALL fall back to the local mirror and B2B writes SHALL wait up to 70 s.

**Validates: Requirements 2.35, 2.41, 3.13**

Property 11: Bug Condition - Scheduled jobs run exactly once

_For any_ set of Cloud Scheduler deliveries, retries and concurrent duplicates for one job and one period, the job SHALL complete once per period, and APScheduler cron jobs SHALL not start when `K_SERVICE` is set, while the desktop keeps its in-process scheduler.

**Validates: Requirements 2.42, 3.11**

Property 12: Bug Condition - Admin console reliability

_For any_ admin route and any failure injected inside it, the response SHALL be a JSON 500 with CORS headers; the number of queries for the fleet, sync doctor and usage views SHALL not grow with the number of businesses; and an SSO arrival SHALL set the admin session only after the server confirms the admin role.

**Validates: Requirements 2.43, 2.44, 2.45, 2.46, 2.47, 2.48, 2.49, 2.50, 3.3, 3.17**

Property 13: Bug Condition - Login and registration

_For any_ username, the billing API SHALL disclose nothing about account existence before sign-in; and _for any_ viewport from 320 to 1920 px wide and 360 to 1200 px high, the login card SHALL be reachable by scrolling, the page SHALL have no horizontal scroll, and the footer edges SHALL match the card edges.

**Validates: Requirements 2.17, 2.18, 2.19, 2.20, 2.21, 2.23, 2.24, 2.25, 2.26, 3.2, 3.16**

Property 14: Bug Condition - Release configuration

_For any_ frontend build without a given `VITE_*` setting, every cross-app URL SHALL default to its production host; the release check SHALL fail on a Vercel sign-in redirect, an invalid certificate, a host mismatch in build-info.json, or differing `JWT_SECRET` or database fingerprints, without printing a secret; and the deploy scripts SHALL keep variables they do not manage.

**Validates: Requirements 2.9, 2.10, 2.49, 2.51, 2.53, 2.54, 2.55, 3.21**

## Fix Implementation

### Changes Required

Assuming the root cause analysis is correct, the changes are grouped by component. Each heading lists the clauses it serves.

New billing tables (`schema_state`, `spent_tickets`, `revoked_sessions`, `scheduled_job_runs`, `discovery_registrations`, `platform_settings`, `client_log_archives`) each get a model in `backend/database/models.py`, an Alembic revision for the constrained-runtime path, and runtime-role grants following the existing pattern in `database/security.py`. None of them is in `MODEL_MAP`, so none gets a capture trigger or reaches the sync protocol.

#### C1. One cloud endpoint (1.32 to 1.34; 2.32 to 2.34; 3.8, 3.10, 3.21)

**File**: `backend/core/cloud_endpoint.py` (new)

**Functions**: `resolve_cloud_url(environ=os.environ) -> tuple[str, str]` returns `(url, source)`; module constants `DEFAULT_CLOUD_URL = "https://staterbill-api-1076771386585.asia-south1.run.app"` and `CLOUD_URL`, `CLOUD_URL_SOURCE` computed at import.

1. **Resolution order**: `CLOUD_API_URL`, `VITE_API_URL`, `CLOUD_URL`, `BIZASSIST_CLOUD_URL`, then the default. Values are trimmed and lose trailing slashes. A value that is not an http(s) URL is skipped with a warning that names the variable. An explicit hf.space value is honoured but logged once as pointing at the retired Space.
2. **Callers**: `services/sync_worker.py` sets `CLOUD_URL = cloud_endpoint.CLOUD_URL`, which keeps the attribute that `cloud_listener`, `routes/auth.py`, `routes/feedback.py`, `routes/admin.py`, `control_outbox` and `log_uploader` import. `routes/b2b_proxy.py` keeps its `CLOUD_URL` attribute (asserted by `test_b2b_proxy_test_isolation.py`). `services/realtime.py` (`_CLOUD_URL`), `_discovery_registration_loop` in `main_groq.py`, `services/telemetry_relay.py`, `scripts/cloud_cleanup_counters.py` and `check_cloud_api.py` read the resolver. Tests set `CLOUD_API_URL=http://127.0.0.1:9` before import; the resolver reads that variable first, so they are unaffected.
3. **Visibility**: the lifespan logs `[CLOUD] cloud API = <url> (from <source>)` once. A new owner-only `GET /api/sync/status` (no such route exists today) returns `{cloud_url, cloud_url_source, cloud_state, last_probe_at, retry_after}`.
4. **Desktop**: new `desktop/src/cloudEndpoint.js` exports `DEFAULT_CLOUD_API_URL` and `resolveCloudApiUrl(env)` with the same order. `desktop/src/backend.js` adds `CLOUD_API_URL: resolveCloudApiUrl(process.env)` to the spawn environment; `desktop/src/telemetry.js` uses the same function. The installer still ships without .env (3.21).
5. **Forwarder** (`ops/hf-forwarder/`, new; the operator pushes it to the existing Space): `Dockerfile` based on `nginxinc/nginx-unprivileged:1.27-alpine`, a Space `README.md` header (`sdk: docker`, `app_port: 7860`), and `default.conf`:
   - `listen 7860`; `location = /__forwarder { return 200 "ok"; }` for diagnosis.
   - `location /`: `proxy_pass` to the Cloud Run URL with `Host` set to the run.app host, `proxy_ssl_server_name on`, HTTP/1.1 with an empty `Connection` header, `proxy_buffering off` and `proxy_request_buffering off` (SSE and uploads stream), `proxy_read_timeout 130s`, `proxy_connect_timeout 10s`, `X-Forwarded-For` and `X-Forwarded-Proto`, and `client_max_body_size 30m`.
   - CORS stays with the billing API, which sees the original `Origin`.

#### C2. Billing API boot (1.36, 1.37; 2.36, 2.37; 3.11, 3.12)

**Files**: `backend/database/migration.py`, `backend/database/change_feed.py`, `backend/database/models.py`, `backend/main_groq.py`, a new Alembic revision.

**Functions**: `run_migrations_and_seed`, `install_change_feed`, new `compute_schema_signature`, `_sqlstate`, `_change_feed_installed`.

1. **Schema state**: new model `SchemaState` (`schema_state`: `key` PK, `signature`, `applied_at`, `applied_by`). It is part of `Base.metadata`, so the conftest `drop_all`/`create_all` cycle resets it.
2. **Signature**: `compute_schema_signature(dialect)` hashes a new `MIGRATION_REVISION` constant (bumped by hand when a backfill changes without a model change), the compiled `CreateTable` and `CreateIndex` DDL of `Base.metadata` sorted by name, and the build id (`BIZASSIST_BUILD_ID`, else `K_REVISION`). Cloud Run changes `K_REVISION` on every deploy, so a full run happens once per revision.
3. **Postgres boot** in `run_migrations_and_seed`:
   - Unprivileged role: the existing readiness check is unchanged (3.11); a differing signature only logs a warning.
   - Privileged role, fast path: `SELECT to_regclass('public.schema_state')`, then one query that reads the stored signature and `to_regprocedure('bizassist_feed_emit(integer,text,jsonb,text)')`. With the role check, that is three short catalog queries. If the signature matches and the emit function exists, boot logs `[Migration] schema current, skipped` and returns.
   - Otherwise it takes `pg_advisory_lock(724839101)` on a dedicated connection with `SET lock_timeout = '90s'`, reads the signature again (a peer may have finished), runs today's steps (`create_all`, column migrations, the `_step` sequence, seeds, change feed and security), writes the signature only when no step recorded a failure, and releases the lock. `_rollback_quietly` appends to a module-level `_STEP_FAILURES` list, so failures caught inside a step still block the write.
   - The module-level `Base.metadata.create_all(bind=engine)` in `main_groq.py` moves into this slow path on Postgres.
   - `BIZASSIST_FORCE_MIGRATIONS=1` forces the slow path.
4. **SQLite boot** (desktop and tests): every step still runs on each start (3.11). Only the seed change in item 6 applies.
5. **Triggers** in `install_change_feed`:
   - `change_feed.py` defines `logger = logging.getLogger("bizassist.change_feed")`.
   - On Postgres the transaction starts with `SET LOCAL lock_timeout = '5s'`, so a lock that cannot be granted fails fast instead of queueing every request behind it.
   - For each synced table: if `pg_proc.prosrc` of `bizassist_feed_<name>` equals the rendered body (whitespace-normalised) and `bizassist_feed_capture` exists on the table and calls that function, nothing is executed. A different body gets `CREATE OR REPLACE FUNCTION`, which takes no table lock. A missing or different trigger gets `CREATE OR REPLACE TRIGGER` (PostgreSQL 14 or later; Supabase runs 15), or `DROP` plus `CREATE` on older servers.
   - The per-table substring handler is removed; errors reach the caller.
6. **Seeding**:
   - Postgres, one statement per table and owner expression, with `body` bound to `to_jsonb(t)`:
     ```sql
     SELECT bizassist_feed_emit((<owner expr>), :entity, s.body, 'INSERT')
     FROM (SELECT to_jsonb(t) AS body, t.id AS _id FROM "<name>" t) s
     WHERE (<owner expr>) IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM sync_feed_events e
                       WHERE e.business_id = (<owner expr>) AND e.entity = :entity
                         AND e.row_uid = COALESCE(s.body->>'uid', s.body->>'id'))
     ORDER BY s._id
     ```
     The key is the expression that `bizassist_feed_emit` stores, so each (business, entity, UID) is seeded at most once (3.12). The payload uses the capture trigger's own encoding. `bizassist_feed_emit` holds each clock row lock to commit, so commit ordering is unchanged. The implementation confirms an index on `sync_feed_events (business_id, entity, row_uid)` and adds one if it is missing.
   - SQLite: one query per table loads the existing `(business_id, row_uid)` keys for that entity into a set, and the loop inserts only missing rows with today's statements. No per-row SELECT remains.
7. **Error classification**: `_sqlstate(exc)` reads `exc.orig.pgcode` (psycopg2) or `exc.orig.sqlstate` (psycopg 3).
   - `40P01` or `55P03`: retry the change-feed transaction up to three times after 2, 4 and 8 s plus jitter. After the last attempt, `_change_feed_installed(conn)` checks the function and every synced table's trigger: if installed, log "peer completed" at WARNING and continue; otherwise raise.
   - Any other error: log it with `exc_info` and raise. The revision then fails its startup probe and the previous revision keeps serving (2.37, 2.49).
8. **Embedding model**: `preload_model_async()` runs only when `K_SERVICE` is unset (desktop). On Cloud Run the model loads on first use.

#### C3. Field Team API (1.4 to 1.6, 1.9; 2.4 to 2.6, 2.9; 3.5, 3.6)

**Files**: `backend-task/app/main.py`, `backend-task/app/security.py`, `backend-task/app/config.py`, `backend-task/deploy_cloudrun.ps1`.

1. **Boot**: `run_migrations()` reads the current heads with `MigrationContext` (as `_unknown_revisions` already does) and returns `True` without calling `command.upgrade` when they equal `script.get_heads()`, logging `[BOOT] ft schema at head <rev>, upgrade skipped`. A new head still upgrades once (2.5).
2. **Origins**: `_default_origins = "https://bizassist-task.vercel.app"`, and `ALLOWED_ORIGINS` becomes the order-preserving union of the defaults and `parse_origins(os.environ.get("ALLOWED_ORIGINS", ""))`. The localhost entries leave the default list because `allow_origin_regex` already covers localhost and LAN (2.53). team.staterbill.com is added through `ALLOWED_ORIGINS` when it is adopted (assumption 3).
3. **Ticket verification**: `redeem_billing_ticket(ticket)` keeps its name and return value and raises a `TicketRefused(reason)` (an `HTTPException` 401) per reason. Constants: `_TICKET_MAX_LIFETIME_S = 120`, `_TICKET_LEEWAY_S = 15`. Checks run in this order, so a key mismatch is never reported as an expiry:

   | Order | Reason | Condition | `detail` shown to the owner |
   |---|---|---|---|
   | 1 | `malformed` | not three parts or a non-integer `exp`; after the signature check, a payload that is not a JSON object | This sign-in link is not valid for Field Team. Open Field Team from BizAssist Billing again. |
   | 2 | `bad_signature` | HMAC mismatch | Field Team could not verify this sign-in link. Field Team and Billing are not set up with the same sign-in key; ask your administrator to check the deployment. |
   | 3 | `expired` | `now > exp + 15` | Sign-in link expired. Open Field Team from BizAssist Billing again. |
   | 4 | `lifetime` | `exp - iat > 120`, or `exp - now > 120` without `iat` | Same as `expired`. |
   | 5 | `audience` | `aud` present and not `field_team` | Same as `malformed`. |
   | 6 | `already_used` | ticket in the spent set | This sign-in link was already used. Open Field Team from BizAssist Billing again. |

   Each refusal logs `[AUTH] hand-off ticket refused reason=<reason> exp_delta=<seconds>`, never the ticket, claims or key. A ticket without `aud` is accepted and logged as `legacy_no_aud` for one release. Spent entries are kept until `exp + 15`. The staff refusal (403), the token-version check (401) and the Pro check (402) after verification are unchanged (3.5, 3.6). The spent set stays in process for this service; see Risks.
4. **Deploy script**: `-AllowedOrigins` defaults to `https://bizassist-task.vercel.app` and is always applied with `--update-env-vars`. After the deploy, the script polls `/api/health` until it reports `pro_required`, `billing_mirror` and `cloud_only` (the readiness gate of 1.9) and exits non-zero otherwise.

#### C4. Billing API tickets, sessions and logout (1.16, 1.28 to 1.31, 1.40; 2.14, 2.16, 2.28 to 2.31, 2.40; 3.1, 3.5, 3.20)

**Files**: `backend/services/auth.py`, `backend/routes/auth.py`, `backend/core/api/realtime.py`, `backend/main_groq.py`, `backend/database/models.py`, a new Alembic revision.

1. **Minting**: `create_sse_ticket(user_payload, expires_in_seconds, *, aud=None)` adds `iat` and, when given, `aud` inside the signed payload. The format does not change, so the deployed Field Team API still parses it.
   - `POST /handoff-ticket` accepts an optional body `{"purpose": "field_team" | "ai_dashboard" | "admin_console"}`. Lifetimes: `field_team` 90 s (`HANDOFF_TTL_FIELD_TEAM`, capped at 120), `ai_dashboard` and `admin_console` 60 s. An `ai_dashboard` ticket also carries `psid`, the caller's `sid`.
   - No body gives a legacy ticket: no `aud`, 30 s, exactly as today, for bundles deployed before this release.
   - `POST /realtime/ticket` mints with `aud="sse"`.
2. **Verification**: new `verify_ticket(ticket, *, audiences, leeway=15) -> TicketCheck(claims, reason)` with the reasons of C3. `redeem_sse_ticket(ticket)` keeps its signature (`dict | None`, used by tests) as a wrapper with `audiences={None, "sse"}`.
   - `get_active_user_or_ticket` accepts `aud` in `{None, "sse"}`.
   - `redeem_ticket` accepts `{None, "ai_dashboard", "admin_console"}`, refuses `field_team` and `sse` with 401, and calls `_validate_token_version(claims)` before it issues a session (2.16). Each refusal logs its reason and returns a reason-specific `detail`.
3. **Spent tickets** (2.40): new model `SpentTicket` (`spent_tickets`: `digest` = SHA-256 of the ticket as PK, `expires_at`). After the other checks pass, redemption inserts the digest with insert-if-absent in a short transaction of its own; no row inserted means `already_used`. The in-memory `_used_tickets` stays as a fast first check. If the table cannot be written, the verifier falls back to the in-memory set and logs a warning, which is today's behaviour. Rows past `expires_at + 1 h` are deleted in bounded batches every 100 inserts and by the telemetry retention job.
   - Why the database: 2.40 names restarts. Every deploy restarts the service within one ticket lifetime, and an in-memory set would let a captured ticket be redeemed again on the new revision. One indexed insert per redemption is cheap at this volume (one per web stream rotation and one per hand-off).
4. **Session claims**: a helper `_session_claims(user_row, *, sid, psid=None)` builds the claims for `login`, `staff_login`, `signup`, `redeem_ticket` and `refresh_session`, so the five call sites cannot drift. Login and signup create a random `sid`; `refresh_session` copies `sid` and `psid` from the presented token; `redeem_ticket` creates a new `sid` and copies `psid` from an `ai_dashboard` ticket.
5. **Logout** (2.14): new `POST /auth/logout` (authenticated, idempotent) inserts the caller's `sid` into `revoked_sessions` (`sid` PK, `expires_at` = the token's `exp`). `get_active_user` checks `revoked_sessions` only for tokens that carry `psid`, next to the token-version check; a revoked `psid` or `sid` gives a marked 401. Tokens without `psid` skip the lookup, so ordinary requests cost the same as today.
   - Why this mechanism: bumping `token_version` signs the owner out on every device; short-lived dashboard tokens would need a refresh channel through Billing; a hidden frame cannot reach the dashboard's partitioned storage on another site. The `psid` check adds one primary-key lookup per dashboard request and nothing elsewhere. Sessions created before this release have no `sid`, so their dashboard sessions end at token expiry, at most 24 h after the release.
6. **Session-rejection marker** (2.28, 2.30, 3.1): `session_rejected(detail)` returns `HTTPException(401, detail, headers={"WWW-Authenticate": 'Bearer error="invalid_token"'})`. It replaces the 401 raises in `get_active_user`, `decode_access_token`, `_validate_token_version`, `get_active_user_or_ticket` and `refresh_session`. The "user not found" 404s of `GET /profile`, `GET /settings` and the business-config route carry the same header. The status codes and `detail` texts stay as they are. CORS `expose_headers` becomes `["X-Total-Count", "WWW-Authenticate", "Retry-After"]`, and `allow_headers` adds `Last-Event-ID`.

#### C5. Plan gates (1.7, 1.27, 1.56; 2.7, 2.27, 2.56; 3.6, 3.9, 3.14)

**File**: `backend/routes/auth.py`, function `_subscription_view`; the billing deploy scripts.

1. `_subscription_view` adds `gates`. `exempt` is true for an admin caller, and `pro` is `effective_plan(plan_holder) == "pro"`:
   ```
   gates.ai          = NOT exempt AND NOT pro                          // /ask* always enforce Pro
   gates.field_team  = NOT exempt AND NOT pro                          // the Field Team API always enforces Pro
   gates.hybrid_sync = NOT exempt AND NOT pro AND subscription_enforced()
   gates.web_preview = NOT exempt AND NOT pro                          // assumption 5, independent of enforcement
   ```
   `enforced` stays in the response for older clients. Staff inherit the owner's plan through `plan_holder`, as today.
2. Both billing deploy scripts set `SUBSCRIPTION_ENFORCED=0` explicitly (a parameter, so the operator can change it). The Field Team API and the `/ask*` routes keep enforcing Pro on the server (3.6).

#### C6. Real-time streams (1.38 to 1.40; 2.38 to 2.40; 3.20)

**Files**: `backend/services/realtime.py` (`RealtimeManager`), `backend/core/api/realtime.py` (`sse_realtime_feed`), `backend/services/cloud_listener.py`, new `frontend-billing/src/sync/sseConnection.js`, `frontend-billing/src/hooks/useRealtimeLeader.js`, `frontend-billing/src/b2b/useB2BRealtime.js`.

1. **History**: `RealtimeManager` gains `epoch` (8 hex characters from `uuid4` at construction), a per-business sequence and a per-business history `deque` of `(seq, event)` with `maxlen = SSE_REPLAY_BUFFER` (default 256). `broadcast()` assigns the sequence number and appends to the history before its first `await`, then queues the same event object as today. Queue items stay plain event dicts, because `test_realtime_sync.py` and `test_sse_hardening.py` compare them; the stream finds an event's sequence number by identity in the history. Presence events are delivered but not buffered, since only the latest one matters.
2. **Replay**: `subscribe(business_id)` keeps its signature and its 429 cap (3.20). New `subscribe_from(business_id, last_event_id)` returns `(queue, replay, status)`. `status` is `none` without an id, `complete` when the epoch matches and the history still holds every later event, and `gap` otherwise. It subscribes and copies the history in the same event-loop step, so no event falls between the two.
3. **Stream**: `sse_realtime_feed` takes `last_event_id` from the query string or the `Last-Event-ID` header and sends:
   - `retry: 5000`;
   - `event: hello` with `{"epoch": ..., "replay": status}`;
   - the replayed frames, then live frames, each with `id: <epoch>-<seq>`;
   - keep-alive comments every 15 s, as today;
   - after `SSE_MAX_STREAM_SECONDS` (default 100), `event: rotate` with `data: {}`, and then it returns.

   The token-version check on every loop is unchanged, so revoking a session still closes its stream (3.20).
4. **Billing web client**: `createSseConnection({ fetchTicket, onEvent, onStatus, onGap })` in `sseConnection.js`:
   - mints a ticket, opens `/realtime/events?ticket=…&last_event_id=…`, and records `event.lastEventId`;
   - on `rotate`, closes the `EventSource` at once (before the browser retries with the spent ticket) and reconnects after 0 to 1 s with a new ticket, without a status change;
   - on `hello` with `replay: "gap"`, calls `onGap()`; `none` and `complete` do nothing;
   - on an error or a close without `rotate`, reconnects after 1 s doubling to 30 s with ±30 % jitter, reset by the next `hello`;
   - reports `degraded` only after 30 s without a connection, and `connected` when it returns.

   `useRealtimeLeader` uses the helper: no toasts for connecting or reconnecting; one "Live sync interrupted. Retrying…" toast after 30 s down and one "Live sync restored" toast only after that; `sync.reconnect` only from `onGap`; the session pause after repeated failures counts only failures that were not rotations. `useB2BRealtime` replaces its fixed 5 s retry with the same helper, and its `onGap` triggers one refetch of the B2B lists.
5. **Desktop listener** (`_Listener.run` in `cloud_listener.py`):
   - `httpx.Timeout(connect=10.0, read=45.0, write=10.0, pool=10.0)`, three keep-alive intervals (2.39);
   - the backoff resets to `_RECONNECT_BASE_SEC` once a stream answers 200 and delivers its first line;
   - `event: rotate` counts as a clean end and reconnects after 1 s; a read timeout counts as a drop;
   - after every reconnect, one pull that respects `_MIN_PULL_GAP_SEC`, as a cursor-based catch-up.
6. **Single instance**: the deploy scripts set `--max-instances 1` (assumption 2), which makes in-process fan-out, the history and the rate-limit windows complete (2.40). After a restart the epoch changes, so each client gets `replay: "gap"` and refetches once. Raising the limit later needs Postgres LISTEN/NOTIFY first.

#### C7. Sync worker and B2B proxy (1.35, 1.41; 2.35, 2.41; 3.13)

**Files**: `backend/services/sync_worker.py`, `backend/routes/b2b_proxy.py`, the B2B write calls in `frontend-billing/src/b2b/`.

1. **Cloud state**: a per-business `_CLOUD_STATE` (`online`, `waking`, `busy`, `offline`, with `retry_after`) feeds `/api/sync/status` and the sync popover.
2. **Health probe** in `_sync_business_impl`:
   - read timeout 45 s when the last successful contact is more than 10 minutes old, otherwise 10 s;
   - a time-out sets `waking`, logs at INFO, writes no failed `SyncLog` row, and retries on the next tick;
   - a 429, 502, 503 or 504 (HTML or JSON), or a 200 whose body is not the expected JSON, sets `busy` and waits for `Retry-After` (seconds or an HTTP date, capped at 300 s, 30 s when absent) plus 0 to 20 % jitter;
   - connection and DNS errors set `offline`, as today.
3. **Token refresh** (`ensure_fresh_cloud_token`): `_REFRESH_WHEN_UNDER = 12 h`; timeout 45 s; retries after 1, 2, 4, 8 and then every 15 minutes instead of a flat 15 minutes; 429 and 503 honour `Retry-After`. A 401 still drops the token (unchanged); a cold start never produces a 401.
4. **Push**: `_PUSH_TIMEOUT` read becomes 100 s, inside the 120 s limit. Each chunk sends `X-Client-Request-Id` = SHA-256 of the business id, the sorted outbox ids and the payload digest, so a retried chunk carries the same key. `/api/sync/push` applies rows by UID, so a replayed chunk creates no duplicate; a test pins that guarantee whether or not the push route uses `core/sync/idempotency.replay_guard`.
5. **Parity sweep** (`_cloud_parity_check`): the single legacy pull (`last_sync_at=1970-01-01`, 180 s read) becomes protocol-2 pages from cursor 0, each with `_PULL_TIMEOUT` (60 s), within an overall 10-minute budget. When the budget runs out, the summary says `incomplete`. The sweep stays detection-only.
6. **B2B proxy** (`b2b_cloud_proxy`):
   - Reads (`_READ_METHODS`) serve the local mirror on network errors, time-outs, any 5xx and 429, and keep the 12 s `_TIMEOUT`.
   - Writes use `_WRITE_TIMEOUT = httpx.Timeout(connect=10, read=70, write=30, pool=10)` and keep the "B2B is offline" 503 for network errors (3.13); 429 and 5xx pass through with `Retry-After`.
   - An upstream 401 still drops the stale token and serves reads from the mirror. For a write it now returns 424 `{"detail": "Sign in to BizAssist cloud again to change B2B data.", "code": "cloud_sign_in_required"}` instead of passing the 401 through.
   - The renderer's B2B write calls use a 75 s client timeout.

#### C8. Scheduled jobs and LAN discovery (1.40, 1.42; 2.40, 2.42; 3.11)

**Files**: `backend/services/scheduler.py`, new `backend/routes/internal_cron.py`, new `backend/services/cron_runner.py`, `backend/routes/discovery.py`, `backend/database/models.py`, the alert, summary, audit and telemetry job modules, the billing deploy scripts.

1. **In-process scheduler**: `start_scheduler()` registers nothing when `K_SERVICE` is set and logs that Cloud Scheduler owns the jobs. The desktop (SQLite) keeps every job, including the interval jobs (3.11).
2. **Endpoint**: `POST /internal/cron/{job}` with the header `X-Cron-Secret`, following backend-task's `purge_pings_now`: 404 when `BILLING_CRON_SECRET` is unset or the job is unknown, 403 on a mismatch (`hmac.compare_digest`), excluded from the schema. Jobs: `daily_summary`, `overdue_alerts`, `low_stock_alerts`, `expiry_alerts`, `books_integrity_audit`, `telemetry_retention`, `memory_distillation`, `telemetry_db_maintenance`. `daily_log_upload`, `telemetry_relay`, `hybrid_sync` and `cloud_parity_sweep` are desktop-only and stay off on Cloud Run.
3. **Run record**: `scheduled_job_runs` (`job`, `period` as the primary key; `status`, `cursor`, `lease_until`, `started_at`, `finished_at`, `error`). The period is the IST date for daily jobs and the ISO week for weekly jobs.
   - `cron_runner.run(job, period, budget_s=95)` claims the row with insert-if-absent, or takes over a `partial` row or an expired lease with a conditional UPDATE. A `done` row returns 200 `already_ran`; a live lease returns 409.
   - Job functions accept an optional `after_business_id` and a deadline and return the last business processed. Called without them, as APScheduler does, they process everything as today.
   - When the budget ends first, the row is `partial` with the cursor, and the response is 503 with `Retry-After: 30`, so Cloud Scheduler retries and the run continues from the cursor.
   - Limit: a crash between one business's side effect and the cursor update can repeat that business once.
4. **Cloud Scheduler** (created by the deploy `--setup` step): the current times in Asia/Kolkata, `--attempt-deadline 120s`, `--max-retry-attempts 5`, `--min-backoff 30s`, and the secret read from Secret Manager without printing it.
5. **Discovery**: new `discovery_registrations` (`biz_id`, `ip`, `port` as the key; `url`, `registered_at`, `last_seen`). When `_persist_enabled()` (Postgres, or `DISCOVERY_PERSIST=1`), register and unregister write through, and a lookup that finds no live entry in `_REGISTRY` reloads that BizID's rows newer than `TTL_SECONDS`. `_REGISTRY` stays the in-process cache, so the SQLite tests that clear or seed it keep their meaning.
6. **Rate limits** stay in process. Under `--max-instances 1` they count every request; a restart resets windows of at most 15 minutes, which is accepted.

#### C9. Billing web app (1.1, 1.7, 1.8, 1.12, 1.14, 1.17 to 1.31, 1.56; 2.1, 2.7, 2.8, 2.12, 2.14, 2.17 to 2.31, 2.56; 3.1, 3.8, 3.9, 3.14 to 3.16, 3.18)

**Files**: `frontend-billing/src/config/fieldTeam.js`, `config/aiDashboard.js`, `contexts/AuthContext.jsx`, `api/client.js`, new `api/httpErrors.js`, new `hooks/useSessionRefresh.js`, `layouts/AppLayout.jsx`, `pages/Login.jsx`, `pages/Register.jsx`, `index.css`, `b2b/`.

1. **Field Team launch** (2.1, 2.8, 3.18):
   - `getFieldTeamUrl()` falls back to `FIELD_TEAM_CLOUD_URL` on every build. `VITE_FIELD_TEAM_URL` still overrides it, and the local-fixture rule is unchanged.
   - New `fieldTeamLaunchUrl(user)` returns the Field Team URL with `from_billing=1`, `billing_origin` and `billing_business` and no ticket. The sidebar item and the workspace switcher use it as the anchor `href`, so a middle-click or "Open in new tab" lands on Field Team's sign-in for that business.
   - `openFieldTeam` (plain click, after `preventDefault`): when `window.open` returns null, toast "Your browser blocked the Field Team window. Allow pop-ups for this site, or open the link in a new tab." Otherwise write "Opening Field Team…" into the blank window, request the ticket with `{purpose: "field_team"}` within 65 s, and navigate. When the ticket fails, navigate without `sso` and toast "Couldn't hand over your sign-in. Sign in on Field Team with the same account."
   - `cloudTicket()` (desktop) sends the same purpose.
2. **AI dashboard** (2.12, 2.14, 3.15):
   - `openAiDashboard` opens or reuses the `ai_dashboard` window inside the click, then requests `{purpose: "ai_dashboard"}`, then sets `location.href` with `?sso=`. The blocked-window and failed-ticket toasts match Field Team's.
   - Logout: `notifyAiLogout()` posts `{type: "AUTH_LOGOUT"}` to a live `_aiWindow` at the dashboard origin; a user-initiated sign-out waits up to 3 s for `POST /auth/logout` (sent with `keepalive: true` where the browser supports it) before discarding the token, while a sign-out caused by a session rejection skips the call; the hidden frame uses `getAiDashboardUrl()`, and the port-5173 default leaves `AuthContext.jsx`. The desktop path (port 8451) is unchanged.
3. **Cold-start budgets** (2.20, 2.21, 3.16):
   - On the web, `login`, staff login and `signup` use `WEB_AUTH_BUDGET_MS = 65000` instead of the failover helper's 6 s default. After 4 s the form shows "Waking up the server… this can take up to a minute." A time-out says "The server did not respond. Check your connection and try again." The desktop keeps 8 s and its local-service message.
   - `Login.jsx` sends one `fetch(API_BASE + '/health', { mode: 'no-cors' })` on mount on the web, as a warm-up whose result is ignored.
   - Signup sends `X-Client-Request-Id`. After a time-out or network error it signs in with the same credentials: success continues exactly as a successful signup (template and token steps); 401 retries the signup once with the same request id; anything else shows the server's message.
4. **Error mapping** (2.22): `api/httpErrors.js` exports `readableError(status, contentType, bodyText)` and `retryDelayMs(attempt, retryAfter)`.
   - HTML or other non-JSON bodies for 429, 500, 502, 503 and 504 become short messages: "The server is busy. Trying again…", "The server is starting. Trying again…", "The server took too long to respond."
   - `request()` and `authFetch` retry GET, HEAD and requests that carry `X-Client-Request-Id` on 429, 502, 503, 504 and network errors: at most three times within 60 s, honouring `Retry-After` up to 30 s.
   - None of these statuses signs the user out.
5. **Sign-out rule** (2.28, 2.30, 3.1): `isSessionRejection(res)` is true when the response comes from the current API base and `WWW-Authenticate` contains `invalid_token`.
   - A marked 401 or 404 signs out, as today.
   - An unmarked 401 from the own backend triggers one `POST /auth/refresh`: a 401 from refresh signs out (this keeps a rolled-back API without the marker working); otherwise the request is retried once and the session stays.
   - Every other 401 or 404 shows its error and keeps the session. `fetchProfile`, `fetchSettings` and the business-config fetch follow the same rule.
6. **Sliding refresh** (2.29): `useSessionRefresh(token)` runs on the web only. Every 5 minutes and on `focus` or `visibilitychange` it reads `exp` (unverified decode) and calls `POST /auth/refresh` when fewer than 6 h remain. The new token goes through `tokenStorage` and a `storage` event reaches the other tabs. Network errors and 5xx retry on the next tick.
7. **Plan gates and preview** (2.7, 2.27, 2.56, 3.9, 3.14):
   - `planKnown = typeof settings?.subscription?.plan === 'string'`; `gate(name) = planKnown && (subscription.gates?.[name] ?? legacyGate(name))`, where `legacyGate` keeps today's rule for a server without `gates`.
   - `EXTERNAL_APPS` entries name their gate (`field_team` or `ai`); `handleOpenExternal` and the PRO badges use `gate(app.gate)` instead of `aiGated`. The preview lock uses `gate('web_preview')` instead of `isFreePlan`. Cashiers and supply adders still return early (3.14).
   - The timer key becomes `bizassist_preview_start:<BizID>:<userId>` in sessionStorage. Login, logout and account switch remove every key with that prefix and the legacy `bizassist_session_start_time`. The timer starts only when `gate('web_preview')` is true and the trial-ended screen is not due; the desktop still never locks (3.8).
   - `fetchSettings` retries after 2, 4, 8, 16 and then every 30 s, and on `focus` and `online`; `planKnown` stays false meanwhile.
8. **Login and registration** (2.17 to 2.19, 2.23 to 2.26):
   - `Login.jsx` drops the `/api/biz_id/check` effect, `bizLookup` and `noBizFound`. `handleOwnerContinue` goes straight to the credential step, and a failed sign-in shows one message: "Wrong username or password." The desktop's cloud-verified recovery inside `login` is unchanged.
   - `Register.jsx` drops the live username check; a taken username is reported from the signup response, which comes from the cloud on the desktop.
   - CSS in `index.css`: one `.login-card` rule (`width: 100%; max-width: var(--login-card-width, 420px); box-sizing: border-box`), a `.login-card--wide` modifier (440 px) for Register, and `.login-footer` using the same width so its edges line up with the card.
   - `.login-container`: `width: 100%` instead of `100vw`; `min-height: 100vh` followed by `min-height: 100dvh`; `overflow-y: auto`; a column flex layout with `justify-content: flex-start`. The card wrapper uses `margin-block: auto`, which centres the card when it fits and keeps its top reachable when it does not.
   - The "⚙ System check" trigger moves inside the login container; its panel uses the modal layer above it.
   - The decorative backdrop uses a `.login-backdrop-grid` class with 4, 2 and 1 columns at 1024 px and wider, 600 px and wider, and below. The inline layout styles in `Login.jsx` and `Register.jsx` move to classes.

#### C10. Field Team web app (1.2 to 1.4, 1.8; 2.2 to 2.4, 2.8; 3.7, 3.18, 3.19)

**Files**: `frontend-task/src/lib/theme.js`, `src/lib/auth.jsx`, `src/lib/api.js`.

1. **Trust list** in `theme.js`: `DEFAULT_BILLING_ORIGINS = ['https://staterbill.com', 'https://www.staterbill.com', 'https://bizassist-billing.vercel.app']`. `sanitizeBillingUrl` accepts these, every origin in the comma-separated `VITE_BILLING_URL`, and local hosts on ports 5174 and 8450, as today. `BILLING_CLOUD_URL`, the fallback for "Back to Billing" and Register links, becomes https://staterbill.com. Appearance tokens are still sanitized (3.19).
2. **Launch without a ticket** in `auth.jsx`: for a trusted origin, the existing path already clears the stored session and shows a notice; the trust fix extends it to staterbill.com and www (2.3). The notice names the business: "Sign in with the Billing account for <BizID> to continue." The different-business guard in `startBillingBridge` is unchanged.
3. **Connection messages** in `api.js`: a failed fetch while `navigator.onLine === false` keeps "No connection — check mobile data / Wi-Fi."; otherwise the message is "Could not reach the Field Team server. It may be starting up." (2.4).
4. **Exchange retry**: `POST /api/auth/exchange` gets a 70 s timeout and retries network errors and 429, 502, 503 and 504 after 2, 4 and 8 s while showing "Field Team is starting…". The retry window is `exp - iat + 10` seconds (legacy tickets: 30) from the moment the page started, using the ticket's own fields, so a wrong phone clock does not shorten it.

#### C11. AI dashboard and admin console web apps (1.13, 1.15, 1.31, 1.45, 1.50; 2.13, 2.15, 2.31, 2.45, 2.50)

**Files**: `frontend-ai/src/utils/handoff.js`, `frontend-ai/src/contexts/AuthContext.jsx`, `frontend-admin/src/utils/handoff.js`, `frontend-admin/src/contexts/AuthContext.jsx`, `frontend-admin/src/pages/admin/AdminLogin.jsx`, the Infrastructure page and its stylesheet.

1. **Trust list**: `trustedHandoff` accepts `window.location.origin`, the three default Billing origins, every origin in the comma-separated `VITE_BILLING_URL`, and the existing local rule. The `event.source === opener` check is unchanged (3.7).
2. **AI dashboard**: a failed `?sso=` or `SSO_TICKET` redemption calls `clearSession()` and shows "Billing could not sign you in. Open Dashboard BIZASSIST from Billing again, or sign in here." with a sign-in button (2.15). A marked 401 clears the session (2.14, 3.1). Errors use the same `readableError` mapping as Billing.
3. **Admin SSO** (2.50): after `/redeem-ticket` returns `role === 'admin'`, the console calls new `GET /admin/session` (it runs `svc.require_admin`, 3.17) and sets `adminUser` only when that returns 200. `?logout=true` removes `user`, `admin_user`, `biz_name` and every stored token.
4. **Admin session** (2.31): `authFetch` signs out only on a marked 401. `useSessionRefresh` refreshes the admin token within 6 h of expiry and on focus; if refresh fails, a banner warns 10 minutes before expiry. Before any redirect to `/admin/login` the current path goes to sessionStorage, and `AdminLogin` returns to it when it is a same-origin path under `/admin/`, otherwise to `/admin/dashboard`.
5. **Infrastructure page** (2.45):
   - No invented values: each missing metric shows "unavailable".
   - The error banner shows the HTTP status and `detail`, with the console's existing retry button.
   - Auto-refresh is off by default, with an opt-in 60 s interval that pauses while `document.hidden` and skips a tick while a request is in flight.
   - Remove the unused `useDialog` import, replace "alert-triangle" with an icon that the icon map defines, and add the `@keyframes` rule for `.spinning`.

#### C12. Admin API (1.43 to 1.49; 2.43 to 2.49; 3.3, 3.17)

**Files**: `backend/routes/admin.py`, `backend/services/admin_service.py`, `backend/core/sync/tenant_scope.py`, `backend/services/router_mode.py`, `backend/routes/feedback.py`, `backend/requirements_hf.txt` (or whichever file `backend/Dockerfile` installs), root `requirements.txt`, `backend/database/models.py`, a new Alembic revision.

1. **Metrics** (`get_admin_infrastructure_metrics`, 2.43, 2.44):
   - `psutil` is declared in the image's requirements and the root requirements, and imported once at module level inside `try`. Without it, process metrics are `null` and listed in `unavailable`.
   - A module-level `psutil.Process()` is primed with `cpu_percent(None)` at import, so later readings are real.
   - Row counts come from `SELECT relname, reltuples::bigint FROM pg_class WHERE relname IN (...)`. These are catalog estimates and read no tenant rows, so no `ALLOWED` entry is needed. Negative estimates (never analysed) and SQLite give `null`.
   - Probes of https://staterbill.com and the Field Team API run concurrently with a 2 s timeout each. The Hugging Face probe runs only when `HF_STANDBY_URL` is set.
   - Region comes from `CLOUD_RUN_REGION`, which the deploy scripts set, else `null`.
   - The whole response is cached in process for 45 s; `?refresh=1` bypasses the cache at most once per 10 s.
2. **Errors** (2.46): `get_rate_limits` and `get_all_usage_stats` get the `except Exception` → `HTTPException(500)` pattern of the other admin routes, so the error passes through CORS as JSON.
3. **Query counts** (2.47): `list_businesses`, `sync_doctor` and the usage stats compute each metric with one grouped query over all businesses (`GROUP BY business_id`) and join the results in Python. New `GET /admin/businesses/{id}` returns one fleet row, the sync doctor accepts `?business_id=`, and `business_details` takes `section`, `limit` (default 50, maximum 200) and `offset` and returns `has_more`. The detail page uses these instead of loading the fleet. Functions that change or move update their `tenant_scope.ALLOWED` entries with the same justification, because the guard rejects stale entries (3.3).
4. **Durable state** (2.48):
   - Router mode: new `platform_settings` (`key` PK, `value`, `updated_at`, `updated_by`). `set_mode()` writes it and updates the local cache at once; `get_mode()` reads it through a 30 s cache and falls back to the `LLM_ROUTER` variable when no row exists; `reset_mode()` deletes the row. When the table cannot be read, the in-process value applies, as today.
   - Log archives: new `client_log_archives` (`id`, `business_id`, nullable `feedback_id`, `kind`, `filename`, `content` as LargeBinary, `size`, `created_at`). `submit_merchant_feedback` and the daily log upload keep the existing upload bound. The newest 5 archives per business and 200 MB in total are kept, deleting the oldest first. `/admin/feedback/logs/{id}` and `/admin/business-logs/{id}` stream from the table, with files on instance disk as a read fallback for rows written before this release.
   - Audit: admin mutations write `action_logs`, which the read path already prefers; the JSONL fallback is labelled "this instance only".
   - Views that describe one instance (`cache-stats`, `flush-all-cache`, `server-log`) return `instance: {service, revision, started_at, boot_id}`; `server-log` also returns a Cloud Logging filter for the service, for the full log tail.
   - Admin readers of the new tables get `tenant_scope.ALLOWED` entries; nothing outside admin routes reads them across tenants.
5. **Admin database role** (2.36, 2.49): the privileged runtime stays for this release, so the console works without `ADMIN_SERVICE_URL`. The deploy scripts mount `ADMIN_SERVICE_URL` from Secret Manager when the secret exists, which keeps the console working if the runtime later moves to a constrained role.

#### C13. Deploy scripts, release check, configuration and documentation (1.9, 1.10, 1.49, 1.51 to 1.56; 2.9, 2.10, 2.49, 2.51 to 2.56; 3.10, 3.21)

1. **Billing deploy scripts** (`backend/deploy_cloudrun.sh` and `deploy_cloudrun.ps1`, same settings in both):
   - `--min-instances` as a parameter (default 0), `--max-instances 1`, `--timeout 120`.
   - `--update-env-vars`: `ADMIN_API_ENABLED=1`, `TZ`, `BIZ_TIMEZONE`, `WEB_CONCURRENCY=1`, `SUBSCRIPTION_ENFORCED=0` (parameter), `CLOUD_RUN_REGION=<region>`, `SSE_MAX_STREAM_SECONDS=100`, and `ALLOWED_ORIGINS` set to https://staterbill.com, https://www.staterbill.com, https://admin.staterbill.com, https://bizassist-billing.vercel.app, https://bizassist-task.vercel.app and https://bizassist-dev-workspace-ai.vercel.app. There is no localhost entry, no team.staterbill.com or ai.staterbill.com, and no hf.space.
   - `--update-secrets`: `DATABASE_URL`, `JWT_SECRET`, `BILLING_CRON_SECRET`, and `ADMIN_SERVICE_URL` when that secret exists. Variables and secrets that the script does not manage are kept (2.49).
   - Rollout: deploy with `--no-traffic --tag rc`, poll `https://rc---<service host>/health` for up to 120 s (expects 200 and `status: ok`), then `gcloud run services update-traffic --to-latest`. Any failure exits non-zero and leaves traffic on the previous revision.
   - `--setup` creates `BILLING_CRON_SECRET` when it is missing and creates or updates the Cloud Scheduler jobs of C8.
2. **Billing CORS defaults**: `_default_origins` in `main_groq.py` holds the production list plus the other current vercel.app origins (3.10), and the environment list is unioned with it, as in the Field Team API. team.staterbill.com, ai.staterbill.com and the hf.space origin leave the defaults (2.53).
3. **build-info.json**: each frontend gets a small Vite plugin that writes `dist/build-info.json` with `app`, `commit` (`VERCEL_GIT_COMMIT_SHA`), `built_at` and the resolved `VITE_API_URL`, `VITE_FIELD_TEAM_URL`, `VITE_AI_DASHBOARD_URL`, `VITE_BILLING_URL` and `VITE_PUBLIC_WEB_URL`. These are public URLs only; every other cross-app URL default becomes the production host (2.54).
4. **Release check** (`dev/check_cloud_release.py`):
   - Defaults: the Cloud Run billing and Field Team APIs, https://staterbill.com, https://www.staterbill.com, https://bizassist-task.vercel.app, https://bizassist-dev-workspace-ai.vercel.app, https://admin.staterbill.com and the forwarder.
   - The first request to each API may take up to 75 s (cold start); later requests use normal timeouts.
   - It fails on a redirect to `vercel.com/login` or `vercel.com/sso-api`, a TLS error, a missing Field Team readiness field, or a build-info.json URL that is not the production host.
   - Shared secrets: if both services mount the same Secret Manager secret and version for `JWT_SECRET` and for `DATABASE_URL` (read with `gcloud run services describe`), they match. Otherwise it compares SHA-256 digests of the values, read with `gcloud secrets versions access` or passed by the operator as `--jwt-sha256-billing` and `--jwt-sha256-field`. It prints only "match" or "mismatch" (2.9, 3.21).
   - With `--owner-token`, it mints a `field_team` ticket and exchanges it at the Field Team API as an end-to-end proof.
5. **Landing page** (`bizassist-landing/src/App.jsx`): Terms, Privacy, Refunds and Contact link to https://staterbill.com/terms, /privacy, /refund-policy and /contact (2.51).
6. **Documentation** (2.55): `.env.example`, `backend/README.md` and the setup documents describe Cloud Run and staterbill.com. A new runbook, `docs/runbooks/cloud-run-migration.md`, lists the operator steps in order, each with a verification command: www.staterbill.com domain and certificate (2.52); Deployment Protection off for the production AI dashboard (2.11); the per-project `VITE_*` values (2.54); the Field Team API redeploy (2.9); shared `JWT_SECRET` and `DATABASE_URL`; `SUBSCRIPTION_ENFORCED`; `BILLING_CRON_SECRET` and the Scheduler jobs; the forwarder (2.33); optional `--min-instances 1`; optional custom subdomains with their DNS.

### Backward Compatibility and Deploy Order

Deploy order: Field Team API → billing API → HF forwarder → frontends → desktop release.

| Step | Why it comes here | Compatibility |
|---|---|---|
| 1. Field Team API | It must accept 90 s `field_team` tickets before the billing API mints them; the deployed revision refuses tickets that live longer than 60 s. | Accepts today's 30 s tickets without `aud`. |
| 2. Billing API | The frontends need `purpose`, `gates`, the marker, `/auth/logout`, rotation and replay. | Old bundles send no `purpose` and get 30 s legacy tickets. They ignore `gates`, `WWW-Authenticate`, `id:` and `event: rotate`, so their streams reconnect as today, every 100 s instead of 120 s, until step 4. The removed lookup routes return 404, which the old Login page treats as "no result" and does not block. |
| 3. HF forwarder | Old desktop apps reach the new billing API. | Pure pass-through. |
| 4. Frontends | Billing, Field Team, AI dashboard, admin console, landing page. | Against a rolled-back API: an unmarked 401 is resolved by one refresh, a missing `gates` uses `legacyGate`, and a stream without rotation is handled as a drop. |
| 5. Desktop release | The bundled backend uses the resolver, the shell passes `CLOUD_API_URL`, and `cloudTicket()` asks for 90 s tickets. | Older installs keep working through the forwarder. |

All new tables are additive, and older revisions ignore them. The transition items are removed in the following release: tickets without `aud` (redeemers then require it and `/handoff-ticket` requires `purpose`), `legacyGate`, the disk fallback for log archives, and the forwarder once installs have updated (assumption 6).

### Risks and Rollback

| Risk | Mitigation | Rollback |
|---|---|---|
| The Field Team API is rolled back after step 2 and refuses 90 s tickets. | `HANDOFF_TTL_FIELD_TEAM` is configurable. | Set it to 55 on the billing API. |
| The first boot of a new revision runs the full migration and takes table locks. | `lock_timeout` 5 s with retries; the revision gets traffic only after the tagged health check passes. | Traffic stays on the previous revision; fix and redeploy. |
| The signature hides a backfill-only change. | `K_REVISION` changes on every deploy; `MIGRATION_REVISION` covers local development. | Set `BIZASSIST_FORCE_MIGRATIONS=1` and restart. |
| A seed statement over a large table runs long on a release boot. | Set-based statement on the event-key index; Cloud Run's default startup probe allows 240 s. | As for the second row. |
| During a revision switch two instances run for up to 100 s, so an event published on one misses streams on the other. | Streams rotate within 100 s, and the new epoch triggers one `sync.reconnect`. | None needed. |
| The Field Team API's spent set is in memory, so a captured ticket could be redeemed again within 105 s after a Field Team restart. | Restarts are rare and the window is one ticket lifetime. | Add an `ft_spent_tickets` table through the ft_* Alembic chain if needed. |
| IP-based login limits see the forwarder's address for old desktop installs. | Confirm that the API reads `X-Forwarded-For`; old desktops call `/login` only for fresh-device recovery. | Raise the limit for that address or restore the Space. |
| A cron job keeps exceeding its 95 s budget. | Partial runs resume from the cursor through Scheduler retries. | Run it with the runbook command, or move it to a Cloud Run Job. |
| Database growth from archives, spent tickets and revoked sessions. | Caps and purges (C4, C12); the weekly maintenance job reports sizes. | Lower the caps. |
| A frontend regression. | build-info.json and the release check. | Promote the previous Vercel deployment. |
| A billing API regression. | Tagged rollout. | `gcloud run services update-traffic staterbill-api --to-revisions <previous>=100`. |
| The forwarder misbehaves. | `/__forwarder` and `/health` checks in the runbook. | Revert the Space commit. |

## Testing Strategy

### Validation Approach

Validation runs in two phases. First, tests that encode the expected behaviour run against the unfixed code and must fail, which confirms each root cause or sends it back for a new hypothesis. Second, the same tests must pass on the fixed code while the existing suites still pass. Most clauses have a backend test. Frontend and layout tests are written here, and the user runs them locally, because vitest and Playwright cannot run in the agent sandbox.

`hypothesis` is not installed in the Python 3.12 interpreter that runs the suite (checked with `import hypothesis`), and no frontend depends on `fast-check`. Property-style tests are therefore parametrized: `pytest.mark.parametrize` over `itertools.product` tables, generators driven by `random.Random(seed)` with fixed seeds, and `it.each` tables in vitest. No dependency is added.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Add the tests below and run them on the unfixed code. Two counterexamples already exist in the baseline: `test_session_invalidation.py::test_staff_cannot_run_owner_sync_pull_or_discover_accounts_anonymously` (1.17) and `test_tenant_scope.py::test_no_unscoped_tenant_reads` (1.44).

**Test Cases** (billing backend, `backend/tests/`):
1. **Endpoint default** (`test_cloud_endpoint.py`): with the four variables removed, the resolved URL is the Cloud Run default (will fail on unfixed code: hf.space). `test_no_retired_host_defaults.py` scans `backend/`, `desktop/src/`, `dev/`, `scripts/` and the frontend `src/` trees for hf.space and bizassist-billing.vercel.app defaults, ignoring comments and test files, outside an explicit allow-list of transition trust lists, the forwarder and documentation (will fail).
2. **Tickets** (`test_handoff_ticket_purpose.py`): a `field_team` purpose gives a 90 s ticket with `aud`; `/redeem-ticket` refuses an `aud=field_team` ticket; a ticket minted before a token-version bump is refused with 401 (will fail: 200).
3. **Durable single use** (`test_spent_tickets_durable.py`): redeem, clear `_used_tickets` to simulate a restart, redeem again; expected `already_used` (will fail).
4. **Marker** (`test_session_rejection_marker.py`): an expired or revoked token gets 401 with `WWW-Authenticate: Bearer error="invalid_token"`, and the CORS response exposes it (will fail).
5. **Dashboard logout** (`test_logout_revokes_dashboard.py`): login, `ai_dashboard` ticket, redeem, `POST /auth/logout` with the Billing token, then the dashboard token gets a marked 401 (will fail: no route, token still valid).
6. **Boot work** (`test_boot_fast_path.py`): a `before_cursor_execute` listener counts statements. On SQLite, `install_change_feed` issues one existence SELECT per row (will fail). On Postgres (testcontainers, skipped without Docker), a second `run_migrations_and_seed()` issues CREATE, DROP or ALTER statements (will fail).
7. **Error handling** (`test_change_feed_errors.py`): an injected `OperationalError` with `pgcode = "40P01"` raises `NameError` from the handler (will fail), and an error whose message contains "transaction block" is logged as "peer completed" (will fail).
8. **Streams** (`test_sse_rotation_replay.py`): with `SSE_MAX_STREAM_SECONDS=1`, the stream ends with `event: rotate`, frames carry `id:`, and a reconnect with `last_event_id` replays the missed events (will fail).
9. **Listener** (`test_cloud_listener_timeouts.py`): the stream timeout has `read=45`, and the backoff returns to the base after an established stream drops (will fail).
10. **Sync worker** (`test_sync_worker_cold_cloud.py`): an HTML 503 with `Retry-After: 120` gives `busy` and no attempt before 120 s; a probe time-out gives `waking`; refresh starts 12 h before expiry and retries after 1 minute (will fail).
11. **B2B proxy** (`test_b2b_proxy_cold_cloud.py`): an upstream 503 on a read serves the mirror; an upstream 401 on a write returns 424 (will fail: passthrough).
12. **Cron** (`test_internal_cron.py`): with `K_SERVICE` set, `start_scheduler()` registers no cron job (will fail); the endpoint returns 404, 403 and `already_ran` as designed.
13. **Admin errors** (`test_admin_routes_json_500.py`): `svc.require_admin` is patched to raise `RuntimeError`, and every `/admin/*` route must answer a JSON 500 with `access-control-allow-origin` for an allowed origin (will fail for rate-limits and usage-stats).
14. **Metrics** (`test_infrastructure_metrics.py`): with `sys.modules["psutil"] = None`, the endpoint returns 200 and lists process metrics as unavailable; no Hugging Face probe without `HF_STANDBY_URL` (will fail).
15. **Durability** (`test_discovery_persistence.py`, `test_router_mode_persisted.py`, `test_feedback_archive_durable.py`): register, set the mode or upload an archive, clear the in-process state or delete the disk file, then read again (will fail).
16. **Gates** (`test_settings_gates.py`): with `SUBSCRIPTION_ENFORCED=0`, a free account gets `web_preview` and `field_team` true and `hybrid_sync` false; a Pro account gets all false (will fail: no `gates`).

**Test Cases** (Field Team backend, `backend-task/tests/`):
17. **Refusal reasons** (`test_ticket_refusal_reasons.py`): a bad signature, an expiry, a reuse and a wrong audience each return their own message; a 90 s ticket redeemed at 100 s is accepted (will fail: one message, 90 s refused).
18. **Boot** (`test_boot_skips_upgrade_at_head.py`): with the database at head, `alembic.command.upgrade` is not called (will fail).
19. **Origins** (`test_default_origins.py`): without `ALLOWED_ORIGINS`, https://bizassist-task.vercel.app is allowed, and an environment list is added to the defaults (will fail).

**Test Cases** (frontends, run locally by the user):
20. **Billing** (`frontend-billing/src/__tests__/`): `aiDashboardOpen.test.js` (`window.open` is called before the ticket promise resolves), `fieldTeamLaunch.test.js` (production URL without `VITE_FIELD_TEAM_URL`, toasts for a blocked window and a failed ticket), `planGates.test.jsx` (no Pro alert or timer while settings are null; per-BizID key reset on login and logout), `sessionRejection.test.js` (unmarked 401 and 404 keep the session, marked 401 ends it, HTML 503 becomes text and retries after `Retry-After`), `realtimeRotate.test.js` (silent reconnect on rotate, `sync.reconnect` only on gap, no toast within 30 s), `authBudget.test.js` (65 s budget, waking message at 4 s, login fallback after a signup time-out). All will fail.
21. **Field Team** (`frontend-task`): `theme.test.js` trusts staterbill.com, www and a comma list and falls back to https://staterbill.com; `api.test.js` covers the online-failure message and the exchange retry window (will fail).
22. **AI dashboard and admin console**: `handoff.test.js` accepts the three default origins only from the opener; the admin `authContext.test.jsx` sets `adminUser` only after `GET /admin/session`, clears both sessions on `?logout=true`, and keeps the return path (will fail).
23. **Layout** (Playwright, `frontend-billing/e2e/login-layout.spec.js`): at 360×640, 844×390, 768×1024 and 1366×768, the card top is reachable after scrolling to the top, `scrollWidth <= innerWidth`, the footer edges are within 1 px of the card edges, and `elementFromPoint` at the System check centre is the trigger. Screenshots are saved for review (will fail).

**Expected Counterexamples**:
- The hf.space default in the sync worker, B2B proxy, relay, discovery, telemetry and desktop shell.
- A 30 s ticket refused at 52 s; one message for every refusal; a 200 from `/redeem-ticket` after a force logout.
- As many existence queries as rows during the change-feed install, `NameError` in its handler, and "block" classified as a lock error.
- Streams without rotation or ids; a listener with `read=None` and a backoff that never resets.
- `offline` for an HTML 503; a pass-through 401 for a B2B write; cron jobs registered in-process on Cloud Run.
- Plain-text 500s without CORS; `window.open` after an `await`; a Pro alert with unknown settings; sign-out on an unmarked 401 or 404; staterbill.com untrusted by Field Team.
- Possible causes beyond the hypotheses: a different 401 source than `get_active_user`, or an image that does install psutil (then 1.43 is configuration only).

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL X WHERE isBugCondition(X) DO
  result := F'(X)
  ASSERT expectedBehavior(X, result)
END FOR

// Component instances, each a parametrized test:
FOR ALL (env) DO ASSERT resolve_cloud_url(env) = firstValid(env, ORDER) OR DEFAULT END FOR
FOR ALL ticket cases t DO ASSERT verify(t).reason = oracleReason(t) END FOR
FOR ALL responses r DO
  ASSERT signsOut(r) = (ownBase(r) AND (marked(r) OR (r.status = 401 AND refreshReturns401(r))))
END FOR
FOR ALL stream histories h, cuts c DO ASSERT delivered(h, c) = h OR gapSignalled(h, c) END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT F(X) = F'(X)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain
- It catches edge cases that manual unit tests might miss
- It provides strong guarantees that behavior is unchanged for all non-buggy inputs

Here the generation is parametrized, as explained above. Where the original function can run in the test, the check is differential: the per-row seeder of F is copied into the test module as `_reference_seed`, and both seeders run on the same seeded fixtures.

**Test Plan**: Observe the behaviour of the unfixed code first for warm-cloud, desktop and transition-host interactions, then pin it in tests. The full existing suites are the main preservation check.

**Test Cases**:
1. **Sessions and outages (3.1)**: the existing revocation and 503 tests pass; marked 401s still sign out in Billing.
2. **No discovery (3.2)**: `GET /staff-counters?owner=` stays 404; a route-inventory test fails when an unauthenticated route that returns account fields is added.
3. **Tenant scope (3.3)**: `test_tenant_scope.py` passes with the updated `ALLOWED` entries and still rejects a stale entry.
4. **Identity and Local-only (3.4)**: `test_local_only_stays_local` and the cross-database identity tests pass unchanged.
5. **Tickets (3.5, 3.6, 3.18)**: `backend-task/tests/test_billing_contract.py` still accepts 30 s tickets without `aud`; staff tickets still get 403, pre-logout tickets 401, and non-Pro businesses 402 with the current messages.
6. **Message trust (3.7, 3.19)**: messages from a non-opener or an unlisted origin are refused for every generated origin; appearance tokens with `url(` are dropped.
7. **Routing and desktop (3.8, 3.15, 3.16)**: localhost and LAN hosts resolve to the local backend; desktop sign-in still fails within 8 s with the local-service message; the desktop opens 127.0.0.1:8451.
8. **Free plans (3.9, 3.14)**: with fake timers, a known free plan locks after 5 minutes, a lapsed trial shows the trial-ended screen, a known non-Pro plan shows the PRO badges, and cashiers see neither app.
9. **Transition hosts (3.10)**: CORS and every trust list accept https://bizassist-billing.vercel.app and the other current vercel.app origins.
10. **Local start-up and replication (3.11, 3.12)**: on SQLite, two `run_migrations_and_seed()` calls both run the backfill steps; the constrained-runtime refusal still raises "Database migration required"; the new seeder produces the same `(business_id, entity, row_uid)` set and per-business revision counts as `_reference_seed`.
11. **Warm cloud (3.13)**: B2B pass-through, the mirror on network errors and stale tokens, and the "B2B is offline" 503 behave as the existing B2B tests expect.
12. **Admin (3.17)**: admin routes return 404 without `ADMIN_API_ENABLED`, re-check authority, audit mutations, and 2FA sign-in works.
13. **Streams (3.20)**: the 21st connection gets 429 and a revoked session's stream closes.
14. **Secrets (3.21)**: `caplog` records from ticket refusals, the cloud resolver and the release check never contain the test `JWT_SECRET` or `DATABASE_URL` values.

### Unit Tests

- `resolve_cloud_url` and `resolveCloudApiUrl`: order, trimming, invalid values, the retired-host warning.
- `verify_ticket` and `redeem_billing_ticket`: every reason in the C3 table, leeway edges at `exp + 15` and `exp + 16`, lifetime 120 against 121.
- `_session_claims`, `refresh_session` (keeps `sid` and `psid`) and `get_active_user` (checks `revoked_sessions` only with `psid`).
- `_subscription_view` gates; `legacyGate` and `gate()` in Billing.
- `compute_schema_signature`, `_sqlstate` for psycopg2 and psycopg 3 errors, `_change_feed_installed`.
- `RealtimeManager.subscribe_from` statuses (`none`, `complete`, `gap`) and identity-based sequence lookup with duplicate coalescing.
- `retryDelayMs` and the Python `Retry-After` parser: seconds, HTTP dates, garbage, values above the cap.
- `cron_runner.run`: claim, `already_ran`, lease takeover, `partial` with cursor.
- `readableError`, `isSessionRejection`, the exchange retry window in Field Team.

### Property-Based Tests

- **Cloud URL**: the product of the four variables over {unset, "", "  ", "https://a.example/", "not a url", "https://x.hf.space"} (1,296 cases) against an oracle that takes the first valid value in order.
- **Tickets**: signature {valid, invalid} × age {0, 30, 89, 104, 105, 106, 200} × lifetime {30, 60, 90, 120, 121} × `aud` {none, field_team, ai_dashboard, admin_console, sse} × `iat` {present, absent} × spent {no, yes}, checked against an oracle that implements the C3 order, for the Field Team API and for each billing redeemer's audience set.
- **Origins**: candidate origins (staterbill.com, www, the old vercel.app host, look-alikes such as `https://staterbill.com.evil.example` and `http://staterbill.com`, local ports 5174, 8450 and 3000, a LAN address) × `VITE_BILLING_URL` lists × source {opener, other window}.
- **Sign-out rule**: status {200, 401, 403, 404, 429, 500, 503, 504} × marker {present, absent} × origin {own base, other} × body {JSON, HTML}.
- **Gates**: plan {pro, free, missing} × status {trial, active, none} × `SUBSCRIPTION_ENFORCED` {0, 1} × role {owner, staff, cashier, supply adder, admin} for the server flags and the client decision.
- **Seeding**: 25 fixed seeds generate businesses, parent, child and B2B rows and a random subset of existing events; after two installs each (business, entity, UID) appears exactly once, and the differential check of preservation case 10 holds.
- **Replay**: fixed seeds generate broadcasts over three businesses with buffer sizes 4 and 256, random cut points and restarts; the delivered sequence equals the broadcast sequence without duplicates, or `gap` is reported exactly when the buffer cannot cover the cut.
- **Cron**: fixed seeds generate interleaved deliveries, retries and lease expiries for one period; exactly one run ends `done`, and the cursor never moves backwards.
- **Layout**: the four required viewports plus 320×568 and 1920×1080 (Playwright, locally).

### Integration Tests

- Billing API in process: login, `ai_dashboard` ticket, redemption, a dashboard request, `POST /auth/logout`, then a marked 401 for the dashboard.
- Cross-service ticket vector: a `backend-task` test mints a `field_team` ticket with billing's `create_sse_ticket` (as `test_billing_contract.py` does) and redeems it at 100 s with a frozen clock.
- SSE through the TestClient: rotation, reconnect with `last_event_id`, and replay; a new `RealtimeManager` (restart) yields `gap`.
- Cron through the endpoint with a small budget: `partial`, then a retry that finishes from the cursor.
- Playwright, locally: the login layout, and a Field Team launch with pop-ups blocked that shows the toast and keeps the anchor working.
- After deployment (operator, from the runbook): `python dev/check_cloud_release.py`, `GET /api/sync/status` on a packaged desktop app showing the Cloud Run URL, and `curl` through the forwarder for `/health` and a ticketed stream.

### Running the Suites

Every run uses parallel mode:
- Billing backend, from `backend/`: `$env:GROQ_API_KEY='mock_groq_api_key'; python -m pytest tests/ -q -n auto --dist loadscope`
- Field Team backend, from `backend-task/`: `python -m pytest tests/ -q -n auto --dist loadscope`
- Frontends, run by the user on the developer machine from `frontend-billing`, `frontend-task`, `frontend-ai` and `frontend-admin`: `npx vitest run --pool=threads --reporter=dot`; also `npm run lint` in `frontend-admin`, and `npx playwright test e2e/login-layout.spec.js` in `frontend-billing`.
- `run_tests.ps1` is never used in automation, because it starts a dashboard server and waits for input.
- `test_intent_router.py::test_semantic_router_eval_accuracy` fails only where huggingface.co is unreachable and is exempt there (3.22).
- New modules follow the existing test headers (`DATABASE_URL` on SQLite, a mock `GROQ_API_KEY`, `CLOUD_API_URL=http://127.0.0.1:9`) and reset module state (`realtime_manager`, `_REGISTRY`, `_used_tickets`, caches) in fixtures, so `-n auto --dist loadscope` stays isolated. Postgres-only tests use the existing testcontainers setup and skip without Docker.
- Target after the fix: the 2,526 passing billing tests plus the new ones, the two regression tests fixed, the full Field Team suite plus its new tests, and no failure other than the exempt semantic-router test.
