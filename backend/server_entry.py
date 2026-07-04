"""
server_entry.py — PyInstaller entry point for the bundled desktop backend.

The Electron shell spawns:  bizassist-backend --host 127.0.0.1 --port 8001
and sets BIZASSIST_DATA_DIR to the per-user app-data folder so the SQLite DB
survives app updates/reinstalls.

Build:  pyinstaller bizassist-backend.spec   (see desktop/scripts/build-backend.*)
"""
from __future__ import annotations  # PEP 604 (X | Y) on Python 3.9 dev venvs
import argparse
import multiprocessing
import os
import sys
from pathlib import Path


def _ensure_jwt_secret(data_dir: str | None) -> None:
    """
    services/auth.py hard-fails without JWT_SECRET. The packaged app ships no
    .env (secrets never go inside the exe), so resolve one at runtime:

      1. Already in the environment → use it.
      2. .env in the data dir → loaded (lets users share the cloud's secret,
         REQUIRED for hybrid sync: local-signed tokens must verify on the cloud).
      3. Otherwise generate once and persist to <data_dir>/jwt-secret so local
         sessions survive restarts. (Hybrid sync will 401 until the user drops
         the shared secret into .env — local & cloud-mode use is unaffected.)
    """
    if os.environ.get("JWT_SECRET"):
        return

    base = Path(data_dir or ".")
    env_file = base / ".env"
    if env_file.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_file)
        except Exception:
            pass
        if os.environ.get("JWT_SECRET"):
            return

    secret_file = base / "jwt-secret"
    if secret_file.exists():
        secret = secret_file.read_text(encoding="utf-8").strip()
    else:
        import secrets as _secrets
        secret = _secrets.token_urlsafe(48)
        secret_file.write_text(secret, encoding="utf-8")
    os.environ["JWT_SECRET"] = secret


def _configure_environment() -> None:
    """Point the DB (and any relative-path assets) at a stable, writable dir."""
    data_dir = os.environ.get("BIZASSIST_DATA_DIR")
    if data_dir:
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        # database/db.py: DATABASE_URL defaults to sqlite:///./bizassist.db
        os.environ.setdefault(
            "DATABASE_URL",
            "sqlite:///" + str(Path(data_dir, "bizassist.db")).replace("\\", "/"),
        )
        # Relative writes (logs, chroma_db, uploads) land in the data dir too.
        os.chdir(data_dir)

    _ensure_jwt_secret(data_dir)

    # Frozen builds: make bundled packages importable & silence __pycache__.
    if getattr(sys, "frozen", False):
        os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")


def main() -> None:
    multiprocessing.freeze_support()  # REQUIRED before anything else on Windows

    parser = argparse.ArgumentParser(description="BizAssist local backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()

    _configure_environment()

    import uvicorn
    from app import app  # FastAPI instance (re-export of main_groq:app)

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        workers=1,          # single process — PyInstaller-safe
        log_level="info",
        access_log=False,   # keep the desktop log quiet
    )


if __name__ == "__main__":
    main()
