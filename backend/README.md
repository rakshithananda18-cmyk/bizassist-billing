---
title: BizAssist
emoji: 📊
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# BizAssist — API (backend)

This Hugging Face Space runs the **BizAssist FastAPI backend** as a Docker image
(port 7860). The React frontend is deployed separately (Vercel) and points its
`VITE_API_URL` at this Space.

The configured Space builds from the repository's root `Dockerfile`, which
copies this backend and installs `backend/requirements_hf.txt`. The Dockerfile
inside this folder supports a separately configured backend-only build.

## Required Space secrets / variables
Set these in **Settings → Variables and secrets**:

| Name | Type | Notes |
|---|---|---|
| `DATABASE_URL` | secret | PostgreSQL connection; never store a credential-bearing URL as a public variable |
| `GROQ_API_KEY` | secret | required — LLM tiers + router |
| `JWT_SECRET` | secret | required — random string |
| `EMAIL_USER` / `EMAIL_PASS` / `EMAIL_FROM` | secret | optional — real reminder emails |
| `LLM_ROUTER` | variable | `off` (default) / `shadow` / `on` |
| `AGENT_MODE` | variable | `pipeline` (default) / `loop` |
| `INTENT_ROUTER` | variable | `off` / `shadow` / `on` |
| `ALLOWED_ORIGINS` | variable | comma-separated; add your Vercel URL if it differs from the defaults |

Space-local SQLite, vector indexes and uploads are ephemeral unless persistent
storage is configured. The current cloud deployment uses PostgreSQL for its
application database; persistent file/vector storage is a separate setting.

## Schema upgrades

Current Billing Alembic head is `e70b5d2a4c06`. From this folder, use the schema
operator's private environment to run `python -m alembic current`, then
`python -m alembic upgrade head` after a verified backup. The operator needs the
privileges in [the deployment contract](../docs/audit/2026-10-31/implementation/trust-role-deployment.md).
Re-running the upgrade is supported. Startup's additive schema checks do not
replace recording the Alembic revision. Field owns its separate `ft_*` chain.

The [31 October deployment record](../docs/audit/2026-10-31/DEPLOYMENT.md)
separates applied upgrades from remaining role, credential and data-review work.

The full project (frontend + docs) lives in the main repository.
