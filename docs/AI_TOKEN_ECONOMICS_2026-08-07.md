# AI token economics & deferred work — 2026-08-07

Written after a session that repaired the AI chat pipeline. It records what was
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

`INTENT_ROUTER=shadow` costs **zero Groq tokens** (local MiniLM) and, since
2026-08-07, runs off the request path in a daemon thread. Leave it on: it is the
free instrument that would tell us whether the semantic router could ever replace
the paid one. Current evidence says not yet — it went DISAGREE/DISAGREE/AGREE on
three production queries and was ambiguous on two the paid router got right.

To size `SNAPSHOT_CONTEXT`, log `len(snap)` at
`services/ai_router_execution.py` where `get_business_snapshot` is called, and
compare AI_SIMPLE `input_tokens` in `token_usage` with it on and off.

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

**Sync inbox, 9 B2B rows held on the local device.** Their stored payloads predate
the BizID fix and the pull cursor has advanced past them, so retrying replays the
old payload and fails identically. They need the cursor rewound to before
`2026-08-03T14:50` now that the cloud sends BizIDs; `core/sync/inbox.py` refreshes
a held row's payload when the cloud re-offers it.

**Verification debts from that session** — neither rendered in a browser, because
the tooling blocked localhost:

- the universal search palette (`Ctrl+K`, and the `?field=` settings deep link,
  which is timing-based — it defers 120 ms for the tab to mount)
- the collapsed-sidebar fix for the minimized-invoice card
