#!/usr/bin/env python3
"""
benchmark_reports.py
====================
Runs benchmarks on key reporting endpoints to measure performance under load.
Calculates P&L, Day Book, Balance Sheet, Trial Balance, Sales Register, and Stock Movement.
"""
import os
import sys
import time
from datetime import datetime, timedelta
from fastapi import Response

# Add the backend directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database.db import SessionLocal
from core.api.reports import (
    report_pnl,
    report_day_book,
    report_balance_sheet,
    report_trial_balance,
    report_sales_register,
    report_stock_movement,
    report_audit_journal,
    report_verify_chain
)

def run_benchmark(business_id: int):
    db = SessionLocal()
    current_user = {"id": business_id, "username": "benchmark_user"}
    
    # Calculate dates
    today_str = datetime.today().strftime("%Y-%m-%d")
    month_ago_str = (datetime.today() - timedelta(days=30)).strftime("%Y-%m-%d")
    year_ago_str = (datetime.today() - timedelta(days=365)).strftime("%Y-%m-%d")

    print(f"===========================================================")
    print(f" RUNNING REPORT BENCHMARKS FOR BUSINESS {business_id}")
    print(f"===========================================================")
    
    benchmarks = [
        {
            "name": "P&L (1 Day)",
            "func": lambda: report_pnl(from_date=today_str, to_date=today_str, current_user=current_user, db=db)
        },
        {
            "name": "P&L (1 Month)",
            "func": lambda: report_pnl(from_date=month_ago_str, to_date=today_str, current_user=current_user, db=db)
        },
        {
            "name": "P&L (1 Year)",
            "func": lambda: report_pnl(from_date=year_ago_str, to_date=today_str, current_user=current_user, db=db)
        },
        {
            "name": "Day Book (Today, paginated 200)",
            "func": lambda: report_day_book(from_date=today_str, to_date=today_str, limit=200, offset=0, current_user=current_user, db=db)
        },
        {
            "name": "Day Book (1 Month, paginated 200)",
            "func": lambda: report_day_book(from_date=month_ago_str, to_date=today_str, limit=200, offset=0, current_user=current_user, db=db)
        },
        {
            "name": "Day Book (1 Year, paginated 200)",
            "func": lambda: report_day_book(from_date=year_ago_str, to_date=today_str, limit=200, offset=0, current_user=current_user, db=db)
        },
        {
            "name": "Balance Sheet",
            "func": lambda: report_balance_sheet(current_user=current_user, db=db)
        },
        {
            "name": "Trial Balance",
            "func": lambda: report_trial_balance(from_date=None, to_date=None, current_user=current_user, db=db)
        },
        {
            "name": "Sales Register (1 Month, limit=2000)",
            "func": lambda: report_sales_register(response=Response(), from_date=month_ago_str, to_date=today_str, limit=2000, offset=0, current_user=current_user, db=db)
        },
        {
            "name": "Sales Register (1 Year, limit=2000)",
            "func": lambda: report_sales_register(response=Response(), from_date=year_ago_str, to_date=today_str, limit=2000, offset=0, current_user=current_user, db=db)
        },
        {
            "name": "Stock Movement (1 Year, limit=2000)",
            "func": lambda: report_stock_movement(response=Response(), from_date=year_ago_str, to_date=today_str, limit=2000, offset=0, current_user=current_user, db=db)
        },
        {
            "name": "Audit Journal (1 Year, limit=2000)",
            "func": lambda: report_audit_journal(from_date=year_ago_str, to_date=today_str, limit=2000, offset=0, current_user=current_user, db=db)
        },
        {
            "name": "Verify Hash Chain",
            "func": lambda: report_verify_chain(current_user=current_user, db=db)
        }
    ]
    
    results = []
    for b in benchmarks:
        print(f"Benchmarking {b['name']}...", end="", flush=True)
        # Warmup
        try:
            b["func"]()
        except Exception as e:
            print(f" ERROR: {e}")
            continue
            
        times = []
        for _ in range(3):
            t0 = time.perf_counter()
            res = b["func"]()
            t1 = time.perf_counter()
            times.append((t1 - t0) * 1000.0) # in ms
            
        avg_time = sum(times) / len(times)
        min_time = min(times)
        
        # Get count of items returned
        count_val = "N/A"
        if isinstance(res, list):
            count_val = len(res)
        elif isinstance(res, dict):
            if "transactions" in res:
                count_val = len(res["transactions"])
            elif "entries" in res:
                count_val = len(res["entries"])
            elif "ledgers" in res:
                count_val = len(res["ledgers"])
                
        print(f" Done. Avg: {avg_time:.2f}ms, Min: {min_time:.2f}ms (Items: {count_val})")
        results.append({
            "name": b["name"],
            "avg_ms": avg_time,
            "min_ms": min_time,
            "count": count_val
        })
        
    print(f"\n===========================================================")
    print(f" BENCHMARK RESULTS SUMMARY (Business {business_id})")
    print(f"===========================================================")
    print(f"{'Report Name':<38} | {'Avg Latency':<12} | {'Min Latency':<12} | {'Records':<8}")
    print(f"-" * 78)
    for r in results:
        avg_str = f"{r['avg_ms']:.2f} ms"
        min_str = f"{r['min_ms']:.2f} ms"
        print(f"{r['name']:<38} | {avg_str:<12} | {min_str:<12} | {r['count']:<8}")
    print(f"===========================================================")
    
    db.close()

if __name__ == "__main__":
    business_id = 2
    if len(sys.argv) > 1:
        try:
            business_id = int(sys.argv[1])
        except ValueError:
            pass
            
    run_benchmark(business_id)
