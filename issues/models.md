models.py
  ├── Mixins (reusable, composable)
  │     ├── BusinessOwnedMixin  → id, business_id, created_at, updated_at  (on every table)
  │     └── GSTFieldsMixin      → gstin, place_of_supply, cgst/sgst/igst amounts (on taxable docs)
  │
  ├── Existing tables (backward-compatible additions only)
  │     ├── Invoice             + customer_id (FK nullable), invoice_type, gstin_buyer, tax totals
  │     └── Inventory           + cost_price, unit, reorder_point, vendor_id (FK nullable), barcode
  │
  └── New tables
        ├── Customer            → proper entity for buyers (name, GSTIN, phone, state_code)
        ├── Vendor              → suppliers (same fields as Customer, different role)
        ├── Product             → catalogue with HSN/SAC, tax rates, selling/cost price
        ├── InvoiceLineItem     → line items per invoice (product, qty, unit, tax breakdown)
        ├── PurchaseOrder       → orders from vendors
        └── PurchaseOrderLineItem

repository.py  (new file — Dependency Inversion + Interface Segregation)
  ├── BaseRepository[T]         → get, get_by_business, create, update, delete, paginate
  ├── InvoiceRepository         → + get_overdue, get_by_customer, revenue_summary
  ├── CustomerRepository        → + get_with_outstanding, search_by_name
  ├── InventoryRepository       → + get_low_stock, get_expiring
  └── VendorRepository          → + get_with_pending_pos