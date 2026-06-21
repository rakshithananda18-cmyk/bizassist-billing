# `core/` — the BizAssist Billing Ecosystem

This package is **the product's core**: billing, stock, catalogue, and (soon)
purchase, connections, and B2B orders. It is the painkiller the business owner
actually wants. It is deliberately kept **separate from the AI/legacy code**
(which lives in `services/`, `routes/ask*`, etc.) and is wired to the AI
dashboard only at the very end — AI is a paid add-on, not the core.

## Why a separate folder?

So the foundation stays clear and organised as it grows. New domains get a new
folder **here**, never bolted back onto `services/`. The split also makes the
"wire AI last" plan trivial: `core/` has zero dependency on the AI code.

## Layout (one folder per domain module)

```
core/
  models.py   the billing ecosystem's OWN tables (StockLedger, ProductBarcode,
                BusinessSettings, …) — defined here so the schema is organised by
                domain, but registered on the SAME shared Base (see below)
  api/        the ecosystem's HTTP layer — every core route, aggregated into one
                core_router; the app mounts billing with one include_router line
                sales.py    POST /sales, product/barcode search, get invoice
                business.py GET/POST/PATCH /business/* (template config)
  stock/      append-only stock ledger — the inventory truth
                ledger.py: record_movement / current_stock / rebuild_inventory_cache
  catalog/    product barcodes — one product → many codes (packaging revisions)
                barcode.py: resolve_barcode / add_barcode / set_primary / deactivate
  billing/    sale invoices — deterministic GST, atomic command handlers
                commands.py: create_sale_invoice
  templates/  per-business-type config (medical / restaurant / supermarket / …)
                loader.py + configs/*.json
  purchase/   (Phase 2)  supplier invoices + OCR auto-entry
  connection/ (Phase 3)  BizID, connection codes, sharing policy
  order/      (Phase 3)  B2B orders
```

Each module exposes its public API from its `__init__.py`, so callers import
`from core.billing import create_sale_invoice` or `from core.stock import ledger`.

## Tables: organised by domain, ONE database

Core owns its tables in `core/models.py` (separate file = clear ownership), but
they register on the **same** SQLAlchemy `Base`/metadata as the shared tables in
`database/models.py`. This is a modular monolith, **not** separate databases:

- A sale writes shared `Invoice` + `InvoiceLineItem` **and** core `StockLedger`
  in ONE atomic transaction, with foreign keys between them.
- The AI advisor reads the shared `Invoice`/`Product`/`Customer` tables.

Splitting into physically separate databases would break those FKs and that
atomicity — so we split the *files*, never the database. The shared mixins live
in `database/db.py` (a model-free module) so `core/models.py` and
`database/models.py` can both inherit them with no import cycle; `database/models.py`
imports `core/models.py` at the bottom purely to register the core tables on the
shared metadata.

Bucket guide:
- **core-only** → `core/models.py` (StockLedger, ProductBarcode, BusinessSettings)
- **shared by core + AI** → `database/models.py` (User, Product, Invoice, Inventory, Customer, Vendor)
- **AI-only** → `database/models.py` for now (BusinessFact, Feedback, QueryOverride, …)

## Shared layers (used by BOTH core and AI — stay central)

```
database/models.py   the schema (shared)
database/db.py       the session
services/auth.py     auth
```

## Migration note — `services/` shims

The original implementations lived in `services/stock_ledger.py`,
`services/product_barcode.py`, `services/billing.py`. Those files are now **thin
compatibility shims** that re-export from `core/` so nothing breaks during the
move. New code should import from `core/`. Once no caller uses the old paths,
the shims can be deleted.

## Conventions

See [`../FOUNDATION.md`](../FOUNDATION.md). In short: one tenant key
`business_id` on every query; money & stock are append-only (corrections are new
rows, never overwrites); one command = one atomic transaction (the command
handler owns the commit, lower helpers compose without committing); migrations
are additive/nullable; routes stay thin, commands stay fat.
