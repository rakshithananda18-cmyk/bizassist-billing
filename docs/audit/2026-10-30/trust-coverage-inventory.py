"""Transparent file-level coverage inventory for the trust/sync audit."""
import ast
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[3]
files = subprocess.check_output(["git", "-c", "core.fsmonitor=false", "ls-files"], cwd=ROOT, text=True).splitlines()
service = {"auth", "rate_limiter", "registration_policy", "totp", "cloud_listener", "sync_worker", "immediate_sync", "realtime", "scheduler", "ops_health", "self_healing", "admin_service", "telemetry_relay", "telemetry_maintenance", "log_uploader"}
routes = {"auth", "sync", "sync_staff", "sync_profile", "data_transfer", "discovery", "realtime_relay", "b2b_proxy", "public", "telemetry", "admin"}
root_backend = {"main_groq.py", "server_entry.py", "app.py", "logging_config.py", "Dockerfile", "bizassist-backend.spec", "requirements_hf.txt", "Pipfile", "Pipfile.lock", "alembic.ini", ".dockerignore", ".gitignore"}
deep = {
    "backend/database/db.py", "backend/database/models.py", "backend/database/sync_map.py", "backend/database/migration.py",
    "backend/services/auth.py", "backend/services/sync_worker.py", "backend/services/immediate_sync.py", "backend/services/cloud_listener.py",
    "backend/services/rate_limiter.py", "backend/services/self_healing.py", "backend/routes/auth.py", "backend/routes/sync.py",
    "backend/routes/sync_staff.py", "backend/routes/sync_profile.py", "backend/routes/public.py", "backend/routes/data_transfer.py",
    "backend/core/api/staff.py", "backend/core/api/sync.py", "backend/core/api/realtime.py", "backend/core/sync/inbox.py",
    "backend/core/sync/tenant_scope.py", "backend/core/sync/apply_hooks.py", "backend/main_groq.py", "backend/server_entry.py",
    "backend/alembic/env.py", "backend/alembic/versions/9c2f4b8a1d3e_fail_closed_rls_policies.py",
    "backend/alembic/versions/2a6f1c9b4d8e_harden_b2b_rls_policies.py", "backend/alembic/versions/d7e3a9c6f8b1_create_rls_policies.py",
    "backend/alembic/versions/aea3a6d76429_enable_rls_and_restrict_api.py",
    "backend/alembic/versions/d9f1a2b3c4d5_harden_document_sequences_and_accounting.py",
    "backend/alembic/versions/f78e8836b7b1_add_phase_3_and_phase_4_schema_updates.py",
    "backend/alembic/versions/c0017902b685_baseline_schema.py", "backend/bizassist-backend.spec", "backend/Dockerfile",
    "desktop/src/main.js", "desktop/src/backend.js", "desktop/src/static-server.js", "desktop/src/telemetry.js",
    "desktop/src/preload.js", "desktop/src/updater.js", "desktop/package.json", "ops/db-backup/backup.py",
    "ops/db-backup/README.md", "ops/db-backup/deploy_backup.ps1", "backend/tests/test_pull_partial.py",
    "backend/tests/test_rls_policies.py", "backend/tests/test_rls_postgres.py", "backend/tests/test_session_invalidation.py",
    "backend/tests/test_sync_pull_failure_visibility.py", "backend/tests/test_sync_profile.py",
}
test_pattern = re.compile(r"(sync|auth|rls|tenant|cloud|local|hosting|migration|migrate|uid|staff|token|session_invalidation|rate_limiter|sse|db_guard|dbcompat|db_invariants|user_policy|seed_users|seed_scripts|p0_isolation|discovery|realtime|logging_config)")
script_pattern = re.compile(r"(sync|outbox|cursor|fk_|orphans|staff|cloud|reconcile_local|clean_ids)")
def owned(path):
    p = Path(path)
    return (path.startswith(("desktop/", "ops/", "backend/database/", "backend/alembic/", "backend/core/sync/"))
            or path == "Dockerfile" or path in {"backend/core/api/sync.py", "backend/core/api/realtime.py", "backend/core/api/staff.py", "backend/core/dpapi.py", "backend/core/identity.py"}
            or (p.parent.as_posix() == "backend/services" and p.stem in service)
            or (p.parent.as_posix() == "backend/routes" and p.stem in routes)
            or (p.parent.as_posix() == "backend" and p.name in root_backend)
            or (path.startswith("backend/tests/") and test_pattern.search(p.stem))
            or (path.startswith("backend/scripts/") and script_pattern.search(p.stem)))

rows=[]
errors=[]
for path in files:
    if not owned(path):
        continue
    p=ROOT/path
    if not p.exists():
        rows.append((path,"excluded","Tracked path absent from working tree")); continue
    if p.suffix.lower() in {".png",".ico",".icns",".jpg",".db",".exe",".dll",".pdf",".zip",".woff",".woff2"}:
        rows.append((path,"excluded","Binary asset inventoried; no runtime semantics claim")); continue
    if "lock" in p.name.lower():
        rows.append((path,"screened","Dependency lock metadata inventoried; vulnerability database not queried")); continue
    raw=p.read_bytes()
    try:
        source=raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        rows.append((path,"excluded","Non-UTF8 or binary asset inventoried")); continue
    lines=len(source.splitlines())
    note=f"Automated complete-file read/risk screening; {lines} lines; sha256={hashlib.sha256(raw).hexdigest()[:12]}"
    if p.suffix==".py":
        try:
            tree=ast.parse(source)
            funcs=sum(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) for n in ast.walk(tree))
            note+=f"; AST parsed, {funcs} functions"
        except SyntaxError as e:
            errors.append(f"{path}:{e.lineno}: {e.msg}")
            note+=f"; AST parse error line {e.lineno}"
    elif p.suffix==".json":
        try: json.loads(source); note+="; JSON parsed"
        except json.JSONDecodeError: note+="; JSON parse failed"
    risk=len(re.findall(r"except|SessionLocal|business_id|set_config|shell|exec|spawn|fetch|password|token|cursor|commit|rollback|DROP|DELETE",source,re.I))
    note+=f"; {risk} risk-marker matches"
    depth="deep" if path in deep else "screened"
    if depth=="deep": note+="; manual trace of selected critical flows and linked callers (not every line proven)"
    rows.append((path,depth,note))
out=ROOT/"docs/audit/2026-10-30"
out.mkdir(parents=True,exist_ok=True)
with (out/"trust-sync-ops-coverage.csv").open("w",newline="",encoding="utf-8") as f:
    w=csv.writer(f);w.writerow(["path","review_depth","notes"]);w.writerows(rows)
print(json.dumps({"assigned_tracked_files":len(rows),"depth_counts":{d:sum(r[1]==d for r in rows) for d in ("deep","screened","excluded")},"parse_errors":errors},indent=2))
