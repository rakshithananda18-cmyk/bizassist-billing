# REVIEW_1 Implementation Notes — 2026-07-10

Everything code-level from REVIEW_1 is implemented. Verified: backend app boots with migrations, 12 new tests pass, 165 existing auth/roles/settings/SSO/plan-gating/staff/SSE tests pass, all new/edited frontend files parse.

---

## BATCH 2 — same day: Section-B recommendations + UX fixes (all verified)

Verification: 25 new tests pass (`test_review1_hardening.py` + `test_totp_and_metrics.py` + updated `test_rls_policies.py`), 157 regression tests pass (admin/SSO, roles, settings, auth-logging, staff, print-payload, billing, sales API, plan gating, signup, SSE, user policy), all touched frontend files parse.

### Test-suite fixes (your 2 failures)
- `test_rls_policies.py` updated to assert the NEW intended behavior: parameterized `set_config()` RLS call, and `?token=` auth off-by-default (with an opt-in-flag case). Both will pass on your next run.

### UX / correctness fixes you asked for
- **POS live clock**: real-time ticking date+time (IST, seconds included) in the POS top bar — always Asia/Kolkata so the counter clock matches invoices even on a misconfigured machine (`PosTopBar.jsx`).
- **Invoice time wrong (UTC)**: `print_payload.py` now converts stored UTC to business-local time (`BIZ_TIMEZONE` env, default Asia/Kolkata) rendered as `h:mm AM/PM` — fixes Classic, Modern AND Thermal templates in one place. Thermal POS receipt pinned to IST too.
- **POS settings "not editable"**: root cause found — the settings modal's focus trap yanked focus away from `CustomSelect`'s portaled dropdown the instant it opened, killing every picker. Trap is now portal-aware. Bonus: the GST state picker had only 7 states; now the full CBIC list (all 36 codes).
- **Classic invoice look**: restyled — one strong outer frame, light inner rules, muted secondary ink, uppercase column headers, proper totals ladder with an emphasized GRAND TOTAL rule. Same layout, columns, data and test hooks; template tests still pass.
- **B2B Network confusion**: added a 3-step "How it works" strip (BizID = phone number analogy), renamed the baffling "As Buyer/As Seller" to **"They're my Supplier" / "They're my Customer"**, and a live plain-language preview of exactly what the connection will do before you hit connect.

### Section B recommendations
- **B6 (LLM stalls)**: honest finding — sync routes/generators already run in Starlette's threadpool, so the event loop was never blocked; the real risks were unbounded upstream calls pinning threads forever and the 40-thread default cap. Fixed: shared `services/groq_client.py` factory (timeout `GROQ_TIMEOUT_SECS`=60, bounded retries) now used by ALL 8 Groq call sites, + `THREADPOOL_LIMIT` env (default 80) applied at startup.
- **B7 (Backup)**: "Backup to file / Restore from file" card in Settings (`FileBackupCard.jsx`) — full JSON export via the existing battle-tested `/api/data-transfer/export`, restore replays through `import?merge=true` (LWW, non-destructive). Works in every hosting mode; local-only merchants finally have disaster recovery.
- **B8 (Admin 2FA)**: RFC-6238 TOTP implemented with stdlib only (`services/totp.py` — no new dependency). Enroll/confirm/disable endpoints under `/admin/2fa/*`, secret stored server-side in the reserved settings key (stripped from every client response — including a leak I caught in PUT /settings echo), login demands the code only for admins with 2FA confirmed, disabling requires a live code. UI: security card on Health & Audits + OTP step on the admin login.
- **B9 (Metrics)**: `GET /admin/metrics` + **Metrics** page — plan mix, Pro-expiring-≤14d, activation funnel (registered → first invoice → 10 invoices → sync → AI), 7/30-day activity, churn-risk table (5+ invoices then 14+ days silent) with one-click paths to the business drill-down and a win-back campaign.

### Still ops-only (unchanged)
Signing cert (GAP-7), uptime monitor + SENTRY_DSN activation (GAP-5), infra move (GAP-2, deferred by you), key rotation (GAP-8), WhatsApp + payments accounts (GAP-9/10).

---

## BATCH 3 — owner-requested staff & operations features (all verified)

Verification: 85 backend tests pass across shifts/import/staff/roles + 2 new tests
(import preview writes nothing → commit writes → duplicates flagged; shift-invoices
endpoint shape & visibility). All new/edited frontend files parse; the Code 128
table was validated programmatically (106 symbols, each exactly 11 modules).

### Two staff sectors under one umbrella
**Honest finding first:** the backend already had both roles (`cashier`, `supply adder`)
with correct permission guards, and Settings → Staff already had the role picker —
what was missing was the EXPERIENCE around the stock role. Shipped:
- **Role-aware navigation**: Supply Adders now land on Inventory and see only their
  sector (Home, Inventory, Purchases, Profile, Support, Settings); Cashiers keep the
  sales sector. Off-role URLs redirect. Backend guards remain the real authority.
- **Barcode label printing (new feature)**: Inventory → *Print Labels* — pick products
  and quantities, choose 38×25 / 50×25 / 65×35 mm, print. Labels carry business name,
  price and a scannable Code 128 barcode, rendered by a dependency-free encoder
  (`utils/code128.js`) — works fully offline in the packaged app. Codes scan straight
  into the POS search.
- Product quick-add, stock adjust and godown transfer already lived on Inventory —
  the page is now the stock team's umbrella and its ⓘ help explains the whole flow.

### One stock, many selling points (B2B + retail)
**Honest finding:** this capability already existed end-to-end — products carry
Retail / Wholesale / Distributor prices, the POS has a per-line Price Option, and
each B2B connection pins a customer to a tier + discount. It was undiscoverable.
Documented properly in the Inventory and B2B Network ⓘ help. No schema was added
because none was needed.

### Shift operations
- **Cash In/Out simplified for staff**: one dropdown ("What is this?") instead of four
  radio cards, with a plain-language hint and a +into/−out-of-drawer badge per choice.
- **Printable shift summary**: after closing, *View & Print Summary* shows the full
  reconciliation (expected vs counted with OVER/SHORT verdicts), all cash movements,
  and **every invoice that took a payment during the shift** — clickable on screen,
  listed on paper. New backend endpoint `GET /shifts/{id}/invoices` (per-shift
  collected amounts, cashier sees only their own shift).
- **Shift-wise data**: already captured — every shift lands in Reports → Operations →
  Shift Reconciliations (owner-only history with discrepancies per operator).

### Import & purchase approval gates ("nothing lands without approval")
- **Products import (Data Migration)**: files are now parsed with `?preview=1`
  (zero writes) → an editable review table pops up (fix any cell, untick any row;
  duplicate names/SKUs pre-flagged and unticked) → *Approve & Import N* commits
  only the ticked rows. Cancel imports nothing.
- **Purchase bills**: the editable review table already existed (upload → review →
  commit); added the missing piece — a per-row **remove** button so a wrongly
  extracted line can be dropped before it touches the books.

### Answered
- **Local admin metrics "disabled"**: not a bug — `/admin/*` is fail-closed. Set
  `ADMIN_API_ENABLED=1` in `backend/.env` for local development.

### Recommendations after batch 3 (honest, in order)
1. **Label printing hardware pass**: test the three label sizes against the owner's
   actual label printer/stock (thermal label printers vary); add a size preset if
   their stock differs. 30 minutes with the physical printer beats any code review.
2. **Supply-adder shift question**: stock staff currently can open shifts (backend
   allows it). Decide whether stock staff should be exempt from the shift gate —
   today they'd only need it if they ring sales, which their nav no longer offers.
3. **Customer/vendor import approval**: products got the approval table; customers
   and vendors still import directly. Same preview pattern applies — ~1h each when
   wanted.
4. **Shift summary auto-print setting**: if owners want the summary to print
   automatically at close (no extra tap), it's a one-line setting away.
5. The bigger arc is unchanged: WhatsApp + payment links remain the gate to the
   collections agent (REVIEW_2), and the ops list (cert, Sentry DSN, uptime, key
   rotation) is still on your side.

---

## BATCH 4 — inventory revamp, activity feed, LAN sync fix (all verified)

Verification: 4 new tests pass (`test_activity_and_adjustments.py`) + 21
regression tests across sync/stock-ledger/barcodes; every new/edited file
compiles/parses.

### LAN / sync fixes (from your live logs)
- **"BizID mismatch for counter_1" refusal loop — FIXED.** Root cause: staff
  tokens carry the OWNER's BizID with the STAFF username; when the staff row
  isn't mirrored on the target DB (or another business grabbed the generic
  name 'counter_1' first), the pair-lookup missed and the guard refused
  forever, every 30s. The resolver now falls back to the OWNER row by BizID —
  the identity spine — before the refusal. Covered by a test.
- **Counter naming ("completely different through URL")**: counter codes
  (LCL-C1 vs C1) intentionally differ between local and cloud entry points
  (separate invoice series). The counter menu now shows the operator's
  friendly name next to the code ("LCL-C1 — counter_1") so it's recognisable
  everywhere.
- Noted from logs, no action needed: `pdf_failed: No module named 'weasyprint'`
  is the optional PDF export dep missing from your local venv
  (`pip install weasyprint` if you want invoice PDFs locally).

### Inventory revamp
- **Full product form (add + EDIT)**: honest finding — the backend accepted
  every field and had a PATCH endpoint, but the page exposed a handful of
  fields and had **no edit at all**. New `ProductFormModal`: Basics / Pricing
  (retail-wholesale-distributor-cost + MRP) / Tax (HSN, CGST/SGST) / Stock /
  Codes — used for both add and edit (Edit button on every row).
- **Multiple barcodes per product**: edit mode lists all barcodes and adds
  more (old pack / new pack / carton codes) via the existing barcode API.
- **Scan Stock-In**: scan → existing product found (via the same resolver the
  POS uses, so secondary barcodes work) → qty + mandatory reason → stock added.
  No duplicates ever; unknown codes offer "add as new product" with the code
  prefilled. Optimized for repeated scanning.
- **Richer table**: MRP + HSN·GST columns added alongside the 4 prices.
- **BUG FOUND & FIXED**: the old Adjust Stock modal posted to
  `/billing/stock/adjust` — an endpoint that **never existed**. Every
  adjustment silently 404'd. It now uses the real per-product adjustment API.
- **Labels — selectable fields**: choose what prints (business name, item
  name, item code, MRP, special price, barcode) — the choice is remembered
  per device.

### Anti-tamper ("inventory can't be scammed by staff")
- Stock adjustments now REQUIRE a reason (backend rejects blank notes — not
  just UI validation).
- Every adjustment is attributed (who, when, why, before/after) and surfaces
  in the owner's activity feed. The stock ledger itself is append-only.

### Business Activity feed (Dashboard)
- New `GET /activity` (owner-only) over the existing `table_alterations`
  audit: EVERY action — billing, stock, payments, purchases, settings, staff,
  shifts, B2B, books — as human summaries, categorized, with field-level
  what-changed diffs for updates.
- Dashboard now ends with the **Business Activity** panel: category chips,
  clickable rows → before/after detail modal, staff attribution on every row,
  load-more pagination. Settings changes read as "Settings updated"; stock
  movements as "Stock adjustment: −2 × Product"; cash movements with amounts.

### Honest limits of this batch
- The activity feed shows what the audit trail captures; a handful of system
  tables (sync queue, telemetry, chat) are deliberately excluded as noise.
- Existing duplicated staff usernames on the cloud stay namespaced
  (`counter_1__7`) internally — display names now hide this, but a proper
  per-business username scheme is a schema project for later.
- The legacy Add Product modal is dead-coded (`false &&`) rather than deleted
  to keep the diff reviewable — delete it on the next cleanup pass.

## What changed

### Bug fixes
- **BUG-1** `routes/admin.py`: added missing `from sqlalchemy import text` — `/admin/health-check` works again. Regression test: `tests/test_review1_hardening.py::test_admin_health_check_returns_200`.
- **BUG-2** `main_groq.py`: shutdown watcher now finds the uvicorn Server object once (bounded startup scan) and polls a cached reference — no more full-heap `gc.get_objects()` every second.
- `database/db.py`: RLS GUC set via parameterized `set_config()` instead of an f-string `SET`.
- Removed stray `.env.example.example`.

### Auth hardening (GAP-1)
- `users.token_version` column (migration registry entry — applies automatically on boot, SQLite + Postgres).
- Every JWT now carries a `tv` claim (login, staff login, signup, reclaim, ticket redeem). `get_active_user` validates it against the DB with a 30s in-process cache. Legacy tokens (no `tv`) are treated as `tv=0` — nothing breaks on deploy, but a bump revokes them too.
- **`POST /admin/force-logout/{business_id}`** — bumps token_version for owner + all staff: every session dies within ~30s. Wired to a button on the new business drill-down page.
- **`POST /auth/refresh`** — exchanges a valid token for a fresh one (claims re-read from DB). Enables lowering the TTL later.
- `ACCESS_TOKEN_TTL_MINUTES` env knob (default still 1440). Recommended later: set to 60 and have clients call `/auth/refresh` periodically.
- Generic `?token=` query auth is now **off by default** (`ALLOW_QUERY_TOKEN_AUTH=1` restores it). SSE tickets are unaffected.

### Observability & hygiene (GAP-5/8)
- Sentry init in `main_groq.py`, active only when `SENTRY_DSN` is set; `sentry-sdk` added to `requirements_hf.txt`.
- `.gitleaks.toml` + `.pre-commit-config.yaml` (gitleaks, private-key detection, large-file guard). Activate with `pip install pre-commit && pre-commit install`.

### Admin Console — growth half (§4.3)
- New tables: `campaigns`, `campaign_deliveries`, `offers`, `offer_redemptions` (auto-created on boot; excluded from the table-alteration audit).
- `services/campaign_service.py` + `routes/campaigns.py`:
  - Admin: campaign CRUD + activate/pause/end, audience preview (dry-run reach count), offer CRUD + enable/disable. All behind the fail-closed `ADMIN_API_ENABLED` gate + `require_admin`, mutations audit-logged.
  - Audience filters: `plans`, `business_types`, explicit `bizids` — empty filter = everyone.
  - Merchant: `GET /announcements` (live, qualifying, non-dismissed campaigns; delivery row written on first fetch), `POST /announcements/{id}/ack` (seen/clicked/dismissed funnel), `POST /offers/redeem` (owner-only; grants Pro for N days through the existing `users.settings.subscription` machinery, stacks onto a live grant, enforces caps/deadlines/once-per-business).
  - Honesty guard: email/whatsapp campaigns can be drafted but **cannot be activated** until the notifier integration lands.

### Admin Console — debugging half (§4.2)
- **`GET /admin/sync-doctor`** — red/amber/green per business with reasons (stuck queue age, errored ops, recent push failure rate), worst-first.
- **Campaigns page** (`/admin/campaigns`): campaign + offer tables with funnel stats, create modals with audience preview.
- **Business drill-down** (`/admin/businesses/:id`): overview stats, sync-doctor verdict, latest telemetry scoped by BizID, server-log tail filtered to the business, rate-limit summary, and Force logout / Flush cache / Download logs actions. Linked from the Businesses table (name + "Open").

### Billing app
- `AnnouncementsCard` on Home: dismissible announcement cards (mini-markdown, XSS-safe), one-tap offer redemption from a campaign, plus a quiet "Have an offer code?" entry. Owner-only, fail-quiet (a promo can never break the app shell).

## New tests
`backend/tests/test_review1_hardening.py` — 12 cases: health-check regression, refresh, force-logout revocation, query-token default-off, offer lifecycle (grant/dup/caps/validation), campaign lifecycle + funnel, email-activation guard, audience preview, cashier blocks, admin gates, sync doctor.

## Deploy checklist (your side)
1. Run the backend once locally — migrations add `token_version` and the campaign tables automatically. Then run `pytest` (full suite) as usual.
2. HF Space: rebuild (picks up `sentry-sdk`); optionally add `SENTRY_DSN` secret (free tier at sentry.io) — everything works without it.
3. All existing users stay logged in through the deploy (legacy tokens validate as `tv=0`).
4. If any external integration relied on `?token=` query auth, set `ALLOW_QUERY_TOKEN_AUTH=1` (none found in the codebase).
5. Admin Console: redeploy `frontend-admin` (new Campaigns page + drill-down), `frontend-billing` (announcements card).

## Not doable from code (ops items still open from REVIEW_1)
- Code-signing certificate purchase (GAP-7), uptime monitor signup (GAP-5), moving cloud off HF free tier (GAP-2 — deferred by you, noted), payment gateway + WhatsApp accounts (GAP-9/10 — prerequisites for the collections agent in REVIEW_2).
