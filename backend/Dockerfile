# ──────────────────────────────────────────────────────────────────────────────
# BizAssist Backend — Hugging Face Spaces Docker image
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
    HF_HUB_DISABLE_SYMLINKS_WARNING=1

WORKDIR /app

# Install system build tools (needed for some packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (as root, before switching user)
COPY --chown=user requirements_hf.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements_hf.txt

# Pre-bake the embedding model into the image (22MB — avoids cold-start download)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Copy application source and set ownership
COPY --chown=user . /app

# Create writable runtime directories AS ROOT, then hand ownership to user
RUN mkdir -p /app/chroma_db && chown -R user:user /app

# Switch to non-root user for runtime
USER user

EXPOSE 7860

CMD ["uvicorn", "main_groq:app", "--host", "0.0.0.0", "--port", "7860"]

