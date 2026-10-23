# BizAssist Field Team — Master Plan (v0.1, 2026-10-22)

*Scope: the field-staff app of the BizAssist ecosystem (Billing → **Field Team** → AI). First customer profile: medical / pharma **wholesale distributor** delivering daily to retail medical shops.*

---

## 1. MVP requirements → what is built

| Requirement (owner's words) | Built as | Code |
|---|---|---|
| Owner login | Same username/password as BizAssist Billing (same `users` row). Signup from this app creates a billing-compatible account. SSO: the **Field Team** link in billing's sidebar opens this app with `?sso=<ticket>` — billing's 30-second single-use `/handoff-ticket`, the same hand-off as its AI dashboard — exchanged at `POST /api/auth/exchange`. | `routers/auth.py`, `security.redeem_billing_ticket`, `lib/auth.jsx` |
| Staff login, multiple people, owner sets password | Owner creates staff (`ft_staff`) and sets/resets passwords; staff sign in with **BizID + login name + password**. Billing's password policy. | `routers/staff.py` |
| Device-specific login or one device at a time | Owner setting: `single_session` (new login signs the old device out) or `bound` (locked to the first phone; owner releases it). Enforced on every request. | `security.py`, `routers/auth.py` |
| Attendance with server time and location | Check-in/out stamped with **server UTC**; phone clock kept only as evidence (skew shown to owner). Late = after `workday_start + grace` in business timezone. | `routers/attendance.py` |
| Location mandatory for tasks | Every staff write carries a GPS fix; refused if missing, (0,0) or worse than `max_accuracy_m`. Field work refused unless checked in. | `geo.py`, every staff route |
| Owner assigns tasks; done in time → points | Tasks have due time + points; on-time vs late decided by server completion time; points go to an append-only ledger. | `routers/tasks.py`, `services.award_task_points` |
| Route per calendar day, mark deliveries | Route templates (ordered shops, weekdays, default person, deliver-by) → a **run** per day per person; arrive (geofenced) → complete delivery with boxes delivered → shop done → run completed. | `routers/runs.py` |
| Tasks inside the route (return collect, etc.) | Per-shop extra tasks: `return_pickup`, `payment_collect`, `order_taking`, `stock_check`, `general`. | `models.TASK_TYPES` |
| Scorecard / incentives | Per person per period: points, on-time %, missed, deliveries, boxes, amount collected, days present/late. Incentive slabs: **to decide** (§10). | `routers/dashboard.py` |
| Item requirement list / taking orders at the shop | Staff records an order or requirement list (items, qty, unit, note) at the shop, with location; owner inbox with statuses. | `routers/requests.py` |
| Number of routes, staff glance + immediate work | Owner: dashboard, day plan. Staff: "Today" screen = duty status, route, next shop, tasks, points. | `pages/` |
| Shops + contact numbers | Shops with contact, phone (tap-to-call), address, pin. **Import from billing customers** (stays linked by `customer_id`). | `routers/shops.py` |
| Boxes per shop, orders sent for delivery | Planned per shop per day (`boxes_planned`, `orders_count`, invoice refs); delivered boxes captured at completion; dashboard totals. | `routers/runs.py` |
| Location + delivery tracking | Live map (last fix per person), day trail, event pins (check-in, arrive, task done). | `routers/tracking.py`, `pages/owner/Live.jsx` |

Verified: 50 backend tests pass on SQLite, on Postgres 16, and on Postgres with **billing's real schema** (created from billing's own models); 9 frontend unit tests; an end-to-end browser run (owner sets up → agent works the route on a phone viewport with GPS → second phone signs the first out → owner dashboard shows 2/2 deliveries, 5/5 boxes) with zero console errors.

---

## 2. Backend decision: same identity + same database, separate service

**Decision:** do **not** add this to the billing backend process; do **not** build a separate identity or database either. One Supabase Postgres, one owner account (BizID), two services.

**Repo (2026-10-22):** one repo, two services. The code moved into bizassist-billing (history kept) as **`backend-task/`** and **`frontend-task/`**, named like billing's `backend/` and `frontend-billing/` / `frontend-ai/` / `frontend-admin/`, because the two apps share a contract — billing's `users` / `customers` columns, the hand-off ticket, the `ft_*` autogenerate guard, `JWT_SECRET` — and one PR + one CI run (`.github/workflows/field-team.yml`, contract job) now covers both sides. It also shares billing's `venv`, `start_dev.bat`, `run_tests.bat` (scope `task`) and test dashboard. Deployment stays separate, the same way billing deploys: the API to its own Cloud Run service in Mumbai (`backend-task/deploy_cloudrun.ps1`), the screens to their own Vercel project (Root Directory `frontend-task`).

| Fact (checked in the repos) | Consequence |
|---|---|
| Billing's own docs: a Chroma/HNSW stall "freezes the WHOLE backend" (single process, `.env.example`, `Dockerfile` comments). | GPS pings and check-ins must not share a process with the AI stack. |
| Billing image installs tesseract, poppler, weasyprint and bakes a sentence-transformers model. | Slow rebuild + cold start; this service's image has none of it. |
| Billing has a desktop/local SQLite + cloud hybrid sync (`sync_map`, PyInstaller build, 970+ tests). | Field ops is cloud-only (a phone must reach the server). Adding tables there drags in sync/desktop concerns for no benefit. |
| Billing's role guard is a **deny-list**: `restrict_cashier` blocks only `cashier` and `supply adder` (`services/auth.py`). | A field worker stored as a billing `users` row with a new role would be treated as **owner** by every billing endpoint. Field staff therefore live in `ft_staff`, and their tokens are signed with a key billing cannot verify (tested). |
| Billing is a modular monolith on one DB, tenant key `business_id` = owner `users.id`, BizID for anything crossing databases (`core/identity.py`). | Same tenant key and same DB here → owner account, BizID and customers are shared with zero sync. |

What is shared vs owned:

| Shared (billing owns) | Owned here |
|---|---|
| `users` (owner login, BizID, `token_version` → billing "force logout" also logs out of this app), `customers` (shops import) | `ft_settings, ft_staff, ft_attendance, ft_shops, ft_routes, ft_route_stops, ft_runs, ft_run_stops, ft_tasks, ft_item_requests, ft_location_pings, ft_points_ledger, ft_activity` |
| `JWT_SECRET` value | Alembic chain with version table `ft_alembic_version`; RLS policy per `ft_*` table (same predicate as billing) |

Guard added to billing (`bizassist-billing/backend/alembic/env.py`, `include_object`): without it, `alembic revision --autogenerate` in billing against the shared DB **would drop all 14 `ft_*` tables** (measured: 14 tables before the filter, 0 after).

When to merge into one process: never needed for correctness; reconsider only if both services move to paid hardware and the AI stack is split out of billing.

---

## 3. Identity and security

- Owner token: `typ=owner`, `bid`, `uid`, `public_id`, `tv` (= billing `users.token_version`, checked every request).
- Staff token: `typ=staff`, `bid`, `sid`, `ses` (session id), `dev` (device id), `tv`, plus `public_id` (the business's BizID, read only for `[BizId=…]` log lines). All must match the `ft_staff` row; a new login rotates `ses`.
- Signing key `HMAC-SHA256(JWT_SECRET, "bizassist-task:v1")` + `aud=bizassist-task` → rejected by billing's decoder (tested both ways).
- SSO from billing: a **30-second, single-use** ticket (billing `POST /handoff-ticket`, signed `HMAC-SHA256(JWT_SECRET, "sse|…")`), verified here with the shared secret — no call to the billing Space — then the same owner checks as a login (owner role, BizID match, `token_version`). Spent tickets are remembered in-process (one worker); tickets valid for more than 60 s are refused. A full billing session token never travels in a URL.
- Every query filters `business_id` from the token; cross-tenant ids return 404 (tested). Postgres RLS on every `ft_*` table as defence in depth (verified with a non-bypass role: unscoped → 0 rows, scoped → own rows only).
- Login throttle: 10 failures / 15 min per IP + account (in-process; one worker).
- "Device" = a random id stored in the browser. Clearing site data = a new device → owner releases the old one. A native app can use a hardware-backed id (Phase 2).

---

## 4. Location — what is enforced, what a web app cannot do

Enforced server-side: fix required on every field action · accuracy ≤ `max_accuracy_m` (default 150 m) · arrival distance to the shop pin stored, flagged outside `geofence_radius_m` (default 200 m) or refused when `geofence_enforced` · first visit to an unpinned shop pins it · server time on every row.

Limits of a PWA (browser):

| Limit | Mitigation in MVP | Full fix |
|---|---|---|
| GPS stops when the screen locks / app is backgrounded (Android Chrome and iOS Safari; see sources) | Trail recorded while app is open; "Keep screen on during route" (Screen Wake Lock API); every action has its own fix; offline points buffered and replayed | Android app wrapper with a foreground location service (e.g. Capacitor + background-geolocation plugin). A TWA is still Chrome → same limit. |
| Cannot detect mock-location apps | Accuracy, distance-to-pin, server time and the trail are visible to the owner | Native: `Location.isMock()` (Android 12+) / `isFromMockProvider()` |
| GPS needs HTTPS | The screens are served by Vercel over HTTPS (and `localhost` counts as secure in dev) | — |

Storage (measured on Postgres 16, 100,000 rows): **203 bytes per ping** (heap 126 + indexes 77). 10 staff × 8 h × 1 ping/60 s = 4,800/day ≈ **0.97 MB/day**; 60-day retention ≈ **58 MB**. At 30 s, double. Server keeps at most one ping per half-interval per person and only while checked in.

---

## 5. Maps — cost

| Need | Used now | Cost |
|---|---|---|
| Navigation to a shop | **Google Maps URLs** (`/maps/dir/?api=1&destination=lat,lng`) open the Google Maps app | Free, no API key (Google docs) |
| Owner live map + trail | Leaflet + OpenStreetMap tiles (`VITE_MAP_TILE_URL` to switch) | Free; OSM policy: attribution, valid User-Agent, **no heavy use**, no SLA. One owner dashboard is light use. |
| Distance / geofence | Haversine on the server | Free |
| Geocoding addresses, route optimisation | Not used in MVP (shop pins come from owner paste/"use my location" or first visit) | — |

If Google Maps Platform is needed later (India price list, effective 2024-08-01 cut of up to 70%): free usage caps per SKU per month — **Essentials 70,000**, **Pro 35,000**, **Enterprise 7,000** (e.g. Compute Routes Essentials India: 70,000 free, then $1.50 / 1,000). Global list for comparison: 10,000 / 5,000 / 1,000. Billing account (card) required. Confirm each SKU on the India pricing page before enabling — the Dynamic Maps India cap was not confirmed in this review.

Indian alternative: Ola Maps announced 5 million free calls/month per API (July 2024) — current terms not confirmed.

**Recommendation:** stay key-less (Maps URLs + OSM) until owners ask for in-app route optimisation; then evaluate Google Routes (India caps) vs Ola Maps on real call counts.

---

## 6. Points (gamification)

| Event | Points |
|---|---|
| Task done by its due time (server clock) | the task's points (default 10, owner-set per task/stop) |
| Task done late | `late_points_pct` % of its points (default 0) |
| On-time check-in | `on_time_checkin_points` (default 5) |
| Missed task | 0, counted as "missed" on the scorecard |

Ledger is append-only (`ft_points_ledger`); completed tasks cannot be edited (409).

---

## 7. Ecosystem integration (Billing ↔ Field Team)

| Step | Status |
|---|---|
| Same owner login, BizID, `token_version` | Done |
| Shops ← billing customers (`customer_id` link) | Done |
| SSO: **Field Team** link in billing's sidebar (owner-only, like Dashboard BIZASSIST) → `?sso=<30 s ticket>` → `/api/auth/exchange` | Done in both, same repo: `frontend-billing/src/config/fieldTeam.js` (shown once billing's Vercel project has `VITE_FIELD_TEAM_URL`); the ticket format is checked against billing's own code in CI (`test_billing_contract.py`) |
| Pro plan gate on Field Team | **Decide** (D7) — billing's link has the switch (`EXTERNAL_APPS.fieldTeam.proOnly`); a real gate must also be checked here, at owner sign-in |
| Billing autogenerate guard for `ft_*` | Done (billing `alembic/env.py`) |
| Deliveries from billing invoices (pick invoices per shop → boxes, refs; optional collection of the amount due) | Done — `GET /api/shops/{id}/billing-invoices` reads the linked customer's `invoices` / `invoice_line_items`; tasks keep them in `ft_task_invoices` (one live delivery and one live collection per bill). Boxes come from box/carton/case lines. Shops added by hand link to a customer from Shops → Edit. Read-only: billing's tables are never written. B2B orders follow with retailer ordering (below), since a B2B order needs the shop to have its own BizAssist account |
| Shop request → billing B2B order / sale draft (catalogue picker) | Next |
| Collections (`payment_collect`) → billing payment (owner confirms; AI never moves money) | Next |
| Retailers ordering via BizID connections (billing D10) feeding the next day's run | Later |
| AI advisor reads `ft_*` ("which agent misses Tuesday shops") | Later |

---

## 8. Deployment (Cloud Run API in Mumbai + Vercel screens)

**Why Cloud Run (decided 2026-10-23).** Hugging Face no longer lets free accounts create Docker or CPU-basic Gradio Spaces (July 2026), and a free ZeroGPU Space refuses an app with no `@spaces.GPU` function (tried: `RUNTIME_ERROR`). Render's free web service sleeps after 15 min and takes ~1 min to wake, shares a 5 GB/month workspace bandwidth pool since 2026-08-01 (free services suspended when exceeded without a card), and may suspend free services with heavy traffic to external databases — every request here goes to Supabase. Oracle Always Free reclaims instances idle (<20% CPU/network/memory) for 7 days. Cloud Run in `asia-south1` is free at this load (request-based free tier), wakes in seconds, keeps data near India, and is where billing can follow before a public launch.

| Item | Value |
|---|---|
| Cloud Run service (API only) | `bizassist-task`, region `asia-south1` (Mumbai), built by Cloud Build from `backend-task/Dockerfile` (`deploy_cloudrun.ps1` → `gcloud run deploy --source backend-task`). Container runs `serve.py`: one uvicorn process on `$PORT` (8080). **max 1 instance** (login throttling is in-memory), **min 0** (free; wakes in seconds — `-MinInstances 1` keeps it warm, billed while idle), 1 vCPU / 512 MiB (uses ~110 MB), CPU only during requests, startup CPU boost. Runs as service account `bizassist-task-run`, which can read only its three secrets. CI builds the same image and checks `/api/health` on `$PORT`. |
| GPS retention | CPU is off between requests, so the in-process 6-hour purge loop is disabled (`TASK_PURGE_LOOP=0`). Cloud Scheduler job `bizassist-task-purge-pings` calls `POST /api/internal/purge-pings` daily at 03:30 IST with header `X-Cron-Secret` (= `TASK_CRON_SECRET`; endpoint 404s when unset). The purge runs business by business under the `ft_*` row-level security, so it also works for a database role without `BYPASSRLS`. |
| Secrets (Secret Manager) | `DATABASE_URL` (billing's Supabase **pooler** URI), `JWT_SECRET` (billing's value), `TASK_CRON_SECRET` (generated by the setup run) |
| Env vars | `TASK_PURGE_LOOP=0`, `BIZ_TIMEZONE=Asia/Kolkata`, `ALLOWED_ORIGINS` = the Vercel URL (replaces the localhost defaults; LAN/localhost stay allowed by pattern) |
| Vercel (screens) | Own project importing **bizassist-billing**, Root Directory `frontend-task`, Vite, production branch `main`, env `VITE_API_URL` = the Cloud Run service URL (`frontend-task/vercel.json` = SPA rewrite). Same arrangement as billing's `frontend-billing` / `frontend-ai` / `frontend-admin`. |
| Migrations | Automatic on start, `ft_*` only (`TASK_AUTO_MIGRATE=1`); one instance, so never concurrent |
| Google account | Free trial ($300 / 90 days) covers set-up; **upgrade to a full account before it ends** or Google stops the service. At pilot load the request-based free tier means ₹0; set a budget alert. |
| Supabase free | 500 MB database shared with billing; project pauses after 7 days idle (billing's traffic keeps it awake). At ~203 bytes per ping, 100 staff ≈ 10 MB/day → with 60-day retention ≈ 600 MB: plan **Supabase Pro** (≈$25/month, 8 GB, backups) at roughly 50–80 staff in total, or at public launch. |
| URL to give staff | **The Vercel URL** (add to home screen → installs as an app). A phone's device id is stored per web address, so the address staff install must never change — the API behind it moves by changing `VITE_API_URL` only. |

### 8.1 Go-live order (do not reorder)

Billing is mirrored to its own Hugging Face Space, and **every push there rebuilds the image**. A rebuild without the SQLAlchemy pin cannot reach Supabase (§9 #1), so billing was fixed and redeployed first.

| # | Step | Check that it worked |
|---|---|---|
| 1 | ✅ Merge billing PR #3: Alembic `ft_*` guard + SQLAlchemy `<2.1` pin (2026-10-22, `e89f107`) | PR CI green, including "Financial Invariants on Postgres" |
| 2 | ✅ Push billing `main` to the billing Space (2026-10-22; first build failed — §9 #4 — fixed by `79685a5`, live 23:14) | `/health`: `status ok, db connected, postgresql` |
| 3 | ✅ Merge billing PR #4 (`feat/field-team`): `backend-task/` + `frontend-task/` (with history), the sidebar link, `.github/workflows/field-team.yml` (2026-10-22, `088bdf1`) | Field Team workflow green, including the contract job |
| 4 | Merge the Cloud Run branch (`feat/task-cloud-run`): `serve.py`, scheduled purge endpoint, `deploy_cloudrun.ps1`, CI `image` job | Field Team workflow green, including `image` |
| 5 | Google Cloud project with billing (trial is fine — upgrade before it ends). Install the Google Cloud CLI, `gcloud auth login`, then from `main`: `.\backend-task\deploy_cloudrun.ps1 -Project <id> -Setup` (asks for `DATABASE_URL` and `JWT_SECRET` — billing's values; typed input is hidden) | Script ends with `/api/health` → `db: postgresql`; Cloud Run log shows `Running upgrade  -> 0001_ft_initial` on the first start, then `[BOOT] BizAssist Task ready db=postgresql … purge=scheduled`; Cloud Scheduler lists `bizassist-task-purge-pings` |
| 6 | Vercel → Add New → Project → import **bizassist-billing**. Root Directory `frontend-task`, Framework Vite, env `VITE_API_URL=<Cloud Run service URL>` → Deploy | The Vercel URL shows the Field Team sign-in page |
| 7 | `.\backend-task\deploy_cloudrun.ps1 -Project <id> -AllowedOrigins https://<vercel-url>` | Owner signs in on the Vercel URL; no CORS error in the browser console |
| 8 | Billing's `frontend-billing` Vercel project → env `VITE_FIELD_TEAM_URL=https://<vercel-url>` → Redeploy (Vite reads it at build time). Frontend only — no billing Space push | Billing sidebar shows **Field Team** to owners; it opens the Vercel URL already signed in |
| 9 | Owner adds one staff member, shares the BizID **and the Vercel URL** | Staff phone: sign in → Check in → location accepted |
| 10 | Pilot one distributor for 1–2 weeks (Phase 1.1, §10) | Dashboard shows real deliveries / boxes / points |

Field Team runs on its own Cloud Run service and its own Vercel project: the two apps restart, sleep and fail independently, and a Field Team deploy never rebuilds billing. Before a public launch, billing should follow to Cloud Run in Mumbai (needs one always-on instance for its in-process scheduler and AI stack — paid; its HF URL is hard-coded in 15 files incl. the desktop app, so it needs a configurable URL and a desktop update first).

---

## 9. Billing findings from this review

1. **SQLAlchemy 2.1 driver default.** Billing pins `sqlalchemy>=2.0.0` + `psycopg2-binary` only. SQLAlchemy 2.1 (2.1.6 is what pip installs today) resolves `postgresql://` to **psycopg v3**, which is not installed → a fresh billing image build fails to connect to Supabase (`ModuleNotFoundError: No module named 'psycopg'`, reproduced). **Fixed in billing PR #3** (commit `e89f107`: `sqlalchemy>=2.0.0,<2.1` in `requirements.txt`, `backend/requirements_hf.txt`, `backend/Pipfile`). Confirmed in billing CI on 2026-10-22: the commit before the pin installed `sqlalchemy-2.1.6` and the "Financial Invariants on Postgres" step failed at `database/db.py:75` with exactly this error. This service rewrites the URL to `postgresql+psycopg2://` instead.
2. **Billing's Alembic chain cannot build an empty Postgres** (`ALTER TABLE public.expenses FORCE ROW LEVEL SECURITY` fails — no migration creates `expenses`; reproduced on Postgres 16 with Supabase's `anon`/`authenticated` roles created). Production works because tables come from `create_all` at startup. Matters for disaster recovery and CI — open.
3. **Role deny-list** (§2) — open. Any future billing role must be added to `restrict_cashier`, or the guard flipped to an allow-list.
4. **Billing's HF image drifts on every requirements change** (2026-10-22 outage, ~20 min). The SQLAlchemy pin changed `requirements_hf.txt`, so the pip layer was rebuilt for the first time in months and pulled transformers 5.20 + sentence-transformers 6.2 next to the pinned `torch==2.5.1`; transformers 5 disables PyTorch below 2.6 and the MiniLM pre-bake step failed. **Fixed** by `79685a5` (`transformers<5`, `sentence-transformers<6`). Open: nothing builds the billing image before it reaches the Space — CI installs `requirements.txt` (no torch pin), not `requirements_hf.txt`. A CI `docker build` of the root `Dockerfile` (or a lock file) would have caught it.

---

## 10. Next phases and open decisions

**Phase 1.1 (owner pilot, 1–2 weeks):** deploy Cloud Run + Vercel; billing "Field Team" link (SSO, built — §7); pilot with one distributor; tune accuracy/geofence from real data.
**Phase 2:** Android wrapper (background GPS + mock-location flag); ~~deliveries from billing invoices~~ (done); shop request → B2B order draft; collections → payments; notifications (new run, overdue task).
**Phase 3:** incentive slabs and payout report; route optimisation; retailer self-ordering feeding runs; AI advisor over field data.

Decisions for the owner:

| # | Decision | Default in code |
|---|---|---|
| D1 | Device policy for this business | one device at a time |
| D2 | Geofence: flag or refuse | flag (200 m) |
| D3 | Incentive formula (₹ per point? slabs? monthly cap?) | points only |
| D4 | Ping interval vs battery (30 s / 60 s / 120 s) | 60 s |
| D5 | Native Android app for background tracking — when | Phase 2 |
| D6 | Fix billing finding #1 now | **done** — billing PR #3 |

---

## Sources

- Google Maps Platform India pricing — https://developers.google.com/maps/billing-and-pricing/pricing-india
- Google Maps Platform core pricing — https://developers.google.com/maps/billing-and-pricing/pricing
- Google Maps URLs (no key needed) — https://developers.google.com/maps/documentation/urls/get-started
- OSM tile usage policy — https://operations.osmfoundation.org/policies/tiles/
- Ola Maps free tier announcement (Jul 2024) — https://tech.olakrutrim.com/ola-maps-made-for-india-priced-for-india/
- HF Spaces hardware/sleep — https://huggingface.co/docs/hub/en/spaces-overview , https://huggingface.co/docs/huggingface_hub/main/guides/manage-spaces
- HF free Docker / CPU-basic Spaces now paid (July 2026, forum) — https://discuss.huggingface.co/t/docker-sdk-now-marked-as-paid-when-creating-a-new-space/177580
- Render free tier (spin-down, hours, outbound-traffic suspension) — https://render.com/docs/free
- Oracle Always Free idle reclamation — https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm
- Cloud Run pricing and free tier — https://cloud.google.com/run/pricing
- Supabase free limits (secondary) — https://www.jetadmin.io/blog/supabase-pricing-2026-guide-to-plans-limits-and-real-world-costs/
- Web geolocation in background (W3C discussion) — https://lists.w3.org/Archives/Public/public-geolocation/2016Feb/0016.html
