"""Bounded, cached platform diagnostics. Counts are catalog estimates only."""
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import text
from services.dates import utc_now
import httpx
try:
    import psutil
    _PROCESS = psutil.Process()
    _PROCESS.cpu_percent(None)
except Exception:
    psutil = _PROCESS = None

_cache = None
_cached_at = 0.0
_refresh_at = 0.0
_lock = threading.Lock()


def _probe(url):
    start = time.monotonic()
    try:
        with httpx.Client(timeout=2.0, follow_redirects=True) as client:
            response = client.get(url)
        protected = response.status_code in (401, 403) or any(path in str(response.url) for path in ("vercel.com/login", "vercel.com/sso-api"))
        return {"url": url, "status": "ONLINE" if response.status_code < 400 and not protected else "ERROR", "code": response.status_code, "latency_ms": round((time.monotonic()-start)*1000), "edge_pop": response.headers.get("x-vercel-id", "").split("::")[0] or None, "error": "Deployment is protected" if protected else (None if response.status_code < 400 else f"HTTP {response.status_code}")}
    except Exception as exc:
        return {"url": url, "status": "UNREACHABLE", "code": None, "latency_ms": round((time.monotonic()-start)*1000), "edge_pop": None, "error": str(exc)}


def metrics(db, *, refresh=False):
    global _cache, _cached_at, _refresh_at
    with _lock:
        now = time.monotonic()
        bypass = refresh and now - _refresh_at >= 10
        if _cache is not None and now - _cached_at < 45 and not bypass:
            return _cache
        if bypass:
            _refresh_at = now
        unavailable = []
        process = {"memory": {"rss_mb": None, "vms_mb": None, "percent": None}, "cpu_percent": None, "thread_count": None, "uptime_seconds": None}
        try:
            if _PROCESS is None or psutil is None:
                raise RuntimeError("psutil unavailable")
            memory = _PROCESS.memory_info()
            process.update(memory={"rss_mb": round(memory.rss/1048576, 2), "vms_mb": round(memory.vms/1048576, 2), "percent": round(_PROCESS.memory_percent(), 2)}, cpu_percent=_PROCESS.cpu_percent(None), thread_count=_PROCESS.num_threads(), uptime_seconds=int(time.time()-_PROCESS.create_time()))
        except Exception:
            unavailable.extend(["cloud_run.memory", "cloud_run.cpu_percent", "cloud_run.thread_count", "cloud_run.uptime_seconds"])
        region = os.getenv("CLOUD_RUN_REGION")
        if not region:
            unavailable.append("cloud_run.region")
        cloud = dict(process, provider="Google Cloud Run" if os.getenv("K_SERVICE") else "Local runtime", service_name=os.getenv("K_SERVICE"), revision=os.getenv("K_REVISION"), region=region, status="ACTIVE", role="Primary Production Backend", python_version=sys.version.split()[0], platform=sys.platform)
        dialect = db.bind.dialect.name
        counts = dict.fromkeys(("users", "invoices", "products", "payments", "audit_logs"))
        size_bytes = size_str = active = idle = total = maximum = hit = None
        if dialect == "postgresql":
            queries = {
                "size": "SELECT pg_size_pretty(pg_database_size(current_database())), pg_database_size(current_database())",
                "connections": "SELECT count(*) FILTER (WHERE state='active'), count(*) FILTER (WHERE state='idle'), count(*) FROM pg_stat_activity WHERE datname=current_database()",
                "maximum": "SHOW max_connections",
                "hit": "SELECT round(100.0*sum(heap_blks_hit)/nullif(sum(heap_blks_hit)+sum(heap_blks_read),0),2) FROM pg_statio_user_tables",
                "counts": "SELECT relname, reltuples::bigint FROM pg_class WHERE relnamespace='public'::regnamespace AND relname IN ('users','invoices','products','payments','action_logs')",
            }
            values = {}
            for key, query in queries.items():
                try:
                    with db.begin_nested():
                        values[key] = db.execute(text(query)).all()
                except Exception:
                    unavailable.append("supabase."+key)
            if values.get("size"):
                size_str, size_bytes = values["size"][0]
            if values.get("connections"):
                active, idle, total = values["connections"][0]
            if values.get("maximum"):
                maximum = int(values["maximum"][0][0])
            if values.get("hit") and values["hit"][0][0] is not None:
                hit = float(values["hit"][0][0])
            aliases = {"action_logs": "audit_logs"}
            for name, count in values.get("counts", []):
                counts[aliases.get(name, name)] = int(count) if count >= 0 else None
        else:
            try:
                size_bytes = db.execute(text("PRAGMA page_count")).scalar() * db.execute(text("PRAGMA page_size")).scalar()
                size_str = f"{size_bytes/1048576:.2f} MB"
            except Exception:
                unavailable.append("supabase.size")
            unavailable.extend(["supabase.connection_pool", "supabase.cache_hit_ratio_pct", "supabase.table_counts"])
        urls = {"billing": "https://staterbill.com", "field_team": os.getenv("FIELD_TEAM_API_URL", "https://staterbill-task-ftkym77vzq-el.a.run.app").rstrip("/")+"/api/health"}
        hf = os.getenv("HF_STANDBY_URL", "").rstrip("/")
        if hf:
            urls["huggingface"] = hf+"/health"
        with ThreadPoolExecutor(max_workers=len(urls)) as pool:
            futures = {key: pool.submit(_probe, url) for key, url in urls.items()}
            probes = {key: future.result() for key, future in futures.items()}
        hf_metrics = dict(probes.get("huggingface", {"status": "UNAVAILABLE", "code": None, "latency_ms": None, "error": "Forwarder probe is not configured"}), provider="Hugging Face Spaces", role="Legacy compatibility forwarder", url=hf or None, failover_ready=False)
        if not hf:
            unavailable.append("huggingface")
        database = {"provider": "Supabase PostgreSQL" if dialect=="postgresql" else "SQLite Local Mirror", "dialect": dialect, "status": "CONNECTED", "size_str": size_str, "size_bytes": size_bytes, "connection_pool": {"active": active,"idle": idle,"total": total,"max": maximum,"utilization_pct": round(total/maximum*100,1) if maximum and total is not None else None}, "cache_hit_ratio_pct":hit,"table_counts":counts, "counts_are_estimates":True}
        endpoint = dict(probes["billing"], name="StaterBill Web Application", domain="staterbill.com")
        _cache = {"status":"ok","timestamp":utc_now().isoformat(),"cloud_run":cloud,"huggingface":hf_metrics,"supabase":database,"vercel":{"provider":"Vercel Edge Global Network","status":endpoint["status"],"endpoints":[endpoint]},"field_team":probes["field_team"],"unavailable":unavailable}
        _cached_at = time.monotonic()
        return _cache
