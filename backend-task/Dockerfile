# ──────────────────────────────────────────────────────────────────────────────
# BizAssist Task (Field Team) API — Hugging Face Spaces, Docker SDK, port 7860.
#
# Built from backend-task/ as the Space's root (deploy_space.ps1 pushes this
# folder, split out of bizassist-billing). API only, like the billing Space:
# the screens are frontend-task/ on their own Vercel project, which staff
# install — so this image has no Node build stage.
#
# Same base image and non-root user as the billing Space (../Dockerfile).
# Deliberately LIGHT: no OCR, no PDF, no ML model — so a cold start after the
# free tier's 48 h sleep takes seconds.
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
EXPOSE 7860

# ONE process: login throttling and the GPS-purge loop are in-memory (same rule
# as billing's WEB_CONCURRENCY=1). Never add --workers or --reload here.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860", "--proxy-headers", "--forwarded-allow-ips", "*"]
