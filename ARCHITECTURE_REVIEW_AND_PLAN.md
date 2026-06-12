# BizAssist — Senior Architecture Review & Improvement Plan

*Reviewed: June 2026 · Scope: full backend (`backend/`), React frontend (`frontend-react/`), blueprint docs, notes*

---

## Part 1 — What Is Already Good (keep, don't rewrite)

The 4-tier routing model (CONVERSATIONAL → DIRECT → CACHE → AI_SIMPLE → AI_COMPLEX) is the right economic architecture. The intent registry, action preview→confirm→audit lifecycle (`actions.py` + `ActionLog`), per-user rate limiting with token budgets, local MiniLM embeddings (zero API cost), file dedupe by SHA-256, upload size caps, and 100 passing tests are all things many funded startups don't have. The recent security patches (JWT secret enforcement, CORS allowlist, XSS escaping) landed correctly.

**Verdict: the skeleton is sound. The problems are duplication, brittle routing, concurrency hazards, and an agent layer that is agentic in name but linear in practice.**

---

## Part 2 — Issues Found (ranked by severity)

> **Status legend:** ✅ done & tested · 🟡 partially done · ⬜ not started. Updated as work lands.

### 🔴 Critical — correctness & concurrency

**C1. ✅ `agent_graph.py` global `_run_tokens` is a race condition.**
A module-level dict is reset and mutated per request. Two concurrent AI_COMPLEX requests (FastAPI runs sync routes in a threadpool) will corrupt each other's token counts and billing data. Fix: carry token counts inside `AgentState` / return them from the run.
> **✅ Resolved:** `_run_tokens` deleted; `tokens_in`/`tokens_out` now live in `AgentState`, each node reads-adds-returns, run functions read totals from final state. Concurrent runs can't cross-contaminate. Covered by `test_agent_graph_tokens.py`. (This also unblocks the agent-side of C3.)

**C2. ✅ `handle()` and `handle_stream()` in `ai_router.py` are ~90% duplicated (1,100 lines).**
Session resolution, history fetch, classification, rate limit, cache, DIRECT, intent-first, AI paths — all written twice. They have *already drifted*: the non-stream path reports `"meta": {"tokens": 0}` for AI responses (line 692) while the stream path counts real tokens. Every future fix must be made twice or the paths diverge further. Same disease in `agent_graph.py` (`run_agent_graph` vs `run_agent_graph_stream` duplicate the synthesizer prompt with slightly different wording).
> **✅ Resolved:** `ai_router` collapsed into one `process_query()` generator (`handle()`/`handle_stream()` are thin adapters; `tokens:0` drift fixed; ~1,116→~770 lines). The `agent_graph` synthesizer duplication is also gone — one shared `_SYNTH_SYSTEM` + `_synth_messages()` for both run paths. All tests green.

**C3. ✅ Token accounting is incomplete → budgets are fiction.**
- `_polish()` makes a Groq call (~250 tokens) on every first DIRECT/intent answer — never logged to `TokenUsage`.
- CONVERSATIONAL replies call Groq — never logged.
- Non-stream AI_SIMPLE/AI_COMPLEX responses report `tokens: 0` to the client.
The daily token budget in `rate_limiter.py` enforces against numbers that undercount real spend.
> **✅ Resolved:** every Groq call in `ai_router` flows through one `_log_token_usage()` helper (`_polish`, CONVERSATIONAL, tool rounds); `agent_graph` tokens are logged to `TokenUsage` and now surfaced to the client; the rate-limiter daily total is a SQL aggregate (H4). Budgets and the admin page reflect real spend. Covered by `test_token_accounting.py` + `test_rate_limiter.py`.

**C4. ✅ Global cache invalidation on every upload.**
`upload.py` calls `invalidate()` which clears **all users'** context and query caches. One tenant uploading a CSV evicts every other tenant's warm cache. `invalidate_user_cache(user_id)` already exists — use it.
> **✅ Resolved:** all data-change callers (`upload.py` ×4, `chat.py`, `insights_service.py` ×2) now call `invalidate_user_cache(user_id)`. Admin/global flushes left global by design. Covered by `test_cache_scoping.py`.

**C5. 🟡 In-memory state breaks beyond one worker.**
`context_cache`, `_minute_window`, `_ip_window`, `_upload_window`, and APScheduler are all process-local. Run `uvicorn --workers 2` (or HF Spaces autoscaling) and you get: cache misses, doubled rate-limit allowances, and **duplicate alert emails** from two schedulers. Either pin to one worker deliberately (document it) or move shared state to Redis/SQLite.
> **🟡 Partial:** the caches are now LRU-bounded (`OrderedDict`, `MAX_CACHE_USERS=500`, `MAX_QUERIES_PER_USER=200`) so memory can't grow unbounded — covered by `test_cache_scoping.py`. ⬜ The cross-worker problem itself (shared Redis state / single-worker pin + docs) remains — deferred to Phase 5.

### 🟠 High — robustness & API contract

**H1. ✅ Errors returned as 200-OK bodies.** `handle()` returns `{"error": ..., "status_code": 429}` as a normal dict — the HTTP status is 200. Clients must parse bodies to detect failure. Raise `HTTPException` / return proper status codes; define one error envelope.
> **✅ Resolved:** `services/errors.py` defines `AskError`/`ask_error` (one envelope: `{error, code, ...}`); `handle()` raises it; a `main_groq` exception handler renders real status codes. Streaming keeps the in-band SSE error event (status header already sent). Covered by `test_error_contract.py`. ⚠ Frontend must now read non-2xx + `error`/`code` (client change, out of backend scope).

**H2. Two independent keyword classifiers that can disagree.** `query_router.classify()` (regex tiers) and `ai_router._detect_topic()` (keyword → topic) encode overlapping vocabularies separately. "show my pending invoices report" → `COMPLEX_PATTERNS` catches "report" → a 5-call, 70B multi-agent run for a list query. `COMPLEX_PATTERNS` over-triggers badly: `plan`, `improve`, `report`, `compare`, `list all` are everyday words. This is the #1 cost and quality leak — and the previous session already converged on the fix (semantic routing, see Phase 2).

**H3. 🟡 Dates and statuses are stringly-typed.** `invoice_date`, `due_date`, `expiry_date` are `String` columns; 4-format `strptime` loops are copy-pasted in at least 3 places (`ai_router._build_chart_data`, `context_cache._build_context`, handlers). `status` is free text ("Paid"/"Pending"/"Overdue"). Normalize **once at ingest** (parser/column_mapper) into real `Date` columns and a constrained enum; delete every scattered parse loop.
> **🟡 Mostly done:**
> - *Parse:* `services/dates.py` is the single parser; **all ~13** `strptime` loops delegate to it. (`test_dates.py`)
> - *Normalize at ingest:* `services/normalize.py` (`to_iso`, `normalize_status`) wired into **both** ingest paths (`parser.py` CSV/Excel + `pdf_parser.py`) — new uploads store ISO dates + canonical status. (`test_normalize.py`)
> - *Backfill existing rows:* Alembic data migration `a7c4e9f02b13` written (rewrites old rows to ISO/canonical via the same helpers). User runs it on a DB copy then for real.
> - ⬜ *Remaining (optional):* flip the String columns to real `Date`/`Enum` types. Low value on SQLite (typeless) and risky; meaningful mainly for the future Postgres move — deferred.

**H4. ✅ `rate_limiter._get_today_usage` loads every `TokenUsage` row into Python and sums.** O(rows/day) on **every AI request**. Replace with one `func.count`/`func.sum` SQL aggregate.
> **✅ Resolved:** now one `COUNT`/`SUM`/conditional-`SUM` aggregate query (O(1) work in the DB). Covered by `test_rate_limiter.py` (counts today-only, this-business-only, sums correctly).

**H5. ✅ No real migration story.** Custom `migration.py` + `create_all`. Schema changes on a live DB (Postgres later) need Alembic.
> **✅ Resolved:** Alembic wired (`alembic.ini` + `alembic/env.py` reading `DATABASE_URL` / `Base.metadata`), `alembic` in requirements, and a constraint **naming convention** added to `db.py` (required for SQLite batch ALTERs). Baseline revision `c0017902b685` generated (clean `create_table`) against an empty DB and applied; existing dev DB `stamp`ed to it. Future schema changes: `alembic revision --autogenerate` + `upgrade head`. ⬜ Optional follow-up: replace startup `create_all()` with auto `upgrade head` so clones/deploys need no manual step.

**H6. ✅ ~30 hand-rolled `SessionLocal()` try/finally blocks.** Use FastAPI's `Depends(get_db)` generator; smaller code, no leaked sessions on early returns.
> **✅ Resolved.** Swept all **37 route-handler** session sites across the 6 route modules to `db: Session = Depends(get_db)`: `alerts.py` (2), `auth.py` (2), `actions.py` (1), `admin.py` (13 — the `_db()` helper removed), `chat.py` (4), `upload.py` (5 — three short sessions in `upload_file` collapsed into one injected session), `insights.py` (10). Session lifecycle (close on early return / exception) now guaranteed by the dependency rather than per-handler `finally` blocks. Non-route helpers that aren't request-scoped — `intents.py::_persist_turn`, `upload.py::_process_zip_upload` — correctly keep `SessionLocal()` (already leak-safe). `test_sanitized_errors` updated to inject failure via `app.dependency_overrides[get_db]`. All tests green (196 backend + frontend).

**H7. Session metadata denormalized into `ChatMessage`.** `session_title` copied onto every row; resolving a title costs 2 queries per message. Add a `chat_sessions` table (id, business_id, title, created_at) — also unlocks rename/delete/list cheaply.

**H8. ✅ Entity resolution is substring-only, untested, and mislabeled as "fuzzy".**
> **✅ Resolved:** `_extract_customer_name` now delegates to a pure `_match_customer_name(query, names)` — exact substring first, then a token-set fuzzy match (avg of each name-token's best `difflib` ratio against query tokens, threshold 0.82). Tolerates typos (`nilgris`), dropped letters (`nilgiri`), casing, and word order; rejects unrelated text (`"star performers"` ≠ Star Bazaar). The DB still owns the candidate names. 12 tests in `test_entity_match.py`. The plan's "DB fuzzy-match" claim is now true.

*(original finding below)*
 `_extract_customer_name` (`direct_query_handler.py`) resolves a customer from free text with `name.lower() in query.lower()` — plain substring containment, no typo/casing tolerance and no token-level matching. "nilgiri fresh" (dropped trailing *s*), "nilgris fresh" (typo), or a reordered/partial name returns `None`, so the query silently degrades to a generic answer. This is the *entity* half of every client query ("do you know nilgiris fresh?") and the semantic router (H2 / Phase 1) does **not** fix it — the router only classifies intent *type*; the DB still owns entity resolution. There is also no test coverage for this path. Note: Phase 1 currently *describes* this as already handled by "DB fuzzy-match", which is aspirational — the code is substring-match. Fix: upgrade to `difflib.get_close_matches` / token-set matching against the DB's distinct customer names, return a confidence, and add tests for typo, casing, partial, and reordered-name cases.

### 🟡 Medium — security & frontend

**M1. JWT in `localStorage` with 24 h expiry and no refresh.** Any XSS = full account takeover for a day. Acceptable for a beta; for production move to httpOnly cookie + short-lived access token + refresh, or at minimum shorten expiry and add server-side revocation list.

**M2. `"null"` origin in default CORS allowlist** (`main_groq.py`) permits `file://` pages to call the API. Remove from production defaults.

**M3. `authFetch` picks tokens by `url.includes('/admin/')`** — substring matching is fragile (a future `/admin-ish` route, or admin data fetched from non-admin URL, silently uses the wrong token). Pass an explicit `{ asAdmin: true }` option.

**M4. Admin and enterprise share `/login`** with role check client-side after the fact (`adminLogin`). Server returns a valid token either way. Fine-ish (server still enforces `require_admin` per route — verified), but a dedicated admin login endpoint with audit logging is cleaner.

**M5. Upload pipeline runs synchronously in-request** — PDF OCR + embedding indexing can block a worker for seconds. Move indexing to a background task (`BackgroundTasks` now; queue later).

### 🟢 Agentic gaps (it's an "agent" mostly in branding right now)

**A1. The LangGraph graph is a fixed linear pipeline.** planner → invoice → inventory → payment → synthesizer with skip-flags. No conditional edges, no tool loop, no ability to look at intermediate data and decide to dig deeper. It is an orchestrated fan-out, not an agent.

**A2. The planner parses raw JSON by splitting on \`\`\`** — use structured output (Groq JSON mode / `response_format`) instead of string surgery; on failure it defaults to running *all* agents (most expensive fallback).

**A3. One action exists and it only writes log rows.** `send_payment_reminders` drafts messages but `notifier.py` (email/WhatsApp infra that already exists for alerts) is never wired in. The "agent acts" promise of the blueprint Phase 3 is ~20% delivered.

**A4. Nothing is proactive.** APScheduler sends threshold alerts, but no agent ever *initiates*: no daily digest with proposed actions, no "Nilgiris Fresh just crossed 90 days overdue — want me to draft an escalation?"

**A5. Memory is write-only.** Chat turns are embedded into Chroma and searched per query, but the agent never distills durable business facts ("customer X always pays 2 weeks late") into a curated memory that improves future answers.

**A6. No evaluation harness.** Routing accuracy, answer groundedness, and cache hit rates aren't measured, so every router tweak is vibes-driven. (The 42 routing-tier tests are a start — promote them into a scored eval.)

---

## Part 3 — The Plan

Sequenced so each phase ships independently and de-risks the next. Estimated efforts assume current velocity.

### Phase 0 — Stabilize the core (3–4 days) ← do this first
1. **✅ Extract one pipeline.** Refactor `ai_router.py` into a single `process_query()` engine that returns/yields events; `/ask` collects them into one JSON, `/ask/stream` forwards them as SSE. One code path, zero drift. Do the same for `agent_graph` (one synthesizer, streaming flag). — *Done: `ai_router` unified (1,116→~770 lines); `agent_graph` synthesizer now one shared `_SYNTH_SYSTEM`/`_synth_messages()` across both run paths. All green.*
2. **✅ Fix token truth.** Log every Groq call (`_polish`, CONVERSATIONAL, planner, synthesizer, tool rounds) to `TokenUsage`; return real totals in `meta.tokens`. — *Done: `ai_router` calls via `_log_token_usage`; `agent_graph` tokens carried in state and now surfaced to the client (`run_agent_graph` returns `{text,tokens_in,tokens_out}`; stream reads `ag_done` tokens). Covered by `test_token_accounting.py` incl. `test_ai_complex_surfaces_real_tokens`.*
3. **✅ Kill the races.** Move `_run_tokens` into graph state. Replace per-user upload invalidation (`invalidate()` → `invalidate_user_cache(user_id)`). Add max-size (LRU) bounds to both in-memory caches. — *Done: C1 (token race) + C4 (upload scoping) + LRU bounds, all test-covered (`test_agent_graph_tokens.py`, `test_cache_scoping.py`). Cross-worker shared state (rest of C5) deferred to Phase 5.*
4. **✅ Proper HTTP errors.** One error envelope, correct status codes, raised via `HTTPException`. — *Done (H1): `AskError`/`ask_error` + `main_groq` handler; `test_error_contract.py`.*
5. **✅ SQL aggregates in rate limiter**; `Depends(get_db)` session injection; Alembic init. — *SQL aggregate ✅ (H4, `test_rate_limiter.py`). Alembic ✅ (H5 — baseline `c0017902b685` generated & applied; naming convention added). `get_db()` sweep ✅ (H6 — all 37 route-handler sessions migrated; non-route helpers keep `SessionLocal()`).*
6. **🟡 Normalize at ingest:** real `Date` columns + status enum, single date-parser utility; delete the 3 copy-pasted format loops. — *Done: single parser + all loops deduped (`test_dates.py`); ingest normalization in both paths (`services/normalize.py`, `test_normalize.py`); backfill migration `a7c4e9f02b13` for old rows. ⬜ Only the optional String→`Date`/`Enum` column-type flip remains (deferred — SQLite-moot, matters for Postgres).*
   - *DoD: all tests green (now 196) + new tests for token logging, cache scoping, errors, rate limiter, dates; `wc -l ai_router.py` roughly halves. — ✅ ai_router halved & tests added; H5 baseline ✅ + H6 sweep ✅; only the optional H3 String→`Date`/`Enum` column flip stays deferred.*

> **✅ C6 — date-key the query cache.** Done: `_cache_salt()` folds the current date into the salt (`md5(user_id:YYYY-MM-DD:topic)`), so day-sensitive answers ("days overdue", "expiring", "today's priorities") refresh each day and a longer TTL is now safe; same-day variants still share a hit. Covered by `test_cache_salt.py`.

> **Cross-cutting (not a numbered phase item): ✅ Logging.** Central `backend/logging_config.py` (`configure_logging()` + `get_logger()`, env `LOG_LEVEL`, noisy libs muted) wired into `main_groq.py`; message tags standardized app-wide into one greppable scheme (`[ROUTER]`/`[CACHE]`/`[DIRECT]`/`[TOKENS]`/…). Unit-tested in `test_logging_config.py`. Supports the Phase 5 observability goal.

### Phase 1 — Semantic intent router (🟡 in progress — Steps 1 & 2 done)
Replace `query_router.py` regexes + `_detect_topic` keywords with **one** embedding router.

- **✅ Step 1 — build the router.** `services/intent_router.py`: ~8–12 seed phrases per label (12 DB intents + `conversational`/`ai_simple`/`ai_complex`), embedded with the already-loaded MiniLM; `classify(query) → (tier, intent_key, confidence)`, nearest-seed by cosine (vectorized with numpy), below-threshold → AI_SIMPLE. Injectable encoder/seed for testing. Covered by `test_intent_router.py` (mechanics + a scored eval harness that prints accuracy). Now **122 seed examples**; held-out eval **95% on 22 cases** (the one MISS is `tell me about nilgiris fresh` — "fresh" confounds it — kept as honest signal rather than overfitted away).
- **✅ Step 2 — shadow mode (now LIVE).** `INTENT_ROUTER` flag (`off`|`shadow`|`on`). Set to **`shadow` in `.env`** — the server now logs `[ROUTER][shadow] AGREE|DISAGREE …` per request, changing nothing. `LOG_FILE=logs/bizassist.log` persists logs, and **`backend/analyze_shadow.py`** tallies AGREE/DISAGREE + top disagreements against the 95% cutover bar. Proven not to alter routing by `test_shadow_routing.py`.
- **🟡 Step 3 — cutover (gathering data, NOT ready).** ✅ **H8 done** — token-set fuzzy matching (`test_entity_match.py`). 🟡 **Client seeds added** — 8 name-bearing `client_summary` seeds lifted `do you know <name>` lookups (eval: `do you know srinivas kirana` 0.36→0.70 ✅), but `tell me about nilgiris fresh` still MISSES at 0.33 (the word "fresh" confounds it). So the semantic router is **not** cutover-ready — real shadow traffic confirms it still diverges on client lookups and compound phrasings (`tell me about <name> payment status and invoices` → invoice_count). ⬜ Remaining: keep collecting `DISAGREE` data; reach ≥95% on real traffic before making semantic primary with regex fallback. Deliberately NOT overfitting seeds to individual misses.
   - *DoD: one classifier, measured ≥95% accuracy on real traffic, `COMPLEX` no longer triggers on "report/plan/improve" unless genuinely multi-source.*

**✅ Routing-correctness fixes (landed & tested this session — found via manual testing):**
These harden the *current* (regex + cache) path so it's correct while shadow data accrues for the cutover.
- **✅ Cache-discriminator collisions.** `_detect_topic` is coarse and was the cache key, so distinct intents that map to the same topic shared a cache entry ("total revenue" → invoice count; "who owes me most" → overdue list; "draft reminder" → overdue data). `_cache_disc` now keys DIRECT on `handler_key`, AI_COMPLEX/writing on the exact query, AI_SIMPLE on topic. Covered by `test_cache_salt.py`.
- **✅ `client_summary` keyed per customer.** Was keyed on topic, so "tell me about <customer A>" and a fake name returned the first cached customer. Now keyed on the query. Covered by `test_cache_salt.py::test_client_summary_keyed_on_query_per_customer`.
- **✅ Entity-first routing (the bare-name case).** A short (≤4-word) `AI_SIMPLE` query that names a known customer (e.g. `namdhari fresh`) now reroutes to `DIRECT/client_summary` *before* keyword topic detection — so "fresh" no longer mis-routes to `expiring_soon`. `_maybe_entity_first` in `ai_router`, covered by `test_entity_match.py`.
- **✅ Unknown-customer no longer hallucinates.** When `client_summary` can't resolve a named customer, the handler returns an honest `CUSTOMER_NOT_FOUND` message verbatim (no `_polish`, no business-wide insights) instead of falling through to the LLM, which used to fabricate a ₹0 client card. A `_is_general_about_query` guard keeps "tell me about my business" flowing to the AI overview. Covered by `test_entity_match.py`.
- **✅ Entity scoping (named single customer wins).** `_maybe_entity_first` now scopes ANY query that names one known customer to `client_summary` — both bare lookups (`namdhari fresh`, `do yo know Rahul traders`) AND global-aggregate queries scoped to a customer (`how much does Nilgiris Fresh owe me` → Nilgiris's overdue, not the all-customers list). Skipped only for writing tasks (`_WRITING_ACTIONS`) and list-all/ranking phrasings (`_MULTI_SIGNAL`: all/list/top/most/compare…). Replaced the earlier word-cap + analytical-block approach, which wrongly sent customer-scoped questions to the global view. Covered by `test_entity_match.py`.
- **✅ Catch-all cache collision.** `business_summary` is also `_detect_topic`'s default, so unrelated AI_SIMPLE fallbacks ("do yo know Rahul traders") shared one cache entry and got served a stale generic summary. AI_SIMPLE on the catch-all now keys on the query. Covered by `test_cache_salt.py`.
- **✅ "Did you mean" chips.** When a named lookup just misses the 0.82 confidence bar, `_customer_candidates` surfaces near-miss customers as clickable suggestion chips (type `ai`, prompt `tell me about <Name>`) instead of a flat not-found. Covered by `test_entity_match.py`.
- **✅ Writing-task detection fix.** `_WRITING_ACTIONS` missed "follow-up" (and other comms nouns), so "draft a polite follow-up to this customer" was `writing=False` → promoted to the overdue data handler → dumped 249 rows instead of drafting. Added `follow-up`/`reply`/`response`/`whatsapp`/`sms`/`statement`/… Covered by `test_writing_router.py`. Verified live (`writing=True` → AI writing path).

**✅ Chat-session & infra fixes (this session — found via manual testing + HAR):**
- **Stale service worker (root cause of "app not wired to backend").** An orphaned PWA service worker was serving `/chat/history` + `/chat/sessions` from a `bizassist-v1` cache (125 cached responses in the HAR) — so new messages vanished, deletes didn't reflect, the app looked disconnected. Removed the registration AND added a self-unregister + cache-purge script to `index.html` (a registered SW persists until explicitly killed). Removed the dead `/public/manifest.json` + `sw.js` references.
- **Session titles = first SUBSTANTIVE message.** Was the first message verbatim, so every chat opened with "hi" was titled "hi". `_resolve_session` now skips greetings and retro-fits earlier rows; `backend/backfill_titles.py` (dry-run default) re-titles existing history. Covered by `test_session_title.py`.
- **AuthContext memoization + session-fetch race.** `authFetch`/context value now `useCallback`/`useMemo` (stops a re-render→re-fetch loop that clobbered live messages); `fetchSessions` gained a `force` flag so post-mutation refreshes don't reuse a stale in-flight `/chat/sessions` (the "delete didn't reflect" / "New Chat lost previous" sidebar bugs).
- **Rate-limiter UTC boundary (pre-existing).** `_get_today_usage` used local `date.today()` but `TokenUsage.timestamp` is `utcnow()` — daily caps mis-counted near midnight (under-enforced in the first IST hours of a day). Now UTC-consistent. Covered by `test_rate_limiter.py`.

**Phase 1 follow-ups (deferred, take up later):**
- **Pre-warm the router at startup.** First request in shadow/on mode builds the seed matrix (~140 encodes, <1s) and warms the model. `preload_model_async` already warms the embedding model; also pre-build the router's seed matrix there for zero first-request latency.
- **Fast/full test split.** Tag the model-dependent tests (`test_semantic_router_eval_accuracy`, `test_rag` model tests) with `@pytest.mark.slow` + a small `pytest.ini`, so day-to-day runs `pytest -m "not slow"` (a few seconds, no model load) and CI/pre-commit runs the full suite.

### Phase 1.5 — Answer-quality feedback loop (🟡 foundation landed)
A correction loop so wrong answers get captured and fixed instead of lost — and the data foundation for *safe* auto-learning later.

**✅ Step 1 — capture-intent + instant override (built this session).**
- Models `Feedback` (append-only 👍/👎 log: query, route, handler, verdict, correction) and `QueryOverride` (active per-user corrections, unique on `business_id`+`query_norm`).
- `POST /feedback` (verdict + optional correction) and `GET /feedback/intents` (the picker list); UI = 👍/👎 under each answer, 👎 opens a "what did you want?" intent picker.
- `services/feedback_service.py`: `record_feedback` upserts an override on a corrected down-vote and busts the user cache; `get_override` is checked at the top of routing (after entity-first, above all else).
- Behaviour: **mark wrong → pick the right intent → re-run the same query → corrected answer** (exact-query scoped). A down-vote with no correction just logs (a labelled example for offline tuning). Covered by `test_feedback.py`.
- ⬜ Follow-up: generate an Alembic migration for the two tables before any Postgres move (`create_all` covers SQLite dev).

**Future — safe auto-learning (design, deferred). Guiding principle: NEVER mutate the curated seeds; layer learning on top, gate every promotion behind the eval.**
1. **Isolate the learned layer.** Routing precedence: explicit overrides → curated seeds → *learned* examples (separate store, lowest priority). Curated seeds stay immutable, so the learned layer is always wipe-able back to known-good. Isolation is what makes it un-breakable.
2. **Promote on evidence, not first sight.** One correction stays an exact-match override (today's behaviour). Only a *recurring* correction (N independent sessions/users, same fix) becomes a candidate to influence *similar* (fuzzy) queries — so one odd correction can't poison routing.
3. **Gate promotion behind the eval.** Before a learned example affects routing, run the seed set *with it added* against the held-out eval (`test_intent_router`); promote only if accuracy doesn't drop. The eval is the regression guardrail.
4. **Shadow-first + reversible.** Every learned change rides shadow mode first (measure AGREE/DISAGREE before it drives anything), with an env kill-switch to disable the whole learned layer instantly.
5. **Confidence with decay.** Learned routes carry a weight that grows on repeated confirmation and shrinks when later contradicted (a 👎 on a learned route lowers it) — self-correcting, not ossifying.
6. **(Optional) one-click human approve.** Eval-passing candidates wait in a small review queue for approval before going live; drop the human gate once the eval gate is trusted.

> Why it's safe: points 1 + 3 together — curated seeds are immutable, and nothing learned is trusted until it's been measured against them and *failed to make things worse*.

### Phase 1.6 — Smart Insights / Business Advisor (✅ landed)
Replaced the per-answer 💡 insight bulb (which confabulated on factual answers — "₹1,597 more than the due date") with a dedicated, grounded advisor.

- **✅ Removed the bulb.** `_polish` no longer runs on DIRECT/INTENT answers — they return clean DB data (and now cost **0 tokens / no LLM call**). Deterministic alert chips (cash-flow / expiry) stay.
- **✅ Engine — `services/smart_insights.py`.** `build_snapshot(user_id)` = 100% deterministic SQL across collections + aging, top debtors, customer concentration, product fast-movers + dead stock, and risk. `generate_insights(user_id)` feeds that to the 70B model with a grounded prompt → prioritized strengths + improvements, each citing a real ₹ figure, `polarity` ∈ {positive, improve}; model-free fallback. `build_panel_insights(user_id)` = deterministic positive/improve split (no LLM).
- **✅ Routes.** `GET /smart-insights` (on-demand 70B narrative, the chat chip) and `GET /smart-insights/summary` (deterministic split for the always-on right pane).
- **✅ Frontend.** "Smart Insights" chip → full advisor in chat; right-pane "Business Insights" now shows **✓ What's working / ⚠ Could be better** (deterministic, free, always-on), replacing the donut/overdue cards that duplicated the Dashboard. Covered by `test_smart_insights.py`.
- **Trust model:** the always-visible panel is deterministic (free, instant, can't hallucinate); the heavy 70B reasoning is pull-only and always cites the number behind each point.

**⬜ Future — query-contextual deterministic insights (to build later).**
After a relevant answer, surface ONE small **grounded** insight scoped to that query's topic — e.g. "show overdue invoices" → *"Nilgiris Fresh is your biggest debtor (₹2,65,623); ₹1.99L is 180+ days overdue."* Pulled from the snapshot (SQL only, **no LLM**), so it brings back the per-query usefulness of the old bulb WITHOUT the fabrication risk that got the bulb removed. Map each DIRECT topic → a deterministic insight selector over `build_snapshot`; attach it to the answer envelope; render under the answer. Reuses the existing snapshot, so it's a contained addition.

### Phase 2 — A real agent loop (4–5 days)
Rebuild `agent_graph` as an actual agent, not a pipeline:
- **Tool-loop architecture:** planner (JSON mode, structured output) → conditional edges → agent node may call any registered tool, inspect results, and decide to call more (bounded: max 6 tool calls / token budget guard mid-run) → reflection node checks "does the data actually answer the goal?" → synthesizer.
- **Structured outputs everywhere** — `response_format={"type":"json_object"}` for planner/reflection; delete the \`\`\`-splitting.
- Stream `status` events from real graph progress (you already have the SSE plumbing).
- Cheapest failure mode: planner failure falls back to *invoice-only* (most common domain), not all-agents.
   - *DoD: "why is my collection rate dropping?" produces a run trace showing the agent choosing tools adaptively; cost per complex query drops (no blanket fan-out).*

### Phase 3 — Actions that act (3–4 days)
- Wire `notifier.py` into `send_payment_reminders` — real email (and WhatsApp where numbers exist), still preview→confirm→audit, plus **idempotency keys** so a double-click can't double-send.
- Add the next 3 registry actions: `draft_reorder_po` (low stock → PurchaseOrder draft), `mark_invoice_paid`, `escalate_overdue` (90+ day accounts → firmer letter). Each invalidates the user's cache on execute.
- Per-action rate limits + daily action caps in `RateLimitConfig`.
   - *DoD: an owner can go from "who owes me?" → confirm → reminders actually delivered, fully audited.*

### Phase 4 — Proactive agent (3 days)
- Scheduled **daily digest agent**: runs the (now cheap) agent loop per business each morning, produces "3 things that need you today" + suggested actions (each a one-tap confirm). Delivered via existing alerts channel and shown in-app.
- **Anomaly → suggestion bridge:** `detect_anomalies` output becomes actionable chips, not just alerts.
- **Distilled memory:** weekly job summarizes stable business facts into a `business_facts` collection injected into the snapshot (~80 tokens) — the agent starts "knowing" the business.
   - *DoD: a user who never types a query still gets agent value daily.*

### Phase 5 — Production hardening (ongoing)
- Postgres migration via Alembic (SQLite stays for dev), WAL mode meanwhile.
- Redis for cache + rate-limit windows + scheduler lock **when** you scale past one worker — until then, document the single-worker constraint in the Dockerfile/start command.
- Observability: request-ID middleware, per-tier latency/cost metrics, router-disagreement log.
- Auth: shorter access tokens + refresh; move admin to dedicated endpoint; drop `"null"` origin.
- CI: run pytest + the routing eval on every push.

---

## Part 4 — What NOT to do
- **Don't** add an LLM call to classify every message (per your own previous-session conclusion — embeddings are free, faster, offline).
- **Don't** rewrite the intent/action registries or the envelope contract — they're the best parts.
- **Don't** migrate to microservices/Celery/Kafka at this stage; a single FastAPI app with honest constraints will carry you to thousands of users.
- **Don't** start Phase 2 before Phase 0 — building a smarter agent on top of duplicated pipelines doubles the refactor cost later.

## Sequencing summary

| Phase | Theme | Effort | Status | Risk it removes |
|---|---|---|---|---|
| 0 | Correctness & dedup | 3–4 d | ✅ done (items 1–6 ✅, H4/H5/H6 ✅, logging ✅, C6 ✅; only the optional String→`Date`/`Enum` column flip deferred — SQLite-moot) | billing drift, races, cache bleed |
| 1 | Semantic router | 2 d | 🟡 Steps 1 & 2 ✅ (router + eval + shadow now LIVE in `.env` + `analyze_shadow.py`); H8 ✅, routing-correctness + chat/infra fixes landed, client seeds 🟡 (1 of 2 held-out lookups cleared); Step 3 cutover gated on real shadow data (not ready — still diverges on client/compound lookups) | wrong-tier cost leak, regex maintenance |
| 1.5 | Answer-quality feedback loop | 1 d | 🟡 Step 1 ✅ (feedback + instant override built + tested); safe auto-learning designed, deferred | wrong answers lost, no correction path |
| 1.6 | Smart Insights advisor | 1 d | ✅ built (bulb removed; grounded 70B advisor + deterministic panel split); query-contextual insights deferred | hallucinated insights, scattered weak bulbs |
| 2 | Real agent loop | 4–5 d | ⬜ not started | fake agency, blanket fan-out cost |
| 3 | Real actions | 3–4 d | ⬜ not started | "agent that doesn't act" |
| 4 | Proactive digest | 3 d | ⬜ not started | zero-engagement users |
| 5 | Hardening | ongoing | ⬜ not started (logging foundation laid) | scale/security cliffs |

Start with Phase 0, item 1 (the `ai_router` unification) — it touches the most-edited file in the repo and every later phase gets cheaper once it lands.

**Phase 0 remaining:**
- ✅ **H6 sweep done** — all 37 route-handler `SessionLocal()` blocks migrated onto `Depends(get_db)`. Phase 0 is complete; only the optional String→`Date`/`Enum` column-type flip stays deferred (SQLite-moot, matters only for a future Postgres move).
- Optional/deferred: the H3 String→`Date`/`Enum` column-type flip (SQLite-moot; for the Postgres move); replace startup `create_all()` with auto `alembic upgrade head`.

Everything else in Phase 0 is ✅ (H3 is now functionally complete: parse + ingest-normalize + backfill migration). Per **Part 4**, finish H6 before touching Phase 1/2.
