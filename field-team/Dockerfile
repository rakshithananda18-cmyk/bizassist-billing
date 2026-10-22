# ──────────────────────────────────────────────────────────────────────────────
# BizAssist Task (Field Team) — Hugging Face Spaces, Docker SDK, port 7860.
# One container: FastAPI API + the built PWA served at "/" (same origin, HTTPS
# on *.hf.space — browsers only share GPS with secure origins).
#
# Same base image and non-root user as the billing Space
# (bizassist-billing/Dockerfile). Deliberately LIGHT: no OCR, no PDF, no ML
# model — so a cold start after the free tier's 48 h sleep takes seconds.
# ──────────────────────────────────────────────────────────────────────────────

# ── 1. Build the PWA ─────────────────────────────────────────────────────────
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# Same-origin API: leave VITE_API_URL empty so the app calls /api on this Space.
RUN npm run build

# ── 2. API runtime ───────────────────────────────────────────────────────────
FROM python:3.11-slim

RUN useradd -m -u 1000 user
ENV PATH="/home/user/.local/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Kolkata \
    BIZ_TIMEZONE=Asia/Kolkata \
    TASK_STATIC_DIR=/app/static

WORKDIR /app
COPY --chown=user backend/requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY --chown=user backend/ /app/
COPY --from=web --chown=user /web/dist /app/static

USER user
EXPOSE 7860

# ONE process: login throttling and the GPS-purge loop are in-memory (same rule
# as billing's WEB_CONCURRENCY=1). Never add --workers or --reload here.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860", "--proxy-headers", "--forwarded-allow-ips", "*"]
