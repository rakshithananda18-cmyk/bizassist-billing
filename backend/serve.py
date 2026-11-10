"""
serve.py — canonical production entry point for STATER Bill FastAPI backend.

Runs on every container host:
  - Google Cloud Run (Mumbai asia-south1): listens on $PORT (8080)
  - Hugging Face Spaces: listens on $PORT or fallback 7860
"""
import os
import uvicorn

APP = "main_groq:app"
PORT = int(os.environ.get("PORT") or 7860)

if __name__ == "__main__":
    uvicorn.run(
        APP,
        host="0.0.0.0",
        port=PORT,
        proxy_headers=True,
        forwarded_allow_ips="*"
    )
