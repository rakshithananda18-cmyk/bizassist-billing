# Bugfix Requirements Document

## Introduction

The billing API moved from a Hugging Face Space to Google Cloud Run (`staterbill-api`, asia-south1), the billing web app moved to the new domain https://staterbill.com, and Field Team got its own Cloud Run service (`bizassist-task`). Since the move, users report unreliable sign-in, a Vercel "SSO" page, hand-off and stream time-outs, sync failures, unexpected sign-outs, admin console errors, and Field Team not opening from Billing. The investigation (code reading, live checks on 2026-11-07 and parallel test runs) traced these symptoms to old-host defaults that the move left behind, client and server code that assumes an always-warm single instance, regressions from commits 5700877 and 38b5244, and production configuration that is missing or reset by the deploy scripts. As the user asked, the document covers every finding. The report's "ssc time out" is read as both the hand-off (SSO) ticket time-out and the real-time (SSE) stream time-out.

**Terms.** *Billing* is the billing web app (https://staterbill.com) and the desktop app's renderer. *Billing API* is the `staterbill-api` Cloud Run service. *Field Team* is the Field Team web app (https://bizassist-task.vercel.app), and *Field Team API* is the `bizassist-task` Cloud Run service. *AI dashboard* is Dashboard BIZASSIST. *Admin console* is https://admin.staterbill.com. *Desktop app* is the Electron app with its bundled local backend. A *cold start* is a request that reaches a Cloud Run service while it is scaled to zero or still starting. A *hand-off ticket* is the short-lived, single-use sign-in ticket that Billing passes to Field Team or the AI dashboard; the admin console accepts these tickets too. The *real-time stream* is the server-sent-events connection used for live sync.

**Bug condition.** An interaction X (a request, page load, app launch, service boot or scheduled job) triggers this bug when C(X) holds:

```pascal
FUNCTION isBugCondition(X)
  INPUT: X, an interaction with the post-migration production system
  OUTPUT: boolean
  RETURN usesStaleOrMissingHost(X)     // Hugging Face, bizassist-billing.vercel.app or :5173 defaults, or a new origin missing from a list
      OR meetsColdStartOrTimeLimit(X)  // service scaled to zero or starting, or work longer than the 120 s (billing) or 60 s (Field Team) request limit
      OR dependsOnInstanceState(X)     // in-process or local-disk state while running on more than one instance, after a restart or after scale-to-zero
      OR decidesOnUnknownState(X)      // plan not loaded yet, or a 401/404 that does not reject the session
      OR hitsRegression(X)             // behaviour introduced by 5700877 or 38b5244
      OR dependsOnMissingConfig(X)     // CORS lists, ADMIN_SERVICE_URL, SUBSCRIPTION_ENFORCED, DNS/TLS, Vercel protection or build variables
END FUNCTION
```

Fix checking: for every X where C(X) holds, the fixed system F' behaves as the matching clause 2.k states. Preservation checking: for every X where C(X) does not hold, F'(X) = F(X), and every clause 3.k holds.

**Assumptions.** These are the recommended defaults for the open decisions. Each one is the user's call and can change before design.

1. Cold starts: both services keep `--min-instances 0` as the baseline, and every clause below must hold against a cold service that needs up to 60 seconds to start. Setting `--min-instances 1` on `staterbill-api` is recommended as an operator cost decision, but nothing relies on it.
2. Multiple instances: `staterbill-api` runs with `--max-instances 1` for this release, so in-process real-time fan-out stays correct. Raising the limit later needs a cross-instance channel first (Postgres LISTEN/NOTIFY on a session-mode connection).
3. URLs: Field Team stays at https://bizassist-task.vercel.app and the AI dashboard at https://bizassist-dev-workspace-ai.vercel.app for this release. team.staterbill.com and ai.staterbill.com are optional later; trust lists read the configured URLs, so switching is configuration only. A same-site ai.staterbill.com would also let a hidden frame on staterbill.com reach the AI dashboard's stored session, which browsers that partition third-party storage prevent for a vercel.app host.
4. `SUBSCRIPTION_ENFORCED` stays off in production for this release, and the billing deploy scripts set it explicitly so the value is visible. Clients follow the enforcement that the server reports for each gate.
5. The 5-minute web preview stays for genuinely free web accounts (plan known, not Pro, no active trial). The server reports this gate as on for those accounts independently of `SUBSCRIPTION_ENFORCED`. Pro accounts and sessions whose plan is not yet known never see it.
6. Hugging Face: the Space becomes a forwarder to the Cloud Run billing API, so already-installed desktop apps recover without a reinstall. The next desktop release switches to the new default, and the Space is retired once installs have updated.
7. A stable api.staterbill.com in front of Cloud Run is optional and not part of this release.

**Operator configuration.** Clauses tagged *(operator)* are met by configuration that the user performs, not by code: the Vercel domain and certificate for www.staterbill.com; Deployment Protection off for the production AI dashboard; per-project `VITE_API_URL`, `VITE_FIELD_TEAM_URL`, `VITE_AI_DASHBOARD_URL`, `VITE_BILLING_URL` and `VITE_PUBLIC_WEB_URL`; a Field Team API redeploy with its production origins; the same `JWT_SECRET` and `DATABASE_URL` on both services; min-instances; `SUBSCRIPTION_ENFORCED`; the Hugging Face forwarder; and DNS for any custom subdomain that is adopted.

**Verification.** Every test run uses parallel mode (user preference):

- Billing backend, from `backend/`: `$env:GROQ_API_KEY='mock_groq_api_key'; python -m pytest tests/ -q -n auto --dist loadscope`
- Field Team backend, from `backend-task/`: `python -m pytest tests/ -q -n auto --dist loadscope`
- Frontends, on the developer machine (needs node_modules), from each frontend directory: `npx vitest run --pool=threads --reporter=dot`
- `run_tests.ps1` is not used in automation, because it starts a dashboard server and waits for input.

Baseline before the fix: the billing suite had 2,526 passed, 27 skipped and 3 failed. Two failures are regressions covered by clauses 1.17 and 1.44. The third, `test_intent_router.py::test_semantic_router_eval_accuracy`, fails only because the sandbox cannot download its model from huggingface.co. The Field Team suite passed. The login layout findings (1.23 to 1.26) come from reading the code and still need visual confirmation.

## Bug Analysis

### Current Behavior (Defect)

#### A. Field Team from Billing

1.1 WHEN the billing web app is built without `VITE_FIELD_TEAM_URL` THEN the system hides the Field Team sidebar item and workspace switcher, and any other Field Team entry point returns without opening anything or saying why (the web fallback was removed in 38b5244).

1.2 WHEN Field Team is opened from https://staterbill.com or https://www.staterbill.com THEN Field Team rejects the Billing origin, because it trusts only https://bizassist-billing.vercel.app, one `VITE_BILLING_URL` and local ports 5174 and 8450; as a result the different-business guard is off, the appearance hand-off never starts, and "Back to Billing" and Register links point to https://bizassist-billing.vercel.app.

1.3 WHEN Field Team is opened from https://staterbill.com and no hand-off ticket arrives (the ticket request failed) THEN Field Team silently restores the session stored in that browser, which can belong to a different business.

1.4 WHEN the Field Team web app runs on an origin that is missing from the Field Team API's `ALLOWED_ORIGINS` THEN the CORS preflight for `/api/auth/exchange` fails and Field Team shows "No connection — check mobile data / Wi-Fi."; the built-in default lists only localhost origins, and the deploy script sets the list only when `-AllowedOrigins` is passed, otherwise keeping whatever the previous revision had.

1.5 WHEN the Field Team API is cold and its start-up (database preparation and a migration run on every cold start) plus the page load take longer than the 30-second ticket lifetime THEN the hand-off fails with "Sign-in link expired — open Field Team from BizAssist Billing again", because Billing mints 30-second tickets and the Field Team API refuses any ticket past its expiry with no leeway.

1.6 WHEN the Field Team API refuses a hand-off ticket THEN it returns the same "Sign-in link expired" message whether the ticket expired, failed its signature check (for example because the two services hold different `JWT_SECRET` values) or was already used, so neither the owner nor the operator can tell a time-out from a configuration fault.

1.7 WHEN `/settings` is still loading or has failed on the web THEN Billing treats the plan as free and shows Pro owners the "Pro plan feature" alert and PRO badges on Field Team and Dashboard BIZASSIST.

1.8 WHEN the browser blocks the Field Team window, the ticket request fails, or the owner middle-clicks the link or chooses "Open in new tab" THEN Billing gives no feedback (the blocked window is ignored and the ticket failure goes only to the browser console) or opens the bare Field Team URL with no sign-in hand-off.

1.9 WHEN the deployed Field Team API was checked on 2026-11-07 THEN its `/api/health` lacked `pro_required`, `billing_mirror` and `cloud_only`, which shows it runs an older revision than the repository, one that its own deploy readiness gate would reject; and nothing verifies that the two Cloud Run services share the same `JWT_SECRET` and `DATABASE_URL`.

1.10 WHEN the release check (`dev/check_cloud_release.py`) runs with its defaults THEN it probes the Hugging Face Space and https://bizassist-billing.vercel.app instead of the Cloud Run billing API and https://staterbill.com, and it does not check the AI dashboard, the admin console, www.staterbill.com or Vercel Deployment Protection.

#### B. SSO page and Dashboard BIZASSIST

1.11 WHEN an owner opens Dashboard BIZASSIST on the web THEN https://bizassist-dev-workspace-ai.vercel.app redirects to Vercel's sign-in page (Deployment Protection), so the owner sees a Vercel SSO page and the 30-second hand-off ticket expires in the meantime.

1.12 WHEN an owner opens Dashboard BIZASSIST on the web and the ticket request is slow (for example during a billing API cold start) THEN Billing calls `window.open` only after the ticket returns, outside the click, so the browser can block it as a pop-up and nothing opens.

1.13 WHEN the AI dashboard or the admin console receives a hand-off `postMessage` from https://staterbill.com, or the AI dashboard receives a logout `postMessage` from it, THEN it rejects the message, because its trusted Billing origin defaults to https://bizassist-billing.vercel.app unless `VITE_BILLING_URL` is set.

1.14 WHEN a web user signs out of Billing THEN the AI dashboard stays signed in: unless `VITE_AI_DASHBOARD_URL` is set, the hidden logout frame loads `http://<billing host>:5173/?logout=true`, which is blocked as mixed content on https://staterbill.com; a frame from another site cannot clear the dashboard's own storage in browsers that partition third-party storage; and the dashboard rejects the `AUTH_LOGOUT` message (1.13).

1.15 WHEN the AI dashboard cannot redeem its hand-off ticket (expired, rejected or network error) THEN it silently restores the session stored in that browser, which can belong to a different business, and shows no message.

1.16 WHEN a hand-off ticket minted before a force logout is redeemed at the billing API's `/redeem-ticket` (used by the AI dashboard and the admin console) within its lifetime THEN the billing API issues a fresh session, because it does not compare the ticket's token version with the account's current one; the Field Team API does compare them.

#### C. Login and registration

1.17 WHEN an unauthenticated client sends a username to `POST /api/biz_id/check` or `GET /api/auth/check-username` THEN the billing API reports whether the account exists, its business name, whether it is staff and the owner's username (account enumeration and business-name disclosure, added in 5700877), and `test_session_invalidation.py::test_staff_cannot_run_owner_sync_pull_or_discover_accounts_anonymously` fails because the route returns 200 instead of 404.

1.18 WHEN a user continues on the login page's "Other business" step THEN Continue is blocked with "No business found" whenever the lookup reports no match; on the desktop app the lookup asks the local backend, so on a fresh install every account that exists only in the cloud is blocked and the cloud-verified fresh-device recovery never runs; and Continue pressed within 300 ms of the last keystroke uses the previous keystroke's result.

1.19 WHEN a user registers on the desktop app THEN the username check shows "Available" or "Already registered" from the local database, although the account is created on the cloud first.

1.20 WHEN the billing API is cold and a user signs in, a staff member signs in or an owner registers on the web THEN the request is aborted after 6 seconds (the failover helper's default overrides the 8-second sign-in limit, and other authenticated requests stop at 12 seconds), and the page says "The sign-in service is not responding. Wait a moment, then restart BizAssist if it persists.", which is wrong advice on the web.

1.21 WHEN a registration request times out on the client after the server has already created the account THEN retrying reports that the username already exists, and the owner is left with no session.

1.22 WHEN the Cloud Run front end answers with an HTML error page (429, 500, 503 or 504 during a cold start, at capacity or at the request limit) THEN the web apps show the raw HTML or a generic failure as the error text and do not retry.

1.23 WHEN the login card plus its footer are taller than the viewport (phones, landscape, browser zoom, the "No business found" box, the migration note) THEN the top of the card is cut off and cannot be scrolled to, the 100vh height hides the bottom behind mobile browser toolbars, and the 100vw width adds a horizontal offset the width of the scrollbar.

1.24 WHEN the login page renders THEN two conflicting `.login-card` rules (max-width 400px with padding 32px 36px, and width min(100%, 420px) with padding 40px 32px and hidden overflow) decide the card's size by stylesheet order, and the footer (max width 440px) does not line up with the card's edges.

1.25 WHEN a user tries to open "⚙ System check" on the login page THEN it is visible but cannot be clicked, because the full-screen login overlay (z-index 9999) covers it (z-index 50).

1.26 WHEN the login page renders on a narrow screen THEN the decorative backdrop keeps its inline four-column grid, which overrides the responsive CSS.

#### D. Automatic sign-out

1.27 WHEN a Pro user's `/settings` is still loading or has failed on the web THEN the 5-minute preview timer starts (a missing plan counts as free and the server's `enforced` flag is ignored), and after 5 minutes the full-screen "Upgrade to Pro Required" lock appears with Sign Out as its only button; the timer's start time stays in session storage across sign-outs and account switches (only the Sign Out buttons on the lock and trial-ended screens clear it), so after signing in again the lock can appear at once; and a failed `/settings` load is not retried.

1.28 WHEN any request made through the billing web app's API client or authenticated fetch returns 401 THEN the app signs the user out, including a 401 that does not reject the user's session, such as a cloud 401 that the desktop app's B2B proxy passes through for a write.

1.29 WHEN a web tab stays open for 24 hours after sign-in THEN the access token expires mid-shift and the next request signs the user out, because no web app calls `POST /auth/refresh`.

1.30 WHEN `/profile`, `/settings` or the business-config request returns 404 THEN Billing signs the user out, even when the 404 does not mean "account not found" (for example a route missing on an older revision or a wrong API host).

1.31 WHEN an admin's token expires or any admin console request returns 401 THEN the admin console signs the admin out with no warning, and after signing in again it always opens /admin/dashboard instead of the page the admin was on.

#### E. Sync

1.32 WHEN a packaged desktop app syncs (push, pull, Instant Pull, token refresh, plan refresh) THEN its bundled backend calls the Hugging Face Space, which now returns HTTP 503, because the desktop shell passes no cloud URL and the installer must not ship a .env file, while the renderer signs in to Cloud Run and hands the backend a Cloud Run token; the result is "Cloud unreachable", a growing outbox, failing pulls and expiring cloud tokens.

1.33 WHEN an already-installed desktop app (released before this fix) signs in to the cloud or syncs THEN it calls the Hugging Face Space, which returns HTTP 503, so it cannot sync or recover accounts until it is updated.

1.34 WHEN any other cloud caller runs without an explicit setting (the B2B proxy, the pos.* real-time relay, LAN discovery registration, the telemetry relay, the desktop shell's telemetry, the admin standby probe, maintenance scripts) THEN it falls back to, or is hard-coded to, the Hugging Face URL, and the fallbacks read four different variable names (`CLOUD_API_URL`, `VITE_API_URL`, `CLOUD_URL`, `BIZASSIST_CLOUD_URL`).

1.35 WHEN the desktop app's B2B proxy receives an HTTP 5xx or 429 response from the cloud for a read THEN it passes the error through instead of serving the local B2B mirror (it falls back only on network errors and 401), and its 12-second limit makes B2B writes fail with "B2B is offline" during a cold start.

1.36 WHEN a billing API instance boots on Cloud Run with a privileged database role (superuser or BYPASSRLS; the Supabase `postgres` role normally has BYPASSRLS, still to be confirmed) THEN every cold start runs `create_all`, the full migration and the change-feed install before the port opens; the install drops and recreates the capture trigger on every synced table (ACCESS EXCLUSIVE locks) and checks every existing row with one query each, all in one transaction, so boot time grows with the data and the locks block requests on any other instance.

1.37 WHEN the change-feed install hits a lock or deadlock error THEN its own error handler fails with NameError (it logs through an undefined logger); the start-up code swallows only errors whose message contains "lock" or "deadlock", so it re-raises and the container crashes at import; and because "lock" also matches "block" (for example "current transaction is aborted, commands ignored until end of transaction block"), unrelated failures are logged as "peer completed" and the change feed can be left uninstalled.

1.38 WHEN a web client keeps the real-time stream open THEN Cloud Run ends it at the 120-second request limit, and Billing then shows "Sync stream interrupted. Reconnecting…", "Connecting to cloud sync stream…" and "Cloud real-time sync connected." and dispatches `sync.reconnect`, so every open page refetches its data about every 2 minutes for every web user; the stream has no event ids or replay, so events sent during the gap are lost.

1.39 WHEN the desktop app's Instant Pull stream is cut by the platform THEN its reconnect delay doubles up to 120 seconds and never resets (it resets only after a clean close), and because the stream has no read timeout, a connection that drops silently can block the listener indefinitely.

1.40 WHEN the billing API runs more than one instance (`--max-instances 2`), restarts or scales to zero THEN state held in process memory diverges or is lost: real-time events (cart mirroring, live counters, pull pings, relayed pos.* events) reach only clients connected to the same instance; the LAN discovery registry empties; rate-limit windows count per instance; and the record of spent hand-off tickets is per instance, so a ticket can be redeemed once on each instance.

1.41 WHEN the cloud is cold or answers with a Google 429 or 503 HTML page THEN the desktop sync worker's 10-second health probe fails (the HTML body fails its JSON check) and reports "Cloud unreachable"; a failed token refresh (10-second timeout) is retried only after 15 minutes, so the token can expire, the next pull gets 401, the worker drops the token, and sync stops until the owner signs in again; the push read timeout (120 s) equals the platform limit, and the parity sweep's 180-second read is always cut at 120 seconds; and `Retry-After`, 429 and 503 are not handled.

1.42 WHEN a scheduled job falls due on Cloud Run (daily summary 08:00, overdue alerts 09:00, low-stock alerts 09:05, expiry alerts 09:10, books-integrity audit 03:30, telemetry retention 02:30, log upload 23:30, weekly memory distillation and database maintenance) THEN it usually does not run, because the instance is scaled to zero or its CPU is throttled outside requests, and with two instances it can run twice.

#### F. Admin console

1.43 WHEN an admin opens the Infrastructure page THEN `/admin/infrastructure-metrics` imports psutil, which no requirements file declares, so wherever the image lacks it the endpoint fails with HTTP 500 and the page shows "Pending Deployment" (to be confirmed in Cloud Logging).

1.44 WHEN `/admin/infrastructure-metrics` runs THEN it counts invoices, products, payments and audit logs with no owner predicate and no entry in `tenant_scope.ALLOWED`, so `test_tenant_scope.py::test_no_unscoped_tenant_reads` fails (regression from 5700877), and it probes the Hugging Face Space and https://staterbill.com one after the other on every call.

1.45 WHEN the metrics request fails THEN the Infrastructure page shows hard-coded healthy values as if they were real (ACTIVE, CONNECTED, ONLINE, 15% memory, 5% CPU, 4 threads, 99.8% cache hit, BOM1, HSTS, ~180–450 ms, "Synced to origin/main", 1200 ms) and labels every error "Pending Deployment"; it also auto-refreshes every 15 seconds by default (keeping the instance awake and probing Hugging Face), its unused `useDialog` import makes `npm run lint` fail (CI runs it with `--max-warnings 0`), the "alert-triangle" icon does not exist, the `.spinning` class has no CSS, CPU always reads 0, and the region comes from a variable that Cloud Run does not set.

1.46 WHEN `GET /admin/rate-limits/{id}` or `GET /admin/usage-stats` raises an unexpected error THEN the error leaves the route without a JSON body or CORS headers, so the browser reports a CORS failure instead of a server error.

1.47 WHEN the admin console lists businesses, runs the sync doctor, loads usage stats or opens one business THEN the billing API runs several queries per business, returns every invoice, inventory row, payment and chat message of a business unpaginated, and the business detail page loads the whole fleet to show one business, so these requests grow with the fleet towards the 120-second limit.

1.48 WHEN an admin changes the router mode, flushes caches, reads cache statistics or the server log status, downloads client log archives uploaded with feedback, or reads the audit-log file THEN the action applies to, or reads from, only the instance that served the request; files written to the instance's in-memory disk are lost on scale-to-zero (the feedback row remains but its archive returns 404), and the router mode resets on every cold start.

1.49 WHEN the billing API runs with a non-privileged database role and `ADMIN_SERVICE_URL` is not set THEN every `/admin/*` request returns 503 "Platform administration service is not configured"; no deploy script provisions `ADMIN_SERVICE_URL`; `deploy_cloudrun.sh` replaces every environment variable and secret on each deploy (`--set-env-vars`, `--set-secrets`), dropping anything set by hand; and the billing deploy reports the service as live even when its health check fails.

1.50 WHEN an admin arrives in the admin console through a hand-off ticket THEN only the owner session is set, never the admin session, so the admin is sent to the admin login; and `?logout=true` clears the owner session but leaves the stored admin session.

#### G. Domain leftovers

1.51 WHEN a visitor opens Terms, Privacy, Refunds or Contact on the landing page THEN the links go to https://bizassist-billing.vercel.app.

1.52 WHEN a visitor opens https://www.staterbill.com THEN the browser shows a certificate error, because the certificate covers only staterbill.com.

1.53 WHEN the production CORS lists are deployed THEN they include team.staterbill.com and ai.staterbill.com, which do not resolve, and the PowerShell deploy script adds http://localhost:5174 to production.

1.54 WHEN a frontend's Vercel project lacks one of its `VITE_*` settings THEN the build silently falls back to an old host or hides a feature (1.1, 1.2, 1.13), and nothing checks these settings before a release.

1.55 WHEN an operator follows the setup documentation or `.env.example` THEN they describe a Hugging Face and Vercel-only setup, including setting `VITE_API_URL` to an hf.space URL.

#### H. Plan enforcement consistency

1.56 WHEN production runs THEN `SUBSCRIPTION_ENFORCED` is unset (no billing deploy script or Dockerfile sets it), `/settings` reports `enforced: false` and the `require_plan` gates are open, yet Billing applies its own gates (the 5-minute preview, PRO badges) without reading that flag, while the Field Team API always enforces Pro, so client and server disagree about what is gated.

### Expected Behavior (Correct)

#### A. Field Team from Billing

2.1 WHEN the billing web app is built for production without `VITE_FIELD_TEAM_URL` THEN the system SHALL show Field Team to owners and open the production Field Team URL (assumption 3), and `VITE_FIELD_TEAM_URL` SHALL still override it.

2.2 WHEN Field Team is opened from https://staterbill.com, https://www.staterbill.com, https://bizassist-billing.vercel.app or the desktop app THEN Field Team SHALL trust that origin as Billing, apply the different-business guard, start the appearance hand-off, and point "Back to Billing" and Register links at the origin that opened it (https://staterbill.com when that origin is unknown).

2.3 WHEN Field Team is opened from Billing without a usable ticket THEN Field Team SHALL NOT silently restore a stored session and SHALL ask the owner to sign in for the business that Billing named, as it already does for a trusted Billing origin.

2.4 WHEN the Field Team web app calls the Field Team API from its production origin (https://bizassist-task.vercel.app, and team.staterbill.com if adopted) THEN the CORS preflight SHALL succeed by default, without depending on a manually passed `-AllowedOrigins` (operator: redeploy with the production origins); and WHEN a request fails while the browser is online THEN Field Team SHALL say that the server could not be reached instead of telling the user to check mobile data.

2.5 WHEN the Field Team API needs up to 60 seconds to start THEN the hand-off from Billing SHALL sign the owner in on the first attempt, tickets SHALL stay short-lived (a lifetime of at most 120 seconds), and a cold start with an up-to-date schema SHALL NOT repeat migration work.

2.6 WHEN the Field Team API refuses a hand-off ticket THEN it SHALL log the specific reason and SHALL show a message that matches it (expired, already used, or not signed with the shared key, which points to a configuration fault), without revealing any secret.

2.7 WHEN the plan is not yet known THEN Billing SHALL NOT show the Pro alert or PRO badges, and SHALL apply the Field Team and AI dashboard gate only once the plan is known to be non-Pro.

2.8 WHEN the Field Team or AI dashboard window cannot be opened, the ticket cannot be obtained, or the link is opened in a new tab THEN Billing SHALL tell the owner what happened and how to continue (allow pop-ups, retry, or sign in on Field Team), and a link opened in a new tab SHALL still land on a working sign-in for the right business.

2.9 WHEN a release is deployed THEN the Field Team API SHALL run the repository's revision and pass its own readiness gate (operator: redeploy), and the release check SHALL confirm, without revealing secrets, that the two services accept each other's tickets (same `JWT_SECRET`) and use the same database.

2.10 WHEN the release check runs with its defaults THEN it SHALL target the current production hosts (the Cloud Run billing and Field Team APIs, https://staterbill.com, and the Field Team, AI dashboard and admin console URLs), SHALL tolerate a cold start, and SHALL fail when a production frontend redirects to a Vercel sign-in page or presents an invalid certificate.

#### B. SSO page and Dashboard BIZASSIST

2.11 WHEN an owner opens Dashboard BIZASSIST on the web THEN the production AI dashboard SHALL load directly without a Vercel sign-in page, and the owner SHALL arrive signed in (operator: turn off Deployment Protection for the production deployment, or serve it from a public custom domain).

2.12 WHEN an owner opens Dashboard BIZASSIST THEN Billing SHALL open the window within the click, before waiting for the ticket, as it already does for Field Team.

2.13 WHEN the AI dashboard or the admin console receives a hand-off message, or the AI dashboard receives a logout message, from https://staterbill.com, https://www.staterbill.com or https://bizassist-billing.vercel.app THEN it SHALL accept the message by default (exact origin, from its opener only), and `VITE_BILLING_URL` SHALL still be able to add an origin.

2.14 WHEN a web user signs out of Billing THEN the AI dashboard session that Billing opened SHALL end, at the latest on that dashboard's next request to the billing API, and Billing SHALL address the configured AI dashboard URL instead of port 5173.

2.15 WHEN the AI dashboard cannot redeem its hand-off ticket THEN it SHALL NOT restore a stored session for a business other than the one Billing named, and SHALL show a message with a way to sign in.

2.16 WHEN a hand-off ticket minted before a force logout is redeemed at the billing API's `/redeem-ticket` THEN the billing API SHALL refuse it with 401, as the Field Team API does.

#### C. Login and registration

2.17 WHEN an unauthenticated client calls `POST /api/biz_id/check` or `GET /api/auth/check-username` THEN the billing API SHALL return 404 and disclose nothing, and the session-invalidation test SHALL pass.

2.18 WHEN a user continues on the "Other business" step THEN the login page SHALL go to the credential step without looking up the business, and the sign-in itself (including the desktop app's cloud-verified fresh-device recovery) SHALL decide, with one generic error for a wrong username or password.

2.19 WHEN a user registers THEN a taken username SHALL be reported from the cloud's sign-up result, which is the authority, and not from the local database.

2.20 WHEN the billing API is cold and a user signs in or registers on the web THEN the request SHALL be allowed up to 60 seconds to complete with a visible "server is starting" state, and web users SHALL NOT be told to restart BizAssist; the desktop app SHALL keep its bounded wait and message for the local backend (3.16).

2.21 WHEN a registration's outcome is unknown because of a time-out THEN Billing SHALL recover the account that may have been created (for example by signing in with the same credentials) instead of reporting that the username already exists.

2.22 WHEN the Cloud Run front end answers with a 429, 500, 503 or 504 HTML page THEN the web apps SHALL show a short readable message, SHALL retry idempotent requests with backoff that honours `Retry-After`, and SHALL NOT sign the user out because of it.

2.23 WHEN the login content is taller than the viewport THEN the whole card SHALL be reachable by scrolling, nothing SHALL hide behind mobile browser toolbars, and the page SHALL have no horizontal offset or scroll.

2.24 WHEN the login page renders THEN the card SHALL have a single definition, and the footer SHALL line up with the card's edges at every width.

2.25 WHEN a user opens "⚙ System check" on the login page THEN it SHALL respond to clicks and stay usable at every viewport size.

2.26 WHEN the login page renders on a narrow screen THEN the decorative backdrop SHALL follow the responsive layout.

#### D. Automatic sign-out

2.27 WHEN the plan is not yet known THEN no preview timer SHALL run; the timer SHALL start only for a session whose plan is known to be free and for which the server reports the preview gate as on (assumption 5); its start time SHALL reset on sign-in, sign-out and account switch; a failed `/settings` load SHALL be retried; and a Pro user SHALL never see the lock.

2.28 WHEN a 401 does not reject the current session token THEN the web apps SHALL show the error and keep the session; WHEN the billing API rejects the session token itself THEN they SHALL sign out as today (3.1).

2.29 WHEN a web session is in use THEN the web apps SHALL refresh the access token before it expires, so an active user is never signed out by token age alone.

2.30 WHEN `/profile`, `/settings` or the business-config request returns 404 THEN Billing SHALL sign out only when the API states that the account no longer exists, and SHALL report any other 404 without ending the session.

2.31 WHEN an admin session nears or reaches expiry THEN the admin console SHALL refresh it, or warn and ask the admin to sign in; a 401 that does not reject the session SHALL NOT sign the admin out; and after signing in the admin SHALL return to the page they were on.

#### E. Sync

2.32 WHEN a packaged desktop app syncs THEN its bundled backend SHALL use the same cloud API as the renderer (the Cloud Run billing API by default) without a .env file.

2.33 WHEN an already-installed desktop app calls the Hugging Face URL THEN the request SHALL reach the Cloud Run billing API (operator: Hugging Face forwarder, assumption 6), and the next desktop release SHALL move the app to the new default.

2.34 WHEN any cloud caller resolves the cloud URL THEN it SHALL take it from one shared setting whose default is the current production API, and the existing variable names SHALL still work as overrides.

2.35 WHEN the desktop app's B2B proxy receives 5xx or 429 from the cloud for a read THEN it SHALL serve the local mirror, as it does for network errors, and B2B writes SHALL wait out a cold start of up to 60 seconds before reporting that B2B is offline.

2.36 WHEN a billing API instance boots and the schema is already current THEN start-up SHALL do no DDL and no per-row work, SHALL take a bounded time that does not grow with the data, and SHALL take no locks that block requests; schema changes SHALL be applied once per release, under one migration lock, before traffic moves to the new revision; and the database role chosen for the runtime SHALL keep the admin console working (2.49).

2.37 WHEN the change-feed install fails THEN the real cause SHALL be logged; only a genuine concurrent-migration conflict SHALL be treated as "another instance finished", and only after confirming that the change feed is installed; any other failure SHALL fail the migration visibly.

2.38 WHEN the platform or the server ends a real-time stream THEN Billing SHALL reconnect without toasts unless the stream stays down for more than 30 seconds, SHALL receive the events it missed (event ids with replay, or a cursor-based catch-up), and SHALL NOT refetch every page when nothing was missed.

2.39 WHEN the Instant Pull stream is cut after it was established THEN the next reconnect SHALL use the base delay, and a stream that delivers nothing, not even keep-alives, for three keep-alive intervals SHALL be treated as dead and reopened.

2.40 WHEN the billing API restarts, scales to zero or runs more than one instance THEN every real-time event SHALL reach every subscribed client of that business, a hand-off ticket SHALL be redeemable at most once, rate limits SHALL count all of a client's requests, and LAN discovery registrations SHALL NOT be lost (assumption 2).

2.41 WHEN the cloud is starting or temporarily refusing requests THEN the sync worker SHALL report the cloud as starting rather than unreachable, SHALL retry with backoff that honours `Retry-After`, SHALL keep retrying token refresh until it succeeds well before expiry, SHALL use request timeouts that fit inside the platform limit, and SHALL never drop a token because of a cold start.

2.42 WHEN a scheduled job falls due on the cloud THEN it SHALL run exactly once (for example triggered by Cloud Scheduler with a shared secret and a run lock).

#### F. Admin console

2.43 WHEN an admin opens the Infrastructure page THEN the endpoint SHALL return data on the production image (every runtime dependency declared), and a metric it cannot read SHALL be marked unavailable instead of failing the request.

2.44 WHEN `/admin/infrastructure-metrics` runs THEN each platform-wide count SHALL either carry a justified entry in `tenant_scope.ALLOWED` or be removed, so that the tenant-scope test passes; and outside probes SHALL be bounded, run concurrently or from a cache, and SHALL NOT target retired hosts.

2.45 WHEN the metrics request fails or a value is unavailable THEN the Infrastructure page SHALL show "unavailable" instead of invented values, describe the actual error, and follow the console's existing load-error-and-retry pattern; auto-refresh SHALL be off by default; `npm run lint` SHALL pass; the icons and spinner SHALL render; and CPU and region SHALL show real values or "unavailable".

2.46 WHEN any admin route raises an unexpected error THEN it SHALL return a JSON 500 that the browser can read (with CORS headers), like the other admin routes.

2.47 WHEN the admin console lists businesses, runs the sync doctor, loads usage stats or opens one business THEN the billing API SHALL use a number of queries that does not grow with the number of businesses, SHALL paginate detail lists, and the console SHALL load only the business being viewed.

2.48 WHEN an admin changes a setting or reads diagnostics THEN settings SHALL apply to every instance and survive restarts, uploaded log archives and audit records SHALL be stored durably (database or object storage), and any view that describes a single instance SHALL say which one.

2.49 WHEN the runtime uses a non-privileged database role THEN the deploy SHALL provision `ADMIN_SERVICE_URL` from Secret Manager so that the admin console works; both billing deploy scripts SHALL apply the same settings and SHALL keep variables and secrets they do not manage; and a deploy SHALL fail when the new revision's health check fails.

2.50 WHEN an admin arrives through a hand-off ticket THEN the admin console SHALL establish the admin session only after the server confirms the admin role, and `?logout=true` SHALL clear every session the console holds.

#### G. Domain leftovers

2.51 WHEN a visitor opens Terms, Privacy, Refunds or Contact on the landing page THEN the links SHALL go to https://staterbill.com.

2.52 WHEN a visitor opens https://www.staterbill.com THEN it SHALL present a valid certificate and redirect to https://staterbill.com (operator: add www.staterbill.com to the Vercel project).

2.53 WHEN the production CORS lists are deployed THEN they SHALL contain only origins that serve a production frontend under assumption 3, plus the transition origins (3.10), and development origins SHALL come only from the existing localhost and LAN rule.

2.54 WHEN a production frontend is built without one of its `VITE_*` settings THEN every cross-app URL SHALL default to the production host, and the release checklist SHALL record each project's `VITE_API_URL`, `VITE_FIELD_TEAM_URL`, `VITE_AI_DASHBOARD_URL`, `VITE_BILLING_URL` and `VITE_PUBLIC_WEB_URL` (operator).

2.55 WHEN an operator follows the setup documentation or `.env.example` THEN they SHALL describe the Cloud Run and staterbill.com setup, the per-project Vercel settings and the operator checklist.

#### H. Plan enforcement consistency

2.56 WHEN Billing decides whether to apply a plan gate THEN it SHALL follow the enforcement that the server reports for that gate (assumptions 4 and 5), the billing deploy scripts SHALL set `SUBSCRIPTION_ENFORCED` explicitly, and the Field Team API and the AI chat endpoints SHALL keep enforcing Pro on the server.

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a session token's subject is revoked (token version bumped, for example by a force logout) or deleted THEN the billing and Field Team APIs SHALL CONTINUE TO return 401; WHEN the database is unreachable THEN they SHALL CONTINUE TO return 503; and WHEN the billing API rejects the session token itself THEN the web apps SHALL CONTINUE TO sign the user out.

3.2 WHEN an unauthenticated client probes staff or account discovery routes THEN the API SHALL CONTINUE TO disclose nothing (`GET /staff-counters?owner=` returns 404), and no new anonymous lookup SHALL be added.

3.3 WHEN backend code reads tenant tables THEN the tenant-scope guard SHALL CONTINUE TO fail any read without an owner predicate unless `core/sync/tenant_scope.ALLOWED` justifies it, and SHALL CONTINUE TO reject stale or unjustified allowances.

3.4 WHEN data crosses a database boundary THEN BizID SHALL CONTINUE TO be the only business identity used, and a Local-only business SHALL CONTINUE TO send nothing to the cloud (`test_local_only_stays_local`).

3.5 WHEN a hand-off ticket is minted or redeemed THEN tickets SHALL CONTINUE TO be issued only to owners, signed with HMAC over the shared `JWT_SECRET`, short-lived and single-use; and the Field Team API SHALL CONTINUE TO refuse staff tickets (403) and tickets minted before a force logout (401).

3.6 WHEN a business without an active Pro plan (after any grace period) uses Field Team THEN the Field Team API SHALL CONTINUE TO refuse it with 402 and its current messages, and the AI chat endpoints SHALL CONTINUE TO require Pro.

3.7 WHEN a page receives a hand-off, appearance or logout message THEN it SHALL CONTINUE TO accept the message only from an exact allow-listed origin and only from its opener; this fix only adds the new production origins.

3.8 WHEN the app runs on localhost or a LAN address (desktop app or LAN cashier) THEN it SHALL CONTINUE TO use the local backend, and WHEN it runs on any other host THEN it SHALL CONTINUE TO use the cloud.

3.9 WHEN a genuinely free web account (plan known, not Pro, no active trial) uses the web app THEN it SHALL CONTINUE TO get the 5-minute preview and lock (assumption 5); WHEN a signup trial has lapsed THEN the trial-ended screen SHALL CONTINUE TO appear; and WHEN the plan is known and not Pro THEN Billing SHALL CONTINUE TO show the PRO badge and upgrade note for Field Team and Dashboard BIZASSIST.

3.10 WHEN clients use the old hosts during the transition THEN https://bizassist-billing.vercel.app and the other current vercel.app origins SHALL CONTINUE TO be accepted by the CORS and trust lists, and already-installed desktop apps that call the Hugging Face URL SHALL CONTINUE TO work once the forwarder (or a restored Space) is in place.

3.11 WHEN the desktop app's local (SQLite) backend starts THEN it SHALL CONTINUE TO create and migrate its schema, install the change feed and run its in-process scheduler; and WHEN the cloud schema is behind THEN a constrained cloud runtime SHALL CONTINUE TO refuse to start ("Database migration required").

3.12 WHEN the change feed is installed or refreshed THEN rows missing from the event history SHALL CONTINUE TO be seeded exactly once per UID, and replication SHALL CONTINUE TO be commit-ordered.

3.13 WHEN the cloud is reachable and warm THEN sign-in, registration, sync push and pull (protocol 2), outbox chunking and backoff, and B2B proxying SHALL CONTINUE TO behave as today; B2B reads SHALL CONTINUE TO fall back to the local mirror on network errors and stale tokens; and B2B writes SHALL CONTINUE TO be refused with "B2B is offline" when the cloud is truly unreachable.

3.14 WHEN a cashier or supply adder is signed in THEN Field Team and Dashboard BIZASSIST SHALL CONTINUE TO be unavailable to them, and WHEN enforcement is on THEN switching to Local + Cloud SHALL CONTINUE TO require Pro (402).

3.15 WHEN the desktop app opens Dashboard BIZASSIST THEN it SHALL CONTINUE TO open the bundled dashboard (127.0.0.1:8451) in its own window, and blank print windows SHALL CONTINUE TO open inside the app.

3.16 WHEN the desktop app's local backend does not respond THEN desktop sign-in SHALL CONTINUE TO fail within a bounded wait with the local billing service message.

3.17 WHEN admin routes run THEN `ADMIN_API_ENABLED` SHALL CONTINUE TO gate them (404 when unset), every admin request SHALL CONTINUE TO re-check admin authority in the database and audit mutations, and the admin 2FA sign-in SHALL CONTINUE TO work.

3.18 WHEN Field Team is opened from the desktop app THEN the desktop app SHALL CONTINUE TO get the ticket from the cloud rather than from its local backend and SHALL CONTINUE TO ask Local-only businesses to switch to Local + Cloud first, and Field Team SHALL CONTINUE TO apply the different-business guard.

3.19 WHEN Billing sends appearance settings to Field Team THEN Field Team SHALL CONTINUE TO accept only sanitized colour tokens for the verified business, never URLs or credentials.

3.20 WHEN a real-time stream is open THEN the per-business connection cap SHALL CONTINUE TO apply, and revoking a session SHALL CONTINUE TO close its open stream.

3.21 WHEN the services are deployed or the desktop installer is built THEN secrets SHALL CONTINUE TO come only from Secret Manager without being printed or logged, and the installer SHALL CONTINUE TO ship without a .env file.

3.22 WHEN the backend test suites run in parallel with the commands in the introduction THEN every test that passes today SHALL CONTINUE TO pass (2,526 billing tests and the full Field Team suite), with `test_semantic_router_eval_accuracy` exempt only where huggingface.co is unreachable.
