# Multi-Tenant Isolation — How Local & Cloud Users Don't Clash

## The Three-Layer Isolation System

### Layer 1 — URL-based Platform Lock (config.js)
```
localhost     → always LOCAL backend  (only that user's SQLite)
any other URL → always CLOUD backend  (only that user's PostgreSQL rows)
```
Two different users on two different devices never share a backend. No clash possible.

### Layer 2 — business_id Scoping (every DB table)
Every data table has a `business_id` column. Every query filters by it:
```sql
SELECT * FROM invoices WHERE business_id = 7   -- cloud Rakshith
SELECT * FROM invoices WHERE business_id = 122 -- local Rakshith (separate DB)
```
Even if two users were on the same DB, their data is in separate rows.

### Layer 3 — public_id "BizID" (cross-DB passport)
```python
public_id = Column(String, unique=True)  # e.g. "BA-A1B2C3"
```
Same person → same BizID on every DB.
Different people → different BizIDs → zero overlap.

---

## The Integer ID Clash Problem (What We Fixed)

```
Local DB:  Rakshith  id=122  public_id="BA-A1B2C3"
Cloud DB:  Rakshith  id=7    public_id="BA-A1B2C3"
           Suresh    id=8    public_id="BA-X9Y8Z7"
```

**Old bug**: Sync JWT said `id=122` → cloud decoded it → looked for user 122 → 
found Suresh (if Suresh happened to have id=122 on cloud) → Suresh's data exposed 🚨

**Fix applied**: 
- `sync.py` line 170: `data["business_id"] = business_id` — cloud ALWAYS overwrites 
  the payload's business_id with the authenticated user's cloud business_id.
  Even if local sent business_id=122, cloud saves it as business_id=7. ✅
- `migrate.py`: username-based ID resolution + _remap_rows() remaps 122→7 on import. ✅

---

## Remaining Risk: JWT Identity Resolution

The sync worker creates a JWT with `"id": local_business_id (122)`.
Cloud decodes it and tries `db.query(User).filter(User.id == 122)`.

If cloud has NO user with id=122 → sync fails (401/404). No data leak, just no sync.
If cloud HAS a DIFFERENT user with id=122 → that user's session is used → DATA LEAK 🚨

### Fix Applied

Include `public_id` in the JWT and have the cloud resolve by `username`:

```python
# sync_worker.py — fixed (use username for resolution)
token = create_access_token({
    "id": business_id,           # kept for backward compat
    "public_id": user.public_id, # cross-DB passport
    "username": user.username,   # unique string, safe cross-DB key
    ...
})
```

And in `sync.py` and `auth.py`:
- `sync.py`: Resolves `business_id` using `_resolve_business_id_by_username` instead of trusting the JWT ID directly.
- `auth.py`: Resolves the user by `username` in `/settings` (GET/PUT) and `/profile` (GET/PUT) routes to prevent stale session ID clash errors during migrations and mode transitions.

---

## Registration Isolation (No Cross-Contamination)

```
New user registers on LOCAL app
  → Gets local account: id=auto, public_id=BA-XXXXX
  → All data scoped to that local id
  → Cloud knows NOTHING about this user (separate DB)

Same person registers on CLOUD via Vercel
  → Gets cloud account: id=auto (different), public_id=BA-YYYYY (different!)
  → All data scoped to that cloud id
  → These are treated as TWO SEPARATE ACCOUNTS

User runs Migration (local → cloud)
  → _upsert_users() updates cloud Rakshith's profile fields from local
  → _remap_rows() remaps all business_id 122→7
  → Now ONE unified account on cloud with all local data
  → public_id becomes the same on both (updated during migration)
```

---

## Summary: What Prevents Clashes

| Mechanism | Protects Against |
|---|---|
| URL-based platform lock | Wrong backend entirely |
| business_id column scoping | Other users' data on same DB |
| JWT authentication | Unauthenticated access |
| sync.py overwrites business_id | Wrong business_id in sync payload |
| username-based resolution (migrate.py, sync.py, auth.py) | Integer ID collisions on import and active API sessions |
| public_id (BizID) | Cross-DB identity confusion |
