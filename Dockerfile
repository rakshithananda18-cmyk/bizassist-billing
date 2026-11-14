# ──────────────────────────────────────────────────────────────────────────────
# BizAssist / STATER Bill — Production Root Docker image
# SDK: Docker  |  Port: $PORT (Cloud Run default 8080, HF default 7860)
# ──────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim

# Create a non-root user (recommended by HF docs & Cloud Run)
RUN useradd -m -u 1000 user
ENV HOME=/home/user \
    PATH="/home/user/.local/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BIND_HOST=0.0.0.0 \
    HF_HOME=/home/user/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/home/user/.cache/sentence_transformers \
    HF_HUB_DISABLE_SYMLINKS_WARNING=1 \
    ADMIN_API_ENABLED=1 \
    LOG_FILE=logs/bizassist.log \
    TZ=Asia/Kolkata \
    BIZ_TIMEZONE=Asia/Kolkata

WORKDIR /app

# Install system build tools + WeasyPrint PDF deps + Tesseract OCR
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential gcc \
        libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
        libgdk-pixbuf-2.0-0 libharfbuzz0b libffi-dev shared-mime-info \
        tesseract-ocr poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY --chown=user backend/requirements_hf.txt backend/requirements_hf.lock ./
RUN pip install --no-cache-dir --only-binary=:all: --require-hashes -r requirements_hf.lock

# Pre-bake the embedding model into the image (22MB — avoids cold-start download)
RUN mkdir -p /home/user/.cache && chown user:user /home/user/.cache
USER user
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
USER root

# Copy ONLY the backend directory to /app
COPY --chown=user backend/ /app/

# Create writable runtime directories AS ROOT, then hand ownership to user
RUN mkdir -p /app/chroma_db && chown -R user:user /app

# Switch to non-root user for runtime
USER user

EXPOSE 7860 8080

CMD ["python", "serve.py"]
