# BizAssist Field Team — API (`backend-task/`)

Staff attendance, delivery routes, on-site tasks, shop orders and incentive points — for the owner and the field team of a business already on **BizAssist**. First vertical: **medical / pharma wholesale distribution** (daily beats to retail medical shops: boxes, orders, returns, collections).

Part of the **bizassist-billing** repo, named like billing's own folders:

```
backend/          billing API                       → HF Space BizAssist (git push space main)
backend-task/     Field Team API  (this folder)     → Google Cloud Run, Mumbai (deploy_cloudrun.ps1)
frontend-billing/ frontend-ai/ frontend-admin/      → Vercel
frontend-task/    Field Team PWA                    → Vercel (Root Directory frontend-task)
docs/FIELD_TEAM_MASTER_PLAN.md                      → why, security, hosting, go-live order
```

Same identity and database as billing, separate service: owners sign in with their **billing account** (or open **Field Team** from billing's sidebar — a 30-second hand-off ticket, `?sso=`), shops can be **imported from billing customers**, and every Field Team table is `ft_*` in the shared Supabase Postgres, migrated by this folder's own Alembic chain (version table `ft_alembic_version`) at start-up. Why a separate service: [docs/FIELD_TEAM_MASTER_PLAN.md §2](../docs/FIELD_TEAM_MASTER_PLAN.md).

| Who | Gets |
|---|---|
| Owner (desktop or phone) | Dashboard · live map + GPS trail · day plan per route · tasks · shops (import from Billing customers) · routes · staff + devices · attendance register · shop requests · scorecard · activity · settings |
| Staff (phone, installable PWA) | Check in/out · today's route with shop, phone (tap to call), navigation (Google Maps) · arrive (geofenced) · complete delivery / return / collection tasks · skip with reason · shop order / requirement list · points & score |

**Rules enforced by the server:** owner sets every staff password · one device at a time, or locked to one phone · every staff action needs a GPS fix within the accuracy limit · all times are server time · field work only while checked in · points only for work done by the due time · points are an append-only ledger.

## Run locally — billing's `start_dev.bat`

From the repo root, `start_dev.bat` starts billing **and** Field Team:

- **Field Team API** `http://127.0.0.1:8002` (`--reload`, SQLite `backend-task/bizassist_task.db`, standalone), log `backend-task/logs/bizassist_task.log`.
- **Field Team PWA** `http://localhost:5176` (Vite; `/api` is proxied to `:8002`).
- Uses billing's `venv` (billing's `requirements.txt` covers everything here). The first run copies `backend-task/.env.example` to `backend-task/.env`.

GPS in the browser needs `https://` or `localhost`; to test on a phone, use the deployed Vercel URL.

## Tests — billing's `run_tests.bat`

```bat
run_tests.bat task fast
```

`task` runs `backend-task` (pytest; `fast` = all cores, pytest-xdist) and `frontend-task` (vitest). Results stream into the root `test_results.json`, so billing's live test dashboard shows them. In CI: `.github/workflows/field-team.yml`, which also runs on the billing files Field Team depends on, builds the Cloud Run image and checks it serves `/api/health` on `$PORT`, and has a **contract** job — this suite on billing's real schema, plus tickets minted by billing's own code (`tests/test_billing_contract.py`). Postgres locally: `TASK_TEST_DATABASE_URL=postgresql://…/task_test`, serial.

## Logging — billing's format

```
22:47:23 INFO  task                   [BizId=BA-D686P8] [FIELD] biz=1 actor=staff:1 action=attendance.check_in attendance#1
```

Time · level · component · `[BizId=…]` of the caller (set per request in `app/main.py` middleware, `-` when signed out) · `[TAG]` (`app/logging_config.py`: BOOT, AUTH, FIELD, TRACK, HTTP). `LOG_LEVEL`, `LOG_FILE` (rotating, 5 MB × 3), `LOG_FORMAT=json` (ECS fields, `service.name=bizassist-task`), `NO_COLOR`. On Cloud Run, logs go to Cloud Logging.

## Deploy — API to Cloud Run (Mumbai), screens to Vercel

One-time, in Google Cloud (project with billing enabled; the free trial works, but **upgrade to a full account before it ends** or Google stops the service):

1. Install the Google Cloud CLI and sign in: `gcloud auth login`.
2. From the repo root: `.\backend-task\deploy_cloudrun.ps1 -Project <project-id> -Setup` — enables the APIs, asks for `DATABASE_URL` (billing's Supabase **pooler** URI) and `JWT_SECRET` (billing's value) and stores them in Secret Manager (typed values are hidden), generates `TASK_CRON_SECRET`, creates the `bizassist-task-run` service account that can read only those, deploys, schedules the daily GPS purge (Cloud Scheduler, 03:30 IST) and checks `/api/health` reports `db: postgresql`.
3. Later deploys: the same script without `-Setup`.

Service shape: **max 1 instance** (login throttling is in-memory, one process like billing), **min 0** (free tier; wakes in a few seconds — `-MinInstances 1` keeps it warm, billed for idle time), CPU only during requests, so the in-process purge loop is off (`TASK_PURGE_LOOP=0`) and Cloud Scheduler calls `POST /api/internal/purge-pings` with `X-Cron-Secret`. The purge works business by business under the `ft_*` row-level security.

Then, as in [docs/FIELD_TEAM_MASTER_PLAN.md §8.1](../docs/FIELD_TEAM_MASTER_PLAN.md):

4. **Vercel:** import **bizassist-billing** again → Root Directory `frontend-task` → Vite → env `VITE_API_URL=<Cloud Run service URL>` → Deploy.
5. **CORS:** `.\backend-task\deploy_cloudrun.ps1 -Project <id> -AllowedOrigins https://<vercel-url>` (kept on later deploys).
6. **Billing:** `VITE_FIELD_TEAM_URL=https://<vercel-url>` on billing's `frontend-billing` Vercel project → redeploy → owners get the **Field Team** link.
6a. **Pro plan:** Field Team is part of BizAssist Pro. Grant Pro to each business that uses it in billing's admin console (your own first), then `.\backend-task\deploy_cloudrun.ps1 -Project <id> -ProGate on` (kept on later deploys; `-ProGate off` turns it off). Businesses not on Pro are refused with a clear message; an expired plan keeps working for `TASK_PRO_GRACE_DAYS` (7) days while the owner sees a renewal warning. Same rule as billing's `effective_plan` (checked in CI).
7. Give staff the BizID and **the Vercel URL** (device ids are per address, so it must not change later; the API behind it can move freely).
