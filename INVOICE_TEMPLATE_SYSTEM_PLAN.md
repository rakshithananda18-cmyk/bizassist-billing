# BizAssist — Invoice Template System & Multi-Vertical Billing Counter
## Implementation-Ready Plan (3 Testable Phases)

**Scope:** Classic printed invoice + Modern BizAssist invoice + thermal, switchable per invoice with zero data mutation; business-type-adaptive billing counters; logging; tests; migration; rollout.
**Constraint honored:** supermarket billing (`Sales.jsx` + `ThermalReceipt.jsx`) keeps working unchanged until Phase 2 migrates it *onto* the new engine.

---

# ✅ STATUS BOARD (updated 2026-07-02)

| Phase | Status | Delivered | Tests |
|---|---|---|---|
| **Phase 1 — Template engine + Classic + Modern** | ✅ **SHIPPED** | `core/billing/print_payload.py` (payload v1, `payload_hash`, amount-in-words, GST state map, visibility resolution) · `GET /sales/{no}/print-payload` · `POST /sales/print-events` beacon (9 log events) · migration `a8d3f1c9e5b7` (line `mrp`/`expiry_date`/`attributes`, `invoice_title`) · sale-time MRP/expiry snapshot in `commands._compute_line` · `print.invoice_template` setting · frontend `src/invoice/` (registry, formatters, ClassicA4, ModernA4, PrintPortal, InvoiceViewer with deep-frozen payload + `TemplateBoundary` crash fallback) · route `/invoice/:invoiceNo/view` · A4 `@media print` isolation in `index.css` | 18 backend + 20 frontend, all green; 72 backend + full frontend regression green |
| **Phase 2 — Multi-type + billing profiles (backend + counter gating)** | 🟢 **~80% SHIPPED** | `business_settings.business_types` (migration `b4e7a2d8f1c3`, lazy `[template_key]` fallback, no backfill) · `resolve_billing_profile()` + `get_business_types()` in loader · 4 new verticals (electronics, repair, mobile, b2b_supplier) · 7 verticals extended with `customer_required`/`line_fields`/`counter_widgets` · `POST /business/setup` accepts `template_keys[]` · `GET /business/billing-profile?mode=` · `billing_profile_applied` logging · frontend: `ThermalCompact` registry template (viewer reprints; POS thermal path untouched) · `useBillingProfile` hook (session cache, **fail-open**) · CheckoutModal customer-first gating (buttons + all 4 hotkeys) · View/Print buttons in Payments modal + Dashboard recent invoices | 18 backend (`test_billing_profile.py`) + 10 frontend, all green; full suite 188/188 |
| **Phase 2 — Chunk A (counter UX)** | ✅ **SHIPPED** | Registration multi-select ("Also runs as…" in `Register.jsx` → `POST /business/setup {template_keys}`, non-fatal fallback) · `CounterModeSwitcher` in `PosTopBar` (pills, visible only for multi-type, sticky per device via `pos.counter_mode`) · `useBillingProfile` upgraded: per-mode cache, live `bizassist:counter-mode` event, explicit-mode override, `counter_mode_switched` log — CheckoutModal gating follows the switched mode automatically · conftest hardened against Windows SQLite `disk I/O error` (retry + WAL/SHM cleanup) | +7 frontend tests; full suite 195/195 |
| Phase 2 — remaining | 🔲 OPEN | `Sales.jsx` entry-mode adaptation (barcode/search/menu focus) + vertical line-field entry (batch/expiry/size on the cart row → `attributes` snapshot) · Settings "Business types" add/remove section · Playwright e2e spec | — |
| **Phase 3 — PDF / share / conversions** | 🔲 NOT STARTED | — | — |
| **Phase 4.1 — Token foundation** | ✅ **SHIPPED** | One motion system (`--dur-fast` 120ms / `--dur` 180ms / `--dur-slow` 240ms, single ease-out; all 22 hardcoded transition durations replaced) · 6-step type scale + line-height tokens · 4px spacing grid (`--sp-1..8`) · `--border-hairline`/`--border-strong` (light + dark) · one `:focus-visible` accent ring (`--focus-ring`), quiet for mouse · app-wide tabular numerals (aligned digits everywhere) · form controls pinned to `--border-strong` · `prefers-reduced-motion` kill-switch · print blocks byte-untouched | `tokens.test.js` guard (6 tests incl. no-hardcoded-duration sweep); full suite 201/201 |
| **Phase 4.2 — Component pass** | ✅ **SHIPPED** (core) | Buttons (uniform 30/36/42px heights, press state, clean outline secondary) · tables (hairline separators, zebra OFF, muted uppercase headers, neutral hover, mono cells → tabular Geist Mono) · forms (38px controls) · modal rise softened to 8px · `.skeleton` shimmer + `<Skeleton>/<SkeletonTable>` + `<EmptyState>` shared components · badges unified. Modals/sidebar were already on-system (restraint — no churn). Deferred: POS cart internals (await Sales.jsx chunk), per-page EmptyState adoption (opportunistic) | +7 tests (`PolishComponents.test.jsx` incl. CSS-contract asserts); full suite 208/208 |
| **B2B transfer bug fix** (user-reported) | ✅ **SHIPPED** | Cloud↔Local sync dropped `b2b_connections`/`b2b_orders`/`b2b_order_line_items` (two-sided tables, no `business_id`). New `core/connection/transfer.py`: BizID-keyed export, identity re-resolution on import, counterparty stubs, natural-key upserts, idempotent. Requires cloud redeploy + re-sync | 4 tests (`test_b2b_transfer.py`) + 19 regression |

### Deviations from plan (deliberate, documented)
1. **Template preference storage:** used the existing `User.settings.print.invoice_template` (via `PUT /settings`) instead of a new `PUT /business/print-settings` — the app already had a print-settings mechanism; no new surface added.
2. **Thermal on the registry:** shipped as a NEW payload-based `ThermalCompact` renderer for *saved* invoices. The live POS `ThermalReceipt` (which renders from in-flight form state, not a saved invoice) was left byte-untouched — safer than the planned refactor; the parity-gate refactor moves to the Phase 2 remainder as an optional item.
3. **`invoice_layout` stayed a string** in configs; the structured mapping lives in `loader._LAYOUT_TO_TEMPLATE`. Avoids touching every consumer; same outcome.
4. **Phase 1 PDF** is browser print-to-PDF (as planned); the legacy `GET /sales/{no}/pdf` server endpoint remains as fallback.

---

# 📌 HANDOFF — CURRENT STATE, PENDING WORK, NEXT STEPS (recorded 2026-07-02, end of session)

## H0. Shipped this session (beyond the status board above)

| Chunk | Files touched | Tests |
|---|---|---|
| **Sales structural chunk** — serial/IMEI line field end-to-end + profile-driven cart columns | `Sales.jsx` (useBillingProfile hook, `serial` in columnOrder w/ localStorage backfill, profile-aware `colVisible` for mrp/serial, `serial_no` in all 3 item constructors) · `CartItemRow.jsx` (serial input cell, class `serial-input`) · `CartTableHeader.jsx` (SERIAL / IMEI header) · `invoiceMath.buildInvoicePayload` (+`serial_no`) · backend `sales.py` (`FrontendInvoiceItem.serial_no` + lines passthrough) | `SerialLineField.test.jsx` (6) + `test_serial_line_field.py` (1 e2e: POS save → line row → print payload column); affected suites 102/102, backend 6/6 |
| conftest hardening | `tests/conftest.py` — 3× retry with WAL/SHM cleanup for Windows `disk I/O error` | verified on previously-failing module |

## H1. ⚠️ DEPLOY CHECKLIST (do this when you push — order matters)

1. **Cloud (HF space) redeploy** with this codebase. The B2B transfer fix runs at *export time on the cloud side* — without redeploy, Cloud→Local sync still drops B2B data.
2. **Cloud DB migration:** `alembic upgrade head` → applies `a8d3f1c9e5b7` (invoice print fields) and `b4e7a2d8f1c3` (business_types). Both additive/nullable, safe.
3. **Local:** just restart — `run_migrations_and_seed()` auto-adds the SQLite columns on boot.
4. **Re-run Cloud → Local Sync** from Settings → B2B Orders + B2B Network populate (counterparty stubs get created for businesses that only exist in cloud).
5. Verify: B2B Orders → **Incoming Orders (Sales)** tab shows `B2B-ORD-20260630-2QTE` (you are the seller; it was never an "Outgoing" order).

## H2. PENDING CODE CHANGES (concrete, in recommended order)

**P1 — Settings UI toggles + "Business types" section** *(small, do first)*
- `pos_show_serial` is read by `Sales.jsx` colVisible but has no default in `routes/auth.py:_DEFAULT_SETTINGS.transactions` and no toggle in `Settings.jsx` → add both (copy the `pos_show_mrp` pattern).
- Settings → new "Business types" card: list `GET /business/billing-profile → business_types`, add/remove via `POST /business/setup {template_keys}` (backend done; changing the PRIMARY clears overrides — warn in UI).

**P2 — Entry-mode adaptation in Sales.jsx** *(medium)*
- `billingProfile.entry_mode` is already available in Sales.jsx (hook wired this session). Apply: `barcode` → keep current autofocus (default, no-op); `search` → same input without scan-first jump; `menu` (restaurant) → product-grid panel instead of search list — this is the only real build; gate it behind `entry_mode === 'menu'` so nothing else changes. KOT ticket rendering pairs with it (config flag `workflows.tables_kot` exists).
- Batch/expiry/mrp columns are already profile-aware via `line_fields`; textile size/color should ride `InvoiceLineItem.attributes` — add a generic small-input cell for `line_fields` not covered by dedicated columns, snapshot as JSON in `buildInvoicePayload` (`attributes` column already exists, backend accepts it via `_compute_line`? — NOTE: `_compute_line` does NOT yet map `attributes`; add `"attributes": json.dumps(line["attributes"])` there when you build this).

**P3 — Phase 3 (product leverage: share the invoice)** *(the next big chunk)*
1. Decision spike: WeasyPrint (already the legacy `/pdf` fallback dep) vs `playwright`-chromium rendering the actual React templates. Recommendation: **WeasyPrint first** (zero new infra; render a server-side HTML twin of ClassicA4 from the SAME print payload), swap to chromium later if fidelity disappoints.
2. `GET /sales/{no}/pdf?template=` — replace the legacy `generate_invoice_html` path with payload-driven rendering; delete `num_to_words_indian` duplicate in `sales.py` in the same PR.
3. Public share link: `GET /public/invoice/{uid_token}` — unguessable `invoice.uid`, business opt-in flag, renders view-only page with ZERO cost/margin fields (BizID leak rule). This is the Trust-Ledger wedge surface.
4. WhatsApp share: `share.js` already has `buildWaShareUrl` builders — wire to hosted PDF/link.
5. Duplicate invoice (`POST /sales/{id}/duplicate` → draft through billing command) + credit-note convert (seller command exists — `create_credit_note` in `core/billing/commands.py`; add route + viewer button).
6. Per-invoice template override: tiny migration `invoices.print_template`; resolution order becomes invoice → user last-used → business setting → vertical default.

**P4 — Realtime/outbox sync for B2B tables** *(design first, don't rush)*
- Only the EXPORT/IMPORT path was fixed. `database/sync_map.py MODEL_MAP` still excludes `b2b_connections/b2b_orders/b2b_order_line_items` — deliberate: realtime sync scopes rows by single `business_id` and matches on `uid` (these tables have neither). To include them you need: uid columns (+alembic+sqlite migration+`_UID_TABLES`), two-sided scoping in `routes/sync.py` pull + `sync_worker` push, and BizID re-resolution like `core/connection/transfer.py`. Until then: B2B changes propagate via the manual Sync button only.

**P5 — Phase 4 leftovers**
- POS cart-area polish now unblocked (serial column landed): densify cart inputs onto the token scale.
- Per-page inline-style extraction: opportunistic only, when touching a page anyway.
- Playwright visual-regression baselines (390px + 1280px per page) before any further CSS pass.

**P6 — E2E spec (still open)**
- `e2e/invoice-templates.spec.js`: create invoice at POS → open `/invoice/:no/view` → switch Classic/BizAssist/Thermal → assert grand total + `payload_hash` unchanged → set default → reload persists. Needs running backend; run outside sandbox.

**P7 — From the product review (strategic P0s, schedule deliberately)**
- Integer-paise (or Decimal) money end-to-end; nightly accounting-invariant job (trial balance foots, every invoice has a journal entry, hash-chain verify); divergent-edit conflict policy per entity (immutable + amendment for financial docs). These are the production-trust items — bigger than the invoice plan, tracked in `BIZASSIST_EXPERT_REVIEW.md` §7 P0.

## H3. KNOWN QUIRKS / CAVEATS (so they don't bite you)

1. **Mixed line endings:** repo is mostly CRLF; some tooling writes LF. Harmless to builds, but exact-match patch scripts must handle both (this session's scripts do).
2. **`pos_show_serial` default:** until P1 lands, serial column visibility is purely profile-driven (electronics/mobile/repair show it; others don't). Explicitly setting `transactions.pos_show_serial=true` via API also works.
3. **Counterparty stubs** (`bizstub-*` usernames) appear in the local users table after a sync — they're directory entries with unusable passwords, expected and harmless; a later cloud sync matches them by BizID.
4. **Test dashboard flake:** if `disk I/O error` ever reappears on Windows, it's file-lock contention on `test_bizassist.db` — the conftest now retries 3× with WAL/SHM cleanup; also avoid running the dashboard server against the same DB while pytest runs.
5. **Dev-sandbox file sync** (my environment, not yours): edited files intermittently truncate in the sandbox replica; all real files on disk were verified intact each time. If your CI mounts folders similarly, prefer `git clone` workspaces.

# ▶ WHAT'S NEXT (original phase-level recommendation — still valid)

### Chunk A — Finish Phase 2 UX (1 session)
1. **Registration multi-select** (`Register.jsx`): business-type picker → `POST /business/setup {template_keys}`. Backend done; UI only.
2. **Counter mode switcher** (`PosTopBar.jsx`): visible when `profile.business_types.length > 1`; sticky per device (`localStorage`); logs `counter_mode_switched`. Feeds `mode` into `useBillingProfile(mode)`.
3. **Entry-mode + line-field adaptation in `Sales.jsx`**: barcode-focus vs search vs menu from `profile.entry_mode`; render `profile.line_fields` (batch/expiry/serial/size) on the cart line; snapshot into `attributes` on save. *Highest-risk file in the repo — do it as its own PR with the existing Sales test suite as the gate.*
4. Settings page: "Business types" section (add/remove secondary types).

### Chunk B — Phase 3 wedge (highest product leverage)
Priority inside Phase 3: **server PDF → WhatsApp share → duplicate → credit-note convert**. The share link is the BizID Trust Ledger acquisition surface from the product review — build the PDF/link infrastructure with the public-token model from day one (unguessable `invoice_uid` token, business opt-in, zero cost/margin fields).

### Chunk C — Phase 4 tokens-first polish
Ship §4.1 (tokens only) alone first — biggest visual lift, smallest risk, no test churn beyond snapshots.

# ⚠ SUGGESTIONS / WATCH-LIST (from implementation experience)

1. **CRLF + huge files:** `Sales.jsx` (2,640 lines), `CheckoutModal.jsx` (1,267) are CRLF and heavily inline-styled. Before Chunk A step 3, consider extracting the cart-line row into its own component — it shrinks every future vertical change.
2. **`num_to_words_indian` duplication:** canonical copy now lives in `print_payload.py`; the legacy copy in `core/api/sales.py` serves only `generate_invoice_html`. When Phase 3 server-PDF replaces the legacy HTML path, delete the legacy generator + its words function in the same PR.
3. **Fail-open gating is a policy choice:** offline counters skip `customer_required` enforcement (correct for billing continuity). If a business wants hard enforcement offline, cache the last-known profile in the outbox layer — one-line change in `useBillingProfile` (persist `_cache` to `localStorage`).
4. **`meta.template_default` vs profile default:** payload uses the *saved print setting*; profile uses the *vertical's layout*. Resolution order in the viewer is: user last-used → business setting → vertical default. Keep that order when adding per-invoice override (Phase 3) — it becomes: invoice → user → business → vertical.
5. **Estimates/credit notes** already flow through the payload (title map handles them), but there's no viewer entry point from the credit-note list yet — cheap add during Chunk B.
6. **E2E gap:** unit/component coverage is strong; the planned Playwright spec (`e2e/invoice-templates.spec.js` — create → switch → totals unchanged → persist) is still open. Add it in Chunk A while touching Sales.
7. **Dev-environment note:** the sandboxed test runs hit workspace↔sandbox file-sync truncation on *edited* files (real files always intact). If CI runs in a similar mounted environment, prefer `git clone` over folder mounts for test workspaces.

---

## 0. Current-State Audit (what we build on — do not reinvent)

| Existing asset | Location | Reuse |
|---|---|---|
| **Business Template System** — config-per-vertical JSON (8 configs: general, supermarket, pharmacy, restaurant, wholesale, hardware, textile, services) with `terminology`, `billing`, `product_fields`, `invoice_layout`, `workflows`; loader with override guardrails | `backend/core/templates/` | This IS the business-type config layer. We extend `invoice_layout` from a string (`"thermal_80mm"`) into a structured object. No new config system |
| `BusinessSettings.template_key` (single vertical per business) | `core/models.py:166` | Extend for multi-type (Phase 2) |
| Line items already carry `hsn_sac`, `unit`, `batch_no`, `serial_no`, per-line CGST/SGST/IGST/cess, `taxable_value`, `discount`, `discount_pct`, `line_total`, denormalised `product_name` | `database/models.py` (InvoiceLineItem) | 90% of Classic GST columns already exist. Missing: `mrp`, `expiry_date`, line `attributes` snapshot |
| Invoice: GSTFieldsMixin, `cash_discount`, `paid_amount`, `payment_mode`, `due_date`, customer FK | `database/models.py` | Header/totals source |
| Split payments (`InvoicePayment`, `TenderChips.jsx`), amount tender UX | `core/models.py`, `frontend-billing/src/components/sales/` | Payment block source |
| Thermal receipt with drag-to-reorder header layout persisted at `settings.print.header_layout` | `ThermalReceipt.jsx`, `utils/printLayout.js` | Becomes one renderer in the registry (Phase 2) |
| Money math owned by billing commands, never templates ("templates change PRESENTATION + DEFAULTS only" — loader guardrail) | `core/billing/commands.py`, `core/accounting/posting.py` | The invariant this whole plan preserves |
| Structured loggers `bizassist.*`, `ActionLog` audit pattern | `services/`, `posting.py` | Logging plan follows this style |
| Test harness: `test_business_template.py`, component tests (`ThermalReceipt.test.jsx`), Playwright e2e | `backend/tests/`, `frontend-billing/src/__tests__/`, `e2e/` | Test plan slots in |

**Gaps:** single print template; no A4 layout; no normalized print payload; no template preference storage; no server PDF; single business type; `mrp`/`expiry` not snapshotted on line items.

---

## Core Architecture Decision

**One normalized payload, many renderers.** Data and presentation are separated by contract:

```
Invoice + LineItems + Payments + BusinessSettings + Customer   (DB, unchanged)
        │
        ▼
GET /sales/{id}/print-payload            backend mapper (core/billing/print_payload.py)
        │      → InvoicePrintPayload v1 (versioned, normalized, computed once)
        ▼
frontend-billing/src/invoice/
  ├── registry.js          { classic: ClassicA4, modern: ModernA4, thermal: ThermalCompact }
  ├── InvoiceViewer.jsx     template selector + print/PDF/share toolbar
  ├── templates/ClassicA4.jsx | ModernA4.jsx | ThermalCompact.jsx   (pure: payload → JSX)
  └── printFrame.js         portal/iframe print isolation (pattern from ThermalReceipt)
```

Rules that make "switching never mutates data" structurally true:

1. **Templates are pure functions** of `(payload, displayConfig)`. Props are frozen (`Object.freeze` in dev); no template receives a setter, no template fetches.
2. **All money values arrive pre-computed and pre-formatted** in the payload (mapper runs server-side next to the command layer). Templates never add, round, or derive amounts — including amount-in-words.
3. **Field visibility is config, not template logic.** The payload carries a `visibility` block resolved from the business template config; renderers just honor it.
4. **Unknown/failed template → fallback to `classic` + `template_fallback_used` log**, never a blank invoice.

### InvoicePrintPayload v1 (contract)

```jsonc
{
  "version": 1,
  "invoice": { "id", "uid", "number", "title",            // "Tax Invoice" | "Bill of Supply" | "Retail Invoice" | "Estimate" | "Proforma" | "Credit Note"
               "date", "time", "place_of_supply", "due_date", "notes", "is_credit" },
  "seller":  { "name", "logo_url", "address", "phone", "email",
               "gstin", "state", "state_code", "biz_id", "upi_qr": {"vpa","payload"} | null,
               "bank": {...} | null },
  "buyer":   { "name", "phone", "billing_address", "shipping_address" | null,
               "gstin" | null, "state", "customer_type" },   // retail | wholesale | registered
  "lines": [ { "sno", "name", "description", "hsn_sac", "batch_no", "expiry", "mrp",
               "serial_no", "qty", "unit", "rate", "discount", "taxable_value",
               "gst_rate", "cgst", "sgst", "igst", "cess", "line_total",
               "attributes": {...} } ],                      // size/color/warranty… snapshot
  "totals":  { "subtotal", "total_discount", "taxable_amount", "cgst_total",
               "sgst_total", "igst_total", "cess_total", "round_off", "cash_discount",
               "grand_total", "amount_paid", "balance_due", "amount_in_words",
               "previous_balance" | null, "current_balance" | null },
  "payments": [ { "mode", "amount", "reference" | null } ],  // split tender rows
  "tax_summary": [ { "hsn", "taxable", "rate", "cgst", "sgst", "igst" } ],  // GST annexure
  "footer":  { "terms", "return_policy", "signature_label", "thank_you",
               "computer_generated_note": true },
  "visibility": { "gst_mode": true|false, "igst_mode": bool,   // inter-state
                  "columns": ["hsn","batch","expiry","mrp","serial", …],
                  "blocks": ["shipping","bank","upi_qr","prev_balance","transport"] },
  "meta": { "business_type": "supermarket", "template_default": "thermal",
            "generated_at", "payload_hash" }                  // hash → e2e "totals unchanged" check
}
```

`visibility.gst_mode=false` collapses the item table to the simple 6-column mode (S.No / Item / Qty / Rate / Discount / Amount) and suppresses GSTIN/tax blocks — resolved server-side from seller GSTIN presence + template config, so a non-GST business can never accidentally print empty tax columns.

---

# PHASE 1 — Template Engine + Classic + Modern (ship, test, move on)

**Goal:** open any existing invoice → switch Classic / Modern / (existing) Thermal → print / download — with zero change to how invoices are created. Supermarket POS untouched.

## 1.1 Backend

| Change | Detail |
|---|---|
| **`core/billing/print_payload.py`** (new) | `build_print_payload(invoice_id, business_id, db) -> dict`. Pure read. Computes amount-in-words (Indian numbering: lakh/crore), round-off display, HSN tax summary, resolves visibility from `resolve_for(business_id)` template config + seller GSTIN. Reuses totals already persisted by commands — **never recomputes tax** |
| **`GET /sales/{invoice_id}/print-payload`** (extend `core/api/sales.py`) | Auth + business-scoped (existing patterns). Returns payload v1. 404-safe, staff-role allowed |
| **`InvoicePrintSettings`** | New keys inside `BusinessSettings.overrides` JSON under `invoice_layout` (already a mergeable section in `loader.py` — no new table): `{"default_template": "classic|modern|thermal", "paper": "a4|thermal_80mm", "show_logo": bool, "footer": {terms, return_policy, thank_you}, "bank": {...}, "upi_vpa": "..."}` |
| **`PUT /business/print-settings`** (extend `core/api/business.py`) | Persists via existing `validate_overrides` guardrails |
| **Invoice title resolution** | Mapper derives title: seller GSTIN + buyer GSTIN → "Tax Invoice"; GST seller, B2C → "Tax Invoice"/"Retail Invoice" per config; no GSTIN → "Retail Invoice"; composition scheme flag (settings) → "Bill of Supply"; `status=estimate` → "Estimate" |
| **Migration `add_invoice_print_fields`** | `invoice_line_items`: add `mrp Float NULL`, `expiry_date String NULL`, `attributes JSON NULL` (snapshot of vertical fields at sale time — consistent with `Product.attributes` philosophy: no schema fork per vertical). `invoices`: add `invoice_title String NULL`, `round_off Float NULL`. All nullable → zero backfill risk; payload falls back gracefully for historical rows |

## 1.2 Frontend (`frontend-billing`)

| Component | Responsibility |
|---|---|
| `src/invoice/registry.js` | `{ key → {component, label, paper, supports:{gst, nonGst}} }`. Adding a template later = one entry |
| `src/invoice/InvoiceViewer.jsx` | Route `/invoice/:id/view` + modal from Sales/Reports lists. Toolbar: template selector (segmented control: **Classic · BizAssist · Thermal**), Print, Download PDF, Share, Duplicate (Phase 3), Convert to Credit Note (Phase 3). Fetches payload once; switching templates re-renders only — payload object is frozen and never refetched (this is the no-mutation guarantee, and the thing the e2e asserts) |
| `src/invoice/templates/ClassicA4.jsx` | Part-1 spec exactly: bordered header (name/logo/address/GSTIN/state+code), title strip, invoice no + date/time + place of supply, buyer block (billing/shipping/GSTIN/type), full GST item table (S.No/Item/HSN/Batch/Expiry/MRP/Qty/Unit/Rate/Disc/Taxable/GST%/CGST/SGST/IGST/Total) with column set driven by `visibility.columns`, totals ladder, amount in words, payment rows, HSN tax summary annexure, footer (terms/bank/UPI QR/signature/"Computer generated invoice"). Monochrome, table-ruled, dense — prints like the market-standard bill books every distributor knows |
| `src/invoice/templates/ModernA4.jsx` | Brand-accent header band (single accent color, business-configurable, default BizAssist indigo), logo left / invoice-meta card right, buyer + metadata as two clean blocks, generous whitespace, item table with light row separators (no full grid), right-aligned elegant totals panel with grand-total emphasis, payment status chip (PAID / PARTIAL / DUE), QR + UPI payment block, slim footer. Typography: system font stack + tabular numerals for amounts. No gradients, no decoration — premium and printable in B/W |
| `src/invoice/printFrame.js` | Extracted from the proven ThermalReceipt portal pattern: renders selected template into isolated print root with `@page` CSS (`A4` / `80mm auto`), triggers `window.print()` |
| PDF (Phase 1 scope) | Client-side print-to-PDF via the same print CSS (browser native). Server-rendered PDF deferred to Phase 3 — keeps Phase 1 shippable |
| Preference | Business default from print-settings; per-user last-used in `localStorage` (`invoice.template.<business_id>`); explicit "Set as default" writes to `PUT /business/print-settings` |

Both A4 templates handle: simplified non-GST column mode, IGST vs CGST/SGST column swap, ≥ 25-line page-break with repeated table header, mobile viewing (payload renders read-only responsive; print CSS unaffected).

## 1.3 Phase 1 Logging (logger: `bizassist.invoice_render`)

Backend structured logs (same style as `[ACCT]`/sync logs) + a lightweight `POST /sales/print-events` beacon for client-side events:

| Event (`action`) | When | Extra fields |
|---|---|---|
| `payload_built` | print-payload served | `gst_mode`, `line_count`, `payload_hash` |
| `payload_missing_fields` | required field absent for GST invoice (e.g. GSTIN present but state_code missing) | `missing[]` — warn, not fail |
| `gst_field_mismatch` | buyer GSTIN state ≠ place of supply, IGST/CGST inconsistency detected while mapping | `expected`, `found` |
| `template_selected` | user switches template | `template_type`, `previous` |
| `print_opened` | print dialog triggered | `template_type` |
| `pdf_generated` / `pdf_failed` | export attempt | `duration_ms` / `error` |
| `shared` | share action | `channel` |
| `template_fallback_used` | unknown key or renderer threw | `requested`, `fallback`, `error` |
| `print_settings_saved` | business default changed | `default_template` |

Every event carries: `invoice_id`, `invoice_uid`, `business_id`, `user_id` (when available), `template_type`, `business_type`, `action`, `success`, `error` (nullable). Client beacon failures are silent (never block printing).

## 1.4 Phase 1 Tests (exit gate)

Backend (`tests/test_print_payload.py`, `tests/test_print_settings.py`):

1. Payload contains all required sections for a full GST B2B invoice (seller+buyer GSTIN, place of supply, per-line tax, HSN summary).
2. Non-GST business → `gst_mode=false`, no GSTIN/tax keys leak, simple column set.
3. B2C GST invoice → buyer GSTIN absent, title "Tax Invoice"/"Retail Invoice" per config.
4. Inter-state → `igst_mode=true`, CGST/SGST zero; intra-state inverse.
5. Split payment (cash+UPI) appears as two payment rows summing to `amount_paid`.
6. Credit invoice → `balance_due = grand_total − paid`, due_date present.
7. Amount-in-words: paise, lakh/crore boundaries, ₹0, ₹99,99,999.99.
8. `payload_hash` stable across two builds of the same invoice (determinism).
9. Print-settings save/load round-trip through `validate_overrides`; invalid template key rejected.
10. Tenant isolation: user B cannot fetch user A's payload (extends existing RLS/auth test patterns).
11. Log events emitted with required fields (`caplog` assertions, like `test_auth_logging.py`).
12. Historical invoice (pre-migration, null new columns) builds a valid payload.

Frontend (`src/__tests__/invoice/`):

13. ClassicA4 snapshot: GST mode + non-GST mode.
14. ModernA4 snapshot: paid / partial / due states.
15. Template switch: render Classic → switch Modern → deep-equal payload prop unchanged (frozen object identity).
16. `visibility.columns` toggles HSN/batch/expiry/MRP/serial columns.
17. Print button invokes printFrame with selected template; PDF button calls handler.
18. Fallback: registry miss renders Classic + fires `template_fallback_used` beacon.
19. Long invoice (40 lines) paginates with repeated header (jsdom structural assert).
20. Mobile viewport (390px) — no horizontal overflow (existing responsive test pattern).

E2E (`e2e/invoice-templates.spec.js`): create invoice at POS → open viewer → totals visible → switch all three templates → assert on-screen grand total and `payload_hash` identical across switches → print (dialog stubbed) → set Modern as default → reload → Modern loads.

**Phase 1 done =** all above green + existing `ThermalReceipt.test.jsx`, sales API and billing tests untouched and green.

---

# PHASE 2 — Business-Type Billing Profiles & Adaptive Counter

**Goal:** registration selects multiple business types; the POS counter, default fields, and invoice columns adapt per type; thermal template joins the registry. Supermarket behavior = current behavior (it becomes just the `supermarket` profile).

## 2.1 Data model

| Change | Detail |
|---|---|
| **Multi-type business** | `BusinessSettings.business_types JSON NULL` (ordered list, first = primary; migration backfills `[template_key]`). `template_key` stays as the primary — nothing existing breaks. Signup picker becomes multi-select; counter gets a mode switcher when >1 type |
| **`BusinessBillingProfile`** (resolved object, not a table) | `resolve_billing_profile(business_id, db, mode_key=None)` in `core/templates/loader.py`: template config ⊕ overrides ⊕ chosen mode → `{entry_mode, customer_first, default_invoice_type, payment_modes, price_tier_enabled, line_fields[], counter_widgets[], invoice: {template, paper, columns[], blocks[]}}` |
| **Template config extension** (per JSON, guardrailed via existing `_MERGEABLE_SECTIONS`) | `invoice_layout` string → object: `{"default_template", "paper", "columns", "blocks", "title_map"}`; `billing` gains `line_fields`, `counter_widgets`, `customer_required` |
| **New vertical configs** | Add JSONs: `electronics.json`, `repair.json`, `mobile.json`, `b2b_supplier.json`, `grocery→supermarket alias`; extend existing pharmacy/restaurant/wholesale/hardware/textile(garments)/services per matrix below. *Adding a vertical remains: one JSON file, no migration* |
| **`InvoiceFieldVisibility` / `InvoiceColumnConfig`** | Not new tables — they are the `columns`/`blocks` arrays in config, already flowing through `payload.visibility` since Phase 1. Phase 2 adds the per-business override UI in Settings |

## 2.2 Billing-counter mode matrix (drives config JSONs)

| Business type | Entry mode | Customer | Invoice default | Extra line fields | Counter widgets | Print default |
|---|---|---|---|---|---|---|
| Supermarket/grocery | barcode-first, fast scan, qty edit | optional (phone only) | B2C, tax-inclusive | MRP, discount | split tender (exists), quick-qty | thermal |
| Retail shop | search+barcode | optional | B2C | discount | quick discount | thermal/A5 |
| Wholesale/distributor | **customer-first** | required | B2B GST, credit | bulk qty, price tier, free-qty scheme | outstanding-balance banner, transport/e-way fields, B2B order convert (exists: `B2BOrders`) | classic A4 |
| Pharmacy | search | optional | B2C GST | **batch (exists), expiry, MRP, manufacturer** | expiry alert chip, prescription ref (attributes) | thermal/A5 |
| Electronics/appliances | search | recommended | GST | **serial/IMEI (exists), warranty months, installation note** | delivery address block | modern A4 |
| Hardware/building | search | optional | GST, credit common | **unit conversion (ft/m/kg/bag), weight/length/area** | delivery challan toggle, transport | classic A4 |
| Restaurant/food | **grid/token** | none | B2C inclusive | parcel/dine-in flag | table/token no., service charge %, KOT (Phase 3 flag) | thermal compact |
| Service business | line-entry | required | SAC invoice | **SAC, labor hours/rate** | advance received, job/appointment ref | modern A4 (service layout) |
| Repair center | job-first | required | SAC + parts | **job card no., device details, problem, parts used, warranty note** | job status, advance | modern A4 |
| Garments/footwear | barcode/SKU | optional | B2C | **size/color variants (attributes), exchange-by date** | heavy-discount presets | thermal/A5 |
| Mobile/accessories | barcode+IMEI | optional | B2C/B2B | IMEI (serial_no), warranty | IMEI scan | thermal/A4 |
| B2B supplier | customer-first | required | B2B GST | tier price, scheme | order-to-invoice (exists), outstanding | classic A4 |
| General trader | search | optional | auto | — | — | classic A4 |

All vertical line fields ride in `InvoiceLineItem.attributes` (added Phase 1) except the already-typed columns (`batch_no`, `serial_no`, `hsn_sac`, `mrp`, `expiry_date`). Counter renders extra fields from `attributes_schema(key)` — the mechanism `product_fields` already uses.

## 2.3 Frontend counter changes

- `Sales.jsx` reads `resolve_billing_profile` (one new `GET /business/billing-profile?mode=` call, cached in context): toggles customer-first gating, entry mode (barcode focus vs search vs grid), visible line-item fields, counter widgets, default payment modes, default print template.
- **Mode switcher** in `PosTopBar` when `business_types.length > 1` (e.g. a shop that is retail + repair). Mode choice logs `billing_profile_applied` and is sticky per device.
- `ThermalCompact` template moves into the registry (`ThermalReceipt.jsx` refactored to consume `InvoicePrintPayload` — its header-layout drag feature and tests are preserved; snapshot parity test proves identical output for supermarket invoices → **the do-not-break-supermarket gate**).
- Wholesale extras: outstanding balance banner (party ledger endpoint exists), transport/e-way fields → `invoice.attributes`.

## 2.4 Phase 2 logging additions

`billing_profile_applied` (`mode_key`, `business_types`), `counter_mode_switched`, `line_field_schema_missing` (attributes schema absent for configured field), `column_config_overridden`. Same envelope as Phase 1.

## 2.5 Phase 2 tests (exit gate)

Backend: profile resolution per each of the 13 types (config → correct entry mode/columns/fields); multi-type backfill migration (`template_key` → `business_types`); override guardrails still reject new top-level sections; pharmacy payload includes batch/expiry columns while supermarket payload excludes them; hardware unit-conversion lines carry converted qty snapshot; wholesale B2B payload requires buyer GSTIN → `gst_field_mismatch` warn if absent.

Frontend: pharmacy fields visible only under pharmacy profile; serial/IMEI only for electronics/mobile; customer-first gating blocks checkout without customer for wholesale/service; restaurant grid mode renders; **thermal parity snapshot** (old ThermalReceipt output == registry ThermalCompact output for same invoice); mode switcher persists.

E2E: register with 2 business types → counter shows mode switcher → bill in each mode → each invoice opens with the right default template and columns → supermarket regression suite unchanged.

---

# PHASE 3 — Distribution, Conversions, and Advanced Templates

**Goal:** the invoice becomes a shareable artifact; viewer completes its toolbar; long-tail layouts.

| Workstream | Detail |
|---|---|
| **Server-side PDF** | `services/pdf_render.py` (Playwright-chromium or WeasyPrint rendering the same frontend template bundle — one source of truth; decision spike first). `GET /sales/{id}/pdf?template=`. Cached per `(invoice_uid, template, payload_hash)`. Unlocks WhatsApp/email attach + consistent PDFs regardless of client browser |
| **Share** | Share sheet: WhatsApp (wa.me link with hosted PDF URL), email (existing notifier), copy-link. Hosted invoice link = read-only public page keyed by unguessable `invoice_uid` token + explicit business opt-in (this is also the **BizID Trust Ledger wedge surface** from the product review) |
| **Duplicate invoice** | `POST /sales/{id}/duplicate` → new *draft* through the existing billing command (full stock/journal integrity; not a row copy) |
| **Convert to credit note / return** | Uses existing returns support (`allow_returns` config): pre-fills return command from invoice lines; payload `invoice.title="Credit Note"`, `is_credit=true`; journal reversal already owned by accounting layer |
| **Per-invoice template override** | `invoices.print_template String NULL` (tiny migration): viewer "Always use for this invoice" — resolution order: invoice override → user last-used → business default → template-config default (each step logged) |
| **Additional templates** | `HalfPageA5`, `ServiceInvoice` (SAC/labor emphasis, no item grid), `EstimateLayout` (watermark "ESTIMATE — not a tax invoice"). Registry entries only |
| **Restaurant KOT** | Kitchen ticket renderer behind `workflows.kot` flag (config already has `workflows`) |
| **Polish** | Logo upload (reuse `upload.py`), accent-color picker (guardrailed to accent only), UPI QR generation from configured VPA |

Phase 3 tests: PDF byte-determinism per `payload_hash`; share-link auth (unauth → only public template, no cost fields — mirrors BizID "leak nothing" rule); duplicate posts fresh journal/stock (assert via existing accounting tests); credit-note totals negative-mirror original; override resolution order; A5/service snapshots.

---

# PHASE 4 — Premium UI Polish Pass (no redesign)

**Goal:** the existing `frontend-billing` app — same layout, theme, navigation, workflows, features — but with Apple-grade calm: precise, quiet, consistent. Zero flow changes, zero feature changes, zero flashiness.

## 4.0 Current-state audit (what we work with)

- Single `src/index.css` (~4,100 lines) with an already-good **token system**: warm near-white canvas (`--bg: #fdfdfc`), terracotta accent (`--accent: #c15f3c`), radius scale, 3-tier soft shadows, `--dur`/`--ease` motion vars, status colors. **The theme stays — we refine, not replace.**
- No Tailwind; component classes + heavy inline `style={{}}` in pages (`Dashboard`, `Parties`, `Payments`, `B2B*`, …) → the main source of visual inconsistency.
- Transition durations scattered (0.13s / 0.15s / 0.18s / 0.22s hardcoded alongside `var(--dur)`).

## 4.1 Foundation pass (tokens only — instant global lift)

| Area | Change | Apple-feel rationale |
|---|---|---|
| Type scale | Lock a 6-step scale as tokens (`--fs-xs 12 → --fs-2xl 24`), line-heights 1.45 body / 1.2 headings; `font-variant-numeric: tabular-nums` on ALL amounts, tables, totals | Numbers that align are 80% of "premium" in a billing app |
| Spacing | 4px-grid tokens (`--sp-1..--sp-8`); sweep components onto them (kills the 13px/18px/22px drift) | Consistent rhythm reads as engineered |
| Borders | Split `--border` into `--border` (hairline `rgba` ~55% current strength) + `--border-strong` (inputs/tables); hairlines everywhere else | Apple = hairlines, not 1px grey boxes |
| Shadows | Recalibrate: cards `--shadow-sm` only; `--shadow-md` reserved for popovers, `--shadow-lg` for modals. Never shadow + strong border together | One elevation language |
| Motion | Single system: `--dur-fast: 120ms`, `--dur: 180ms`, `--dur-slow: 240ms`, `--ease: cubic-bezier(.2,.8,.2,1)`; replace every hardcoded duration; add `@media (prefers-reduced-motion)` kill-switch | Smooth = consistent, not slow |
| Focus | One focus token: 2px accent-dim ring (`box-shadow: 0 0 0 3px var(--accent-dim)`) + `--border-focus` → accent; applied via `:focus-visible` only | Keyboard-visible, mouse-quiet |
| Accent discipline | Accent reserved for: primary action, active nav item, focus, links. Everything else neutral | Restraint is the premium signal |

## 4.2 Component pass (one PR per row — independently reviewable/testable)

| Component | Polish (existing classes, refined) |
|---|---|
| **Buttons** | 3 variants only (primary filled / secondary outline-on-white / ghost) + danger. Uniform height (36px, 32px compact), radius `--radius-md`, subtle `translateY(0.5px)` + shadow-remove on `:active` (pressed feel), disabled = 45% opacity never grey-swap, loading = inline spinner replacing label at fixed width (no layout jump) |
| **Tables** | Header: `--fs-xs` uppercase 0.04em tracking, `--text-muted`, hairline bottom only. Rows: 44px, hairline separators, no zebra; hover `--bg-3`; numeric cells right-aligned tabular; sticky header on scroll; row-count footer |
| **Forms** | Inputs 38px, `--border-strong`, white bg, focus ring per 4.1; labels `--fs-sm` medium above (never floating); error = danger border + 12px message below (no shake); consistent field gap `--sp-4` |
| **Cards** | White, hairline border, `--shadow-sm`, `--radius-lg`, uniform `--sp-5` padding; card title row standardized (title left / action right); kill any card-in-card double borders |
| **Modals** | Overlay `rgba(20,18,15,.4)` + 4px backdrop-blur; panel `--radius-xl` + `--shadow-lg`; enter: 160ms fade + 8px rise (no bounce); uniform header/body/footer padding; footer buttons right-aligned primary-last; Esc/overlay-click preserved as-is |
| **Sidebar** | Active item: `--accent-dim` pill + accent text + 2px inset accent bar (no full-width fill); inactive hover `--bg-3`; icon 18px optical grid; section labels `--fs-xs` muted uppercase; smooth width transition already present — keep |
| **Topbar / PosTopBar** | Hairline bottom border, remove drop shadow; glass tokens already exist → `--glass-bg` + saturate blur for sticky state only; consistent 8px control gaps; extract its inline styles |
| **Hover/focus states** | Sweep: every interactive element gets exactly one hover response (bg shift ≤ 4% luminance) + the 4.1 focus ring; remove scale/transform hovers except press states |
| **Empty states** | One `<EmptyState icon title hint action?>` component (small 20px muted icon, one-line title, one muted hint, optional ghost action) replacing per-page ad-hoc "No data" divs |
| **Loading states** | Skeleton shimmer (1.4s, `--bg-3`→`--bg-4`) for tables/cards/dashboard tiles; buttons per above; never full-page spinners for partial loads; existing 0.8s `spin` kept for POS-blocking ops only |
| **Toasts/badges** | Status chips: `--*-dim` bg + status text, `--radius-sm`, 11px medium — consistent across invoice status, sync state, stock alerts |

## 4.3 Mobile/responsiveness pass

- Audit at 360/390/768/1024 (breakpoints exist at 768/1024): tables → horizontal scroll with sticky first column (never squashed columns); modals → full-width sheets ≤ 480px (slide-up 200ms); touch targets ≥ 44px on POS counter (qty steppers, tender chips); sidebar → existing drawer behavior kept, overlay per modal spec; `--zoom` display-size feature respected (test at 0.9/1.1).

## 4.4 Engineering approach (how, without breaking anything)

1. **Tokens first** (4.1) — one PR, app-wide effect, trivially revertible.
2. **Inline-style extraction, opportunistic:** when a 4.2 PR touches a component, move its `style={{}}` visual props into classes; do NOT do a big-bang extraction (churn risk, no user value).
3. **No DOM restructuring** — selectors and class names keep working; component tests (28 files in `src/__tests__/`) must pass untouched except snapshot refreshes.
4. `index.css` reorganized in place with section banners (tokens / base / components / pages / print) — file split deferred, not required for the outcome.
5. Print CSS (`ThermalReceipt`, Phase-1 templates) explicitly excluded from the sweep — print output is byte-frozen.

## 4.5 Phase 4 logging & tests

Logging: none needed beyond existing — visual pass adds no events (optionally log `display_density_changed` if a compact-mode toggle is added later; out of scope).

Tests (exit gate):
- All existing component/unit tests green with only snapshot updates; **zero test logic changes** (proves no behavior drift).
- New `tokens.test.js`: every color/duration/radius used in `index.css` resolves to a token (regex sweep — blocks future hardcoding).
- `EmptyState` + skeleton component tests.
- Playwright visual regression: screenshot baseline per page at 390px and 1280px before the pass; after each PR, diff review is the merge gate (intended changes approved, layout shifts rejected).
- Axe/a11y smoke: focus-visible rings present, contrast ≥ 4.5:1 for text tokens (the darkened `--text-muted: #555` already passes; verify status colors on dim backgrounds).
- Manual QA script: full POS sale → checkout → print, on desktop + 390px, per business-type mode (Phase 2) — flows must be pixel-different, behavior-identical.

**Rollout:** ship 4.1 alone first (biggest win, smallest risk) → component PRs in the 4.2 order (buttons/tables/forms touch everything — do them early) → mobile pass → one pilot week before default. No feature flag needed (CSS-only), but tag a rollback release.

---

## Migration Plan (cumulative, all reversible)

| # | Migration | Phase | Risk |
|---|---|---|---|
| 1 | `add_invoice_print_fields` — line items: `mrp`, `expiry_date`, `attributes JSON`; invoices: `invoice_title`, `round_off` (all NULL) | 1 | None — additive, payload falls back for old rows |
| 2 | `add_business_types` — `business_settings.business_types JSON`, backfill `[template_key]` | 2 | None — `template_key` remains authoritative primary |
| 3 | `add_invoice_print_template` — `invoices.print_template NULL` | 3 | None |

All follow existing universal-compatibility conventions (SQLite + Postgres), get `uid` sync coverage via existing `sync_map` model registration, and RLS inherits from table policies (no new tables → no new policies; verify with existing `test_rls_postgres.py` extension).

## Rollout Plan

1. **Phase 1 behind flag** `invoice_templates_v1` in template config `workflows` (config-over-code, per business): internal → 10 pilot businesses (mix GST/non-GST) → watch `template_fallback_used`, `pdf_failed`, `gst_field_mismatch` rates → default-on. Old print path stays as instant fallback.
2. **Phase 2**: new registrations get multi-type picker first; existing businesses opt in from Settings ("Add business type"). Thermal parity snapshot gate blocks release if supermarket output drifts by one character.
3. **Phase 3**: share/PDF per-business opt-in; public link requires explicit enable.
4. Each phase ends with: full regression (`run_tests`), pilot feedback, log-dashboard review of the Phase's new events before the next begins.

## Build Order Summary

| Phase | Ships | Testable outcome |
|---|---|---|
| **1** | Payload contract + registry + Classic + Modern + viewer + preferences + logging | Any invoice: switch/print/PDF, data provably immutable |
| **2** | Multi-type profiles + adaptive counter + 13 vertical configs + thermal on registry | Each business type bills its own way; supermarket byte-identical |
| **3** | Server PDF + share + duplicate + credit note + per-invoice override + A5/service/KOT | Invoice becomes a distribution channel |
| **4** | Token refinement + component polish + empty/loading states + mobile audit (CSS-only, no redesign) | Same app, premium feel; all existing tests green with snapshot-only updates |
