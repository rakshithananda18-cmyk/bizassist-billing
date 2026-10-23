"""
space_app.py — the one way the Field Team API is started when deployed.

- HF Space: new Docker Spaces need a paid plan, so the Space uses the Gradio
  SDK (README front-matter: `sdk: gradio`, `app_file: space_app.py`). HF
  installs requirements.txt, runs `python space_app.py` and routes traffic to
  port 7860. Gradio itself is not used.
- Container hosts (Dockerfile CMD, e.g. Render's free web service): the same
  file, on the port the host sets in $PORT.

ONE process — no workers, no reload: login throttling and the GPS purge loop
are in-memory (same rule as the Dockerfile and billing's WEB_CONCURRENCY=1).
"""
import os

import uvicorn

APP = "app.main:app"
PORT = int(os.environ.get("GRADIO_SERVER_PORT") or os.environ.get("PORT") or 7860)

if __name__ == "__main__":
    uvicorn.run(APP, host="0.0.0.0", port=PORT, proxy_headers=True, forwarded_allow_ips="*")
