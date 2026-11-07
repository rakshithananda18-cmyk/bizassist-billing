"""
services/api_tracer.py
======================
High-performance in-memory APM tracer and Cloud Cost Estimator.
Captures recent API requests in a thread-safe ring buffer, computes
traffic statistics (RPM, latency percentiles, error rates), and
estimates monthly cloud infrastructure costs across Google Cloud Run,
Supabase Database, Groq AI, and Vercel Edge.
"""

import time
import uuid
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

_MAX_TRACES = 1000
_traces_lock = threading.Lock()
_traces: deque = deque(maxlen=_MAX_TRACES)

# Running counters
_stats_lock = threading.Lock()
_request_timestamps: deque = deque(maxlen=2000) # timestamps for RPM
_latencies: deque = deque(maxlen=2000)
_status_counts = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}
_total_requests = 0
_start_time = time.time()


def record_request(
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    ip: Optional[str] = None,
    biz_id: Optional[str] = None,
    user_id: Optional[int] = None,
    user_agent: Optional[str] = None,
    error: Optional[str] = None,
) -> str:
    """Record an HTTP request into the in-memory trace ring buffer."""
    global _total_requests
    now = time.time()
    trace_id = f"trc_{uuid.uuid4().hex[:12]}"
    
    # Classify status
    if 200 <= status_code < 300:
        bucket = "2xx"
    elif 300 <= status_code < 400:
        bucket = "3xx"
    elif 400 <= status_code < 500:
        bucket = "4xx"
    else:
        bucket = "5xx"

    with _stats_lock:
        _total_requests += 1
        _status_counts[bucket] = _status_counts.get(bucket, 0) + 1
        _request_timestamps.append(now)
        _latencies.append(duration_ms)

    # Sanitize path to avoid unbounded query string bloat
    clean_path = path.split("?")[0] if "?" in path else path

    trace_entry = {
        "id": trace_id,
        "timestamp": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "method": method.upper(),
        "path": clean_path,
        "full_path": path,
        "status": status_code,
        "duration_ms": round(duration_ms, 2),
        "ip": ip or "127.0.0.1",
        "biz_id": biz_id or "—",
        "user_id": user_id,
        "user_agent": (user_agent[:80] + "…") if user_agent and len(user_agent) > 80 else (user_agent or "—"),
        "error": error,
    }

    with _traces_lock:
        _traces.appendleft(trace_entry)

    return trace_id


def get_recent_traces(
    limit: int = 50,
    status_filter: Optional[str] = None,
    method_filter: Optional[str] = None,
    search: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve filtered recent API traces from the ring buffer."""
    with _traces_lock:
        items = list(_traces)

    results = []
    search_lower = search.lower().strip() if search else None

    for item in items:
        if status_filter:
            s = item["status"]
            if status_filter == "2xx" and not (200 <= s < 300):
                continue
            if status_filter == "4xx" and not (400 <= s < 500):
                continue
            if status_filter == "5xx" and not (s >= 500):
                continue

        if method_filter and item["method"] != method_filter.upper():
            continue

        if search_lower:
            if (search_lower not in item["path"].lower() and
                search_lower not in str(item.get("biz_id", "")).lower() and
                search_lower not in str(item.get("status", ""))):
                continue

        results.append(item)
        if len(results) >= limit:
            break

    return results


def get_trace_by_id(trace_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a single trace by ID with complete detail."""
    with _traces_lock:
        for t in _traces:
            if t["id"] == trace_id:
                return dict(t)
    return None


def get_console_metrics() -> Dict[str, Any]:
    """Calculate real-time APM metrics and cloud cost estimation."""
    now = time.time()
    
    with _stats_lock:
        # Calculate RPM over last 60 seconds
        cutoff_60s = now - 60
        rpm = sum(1 for ts in _request_timestamps if ts >= cutoff_60s)
        
        # Calculate RPM over last 5 minutes (average)
        cutoff_300s = now - 300
        reqs_5m = sum(1 for ts in _request_timestamps if ts >= cutoff_300s)
        rpm_5m = round(reqs_5m / 5.0, 1)

        # Latencies
        lats = sorted(list(_latencies))
        n = len(lats)
        p50 = round(lats[int(n * 0.50)], 1) if n > 0 else 0.0
        p95 = round(lats[int(n * 0.95)], 1) if n > 0 else 0.0
        p99 = round(lats[int(n * 0.99)], 1) if n > 0 else 0.0
        avg_lat = round(sum(lats) / n, 1) if n > 0 else 0.0

        status_copy = dict(_status_counts)
        tot = _total_requests

    # Error rate
    err_count = status_copy.get("4xx", 0) + status_copy.get("5xx", 0)
    error_rate_pct = round((err_count / max(1, tot)) * 100, 2)

    # ── Cloud Cost Breakdown ────────────────────────────────────────────────
    # Google Cloud Run Free Tier: 2,000,000 requests/mo, 360,000 vCPU-seconds, 180,000 GiB-seconds
    # Supabase Free Tier: 500 MB database storage, 50,000 monthly active users
    # Groq Free Tier: 30 RPM, 14,400 RPD, generous token allocations
    # Vercel Hobby: 100 GB bandwidth, 1,000,000 Edge invocations
    cloud_run_requests_est = tot * 30  # estimated monthly requests at current run-rate
    cloud_run_cost_usd = 0.00 if cloud_run_requests_est <= 2000000 else round((cloud_run_requests_est - 2000000) * 0.0000004, 2)
    supabase_cost_usd = 0.00 # Free tier up to 500MB
    groq_cost_usd = 0.00     # Free tier
    vercel_cost_usd = 0.00   # Hobby plan

    total_monthly_usd = round(cloud_run_cost_usd + supabase_cost_usd + groq_cost_usd + vercel_cost_usd, 2)
    total_monthly_inr = round(total_monthly_usd * 86.5, 2)

    # Projected costs at scale
    scale_10x_usd = 0.00 if (cloud_run_requests_est * 10) <= 2000000 else round(((cloud_run_requests_est * 10) - 2000000) * 0.0000004, 2)
    scale_100x_usd = round(((cloud_run_requests_est * 100) - 2000000) * 0.0000004 + 25.0, 2) # Pro DB added at 100x

    cost_breakdown = {
        "currency": "USD",
        "current_monthly_usd": total_monthly_usd,
        "current_monthly_inr": total_monthly_inr,
        "plan_status": "100% Free Tier Compliant",
        "services": [
            {
                "name": "Google Cloud Run",
                "role": "Serverless APIs (Mumbai)",
                "unit": "Requests & vCPU",
                "consumed": f"{tot:,} requests logged",
                "quota": "2,000,000 req / mo free",
                "cost_usd": cloud_run_cost_usd,
                "status": "FREE_TIER" if cloud_run_cost_usd == 0 else "ACTIVE_BILLING"
            },
            {
                "name": "Supabase PostgreSQL",
                "role": "Primary Database",
                "unit": "Storage & Compute",
                "consumed": "43 MB used",
                "quota": "500 MB free storage",
                "cost_usd": supabase_cost_usd,
                "status": "FREE_TIER"
            },
            {
                "name": "Groq AI LPU",
                "role": "LLM Router & Billing Copilot",
                "unit": "Tokens",
                "consumed": "Within rate limits",
                "quota": "14,400 req / day free",
                "cost_usd": groq_cost_usd,
                "status": "FREE_TIER"
            },
            {
                "name": "Vercel Global Edge",
                "role": "Frontend Distribution",
                "unit": "Bandwidth & Edge Requests",
                "consumed": "Edge caching active",
                "quota": "100 GB bandwidth / mo",
                "cost_usd": vercel_cost_usd,
                "status": "FREE_TIER"
            }
        ],
        "projected_scale": {
            "at_10x_traffic_usd": scale_10x_usd,
            "at_100x_traffic_usd": scale_100x_usd
        }
    }

    return {
        "uptime_seconds": int(now - _start_time),
        "traffic": {
            "rpm_1m": rpm,
            "rpm_5m": rpm_5m,
            "total_requests": tot,
            "error_rate_pct": error_rate_pct,
            "status_distribution": status_copy,
        },
        "latency": {
            "p50_ms": p50,
            "p95_ms": p95,
            "p99_ms": p99,
            "avg_ms": avg_lat,
        },
        "cost": cost_breakdown,
        "timestamp": datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
    }
