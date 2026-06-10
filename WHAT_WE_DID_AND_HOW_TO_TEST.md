# BizAssist — What we changed & how to test it

Plain-language summary of this session's work, and how to check each thing
yourself. All 138 automated tests pass.

---

## The fastest check (covers everything)

```powershell
cd "D:\Dev Workspace\ai_agent_lab_google(1)\bizassist\backend"
..\venv\Scripts\activate
pytest tests/ -q
```

Expected: **144 passed**. That one command verifies every change below.

To run the actual server and click around:

```powershell
uvicorn main_groq:app --reload
```

Then open the API at http://127.0.0.1:8000 (or use your React frontend).

---

## What we did (in plain words)

### 1. Cleaned up the messy "answer engine" (ai_router)
The code that answers a user's question existed **twice** — once for normal
replies, once for streaming. They had drifted apart and one of them was lying
about token counts. We merged them into **one** path, so there's no more
"fix it in two places."

**How to test:** ask the same question normally and in streaming mode — you get
the same answer and the same source label. (Automated: `test_token_accounting.py`.)

### 2. Fixed token counting (so usage/billing is honest)
Before, several AI calls weren't being counted, and normal replies reported
"0 tokens" even when they used some. Now **every** AI call is counted and the
real number is reported.

**How to test:** ask a question, then look at the admin usage page (or the
`token_usage` table). The numbers are now non-zero and real.

### 3. Made errors behave correctly
Before, when you hit a rate limit, the server said "200 OK" but put an error
inside — so the app couldn't tell success from failure. Now it returns a proper
**429** (or 500) with a clean error body.
> ⚠️ Note: your **frontend** must now check the HTTP status / `error` field.
> If it only reads a 200 body, errors will look like "no response."

**How to test:** spam the `/ask` endpoint past the per-minute limit — you'll get
a real `429` response. (Automated: `test_error_contract.py`.)

### 4. One tenant's upload no longer wipes everyone's cache
Before, any file upload cleared the cached answers for **all** users. Now it only
clears **that** user's cache.

**How to test:** as User A, ask something (gets cached). As User B, upload a file.
User A's cached answer still works. (Automated: `test_cache_scoping.py`.)

### 5. Caches can't grow forever
Added size limits (LRU) so memory stays bounded under heavy use.

**How to test:** automated only — `test_cache_scoping.py` proves old entries get
evicted when the limit is hit.

### 6. Fixed a concurrency bug in the multi-agent path
The "complex analysis" path used one shared counter for tokens. Two requests at
once could corrupt each other's numbers. Now each request keeps its own count.

**How to test:** automated — `test_agent_graph_tokens.py`.

### 7. Rate-limit check is now fast
It used to load **every** usage row for the day and add them up in Python on
every request. Now it's a single database SUM/COUNT.

**How to test:** automated — `test_rate_limiter.py`. (Behaviour is unchanged;
it's just faster.)

### 8. One date parser instead of ~13 copies
The same "try these date formats" loop was copy-pasted in 13 places. We made
**one** shared `parse_date()` and pointed everything at it.

**How to test:** upload data with mixed date formats (e.g. `2026-01-15`,
`15/01/2026`, `15-01-2026`) and check "overdue" and "expiring soon" still work.
(Automated: `test_dates.py` + the handler tests.)

### 9. Clean, easy-to-read logs
All logging now goes through one config. Each line shows **where** it came from
and a clear tag like `[ROUTER]`, `[DIRECT]`, `[CACHE]`, `[TOKENS]`, `[AI_SIMPLE]`.

**How to test:** run the server and watch the console. For more detail:

```powershell
$env:LOG_LEVEL="DEBUG"; uvicorn main_groq:app --reload
```

You'll see lines like:
`12:34:56 INFO  services.ai_router      [DIRECT] handler=invoice_count`

### 11. Cached answers refresh each day (no stale "days overdue")
The cache key now includes today's date. So a "what's overdue / expiring / due
today" answer cached yesterday is automatically refreshed today, instead of
showing yesterday's numbers. Same-day repeats still hit the cache (fast/cheap).

**How to test:** automated — `test_cache_salt.py` proves the key changes across
days but stays the same within a day. (Live: ask "show overdue" today and again
tomorrow — tomorrow recomputes.)

### 12. Tidied the multi-agent "complex analysis" path
The detailed-analysis path had its instructions written twice (and they'd
drifted — the streaming version was a shortened copy). Merged into one shared
version. Also, complex answers now report their real token cost to the app
(before it showed 0, even though the database recorded it).

**How to test:** automated — `test_token_accounting.py::test_ai_complex_surfaces_real_tokens`.
(Live: ask a "analyze my business and give a recovery plan" type question and
check the reported tokens are non-zero.)

### 10. Migration tooling set up (Alembic)
Added the scaffolding for proper database migrations. **One step is still left**
for you to run (see below).

---

## Things that are set up but need ONE manual step from you

### Set up the Alembic migration baseline

**Background you need to know:**
- `alembic revision --autogenerate` = the AUTHOR step. Run it ONCE, commit the
  generated file in `alembic/versions/` to git. Not run by users.
- `alembic upgrade head` = the APPLY step. Anyone who clones the repo runs this
  to bring their DB up to date. It's the repeatable/automatable one.
- The baseline must be generated against an EMPTY database so it contains clean
  `CREATE TABLE` statements (a baseline that ALTERs tables can't run on a fresh
  clone).

**One-time install (if needed):**
```powershell
cd "D:\Dev Workspace\ai_agent_lab_google(1)\bizassist\backend"
..\venv\Scripts\activate
pip install alembic
```

**Step A — confirm the naming-convention code change is safe:**
```powershell
pytest tests/ -q
```
Expected: **138 passed**. (If red here, the `db.py` naming-convention change
broke something — tell me.)

**Step B — remove any earlier bad migration, then generate a CLEAN baseline
against a throwaway empty DB (keeps your real dev DB untouched):**
```powershell
# delete the earlier messy autogenerate if it exists
Remove-Item alembic\versions\*_baseline_schema.py -ErrorAction SilentlyContinue

$env:DATABASE_URL="sqlite:///./_baseline_tmp.db"
python -m alembic revision --autogenerate -m "baseline schema"
python -m alembic upgrade head
Remove-Item _baseline_tmp.db
```
Expected:
- `revision` prints `Generating ...\alembic\versions\<hash>_baseline_schema.py ... done`
  and the file contains many `op.create_table(...)` calls (NOT `op.alter_column`).
- `upgrade head` prints `Running upgrade  -> <hash>, baseline schema` with **no
  error** (this is the test that the "Constraint must have a name" bug is fixed).

**Step C — mark your existing dev DB as already at the baseline (no DDL run):**
```powershell
$env:DATABASE_URL="sqlite:///./bizassist.db"   # or whatever your real dev DB is
python -m alembic stamp head
```
Expected: `Running stamp_revision  -> <hash>`.

**Step D — commit the new file** in `alembic/versions/` to git.

**For anyone who clones the repo later:** they just run `python -m alembic
upgrade head` once (on an empty DB) — no autogenerate, no manual SQL.

> Note: the app still calls `create_all()` at startup, so a fresh clone already
> builds its tables on first run. Alembic becomes the source of truth for future
> schema CHANGES (like the upcoming Date-column migration) and for Postgres. A
> later cleanup can replace `create_all()` with an automatic `upgrade head` at
> startup so no manual step is ever needed.

---

## What's NOT done yet (honest list)

- Turning date/status columns into real `Date`/enum types in the database
  (needs the Alembic baseline above first, plus a data backfill).
- Switching the ~30 old database-session blocks to the new `get_db()` helper
  (the helper exists; the switch-over is pending).
- Token counting inside the multi-agent path (the simple path is done).
- Optional idea: include the date in the cache key so day-sensitive answers
  ("days overdue") never go stale overnight.

Full detail is tracked in `ARCHITECTURE_REVIEW_AND_PLAN.md` with ✅ / 🟡 / ⬜
marks next to each item.
