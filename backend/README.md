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

Build context is this folder: `Dockerfile` + `requirements_hf.txt` here.

## Required Space secrets / variables
Set these in **Settings → Variables and secrets**:

| Name | Type | Notes |
|---|---|---|
| `GROQ_API_KEY` | secret | required — LLM tiers + router |
| `JWT_SECRET` | secret | required — random string |
| `EMAIL_USER` / `EMAIL_PASS` / `EMAIL_FROM` | secret | optional — real reminder emails |
| `LLM_ROUTER` | variable | `off` (default) / `shadow` / `on` |
| `AGENT_MODE` | variable | `pipeline` (default) / `loop` |
| `INTENT_ROUTER` | variable | `off` / `shadow` / `on` |
| `ALLOWED_ORIGINS` | variable | comma-separated; add your Vercel URL if it differs from the defaults |

> ⚠ **Storage is ephemeral.** SQLite (`bizassist.db`), `chroma_db/`, and uploads
> reset on every Space rebuild/restart. For durable data, attach HF persistent
> storage and point `DATABASE_URL` at `/data/…`.

The full project (frontend + docs) lives in the main repository.
