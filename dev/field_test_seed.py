"""
dev/field_test_seed.py — sample data for `start_dev.bat fieldtest`.

Runs in the "Field Test Setup" window that start_dev opens in field test mode,
once the billing backend (:8001) and the Field Team API (:8002) are up on the
throwaway database local_field_test.db. Everything goes through the two apps'
own APIs, as a person would do it, except one line: the test owner is put on
BizAssist Pro directly in that database (billing's admin console is not part of
local dev), so billing's Field Team link opens.

Creates, once (re-running only prints the summary):
  * billing owner `fieldtest_owner` on Pro, two customers, a box-packed product
    and three unpaid bills;
  * in Field Team: both customers imported as shops, agent `kiran`, and GPS
    limits loosened for a laptop (2 km accuracy, geofence not enforced).

Throwaway local test accounts — the same password for both, below.
"""
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import httpx

# start_dev's ports; the overrides exist only to try this beside a running dev setup.
BILLING = os.environ.get("FIELD_TEST_BILLING_URL", "http://127.0.0.1:8001")
TASK = os.environ.get("FIELD_TEST_TASK_URL", "http://127.0.0.1:8002")
DB = Path(__file__).resolve().parent.parent / "local_field_test.db"
OWNER = "fieldtest_owner"
STAFF_LOGIN = "kiran"
PASSWORD = "FieldTest#2026"  # local throwaway database only

c = httpx.Client(timeout=30)


def ok(r):
    if r.status_code >= 400:
        sys.exit(f"{r.request.method} {r.request.url} failed: {r.status_code} {r.text[:300]}")
    return r.json()


def wait(url):
    for _ in range(120):
        try:
            if c.get(url).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    sys.exit(f"{url} did not come up - check its window.")


def grant_pro(username):
    con = sqlite3.connect(DB)
    try:
        (raw,) = con.execute("SELECT settings FROM users WHERE username = ?", (username,)).fetchone()
        s = json.loads(raw or "{}")
        s["subscription"] = {"plan": "pro", "status": "active", "expires_at": None,
                             "granted_by": "field test seed", "note": "local throwaway database"}
        con.execute("UPDATE users SET settings = ? WHERE username = ?", (json.dumps(s), username))
        con.commit()
    finally:
        con.close()


def main():
    if os.environ.get("BIZASSIST_FIELD_TEST") != "1":
        sys.exit("Run through `start_dev.bat fieldtest` - this writes sample data and must only see the throwaway database.")
    wait(f"{BILLING}/health")
    wait(f"{TASK}/api/health")
    if not DB.exists():
        sys.exit(f"{DB.name} not found - is the billing backend running in field test mode?")

    login = c.post(f"{BILLING}/login", json={"username": OWNER, "password": PASSWORD})
    fresh = login.status_code != 200
    if fresh:
        owner = ok(c.post(f"{BILLING}/signup", json={"username": OWNER, "password": PASSWORD,
                                                       "business_name": "Field Test Distributors"}))
    else:
        owner = login.json()
    grant_pro(OWNER)
    bh = {"Authorization": f"Bearer {owner['token']}"}

    if fresh:
        balaji = ok(c.post(f"{BILLING}/customers", headers=bh, json={"name": "Sri Balaji Medicals", "phone": "9811111111", "address": "4th Block, Jayanagar"}))["id"]
        apollo = ok(c.post(f"{BILLING}/customers", headers=bh, json={"name": "Apollo Pharmacy", "phone": "9822222222", "address": "BTM Layout"}))["id"]
        boxed = ok(c.post(f"{BILLING}/products", headers=bh, json={"name": "Paracetamol 500 (box of 10 strips)", "unit": "Box",
                                                                   "selling_price": 100, "cgst_rate": 6, "sgst_rate": 6, "track_inventory": False}))["id"]
        for customer, qty in ((balaji, 10), (balaji, 2), (apollo, 5)):
            ok(c.post(f"{BILLING}/sales", headers=bh, json={"place_of_supply": "29", "customer_id": customer, "paid_amount": 0,
                                                             "lines": [{"product_id": boxed, "quantity": qty, "unit_price": 100}]}))

    ft = ok(c.post(f"{TASK}/api/auth/exchange", json={"billing_token": owner["token"]}))
    th = {"Authorization": f"Bearer {ft['token']}"}
    if fresh:
        ok(c.patch(f"{TASK}/api/settings", headers=th, json={"max_accuracy_m": 2000, "geofence_radius_m": 5000, "geofence_enforced": False}))
        customers = [x["id"] for x in ok(c.get(f"{TASK}/api/billing/customers", headers=th)) if not x["linked"]]
        ok(c.post(f"{TASK}/api/shops/import-billing", headers=th, json={"customer_ids": customers}))
        ok(c.post(f"{TASK}/api/staff", headers=th, json={"name": "Kiran", "login_name": STAFF_LOGIN, "password": PASSWORD, "role": "delivery"}))

    print(f"""
  Field test data is ready ({'created' if fresh else 'already there'}).

  Billing (owner)      http://localhost:5174   user {OWNER}   password {PASSWORD}
  Field Team (owner)   sidebar link in billing, or http://localhost:5176 -> Owner, same user/password
  Field Team (agent)   http://localhost:5176 -> Staff   BizID {ft['public_id']}   login {STAFF_LOGIN}   password {PASSWORD}

  Try it:
   1. Field Team owner: Tasks -> Assign task -> Payment collection, shop Sri Balaji Medicals,
      "Pick billing invoices" (or Day plan -> pick bills -> "Also collect ... due").
   2. Agent (another browser or a private window): check in, open the task, enter the amount,
      choose UPI / Cheque / Cash, Mark done. Allow location when the browser asks.
   3. Billing: Contacts & Payments -> Field collections -> Confirm.
   4. Field Team owner: Tasks -> done shows "Recorded in billing".
""")


if __name__ == "__main__":
    main()
