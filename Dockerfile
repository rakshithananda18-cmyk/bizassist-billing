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
    LOG_FILE=logs/bizassist.log \
    TZ=Asia/Kolkata \
    BIZ_TIMEZONE=Asia/Kolkata

# ── CHAT_MEMORY_ENABLED — set this as a SPACE VARIABLE, not here ─────────────
#
# Semantic recall of past conversations, injected into AI_SIMPLE prompts. It
# defaults OFF in code (services/embeddings.py) and production turns it on:
#
#     Space → Settings → Variables → CHAT_MEMORY_ENABLED = 1
#
# A variable, not a secret — it is a policy flag, not a credential, and it should
# be readable by anyone looking at why the Space behaves as it does.
#
# WHY IT IS SAFE HERE, AND ONLY HERE. The freeze that forced this switch is a
# native, GIL-holding block inside Chroma's persisted HNSW index, and it needs
# two processes touching one index. Development creates exactly that:
# `uvicorn --reload` runs a reloader AND a worker, and both import the app. The
# CMD at the bottom of this file does not — one uvicorn process, no --reload, no
# --workers — and within it every Chroma call is serialised by
# `_LockedCollection`. **If --workers is ever added to that CMD, clear the Space
# variable in the same change.**
#
# WHY NOT `ENV` ON THIS LINE. It is an incident switch, and its whole value is
# how fast it can be flipped. Baked into the image, turning it off costs a
# commit, a push and a full rebuild — and this image apt-installs tesseract and
# poppler, so that is minutes with the backend frozen. A Space variable is a
# toggle and a restart. Space variables also override image ENV, so setting it
# both places would leave two sources of truth for one flag.

WORKDIR /app

# Install system build tools (needed for some packages) + weasyprint system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential gcc \
        libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
        libgdk-pixbuf-2.0-0 libharfbuzz0b libffi-dev shared-mime-info \
        # OCR fallback for bill uploads. `pytesseract` and `pdf2image` are only
        # PYTHON WRAPPERS — they import fine without these, so the code's
        # ImportError guard never fires and the failure surfaced instead as a
        # pdf2image/Tesseract error telling the owner to pip install packages
        # that were already installed. tesseract-ocr is the OCR engine itself;
        # poppler-utils is what pdf2image shells out to.
        # This is a Docker SDK Space, so `packages.txt` is ignored — system
        # packages have to be here.
        tesseract-ocr poppler-utils \
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
