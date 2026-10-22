---
title: BizAssist Field Team
emoji: 🚚
colorFrom: red
colorTo: yellow
sdk: docker
pinned: false
app_port: 7860
---

# BizAssist Field Team — API (`backend-task/`)

Staff attendance, delivery routes, on-site tasks, shop orders and incentive points — for the owner and the field team of a business already on **BizAssist**. First vertical: **medical / pharma wholesale distribution** (daily beats to retail medical shops: boxes, orders, returns, collections).

Part of the **bizassist-billing** repo, named like billing's own folders:

```
backend/          billing API                       → HF Space BizAssist (git push space main)
backend-task/     Field Team API  (this folder)     → HF Space bizassist-task (deploy_space.ps1)
frontend-billing/ frontend-ai/ frontend-admin/      → Vercel
frontend-task/    Field Team PWA                    → Vercel (Root Directory frontend-task)
docs/FIELD_TEAM_MASTER_PLAN.md                      → why, security, go-live order
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

`task` runs `backend-task` (pytest; `fast` = all cores, pytest-xdist) and `frontend-task` (vitest). Results stream into the root `test_results.json`, so billing's live test dashboard shows them. In CI: `.github/workflows/field-team.yml`, which also runs on the billing files Field Team depends on and has a **contract** job — this suite on billing's real schema, plus tickets minted by billing's own code (`tests/test_billing_contract.py`). Postgres locally: `TASK_TEST_DATABASE_URL=postgresql://…/task_test`, serial.

## Logging — billing's format

```
22:47:23 INFO  task                   [BizId=BA-D686P8] [FIELD] biz=1 actor=staff:1 action=attendance.check_in attendance#1
```

Time · level · component · `[BizId=…]` of the caller (set per request in `app/main.py` middleware, `-` when signed out) · `[TAG]` (`app/logging_config.py`: BOOT, AUTH, FIELD, TRACK, HTTP). `LOG_LEVEL`, `LOG_FILE` (rotating, 5 MB × 3), `LOG_FORMAT=json` (ECS fields, `service.name=bizassist-task`), `NO_COLOR`.

## Deploy — API to its Space, screens to Vercel (like billing)

1. **Space:** create one → **Docker** → blank, **Public**. Settings → **Secrets** *before the first push*: `DATABASE_URL` = the billing Space's Supabase URL, `JWT_SECRET` = the billing Space's value. Then from the repo root `.\backend-task\deploy_space.ps1 -FirstPush` (later: without `-FirstPush`; `-DryRun` to preview). The Space gets this folder as its root (`git subtree split`); the front-matter above configures it. Billing's own `git push space main` is unaffected.
2. **Vercel:** import **bizassist-billing** again → Root Directory `frontend-task` → Vite → env `VITE_API_URL=https://<owner>-<space>.hf.space` → Deploy.
3. **Space → Variables:** `ALLOWED_ORIGINS=https://<vercel-url>`.
4. **Billing:** `VITE_FIELD_TEAM_URL=https://<vercel-url>` on billing's `frontend-billing` Vercel project → redeploy → owners get the **Field Team** link.
5. Give staff the BizID and **the Vercel URL** (device ids are per address, so it must not change later).

Full order with checks: [docs/FIELD_TEAM_MASTER_PLAN.md §8.1](../docs/FIELD_TEAM_MASTER_PLAN.md).
