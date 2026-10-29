# Field Team agent survey — 29 October 2026

This review covers every routed Field Team page, its owner/staff boundaries,
Billing identity and financial read adapters, cloud/Pro rules, location buffering,
and the shared-cloud business deletion lifecycle. It is a source, component-test
and isolated API/database review. It does not assert that every authenticated page
was manually visited in the deployed browser or on physical staff phones.

The user's in-progress workspace/profile/sidebar design was retained. The audit
made targeted fixes around that design and did not change the two-local-database
development arrangement. Field operations remain cloud only in production.

## Confirmed issues fixed

| Priority | Finding and resulting behavior | Evidence |
|---|---|---|
| P1 | A single global GPS buffer could replay another staff member's/business's offline positions after a browser account switch. Production trackers now scope storage by verified BizID and staff ID and bind sends to their original token. In-flight session changes retain unsent points in their original scope; they never send through the new account. Legacy unowned points are not attributed to a new user. | `frontend-task/src/lib/tracker.js`, `layouts/StaffLayout.jsx`; `trackerSession.test.js` |
| P1 | HTTP408/429/5xx lost buffered GPS evidence; a later failed chunk could also replay already acknowledged chunks. Only unsent chunks are now retained, capped at120 points; timer ticks retry queued evidence even without a new GPS fix. Network/identity boundaries remain enforced. | `tracker.js`, `trackerSession.test.js` |
| P1 | Two simultaneous task completions could both observe pending state and award duplicate points or replace collection evidence. Completion/update now lock only the scoped task row on PostgreSQL. Two real concurrent requests produce200/409 and one task-points entry. | `backend-task/app/routers/tasks.py`; `test_task_audit_regressions.py` |
| P1 | Concurrent owners could both plan delivery/collection work for the same invoice. All planning paths now resolve and lock the same tenant-scoped invoice rows, in ascending ID order, before the active-task check; locks stay in the caller's transaction. Real concurrent planning produces201/409. | `app/invoices.py::resolve_invoices`; task-audit concurrency regression |
| P1 | Field balances used gross minus stored paid amount and ignored linked returns. The read adapter now matches Billing's linked-credit-adjusted obligation and authoritative receipt sums. Fully returned bills cannot be assigned or collected; partial returns reduce suggested/expected/current collection amounts. Paid returns expose credit due without inventing a payment/refund. Collection amounts cannot exceed current adjusted dues. | `app/invoices.py`, `app/billing_context.py`, `app/billing_models.py`, `routers/runs.py`; `test_credit_balance_alignment.py` |
| P1 | A cloud Billing business wipe left orphaned Field rows: business ownership columns intentionally do not have user FKs, and internal Field cascades do not fire merely because a Billing owner is deleted. Billing's centralized purge now explicitly removes the same business's14 whitelisted Field tables child first, in the existing transaction. Synthetic actual-schema proof removes one complete Field tree while preserving another and revokes the deleted owner's and staff's API access. | `backend/services/field_business_cleanup.py`, `services/admin_service.py`; `test_business_delete_lifecycle.py` |
| P1 | Non-finite expected/collected amounts could bypass a non-negative-only float rule; non-finite GPS metadata could also reach storage/error formatting. Money fields and all GPS floats now reject non-finite inputs. Validation responses omit raw inputs and safely return422 even for crafted1e309/Infinity payloads, without creating attendance, collection or points rows. | `routers/tasks.py`, `routers/runs.py`, `app/geo.py`, `app/main.py`; task-audit negative tests |
| P2 | Null/blank task edits caused errors or invalid state, partial due-time edits cleared the due date, and a route task could be reassigned independently of its run. Invalid edits now return422, due edits preserve the other calendar component, and route reassignment must go through the run. | `routers/tasks.py`; task-audit validation/date/reassignment tests |
| P2 | Slow Live-map trail responses could replace a newer person's selected trail, and failures silently hid the trail. Obsolete requests are ignored; the current failure and loading state are visible. | `pages/owner/Live.jsx`, `Live.test.jsx` |
| P2 | Field Login offered an optional-phone signup form that the deployed Pro gate correctly refused. New owners now follow a direct Billing registration link, centralizing required phone capture and the first-time14-day Pro trial. The development-only backend signup fixture is retained. | `pages/Login.jsx`, `Login.test.jsx` |
| P2 | The mobile profile trigger was a clickable div without keyboard activation. It is now a native button with an accessible name and expanded state. | `layouts/OwnerLayout.jsx` |
| P2 | The picker allowed selecting bills with no money due. Collection selection now disables those bills and displays returns/credit separately. | `components/InvoicePicker.jsx`, `InvoicePicker.test.jsx` |

The existing same-business bridge tests also exposed a test timing race: the
assertion sampled bridge calls before the initial verified-business effect had
run. The test now waits for that first effect before measuring unchanged-business
refresh behavior; no production authentication behavior was changed for that test.

## Every-page inventory

Routes are selected by verified caller kind in `frontend-task/src/App.jsx`; owner
and staff route trees are separate. Backend role checks remain authoritative.

| Caller / route | Surveyed behavior | Verification / remaining limit |
|---|---|---|
| Signed out / Login | Staff uses BizID, login name, password and device identity. Owner uses the Billing account. New-owner registration goes to Billing. | Auth, device, SSO/business bridge and new registration-link tests. No real signup submitted. |
| Owner `/` Dashboard | Business-date attendance, route progress, deliveries, overdue work and recent activity; generation from route templates. | `test_runs_tasks.py`, attendance/dashboard coverage; totals were verified on synthetic days. Production multi-device refresh remains a release check. |
| Owner `/live` Live map | Last known duty/location, route progress, selectable person/day trail,30-second refresh. | Tracking API and trail-race/error component tests. Background/locked-phone GPS cannot be inferred from desktop tests. |
| Owner `/plan` Day plan | Manual/generated runs, shops, boxes, invoice picks, due collection, cancel and whole-run reassignment. | Invoice/run/task suites and two-planner PostgreSQL race. No physical delivery-day soak. |
| Owner `/tasks` Tasks | Assign, filter, pending/overdue/done/cancelled, points and linked bill snapshots/current dues. | Task edit/completion/financial alignment regressions. Owner/staff simultaneous cancel/reassign/complete remains a useful stress test. |
| Owner `/requests` Shop requests | New/acknowledged/fulfilled/closed inbox; item quantities, notes, shop, staff and event location. | Tracking/request API suite. Requests are not automatically converted to Billing sales/B2B orders. |
| Owner `/shops` Shops | Import/link Billing customers; shared name, phone and address remain Billing-authoritative; delivery pin and notes are Field-owned. | `Shops.test.jsx`, Billing customer/alignment tests. The explicit development-mirror warning is retained. |
| Owner `/routes` Route templates | Weekdays, stop order, default staff, due time, active state and daily generation. | Route/run suites. Dependency-fetch failure UX and rapid duplicate submit protection can be made more uniform. |
| Owner `/staff` Staff/devices | Field staff accounts, password policy, role labels, activation, session/device release and sign-out. | Staff/device/auth suites. Disabling a person does not redesign outstanding route ownership; the owner should reassign pending work. |
| Owner `/attendance` Attendance | Server-time/day register, checked in/out, lateness, absences and location evidence. | Attendance/timezone tests and non-finite GPS rejection. Device location permissions need phone verification. |
| Owner `/scorecard` Scorecard | Points, on-time tasks, missed work, deliveries, boxes, reported collections and presence by period. | Task/attendance/collection suites; duplicate-completion award race fixed. Points are not payroll or paid incentives. |
| Owner `/activity` Activity | Tenant-scoped action trail with actor, server time and event location. | Logging/activity coverage including caller BizID context. Not a tamper-evident export/signing system. |
| Owner `/settings` Settings | Field-only operational rules; shared Billing business link; per-business display mode and inherited palette. | Settings/auth/theme/bridge suites. Direct login on a new device uses defaults until Billing appearance arrives; universal cloud-persisted palette fetch remains a recommendation. |
| Staff `/` Today | Duty, GPS/connection status, route start/arrival/skip/delivery/task completion, boxes, collection amounts, points and wake-lock control. | Full synthetic workday, geofence, request, collection and completion tests. Actual GPS, battery, screen lock and browser permissions remain device tests. |
| Staff `/my-tasks` My tasks | Own pending/done work; source bill snapshots plus current adjusted balance; route work completes from Today. | Staff ownership and current-dues API tests. Consistent refresh/retry controls can improve stale-session recovery. |
| Staff `/request` Shop order | Shop/route context, order or requirement list, positive quantities, on-duty GPS, own request history. | Request validation/tenant tests. Dependency-fetch failures are not yet surfaced as consistently as top-level page errors. |
| Staff `/score` My score | Own monthly points, punctuality, deliveries, boxes, attendance, missed work and reported collections. | Scorecard/API tests. It does not record a cash handover or expense reimbursement. |

Common shell review covered the user's workspace/profile controls, collapse state,
mobile drawer/focus trap, active navigation, business-name overflow, display modes,
theme-token bridge, token-change response guards and API error translation. No
broad layout/style rewrite was performed.

## Billing identity, money and deletion boundaries

- Online Billing and Field use the same cloud user/BizID/customer/invoice rows.
  Separate local development mirrors are not merged. Production configuration
  rejects an implicit SQLite Field database or an enabled development mirror.
- Field staff are `ft_staff`, not Billing owner users. Their task tokens have a
  derived signing key and audience; Billing-style decoding rejects them. Device,
  active-session, business identity, role and owner's plan are checked server side.
- Deployed Field Pro enforcement is mandatory in config. Paid expiry may have the
  documented grace period; a free trial has no extra grace and ends at its expiry.
  First-time registration/phone/trial authority is Billing, not a second Field plan.
- Field reads invoices and records reported collection evidence. The owner confirms
  allocations in Billing through its payment command/idempotency contract. The
  credit-adjusted adapter does not create a receipt, refund or customer advance.
- Cloud deletion removes the scoped shared-cloud Field tree. `ft_alembic_version`
  is retained. Unsupported tables/relationships, malformed cross-business Field
  references or insufficient RLS visibility stop deletion with409. The helper never
  commits on its own and never disables a database policy. Root's trial-phone claim
  retention remains in the same centralized purge.
- Cloud deletion does not remotely erase offline Billing copies or consume a local
  deletion acknowledgement. That separate retirement/tombstone channel remains
  the lifecycle work described in the main survey.

## Completed checks

These are overlapping runs and must not be added together as unique test counts.
All API/database tests used generated fixture identities and disposable test DBs;
developer/production DSNs were cleared and external network access blocked. Cloud
purge tests explicitly mocked vector-store deletion so synthetic integer IDs could
not touch an existing embedding namespace.

| Check | Result |
|---|---|
| Final full Field frontend after picker, GPS and login fixes |68 passed /16 files |
| Final affected frontend set (picker, tracker session, login, Live) |10 passed /4 files |
| Final frontend production build |Passed; approximately461kB JS /136kB gzip,54kB CSS |
| Full Field SQLite suite before final financial adapter additions |138 passed,7 skipped |
| Full Field PostgreSQL mirror suite at that stage |140 passed,5 skipped |
| Full suite against actual Billing-model PostgreSQL schema, including opted-in non-bypass RLS probe |151 passed, no skips, before the final GPS/deletion/credit-focused additions |
| Final task/GPS/finite-money/concurrent completion/planning PostgreSQL regressions |20 passed |
| Invoice/run/planning concurrency PostgreSQL regression set |29 passed |
| Final SQLite task/run/auth/tracking set |51 passed,2 real-PostgreSQL concurrency cases skipped |
| Final linked-credit/receipt/collection/deletion PostgreSQL set |35 passed, no skips |
| Same balance/collection compatibility set on SQLite |33 passed |
| All14-table cloud deletion/preservation proof |2 passed on actual Billing-schema PostgreSQL |

The earlier SQLite skips were four opt-in Billing source-contract checks, two
PostgreSQL/RLS checks and the real row-lock race. The PostgreSQL mirror skips were
the four source-contract checks and the separately opted-in restricted-role RLS
probe. The actual Billing-schema run enabled both contracts and the non-bypass
RLS probe. These skips therefore do not stand in for the cloud checks: those
checks were actually executed in the explicit PostgreSQL run.

Exact local audit commands used the guarded scratch runners:

```text
scratch/core-workflow-venv/Scripts/python.exe -u scratch/field_audit_runner.py tests -q -o addopts=
scratch/core-workflow-venv/Scripts/python.exe -u scratch/field_audit_pg_runner.py --billing-schema tests -q -o addopts=
scratch/core-workflow-venv/Scripts/python.exe -u scratch/field_audit_pg_runner.py --billing-schema tests/test_task_audit_regressions.py -q -o addopts=
scratch/core-workflow-venv/Scripts/python.exe -u scratch/field_audit_pg_runner.py --billing-schema tests/test_credit_balance_alignment.py tests/test_billing_alignment.py tests/test_billing_invoices.py tests/test_collections.py tests/test_business_delete_lifecycle.py -q -o addopts=
```

Frontend commands, from `frontend-task`: `node node_modules/vitest/vitest.mjs run`
and `node node_modules/vite/bin/vite.js build`.

## Recommendations and remaining proof

1. **Release gate:** deploy compatible Billing and Field builds against the same
   cloud database/secret and verify source health flags,14-day trial expiry, Pro
   denial, SSO, force logout and customer/invoice/return parity with disposable
   accounts. The isolated suite does not prove a deployed environment's settings.
2. **Phone/workday soak:** test Android/iOS location denial, coarse location,
   screen lock, backgrounding, reconnect and device replacement. The app accurately
   explains that a PWA cannot guarantee background GPS or identify mocked GPS.
3. **Lifecycle operations:** repair any pre-existing orphan Field rows separately
   after a backup; this code does not guess their former owner's identity. Run
   administrative cleanup with full Field visibility, or retain the safe409 refusal.
4. **P2 UI resilience:** standardize dependency-error/retry displays and submit locks
   in task/route/request forms. Some dependency loads currently become empty
   selectors rather than explicit retry states. This is a usability gap, not a
   verified money-loss event.
5. **Convergence and evidence:** add an owner-visible reconciliation view separating
   reported cash, Billing-confirmed receipts, remaining obligation and actual cash
   handover. An expense/reimbursement workflow and photo/signature proof are future
   product scope; current Field pages do not implement them.
6. **Consistent preferences/live updates:** fetch shared appearance for direct
   Field logins on a fresh device, and use the common change/event mechanism for
   owner dashboards and inboxes. Present freshness and retry state explicitly.
7. **Further concurrency soak:** combine owner cancel/reassign with staff completion,
   multi-invoice plans in different orders and interrupted owner confirmations.
   The two proven row races are fixed; that is not a proof of every interleaving.

No live business was registered, imported, deleted or financially repaired during
this agent review. No commit, push or production deployment was performed.
