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


def _read_wrapped_secret(wrapped_file: Path) -> str | None:
    """Unwrap <data_dir>/jwt-secret.dpapi, or None if it cannot be read.

    None covers the cases that matter: a different Windows user, a reinstalled
    profile, a data directory restored onto another machine. The caller mints a
    fresh secret — which costs everyone a re-login and nothing else, because this
    secret signs SESSIONS, not data. (Hybrid installs take their secret from
    `.env` above and never reach this path at all.)
    """
    if not wrapped_file.exists():
        return None
    from core import dpapi
    plain = dpapi.unprotect(wrapped_file.read_bytes())
    if plain is None:
        print("[server_entry] jwt-secret.dpapi could not be unwrapped on this "
              "machine/profile — minting a fresh secret. Everyone signs in "
              "again; no data is affected.", file=sys.stderr)
        return None
    return plain.decode("utf-8").strip()


def _persist_secret(base: Path, secret: str) -> None:
    """Write the secret DPAPI-wrapped when possible, plaintext when not.

    The plaintext fallback is for Linux/macOS dev and CI, where there is no
    DPAPI. It is stated out loud rather than silently degraded, because a
    "secret at rest" that is sometimes not is exactly the kind of thing that
    gets believed.

    The legacy plaintext file is removed ONLY after the wrapped copy has been
    read back successfully. Deleting first and failing second would lock the
    owner out of their own sessions to gain nothing.
    """
    from core import dpapi
    wrapped_file = base / "jwt-secret.dpapi"
    legacy_file = base / "jwt-secret"

    blob = dpapi.protect(secret.encode("utf-8"))
    if blob is None:
        legacy_file.write_text(secret, encoding="utf-8")
        if dpapi.available():
            print("[server_entry] DPAPI refused to wrap jwt-secret; it is on "
                  "disk in PLAINTEXT.", file=sys.stderr)
        return

    wrapped_file.write_bytes(blob)
    # Verify before destroying the only other copy.
    if _read_wrapped_secret(wrapped_file) != secret:
        print("[server_entry] jwt-secret.dpapi did not read back correctly — "
              "keeping the plaintext file.", file=sys.stderr)
        legacy_file.write_text(secret, encoding="utf-8")
        return
    if legacy_file.exists():
        legacy_file.unlink()
        print("[server_entry] jwt-secret migrated to DPAPI; the plaintext copy "
              "has been removed.", file=sys.stderr)


def _ensure_jwt_secret(data_dir: str | None) -> None:
    """
    services/auth.py hard-fails without JWT_SECRET. The packaged app ships no
    .env (secrets never go inside the exe), so resolve one at runtime:

      1. Already in the environment → use it.
      2. .env in the data dir → loaded (lets users share the cloud's secret,
         REQUIRED for hybrid sync: local-signed tokens must verify on the cloud).
      3. <data_dir>/jwt-secret.dpapi → unwrapped via Windows DPAPI.
      4. <data_dir>/jwt-secret → LEGACY plaintext. Read, re-persisted wrapped,
         and the plaintext deleted.
      5. Otherwise generate once and persist (wrapped where possible) so local
         sessions survive restarts. (Hybrid sync will 401 until the user drops
         the shared secret into .env — local & cloud-mode use is unaffected.)

    WHY WRAPPED (C-1 §7). This file used to be written in cleartext next to
    `bizassist.db`. On a hybrid install the secret it holds SIGNS TOKENS THE
    CLOUD ACCEPTS, so a copy of this one file is a copy of the shop's cloud
    identity — a worse leak than the price book the encryption work is about.
    DPAPI binds it to this Windows user on this machine, so a copied data
    directory is useless. It does NOT defend against anything running as that
    same user; see docs/DECISION_LOCAL_DB_ENCRYPTION_2026-08-03.md §1.
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

    secret = _read_wrapped_secret(base / "jwt-secret.dpapi")

    if secret is None:
        legacy_file = base / "jwt-secret"
        if legacy_file.exists():
            secret = legacy_file.read_text(encoding="utf-8").strip()
        else:
            import secrets as _secrets
            secret = _secrets.token_urlsafe(48)
        _persist_secret(base, secret)

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
