import sqlite3, sys, os, json
db = sys.argv[1] if len(sys.argv) > 1 else "bizassist.db"
c = sqlite3.connect(f"file:{os.path.abspath(db)}?mode=ro", uri=True)
c.row_factory = sqlite3.Row
print(f"{'qid':>5} {'entity':<18}{'row':>5} {'synced':<8}{'payload':>9}  uid / error")
for r in c.execute("SELECT id,entity,entity_id,synced_at,payload,error FROM sync_queue "
                   "WHERE entity IN ('register_shifts','invoices','invoice_payments') "
                   "ORDER BY id DESC LIMIT 12"):
    uid = ""
    if r["payload"]:
        try: uid = json.loads(r["payload"]).get("uid", "")
        except Exception: uid = "(unparseable)"
    print(f"{r['id']:>5} {r['entity']:<18}{r['entity_id']:>5} "
          f"{'YES' if r['synced_at'] else 'no':<8}"
          f"{(len(r['payload']) if r['payload'] else 0):>9}  "
          f"{uid or (r['error'] or '')[:40]}")
