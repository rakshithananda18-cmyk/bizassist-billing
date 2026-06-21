# BizAssist — Detailed Build Plan: Next 3 Phases (agent-ready)

*June 2026 · Hand this to any agent/dev. Self-contained build spec for Phase 1B (finish Billing + per-vertical customization), Phase 2 (Purchase/OCR auto-entry), Phase 3 (Connections + Ordering). Read `backend/FOUNDATION.md` and `BIZASSIST_ECOSYSTEM_MASTER_PLAN.md` first — they define the conventions and the "why".*

---

## 0. Where we are (context for the agent)

**Strategy (do not deviate):** billing-first painkiller; AI is a *parked, paid add-on* (already built + tested, gated by plan — do NOT prioritize it). The USP is the one-app B2B ecosystem; connections share *the deal, not the books*. Every business is scoped by `business_id`. Money/stock are **append-only**. Money math is **deterministic SQL, never AI**. Migrations are **additive + nullable**. Routes are thin; logic lives in **command handlers / domain services** (modular monolith, not microservices).

**Already built & green (404+ tests):**
- `database/models.py` — `StockLedger` (append-only stock truth), `ProductBarcode` (one product → many barcodes), universal `Product`/`Invoice`/`InvoiceLineItem` fields incl. GST `reverse_charge`, and `Product.attributes` (JSON escape-hatch). Migrations through `f3b8c1e6a2d7`.
- `services/stock_ledger.py` — `record_movement` (append-only) / `current_stock` / `rebuild_inventory_cache`.
- `services/product_barcode.py` — `resolve_barcode` / `add_barcode` (conflict-safe) / `set_primary` / `deactivate`.
- `services/billing.py` — **`create_sale_invoice`** command: atomic invoice + lines + `sale` stock movements; deterministic GST (intra CGST+SGST / inter IGST, MRP-inclusive, per-line tax, round-off); idempotent on invoice number; status from `paid_amount`; non-stock items skip stock.
- `routes/sales.py` — `POST /sales`, `GET /sales/products/search`, `GET /sales/barcode/{code}`, `GET /sales/{invoice_no}`.
- Tech stack (decided, see `BIZASSIST_TECH_ARCHITECTURE.md`): React+Vite PWA · FastAPI · PostgreSQL (+ Alembic) · SQLCipher offline later · SSE realtime · Razorpay · WeasyPrint PDF · Groq+MiniLM AI.

**Conventions every task MUST follow** (from FOUNDATION.md): one tenant key `business_id` on every query; append-only money/stock (corrections = new rows); one command = one atomic transaction + idempotency key; lower-level services don't commit (compose in the command's txn); additive migrations; ship tests incl. negative scoping cases.

---

## 1. The Business Template System — customization per vertical (the centerpiece of Phase 1B)

> **Answer to "can each business type be different?": yes, fully — via config, not forks.** Medical, restaurant, supermarket, textile etc. each get their own labels, fields, tax/printing defaults, and workflows. The data model already fits all of them (universal columns + `Product.attributes` JSON). This section is a complete spec; it is referenced by every UI screen in Phase 1B.

### 1.1 Principle
**Config-over-code (Strategy pattern).** One JSON template per business type defines how the app *looks and behaves*. The UI renders forms/labels/screens dynamically from the template. Adding a new vertical = one JSON file + (rarely) one workflow component — **no schema change, no code fork.** This is what makes the product "compatible to all businesses" *and* feel native to each.

### 1.2 Data model (additive)
- `business.business_type` (already specced) — the chosen vertical key.
- **New table `business_settings`** (one row per business): `business_id` (unique), `template_key` (the vertical), `overrides` (JSON — owner's per-setting overrides), `created_at`, `updated_at`. The *resolved* config = template defaults deep-merged with `overrides`.
- No other schema change — vertical fields ride in `Product.attributes` / existing columns.

### 1.3 Template config schema (`backend/business_templates/<key>.json`)
```jsonc
{
  "key": "pharmacy",
  "label": "Pharmacy / Medical",
  "terminology": {                      // dynamic labels across the UI
    "customer": "Patient", "product": "Medicine", "bill": "Bill", "supplier": "Distributor"
  },
  "billing": {
    "default_invoice_type": "B2C",
    "tax_inclusive_default": true,       // retail MRP-inclusive
    "entry_mode": "search",              // "search" | "barcode" | "menu"
    "payment_modes": ["cash","upi","card","credit"],
    "eway_threshold": 50000,
    "allow_returns": true
  },
  "inventory": {
    "track_batch": true, "track_expiry": true, "track_serial": false,
    "loose_qty": false, "default_uoms": ["Strip","Bottle","Box","Nos"],
    "reorder_default": 10
  },
  "product_fields": [                    // which fields the product form shows/requires
    {"field":"name","required":true},
    {"field":"hsn_sac","label":"HSN","required":true},
    {"field":"mrp","required":true},
    {"field":"barcode"},
    {"attr":"salt","label":"Salt / Composition"},
    {"attr":"drug_schedule","label":"Drug Schedule","type":"enum","options":["","G","H","H1","X"]},
    {"attr":"manufacturer"}
  ],
  "invoice_layout": "a4_tax_invoice",    // or "thermal_58mm", "thermal_80mm"
  "workflows": ["expiry_register"],       // optional vertical modules to enable
  "ai_pack": "available"
}
```

### 1.4 The four verticals the owner named (concrete configs)

| Aspect | **Supermarket / Kirana** | **Pharmacy / Medical** | **Restaurant / Café** | **Textile / Garments** |
|---|---|---|---|---|
| terminology | Customer / Product / Bill | Patient / Medicine / Bill | Customer / Item / KOT+Bill | Customer / Product / Bill |
| entry mode | **barcode**-first | search-first | **menu**-first (tap dishes) | search / barcode |
| tax inclusive | yes (MRP) | yes (MRP) | yes (menu price incl.) | often no (add GST) |
| loose/weighed qty | **yes** (kg/g) | no | no (portions) | no |
| track batch/expiry | optional | **yes (mandatory)** | no | no |
| track serial | no | no | no | optional |
| variants | no | no | no | **yes (size×colour matrix)** |
| key `attributes` | — | salt, drug_schedule, manufacturer | is_veg, portion, prep_station | size, colour, fabric, brand |
| invoice layout | thermal 80mm | A4 tax invoice | thermal (KOT + bill) | A4 / thermal |
| special workflow | weighing-scale input | expiry register, schedule-H log | **tables + KOT** (Phase later) | **variant matrix entry** |
| units | Nos, Kg, g, Pack | Strip, Bottle, Box | Plate, Half, Full | Piece, Metre, Set |

> Ship **8 templates** in Phase 1B: `supermarket`, `pharmacy`, `restaurant`, `textile`, `wholesale`, `hardware`, `services`, `general`. The four above are fully specced; the rest reuse the same schema. Restaurant **tables/KOT** and textile **variant matrix** are *optional workflow components* — stub them in 1B (config flag) and build the heavy versions only if the pilot needs them.

### 1.5 Backend deliverables (Phase 1B)
- `backend/business_templates/*.json` — the 8 configs above.
- `services/business_template.py` — loader: `get_template(key)`, `resolve_for(business_id, db)` (template ⊕ overrides), `validate_overrides`, `attributes_schema(key)` (for form rendering + validation). Pure, cached, unit-tested.
- Migration: `business_settings` table (additive).
- Endpoints (`routes/business.py`):
  - `GET /business/templates` → list of `{key,label}` for the signup picker.
  - `POST /business/setup` `{template_key}` → creates/updates `business_settings`.
  - `GET /business/config` → the **resolved** config for the logged-in business (the frontend's source of truth for labels/fields/defaults).
  - `PATCH /business/config` → owner overrides (e.g. turn batch tracking off).
- `create_sale_invoice` already accepts `tax_inclusive`; the route should default it from the business config when the client doesn't send it.

### 1.6 Frontend deliverables (Phase 1B)
- On signup → **business-type picker** (reads `GET /business/templates`).
- A `useBusinessConfig()` hook that loads `GET /business/config` once and provides labels + field schema app-wide.
- **Dynamic product form**: renders fields from `template.product_fields` (core columns + `attr:` rows → `Product.attributes` JSON), with type/required/enum from the schema.
- **Dynamic labels** everywhere (`t('customer')` → "Patient" for pharmacy).
- **Counter entry mode** switches by config: barcode-first (supermarket), search-first (pharmacy), menu grid (restaurant).
- Settings screen to flip overrides.

### 1.7 Tests (Phase 1B, template)
`test_business_template.py`: each of the 8 templates loads + validates; `resolve_for` merges overrides; pharmacy requires batch/expiry; restaurant marks items non-stock; textile exposes variant attrs; `GET /business/config` returns resolved config scoped to the caller.

### 1.8 Guardrails
- Templates change **presentation + defaults**, never the money math or scoping. A pharmacy invoice and a textile invoice run through the *same* `create_sale_invoice`.
- Vertical fields go in `attributes` — **never** add a column per vertical.
- Unknown template → fall back to `general`. Owner overrides never bypass GST validity.

---

## 2. PHASE 1B — Finish the Billing Painkiller (+ customization) · ~3–4 weeks

**Goal:** a pilot business (and a pharmacy/restaurant demo) can run a full day end-to-end, and the app *feels native* to its vertical. This completes the sellable painkiller.

**Deliverables (each = its own task, sequence top→down):**

1. **Business Template System** — §1 in full (backend configs + loader + endpoints + dynamic UI). *Do this first; the UI below depends on it.*

2. **Sales Counter UI** (`Sales.jsx`) — keyboard/barcode-first, **template-aware** entry mode. Flow: search/scan item (`GET /sales/products/search`, `GET /sales/barcode/{code}`) → qty (loose qty if config) → live GST + total → payment mode → **Save** (`POST /sales`) → print/share. Optimistic UI; **never block on network/AI**; `Enter` finalizes; hold/resume a bill. Target: 5-line bill < 45s.

3. **Product / Item management UI** — list + dynamic create/edit form (template fields), barcode add (multi), opening stock (writes a `stock_ledger` `opening` movement). Backend: `routes/products.py` (CRUD, scoped) + a `CreateProduct`/`UpdateProduct` service; reuse `product_barcode`.

4. **Customer / Supplier management** — CRUD over existing `Customer`/`Vendor`; dues shown from invoices/payments. `routes/parties.py`.

5. **Payments & dues** — `RecordPayment` command (append-only; updates invoice `paid_amount` + status via a *new payment row*, never overwriting history). `routes/payments.py`: `POST /payments`, `GET /parties/{id}/ledger`. Tests: partial → Partial, full → Paid; idempotent.

6. **Returns / Credit notes** — `CreateCreditNote` command: reverses a sale (new credit-note invoice + `return_in` stock movements). Append-only (never edits the original). UI on an invoice → "Return". Tests: stock restored, original untouched.

7. **Invoice PDF + share** — WeasyPrint HTML templates **per `invoice_layout`** (A4 tax invoice, thermal 58/80mm). `GET /sales/{invoice_no}/pdf`. Pull business letterhead/GSTIN/signature + UPI QR. WhatsApp/share link (deep link first; Business API later). E-way fields captured when total > ₹50k (PDF includes them).

8. **Switch-in import** — `routes/import.py` + `services/import_data.py`: CSV/Excel → item master, customers + opening dues, opening stock (as `stock_ledger` `opening` movements). Reuse `column_mapper`/`parser`. Preview → confirm → commit. Tests: messy CSV → products + opening stock; idempotent re-import.

9. **Reports** — `routes/reports.py`: day/period sales, **GSTR-1-ready** GST summary (per-HSN, you have per-line tax), stock-on-hand (from ledger), dues. Read-only, scoped.

10. **Staff roles (RBAC)** — `User.role` per business (owner/cashier); a permission dependency. Cashier: bill yes; delete-invoice / change-price / see-profit no. Tests: negative permission cases.

**Acceptance criteria (Phase 1B "done"):**
- Pilot wholesaler runs a full day parallel to his old system, his catalogue imported.
- A **pharmacy** demo (batch/expiry forms, "Patient" labels, MRP-inclusive) and a **restaurant** demo (menu-grid entry, non-stock items) both work from the *same* code via config.
- Bill → stock deducts → GST correct → PDF prints (thermal + A4) → share works.
- All new tests green + full suite stays green.

**Guardrails:** lead with billing (AI stays behind plan gate); billing path offline-capable + optimistic; money deterministic + append-only; every query scoped; additive migrations only.

---

## 3. PHASE 2 — Purchase + Stock Auto-Entry (kill manual entry on the buy side) · ~2–3 weeks

**Goal:** the owner adds a supplier delivery by **snapping the bill**, not typing — the second painkiller. Implements the **Detect → Map → Confidence → Review → Commit** pipeline (Tech doc).

**Deliverables:**

1. **Purchase data model** (additive): `purchase_invoices` + `purchase_invoice_items` (mirror sales; supplier_id, number, dates, totals, GST, status). Distinct from `purchase_orders` (the *order*) — this is the *received bill*.

2. **OCR ingestion** — `services/purchase_ocr.py`: photo/PDF → text (Tesseract/cloud OCR or vision-LLM; reuse `pdf_parser`). Extract supplier, invoice no/date, line items (name, qty, rate, HSN, tax, batch/expiry).

3. **Classify + match** — reuse the router/classification + embeddings: map supplier item names → the buyer's `Product` master (fuzzy + MiniLM); suggest HSN/tax/category for new items; **per-line confidence score**.

4. **Review UI** — shows extracted lines with confidence; high-confidence pre-ticked, low flagged; user confirms/corrects, maps to existing products or creates new ones, captures **new barcodes** (→ `product_barcode.add_barcode`).

5. **`AcceptSupplierInvoice` command** — on confirm only: writes `purchase_invoice` + items + `stock_ledger` `purchase` movements; creates/updates products; adds barcodes; updates cost price. Atomic + idempotent (supplier+number). **Never auto-commits low-confidence financial data.**

6. **UoM conversion** — purchase in `purchase_unit` (carton) → stock in `unit` (pieces) via `conversion_factor` (already on `Product`).

7. **Reorder suggestions** — low-stock list with last purchase price/supplier (read-only; the AI advisor enhances later).

**Endpoints:** `POST /purchases/upload` (→ extracted+matched draft), `POST /purchases/confirm` (→ AcceptSupplierInvoice), `GET /purchases`, `GET /purchases/{id}`.

**Tests:** `test_purchase_ocr.py` (messy invoice → mapped lines + confidence), `test_purchase_commit.py` (confirm → purchase invoice + exact stock movements + new barcodes; low-confidence blocks auto-commit; idempotent).

**Acceptance:** snap a real supplier bill → review → stock + cost + barcodes updated; nothing commits without human confirm.

**Guardrails:** confirm-before-commit is mandatory; reuse the multi-barcode + stock-ledger foundation; additive migrations; template-aware (pharmacy purchase captures batch/expiry).

---

## 4. PHASE 3 — Business Connections + Ordering (the network begins) · ~3–4 weeks

**Goal:** the USP foundation — one business connects to another by a **seller-issued code**, sees only a **policy-scoped slice**, and places orders. *Connections share the deal, not the books.* (Invoice→stock sync between connected parties is Phase 4; Phase 3 = connection + order lifecycle + the security boundary.)

**Deliverables:**

1. **Data model** (additive): `connections` (seller_business_id ↔ buyer_business_id, price_tier, credit_limit, outstanding_balance, status), `connection_codes` (seller-issued, single-use, expiring), `orders` + `order_items` (relational), `shared_ledgers` (append-only). `business.public_id` (the **BizID**, random `BA-XXXXXX`).

2. **BizID issuance** — assign on signup; `GET /bizid` (self), `GET /bizid/{code}` (public-profile-only lookup: name, type, city, accepts_orders — **never** transactional data).

3. **Connection flow** — `POST /connections/code` (seller generates), `POST /connections/redeem` (buyer enters code → `connections` row, consent-gated), `POST /connections/{id}/revoke`. Either side can initiate; seller controls who links.

4. **Per-connection visibility policy + the ONE sharing serializer** (§ security): the seller sets, per connected buyer/tier: catalogue scope (all/selected/category), price tier shown, stock visibility (exact/band/hidden), credit terms. A **single** `SharingSerializer` every cross-business read passes through — no endpoint hand-rolls cross-business queries. **Postgres RLS** as the second wall.

5. **Buyer ordering** — `GET /catalog/{seller_bizid}` (policy-scoped), `POST /orders` (buyer places). Template-aware (a buyer browsing a pharmacy distributor sees medicine fields).

6. **Seller order inbox** — `GET /orders?role=seller` (pending), `POST /orders/{id}/accept|edit|reject`. (Convert→invoice + stock sync = Phase 4.)

7. **Realtime** — SSE events `order.created` (→ seller), `order.status` (→ buyer); reuse the existing SSE infra.

**Tests (security-critical — the product lives here):** `test_connections.py` — code redemption creates the pipe; expired/reused code rejected; **buyer A cannot read seller B's other customers / sales / margins / cost / hidden stock** (the boundary); revoke closes the pipe but keeps both rooms private; order → seller inbox; BizID lookup leaks nothing.

**Acceptance:** pilot wholesaler connects one distributor (or 3 retailers); buyer sees only the allowed slice; an order reaches the seller's inbox in real time; all negative-isolation tests pass.

**Guardrails (non-negotiable):** shared transaction, never shared books; one central sharing serializer + RLS; consent-gated, single-use, throttled codes; random BizIDs (no enumeration); append-only ledgers. A single cross-business leak is an extinction event — treat §6 of the master plan as law.

---

## 4.5 Future Phase — Payment Auto-Reconciliation (Based on Adoption)

**Goal:** Automate payment confirmation tracking for remote invoices and POS billing based on merchant adoption.

**Proposed Roadmap:**
1. **Zero-Fee Direct UPI QR (Offline POS - Default):** Continue using peer-to-peer static UPI QRs as the default to avoid Merchant Discount Rate (MDR) transaction fees. Verification remains manual by cashiers (or via Paytm/PhonePe soundbox notification checks).
2. **Automated Payment Links (Payment Gateway Integration):**
   - Provide **Razorpay / PhonePe PG** integration options for remote/wholesale merchants.
   - Allow merchants to save PG API Keys in `BusinessSettings`.
   - Generate dynamic PG checkout payment links (`https://rzp.io/...`) for unpaid invoices shared via WhatsApp.
   - Create a webhook endpoint `/api/webhooks/payments` to receive confirmation callbacks from the gateway, automatically marking invoices as `Paid` and writing balancing ledger postings.

---

## 5. Cross-cutting rules for every agent on every task
1. **Scope every query by `business_id` from the verified token.** Cross-business reads only via an accepted connection + the sharing serializer.
2. **Append-only money/stock.** Corrections = new rows (credit note, signed adjustment). Never overwrite an amount.
3. **One command = one atomic transaction + idempotency key.** Lower-level services don't commit.
4. **AI never moves money.** Totals/tax/stock are deterministic SQL. OCR/classification is confirm-before-commit.
5. **Additive, nullable, backward-compatible migrations.** One revision per change; keep the full suite green.
6. **Templates customize presentation/defaults only** — never the money math or scoping. Vertical fields ride in `attributes`.
7. **Thin routes, fat services/commands.** Modular monolith; no microservices.
8. **Ship tests with every task, including negative scoping/permission cases.**

## 6. Suggested parallelization for multiple agents
- **Agent A (backend core):** §1 template system → Phase 1B items 3–6, 8–10 (products, parties, payments, returns, import, reports, RBAC).
- **Agent B (frontend):** §1.6 dynamic config UI → Sales Counter (1B.2) → product/party screens → reports UI.
- **Agent C (documents/integrations):** Invoice PDF per layout (1B.7) → WhatsApp/share → e-way fields.
- **Then converge** before Phase 2 (purchase/OCR) and Phase 3 (connections), which are more sequential and security-sensitive — fewer agents, more review.

> Definition of done for the whole plan: the pilot runs his business on it daily across his vertical; a second vertical demos from the same code via config; a connected partner can order while seeing only the allowed slice — all with the full test suite green.
