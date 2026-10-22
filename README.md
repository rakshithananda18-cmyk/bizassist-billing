---
title: BizAssist Field Team
emoji: 🚚
colorFrom: red
colorTo: yellow
sdk: docker
pinned: false
app_port: 7860
---

# BizAssist Field Team (`bizassist-task`)

Staff attendance, delivery routes, on-site tasks, shop orders and incentive points — for the owner and the field team of a business already on **BizAssist**.

First vertical: **medical / pharma wholesale distribution** (daily beats to retail medical shops: boxes, orders, returns, collections).

| Who | Gets |
|---|---|
| Owner (desktop or phone) | Dashboard · live map + GPS trail · day plan per route · tasks · shops (import from Billing customers) · routes · staff + devices · attendance register · shop requests · scorecard · activity · settings |
| Staff (phone, installable PWA) | Check in/out · today's route with shop, phone (tap to call), navigation (Google Maps) · arrive (geofenced) · complete delivery / return / collection tasks · skip with reason · shop order / requirement list · points & score |

**Rules enforced by the server:** owner sets every staff password · one device at a time, or locked to one phone · every staff action needs a GPS fix within the accuracy limit · all times are server time · field work only while checked in · points only for work done by the due time · points are an append-only ledger.

## Architecture (one line)

Same identity and same database as BizAssist Billing, separate lightweight service: owners sign in with their **billing account**, shops can be **imported from billing customers**, all field tables are `ft_*` in the shared Supabase Postgres. Why, and what was verified: **[docs/MASTER_PLAN.md](docs/MASTER_PLAN.md)**.

```
backend/    FastAPI + SQLAlchemy 2 + Alembic (ft_* tables, version table ft_alembic_version)
frontend/   React 18 + Vite PWA, billing's design tokens and icon set, Leaflet map → its own Vercel project
Dockerfile  HF Spaces (Docker SDK, port 7860): the API (also serves a copy of the PWA)
```

Opened from billing like Dashboard BIZASSIST: the owner-only **Field Team** link in billing's sidebar opens this app's Vercel URL with `?sso=<ticket>` (billing's 30-second single-use hand-off ticket), and the owner lands signed in.

## Run locally (same as billing: `start_dev.bat`)

```bat
start_dev.bat
```

- **API** `http://127.0.0.1:8002` (uvicorn `--reload`, SQLite `backend/bizassist_task.db`, standalone).
- **PWA** `http://localhost:5176` (Vite; `/api` is proxied to `:8002`).
- **Log** `backend/logs/bizassist_task.log`.
- First run creates `.venv`, installs `backend/requirements-dev.txt` and copies `.env.example` to `backend/.env`. Stale processes on 8002 / 5176 are killed first.

GPS in the browser needs `https://` or `localhost`. To test on a phone, use the deployed URL.

## Tests (same as billing: `run_tests.bat`)

```bat
run_tests.bat fast
```

| Command | Runs |
|---|---|
| `run_tests.bat` | backend (pytest) + frontend (vitest), serial |
| `run_tests.bat fast` | both; backend in parallel across all cores (pytest-xdist, `--dist loadscope`) |
| `run_tests.bat backend fast` / `run_tests.bat frontend` | one suite |
| `.\run_tests.ps1 all -Fast -NoDashboard` | no live dashboard, no "press Enter" (scripts, CI) |

A live dashboard (`serve_dashboard.py`, from port 8090) opens in the browser and follows `test_results.json`, which `backend/tests/conftest.py` writes as tests finish — same file and schema as billing. Postgres: `TASK_TEST_DATABASE_URL=postgresql://…/task_test` with a serial run (workers would race the startup migration).

## Logging (same format as billing)

```
22:47:23 INFO  task                   [BizId=BA-D686P8] [FIELD] biz=1 actor=staff:1 action=attendance.check_in attendance#1
```

Time · level · component (logger name without `bizassist.`) · `[BizId=…]` of the caller (set per request in `main.py` middleware, `-` when signed out) · `[TAG]` (`app/logging_config.py`: BOOT, AUTH, FIELD, TRACK, HTTP). `LOG_LEVEL`, `LOG_FILE` (rotating, 5 MB × 3), `LOG_FORMAT=json` (ECS fields, `service.name=bizassist-task`), `NO_COLOR`.

## Deploy (Hugging Face API + Vercel screens, like billing)

1. **Space:** create one → **Docker** → blank, **Public**. Settings → **Secrets** *before the first push*: `DATABASE_URL` = the billing Space's Supabase URL, `JWT_SECRET` = the billing Space's value. Push this repo (the front-matter above configures the Space).
2. **Vercel:** import this repo → Root Directory `frontend` → Vite → env `VITE_API_URL=https://<owner>-<space>.hf.space` → Deploy.
3. **Space → Variables:** `ALLOWED_ORIGINS=https://<vercel-url>`.
4. **Billing:** set `VITE_FIELD_TEAM_URL=https://<vercel-url>` on billing's `frontend-billing` Vercel project and redeploy → owners get the **Field Team** link.
5. Owner signs in (or uses the link) → Staff → add people → give staff the BizID and **the Vercel URL** (device ids are per address, so it must not change later).

Full order with checks: [docs/MASTER_PLAN.md §8.1](docs/MASTER_PLAN.md#81-go-live-order-do-not-reorder).
