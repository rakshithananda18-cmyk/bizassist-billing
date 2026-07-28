"""
Query cloud data for LCL-OW-0021 via the HF Space API (pull endpoint).
This is the canonical way to read cloud state without a direct DB connection.
"""
import sys, json, os
sys.path.insert(0, ".")

import httpx

CLOUD_URL = "https://rakshit-dev-bizassist.hf.space"
# Use sync token from local DB (the token the sync worker uses)
from database.db import SessionLocal
from sqlalchemy import text

db = SessionLocal()
# Get the sync token for business 7
token_row = db.execute(text(
    "SELECT cloud_token FROM users WHERE id = 7"
)).fetchone()

if not token_row or not token_row[0]:
    # Try sync_tokens table if it exists
    try:
        token_row = db.execute(text(
            "SELECT value FROM sync_tokens WHERE business_id = 7 LIMIT 1"
        )).fetchone()
    except Exception:
        pass

if not token_row:
    # Fall back: try to find token from settings
    try:
        token_row = db.execute(text(
            "SELECT cloud_token FROM business_settings WHERE business_id = 7"
        )).fetchone()
    except Exception:
        pass

db.close()

if not token_row or not token_row[0]:
    print("No cloud token found in local DB — checking users table structure")
    db2 = SessionLocal()
    cols = [r[1] for r in db2.execute(text("PRAGMA table_info(users)")).fetchall()]
    print("users cols:", cols)
    db2.close()
    sys.exit(1)

TOKEN = token_row[0]
print(f"Token found: {TOKEN[:20]}...")

# Pull recent invoice data for business 7 from cloud
# Use the admin/debug endpoint if available, otherwise use pull
headers = {"Authorization": f"Bearer {TOKEN}"}

# Try hitting a cloud debug endpoint
resp = httpx.get(f"{CLOUD_URL}/health", timeout=10)
print(f"Cloud health: {resp.status_code}")

# Use the pull API to get invoice data  
resp2 = httpx.get(
    f"{CLOUD_URL}/api/sync/pull",
    params={"business_id": 7, "entity": "invoice_line_items", "limit": 200},
    headers=headers,
    timeout=30
)
print(f"Pull status: {resp2.status_code}")
if resp2.status_code == 200:
    data = resp2.json()
    # Look for LCL-OW-0021 line items
    TARGET_INV_UID = "63a9cb21-e5e5-4575-b7e6-aae318e0ab53"
    items = data.get("invoice_line_items", [])
    print(f"Total invoice_line_items in pull: {len(items)}")
    for item in items:
        if item.get("invoice_id_uid") == TARGET_INV_UID or item.get("invoice_uid") == TARGET_INV_UID:
            print(f"  MATCH: li uid={item.get('uid')} product={item.get('product_name')} total={item.get('line_total')}")
else:
    print(f"Pull response: {resp2.text[:500]}")
