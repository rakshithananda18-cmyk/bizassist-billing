# ──────────────────────────────────────────────────────────────────────────────
# BizAssist Task (Field Team) API — container image.
#
# Production: Google Cloud Run, Mumbai (asia-south1), built from this folder by
# deploy_cloudrun.ps1 (`gcloud run deploy --source backend-task`). API only,
# like billing: the screens are frontend-task/ on their own Vercel project,
# which staff install — so no Node build stage. CI builds this image and checks
# it serves /api/health on $PORT before anything reaches Cloud Run.
#
# Same base image and non-root user as billing's image (../Dockerfile).
# Deliberately LIGHT (no OCR, no PDF, no ML model): about 110 MB in memory, and
# a Cloud Run cold start takes seconds.
# ──────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

RUN useradd -m -u 1000 user
ENV PATH="/home/user/.local/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Kolkata \
    BIZ_TIMEZONE=Asia/Kolkata

WORKDIR /app
COPY --chown=user requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY --chown=user . /app/

USER user
EXPOSE 8080

# serve.py: ONE uvicorn process (login throttling is in-memory — never add
# workers or reload), on $PORT (Cloud Run sets 8080), else 7860.
CMD ["python", "serve.py"]
