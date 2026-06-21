# BizAssist — Senior Architecture Review & Improvement Plan

*Reviewed: June 2026 · Scope: full backend (`backend/`), React frontend (`frontend-react/`), blueprint docs, notes*

---

## Part 1 — What Is Already Good (keep, don't rewrite)

The 4-tier routing model (CONVERSATIONAL → DIRECT → CACHE → AI_SIMPLE → AI_COMPLEX) is the right economic architecture. The intent registry, action preview→confirm→audit lifecycle (`actions.py` + `ActionLog`), per-user rate limiting with token budgets, local MiniLM embeddings (zero API cost), file dedupe by SHA-256, upload size caps, and 100 passing tests are all things many funded startups don't have. The recent security patches (JWT secret enforcement, CORS allowlist, XSS escaping) landed correctly.

**Verdict: the skeleton is sound. The problems are duplication, brittle routing, concurrency hazards, and an agent layer that is agentic in name but linear in practice.**

---

## Part 2 — Issues Found (ranked by severity)

### 🔴 Critical — correctness & concurrency

**C1. `agent_graph.py` global `_run_tokens` is a race condition.**
A module-level dict is reset and mutated per request. Two concurrent AI_COMPLEX requests (FastAPI runs sync routes in a threadpool) will corrupt each other's token counts and billing data. Fix: carry token counts inside `AgentState` / return them from the run.

**C2. `handle()` and `handle_stream()` in `ai_router.py` are ~90% duplicated (1,100 lines).**
Session resolution, history fetch, classification, rate limit, cache, DIRECT, intent-first, AI paths — all written twice. They have *already drifted*: the non-stream path reports `"meta": {"tokens": 0}` for AI responses (line 692) while the stream path counts real tokens. Every future fix must be made twice or the paths diverge further. Same disease in `agent_graph.py` (`run_agent_graph` vs `run_agent_graph_stream` duplicate the synthesizer prompt with slightly different wording).

**C3. Token accounting is incomplete → budgets are fiction.**
- `_polish()` makes a Groq call (~250 tokens) on every first DIRECT/intent answer — never logged to `TokenUsage`.
- CONVERSATIONAL replies call Groq — never logged.
- Non-stream AI_SIMPLE/AI_COMPLEX responses report `tokens: 0` to the client.
The daily token budget in `rate_limiter.py` enforces against numbers that undercount real spend.

**C4. Global cache invalidation on every upload.**
`upload.py` calls `invalidate()` which clears **all users'** context and query caches. One tenant uploading a CSV evicts every other tenant's warm cache. `invalidate_user_cache(user_id)` already exists — use it.

**C5. In-memory state breaks beyond one worker.**
`context_cache`, `_minute_window`, `_ip_window`, `_upload_window`, and APScheduler are all process-local. Run `uvicorn --workers 2` (or HF Spaces autoscaling) and you get: cache misses, doubled rate-limit allowances, and **duplicate alert emails** from two schedulers. Either pin to one worker deliberately (document it) or move shared state to Redis/SQLite.

### 🟠 High — robustness & API contract

**H1. Errors returned as 200-OK bodies.** `handle()` returns `{"error": ..., "status_code": 429}` as a normal dict — the HTTP status is 200. Clients must parse bodies to detect failure. Raise `HTTPException` / return proper status codes; define one error envelope.

**H2. Two independent keyword classifiers that can disagree.** `query_router.classify()` (regex tiers) and `ai_router._detect_topic()` (keyword → topic) encode overlapping vocabularies separately. "show my pending invoices report" → `COMPLEX_PATTERNS` catches "report" → a 5-call, 70B multi-agent run for a list query. `COMPLEX_PATTERNS` over-triggers badly: `plan`, `improve`, `report`, `compare`, `list all` are everyday words. This is the #1 cost and quality leak — and the previous session already converged on the fix (semantic routing, see Phase 2).

**H3. Dates and statuses are stringly-typed.** `invoice_date`, `due_date`, `expiry_date` are `String` columns; 4-format `strptime` loops are copy-pasted in at least 3 places (`ai_router._build_chart_data`, `context_cache._build_context`, handlers). `status` is free text ("Paid"/"Pending"/"Overdue"). Normalize **once at ingest** (parser/column_mapper) into real `Date` columns and a constrained enum; delete every scattered parse loop.

**H4. `rate_limiter._get_today_usage` loads every `TokenUsage` row into Python and sums.** O(rows/day) on **every AI request**. Replace with one `func.count`/`func.sum` SQL aggregate.

**H5. No real migration story.** Custom `migration.py` + `create_all`. Schema changes on a live DB (Postgres later) need Alembic.

**H6. ~30 hand-rolled `SessionLocal()` try/finally blocks.** Use FastAPI's `Depends(get_db)` generator; smaller code, no leaked sessions on early returns.

**H7. Session metadata denormalized into `ChatMessage`.** `session_title` copied onto every row; resolving a title costs 2 queries per message. Add a `chat_sessions` table (id, business_id, title, created_at) — also unlocks rename/delete/list cheaply.

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
1. **Extract one pipeline.** Refactor `ai_router.py` into a single `process_query()` engine that returns/yields events; `/ask` collects them into one JSON, `/ask/stream` forwards them as SSE. One code path, zero drift. Do the same for `agent_graph` (one synthesizer, streaming flag).
2. **Fix token truth.** Log every Groq call (`_polish`, CONVERSATIONAL, planner, synthesizer, tool rounds) to `TokenUsage` with an `endpoint`/`purpose` tag; return real totals in `meta.tokens`. Budgets become enforceable and the admin usage page becomes honest.
3. **Kill the races.** Move `_run_tokens` into graph state. Replace per-user upload invalidation (`invalidate()` → `invalidate_user_cache(user_id)`). Add max-size (LRU) bounds to both in-memory caches.
4. **Proper HTTP errors.** One error envelope, correct status codes, raised via `HTTPException`.
5. **SQL aggregates in rate limiter**; `Depends(get_db)` session injection; Alembic init.
6. **Normalize at ingest:** real `Date` columns + status enum, single date-parser utility; delete the 3 copy-pasted format loops.
   - *DoD: all 100 tests green + new tests for token logging and cache scoping; `wc -l ai_router.py` roughly halves.*

### Phase 1 — Semantic intent router (2 days — design already done in your previous session)
Replace `query_router.py` regexes + `_detect_topic` keywords with **one** embedding router:
- Chroma collection `intent_examples`, 10–15 seed phrases per intent (13 intents + `ai_simple`/`ai_complex`/`conversational` buckets), embedded with the already-loaded MiniLM.
- `intent_router.classify(query) → (tier, intent_key, confidence)`; below threshold → AI_SIMPLE. Customer names still resolved by DB fuzzy-match (LLM/embeddings never invent entities).
- Keep the current regex router as a fallback behind a feature flag for one release; log disagreements.
- **Eval harness:** turn `test_routing_tiers.py` cases into a scored accuracy suite (target ≥95% on the 100-case set). New intent = add example phrases, rerun eval. No code, no regex, no broken tests.
   - *DoD: one classifier, measured accuracy, `COMPLEX` no longer triggers on "report/plan/improve" unless the query genuinely needs multi-source analysis.*

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

| Phase | Theme | Effort | Risk it removes |
|---|---|---|---|
| 0 | Correctness & dedup | 3–4 d | billing drift, races, cache bleed |
| 1 | Semantic router | 2 d | wrong-tier cost leak, regex maintenance |
| 2 | Real agent loop | 4–5 d | fake agency, blanket fan-out cost |
| 3 | Real actions | 3–4 d | "agent that doesn't act" |
| 4 | Proactive digest | 3 d | zero-engagement users |
| 5 | Hardening | ongoing | scale/security cliffs |

Start with Phase 0, item 1 (the `ai_router` unification) — it touches the most-edited file in the repo and every later phase gets cheaper once it lands.
