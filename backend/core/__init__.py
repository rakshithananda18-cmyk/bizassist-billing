"""
core/ — the BizAssist Billing Ecosystem (the product's core).
=============================================================
This package is the CORE product: billing, stock, catalogue, purchase,
connections, orders — the "painkiller" + the B2B ecosystem. It is deliberately
SEPARATE from the AI/legacy code (which lives in `services/`, `routes/ask*`,
etc.) and is wired to the AI dashboard only at the very end (AI is a paid
add-on, not the core).

Layout (one folder per domain module — add new domains here, never back in
`services/`):
    core/stock/      append-only stock ledger (the truth)
    core/catalog/    product barcodes (one product → many codes)
    core/billing/    sale invoices, payments, returns (command handlers)
    core/templates/  per-business-type config (config-over-code customization)
    core/purchase/   (Phase 2)  supplier invoices + OCR auto-entry
    core/connection/ (Phase 3)  BizID, connection codes, sharing policy
    core/order/      (Phase 3)  B2B orders

Shared layers stay central and are used by BOTH core and AI:
    database/models.py   the schema (shared)
    database/db.py       the session
    services/auth.py     auth

Conventions: see backend/FOUNDATION.md (one tenant key `business_id`,
append-only money/stock, one command = one atomic transaction, additive
migrations, thin routes / fat commands).
"""
