---
title: BizAssist
emoji: 📊
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# BizAssist API

Production runs on Google Cloud Run in `asia-south1`:
`https://staterbill-api-1076771386585.asia-south1.run.app`.
Billing is served at `https://staterbill.com`; Field Team and the AI dashboard
retain their Vercel addresses. `GET /health` must report `status: ok` and
`db: connected` before traffic moves to a new revision.

Deploy from the repository root with `backend/deploy_cloudrun.ps1 -Project
staterbill -Setup` (first deployment) or `bash backend/deploy_cloudrun.sh
--setup staterbill`. Later deploys omit Setup. Both scripts preserve unmanaged
variables and secrets, keep one instance/worker, allow scale-to-zero, check a
release candidate before moving traffic, and configure external scheduled jobs.

Keep DATABASE_URL, JWT_SECRET, GROQ_API_KEY and BILLING_CRON_SECRET in Secret
Manager. Field Team must use the same database and signing secret. A constrained
runtime needs ADMIN_SERVICE_URL for privileged admin operations. Set public
settings through --update-env-vars. Uploaded diagnostic archives, handoff replay
records, session revocations, discovery and scheduler state live in PostgreSQL.
Vector/file storage requires a separately configured durable store.

The old Hugging Face Space becomes the compatibility proxy from
`ops/hf-forwarder/` so already-installed desktops can sync while users upgrade.
The Space front matter above remains for compatibility; production VITE_API_URL
must point to Cloud Run.

Before release, back up the database and apply `python -m alembic upgrade head`
with the schema operator's private environment. Current head is
`h4_auth_admin_runtime_state`. Startup verifies constrained runtime readiness;
a privileged startup serializes migration work under one advisory lock and
skips unchanged schemas. Additive control tables permit application rollback
without dropping data. Field Team owns its separate `ft_*` migration chain.

Follow [the migration runbook](../docs/runbooks/cloud-run-migration.md) for deploy
order, environment variables, verification, and rollback.
