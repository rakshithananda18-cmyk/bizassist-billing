# AI token economics & deferred work — 2026-08-07

Written after the session that repaired the AI chat pipeline; **extended 2026-08-08**
with the AI_COMPLEX model measurement (§3b), AI in the search palette (§6), and a
correction to §5 where the advice recorded here turned out not to work. It records what was
measured, one proposal that the measurements **refuted**, and the levers left
untried — so the next person picks up evidence rather than re-deriving it.

Everything here is reproducible: the commands are included.

---

## 1. The headline: routing is not overhead

An early reading of `token_usage` said *"94% of tokens go to the LLM router, not
to answering"* — 9,261 tokens across 11 routing calls versus 497 for the one
answer in the sample. That figure is real and it is **misleading**, because it
measures what routing costs without measuring what routing *avoids*.

Measured across all retained logs:

```
legacy=AI_SIMPLE    invoked=12   agreed=0    CHANGED=12   (100% changed)
legacy=DIRECT       invoked=13   agreed=1    CHANGED=12   ( 92% changed)
TOTAL               invoked=25   agreed=1    changed=24
```

**The router changes the outcome 96% of the time it runs.** It is not a tax on
answers; it is choosing a different, usually cheaper or better, answer.

A worked example from production (Space, 2026-08-07 20:52):

```
query:   "Draft a polite, professional follow-up to Salma about their outstanding invoices."
legacy:  AI_SIMPLE (writing task)   → would have GENERATED an email (~800–1500 tokens)
llm:     ACTION / email_reminder_digest, customer=Salma, conf 0.80
result:  [DONE] source=action tier=ACTION tokens=0
```

The router spent ~841 tokens and returned a **0-token** gated action preview
instead of a hallucinated draft. It paid for itself on that single query.

### Reproduce

```bash
# what the router did whenever it was invoked
python - <<'PY'
import re, glob, collections
pat = re.compile(r"\[ROUTER\] llm → (\S+?)/(\S+?) \(legacy was (\S+?)/(\S+?)\)")
tot = collections.Counter()
for f in glob.glob('backend/logs/bizassist.log*'):
    for m in pat.finditer(open(f, encoding='utf-8', errors='replace').read()):
        n_t, n_h, o_t, o_h = m.groups()
        tot[(o_t, (n_t, n_h) != (o_t, o_h))] += 1
for legacy in sorted({k[0] for k in tot}):
    same, diff = tot[(legacy, False)], tot[(legacy, True)]
    print(f"legacy={legacy:<10} invoked={same+diff:4} agreed={same:4} CHANGED={diff:4}")
PY
```

```sql
-- cost side, from the app's own accounting
SELECT model_tier, COUNT(*), SUM(total_tokens) FROM token_usage GROUP BY model_tier;
```

---

## 2. REFUTED: "skip the LLM router when legacy already resolved a handler"

**Do not implement this.** It was proposed in this session and the data killed it.

The idea: `_LLM_FASTPATH_HANDLERS` (`services/ai_router_decision.py`) skips the
router for only two handlers — `overdue_range_detail`, `revenue_month_detail`.
Everything else pays ~841 tokens even when legacy matched a deterministic
template. Inverting the rule — invoke only when legacy is *uncertain* — looked
like a free saving, and one production sample supported it:

```
20:55:22  legacy: DIRECT (business_summary)
20:55:25  llm → DIRECT/business_summary (legacy was DIRECT/business_summary)   ← agreed, 841 wasted
```

That sample was the **1 case in 13** where the router agreed. The other twelve:

```
10x  DIRECT/top_customers      →  AI_ADVISE/top_customers
 2x  DIRECT/customer_invoices  →  DIRECT/invoice_detail
```

Neither is noise. `AI_ADVISE` returns data *plus grounded advice* instead of a
bare table — a better answer to "who are my top customers". The second is the
router noticing the query named one specific invoice rather than a customer's
list. The proposed rule would have suppressed all twelve: trading ~841 tokens
per query for systematically worse answers.

**The narrow two-handler allowlist is the correct shape.** Its comment claims
the router "only agrees with these", and the data confirms that is true of those
handlers and false in general.

### If someone wants to revisit it

Widen `_LLM_FASTPATH_HANDLERS` only for handler pairs the logs prove the router
*always* agrees with, over a meaningful sample — not by category, and not from a
single observation. The reproduce script above gives the per-handler evidence.

---

## 3. Levers not yet measured

| Lever | Est. saving | Cost | Status |
|---|---|---|---|
| `SNAPSHOT_CONTEXT=false` | unknown — **never measured** | AI_SIMPLE loses the deterministic business snapshot | The honest next thing to size |
| `CHAT_MEMORY_ENABLED=0` | ~600 tokens / AI_SIMPLE call | loses semantic recall of past chats | Already capped; see §4 |
| `LLM_ROUTER=off` | ~841 / query | **refuted above** — do not | Closed |
| `GROQ_MODEL_COMPLEX` | **8,453 tokens / AI_COMPLEX** | a shorter, shallower answer | **Measured 2026-08-08 — taken; see §3b** |

`INTENT_ROUTER=shadow` costs **zero Groq tokens** (local MiniLM) and, since
2026-08-07, runs off the request path in a daemon thread. Leave it on: it is the
free instrument that would tell us whether the semantic router could ever replace
the paid one. Current evidence says not yet — it went DISAGREE/DISAGREE/AGREE on
three production queries and was ambiguous on two the paid router got right.

To size `SNAPSHOT_CONTEXT`, log `len(snap)` at
`services/ai_router_execution.py` where `get_business_snapshot` is called, and
compare AI_SIMPLE `input_tokens` in `token_usage` with it on and off.

---

## 3b. The AI_COMPLEX model — measured 2026-08-08

The default was not merely expensive. **It could not complete a single question
inside the account's rate limit.**

Same question (`why are my sales down this month`), same business, same tools:

| | `openai/gpt-oss-120b` (was) | `llama-3.3-70b-versatile` (now) |
|---|---|---|
| Wall time | 80.6 s | **1.6 s** (8 s end-to-end in the app, incl. the router) |
| Tokens in + out | 12,617 + 1,220 = **13,837** | 5,204 + 180 = **5,384** |
| Tool rounds | 5, serialised | 3, **all in `round=1`** (parallel) |
| Answer | 3,308 chars, month-by-month table | 635 chars, summary |

The Groq tier is `on_demand` with a **TPM ceiling of 8,000**. gpt-oss needs 13,837
for one question, so it cannot fit — observed as
`429 … Limit 8000, Used 5561, Requested 2514`. The 80.6 s run only completed
because the spend straddled two minute-windows. That is luck, not health.

`GROQ_MODEL_COMPLEX=llama-3.3-70b-versatile` is set in `backend/.env`.

**What was given up, honestly.** gpt-oss ran two more tools
(`list_invoices`, `dormant_customers`) and returned a far richer answer. Cost and
latency were measured; **answer quality was not** — depth is inferred from length
and tool coverage on one question, which is weak evidence. If the shallower
answers prove inadequate on real questions, the fix is the **Groq tier**, not
restoring a default that does not complete. Flipping the variable back is then
the whole change.

⚠ `.env` is gitignored, so this **does not travel to the Space**. Set
`GROQ_MODEL_COMPLEX` there separately (a Variable, not a Secret) or the Space
stays on gpt-oss and rate-limits.

Reproduce: `scripts/`-free, out of process (MODEL is read at import) —
set `GROQ_MODEL_COMPLEX`, then call
`agent_loop.run_agent_loop_stream(q, business_id, [])` and read the `ag_done`
event's `tokens`.

---

## 4. Chat memory — the standing constraint

`CHAT_MEMORY_ENABLED` defaults **off** in code and is **on** in the Space
(Settings → Variables → `CHAT_MEMORY_ENABLED=1`, a variable, not a secret).

The asymmetry is not preference, it is process count. Chroma's persisted HNSW
index blocks in **native code while holding the GIL** when two processes share
it. That freezes the entire interpreter — the port stays open, requests are
accepted, nothing is ever answered, and nothing is logged. It is invisible.
`faulthandler.dump_traceback_later(..., exit=True)` armed on another thread never
fired, which is the proof: no Python bytecode runs anywhere until the native call
returns, so **no timeout, thread or `except` can rescue it.**

- **Dev** runs `uvicorn --reload` → reloader + worker, both importing the app → **off**.
- **The Space** runs one process (`CMD` has no `--reload`, no `--workers`), and
  `_LockedCollection` serialises the threads inside it → **on**.

**If `--workers` is ever added to that CMD, clear the Space variable in the same
change.** The Space becomes multi-process at that moment and inherits the dev
failure mode.

Symptom to watch: the log going *completely* silent — no sync worker, no
scheduler — while `/health` still returns 200. Clearing the variable recovers it.

The injected memories are capped (600 chars per answer, 200 per question). Before
that cap this was the only uncapped context path in the pipeline: three stored
AI_COMPLEX answers at up to 1,800 tokens each, prepended to every AI_SIMPLE
prompt, and a plausible source of the `413 / request too large` branch in
`ai_router.handle_stream`.

---

## 5. Open, not started

**Bill scanning has no vision model.** The key authenticates but is not entitled
to `meta-llama/llama-4-scout-17b-16e-instruct` (404 *"does not exist or you do
not have access to it"*). Since 2026-08-07 vision self-disables after one such
refusal and falls through to Tesseract, so scanning works — just without the
better path on photos. Resolution is an account/entitlement question, or set
`GROQ_VISION_MODEL` to a vision model the key does hold.

**Data repairs, all requiring the machine that holds the real books:**

- `repair_line_items_by_invariant.py --apply` — 31 invoices + 2 b2b_orders overfilled
- `clear_staff_bizids.py --apply` — 32 staff sub-accounts holding their own BizID
- `OW-0003` (biz 7) — payments 311.0 against a 124.0 invoice; a receipt is on the
  wrong invoice. Not scriptable: it needs the actual receipts
- 5 open shifts on biz 42 — a closing cash figure is a **count**, not a calculation

**Sync inbox, B2B rows held on the local device.**
⚠ **CORRECTED 2026-08-08 — the advice previously written here was wrong twice.**
It said: rewind the cursor to before `2026-08-03T14:50` and the rows will drain.
They will not.

1. **The attempts ceiling blocks retry regardless of the cursor.**
   `due_rows` filters `attempts < MAX_AUTO_ATTEMPTS` and that constant is **7**;
   every held row sat at exactly 7. No drain would ever pick them up again, and
   `core/sync/inbox.py` *deliberately preserves* `attempts` on a re-offer so an
   unrelated pull cannot reset backoff. `scripts/rewind_pull_cursor.py` now
   resets both — a rewind alone is a no-op for the rows that most need it.
2. **The cloud does not re-offer them.** Both halves were applied (biz 126 and
   10001) and the cursor then advanced across the rewound window for ~19 minutes
   of pull cycles. The stored `b2b_orders` payload was **unchanged** — still
   `seller_business_id=7, buyer_business_id=114` with no `_bizid` keys. Since
   `_serialize_orm_obj` demonstrably emits `seller_business_id_bizid` for a local
   row, a re-offer would have refreshed it. It never came.

So the payload refresh mechanism is real but unreachable here, and the rows will
re-stick at 7 attempts. **The recoverable path was local, not sync**: the order's
six lines were sitting in the inbox payloads all along and summed to exactly the
invoice's stored subtotal, which is what made
`scripts/repair_b2b_invoice_lines.py` safe rather than a guess.

Root cause of the whole cascade, and it is fixed:
`b2b_orders.seller_invoice_id` was declared `Column(Integer)` with **no
ForeignKey**, and BOTH halves of the spine machinery iterate
`__table__.foreign_keys`. With nothing to walk, the sender emitted no uid and the
receiver never inspected the column, so the cloud's `841` — its own invoice id —
was written through verbatim. Locally 841 belongs to business 9999. `740b11e`
fixed the two party columns; this one was missed because it had no FK to walk.

**Verification debts from that session** — neither rendered in a browser, because
the tooling blocked localhost:

- the universal search palette (`Ctrl+K`, and the `?field=` settings deep link,
  which is timing-based — it defers 120 ms for the tab to mount)
- the collapsed-sidebar fix for the minimized-invoice card

---

## 6. AI in the search palette — 2026-08-08

### The rule the design turns on

**The AI is never invoked while typing.** `/search` is debounced at 250 ms and
cheap; the router costs ~841 tokens per invocation *before* the model answers
(§1). Per-keystroke would be ruinous. An "Ask AI" row appears **last** in the
palette and only runs when explicitly chosen. There is a test asserting that a
fully typed question produces `/search` calls and **zero** `/ask` calls; it is
the most load-bearing assertion in the feature.

Confirmed live: one router invocation for a whole typed question, `8 s`
end-to-end, `tokens=5377`.

### What ships (Phase 1 — read-only Q&A)

| | |
|---|---|
| Endpoint | `/ask/stream` — the SAME one `frontend-ai` uses |
| Gate | Pro **and** not a cashier, mirrored client-side so a free plan is never shown a control that would 402 |
| Trigger | ≥ 2 words **and** ≥ 6 chars (see below) |
| Placement | last group, so it never displaces a record |
| Off switch | Settings → General → **Ask AI from Search** (`general.ai_search_enabled`, default on) |

Reusing the endpoint rather than adding a second AI route keeps one router, one
cache and one set of failure rules. A parallel path would drift the way two
hosting-mode implementations already had to be merged this session.

Three failure shapes are handled, not rediscovered: **503** (no `GROQ_API_KEY`)
latches the row off for the session; a stream that **ends with no terminal
event** says so instead of spinning forever; a mid-stream **`error`** renders as
an error rather than an empty answer.

### The Pro gate had to be made real first

`/ask` and `/ask/stream` carried `require_plan("pro")` that **enforced nothing** —
it is a no-op unless `SUBSCRIPTION_ENFORCED=1`, which is unset in production. The
AI had been free to every plan. `force_enforcement=True` makes the existing
declaration true without flipping the site-wide paywall (which would also gate
`/api/sync/push` and the data-transfer import — a separate, deliberate decision).

Enabling it **broke 51 tests across 9 files**, all of which signed up a fresh
free account and called `/ask`. That is the proof the gate had never bitten. They
now provision a plan via `tests/planhelpers.py::grant_pro`. One test —
`test_subscription_dormant_by_default` — was **repointed, not patched**: its
intent (the site-wide paywall blocks nothing) is still valid, but `/ask` stopped
being a valid probe for it, so it now probes `/api/sync/push`.

⚠ Live behaviour change: a free-plan business using the AI chat now gets 402 with
no grace period. Every business with chat history on the dev machine resolves to
Pro, so measured impact is nobody — **but that machine is not production, and the
production check has not been run.**

### Phase 2 was deliberately NOT built

The plan called for actions behind a confirm step. On reading the machinery, that
was the wrong build:

- The server **already refuses to auto-execute**. `ai_router.py` returns a
  confirm chip and *"Nothing is sent or changed until you confirm"*, and
  `/action/execute` has two write rails — it **recomputes the preview and
  compares fingerprints**, refusing with 428 if the data drifted since the user
  confirmed, plus a replay wall.
- Of the five actions, `send_payment_reminders` and `email_reminder_digest`
  **email customers** and `mark_invoice_paid` **mutates money**.
- A money-and-email confirmation implemented in two surfaces is two places to
  drift — the exact defect fixed twice this session (POSLiveCounter re-deriving
  hosting mode; `create_sale_invoice`'s idempotency wall).
- `Ctrl+Space → type → Enter` is the wrong ceremony for "email 20 customers".

Instead, `source: 'action'` **hands off** to the AI Advisor, which owns
confirmation. A test asserts the palette's only controls are *Dismiss answer* and
*Open AI Advisor*, and that nothing reaches `/action`.

### Open

**The local matchers only handle prefix-style typing.** `matchPages` substring-
matches the *whole* query against a label, so:

```
"setting"              → pages: ["Settings"]
"where are my setting" → pages: [],  settings: []      ← nothing
```

A natural-language question therefore finds nothing locally and falls through to
the assistant — which has database tools and no knowledge of the app's UI, so it
invents an answer. Observed: `setting` (7 chars, one word) cleared the original
length-only bar and produced a reply about invoice totals citing a "Send
Reminder" button that does not exist.

The word-count rule fixes the one-word case and **not** the phrase case. The real
fix is token matching in `config/searchIndex.js`: split the query, drop stopwords
and very short words, match if any remaining token hits the label or keywords.
The trade is more local noise (`sales down` starts matching anything containing
"sales"), bounded by `MAX_STATIC = 4` and by pages ranking below records.

Deliberately **not** a question-word whitelist: *"sales down vs last month"* is a
fair question with no question word in it, and a whitelist trains owners to
phrase things for the parser.

**Phase 3 (memory in the palette) is not started** and should not be until Phase 1
has answered real questions. §4's constraint applies: chat memory is Chroma-backed
and carries the single-process freeze hazard.
