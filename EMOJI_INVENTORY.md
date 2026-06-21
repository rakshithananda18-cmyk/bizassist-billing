# BizAssist — Emoji / Glyph Inventory

_Generated 2026-06-22. Scope: all `.jsx/.js/.py` source (excludes `node_modules`, `venv`,
`dist`, `build`, lockfiles). Box-drawing (`─ ═ │ ├ └`), arrows (`→ ← ↓ ↔`) and math
operators (`≤ ≥ ≠ ⇒ ⊕`) are intentionally excluded — those are doc/ASCII-art in the
master plan, not UI emoji._

## Icon convention (keep consistent everywhere)

- **Expand / collapse caret:** `▾` when collapsed, `▲` when open. Used by the old
  "Collapse ▲ / All ▾" toggle and now by the Reports group buttons (replaced the ▶
  play-triangle 2026-06-22). Do NOT use `▶`/rotating triangles for expand state.

## Emoji used in CODE (count = occurrences)

### Status / feedback
`✅` (18) · `❌` (21) · `⚠` (13) · `✓` (28) · `✕` (44) · `✗` (2) · `🔴` (2) · `🟡` · `🟠` ·
`🔄` (11) · `⏳` · `⏰` · `⏭` (3) · `⏪` · `⏩`

### Section / action icons
`🔍` (5) · `⚙` (4) · `⌨` (2) · `📊` (2) · `📄` (7) · `📋` (2) · `📝` (2) · `🗑` · `🔔` ·
`📁` · `👁` · `🖨` (2) · `🗓` (2) · `➔` · `⬆` · `✦` (7) · `✏` (2) · `🔸`

### Commerce / domain
`💳` (5) · `💵` (2) · `💸` (2) · `💎` (2) · `🏦` (2) · `🏢` (2) · `🏭` · `🏛` · `🛒` (2) ·
`📦` (8) · `📥` (6) · `📤` (3) · `🚚` (3) · `📞` · `📧` (3) · `📱` (2) · `🔌` (2) · `💬` (3) ·
`👤` (3) · `🤝` · `🛡` · `🔒` (2) · `⚡` (2) · `☀` · `🎯` (2) · `🚀` · `🤖` · `🧠` (3) · `💡` ·
`🔊` · `👍` / `👎` (AI app feedback)

_(Lone `️` U+FE0F entries are emoji-presentation variation selectors attached to the
glyphs above — not separate icons.)_

## Emoji used in DOCS (master plan etc.)
Status markers only: `✅` `🟡` `🟢` `🔴` `⬜` `⚠` `❌`

## Where they live
- **`frontend-ai/`** (heaviest): Chat, Dashboard, Alerts, Payments, Database, Upload,
  admin pages, chat components, DialogContext.
- **`frontend-billing/`**: Sales/CheckoutModal/TotalBreakupModal, Settings, Orders,
  Connections, Parties, Stock, Payments, Register, AppLayout, `utils/logger.js`, and the
  new report views — `🔒` Audit Journal, `📥` stock-received (Orders), `⚙️` Settings,
  `⌨️` Hotkeys (PosSettingsModals), `✓`/`✕` balanced/close, `▲▾` Reports group buttons.
- **`backend/`**: ONLY AI/service layers — `agent_graph.py`, `ai_router.py`, `actions.py`,
  `recommendations.py`, `embeddings.py`, `alert_jobs.py`, `handlers/{invoices,inventory}.py`.
  **None in the core billing/accounting/compliance paths** (clean).

## Consistency flags (to standardize if desired)
1. **Check marks mixed for the same meaning:** `✓` (28), `✅` (18). Suggested rule:
   inline glyphs use `✓`; toast/status banners use `✅`.
2. **Close / fail mixed:** `✕` (44, dominant — good default), but `✗` (2) and `❌` (21)
   also appear. Suggested rule: button/close = `✕`; error toast/status = `❌`; avoid `✗`.
3. **Expand caret:** standardized to `▾`/`▲` (see convention above) — no stray `▶`.

_Action pending (optional): sweep the UI to enforce rules 1–2._
