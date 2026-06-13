# BizAssist — Senior Architecture Review v2 (Fresh Pass)

*Reviewed: June 2026 · Second full review after the Phase-0/Phase-1 work landed. Every claim below was verified against the current code, not the changelog.*

---

## Part 1 — Verification of the New Work (independently confirmed)

I re-read the changed code rather than trusting the annotations in the v1 doc. Findings:

| Claimed fix | Verified? | Evidence |
|---|---|---|
| One pipeline (`process_query` generator, thin `handle`/`handle_stream` adapters) | ✅ Real | `ai_router.py` — single generator yields `status/replace/token/final/error` events; both endpoints drain it. The `tokens:0` drift is gone. |
| Token race in agent graph | ✅ Real | `tokens_in/tokens_out` carried in `AgentState`; module global deleted. |
| Token accounting | ✅ Mostly real | `_log_token_usage()` is the single sink; `_polish`, CONVERSATIONAL, tool rounds, agent-graph totals all flow through it. **One gap remains — see R1.** |
| Per-tenant cache invalidation | ✅ Real | `upload.py` ×4, `chat.py`, `insights_service.py` ×2 all call `invalidate_user_cache(user_id)`; only admin flush stays global (by design). |
| LRU-bounded caches | ✅ Real | `OrderedDict` + `move_to_end` + eviction at 500 users / 200 queries-per-user. |
| Error contract | ✅ Real | `services/errors.py` (`AskError`), registered `@app.exception_handler` in `main_groq.py`; frontend `Chat.jsx` already reads non-2xx + `{error, code}` and handles 429. |
| Rate limiter SQL aggregate | ✅ Real | One `COUNT`/`SUM`/conditional-`SUM` query. |
| Date/status normalization at ingest | ✅ Real | `services/dates.py` + `services/normalize.py` wired into `parser.py` and `pdf_parser.py`; Alembic baseline + backfill migrations exist. |
| Semantic router | ✅ Built, ⏳ not live | `intent_router.py` — vectorized nearest-seed classifier over MiniLM, injectable encoder, 15 labels, threshold 0.45. Runs in **shadow mode** (`INTENT_ROUTER=shadow`) logging AGREE/DISAGREE; `analyze_shadow.py` produces the cutover report. |
| Logging overhaul | ✅ Real | `logging_config.py` — component column, canonical `[TAG]`s, env-tunable level, optional rotating file log. |
| Test suite | ✅ Grew 100 → **182 tests** across 21 files (token accounting, cache salt/scoping/regression, error contract, entity matching, shadow routing, normalization, dates…). |

Also new and good, not even claimed in v1: the **cache-salt discriminator** (`_cache_disc`) fixes real collision bugs (per-day salt, `client_summary` keyed per-query, `business_summary` fallback keyed per-query, writing tasks keyed per-query), **entity-first routing** (short query naming a known customer beats keyword misroutes, DB-fuzzy-matched at 0.82), **tool-result truncation** (`MAX_TOOL_CHARS` protects the Groq TPM budget), and an **honest "customer not found"** path that refuses to let the polish-LLM invent a client card.

**Verdict v2: this is a different codebase from three weeks ago. Phase 0 is genuinely done. The engineering discipline (every fix has a test, every subsystem logs greppably) is now above typical seed-startup standard. The remaining work is no longer cleanup — it is cutover, hardening, and the agentic leap.**

---

## Part 2 — Remaining & Newly-Found Issues

### 🔴 R1. Streaming responses under-count tokens (new finding)
In `process_query`, streamed paths never see a `usage` object: CONVERSATIONAL-stream logs nothing, and AI_SIMPLE-stream logs only the first (non-stream) tool-calling round — the streamed final round is invisible. Since the React client uses `/ask/stream` for everything, **most real traffic logs roughly half its output tokens**, and daily budgets drift optimistic again. Fix is small: pass `stream_options={"include_usage": true}` (Groq supports the OpenAI-compatible option) and log the final usage chunk; fall back to a `len(full_text)//4` estimate if absent.

### 🔴 R2. Three classifiers now coexist — the cutover must *delete*, not accumulate
Live regex `classify()` + keyword `_detect_topic()` + shadow `intent_router`. This is correct *transitionally*, but it's also the most dangerous resting state: every routing bug now has three suspects. Two sharp edges in the current cutover design:
- **Shadow "DISAGREE" has no ground truth.** The log compares semantic vs regex, but when they disagree nobody knows who's right. Use the 42 `test_routing_tiers` cases (plus disagreement samples you hand-label) as a gold set and score *both* routers against it — cut over on measured accuracy, not agreement rate.
- **Threshold 0.45 is permissive** for MiniLM cosine over short queries; expect confident wrong matches on 2–3-word queries ("fresh stock?"). Consider a margin test (best − second-best label score) in addition to the absolute threshold.
- After cutover, `_detect_topic` should collapse into the semantic router's label (it *is* the topic) — that's ~150 lines of keyword tables deleted and one source of truth for route + cache-salt + recommendations.

### 🟠 R3. Multi-worker hazard still open (was C5, unchanged)
Caches, rate-limit windows, and APScheduler remain process-local. Acceptable **only if** the deployment is pinned to one worker — but nothing enforces or documents that. Minimum: assert/warn on `WEB_CONCURRENCY>1` at startup and a README note; real fix (Redis or DB-backed windows + scheduler lock) stays in Phase 5.

### 🟠 R4. Planner JSON is still parsed by splitting on ``` (was A2, unchanged)
And its failure mode is still the most expensive one (run *all* agents). Use Groq JSON mode (`response_format={"type":"json_object"}`) and fall back to invoice-only.

### 🟠 R5. `ai_router.py` is creeping back up (~1,070 lines)
The pipeline itself is clean now, but `_build_chart_data` (~120 lines of presentation logic) and `_detect_topic` (~115 lines, dies in R2 anyway) don't belong in the router. Extract `services/charts.py`; the file lands near ~700 and stays there.

### 🟡 R6. Deferred-from-v1 items, still valid, still queued
- **H6:** ~30 manual `SessionLocal()` blocks → `Depends(get_db)` / context-manager helper.
- **H7:** `chat_sessions` table (title still denormalized; `_resolve_session` is 2 queries per message).
- **M1:** JWT in localStorage, 24 h, no refresh.
- **M2:** `"null"` origin **still present** in default CORS (`main_groq.py` line 55) — one-line removal, do it now.
- **M3:** `authFetch` admin-token selection by URL substring.
- **M5:** upload OCR + embedding indexing still synchronous in-request.

### 🟢 R7. The agentic gap is now the headline item
Phase 0 paid the debt; the "agent" itself is unchanged since v1: a **fixed linear graph** (planner → 3 fetchers → synthesizer, skip-flags only), **one action** that writes log rows instead of sending anything (`notifier.py` still unwired), **nothing proactive**, **memory write-only** (turns embedded, never distilled). This is now where every invested day buys the most product value.

---

## Part 3 — The Plan (v2)

Phase 0 ✅ done. Renumbered from here.

### Phase 1 — Finish the router cutover (1–2 days) ← current priority
1. Fix **R1** streaming token usage (`include_usage`) — small, restores budget truth on the main traffic path. *(Do first; it re-baselines the cost data you'll use to judge the cutover.)*
2. Build the **gold eval set**: routing-tier test cases + hand-labeled shadow disagreements (~150 cases). Score regex vs semantic. Add the margin test to `SemanticRouter`.
3. Cut over (`INTENT_ROUTER=on`): semantic router becomes `classify()`; regex kept one release as a sub-threshold fallback; **delete `_detect_topic`** — topic = matched label. Cache-salt discriminator now keys on the *same* label that routed the query (kills the residual classify-vs-topic disagreement class).
4. *DoD: one classifier in the request path, ≥95% on the gold set, `query_router.py` keyword tables deleted next release.*

### Phase 2 — Real agent loop (4–5 days)
Planner with JSON mode (R4) → **conditional edges + bounded tool loop** (agent inspects results, may call more tools, max 6 calls + mid-run token-budget guard) → reflection node ("does the data answer the goal?") → synthesizer. Stream real graph progress as `status` events (plumbing already exists). Failure fallback = invoice-only, not all-agents.
*DoD: a run trace shows adaptive tool choice; AI_COMPLEX average cost drops vs today's blanket fan-out.*

### Phase 3 — Actions that act (3–4 days)
Wire `notifier.py` into `send_payment_reminders` (real email/WhatsApp where contacts exist) with **idempotency keys**; add `draft_reorder_po`, `mark_invoice_paid`, `escalate_overdue` to the registry; per-action daily caps in `RateLimitConfig`; execute → `invalidate_user_cache`.
*DoD: "who owes me?" → confirm → reminders actually delivered, audited, double-click-safe.*

### Phase 4 — Proactive agent (3 days)
Morning **digest agent** per business ("3 things that need you today", each a one-tap action chip) via the existing alerts channel; `detect_anomalies` output becomes actionable suggestions; weekly **memory distillation** job (stable business facts → small `business_facts` collection injected into the snapshot).
*DoD: a user who never types still gets daily agent value.*

### Phase 5 — Production hardening (ongoing)
Single-worker guard now (R3-minimum) → Redis/DB-backed shared state when scaling; Postgres via the Alembic chain already in place; `Depends(get_db)` sweep (R6/H6); `chat_sessions` table (H7); auth upgrade (refresh tokens / httpOnly); drop `"null"` origin (**today**); background upload indexing (M5); CI running the 182 tests + the routing eval per push; request-ID middleware on top of the new logging.

### Do-not-do list (unchanged, still correct)
No per-message LLM classification, no microservices/Celery, no rewriting the registries/envelope, and don't start Phase 2 before the cutover deletes the redundant classifiers — a smarter agent routed by three disagreeing brains is still a confused agent.

---

## Scorecard

| Dimension | v1 | v2 now | After Phase 1–4 |
|---|---|---|---|
| Correctness/concurrency | C | **A−** (R1 pending) | A |
| Efficiency (token economics) | C+ | **B+** | A |
| Robustness (errors, data, tests) | C+ | **A−** | A |
| Routing intelligence | D | **B−** (shadow built, not live) | A− |
| Agentic capability | D+ | **D+** (unchanged) | B+ |
| Production readiness | D | **C** | B+ |

**Bottom line:** the foundation work was executed well and verified clean. Next single most valuable step: **Phase 1, item 1 (streaming `include_usage`)**, then the router cutover — after that, all roads point to the agent loop.
