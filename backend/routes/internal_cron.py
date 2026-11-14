"""Cloud Scheduler entry point. Never accepts an ordinary user's bearer token."""
import hmac
import logging
import os
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from services import cron_runner

router = APIRouter()
logger = logging.getLogger("bizassist.cron")


@router.post("/internal/cron/{job}", include_in_schema=False)
def invoke_cron(job: str, x_cron_secret: str = Header(default="")):
    secret = os.getenv("BILLING_CRON_SECRET", "")
    if not secret:
        raise HTTPException(404, "Not found")
    if not hmac.compare_digest(secret.encode(), x_cron_secret.encode()):
        raise HTTPException(403, "Forbidden")
    if job not in cron_runner.JOBS:
        raise HTTPException(404, "Not found")
    period = cron_runner.period_for(job)
    try:
        status = cron_runner.run(job, period)
    except Exception:
        # Log the registered handler name, not the incoming URL segment.
        logger.exception("Scheduled handler %s failed", cron_runner.JOBS[job][0].__name__)
        raise HTTPException(500, "Scheduled job failed; it will be retried")
    body = {"status":status,"job":job,"period":period}
    return JSONResponse(body, status_code=503 if status == "partial" else 409 if status == "busy" else 200,
                        headers={"Retry-After":"30"} if status in ("busy", "partial") else None)
