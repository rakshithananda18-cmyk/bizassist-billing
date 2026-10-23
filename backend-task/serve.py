"""
serve.py — the one way the Field Team API is started when deployed.

The Dockerfile's CMD runs it on every container host — Google Cloud Run in
production (asia-south1, see deploy_cloudrun.ps1) — on the port the host sets
in $PORT (Cloud Run: 8080), else 7860.

ONE process — no workers, no reload: login throttling is in-memory (same rule
as billing's WEB_CONCURRENCY=1), which is why Cloud Run runs at most one
instance. GPS retention there comes from Cloud Scheduler calling
POST /api/internal/purge-pings, not the in-process loop (TASK_PURGE_LOOP=0).
"""
import os

import uvicorn

APP = "app.main:app"
PORT = int(os.environ.get("PORT") or 7860)

if __name__ == "__main__":
    uvicorn.run(APP, host="0.0.0.0", port=PORT, proxy_headers=True, forwarded_allow_ips="*")
