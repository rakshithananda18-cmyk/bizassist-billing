# BizAssist — Agentic Architecture Blueprint

Turning BizAssist from a chat assistant into an **efficient, interactive, agentic** business
system using a **4-tier response model**: deterministic first, AI on-demand, actions when needed.

Guiding principles:
- **Never spend an AI token on a known question.** Facts/numbers come from the DB; AI only reasons.
- **One response contract, rendered everywhere** (max reusability).
- **Config-driven** chips/alerts/actions — add a feature by adding a registry entry, not new components.
- **Every action is previewed, confirmed, scoped, and logged.**

---

## 0. The Foundation — Unified Response Envelope

Every endpoint that powers a chip / alert / action returns the SAME shape. Frontend has ONE
renderer for it.

```jsonc
{
  "answer": {
    "type": "text | table | metric | list",
    "title": "Overdue Invoices",
    "markdown": "There are 6 overdue invoices totalling ₹66,251 …",
    "data": { /* optional structured payload for rich rendering */ }
  },
  "source": "db | cache | ai",
  "suggestions": [
    { "id": "top_debtors",   "label": "Rank top debtors", "type": "deterministic", "intent": "top_debtors", "icon": "trophy" },
    { "id": "send_reminders","label": "Send reminders",   "type": "action", "action": "send_payment_reminders", "confirm": true, "icon": "bell" },
    { "id": "recovery_plan", "label": "Analyze with AI",  "type": "ai", "prompt": "Draft a recovery plan for my overdue invoices", "icon": "chat" }
  ],
  "meta": { "tokens": 0, "latency_ms": 5 }
}
```

`suggestion.type`: `deterministic` (calls an intent, 0 tokens) · `ai` (sends a prompt) · `action` (runs a gated action).

---

## PHASE 1 — Tier 0: Deterministic Intent Engine (cost + speed win)

**Goal:** every chip, alert card, and dashboard button is answered from the DB with 0 AI tokens.

### Backend
- `services/intents.py` — an **intent registry**: `INTENTS = { "total_revenue": fn, "top_debtors": fn, ... }`, each `fn(user_id, params) -> answer dict`. Reuse the existing functions in `direct_query_handler.py` / `tools.py` (wrap, don't rewrite).
- `routes/intents.py` — `POST /intent` `{ intent, params }` → returns the envelope. Unknown intent → 404 (frontend falls back to AI).
- Intent keys to cover (from current UI): `total_revenue, revenue_summary, overdue_list, overdue_amount, pending_list, top_customers, top_debtors, expiring_soon, low_stock, inventory_count, business_summary`.

### Frontend
- `hooks/useIntent.js` — `runIntent(intent, params)` → posts to `/intent`, returns the envelope.
- One **AnswerRenderer** (reuse markdown renderer + Table/metric) for `answer`.
- **Config-drive the chips**: `config/intents.js` maps each chip/alert/dashboard button → `{ intent, label, icon }`. The chip bar + alert cards read this config instead of hardcoding.

**Outcome:** ~80% of interactions become instant + free + hallucination-proof.

---

## PHASE 2 — Tier 1: Recommendation Engine (agentic feel, still 0 tokens)

**Goal:** every answer comes back with 2–4 smart "next step" chips, rule-based.

### Backend
- `services/recommendations.py` — `recommend(intent, data, context) -> [suggestion]`. Pure rules over data:
  - overdue > 0 → `top_debtors` + `send_payment_reminders` (action) + `recovery_plan` (ai)
  - low_stock items → `reorder_list` + `reorder_qty_suggestion` (ai)
  - after upload → `summarize` (ai) + `anomaly_check`
  - revenue query → `revenue_trend` + `compare_last_month`
- Attach `suggestions` to every envelope (intent + AI + upload responses).
- A `context` helper computes business signals once (overdue count, low-stock count, etc.) and caches them.

### Frontend
- The **chip bar becomes data-driven**: render `response.suggestions`. Click handling by `type`:
  deterministic → `runIntent`; ai → send prompt to chat; action → open ActionConfirm (Phase 3).
- Reuse the existing chips-bar component; it now takes a `suggestions` prop.

**Outcome:** feels proactive and guided, with near-zero token cost.

---

## PHASE 3 — Tier 3: Agentic Actions (the real "agent" — gated)

**Goal:** the assistant *does* things (send reminders, draft reorders), with preview + confirm + audit.

### Backend
- `services/actions.py` — **action registry**: `ACTIONS = { "send_payment_reminders": { preview, execute, requires_confirm: true } }`.
  - `preview(user_id, params)` → returns what WILL happen (recipients, amounts, draft message) — no side effects.
  - `execute(user_id, params)` → performs it (reuse `notifier.py` for email/WhatsApp), returns result.
- `routes/actions.py` — `POST /action/preview`, `POST /action/execute`.
- New table **`action_log`** (id, business_id, action, params, status, result, created_at) for audit.
- Guardrails: business-scoped, rate-limited, confirm-required, dry-run preview always first.
- First action to ship: **`send_payment_reminders`** (highest ROI — recovers cash).

### Frontend
- Reusable **`ActionConfirm`** (uses generic `Modal`): shows the preview (who/amount/message), Confirm/Cancel → execute → result chip ("✓ 6 reminders sent").
- Action suggestions route here automatically (from Phase 2 `type: action`).

**Outcome:** BizAssist takes real, safe, auditable actions — the agent leap.

---

## PHASE 4 — Tier 2 Economics: AI Budget + Product Tiers (profit)

**Goal:** control AI cost and enable monetization.

### Backend
- Extend `rate_limiter.py`: per-plan daily **token budgets** (Free vs Pro). Tag every AI call with tokens used.
- `User.plan` field (`free | pro`). Gate `ai` and `action` suggestions by plan.
- Usage logging surfaced in the existing admin usage page.

### Frontend
- Show remaining AI usage; graceful "Upgrade to Pro" prompt when an AI/action suggestion is gated.

**Outcome:** deterministic tier is cheap-for-everyone; AI + actions are the paid tier — tiering = pricing.

---

## Cross-cutting (smart / reusable / interactive)

- **Single envelope → one renderer** everywhere (chips, alerts, AI, actions).
- **Registries over hardcoding**: intents, recommendations, actions are all maps — adding a capability = one entry.
- **Reuse existing infra**: `direct_query_handler`, `tools`, `context_cache`, `rate_limiter`, `notifier`, `agent_graph`, the UI toolkit (`Section/Table/Modal/Spinner/Icon`).
- **Interactivity**: streaming AI (keep typing effect), optimistic UI, skeletons (`Spinner`), result toasts.
- **Telemetry**: log intent + suggestion usage → learn which to optimize / which AI calls to cache.

---

## Sequencing & Definition of Done

| Phase | Ships | Token cost | DoD |
|------|-------|-----------|-----|
| 1 | Intent registry + `/intent` + AnswerRenderer + config-driven chips | 0 | All chips/alerts/dashboard buttons answered from DB; AI only on explicit ask |
| 2 | Recommendation engine + dynamic chip bar | 0 | Every answer returns relevant next-step chips |
| 3 | Action registry + preview/execute + audit + ActionConfirm | 0 (action) | `send_payment_reminders` works end-to-end with confirm + log |
| 4 | Token budgets + plans + upsell | metered | AI gated by plan; usage visible |

**Workflow per phase:** backend → frontend → verify in dev → **commit** → next phase.

Recommended start: **Phase 1 + 2 together** (cheap, fast, makes it feel smart), then **3**, then **4**.
