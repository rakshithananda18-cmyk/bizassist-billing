# ──────────────────────────────────────────────────────────────────────────────
# BizAssist — Hugging Face Spaces Root Docker image
# SDK: Docker  |  Port: 7860  |  Free tier: 2vCPU, 16GB RAM
# ──────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim

# HF Spaces: create a non-root user (recommended by HF docs)
RUN useradd -m -u 1000 user
ENV PATH="/home/user/.local/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/home/user/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/home/user/.cache/sentence_transformers \
    HF_HUB_DISABLE_SYMLINKS_WARNING=1 \
    ADMIN_API_ENABLED=1 \
    LOG_FILE=logs/bizassist.log

WORKDIR /app

# Install system build tools (needed for some packages) + weasyprint system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential gcc \
        libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
        libgdk-pixbuf-2.0-0 libharfbuzz0b libffi-dev shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
# Note: Since this is built from the root context, we copy from backend/
COPY --chown=user backend/requirements_hf.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements_hf.txt

# Pre-bake the embedding model into the image (22MB — avoids cold-start download)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Copy ONLY the backend directory to /app
COPY --chown=user backend/ /app/

# Create writable runtime directories AS ROOT, then hand ownership to user
RUN mkdir -p /app/chroma_db && chown -R user:user /app

# Switch to non-root user for runtime
USER user

EXPOSE 7860

# We are in /app, which contains the backend code now.
CMD ["uvicorn", "main_groq:app", "--host", "0.0.0.0", "--port", "7860"]
