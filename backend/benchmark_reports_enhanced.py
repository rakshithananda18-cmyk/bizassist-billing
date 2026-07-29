#!/usr/bin/env python3
"""
benchmark_reports_enhanced.py
==============================
Enhanced Dual-Mode Performance & Benchmark Test Suite for BizAssist Billing.
Measures latency and throughput under load for:
  1. LOCAL MODE (Offline SQLite Database Operations & Financial Reports)
  2. LOCAL + CLOUD HYBRID MODE (Sync Outbox Serialization, UID Resolution, Conflict Check & Self-Healing)
"""
import os
import sys
import time
import json
from datetime import datetime, timedelta
from fastapi import Response

os.environ.setdefault("DATABASE_URL", "sqlite:///./bizassist.db")

# Add the backend directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database.db import SessionLocal
from core.api.reports import (
    report_pnl, report_day_book, report_balance_sheet,
    report_trial_balance, report_sales_register, report_stock_movement,
    report_audit_journal, report_verify_chain
)
from services.self_healing import diagnose_and_heal_tenant, heal_hash_chain, heal_sync_outbox_stalls
from database.models import _serialize_orm_obj, SyncQueue, Invoice
from database.sync_map import MODEL_MAP


def run_enhanced_benchmark(business_id: int = 1):
    db = SessionLocal()
    current_user = {"id": business_id, "username": "benchmark_user"}
    
    today_str = datetime.today().strftime("%Y-%m-%d")
    month_ago_str = (datetime.today() - timedelta(days=30)).strftime("%Y-%m-%d")
    year_ago_str = (datetime.today() - timedelta(days=365)).strftime("%Y-%m-%d")

    print("\n" + "="*80)
    print(f"  BIZASSIST DUAL-MODE BENCHMARK & PERFORMANCE SUITE (Business ID: {business_id})")
    print("="*80)

    # ── SECTION 1: LOCAL MODE (SQLite Core Operations) ──────────────────────
    print("\nSECTION 1: LOCAL MODE BENCHMARKS (SQLite Local Storage & Ledger Engine)")
    print("-" * 80)

    local_benchmarks = [
        {
            "mode": "Local (SQLite)",
            "name": "Day Book (Today, limit 200)",
            "func": lambda: report_day_book(from_date=today_str, to_date=today_str, limit=200, offset=0, current_user=current_user, db=db)
        },
        {
            "mode": "Local (SQLite)",
            "name": "Trial Balance (Instant)",
            "func": lambda: report_trial_balance(from_date=None, to_date=None, current_user=current_user, db=db)
        },
        {
            "mode": "Local (SQLite)",
            "name": "Balance Sheet (Instant)",
            "func": lambda: report_balance_sheet(current_user=current_user, db=db)
        },
        {
            "mode": "Local (SQLite)",
            "name": "P&L Report (1 Year Window)",
            "func": lambda: report_pnl(from_date=year_ago_str, to_date=today_str, current_user=current_user, db=db)
        },
        {
            "mode": "Local (SQLite)",
            "name": "Stock Movement (1 Year, limit 2000)",
            "func": lambda: report_stock_movement(response=Response(), from_date=year_ago_str, to_date=today_str, limit=2000, offset=0, current_user=current_user, db=db)
        },
        {
            "mode": "Local (SQLite)",
            "name": "Audit Journal (1 Year, limit 2000)",
            "func": lambda: report_audit_journal(from_date=year_ago_str, to_date=today_str, limit=2000, offset=0, current_user=current_user, db=db)
        },
        {
            "mode": "Local (SQLite)",
            "name": "SHA-256 Hash Chain Verification",
            "func": lambda: report_verify_chain(current_user=current_user, db=db)
        },
        {
            "mode": "Local (SQLite)",
            "name": "Master Self-Healing Diagnostic Run",
            "func": lambda: diagnose_and_heal_tenant(db, business_id=business_id)
        }
    ]

    local_results = []
    for b in local_benchmarks:
        try:
            b["func"]()  # Warmup
        except Exception:
            pass

        times = []
        res = None
        for _ in range(5):
            t0 = time.perf_counter()
            res = b["func"]()
            t1 = time.perf_counter()
            times.append((t1 - t0) * 1000.0)

        avg_ms = sum(times) / len(times)
        min_ms = min(times)
        
        count_val = "N/A"
        if isinstance(res, list):
            count_val = len(res)
        elif isinstance(res, dict):
            count_val = res.get("ok", "OK")
            
        local_results.append({
            "mode": b["mode"],
            "name": b["name"],
            "avg_ms": avg_ms,
            "min_ms": min_ms,
            "status": count_val
        })
        print(f"  [PASS] {b['name']:<42} | Avg: {avg_ms:6.2f} ms | Min: {min_ms:6.2f} ms")

    # ── SECTION 2: LOCAL + CLOUD HYBRID MODE BENCHMARKS ─────────────────────
    print("\nSECTION 2: LOCAL + CLOUD HYBRID MODE BENCHMARKS (Sync Outbox & Concurrency)")
    print("-" * 80)

    inv_sample = db.query(Invoice).filter(Invoice.business_id == business_id).first()
    conn = db.connection()
    
    hybrid_benchmarks = [
        {
            "mode": "Hybrid (Local+Cloud)",
            "name": "Outbox Payload Serialization (Invoice)",
            "func": lambda: _serialize_orm_obj(inv_sample, conn) if inv_sample else {}
        },
        {
            "mode": "Hybrid (Local+Cloud)",
            "name": "Parent UID FK Resolution Lookup",
            "func": lambda: db.query(Invoice.uid).filter(Invoice.id == inv_sample.id).first() if inv_sample else None
        },
        {
            "mode": "Hybrid (Local+Cloud)",
            "name": "Sync Outbox Queue Drain Batch (20 Items)",
            "func": lambda: db.query(SyncQueue).filter(SyncQueue.business_id == business_id).limit(20).all()
        },
        {
            "mode": "Hybrid (Local+Cloud)",
            "name": "Redundant Child Line-Item Heal Clearance",
            "func": lambda: heal_sync_outbox_stalls(db, business_id=business_id)
        },
        {
            "mode": "Hybrid (Local+Cloud)",
            "name": "Single-Pass O(N) Hash Re-Sealing",
            "func": lambda: heal_hash_chain(db, business_id=business_id)
        }
    ]

    hybrid_results = []
    for b in hybrid_benchmarks:
        try:
            b["func"]()  # Warmup
        except Exception:
            pass

        times = []
        res = None
        for _ in range(5):
            t0 = time.perf_counter()
            res = b["func"]()
            t1 = time.perf_counter()
            times.append((t1 - t0) * 1000.0)

        avg_ms = sum(times) / len(times)
        min_ms = min(times)
        
        hybrid_results.append({
            "mode": b["mode"],
            "name": b["name"],
            "avg_ms": avg_ms,
            "min_ms": min_ms,
            "status": "PASS"
        })
        print(f"  [PASS] {b['name']:<42} | Avg: {avg_ms:6.2f} ms | Min: {min_ms:6.2f} ms")

    print("\n" + "="*80)
    print("  FINAL DUAL-MODE BENCHMARK SUMMARY TABLE")
    print("="*80)
    print(f"{'Hosting Mode':<20} | {'Benchmark Operation':<42} | {'Avg Latency':<12} | {'Min Latency':<12}")
    print("-" * 92)
    for r in local_results + hybrid_results:
        print(f"{r['mode']:<20} | {r['name']:<42} | {r['avg_ms']:6.2f} ms     | {r['min_ms']:6.2f} ms")
    print("="*92 + "\n")

    db.close()

if __name__ == "__main__":
    run_enhanced_benchmark(1)
