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
frontend/   React 18 + Vite PWA, billing's design tokens and icon set, Leaflet map
Dockerfile  HF Spaces (Docker SDK, port 7860): builds the PWA, serves it + the API
```

## Run locally

```bash
# API (http://localhost:8002) — SQLite, standalone
python -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt
cp .env.example backend/.env            # set JWT_SECRET (>= 32 chars)
cd backend && ../.venv/bin/uvicorn app.main:app --port 8002 --reload

# PWA (http://localhost:5176, proxies /api → :8002)
cd frontend && npm install && npm run dev
```

GPS in the browser needs `https://` or `localhost`. To test on a phone, use the deployed Space URL.

## Tests

```bash
cd backend && ../.venv/bin/python -m pytest              # 50 tests, SQLite
TASK_TEST_DATABASE_URL=postgresql://…/task_test ../.venv/bin/python -m pytest   # same suite on Postgres
cd frontend && npm test                                   # 9 unit tests
```

## Deploy (Hugging Face Space)

1. Create a Space → **Docker** → blank. Push this repo to it (the front-matter above configures the Space).
2. Space → Settings → **Secrets**: `DATABASE_URL` = the billing Space's Supabase URL, `JWT_SECRET` = the billing Space's value.
3. Open `https://<owner>-<space>.hf.space` directly (not the huggingface.co page — its iframe does not pass GPS permission).
4. Owner signs in with the billing username/password → Staff → add people → share the BizID shown in the sidebar.

Details, costs and limits: [docs/MASTER_PLAN.md §8](docs/MASTER_PLAN.md#8-deployment-hugging-face).
