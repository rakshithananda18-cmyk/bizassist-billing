# BizAssist Backend — Foundation & Conventions

*The rulebook for building BizAssist cleanly. Read this before adding any feature. It keeps the base strong as we stack billing → purchase → connections → sync → AI on top. Decisions trace to `../docs/plans/BIZASSIST_ECOSYSTEM_MASTER_PLAN.md` (§D-numbers) and `../docs/ARCHITECTURE.md`.*

---

## 1. The shape: one modular monolith

One backend, one database, one app — split into **modules with clean boundaries**. Not microservices (Tech doc §2.16). A module owns its tables, its service logic, and its tests, and talks to other modules through clear functions — never by reaching into another module's internals.

**Modules (built incrementally — not all exist yet):**

| Module | Owns | Status |
|---|---|---|
| `product` / `catalog` | product master, HSN/tax defaults, **multi-barcode** | exists + ✅ barcodes (`core/catalog/barcode.py`) |
| `customer_supplier` | customers, vendors, dues | exists (`Customer`, `Vendor`) |
| **`stock`** | `stock_ledger` (append-only truth), inventory cache | ✅ **foundation built** (`core/stock/ledger.py`) |
| `billing` | sales invoices (reuse `Invoice`), payments, returns | ✅ Phase 1 (`core/billing/commands.py`) |
| `templates` | per-vertical config (labels, fields, defaults, workflows) | ✅ Phase 1B (`core/templates/`, `business_settings`) |
| `purchase` | supplier invoices, OCR→commit pipeline | Phase 2 |
| `connection` | BizID, connection codes, sharing policy | Phase 3 |
| `order` | B2B orders between connected businesses | Phase 3 |
| `shared_invoice` | invoice sync + shared ledger | Phase 4 |
| `ai_advisor` | the existing AI engine (router, insights, agent) | exists |
| `subscription` | plans, feature gating | Phase 5 |
| `security_audit` | scoping guard, audit log, signing (later) | cross-cutting |

> **The billing ecosystem lives in `core/`** — one folder per domain module (`core/stock/`, `core/catalog/`, `core/billing/`, then `core/templates/`, `core/purchase/`, `core/connection/`, `core/order/`). It is deliberately kept SEPARATE from the AI/legacy code in `services/`, and is wired to the AI dashboard only at the very end (AI is a paid add-on, not the core). See `core/README.md`.
>
> The old `services/stock_ledger.py`, `services/product_barcode.py`, `services/billing.py` are now **thin shims** that re-export from `core/` (nothing broke in the move). New code imports from `core/`. Shared layers (`database/models.py`, `database/db.py`, `services/auth.py`) stay central and serve both core and AI.
>
> Entry point: the FastAPI app is still defined in `main_groq.py` (legacy name), but `app.py` re-exports it under the neutral `app:app`, which is preferred going forward.

---

## 2. The non-negotiable conventions (every feature inherits these)

### 2.1 Tenant scoping — one key, never trust the client
- Every business is identified by `business_id` (decision **D1** — no separate tenants table).
- **Every query is scoped:** `WHERE business_id = :bid`. The `business_id` comes from the **verified auth token only** — never from a request body/param.
- Cross-business reads (Phase 3+) go **only** through an accepted `connection` and **only** the shared slice, via the single sharing serializer. A query that could leak a partner's private data must be impossible to express.
- *Rule:* if you write a query without a `business_id` filter, it's a bug.

### 2.2 Money & stock are APPEND-ONLY (decision D2)
- Invoices, payments, stock movements, ledger entries are **never updated or deleted**. A correction is a **new reversing entry** (e.g. a credit note, or a signed negative `adjustment` in the stock ledger).
- The `stock_ledger` is the reference implementation — study `core/stock/ledger.py`. Stock changes only by `record_movement()`; `inventory.stock` is a disposable cache you can always `rebuild_inventory_cache()`.
- *Rule:* never `UPDATE` a financial/stock row's amount. Add a new row.

### 2.3 Command handlers own transactions
- Every money-changing action is **one explicit command**: `CreateSaleInvoice`, `AcceptSupplierInvoice`, `PlaceOrder`, etc. (Tech doc §2.16). A command:
  1. opens one DB transaction,
  2. validates,
  3. writes the invoice/payment **and** the stock movement(s) **together**,
  4. commits atomically (all-or-nothing), and
  5. is **idempotent** (a retried command with the same idempotency key does nothing twice).
- Lower-level services (like `stock_ledger.record_movement`) **do not commit** — they compose inside the command's transaction.
- *Rule:* routes stay thin; they call a command/service. No business logic in route functions.

### 2.4 AI never decides money (decision §6)
- Totals, tax, stock counts are **deterministic SQL**. The AI only *advises*; its *actions* stay preview → confirm → audit (`ActionLog`).
- The OCR/classification pipeline follows **Detect → Map → Confidence → Review → Commit** and **never auto-commits low-confidence financial data** — a human confirms before stock/money moves.

### 2.5 Migrations are additive & safe
- One Alembic revision per change; **additive, nullable-by-default, backward-compatible** (chained off the current head). This is what keeps the ~385 tests green. New table or new nullable column — never a destructive change on a live DB.

### 2.6 Everything is tested & traceable
- Each module ships tests, including **negative isolation tests** (no cross-business/connection leak).
- **Named logger per module** (`logging.getLogger("bizassist.<area>")`). **INFO** on every state change with the keys to trace it (`business_id`, invoice no., ids, amounts) using the tagged style (`[STOCK]`, `[BILLING]`, …) so any action is greppable end-to-end; **DEBUG** on the flow (inputs, computed values, branch taken); errors with `exc_info` — never a silent `except`.
- **Closing any phase/task → run `../PHASE_COMPLETION_CHECKLIST.md`** (the Definition of Done): tests green/written + named, info+debug loggers added, master plan §10.0 tracker + §10.1 smartest-app note updated. A feature is "done" only when its named test passes.

---

## 3. Where to put a new thing
- **New table** → model in `database/models.py` + an Alembic revision (additive).
- **New domain logic** → a module under `core/<domain>/` (own folder, public API in its `__init__.py`, append-only/scoping conventions). AI/legacy-only helpers stay in `services/`.
- **New money action** → a command handler (validate → write data + ledger together → commit → idempotent).
- **New HTTP endpoint** → a thin route in `routes/` that calls the service/command; scoped by the auth dependency.
- **New cross-business visibility** → extend the sharing policy/serializer, never a raw query.

---

## 4. Build order (Master Plan §10 — one thing per phase)
1. **Phase 1 — Billing** (sales counter, GST invoice, payments, returns, dues, stock deduction via the ledger, switch-in import). ← *building now*
2. **Phase 2 — Purchase + stock auto-entry** (OCR → Detect→Map→Confidence→Review→Commit).
3. **Hardening** — encrypted offline cache + outbox/delta sync + RLS.
4. **Phase 3 — Connections** (BizID, codes, per-connection sharing policy, ordering).
5. **Phase 4 — Invoice sync** (order→invoice→buyer stock-in, shared ledger).
6. **Phase 5 — AI Advisor** (paid gating).
7. **Phase 6 — Network** (reputation, signed+hash-chained ledger, financing).

Foundational from day one (not a phase): scoping, encryption-readiness, append-only, modular structure — i.e. everything in §2.

---

## 5. Status of the foundation
- ✅ `StockLedger` model + migration `d1f3a6c8e2b0` (append-only, D4).
- ✅ `core/stock/ledger.py` — the reference module (append-only + cache + rebuild).
- ✅ `ProductBarcode` model + migration `e2a4b7d9c1f5` + `core/catalog/barcode.py` — **one product → many barcodes** (companies revise packaging; old stock still scans). Scan resolves to one product; `Product.barcode` kept as the primary/display cache + legacy fallback.
- ✅ **Universal-compatibility fields** + migration `f3b8c1e6a2d7` — the catalogue/invoice schema now fits EVERY business type, and the GST-mandatory `reverse_charge` (Rule 46) was added. See §6.
- ✅ **`billing` module — `create_sale_invoice` command** (`core/billing/commands.py`): the reference command handler — one atomic transaction writes the `Invoice` + line items + a `sale` stock-movement per line; deterministic GST (intra CGST+SGST vs inter IGST, MRP-inclusive back-calc, per-line tax for GSTR-1, round-off); idempotent on the invoice number; status from `paid_amount`; non-stock items skip stock. Tested in `test_billing.py`.
- ✅ **`core/` reorg** — billing ecosystem moved into `core/` (one folder per domain); old `services/{stock_ledger,product_barcode,billing}.py` are now re-export shims; canonical importers point at `core/`. See `core/README.md`.
- ✅ **Schema organised by domain, one DB** — core's own tables live in `core/models.py` (StockLedger, ProductBarcode, BusinessSettings); shared tables stay in `database/models.py`. Both register on the SAME `Base`/metadata (modular monolith — atomic sale across shared `Invoice` + core `StockLedger`, FKs intact). Shared mixins moved to `database/db.py` (model-free) to avoid an import cycle; `database/models.py` bottom-imports `core/models.py` to register the core tables.
- ✅ **Billing wired from core** — all core routes live under `core/api/` (`sales.py`, `business.py`) and aggregate into one `core_router`; the app entry point does a single `app.include_router(core_router)` and never imports individual billing routes. To add a core endpoint, include it in `core/api/__init__.py` — the entry point doesn't change.
- ✅ Thin `POST /sales` route over the command (`routes/sales.py`) + product/barcode search endpoints.
- ✅ **Business Template System** (`core/templates/` + `business_settings` table + migration `a4c9d2e7b3f1`): config-over-code per vertical — 8 shipped templates (`supermarket`, `pharmacy`, `restaurant`, `textile`, `wholesale`, `hardware`, `services`, `general`). Loader does `get_template` / `resolve_for` (template ⊕ owner overrides) / `validate_overrides` (presentation-only guardrails) / `attributes_schema`. Endpoints in `routes/business.py`: `GET /business/templates`, `POST /business/setup`, `GET|PATCH /business/config`. `POST /sales` defaults `tax_inclusive` from the business config. Vertical fields ride in `Product.attributes` — **no schema change per vertical**. Tested in `test_business_template.py`.
- ⬜ Next: the keyboard/barcode-first, template-aware sales counter UI; product/parties management; payments + returns; invoice PDF.

---

## 6. One schema, every business type (universal compatibility)

Validated against the 16 GST Rule-46 mandatory fields and ERPNext's item-master patterns. The principle: **one `products`/`invoices` schema; each business type uses only the fields it needs; vertical-specific fields live in `Product.attributes` (JSON) so a new vertical needs NO migration.**

| Business type | Key fields it uses | Vertical extras (in `attributes`) |
|---|---|---|
| **Retail / supermarket** | `unit` (Kg/loose), `price_includes_tax` (MRP incl. GST), `mrp` | — |
| **Wholesale / distributor** | `purchase_unit` + `conversion_factor` (carton→pcs), `sku`, price tiers (Phase 3) | — |
| **Pharmacy** | `Inventory.batch_no`/`expiry_date`, line `batch_no`, `hsn_sac` | `drug_schedule`, `salt`, `manufacturer` |
| **Garments / footwear** | `variant_of` (+ parent), `brand` | `size`, `colour`, `fabric` |
| **Restaurant / café** | `track_inventory=False`, `category` | `is_veg`, `portion` |
| **Services** | `is_service=True`, `track_inventory=False`, SAC in `hsn_sac` | `duration`, `sac_group` |
| **Electronics** | `brand`, `manufacturer`, line `serial_no` | `imei`, `warranty_months` |

**GST compliance (Rule 46) — covered:** supplier & buyer GSTIN/address (`User` + `Customer` + `gstin_buyer`), invoice no.+date, `place_of_supply`, `hsn_sac`, qty+unit, per-line taxable value + CGST/SGST/IGST/Cess (tax computed **per line**, not on total), `total_amount`, **`reverse_charge`** (now added), e-invoice `irn`/`qr_code`. Signature is applied at PDF time. `round_off` handles final rounding.

**The escape hatch:** any field a future vertical needs goes into `Product.attributes` / line fields — never a schema fork. That is what keeps us "compatible to all businesses" without migration churn.

> The golden rule: **the ledger is the truth, money is append-only, every query is scoped, AI never moves money, and one command = one atomic transaction.** Keep those five and the base stays unbreakable.
