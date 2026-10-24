"""
ops/db-backup/backup.py - nightly copy of the shared cloud database.

Billing (Hugging Face Space) and Field Team (Cloud Run) share ONE Supabase
Postgres. This dumps its `public` schema - every billing and Field Team table -
with pg_dump, checks the dump reads back and holds the core tables, and uploads
it to a private Cloud Storage bucket, which deletes copies after the retention
set by deploy_backup.ps1. Runs as a Cloud Run Job, started nightly by Cloud
Scheduler. Exits non-zero on any failure, so the job execution shows FAILED.

Environment:
  DATABASE_URL   the shared database (Secret Manager, never printed)
  BACKUP_BUCKET  bucket name, without gs://
"""
import datetime
import os
import subprocess
import sys
import tempfile
import urllib.parse

# A dump missing any of these is not a backup of BizAssist; fail loudly.
REQUIRED_TABLES = ("users", "customers", "invoices", "invoice_payments", "ft_tasks")


def log(msg: str) -> None:
    print(f"[DB-BACKUP] {msg}", flush=True)


def libpq_url(url: str) -> str:
    """The app's DATABASE_URL, as pg_dump needs it.

    * SQLAlchemy schemes (postgresql+psycopg2://, postgres://) become postgresql://.
    * Supabase's transaction pooler (port 6543) cannot run pg_dump, which needs
      a session; the same pooler serves sessions on port 5432.
    * Driver-only query options libpq rejects (pgbouncer=true) are dropped.
    """
    p = urllib.parse.urlsplit(url.strip())
    if not p.scheme.startswith("postgres"):
        raise ValueError("DATABASE_URL is not a Postgres URL")
    netloc = p.netloc
    if p.port == 6543 and (p.hostname or "").endswith("pooler.supabase.com"):
        netloc = netloc.rsplit(":", 1)[0] + ":5432"
    query = urllib.parse.urlencode(
        [(k, v) for k, v in urllib.parse.parse_qsl(p.query) if k.lower() != "pgbouncer"])
    return urllib.parse.urlunsplit(("postgresql", netloc, p.path, query, ""))


def tables_in(listing: str) -> set:
    """Table names whose DATA is in a dump, from `pg_restore --list` output.
    Lines look like: `3456; 0 16390 TABLE DATA public invoices postgres`."""
    found = set()
    for line in listing.splitlines():
        parts = line.split()
        if "TABLE" in parts and "DATA" in parts:
            i = parts.index("DATA")
            if i + 2 < len(parts):
                found.add(parts[i + 2])
    return found


def object_name(now: datetime.datetime) -> str:
    return now.strftime("%Y/%m/%d/bizassist-%Y%m%d-%H%M%SZ.dump")


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        # pg_dump's errors name the problem, never the password.
        raise RuntimeError(f"{cmd[0]} failed ({r.returncode}): {r.stderr.strip()[-800:]}")
    return r.stdout


def main() -> int:
    bucket = os.environ.get("BACKUP_BUCKET", "").strip()
    url = os.environ.get("DATABASE_URL", "")
    if not bucket or not url:
        log("BACKUP_BUCKET and DATABASE_URL are required")
        return 2
    now = datetime.datetime.now(datetime.timezone.utc)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "bizassist.dump")
        log("dumping the public schema...")
        env = dict(os.environ, PGCONNECT_TIMEOUT="30")
        env.pop("DATABASE_URL", None)
        run(["pg_dump", "--format=custom", "--no-owner", "--no-privileges", "--schema=public",
             f"--file={path}", f"--dbname={libpq_url(url)}"], env=env)
        size = os.path.getsize(path)
        tables = tables_in(run(["pg_restore", "--list", path]))
        missing = [t for t in REQUIRED_TABLES if t not in tables]
        if missing:
            raise RuntimeError(f"dump is missing {missing} - not uploading it")
        log(f"dump OK: {size:,} bytes, {len(tables)} tables")

        from google.cloud import storage   # imported late: unit tests need no GCP client
        name = object_name(now)
        blob = storage.Client().bucket(bucket).blob(name)
        blob.upload_from_filename(path, content_type="application/octet-stream", if_generation_match=0)
        log(f"uploaded gs://{bucket}/{name}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"FAILED: {e}")
        sys.exit(1)
