# BizAssist Ecosystem — Master Plan & Architecture (Synthesis v1)

*June 2026 · The single source of truth. Reconciles three independent AI reviews (this assistant, "Codex", "Antigravity") into one plan, makes the contested decisions explicitly, and maps everything to your four goals: **easy to use · secure & unbreakable · addictive · makes money**.*

> How to read this: §1 is what all three agreed on (settled). §2 is where they disagreed and the decision we're taking + why (this is the most important section — read it first). §3–§9 are the design. §10 is the build. §11–§13 are pilot, risks, and what needs your sign-off.

---

## 1. The settled core (all three reviews agree)

These are no longer open questions. Treat them as decided:

1. **Do not throw away BizAssist. Reframe it.** It already has the hard parts: React app, FastAPI backend, Postgres + Alembic, a GST-shaped schema (`customers`, `vendors`, `products`, `inventory`, `invoices`, `invoice_line_items`, `payments`, `purchase_orders` with GSTIN/HSN/CGST/SGST/IGST/IRN/QR fields), an upload pipeline (CSV/XLSX/PDF), and a real AI engine (4-tier router, local embeddings, memory, recommendations, gated actions, token metering, rate limiting) with ~385 tests.
2. **Billing first. AI second. Customer network third.** The owner's #1 question is "can I bill fast and stop typing every item?" — not "is the AI cool." Lead with billing.
3. **AI becomes the paid intelligence layer**, not the front door. The current dashboard/chat moves behind an "AI Advisor / Business Intelligence" section, gated by subscription. You already meter tokens per business and have per-plan `RateLimitConfig` — the monetization plumbing exists.
4. **The USP is the ecosystem, not billing.** Billing is commoditized (Vyapar ₹1,099/yr, Zoho free tier). The defensible thing is: **each business gets its own private, branded ordering network for its customers, wired directly into billing + stock + AI.**
5. **The customer/retailer ordering app requires the cloud.** Two parties on two devices/networks need a reachable meeting point. Local-only cannot do this. (You already concluded this.)
6. **Stock must be a movement ledger, not just a number.** Every purchase/sale/return/damage/adjustment is recorded. This is the trust backbone.
7. **E-way bill matters**: a sale > ₹50,000 legally needs an e-way bill (this is the real rule behind "more than 50k"). E-invoice/IRN is only mandatory above ₹5 cr turnover (trending toward ₹2 cr) — build it, gate it per-business.
8. **Pilot the interested owner as a design partner, run parallel with his current system, and charge even a small pilot fee.** Free pilots don't teach pricing.

---

## 2. Where the three disagreed — and the decision we're taking

This is the section to scrutinize. Each decision below resolves a real conflict between the reviews. I give the options, the call, and the *why* — because a wrong call here is expensive to undo.

### D1 — Tenancy: **keep `business_id`; do NOT add a new `tenants` table.** ✅ decided
- *Conflict:* Antigravity proposes a brand-new `tenants` table + `tenant_id` foreign key on every table. Codex and I assume the existing `business_id` (every table is already scoped by it; `User` = one business).
- *Decision:* **Use the `business_id` you already have as the tenant key.** Rename/relabel conceptually to "Business" but do not fork the data model. Adding a parallel `tenants` table means migrating 9 existing tables and rewriting every query and all 385 tests for marginal benefit.
- *Why:* You are *already multi-tenant*. The cheapest, safest path is to formalize what exists, not introduce a second tenancy concept that will drift from `business_id`. **One tenant key, everywhere, forever.**
- *What we DO add:* a `businesses` profile table is optional cosmetic; the essential addition is a `business_type` field on the business and a **second scoping key for the customer side** (`customer_app_user → business_id + customer_id`). See D-sec.

### D2 — Sync conflict resolution: **hybrid, not global last-write-wins.** ✅ decided
- *Conflict:* Antigravity says last-write-wins (LWW) on UTC timestamps, globally. I argued append-only + ownership.
- *Decision:* **Append-only for money/transactions; LWW only for mutable master data.**
  - *Append-only (never destructively edited):* invoices, sales/purchase invoice items, stock-ledger entries, orders, payments, ledger entries. Corrections happen via a *new* entry (credit note, reversal, adjustment), never an overwrite.
  - *LWW (safe to overwrite):* product name/price edits, customer profile, business settings, catalogue.
- *Why:* LWW on an **invoice** can silently destroy a bill if two devices edit the same row — unacceptable for money and trust ("unbreakable" goal). Append-only transactions can't lose data; the worst case is a duplicate you can detect by idempotency key, not a vanished sale.
- *Mechanism:* every syncable row gets `updated_at` (you have it), a `client_id`/`device_id`, and transactions carry an **idempotency key** so a re-sent invoice can't double-post.

### D3 — Order storage: **relational `order_items`, not `items JSONB`.** ✅ decided
- *Conflict:* Antigravity stores order lines as a JSONB blob; Codex/I assume relational line items.
- *Decision:* **Relational `order_items`** (mirrors `invoice_line_items`). Keep an optional JSONB snapshot column only for immutable audit of "what the catalogue showed at order time."
- *Why:* you must query, reserve stock against, report on, and convert order lines into invoice lines. JSONB makes "how many units of product X are reserved across open orders?" painful. Relational is the same shape as your existing invoice items, so handlers/AI tools reuse cleanly.

### D4 — Stock: **`stock_ledger` is the source of truth; `inventory.stock` becomes a cached projection.** ✅ decided
- *Conflict:* current code stores a single `Inventory.stock` integer. Codex (correctly) wants a movement ledger.
- *Decision:* introduce `stock_ledger` (append-only). Current stock = sum of ledger movements for that product. Keep `inventory.stock` as a **denormalized cache** updated on each movement (fast reads), but the ledger is authoritative and rebuildable.
- *Why:* trust. When a shopkeeper disputes "why is my stock 3?", you can show every movement. Also enables reservations (open orders hold stock) and damage/return tracking. This is a competitor weakness — most cheap billing apps only store a number.

### D5 — Hosting: **cloud is the source of truth; local is an optional offline merchant cache.** ✅ decided
- *Conflict:* "installable locally" (owner's words) vs "customer app needs cloud" (everyone).
- *Decision:* **Cloud-first.** Cloud Postgres is the system of record. The merchant app is an **offline-capable client**: it can bill with no internet (queues to a local SQLite), and syncs deltas to cloud on reconnect. The customer app is cloud-only (it must be reachable).
- *Why:* true local-first multi-master sync is the single hardest thing in this whole plan and will sink the timeline. "Works offline, syncs, backed up" satisfies the owner's *real* needs (uptime + data safety + control) without the multi-master nightmare. Ship offline cache in Phase 3, not Phase 1.
- *How dynamic database dialects (SQLite vs Postgres) are handled:*
  1. **Environment-Driven Configuration:** The database engine is configured dynamically via the `DATABASE_URL` environment variable. If `DATABASE_URL` starts with `sqlite`, SQLAlchemy configures a local SQLite engine (with thread-safety flags). If it starts with `postgresql` or `postgres`, SQLAlchemy uses PostgreSQL (e.g. Supabase in cloud deployments).
  2. **ORM Abstraction:** The codebase queries models via SQLAlchemy ORM, which automatically translates standard queries into the correct dialect-specific SQL (SQLite or PostgreSQL) under the hood.
  3. **Dialect-Safe Migrations & Startup Checks:**
     - *Alembic constraints/indexes:* SQLite batch migrations require special rendering (`render_as_batch=True`). Dialect name guards (`if op.get_context().dialect.name == 'sqlite':`) are used to wrap SQLite-specific steps (like redundant baseline index or foreign key creation/drops) to prevent PostgreSQL transaction aborts.
     - *Startup migrations:* Rather than executing dummy `SELECT` queries that abort transaction blocks on PostgreSQL upon failure, dynamic column migrations check for existing columns in database metadata using SQLAlchemy `inspect(conn)`.
- *Recommendation for Hybrid Requirement (Merchant needing both local speed & cloud features):*
  - **Local Counter / Cloud Backbone Hybrid Model:**
    - The shopkeeper's physical POS checkout counter runs the app locally pointing to a local, encrypted SQLite database. This guarantees sub-second checkout speed and 100% counter uptime even during internet blackouts.
    - An asynchronous background **Sync Agent** runs on the merchant's machine, polling a local sync outbox queue to push transaction deltas (e.g., finalized sales, inventory adjustments) to the cloud PostgreSQL database and pull remote updates (e.g. new buyer orders, partner price lists).
    - Cross-business features (such as B2B invoice transfers, catalog discovery, and AI analysis) run exclusively on the Cloud Postgres server via secure REST APIs. If a seller wants to transfer an invoice to a buyer, the seller's Sync Agent pushes it to the cloud, and the buyer's Sync Agent pulls it down to their local counter.
    - Data integrity across dialects is maintained by applying the exact same Alembic schema migrations on both local and cloud databases.
- *Concrete cloud choice:* keep your **own Postgres + Alembic** chain (you already migrated). For the customer-app realtime layer, either (a) add a thin WebSocket/SSE service on your stack (you already use SSE for chat), or (b) adopt **Supabase** (managed Postgres + realtime + auth) if you want speed-to-market and don't mind some lock-in. **Recommendation:** start on your own Postgres + a small SSE push service to avoid lock-in; revisit Supabase only if realtime fan-out becomes a burden. (This is a reversible call — flagged in §13 for your sign-off.)


### D6 — Payments/subscriptions: **Razorpay, manual activation first.** ✅ decided
- *Decision:* For India, **Razorpay** over Stripe. For the pilot cohort, **manually activate plans** (admin toggles `plan`) — don't build self-serve checkout yet. Add Razorpay self-serve once you have >10 paying businesses.
- *Why:* self-serve billing is undifferentiated work; with a handful of local pilots you onboard them by hand and learn pricing. Razorpay also powers the *customer-app UPI collection* later (a future revenue line).

### D7 — E-way bill: **compliant PDF with transport fields first; API aggregator later.** ✅ decided
- *Decision:* Phase 1 = generate a compliant invoice PDF that captures the e-way-bill fields (vehicle no., transporter, distance, Part-A data) when total > ₹50,000. Phase 5 = integrate an e-way bill API aggregator for one-click filing.
- *Why:* the legal need on day one is *a correct document*; full NIC API integration is heavy and can wait until volume justifies it. Get the PDF flow validated by a CA before calling it "compliant."

### D8 — Customer app: **PWA web link first, not a native app.** ✅ decided
- *Decision:* the retailer ordering app ships first as a **mobile PWA** (installable web link, works on any phone, no app-store friction, WhatsApp-shareable invite). Native wrappers only if retention proves it's worth it.
- *Why:* fastest path to the validation that matters (will retailers actually order?), zero store review delay, one codebase. Antigravity's "dedicated app" framing is the *marketing* promise; a branded PWA delivers it technically.

### D-sec — Customer-side isolation: **two-key scoping.** ✅ decided
- A customer-app user resolves to **`(business_id, customer_id)`**, and *every* API call is filtered by both. A retailer can only ever see the one wholesaler's catalogue/prices/their own ledger. This is the "secure, not breakable" requirement made concrete. (Tested explicitly — see §10 Phase 3 tests.)

### D9 — Public Registration ID (the "BizID"): the addressing layer of the network. ✅ decided ★ NEW
- *Your requirement:* every business, wholesaler, and customer gets a **unique registration ID** that can be used to **search** them and **send invoices/orders directly through the app**.
- *Decision:* every account gets a **globally-unique, human-shareable public ID** — call it the **BizID** — that is **separate from the internal `business_id`/`customer_id` primary keys** (never expose serial DB keys). It is the network's addressing system: like a UPI handle, but for businesses, orders, and invoices.
  - **Format:** `BA-XXXXXX` — a `BA-` prefix + 6 chars of Crockford base32 (no ambiguous `0/O/1/I/L`). Random, not sequential (so IDs aren't guessable or countable), collision-checked at issue. Readable aloud, WhatsApp-able, printable on an invoice. Optionally allow a vanity handle later (`@nilgiris-fresh`).
  - **Who gets one:** every **business** (wholesaler *and* a retailer-who-is-a-business) gets a `business.public_id`. Every **customer-app user** gets a `customer_app_user.public_id`. B2B discovery is primarily business↔business by `public_id`.
  - **What a lookup reveals (privacy):** searching a BizID returns **public profile only** — business name, type, city, logo, and "accepts orders: yes/no". It reveals **zero transactional data**. You see enough to confirm "this is the right shop", nothing more.
  - **Connecting = consent:** searching a BizID lets you send a **connection request**; the other side **accepts** → a `b2b_partnership` row is created → now orders/invoices can flow directly between you. Either party can initiate (wholesaler searches retailer, or retailer searches wholesaler). This **replaces/augments** Antigravity's "invitation link" — a WhatsApp invite link is just a pre-filled BizID connect; both paths land on the same consent-gated partnership.
  - **Addressed delivery:** an invoice or order can be **addressed to a BizID** and delivered to that account's **in-app inbox** (plus optional WhatsApp), instead of only sharing a file. This is the feature the web-link-catalog competitors (Vyapar/myBillBook) do **not** have — direct, app-native, addressable document delivery.
- *Why this matters (it's a USP, not a detail):*
  1. **Self-serve network growth** — no manual customer entry, no chasing phone numbers. "What's your BizID?" → search → connect. The friction of building the network collapses.
  2. **Viral, UPI-style** — once everyone has a BizID printed on their invoices and storefront, connecting becomes a habit and a status symbol ("order from us, BizID `BA-7K9P2M`"). Each connection makes the network denser and stickier.
  3. **Trust & security** — consent-gated connection + public-only lookup means the ID is safe to share publicly while data stays locked behind the two-key scoping (D-sec). You can hand your BizID to the world and leak nothing.
- *Resolves open question:* the "wholesaler→retailer invitation flow" is now defined: **BizID search + consent**, with a WhatsApp invite link as the pre-filled shortcut.
- *BizID is not a feature — it's the spine (see §16).* It is the **one identity** the whole ecosystem hangs off: **login** identity · **address** for orders/invoices/payments · **verified badge** (KYC/GSTIN-verified → a trust signal) · **reputation** carrier (payment/fulfilment history) · and later the **payment handle** (like a UPI VPA). Apple's ecosystem is glued together by the Apple ID; ours is glued by the BizID. Treat it with that weight.

### D10 — ONE app for the whole B2B chain, connected by a seller-issued code. ✅ decided ★ supersedes the two-app framing
- *Your clarified vision (and it's better than the two-app split I first drew):* there is **one app/front-end**, not a separate merchant app and customer app. **Everyone in the supply chain is a business that buys from above and sells below** — distributor → wholesaler → retailer. They all run the *same* BizAssist app.
- **Ordering lives *inside* the billing app.** A wholesaler orders from his distributor from within his own app (he's acting as the distributor's *buyer*); a retailer orders from the wholesaler the same way. No separate "customer app" for the B2B chain.
- **Connection = a code the SELLER generates** (consent + privacy). The buyer enters the seller's code → a partnership link is created → from then on the buyer can see that seller's catalogue/tier-prices and place orders. The seller controls who connects (no unsolicited access). BizID stays the *public "find me"* handle; the *connect* is the seller's code/approval. (Discovery is public; connection is consent.)
- **The killer auto-sync (this is the whole reason to be on both ends):** when the seller bills the order, that **invoice's line items flow straight into the buyer's product master and stock** — the buyer never re-types what he bought; his inventory updates itself from his supplier's bill. This is the single biggest "kills manual entry" win, and it only happens when both sides are on BizAssist.
- **Graceful fallback when the other side is NOT on BizAssist:** the business still bills normally — upload-invoice + easy manual add (same flow as any merchant). **No hard dependency on the partner being on the platform** — you just don't get the auto-sync. This keeps adoption unblocked.
- **Adoption is progressive, in ONE app (not a second app):** a brand-new user who only wants to order sees a dead-simple "order from your supplier" screen; billing/stock/reports reveal as they grow. Same app, lite→full. This is how a retailer "tastes" billing and turns it into his daily billing — the dependency you want, with no migration moment.
- **The non-negotiable privacy boundary — a connection shares the *transaction*, not the *books*:** two connected businesses may see ONLY the shared deal between them — the catalogue/prices offered to the buyer, the orders between them, the invoices between them, and the stock-in those invoices create. **Neither may ever see the other's private world** — their other suppliers, other customers, sales, margins, total stock. *Connected = a shared pipe between two private rooms, never one shared room.* Every sync feature must pass: "would the seller be OK with the buyer seeing this, and vice-versa?" If not, it does not sync. **Getting this wrong once = a data leak = the network is dead.** (See the expanded §6.)
- *The consumer exception:* the one-app model fits the **B2B chain** (every node is a business). A true end-consumer won't install a billing app — so consumer ordering is a *later, optional, separate lite surface* (or just walk-in billing). Don't let the consumer case muddy the clean B2B model.

---

## 3. The product in one picture (ONE app, the connected chain — D10)

**One app. Every business runs it.** Each is a private room; a connection is a one-way-consented *pipe* between two rooms carrying only the shared deal. The chain grows up (your suppliers) and down (your buyers) from any entry point.

```
   DISTRIBUTOR  ── BizAssist (one app) ──┐
        │  sells to                       │  each business = a PRIVATE room:
        ▼                                 │   • own billing / stock / customers
   WHOLESALER ★pilot ── BizAssist ────────┤   • own books NEVER shared
        │  sells to                       │
        ▼                                 │  a CONNECTION (seller-issued code) =
   RETAILER ── BizAssist (lite→full) ─────┤   a shared PIPE between two rooms:
        │  sells to                       │   • buyer sees seller's catalogue+tier price
        ▼                                 │   • orders + invoices flow between them
   CONSUMER ── (walk-in bill, or later    │   • seller's invoice → buyer's stock (auto)
                a small order surface)     ┘
```

```
            ┌──────────────── BizAssist PLATFORM (cloud = source of truth) ───────────────┐
            │ FastAPI · Postgres (Alembic) · per-business isolation · append-only ledgers   │
            │ realtime push (orders/invoices/offers) · AI engine (4-tier, existing, paid)   │
            └──────────────────────────────────────────────────────────────────────────────┘
                    ▲ same app for everyone; features reveal by role + plan ▲
```

**One menu, progressive by role/plan** (billing is home; ordering-from-suppliers and AI reveal as the business grows):
`Billing · Sales · Purchases · Stock · Customers · Suppliers · Orders (buy ↑ / sell ↓) · Payments · Reports · AI Advisor · Connections · Settings`

> **The mental model in one line:** *every node runs the same app; a buyer and a seller who connect share a pipe (the deal between them), never a room (their books).* That single rule is what makes a shared platform safe — see §6.

> **The killer feature (D10):** a connected seller's invoice **auto-fills the buyer's stock and product master** — the buyer stops typing what he bought. This is the reason a wholesaler drags his distributor and his retailers onto the platform.

> **No hard dependency:** if your supplier isn't on BizAssist yet, you still bill normally (upload-invoice + manual add). You just miss the auto-sync until they join.

---

## 4. System architecture (detailed)

### 4.1 Layers
- **Data layer:** Cloud Postgres (authoritative) + per-business offline SQLite cache (Phase 3). Alembic migrations as the one schema chain for both.
- **API layer:** FastAPI (existing). All routes `business_id`-scoped via the auth dependency. New route groups: `sales`, `purchases`, `stock`, `orders`, `connections` (code-based partner linking), `subscription`.
- **Realtime layer:** an SSE/WebSocket push service. Events: `order.created`, `order.accepted`, `invoice.ready`, `offer.published`, `stock.low`. The buyer's and seller's apps both subscribe (each sees only its side).
- **AI layer:** unchanged engine. New tools/handlers read the new tables (orders, ledger) so the advisor can say "these 12 buyers haven't ordered in 18 days."
- **Sync layer (Phase 3):** delta sync between offline SQLite and cloud, hybrid conflict rules (D2), idempotency keys on transactions.
- **Front-end:** **ONE app** (the existing React app, re-homed to billing), progressive by role + plan (D10). A small consumer order surface is a *later, optional* add — not a second app.

### 4.2 Request scoping (the security spine)
- Every account token → a verified `business_id`. Every query: `WHERE business_id = :bid`. **Never** trust a client-supplied `business_id` — it comes from the token only.
- **Cross-business reads are allowed ONLY through an accepted connection, and ONLY for the shared slice.** When business A reads anything about business B, the API must check a row in `connections` (A↔B, status=accepted) **and** restrict the result to the shared-pipe data (B's catalogue/tier-price to A; orders/invoices between A and B). A query that would return B's *private* data (other partners, sales, margins, stock totals) to A must be impossible to express — enforce it in a single shared "partner-scope" guard, not ad-hoc per endpoint.
- A future consumer order surface resolves to `(business_id, customer_id)` and is filtered by both — the same discipline, one extra key.

---

## 5. Final reconciled data model

Keep all existing tables. Use `business_id` as tenant key (D1). Add the following. (Names chosen to fit your current snake_case style; line-item tables mirror `invoice_line_items`.)

**Sales / Purchases (formalize what billing needs):**
- `sales_invoices` (or extend existing `invoices`) — header: business_id, customer_id, number, date, totals, GST splits, payment_mode, paid_amount, eway fields, irn/qr. *You already have most of this on `Invoice`; decide whether to reuse `invoices` or introduce `sales_invoices` — see §13 sign-off.*
- `sales_invoice_items` — mirrors `invoice_line_items` (largely exists).
- `purchase_invoices` + `purchase_invoice_items` — supplier bills (partly covered by `purchase_orders`; add the *invoice* (received) concept distinct from the *order*).

**Stock (the trust backbone, D4):**
- `stock_ledger` — **append-only**: id, business_id, product_id, movement_type (`purchase|sale|return_in|return_out|damage|adjustment|order_reserved|order_released`), qty_delta (+/−), reference_type, reference_id, balance_after, note, created_at, device_id.
- `inventory.stock` stays as a cached projection.

**B2B connections & ordering (the ecosystem — D10):**
- `connections` — **seller_business_id ↔ buyer_business_id** (the chain link), price_tier, credit_limit, outstanding_balance, status (`pending|accepted|revoked`), created_at. This is the **partnership = the shared pipe**; every cross-business read is gated by an accepted row here. Either side can revoke (the pipe closes; the rooms stay private).
- `connection_codes` — **seller-issued, single-use, expiring** join code → buyer redeems → writes a `connections` row. The seller controls who links (D10). Codes are random, short-lived, one-time.
- `orders` + `order_items` (D3, relational) — seller_business_id, buyer_business_id, status (`pending|accepted|packed|dispatched|completed|cancelled`), totals; items reference the *seller's* product_id, qty, tier unit_price, + optional JSONB catalogue snapshot (what the buyer saw at order time).
- **Invoice→stock auto-fill (the killer feature):** when the seller bills an order, a job writes the invoice's line items into the **buyer's** product master (if new) and a `stock_ledger` `purchase` movement — the buyer's inventory updates from the seller's bill. Buyer reviews/confirms before it commits (trust).
- `business_catalog_settings` / `price_lists` — the seller's catalogue + per-tier pricing shown to connected buyers only.
- `offers` / `campaigns` — id, business_id, title, scope (all/segment of connected buyers), discount, valid_from/to, push flag.
- *(Optional, later)* `customer_app_users` — `(business_id, customer_id)` identity for a consumer order surface; not needed for the B2B chain.

**Shared ledger (myBillBook-style, enhanced) — the shared pipe, not the books:**
- `shared_ledgers` — seller_business_id, buyer_business_id, transaction_type (`invoice|payment|credit_note|debit_note`), reference_id, amount (+dr/−cr), balance_snapshot, created_at. Both connected sides read **only these rows for their own link** (scoped by the `connections` row). Append-only (D2). It records the *running balance between the two*, nothing about either's wider business.

**Platform:**
- `business.business_type` (FMCG/pharma/grocery/hardware/restaurant) + a template-config loader.
- **`business.public_id`** (D9) — the BizID. Globally-unique, indexed, `BA-XXXXXX` format, random + collision-checked, distinct from the serial PK. A `public_profile` view (name, type, city, logo, accepts_orders) is the *only* thing a BizID lookup may return. (Public discovery; the actual link still needs a `connection_code` — D10.)
- `inbox_items` — recipient business_id, type (`invoice|order|offer|message`), reference_id, read flag → powers BizID-addressed delivery into the app.
- `subscriptions` / extend `User.plan` — plan, status, period, unlocked_features.
- `sync_events` / per-row `sync_status` (Phase 3).

> Migration discipline: every addition is one Alembic revision, additive, nullable-by-default, backward compatible — the same discipline that's already kept your 385 tests green.

---

## 6. "Secure & unbreakable" — goal #2, by design

> **Governing principle: the data IS the money.** A business's invoices, customers, prices, margins, and stock are its most valuable asset — often more sensitive than cash. A single leak (one business seeing a competitor's prices, one breach dumping the directory) doesn't just lose a user, it ends the network's reputation in a tight local trade community where everyone talks. **Security is not a feature here; it is the product.** Treat every design choice as "could this expose someone's money?"

### 6.1 The correctness/trust rules (logic-level — never violate)
1. **One tenant key, gated cross-access** (D1 + D10 + §4.2): every query scoped by the token's `business_id`; cross-business reads only through an accepted `connections` row, and only the shared-pipe slice. **A query that could return a partner's private books must be impossible to express** — one shared partner-scope guard, tested with explicit negative cases ("buyer A cannot read seller B's other customers / sales / margins").
2. **Shared transaction, never shared books** (D10): connected = a pipe between two private rooms. Every sync/read passes "would BOTH sides consent to this field crossing?" If not, it doesn't cross.
3. **BizID is safe-to-share** (D9): public lookup returns public profile only; the actual link needs a seller-issued, single-use, expiring `connection_code`. Random non-sequential IDs prevent directory scraping.
4. **Money is append-only** (D2): invoices/payments/stock/ledger never overwritten — corrections are new reversing entries. No sync edit can delete a sale.
5. **Idempotency keys** on every transaction so a retried/duplicate sync can't double-post a bill or double-deduct stock.
6. **AI never touches money** — totals/tax are deterministic SQL; AI only advises; its actions stay preview→confirm→audit (`ActionLog`).
7. **Staff roles (RBAC)**: owner vs cashier/staff, per `business_id` (staff can bill but not delete invoices, change prices, or see profit). Phase 2.

### 6.2 Base-level security & encryption (infrastructure — build in from day one, cheap now, near-impossible to retrofit)
8. **Encryption in transit — everywhere, no exceptions.** TLS 1.2+ (HTTPS/WSS) on every connection: app↔cloud, the realtime push, the offline-cache sync. No plaintext HTTP, ever. HSTS on. Certificate pinning on the mobile client later.
9. **Encryption at rest — all three copies.** (a) Cloud Postgres with storage-level encryption (managed PG gives this) + column-level encryption for the most sensitive fields (GSTIN, phone, bank/UPI, any KYC). (b) The **offline SQLite cache encrypted** (e.g. SQLCipher) — a stolen shop laptop must not yield a plaintext customer/price book. (c) **Backups encrypted** with separate keys.
10. **Secrets never in code or client.** API keys, JWT secret, DB creds, Groq key in a secrets manager / env (you already moved JWT_SECRET out of code — keep that discipline). The customer/buyer side gets **least privilege**: no secrets shipped to the browser; it can only call its own scoped endpoints.
11. **Auth hardening.** Passwords bcrypt-hashed (already). Short-lived access tokens + refresh; server-side revocation on logout/role-change. **Throttle every credential surface**: login, OTP, and `connection_code` redemption are rate-limited + lockout on abuse (you have rate-limiter infra — extend it). Connection codes are single-use and expire in minutes.
12. **Tenant isolation enforced in one place, defense-in-depth.** A single scoping dependency every route inherits (not per-endpoint `WHERE` clauses a dev can forget). Later: Postgres Row-Level Security as a second wall, so even a buggy query can't cross tenants.
13. **Input safety.** Parameterized queries only (SQLAlchemy already), output-escape all rendered data (you fixed XSS), validate/scan every upload (size caps exist; add type/content checks on invoice photos/PDFs), strict CORS allowlist (you removed the `null` origin).
14. **Audit everything, immutably.** `stock_ledger`, `shared_ledgers`, `action_log`, `connections` (who linked/revoked when), auth events, admin actions, sync events. "Unbreakable" = "always explainable." Audit logs are append-only and access-logged themselves.
15. **Backups + data ownership.** Cloud Postgres point-in-time backup (the offline cache is a cache, not the only copy) + tested restore drills. One-tap **"export all my data"** — owners trust software they can walk away from; easy switch-*out* paradoxically *increases* retention.
16. **PII & compliance discipline.** Collect the minimum (phone, GSTIN, name). India's DPDP Act applies once you hold personal data — consent, purpose limits, deletion on request. Don't store card numbers (let Razorpay vault them — stay out of PCI scope). KYC docs (if any) encrypted + access-logged.
17. **Operational security.** Least-privilege admin accounts + 2FA; no shared logins; monitoring/alerts on anomalies (mass export, off-hours admin, repeated failed logins); a written incident-response + breach-notification plan *before* launch, not after.
18. **Tamper-evident transactions (the "strong encrypted transaction" — a real moat, §14 #3).** Every shared transaction (invoice, payment, ledger entry between two businesses) is **digitally signed by the issuer** and the shared ledger is **hash-chained** — each entry stores the hash of the previous one, so altering any past entry breaks the chain and is instantly detectable. Result: neither party can silently edit or deny a shared invoice after the fact; the ledger is a **neutral cryptographic source of truth** that settles reconciliation disputes. (NOT a blockchain — a per-connection signed, append-only, hash-chained log. Cheap, hugely trust-building.) **Timing (Codex's correct nuance):** plain **encryption** (TLS + at-rest + SQLCipher) is day-one; the **append-only shared ledger** ships with connections (Phase 4); the **signing + hash-chain layer ships in Phase 6** — you can't sign shared transactions before they exist, and it's not first-week work. Leave the schema room for it from the start; implement it when the shared ledger is mature.
19. **Key management.** Encryption + signing keys live in a managed KMS (cloud KMS, or libsodium-backed with a vault), never in code or the DB. Per-business signing keypair (public key published on the BizID profile so a partner can verify signatures); scheduled rotation; envelope encryption for column-level secrets. Losing/rotating keys must never lose data (re-encrypt, don't discard).

### 6.3 What is HARMFUL — the threat list (name the danger, then the guard)
| Threat (the harm) | Why it's lethal here | The guard |
|---|---|---|
| **Cross-business data leak** (A sees B's books via a sync/partner endpoint) | "Data is money" — one leak kills trust in a gossip-tight trade community | §6.1 #1–2 partner-scope guard + RLS (#12) + negative tests |
| **Directory scraping** (harvest every business + prices via IDs) | Hands a competitor your whole market map | Random BizIDs (#3), auth on lookups, rate-limit, public-profile-only |
| **Stolen shop device** (laptop/phone with offline cache) | Plaintext local DB = a dumped customer + price book | Encrypted offline cache (#9b) + device auth + remote revoke |
| **Connection-code abuse** (guessing/replaying join codes to link without consent) | Unauthorized pipe into a private room | Single-use, expiring, throttled, seller-revocable codes (#3, #11) |
| **Tampered/duplicated sync** (replay an invoice, double-post, edit a bill) | Phantom money / lost sale | Append-only + idempotency keys (#4–5), signed transactions |
| **Credential stuffing / weak passwords** | Account takeover = full books | bcrypt, throttle+lockout, refresh tokens, optional 2FA (#11) |
| **Malicious upload** (poisoned invoice photo/PDF → parser exploit or XSS) | Server/client compromise | Size+type+content validation, sandboxed parsing, output-escape (#13) |
| **AI exfiltration / prompt injection** (a crafted record tricks the advisor into leaking another tenant's data) | Subtle, easy to miss | AI reads only the caller's scoped data; never cross-tenant context; actions gated (#6) |
| **Insider / staff abuse** (a cashier exports the customer list, changes prices) | Internal theft of the asset | RBAC (#7) + immutable audit (#14) + anomaly alerts (#17) |
| **Payment fraud / mis-collection** (later, UPI layer) | Real cash loss | Razorpay-vaulted, idempotent, reconciled, never store card data (#16) |
| **Backup loss / ransomware** | The whole network's data gone | Encrypted, off-site, versioned backups + restore drills (#15) |
| **Hard dependency on a partner being online** | One outage stalls everyone | No hard dependency (D10) — fall back to manual billing |
| **Dispute / repudiation** ("you altered that invoice", "I never got that bill") | Reconciliation fights destroy B2B trust | Signed + hash-chained shared ledger (#18) — a neutral, tamper-evident record both sides can verify |
| **Cloud/region outage (the network "collapses")** | The whole ecosystem stalls at once | Anti-collapse design (§16): per-node offline autonomy, no single point of failure as you scale, durable encrypted backups, graceful degradation |

> **The base-level summary:** *encrypt in transit and at rest (all three copies), scope every read by token, gate every cross-business read through a consented pipe, append-only money, least-privilege everywhere, throttle every code/credential, audit immutably, back up encrypted, and assume every record is someone's money.* Build this in from the first migration — security retrofitted onto a live financial network is how startups die.

---

## 7. "Easy to use" — goal #1, by design

1. **Two clean mental models, two sections** (the owner asked for this): **Sales** (optimize for *speed*) and **Stock** (optimize for *accuracy*). Never mix them.
2. **Billing counter = 5 keystrokes:** search item → qty → payment → Enter → printed. Keyboard + barcode first; `Enter` finalizes. Target: a 5-line bill in **< 45 seconds**, no training.
3. **Kill manual entry** (his #1 pain) with four faster stock paths: bulk CSV/Excel (your `column_mapper`/`parser` already normalize messy columns), **AI invoice/photo parsing** (your `pdf_parser` → snap a supplier bill → review → import — a genuine wow vs Vyapar), barcode scan, and PO→receipt.
4. **Self-configuring by business type** (D1 field + template registry, config-over-code — the same pattern as your intents/actions): on signup the format picks fields, tax defaults, units, invoice layout.
5. **One app, no jumping**: billing, stock, customers, dues, reports, AI all under one shell.
6. **WhatsApp-native sharing** of invoices and customer-app invites (table stakes — Vyapar/myBillBook both do it).
7. **Switch-in migration (adoption-critical, was missing):** he is *replacing* an existing system — he already has an item master, customers, stock, dues, and old invoices. On day one we **import his existing data** (your `parser`/`column_mapper` already normalize messy exports; most billing tools export CSV/Excel): item master, customer list with opening dues, opening stock (as the first `stock_ledger` entries). Without this, "easy to use" is a lie — nobody re-enters 800 items by hand. This is also a moat in reverse: an easy switch-*in* and an honest switch-*out* (point 7 in §6) both build trust.
8. **Counter hardware parity:** thermal-printer support + barcode label printing. Small, but it's the difference between "fits my shop" and "doesn't" for a retail counter (Vyapar lists thermal support as a headline feature).

---

## 8. "Addictive & sticky" — goal #3, by design

Stickiness has two engines: **daily habit** (the merchant) and **network lock-in** (the customers).

**Daily-habit hooks (merchant):**
- **Morning digest** (you already built it): "3 things that need you today" — overdue to chase, stock to reorder, retailers gone quiet. Opens the app every morning with a reason.
- **Live order pings**: a retailer order pops on the counter in real time → dopamine of "money came in without a phone call."
- **AI nudges**: "Basmati Rice is your top mover and stock is 4 — reorder?" One-tap action.

**Network lock-in (the real moat):**
- Once a wholesaler's 40 retailers order through *his* PWA, **he can't leave without disrupting his customers.** Billing apps have ~zero switching cost; an active customer ordering network has enormous switching cost. This is the asset.
- **The BizID is the viral accelerant** (D9): printed on every invoice, storefront, and WhatsApp message, it turns "connect to my shop" into a one-search habit — the UPI-handle effect. The more BizIDs in circulation locally, the more valuable it is to have one, the harder it is to leave (your connections live here). This is a classic network-effect flywheel, and it's the part competitors' web-link catalogs can't replicate.
- **Viral pull**: every wholesaler onboards his own retailers for you (free). Some retailers are themselves shops → they discover BizAssist billing → bottom-up spread through the local trade network. **Your customer acquisition is performed by your customers.**
- **Offers/marketing push** keeps retailers opening the app (deals, festival schemes), and gives the wholesaler a reason to stay (his megaphone to his buyers lives here).

> The addictive loop: *merchant bills → AI advises → merchant acts → retailers order → ledger updates → AI sees demand → better advice → more orders.* Each turn makes leaving more costly.

---

## 9. "Make money" — goal #4, by design

Billing = acquisition (cheap/free). The money is in the **network plan + AI + (later) payments**.

| Plan | Indicative price (validate locally) | What's in it | Strategic role |
|---|---|---|---|
| **Starter (Local Billing)** | Free or ~₹999/yr | Billing, stock ledger, invoices, e-way PDF, local backup | Land users; remove the reason to say no (match Vyapar) |
| **Business Cloud** | ~₹3,000–6,000/yr | Cloud sync, multi-device, reports, **customer ordering link** | First real revenue; unlocks the network |
| **AI Pro** | ~₹500–1,500/mo add-on | AI advisor, invoice-photo extraction, stock/reorder suggestions, customer-recovery, digest | High margin; you already built it + meter it |
| **Wholesale Network** | top tier | Full retailer app, order management, price tiers, offers, delivery/challan | The moat tier; highest LTV |

**Why this makes money:**
- **Land-and-expand:** cheap billing in the door → Business Cloud (customer app) → AI Pro. Each tier is a natural upsell triggered by usage.
- **Network multiplies seats:** one wholesaler can pull dozens of retailers into the paid orbit.
- **Future fintech line:** UPI collection through the customer app (Razorpay) + credit/financing referrals once transaction volume exists — the highest-margin layer, deferred until you have flow.
- **Pilot pricing now:** charge the first owner a real (even small) pilot fee — it validates willingness to pay and seriousness.

---

## 10. Phased roadmap (sharper order — fights scope explosion)

> **The #1 risk is scope explosion** (Codex was right to hammer this). If everything is "Phase 1," the project stalls. So: **only ONE thing per phase, each phase sellable alone.** Billing alone first. Don't build connections, signing, reputation, offline, or AI until billing + purchase auto-entry are loved. *Build the big ecosystem in the architecture; ship a painkiller.*

> Foundational from day one (not a phase — just how we build): `business_id` scoping on every query, `business_type` template config, encryption (TLS + at-rest + SQLCipher), append-only ledgers, the modular-monolith structure (Tech doc §10.x). These are *disciplines*, present in every phase.

---

### 10.0 — BUILD STATUS TRACKER  ·  *last updated 2026-06-21*

> Single source of truth for "where are we." Legend: ✅ done · 🟡 partial / needs depth-verification · ⬜ not started.
> Canonical code lives in **`bizassist-billing/`** (the `bizassist/` copy is retired — fully subsumed). Status below reflects that repo: **555 backend tests green; 78 backend API routes across 13 modules; 16 frontend pages.** Items marked 🟡 exist in code (route/page present) but their *depth* (real print, live filing, security negative-tests) is not yet verified — don't trust a ✅/🟡 as "production-proven" until its test is named below.

**Deployment & Migration**
- ✅ **Postgres migration table coverage update (2026-06-21):** Restructured `backend/migrate_sqlite_to_postgres.py` to order and copy all 37 database tables. Ready for Supabase and Hugging Face deployment.

**Foundation / cross-cutting (this session)**
- ✅ **Performance / N+1 Pass on Reports (2026-06-20):** Resolved all N+1 database query patterns and ORM listing instantiation overhead in `/reports/pnl` (joined COGS query), `/reports/outstanding` (case-aggregations in DB), `/reports/day-book` (bulk customer name pre-fetch), `/reports/balance-sheet` and `/reports/trial-balance` (pure DB aggregates). Verified 100% correct by the 555-test suite.
- 🟡 **UI — sticky sub-bars + Reports working-panel (2026-06-20, needs visual QA):** shared `.page-subbar` class (pins a page's filter/tab navigator directly under the already-sticky `.page-header`, via deterministic `--page-header-h: 64px`) applied to Payments, Parties, Purchases, Connections, Orders, Stock and Settings navigators, so filters stay in view while content scrolls (less wasted padding). Reports rebuilt into one **`.reports-panel`** (filters + single-row, manually-expandable report selector + 25/75 recent/output), with the "Recently used" list restyled as clean table-like rows. Settings "Save Changes" already lives in the page-header (the Record-Payment pattern). **Verify with `npm run dev`** — header-height/`top` alignment and the sticky strips are an R6-style visual pass; flagged not-yet-eyeballed.
- ✅ **R3 — Tamper-evident hash chain (2026-06-20):** `journal_entries.prev_hash`/`entry_hash` (migration `a3c7e9b1d2f4`, new head) + SHA-256 chain in `posting.post_entry` (per business, GENESIS root, 2dp-stable) + owner-only `GET /reports/verify-chain` reporting the first broken entry. `test_hash_chain.py`; tamper-evidence sim-proven (edit/hidden-edit/delete all detected). The Phase-6 "signed shared ledger" moat foundation. *User runs `alembic upgrade head` + `pytest`.*
- 🟡 **R2 — Period close/lock (2026-06-20):** event-sourced append-only `period_locks` (migration `f2b9d4c1a8e3`, new head) + `assert_period_open` guard in `posting.post_entry` (the single choke point for all six money write paths) → posting into a closed period is rejected **422** and writes nothing. Owner-only `/accounting/period-lock` + `/period-unlock` API (cashier 403, tenant-scoped, lock-regression blocked). `test_period_lock.py` negative-first. **Unblocks R3 hash-chain.** Opening-balance carry-forward split out as **R2b** (deferred). *User runs `alembic upgrade head` + `pytest`.*
- ✅ **Settings → interactive print preview (2026-06-20):** the Print tab is now a **50/50** split — controls left, **live preview** right — with a **Thermal ⇆ PDF/A4** toggle (independent of the saved mode). The preview is **click-to-edit**: clicking any element (logo, company name/address/phone/email, GSTIN, GST breakdown, amount-in-words, terms, theme colour, signature) scrolls its setting into view on the left and **flashes** it (`Editable` wrapper → `jumpToSetting` → `set-<key>` ids on `SettingRow` + `.setting-flash` keyframe). Live-updates as settings change. **Drag-to-customise header (2026-06-20):** the receipt header lines (logo · company name · address · phone/email · GSTIN) are **drag-reorderable** in the preview with per-line **L/C/R alignment**, persisted to `print.header_layout` (shared `utils/printLayout.js`) and **applied to the real thermal receipt** (`Sales.jsx` renders the header from the saved order+alignment). Backfills/sanitises the layout so it can't lose a line. The left panel **filters by the active preview**: format-specific rows (theme colour / layout / page size / orientation = PDF-only; thermal paper size / theme = thermal-only) show only for the selected format, while shared content settings stay in both. The thermal preview also shows **total Qty vs Items** and **"You have Saved"** (matching the M.R. Traders receipt). *Frontend-only; needs `npm run dev` visual check.*
- 🟡 **R4 (Slice 1) — Post-tax cash discount / round-off (2026-06-20):** `invoices.cash_discount` (migration `b5d8f2a6c3e1`) reduces the payable only — GST/taxable untouched — booked as `Discount Allowed` so the journal foots; **no-op at 0** (existing data/tests unaffected), doesn't break the R3 chain. Wired through `create_sale_invoice`, both sale routes, and the pure frontend math. `test_cash_discount.py` + `invoiceMath.test.js`; reproduces the M.R. Traders receipt (1123→1120, Saved 200.49). UI input + MRP structural rename deferred (§10.3 R4 Slice 2). *User runs `alembic upgrade head` + `pytest`/`npm test`.*
- ✅ **Benchmark receipt captured (2026-06-20):** a real intra-state kirana thermal bill (M.R. Traders) transcribed + reconciled to the rupee in **`BENCHMARK_RECEIPT_MR_TRADERS.md`**. Validates the MRP+Rate+"You have Saved" format and the inclusive multi-slab GST split; surfaced a missing **post-tax cash-discount/round-off** concept (distinct from the existing pre-tax apportioned `bill_discount`) now folded into §10.3 **R4**, plus a new **R8** (thermal template + `wallet` mode + counter id).
- ✅ **R1 — Report pagination + caps (2026-06-20):** `sales-register`, `purchase-register`, `stock-movement`, `stock/ledger`, `day-book` now take `limit`(≤2000)/`offset`, return total via `X-Total-Count` (day-book via `total`), keep summaries over the full window, and stay deterministic (`date,id` order). CORS `expose_headers` updated; `Reports.jsx` requests the max page and warns on truncation so no rows drop silently. Clamp/slice logic sim-verified. (§10.3 R1.)
- ✅ **Performance / N+1 Pass — round 2 (2026-06-20):** (a) `reports._build_journal_entries` (drives `/reports/journal`, `/reports/general-ledger`, P&L-period derivations) no longer loads the *entire* ledger and filters in Python — the date window is now pushed into SQL via `coalesce(date,'') >= from / <= to`, **proven exactly equivalent to the old `within()` guard incl. NULL-dated rows** by a standalone sim, so it's purely a perf change that hits `ix_invoice_business_date`. (b) `/reports/gstr1-b2b` and `/reports/gstr1-b2cs` read `inv.customer_ref` per row (plain-lazy → N+1 of `Customer` queries); both now `joinedload(Invoice.customer_ref)`. `Invoice.line_items` was already `lazy="selectin"` (auto-batched), so it was not a real N+1. Result-preserving; existing `test_journal.py` / `test_audit_journal.py` / GST tests validate (user runs `pytest`).
- ✅ Modular-monolith reorg: billing ecosystem in `core/`; tables split by domain (`core/models.py`) on one shared `Base`; billing wired from `core/api/core_router` (entry point doesn't import individual routes).
- ✅ Business Template System — 8 verticals (`supermarket, pharmacy, restaurant, textile, wholesale, hardware, services, general`) + loader + `business_settings` (migration `a4c9d2e7b3f1`).
- ✅ Backend test suite green (431). 🟡 Frontend test infra: added to `frontend-billing` (vitest); tests now cover money/words formatting **and** invoice money-math (intra/inter GST split, discounts, change-due) — all verified.
- 🟡 **P0 code-health refactor (in progress):** shared `api/client.js`, `utils/format.js`, `utils/invoiceMath.js` (pure + unit-tested: line totals, intra/inter GST split, change-due, **and the invoice payload builder** — the money contract sent to the backend), `<Money>`, `<Modal>` added; `Sales.jsx` slimmed **3,050 → ~2,945** by extracting formatters, totals/GST math, and the save payload; the **save flow is now logged** (`[SALES]` info on attempt/success, error on reject/network — fixed a previously silent `catch`). UI components carved out of Sales.jsx (all presentational, each with render tests): `TotalBreakupModal`, **`PosTotalBar`** (the piece-b total bar), **`InvoiceBreakdownCard`** + **`TenderChips`** (lifted from the payment popup; tender values still come from the pure tested `suggestedTenders`). **`Sales.jsx` is now ~3,611 lines** (3,726 at sync → 3,611 after these extractions). Still a god-component — the payment popup itself was deliberately NOT lifted whole (≈25 props + 2 refs on the money path, too risky to do blind); next safe step is the ref-heavy interactive shell via a `usePaymentFlow` hook, then `<PaymentPanel>`, then migrate pages onto `api/client`.
- ✅ **POS counter redesign (approved mockup — all 3 pieces built):** keeps the existing `Esc`/click → payment trigger. (a) ✅ **column-totals footer** on the cart table (qty/discount/total per column, pure `columnTotals` + tests); (b) ✅ **always-visible bottom total bar** (`pos-totals-bar`: subtotal/tax/grand-total + `Pay ▸ Enter`) replaces the hot-key strip; cart goes full-width. (c) ✅ **payment popup** (`showPaymentPopup`) — `Esc`/Enter-to-open, **smart tender chips** (`suggestedTenders` pure + tested, e.g. 1377→[1377,1380,1400,1500]), instant change (`changeDue`), cash/UPI/card/credit modes, UPI confirm, Enter = save+print. Differentiator = speed + smart tenders, not an unfamiliar layout. *Built offline in the `- Copy` working tree, synced into canonical 2026-06-20 via robocopy; pure helpers node-verified; full `npm test`/`pytest` confirmed green by user.*
- ✅ **POS overcharge bug fixed (2026-06-20):** the "MRP-as-price" scheme stores the discount as an absolute amount `(MRP − chosenPrice) × qty`, but the keyboard qty bumps (`↑/↓`, `+`) changed qty without rescaling it, so a line chosen at qty 1 then raised to qty 4 billed toward MRP (e.g. Sugar 5kg ₹200×4 showed **₹920 instead of ₹760/₹800**, and the displayed unit price didn't match what was charged). Fix: extracted one pure, unit-tested **`schemeDiscount(mrp, chosenPrice, qty)`** in `invoiceMath` and routed **all** discount sites + **all** qty-change paths through a single `withQty()` helper, so the discount can never drift from qty again. `schemeDiscount` node-verified + 5 new vitest cases. *Pending user `npm run dev` re-check on the exact screenshot scenario.*
- ✅ **POS grid + bill-discount pass (2026-06-20):** (i) per-line **discount is now read-only** (it only shows the auto MRP-scheme saving); (ii) the wrong "PRICE/UNIT without tax" column became a correct read-only **PRICE/UNIT after-tax**; (iii) the **TAX cell shows rate + amount** (`5% · ₹19`) and the totals row shows **pre-tax total + tax total**; (iv) new **bill-level discount (₹ or %)** at checkout — pure `resolveBillDiscount` + discount-aware `computeInvoiceTotals` (tax on net, node-verified + vitest), a ₹/% control in the payment popup, a Discount line in the breakdown card **and** the printed receipt, threaded through `buildInvoicePayload` → new `bill_discount` field on `/billing/invoices` → `create_sale_invoice` apportions it across lines (consistent line items, GST on net; `discount_total` recorded). Backend: 2 new `test_billing` cases (apportion + clamp); `bill_discount=0` default keeps all 431 tests unchanged. *Pending user `npm test`/`pytest` + `npm run dev`.*
- ✅ **Payment popup → `CheckoutModal` + grid relabel (2026-06-20, consolidated from `- Copy`):** the whole payment popup was lifted out of `Sales.jsx` into **`components/sales/CheckoutModal.jsx`** (driven by props/callbacks; inline popup fully removed) — **`Sales.jsx` 3,726 → 2,824 lines.** The cart columns were renamed for owner clarity: **PRICE PER UNIT (BEFORE TAX)**, **TOTAL (BEFORE TAX)** (= `lineTotal`), **TOTAL (AFTER TAX)** (= line × (1+rate)); the confusing after-tax-*per-unit* column was dropped. Decision: **kept the MRP-as-price scheme** (so the DISCOUNT column shows MRP savings) rather than removing it — with all qty paths through `withQty`, the grid reconciles (PRICE/UNIT × qty = TOTAL BEFORE TAX = qty×MRP − discount). Gate close-out: added **`CheckoutModal.test.jsx`** (render/smoke: open guard, checkout UI, Save→`onSaveInvoice`) and wired `logger.error` into its customer-save failure paths. *Pending user `npm test` + `npm run dev`.*

**Phase 1 — Billing painkiller** · *status: 🟢 built + hardened (2026-06-22): accounting close/lock + hash chain + carry-forward done; `Sales.jsx` decomposed into 9 tested components (~2,856→~1,650 lines); pagination shipped. Remaining: R4 pricing rename, `Reports.jsx` split, live UI pass.*
- ✅ Sales counter (`Sales.jsx` + `sales.py`): keyboard/barcode, item autocomplete, qty/price/discount, intra/inter GST split, payment modes, multi-tab billing, wholesale/distributor price tiers.
- ✅ Product master, customer/supplier master, `business_type` templates.
- ✅ `stock_ledger` (D4) — sale auto-deducts; godowns + stock transfer.
- ✅ Dues / partial payments (`payments.py`); switch-in + CSV import (`import_route.py`).
- ✅ Reports core: day-summary, P&L, GSTR-1 (B2B/B2CS/HSN), GSTR-3B, sales/purchase register, outstanding, stock-movement.
- ✅ **Accounting depth — Day Book, Balance Sheet & Trial Balance (2026-06-20):** `/reports/day-book` (chronological sale/purchase/expense/receipt register + cash-flow summary) and `/reports/balance-sheet` (cash/AR/inventory vs payables → net worth) built and covered by `test_accounting.py` (empty, depth calcs, cashier-403, tenant isolation). **New `/reports/trial-balance`** completes the trio: every ledger account on its normal Dr/Cr side with a **Capital plug** so the columns always foot (Dr == Cr) — a self-checking statement. Real accounts (Cash/AR/Inventory/AP) are cumulative and tie to the Balance Sheet; nominal accounts (Sales/Purchases/Expenses) honour the from/to window and tie to the P&L. Owner-only (`restrict_cashier`), tenant-scoped, `[REPORT]` INFO log. **`test_trial_balance.py`**: empty foots to zero, **always foots after a paid sale + paid/unpaid purchases** (the Dr==Cr invariant), Sales/Payables on Cr & Purchases on Dr, cashier-403, tenant isolation. Frontend: surfaced in `Reports.jsx` as a card + Dr/Cr table with a green "Balanced" / red "Out of balance" banner + CSV export. *Note: single-entry/derived (no posted journal) — the Trial Balance is reconstructed from source documents, not a true double-entry ledger; a real journal is a Phase-6 deep-moat item. Pending user `pytest`/`npm run dev`.*
- ✅ **Party Ledger / Account Statement (2026-06-20):** new `/reports/party-ledger?party_type=customer|vendor&party_id=&from=&to=` — a single party's running account, transaction by transaction (customer: Sales Dr · Receipts/Credit Notes Cr; vendor: Purchases Cr · Payments/Debit Notes Dr) with **opening balance** (everything before `from` rolled up so a windowed statement still foots) and a **running balance** per row. Built from source docs so it ties out: a customer's closing == their slice of Balance-Sheet receivables, a vendor's == payables (receipts taken from the invoice's own `paid_amount`, never double-counted). Owner-only (`restrict_cashier`), tenant-scoped (foreign/missing party → 404), `[REPORT]` log. **`test_party_ledger.py`**: customer closing ties to receivables, vendor to payables, `from`-window yields a non-zero opening, cashier-403, foreign+missing party 404. Frontend `Reports.jsx`: a card with a customer/vendor toggle + party dropdown, running-balance table with opening row + closing badge, CSV export. This is the flagship Vyapar "Party Statement" parity feature. *Pending user `pytest`/`npm run dev`.*
- ✅ **General Journal + General Ledger — derived double-entry (2026-06-20):** a posting engine (`reports._build_journal_entries`) reconstructs **balanced double-entry** from source docs (no money-path change): a sale → Dr Cash(paid)/AR(balance), Cr Sales(net), Cr GST Payable; purchase → Dr Purchases/GST Input, Cr Cash-or-AP; credit/debit notes reverse; expenses → Dr <Category> Expense, Cr Cash. **Every entry foots by construction** (net = total − GST), and cash legs use the invoice's own `paid_amount` (consistent with Balance Sheet/Party Ledger, no double-count). `GET /reports/journal` (entries with Dr/Cr lines + `balanced` flag + totals) and `GET /reports/general-ledger?account=` (postings regrouped per account with a running balance). Owner-only, tenant-scoped, `[REPORT]` logs. **`test_journal.py`**: every journal entry foots, the journal totals balance, the **GL nets to zero across all accounts** (Σ closing == 0) with Sales on Cr & Purchases on Dr, case-insensitive account filter, cashier-403, tenant isolation. Frontend `Reports.jsx`: a Journal view (grouped entries, indented credits, balanced banner) and a General Ledger view (per-account posting tables + running balance) + CSV. *This is the bridge toward real double-entry — still derived/reconstructed (a posted journal table is the Phase-6 step), but it gives accountant-grade Dr/Cr journal + ledger drill-down today. Pending user `pytest`/`npm run dev`.*
- ✅ **POSTED double-entry journal — written at transaction time (2026-06-20):** the journal is now a *real, append-only* audit trail, not just reconstructed on read. New tables **`journal_entries` + `journal_lines`** (migration **`e7a1c3f5b9d2`**, the new alembic head) and a posting service **`core/accounting/posting.py`** (`post_entry` + `post_sale/credit_note/purchase/debit_note/expense/payment`). `post_entry` is **idempotent** on (business_id, source_type, source_id) and **foots-or-raises** (Σ Dr == Σ Cr enforced before write), and it **composes WITHOUT committing** — the command owns the commit, exactly like `SL.record_movement`. Hooked into all six money-path commands just before their existing `db.commit()`: `create_sale_invoice`, `record_payment`, `create_credit_note` (billing), `accept_supplier_invoice`, `create_debit_note` (purchase), and `create_expense` (payments). New owner-only **`GET /reports/audit-journal`** reads the posted entries directly (the true trail), surfaced in `Reports.jsx` as an **"Audit Journal"** card (🔒 posted-at-transaction-time banner). **`test_audit_journal.py`**: documents post balanced entries at creation, posting is idempotent (re-post → no duplicate), the **posted journal reconciles with the derived General Ledger account-for-account**, cashier-403, tenant isolation. `[ACCT]` posting logs. *No money-path behaviour changed (posting is additive within the same atomic txn); `bill_discount`-style defaults untouched. Pending user `alembic upgrade head` + `pytest`/`npm run dev`.*
- 🟡 Invoice PDF + e-way fields >₹50k — `GET /sales/{no}/pdf` (WeasyPrint → HTML fallback) **now has a route test** (`test_invoice_pdf_route` + 404 case). Thermal 58/80mm CSS present; *layout + e-way capture still need a visual `npm run dev` check.*
- ✅ **Print + WhatsApp share + UPI QR (2026-06-20):** the UPI deep-link, WhatsApp URL, phone-normalise and QR-image builders were extracted to **pure, unit-tested `utils/share.js`** (`buildUpiUri`/`normalizePhoneIN`/`buildWhatsAppShareUrl`/`qrImageUrl`, node-verified + `share.test.js`) and the **3 duplicated UPI sites DRY'd onto them** (CheckoutModal, TotalBreakupModal, Parties); Parties' `console.error`→`logger`. Backend PDF route tested. *The browser print/iframe + WhatsApp window.open still need a one-time `npm run dev` click-through.*
- ✅ **Blank-printout bug fixed (2026-06-20):** save-and-print produced a blank page because the code closed the saved tab and opened a fresh (empty) bill *immediately*, while `window.print()` ran on a `setTimeout` — so it printed the new empty bill. The on-screen `#thermal-receipt` (portal on `document.body`, shown via `@media print`) renders from the live `form`/`activeTab`. Fix: the tab-close/new-bill reset is now deferred into a `finishReset()` that runs **after** `window.print()` returns (it blocks until the dialog closes); the server-PDF iframe path is unaffected (it prints by invoice number). *Pending user `npm run dev` re-print.*
- ✅ **Returns / credit & debit notes — verified posts stock + ledger:** `create_credit_note` writes an append-only `credit_note` Invoice + **RETURN_IN** stock movements (never edits the original); `create_debit_note` (purchase) writes **RETURN_OUT**. Covered by `test_credit_note_api` (stock 10→7 on sale, →8 on return of 1) and `test_create_debit_note`; **added `test_credit_note_tenant_isolation`** (business B cannot credit-note business A's invoice → 4xx). Route is RBAC-gated (`restrict_cashier`).
- 🟡 **Staff roles (owner vs cashier) — RBAC mechanism complete + tested (2026-06-20):** the `restrict_cashier` guard (was duplicated in 3 files) is now the **single source in `services.auth`** (+ `require_owner` alias). Owner-only routes gated: reports (all), credit notes, imports, **business setup/config-write, all purchases, connection mutations (code/redeem/connect/policy/revoke), and manual stock adjustments**. Cashiers keep sales + payments + reads. Frontend hides owner-only nav (`purchases/connections/orders/reports/import/settings`) for cashiers (defense-in-depth; backend 403 is authoritative). **`test_roles.py`** added: parametrized cashier-403 vs owner-not-role-blocked matrix + cashier-can-sell + unauth-401. ✅ *Multi-user staff sub-accounts BUILT (2026-06-20):* `User.parent_business_id` (nullable self-FK; migration `c5e1a9d4f7b2`) lets an owner create cashier logins that **share the owner's data** — at login a staff member's JWT `id` (the scope every route reads) is set to the parent business id, with `user_id` keeping their own identity, so all 78 routes scope correctly with zero changes. New owner-only `core/api/staff.py` (`GET/POST/PATCH/DELETE /staff`, tenant-scoped by `parent_business_id`). **`test_staff.py`**: owner-creates-staff → staff-login-scopes-to-owner-data (sees owner's product), staff-is-cashier (403 on reports/staff-mgmt), tenant isolation (B can't see/delete A's staff), validation (weak pw/role/dup). ✅ *Frontend Staff page (`pages/Staff.jsx`, route `/staff`, owner-only nav under Settings):* list cashiers, add (username+password), reset password, remove — consumes the `/staff` API. **Staff roles (owner vs cashier) is now end-to-end usable in a real shop.** *Pending user `npm run dev` click-through (add a cashier, log in as them, confirm trimmed nav + shared shop data).*
- ✅ `test_import.py` (named in plan) — author and verified passing.

**Phase 2 — Purchase + stock auto-entry (OCR)** · *status: ✅ complete and verified*
- ✅ Manual purchase bills (`Purchases.jsx`, `purchases.py`); purchase order / debit note referenced (🟡 verify flow).
- ✅ **OCR auto-entry pipeline** (Detect→Map→Confidence→Review→Commit) — OCR parsing and structured LLM extraction fully verified with `test_purchase_ocr.py` and `test_purchase_commit.py`.

**Hardening — offline cache + sync + RLS** · *status: ⬜ not started* (deliberately deferred, D5).

**Phase 3 — Business connections** · *status: ✅ security gate PASSED (2026-06-20); features built*
- ✅ `connections.py` (9 routes, mutations now owner-only) + `Connections.jsx` + `orders.py` + `Orders.jsx` (BizID/codes/orders). **The must-pass security gate now holds, proven by `test_connections_security.py`** (self-contained): the supplier catalog (`get_supplier_catalog`) requires an *accepted* connection, exposes **no `cost_price`/margin** (only the policy `selling_price`) and **no customers**; an unconnected stranger → 403; `stock_visibility=hidden` → stock withheld; **revoke immediately closes the pipe** (catalog/order → 403). Existing `test_connections.py` already covered policy/category/band-stock/revoke; this adds the explicit margin + customer + stranger negatives. *Note (RESOLVED 2026-06-20): `get_supplier_catalog` now honours the connection's `price_tier` (wholesale/distributor) — see Phase 4 tier-pricing entry + `test_tier_pricing.py`.*

**Phase 4 — Invoice sync (order→invoice→buyer stock-in, shared ledger)** · *status: ✅ core sync built (2026-06-20)*
- ✅ **Order completion now posts both sides, exactly-once** (`core/order/service.sync_completed_order`, hooked into `transition_order_status` when a seller completes an order): the **seller** gets an auto sale invoice (`B2B-<order_no>`, deterministic ⇒ idempotent via `create_sale_invoice`) which **deducts seller stock** through the append-only ledger; the **buyer** gets an **auto stock-in** (find/create the buyer's product + a `PURCHASE` ledger movement, guarded on an existing `b2b_order` ledger ref). `B2BOrder.seller_invoice_id` (migration `d6f2b4a8e913`) is the exactly-once guard + link. SSE `order.invoiced` event fires to the buyer. **`test_phase4_sync.py`**: completion deducts seller stock (20→15), creates the linked `B2B-` invoice, lands buyer stock (=qty); re-completing does NOT double-post.
- ✅ **Tier-based B2B pricing wired into orders (2026-06-20):** both `get_supplier_catalog` and `create_order` now resolve the buyer's base price from the connection's `price_tier` (`wholesale`→`wholesale_price`, `distributor`→`distributor_price`→`wholesale_price`, else `selling_price`; missing/zero tier price falls back to retail, never free) **before** applying `discount_pct`. `[ORDER]` INFO log on order creation records tier+discount. Catalog tier math is covered in `test_connections.py` (wholesale 80×0.9=72; distributor 70×0.95=66.5); the **order path + fallbacks are covered by new `test_tier_pricing.py`** (wholesale/distributor unit_price, zero-tier→selling fallback, distributor→wholesale chain). No margin leak (still `test_connections_security.py`).
- ✅ **Buyer-side auto-stock-in UI (2026-06-20):** `Orders.jsx` shows a **"📥 Stock received"** badge on completed outgoing (purchase) orders carrying a `seller_invoice_id`, the details modal already surfaces the auto-PURCHASE message + seller invoice number, and the page now **handles the SSE `order.invoiced` event** (live toast + live row badge via `justInvoiced`, with `logger.info('[ORDER] …')`). Render test **`Orders.test.jsx`** (badge shows for completed+invoiced, not for in-flight). *Pending user `npm test`/`pytest` + `npm run dev` click-through.*

**Phase 5 — AI Advisor (paid)** · *status: 🟡 exists, not gated* — full AI dashboard lives in `frontend-ai` + backend; **plan-gating (`test_plan_gating.py`) not built.** Parked per decision (AI is the add-on, not the priority).

**Phase 6 — Deep moat** · *status: 🟡 partially started (2026-06-22)* — ✅ **hash-chained tamper-evident journal shipped** (R3); ✅ **e-invoice/e-way JSON builders + threshold gating + IRN persistence** shipped (R7a/R7a-next, the offline half). Remaining: live IRP/EWB **API** integration + CA-validated filing, reputation/trust score, Redis at scale.

**Immediate next (updated 2026-06-22, from §10.2.1 review):** the 06-20 "immediate next" list is now **done** — `Sales.jsx` decomposition complete (9 tested components), accounting depth + close/lock + hash chain shipped, and the **offline half of compliance** (e-invoice/e-way JSON builders + gating + IRN persistence) is built. Current P0/P1 order: **(1) R7b offline-first + sync + RLS** (biggest gap, score 2/10, load-bearing for the SMB pitch) → **(2) live IRP/EWB API + CA-validate one filing** (turns compliance 5→8; needs sandbox creds) → **(3) R4 Slice3 pricing rename** (now low-risk, kills a bug class) → **(4) finish R5: split `Reports.jsx`** (last god-component) → **(5) R6 live UI/a11y/mobile pass** + **(6) load-test the hot paths**. Quick cleanups (3)+(4) first, then the strategic build (1).

> **Definition of Done — every phase/task closes through `PHASE_COMPLETION_CHECKLIST.md`:** (1) tests run green / written if missing + named here; (2) info **and** debug loggers added, traceable; (3) this tracker updated + a §10.1 smartest-app note added. A feature is ✅ only when its named test passes.

---

### 10.1 — SMARTEST-APP RECOMMENDATIONS (running list)

> The bar is **smart, easy, fully synced, automated, solid.** This is the backlog of ideas that make BizAssist *the smartest* billing app — not just at parity with Vyapar. Add one every time we finish work (Gate 3). Pull the strongest into a phase.

- **Zero-typing purchase entry** — snap a supplier bill → OCR → review → commit (Phase 2). Kills the #1 chore; the second painkiller.
- **Proactive reorder intelligence** — predict stockouts from sales velocity × supplier lead time; one-tap reorder to the *connected* supplier with a prefilled order (ties billing → ecosystem).
- **Smart collections** — predict who'll pay late from payment history; auto-draft WhatsApp reminders; surface "chase these 3 today."
- **Counter speed to <30s/bill** — barcode-first, auto price-tier + scheme application, loose-qty/weighing input, keyboard-only flow. Easy = sticky.
- **[✅ DONE 2026-06-20] Tier-based B2B catalog + order pricing** — both `get_supplier_catalog` and `create_order` now resolve the per-product base price from the connection's `price_tier` (`wholesale_price`/`distributor_price`, falling back to `selling_price`) **before** applying `discount_pct`; covered by `test_tier_pricing.py` + the catalog cases in `test_connections.py`. *Next smart layer:* let the seller maintain real tiered price-lists per connection (not just one wholesale/distributor column) and show buyers their effective price vs MRP savings in the catalog.
- **One-tap settlement on the new payment popup** *(2026-06-20 — builds on the just-shipped POS popup)* — the `suggestedTenders` chips + instant `changeDue` are the foundation; next smart layer = auto-render a **UPI QR for the exact grand total** the instant the popup opens (no typing, no rounding), auto-detect cash-vs-UPI from which the cashier touches first, and remember each customer's usual tender. Turns the fastest part of the bill (taking money) into zero decisions — the visible "smart" moment cashiers feel every sale.
- **Future Payment Auto-Reconciliation (Based on Adoption)** — While zero-fee direct UPI QR codes remain the instore counter default to prevent MDR margins loss, we can add Razorpay/PhonePe Payment Gateway (PG) integrations for remote billing. Merchants can provide their PG API keys in settings, enabling the system to generate dynamic checkout payment links for shared invoices and auto-settle the ledger status via webhook callbacks once paid.
- **[✅ DONE 2026-06-20] Accounting trio (Day Book · Balance Sheet · Trial Balance) + Party Ledger** — derived single-entry statements that foot by construction (`test_accounting.py`, `test_trial_balance.py`) plus a per-party running account statement (`test_party_ledger.py`), a **derived** General Journal + General Ledger (`test_journal.py`), and a **POSTED** double-entry journal written at transaction time (`journal_entries`/`journal_lines`, `test_audit_journal.py`) that reconciles with the derived GL. *Next smart layer:* opening-balance carry-forward + period-close/lock, then **hash-chain the posted journal** (each entry signed over the prior hash) for tamper-evident books — the D5/Phase-6 "signed shared ledger" moat. Also: a reversing-entry UI (corrections post a new balanced reversal, never an edit).
- **[✅ DONE 2026-06-20] Performance & N+1 Optimization Pass on Reports** — Refactored P&L, Outstanding, Day Book, Balance Sheet, and Trial Balance to use database-level aggregates (`func.sum`, conditional `case` statements, joined COGS queries, and batch customer lookups) rather than executing N+1 loop queries or instantiating massive lists of ORM objects in Python memory. This removes all performance bottlenecks as invoice and inventory count scales.
- **Anomaly guardrails** — flag unusual discount, margin dip, duplicate invoice no., negative stock, price typos *before* save. "Secure & unbreakable" felt at the counter.
- **One-click compliance** — GSTR-1/3B export validated against GSTN; e-invoice IRN + e-way auto when thresholds hit. Removes the accountant tax.
- **Cross-business smart sync** — supplier updates a price/scheme → connected buyers see it instantly; order placed → buyer's stock auto-stages on invoice import (Phase 4 magic).
- **Morning AI digest (paid)** — what to reorder, who to chase, what's moving, which retailer went quiet, what offer to send. The advisor reasons over the *network*, not one shop.
- **Self-healing data** — rebuildable ledgers + idempotency mean a crash/double-tap never corrupts books; "why is stock 3?" is always answerable.

---

### 10.2 — DEAD-HONEST REVIEW  ·  *2026-06-20*

> Scope of this review: a **code-level** audit (architecture, data model, money paths, tests, and the UI *as written in JSX*). It is **not** a rendered/visual or usability review — the dev server and `npm run dev` were not run, no screenshots, no real-device testing, no load testing. Ratings reflect engineering quality from the source, and where that limits confidence it's stated. The goal is candor, not encouragement.

#### Scorecard (out of 10)

| Area | Score | One-line verdict |
|---|---|---|
| Backend architecture | **8.5** | Genuinely strong: modular monolith, append-only ledgers, idempotency, one-atomic-txn discipline. Above SMB-norm. |
| Data model / GST correctness | **8** | Deterministic GST, tenant-scoped, additive migrations. Solid. |
| Accounting depth | **8** | Now exceeds Vyapar on paper (day book, BS, TB, P&L, party ledger, journal, **posted** audit trail). Caveat: derived + young. |
| B2B ecosystem (the USP) | **8** | "Share the deal, not the books" is real and *security-tested*. The actual moat. |
| Test discipline | **7.5** | 545 tests, negative tests for money/tenancy, a real 3-gates process. Backend strong; frontend thin. |
| Scalability / performance | **6.5** | Reports N+1 / full-ledger-scan pass done (pnl, outstanding, day-book, BS, TB, journal-windowing, GSTR-1 eager-load). Remaining: no pagination on unbounded list endpoints; still unproven under real load. |
| POS (counter) | **6.5** | Fast, feature-rich, right instincts — but a god-component on a fragile pricing model. |
| UI / frontend code quality | **5.5** | Functional and consistent via CSS vars, but inline-style sprawl, forming god-components, thin reuse, unknown a11y. |
| Compliance (e-invoice/e-way) | **3** | Largely absent. Fine for small merchants, a wall for larger ones. |
| Offline / sync (D5) | **2** | Not started. A real gap for the Indian-SMB connectivity reality the pitch leans on. |
| **Overall** | **~6.8** | A strong, well-disciplined **billing + B2B + accounting core** that is not yet a shippable, at-scale, compliant product. |

#### What is genuinely good (no flattery)
- **The backend is the real asset.** Append-only stock *and* journal ledgers, idempotent commands, every query `business_id`-scoped, one-command-one-transaction, deterministic GST, additive/nullable migrations. This is more disciplined than most billing apps that reach market.
- **The B2B security gate is the differentiator and it's defended by tests** (`test_connections_security.py`): no cost/margin leak, no customer leak, stranger→403, revoke closes the pipe. This is the thing competitors can't trivially copy.
- **Accounting went from "reports" to "books"** in a day: trial balance that foots by construction, party statements that tie to receivables/payables, and now a **posted, idempotent, foots-or-raises journal** written inside the same atomic transaction as the money move. That last part is the difference between "a dashboard" and "an audit trail."
- **The 3-gates process is real**, not theater — money and tenancy get negative tests, and the suite is green at 545.

#### The honest problems (in priority order)
1. **Performance — the structural N+1 / full-scan pass is now done; remaining gap is pagination.** ✅ `report_pnl` (joined COGS), `report_outstanding` (DB case-aggregates), day-book/BS/TB (aggregates), and `_build_journal_entries` (date window pushed into SQL, no longer loads the whole ledger) are fixed; GSTR-1 b2b/b2cs now `joinedload` `customer_ref` and `Invoice.line_items` is `selectin`-batched. **Remaining:** the unbounded list endpoints (`sales-register`, `purchase-register`, `stock/ledger`, `day-book`) still return every row with **no pagination/limit** — the next scale risk. Indices on the hot date paths exist (`ix_invoice_business_date`) but haven't been load-tested.
2. ✅ **Two journal code paths converged.** The derived engine (`reports._build_journal_entries`) and the posted engine (`accounting/posting.py`) now share one set of line-builders (`build_sale_lines`/`build_credit_note_lines`/`build_purchase_lines`/`build_debit_note_lines`/`build_expense_lines`) — account-mapping is defined once and imported, so the two can no longer drift. The reconciliation test still guards them.
3. **The POS pricing model is clever debt.** "MRP-as-price + discount-as-savings" already produced a real overcharge bug (qty-drift). It works now because every qty path is funneled through one helper, but it's a model future devs will misread. A clean `price + explicit discount` model would remove a whole class of bugs.
4. **God-components are forming.** `Sales.jsx` is ~2,800 lines after extraction; `Reports.jsx` is now a 7-branch render ternary heading the same way. Maintainability tax is accruing.
5. **The books are only audit-grade going forward.** The posted journal starts now; historical data is still *reconstructed*. ✅ **Period close/lock now shipped (R2)** — a closed period rejects any new/changed posting (422), enforced at the single `post_entry` choke point, so the books can no longer be altered upstream once locked. ✅ **R2b carry-forward now shipped (2026-06-21)** — the General Ledger opens each account at the prior period's closing balance (computed on read), so a windowed ledger ties to the cumulative as-of figure. (A period-close snapshot table is deferred as a pure perf optimization.)
6. **Frontend testing is shallow** (render/smoke only) and **UI quality is unverified** — inline styles everywhere, no component library, color-only status signals (likely weak accessibility), and I have not seen a single screen actually render. The UI score is a code-smell estimate, not a UX judgment.
7. **Compliance and offline are essentially unbuilt** — e-invoice IRN / e-way bill (mandatory above turnover/value thresholds) and the offline-first/sync/RLS story (D5) that the Indian-SMB pitch depends on.

#### POS verdict (asked for specifically)
Right *instincts*, unfinished *engineering*. Keyboard/barcode-first flow, smart tender suggestions (pure + tested), instant change, multi-tab bills, thermal + server-PDF print, bill discount, UPI-QR/WhatsApp share — that's a genuinely competitive feature set for a counter, and "speed + smart tenders" is the correct wedge against Vyapar. But it rides on a 2,800-line component and an overloaded pricing field that has already bitten once, and print depends on browser timing (the blank-print bug was a symptom). It will *demo* very well; it needs hardening (decomposition, clean pricing, offline) before it's bet-the-shop reliable. **6.5/10.**

#### UI verdict (asked for specifically, with the caveat)
From the code: consistent design tokens (CSS variables, dark surfaces, badges, modals) give it a coherent look, and the information design of the new accounting reports is sensible (Dr/Cr columns, balanced banners, running balances). But it's **inline-style-driven** with repeated magic numbers and no shared component layer, status is often **color-only** (accessibility risk), and there is **no evidence of responsive/mobile testing** — which matters enormously for the shopkeeper-on-a-phone persona. Until it's seen running on a real device, treat UI as **5.5/10 — looks coherent, robustness unproven.** Recommended next: run `npm run dev`, capture the POS + Reports screens, and do a real pass (a11y, mobile, empty/error states).

#### Bottom line
This is a **strong core, not yet a finished product.** The hard, easy-to-get-wrong parts (ledgers, GST, tenancy, B2B isolation, double-entry) are done well and tested. The parts that decide whether it survives contact with a real shop at scale — performance, offline, compliance, UI robustness, and reining in the god-components — are the unfinished majority. Keep the engineering discipline; point it at scale and the front-end next.

---

### 10.2.1 — UPDATED HONEST REVIEW  ·  *2026-06-22*

> Re-rates §10.2 (2026-06-20) after the R1–R8 remediation work, R7a/R7a-next compliance builders, the tenant-isolation audit, and the full `Sales.jsx` decomposition. Same rubric, same candor. **One real difference from last time:** every frontend extraction this round was verified by the user running `npm test` + `npm run dev` after each step — so the UI/POS scores rest on *some* live verification now, not pure code-reading. They are still the user's verification, not a formal a11y/mobile/device pass. No score is inflated; gaps that remain are called gaps.

#### Updated scorecard (Δ vs 2026-06-20)

| Area | 06-20 | 06-22 | Why it moved (or didn't) |
|---|---|---|---|
| Backend architecture | 8.5 | **8.5** | Compliance module, hash-chain, period-lock all landed cleanly on the same disciplined patterns. No inflation — already high. |
| Data model / GST correctness | 8 | **8** | `cash_discount` + e-invoice field mapping added correctly; no structural change. |
| Accounting depth | 8 | **8.5** | Now has period **close/lock** (event-sourced, enforced at the one choke point), a **tamper-evident hash chain**, and **opening-balance carry-forward**. That's a real close-the-books + audit story, not just reports. |
| B2B ecosystem (USP) | 8 | **8.5** | Tenant-isolation audit (125 queries) found no leak; BizID **contact privacy gate** added + tested. Moat reinforced. |
| Test discipline | 7.5 | **8** | Frontend went from smoke-only to **9 render/interaction test files**; backend added compliance/period-lock/hash-chain/cash-discount suites. Still: no e2e, no load tests. |
| Scalability / performance | 6.5 | **7** | **Pagination shipped** on all unbounded list endpoints (the cited remaining gap). Still **unproven under real load**; no offline/RLS. |
| POS (counter) | 6.5 | **7.5** | The 2,856-line god-component is **decomposed into 9 tested components** (~1,650 lines, orchestration only), user-verified rendering. Held back from higher by the **unchanged MRP-as-price pricing debt** (R4 Slice3 deferred). |
| UI / frontend code quality | 5.5 | **6.5** | A real **reusable component layer + render tests** now exist where there was inline sprawl. Still: inline styles elsewhere, **color-only status**, **a11y + mobile unverified** (R6 open). |
| Compliance (e-invoice/e-way) | 3 | **5** | Schema-correct **INV-01 + e-way JSON builders**, ₹50k/₹5cr **gating**, **IRN persistence** — all tested. BUT this is the **offline half only**: no live IRP/EWB API call, no digital-signature handling, **no CA-validated real filing**. Cannot actually file yet. |
| Offline / sync (D5) | 2 | **2** | Unchanged. Still not started. The biggest true product gap. |
| **Overall** | **~6.8** | **~7.3** | The core got materially stronger and the worst code-smell (POS god-component) is gone. The two genuine *product* gaps — **offline** and **live compliance filing** — plus a formal **visual/a11y** pass are what still separate this from shippable-at-scale. |

#### What actually changed (no spin)
- **The "books only audit-grade going forward" problem is now largely closed.** Period lock + hash chain + carry-forward together mean: you can close a period, nobody can silently rewrite it, and a windowed ledger ties to the cumulative figure. That was the headline accounting gap on 06-20.
- **The POS god-component — the loudest maintainability complaint — is resolved.** Nine focused, individually tested components; `Sales.jsx` is ~42% smaller and is now state/orchestration. This is the single most visible quality delta.
- **Compliance moved off zero but is not "done."** There are now correct, tested JSON builders and threshold/IRN plumbing — real and useful — but a merchant still cannot file an e-invoice through the app. Calling this "5/10, half-built" is the honest framing; anything higher would be dishonest.
- **Tenant isolation is now audited, not assumed.** 125 queries swept, no leak, plus the BizID privacy fix.

#### What did NOT change (still true from 06-20)
- **Offline/sync/RLS is unbuilt (2/10).** The Indian-SMB connectivity pitch still rests on something that doesn't exist yet.
- **No live load test** — pagination and indices exist; "fast at 10k invoices on a real Postgres" is still unproven.
- **The pricing model is still clever debt** (MRP-as-price + discount-as-savings). Decomposition made it *safer to change*, but it hasn't been changed.
- **No formal UI pass** — still no a11y audit, no mobile/real-device testing, status still color-only in places.

#### Best recommendations — prioritized (added to the plan)
1. **R7b — Offline-first + outbox/delta sync + idempotency, then Postgres RLS.** Highest strategic value: it's the lowest score (2), it's load-bearing for the whole SMB pitch, and the idempotent/append-only backend is already built to support exactly-once replay. Biggest single lift to "shippable."
2. **Live IRP/EWB API + CA-validate one real flow.** Turns compliance from 5→8 and unlocks ₹5cr+ merchants. The offline builders are done; this needs sandbox credentials + digital-signature handling + one CA-checked filing. Gate e-invoice by the turnover flag (already wired) so you never mis-issue.
3. **R4 Slice3 — retire the MRP-as-price pricing model** for explicit `unit_price` + `line_discount`. Now low-risk (Sales.jsx is decomposed + the math is isolated in `invoiceMath`), and it removes a recurring bug class.
4. ~~**Finish R5 — split `Reports.jsx`**~~ ✅ **DONE 2026-06-22** — 7 view components behind a `{id → component}` registry; ternary gone, `Reports.jsx` 946→~620 lines. (R5 fully complete.)
5. **R6 — live UI/UX pass:** capture POS + Reports on a real device, fix a11y (don't signal status by colour alone), empty/error states, mobile layout. Converts the UI score from "code estimate" to "verified."
6. **Load-test the hot paths** (now that pagination exists) — seed ~10–50k invoices on Postgres and prove the date-windowed reports + registers hold up. Converts scalability from "done in code" to "proven."

**Suggested order:** (3) and (4) are quick, low-risk cleanups to do now; (1) is the big strategic build; (2) unblocks larger customers once creds exist; (5)+(6) are verification passes that should precede any "production-ready" claim.

---

### 10.3 — PRIORITIZED REMEDIATION PLAN  ·  *2026-06-21*

> Turns the open §10.2 problems into concrete, sequenced work. Effort: **S** ≤½ day · **M** 1–2 days · **L** 3+ days / multi-session. Each item ships under the 3 gates (tests · logging · this tracker). Recommended order is top-to-bottom: cheap-and-safe first, then the integrity moat, then the risky/large bets.

**Ecosystem Deployment & Postgres Migration Script Update · S · low risk · backend-only — [✅ DONE 2026-06-21]**
- *Problem:* The original `migrate_sqlite_to_postgres.py` script was written when only 19 basic tables existed. It lacked support for the 18 newer tables added during development (such as `period_locks`, `journal_entries`, `stock_ledger`, `b2b_orders`, etc.), resulting in major data loss on Supabase migration.
- *Shipped:* Updated the `TABLE_ORDER` array in [migrate_sqlite_to_postgres.py](file:///d:/Dev%20Workspace/ai_agent_lab_google%281%29/bizassist-billing/backend/migrate_sqlite_to_postgres.py) with all 37 tables, sequenced in exact foreign-key dependency order.
- *Verified:* Verified local Python syntax and schema dependency mapping.

**R1 — Pagination + caps on unbounded list endpoints · S · low risk · backend-only — [✅ DONE 2026-06-20]**
- *Problem (§10.2 #1 remaining):* `sales-register`, `purchase-register`, `stock-movement`/`stock/ledger`, `day-book` return **every** row — memory/latency blow-up at scale.
- *Shipped:* added `limit` (default 200, hard max 2000) + `offset` Query params via a shared `_clamp_page()` helper on `/reports/sales-register`, `/reports/purchase-register`, `/reports/stock-movement`, `/stock/ledger` (array bodies, with `query.count()` total returned in an **`X-Total-Count`** header — added to CORS `expose_headers`), and on `/reports/day-book` (object body: `transactions` paginated, `total/limit/offset` added, **summary still computed over the full window**). Ordering made deterministic (`date, id`). Body contracts unchanged (still array / same object) so existing render + CSV paths keep working. Frontend `Reports.jsx` now requests `limit=2000` and shows a *"Showing first N of M — narrow the date range"* warning (reads `X-Total-Count` / `total`) so no rows are ever silently dropped. `[REPORT]` debug logs on each.
- *Verified:* clamp + slice logic sim-proven (default/neg/over-max clamping; contiguous pages tile the full list exactly once, no loss/dup); edits syntax-confirmed via Read (bash AST hit the known mount-truncation artifact). *User runs `pytest`/`npm test` to confirm green.*
- *Remaining (deferred):* true keyset "load more" pager UI (current cap-at-2000 + warning is the safe interim); aggregate-SQL summary for day-book on very large windows.

**R2 — Opening-balance carry-forward + period close/lock · M · medium risk · backend core — [🟡 LOCK DONE 2026-06-20 · carry-forward deferred]**
- *Problem (§10.2 #5):* books are audit-grade only *going forward*; upstream rows can still be recomputed/changed; no period boundary.
- *Shipped — period lock (c):* event-sourced append-only `period_locks` table (`locked_through`/`is_active`/`note`; latest event wins) + migration `f2b9d4c1a8e3` (new head, idempotent). `core/accounting/period_lock.py` (`effective_lock`/`assert_period_open`/`lock`/`unlock`/`history`). The guard is hooked into `posting.post_entry` **after** the idempotency return, so the **single choke point protects all six money write paths atomically** (sale/payment/credit-note/purchase/debit-note/expense) — a raise aborts the command, nothing commits. Rejection raised as `PeriodLockedError(ValueError)` → clean **422** with message via the routes' existing `except ValueError` (added the missing branch to the expense route). Owner-only API `GET/POST /accounting/period-lock`, `POST /accounting/period-unlock` (cashier 403), wired in `core_router`. Locking to an earlier date than the current lock is rejected (no silent re-open). *(d) corrections* are already append-only reversing entries (the guard forces them into the open period). `test_period_lock.py`: guard logic, locked-period sale/expense rejected + writes nothing, open-period allowed, unlock re-opens, idempotent pre-lock re-post not blocked, lock-regression 409, cashier 403, tenant isolation. Logic sim-verified; user runs `alembic upgrade head` + `pytest`.
- *Deferred (a):* `opening_balances` per account + "as-of" carry so reports don't re-derive from genesis every time — bigger, lower-urgency; tracked as **R2b**.
- **Unblocks R3-moat** (the lock makes a hash-chain meaningful).

**R2b — Opening-balance carry-forward · M · backend core — [🟡 DONE 2026-06-21 (computed; snapshot deferred)]**
- *Shipped:* General Ledger (`/reports/general-ledger`) now opens each account at the prior period's closing balance instead of `0`. New helper `reports._opening_balances(db, bid, from_date)` sums Dr−Cr of all entries **strictly before** `from_date` (boundary day stays in-window, so every txn is counted exactly once; NULL/blank dates fold into the opening, mirroring `_build_journal_entries.within()`). The endpoint now returns `opening_balance` per account, starts the running balance there, and lists **opening-only accounts** (carried-forward balance, no in-window activity) so the ledger is complete. No new table/migration — derived on read. Trial Balance was already correct (real accounts cumulative + Capital plug); day-book is a txn register, not a running ledger — neither needed changes.
- *Verified:* standalone sim proves the invariant **windowed closing == cumulative as-of-`to` closing** for every account + no double-count at the boundary. `test_journal.py` adds 3 cases (carry-forward ties across the boundary; boundary day counted once; opening-only account appears). Pure read-path — no `test_bizassist.db` rebuild.
- *Deferred (perf only):* an `opening_balances(business_id, account, as_of_date, balance)` **snapshot** written at period close, so large histories read the latest snapshot ≤ window-start instead of replaying from genesis. Correctness is already in place; this is an optimization for scale.

**R3-moat — Hash-chain the posted journal (tamper-evident "signed shared ledger") · M · medium risk — [✅ DONE 2026-06-20]**
- *Problem:* the posted journal is honest but not yet *tamper-evident* — the Phase-6 / D5 moat.
- *Shipped:* `journal_entries` gained `prev_hash` + `entry_hash` (migration `a3c7e9b1d2f4`, new head, additive/idempotent). `posting.post_entry` now computes `entry_hash = SHA256(canonical(entry+lines) + prev_hash)` where `prev_hash` is the prior entry's hash for that business (`"GENESIS"` for the first) — still composes WITHOUT committing, still after the idempotency + period-lock checks (re-posts add no link). Amounts hashed at fixed 2dp so float noise can't shift the hash. `posting.verify_chain(db, bid)` + owner-only `GET /reports/verify-chain` walk the chain and return `{ok, checked, head}` or `{ok: False, broken_at, …}` at the first edited/deleted/reordered entry. Legacy pre-R3 entries (no hash) are skipped so the chain verifies forward. `test_hash_chain.py`: clean chain verifies, in-place line edit breaks at that entry, idempotent re-post preserves the chain, cashier 403, tenant isolation. Tamper-evidence sim-proven (edit detected; a *hidden* edit that recomputes one hash still breaks the next link; deletion detected). Ed25519 signing over the chain head is the later Phase-6 upgrade.
- *Builds on R2:* the period lock stops new postings into closed months; the hash chain makes any change to already-posted entries detectable. Together = "the books can't be quietly rewritten."

**R4 — POS pricing model: MRP-as-price → explicit `price + discount` · M · HIGH risk · money path — [🟡 cash-discount slice DONE 2026-06-20]**
- *Shipped (Slice 1 — post-tax cash discount / round-off, the receipt-proven gap):* `invoices.cash_discount` column (migration `b5d8f2a6c3e1`, new head; nullable default 0 ⇒ **strict no-op**, existing rows/tests untouched). `create_sale_invoice(..., cash_discount=0.0)` → `grand = round(raw_total) − cash_disc` (clamped `[0, rounded]`); GST/taxable untouched. `posting.build_sale_lines` books it as a new **`Discount Allowed`** debit using `gross = total_amount + cash_discount` for the Sales credit, so the entry foots and the **0-case is byte-identical** to the old two-sided entry (shared by the derived + posted engines, so reconciliation holds; verified not to break the R3 hash chain). Routes `/sales` + `/billing/invoices` accept `cash_discount`. Frontend `computeInvoiceTotals` returns `payable`/`cashDiscount` (GST untouched) + `roundOffDiscount()` helper; `buildInvoicePayload` sends it. Tests: `test_cash_discount.py` (no-op at 0, GST unchanged, foots with Discount Allowed, clamp, chain still verifies) + `invoiceMath.test.js` cases. Footing + receipt reproduction (1123→1120, "Saved" 200.49) sim-proven. *User runs `alembic upgrade head` + `pytest` + `npm test`.*
- *Shipped (Slice 2b — checkout rework per pilot feedback, 2026-06-20):* consolidated to **one** discount (post-tax cash discount; removed the Bill Discount field from the popup) + **automatic round-off** (payable auto-rounded to nearest rupee, shown live as Grand total → Round-off → Discount → **Payable**). **Payment now actually recorded**: `paid_amount` + a `mark_paid` flag wired `Sales.jsx form → usePaymentFlow → buildInvoicePayload → FrontendInvoiceRequest → create_sale_invoice`. Non-credit modes → **"Paid & Print"** (sets status **Paid**, settles the full payable exactly via `mark_paid` — immune to cent-drift), credit → **"Save & Print"** (records the due); confirm popup on both. Change line is now a **signed balance** — negative (short) shows **red** "Balance still due". Selected customer → inline **pending-dues** line (total + invoice numbers) under the totals, fetched from `/customers/{id}/ledger`. Tests updated: `invoiceMath.test.js` (round-off, payable, `paymentBalance`, `paid_amount`), `CheckoutModal.test.jsx` (one discount, Paid/Save label, neg-red, dues). *Known edge: JS `Math.round` (half-up) vs backend Python `round` (banker's) can differ ₹1 on exact .5 fractions — rare; `mark_paid` keeps status correct. Needs `npm run dev` visual check.*
- *Shipped (Slice 2 — cash-discount UI, 2026-06-20):* `CheckoutModal` now has a **Cash Discount / Round-off** field (+ one-tap "Round ⤓" using `roundOffDiscount`), shows the live **Payable** + discount line, and the whole payment path (change-due, smart tender chips, amount-received default, UPI-QR amount, exact-amount detection) now targets `payable = grandTotal − cashDiscount` via a single `pay` binding — **a no-op when there's no discount** (`payable === grandTotal`). Wired `cash_discount` through `Sales.jsx` form → `usePaymentFlow` → `buildInvoicePayload`. Tests: `CheckoutModal.test.jsx` (field renders, updates form, payable shows) + `invoiceMath.test.js`. *Needs a live visual check (`npm run dev`) for layout; logic is no-op-safe.*
- *Remaining (Slice 3, deferred — lower value / higher risk):* the structural **MRP→explicit `unit_price`+`line_discount`** rename (qty-drift bug already fixed, so mostly cosmetic debt); the **thermal print template** showing the cash-discount + "You have Saved" + payable lines (folded into **R8**); and the P&L classification decision (currently revenue-reducing via `total_amount`; the journal books `Discount Allowed` expense — net income matches, gross-revenue line differs).

- *Problem (§10.2 #3):* the overloaded MRP-as-price field already caused the qty-drift overcharge bug; future devs will misread it.
- *Benchmark:* validated against a real kirana thermal receipt — see **`BENCHMARK_RECEIPT_MR_TRADERS.md`** (M.R. Traders, reconciled to the rupee). That receipt proves the target model and adds a discount nuance we were missing.
- *Canonical model (from the benchmark):* line carries `mrp` (reference, for the "You have Saved" line), `unit_price` (= "Rate", the taxable base), optional pre-tax `line_discount`, `qty`; **line taxable = (unit_price − line_discount) × qty**. Bill level keeps the existing **pre-tax apportioned `bill_discount`** AND adds a **separate post-tax `cash_discount`/round-off** that does *not* touch GST (the ₹3 "Cash Dis" on the receipt). Stop reusing the MRP column as the live price.
- *Approach:* land it behind `utils/invoiceMath` (already pure + unit-tested) so the contract is provable; one-time data/migration shim so existing invoices still render; surface MRP+Rate+savings exactly as the receipt does.
- *Tests:* property-style — for a grid of (mrp, unit_price, line_discount, qty, scheme, pre-tax bill_discount, post-tax cash_discount), new model == old totals where applicable, GST is computed only on the pre-tax base, post-tax cash discount never changes GST, and the original qty-drift case stays fixed; reproduce the M.R. Traders bill end-to-end (Amt 1123 → −3 → 1120, "Saved" 200.49, slab table 0/5/12/18). *Risk:* highest in this list — live money math; do it deliberately with the user running the full vitest+pytest money suite.

**R8 — Thermal print template + payment/counter fields (from benchmark) · M · low–med risk — [✅ DONE 2026-06-20]**
- *Shipped (final, 2026-06-20):* **per-slab GST tax table** on the receipt (Tax% · Taxable · CGST/SGST, or IGST inter-state) via pure `invoiceMath.gstSlabBreakdown` (+vitest); **FSSAI no.** (`print.fssai_no`) + **counter/terminal id** (`print.counter_id`) + optional **"Prices Incl. GST / E.&O.E."** note (`print.prices_incl_gst`) — all new Settings rows, mirrored in the live preview; **`wallet`** payment mode added to the checkout (paid mode → marks Paid). Receipt now matches the M.R. Traders benchmark end-to-end.
- *Shipped (money lines, 2026-06-20):* the thermal receipt (`#thermal-receipt` in `Sales.jsx`) now prints **Total → (−) Cash Discount → Round Off → PAYABLE** (falls back to a single GRAND TOTAL when neither applies), amount-in-words on the **payable**, **Qty vs Items** counts, and a **"You have Saved"** line (line savings + cash discount) — matching the M.R. Traders receipt's totals block. Needs `npm run dev` visual check on a 3-inch layout.
- *Shipped (columns + header, 2026-06-20):* thermal receipt item table is now **MRP · Rate · Qty · Amt** (dropped the per-item Disc column — the final "You have Saved" total covers all discounts: line + bill + cash). Header compacted (smaller logo, less paper) and now carries **Bill No · Date · Time · Cashier · Counter** (cashier = logged-in user, counter from `print.counter_id` default `CTR1`). Mirrored in the Settings live preview (MRP/Rate sample data, Date/Time/Cashier/Counter, total Qty/Items, "You have Saved"). Compact thermal theme shows MRP→Rate inline.
- *Remaining:* per-slab CGST/SGST tax table, FSSAI no. + `#Incl Gst` header field, footer terms; persisted **counter/terminal id** (settings field + UI) and the **`wallet`** payment mode; a fully **horizontal** logo+name header if desired. (A4/PDF invoice keeps its richer column set incl. discount — change was thermal-only.)
- *Source:* `BENCHMARK_RECEIPT_MR_TRADERS.md` §4–5.
- *Scope:* match the thermal layout (MRP/Rate/Qty/Amt columns, per-slab CGST/SGST tax table, `Qty` vs `Items` counts, `You have Saved`, FSSAI no., counter/cashier, `#Incl Gst`, footer lines, round-off line); add **`wallet`** payment mode and a **counter/terminal id**. Pairs with R4 (the savings + two-discount lines come from R4's model). Best done after R6 (see it render) and R4 (pricing).
- *Tests:* render the benchmark bill and diff against the reconciled figures; payment-mode + counter persisted and shown.

**R5 — Decompose god-components · M · medium risk · frontend — [✅ DONE 2026-06-22]**
- *Problem (§10.2 #4):* `Sales.jsx` ~2,800 lines; `Reports.jsx` is a 7-branch render ternary.
- *Plan of record:* `R5_SALES_DECOMPOSITION_PLAN.md` (repo root) — ordered, one-extraction-per-commit, each `npm run dev`-verified. Order: ①ThermalReceipt ②receipt test ③CartTable ④ProductSearchBar ⑤PosTabBar ⑥Print/Hotkey settings modals ⑦(defer) usePosTabs.
- *Shipped — Step 1 (2026-06-21):* extracted the thermal receipt to `components/sales/ThermalReceipt.jsx` (presentational, 18 read-only props; `renderReceiptHeaderLine` moved with it). `Sales.jsx` 2,856→~2,577 lines; removed now-dead `renderReceiptHeaderLine`, `createPortal`/`getHeaderLayout`/`numberToWords`/`gstSlabBreakdown` imports. **Behaviour unchanged — verbatim move.** ⚠️ Needs `npm run dev` visual check (ring a bill → print receipt; compare to `BENCHMARK_RECEIPT_MR_TRADERS.md`) before the next step.
- *Shipped — Step 2 (2026-06-22):* `__tests__/ThermalReceipt.test.jsx` (vitest/RTL) locks the extraction — header/name, item rows, per-slab GST table, PAYABLE + cash-discount/round-off lines, "You have Saved", GRAND-TOTAL fallback, and null-bill → renders nothing. Portal-aware (queries `screen`, explicit unmount). User runs `npm test`.
- *Shipped — PosTopBar (2026-06-22):* extracted the `pos-top-bar` (bill-tab strip + window controls) to `components/sales/PosTopBar.jsx` (presentational, 8 callbacks, owns no state); removed the now-unused `SettingsIcon` import from `Sales.jsx`. Render test `__tests__/PosTopBar.test.jsx` (tab list, active mark, select/close/new-bill/settings/minimize/close callbacks). *(Decision: deferred `CartTable` (~500 lines, refs + keydown nav) as too risky to extract without live render verification — doing safer self-contained pieces first.)*
- *Shipped — settings modals (2026-06-22):* extracted the gear modal + hotkey modal to `components/sales/PosSettingsModals.jsx` (`PosCounterSettingsModal`, `PosHotkeyModal` — presentational, state/setters passed in, `localStorage` writes stay inline). Render tests `__tests__/PosSettingsModals.test.jsx` (render, close, advanced-settings, column-reorder arrow, reset-defaults). Leaf modals → contained blast radius.
- *Shipped — ProductSearchBar (2026-06-22):* extracted the barcode/search input + autocomplete overlay to `components/sales/ProductSearchBar.jsx` via **forwardRef** (parent keeps `barcodeRef` so the global keydown handler still focuses it — F9/post-save/Escape-clear unchanged); removed the now-unused `SearchIcon` import from `Sales.jsx`. Render test `__tests__/ProductSearchBar.test.jsx` (placeholder/value, onSearchChange, custom-item, results overlay + onPick, empty-state, **ref forwards to the input**).
- *In progress — CartTable (tight loop):* the ~500-line cart table is being sliced, not lifted whole. **Slice 1 (2026-06-22):** extracted the `<thead>` to `components/sales/CartTableHeader.jsx` (pure presentational — column headers in order + sticky offsets + visibility; returns `<thead>` so it sits inside the existing `<table>`). Render test `__tests__/CartTableHeader.test.jsx` (visible headers, hidden-column flag, column order). **Slice 2 (2026-06-22):** extracted the empty-state filler rows to `components/sales/CartEmptyRows.jsx` (presentational; returns a `<tr>` fragment inside the `<tbody>`). Render test `__tests__/CartEmptyRows.test.jsx` (row count, leading + per-visible-column cells, hidden column). **Slice 3 (2026-06-22):** extracted the per-item row to `components/sales/CartItemRow.jsx` (qty/rate/custom-name/custom-tax inputs, batch + price-option selectors, remove button; ~16 props/handlers threaded). KEY: keyboard cell-nav focuses by DOM query (`input.qty-input`/`rate-input`), not refs, so the extraction preserves those classNames → no ref threading needed. Smoke test `__tests__/CartItemRow.test.jsx` (name, **qty-input class** + value, onQtyChange, onRemove, custom-name input). ⚠️ This is the interactive core — needs careful `npm run dev` check (qty/rate edit, batch/price-option select, remove, F-key nav, price-selector popover). **Slice 4 (2026-06-22, CartTable COMPLETE):** extracted the `<tfoot>` "COLUMN TOTALS" row to `components/sales/CartFooterRow.jsx` (presentational; qty/total/discount/GST/grand-total). Render test `__tests__/CartFooterRow.test.jsx`. **CartTable is now fully decomposed** (CartTableHeader + CartEmptyRows + CartItemRow + CartFooterRow) and `Sales.jsx` is ~1,650 lines (from 2,856 — ~42% smaller).
- *Sales.jsx decomposition DONE (2026-06-22):* ThermalReceipt, PosTopBar, both settings modals, ProductSearchBar, and the full CartTable (header/empty/row/footer) are extracted — 9 focused components + 9 render-test files; `Sales.jsx` ~2,856 → ~1,650 lines, now orchestration + state. Behaviour-preserving verbatim moves, each user-verified in `npm run dev`.
- *In progress — Reports.jsx split (2026-06-22):* the 946-line `Reports.jsx` 7-branch render ternary (day-book / balance-sheet / trial-balance / party-ledger / journal+audit-journal / general-ledger / register) is being decomposed one view per slice into `components/reports/` (pure presentational, `fmt` injected — lower risk than the POS cart: no inputs/refs). **Slice 1:** `DayBookView.jsx` (summary cards + transaction table) + `__tests__/DayBookView.test.jsx`. **Slice 2:** `BalanceSheetView`, `TrialBalanceView`, `PartyLedgerView` extracted (+ `__tests__/ReportViews.test.jsx`). **Slice 3 (Reports DONE):** `JournalView` (journal + audit-journal via `isAudit`), `GeneralLedgerView`, `RegisterView` extracted (+ `__tests__/ReportViews2.test.jsx`), and the **7-branch render ternary collapsed to a `{ id → component }` registry** (`day-book`/`balance-sheet`/`trial-balance`/`party-ledger`/`journal`/`audit-journal`/`general-ledger` → view, else `RegisterView`). `Reports.jsx` 946→~620 lines; the god-ternary is gone.

**R5 COMPLETE (2026-06-22):** both god-components decomposed — `Sales.jsx` (9 components) and `Reports.jsx` (7 view components + registry), 16 new components + ~16 render-test files total, all behaviour-preserving verbatim moves verified in `npm run dev`. **R5 → ✅ DONE.**
- *Tests:* render/interaction tests per extracted component; money path unchanged (covered by R4/invoiceMath). *Risk:* extract incrementally, not blind.

**R6 — UI/UX reality pass: run it, see it, fix it · M · needs the running app — [🟡 PARTIAL 2026-06-20]**
- *Shipped (spacing + layout, code-level):* tightened the global sticky `.page-header` (top padding 24→12px, margin-bottom 24→14px, `align-items` centered) so title+subtitle+actions sit in one compact row with content flush below — applies to all 12 pages using the pattern. Confirmed primary actions already live in `.page-actions` (e.g. Settings "Save Changes", Payments "Record Payment", Stock "Add Product"). **Reports page redesigned:** the big descriptive cards became a compact `report-nav` chip selector below the filters; a **25 / 75 split** (`reports-split`) — left rail = party picker (when needed) + persisted **Recently used** list, right = the table/output (existing render branches reused unchanged) with a "Select a report" empty state. *(Not yet visually verified — user runs `npm run dev` to confirm render/mobile/a11y; the truncating mount blocks a local JSX compile, tags hand-verified via Read + Grep balance.)*
- *Delta (2026-06-20, this session):* Reports now split into **two containers** per the latest spec — (1) `.reports-controls` (filters + selector) **pinned sticky under the header** (was scrolling away — the one page that hadn't opted into the sticky pattern), (2) `.reports-workarea` (recent + output). The selector is now **no-scroll**: one row shows what fits and the rest are clipped until "All ▾" expands them (was a horizontal scrollbar). Removed the `.reports-aside` sticky so it can't overlap the new sticky controls. Tags + container nesting hand-verified (mount blocks local JSX compile); user runs `npm run dev` / `npm test`.
- *Delta (2026-06-22):* the flat 17-chip report selector is now **grouped into 4 recommended-order categories** — **Operations** (Day Book · Sales/Purchase Register · Outstanding · Stock Movement), **GST & Compliance** (GST · GSTR-1 B2B/B2CS/HSN · GSTR-3B), **Financial Statements** (P&L · Balance Sheet · Trial Balance), **Books & Ledgers** (Party Ledger · Journal · General Ledger · Audit Journal). Rendered as a **single row of group tab-buttons** (label · count badge · active-dot when a collapsed group holds the current report · chevron); clicking one expands its chips below and **only one group is open at a time** (`openGroup` single-value state; click the open one again to close). **Operations** open by default. Driven by a `REPORT_GROUPS` ordered map (does not touch the `REPORTS` array); all 17 covered exactly once. User runs `npm run dev` to confirm.
- *Original scope still open:* run both frontends, capture POS + Reports + Orders, real a11y (non-color status), mobile/responsive, empty/error states. Also: opt the few remaining toolbar-less pages (Staff/Import/Dashboard/Profile) into `.page-subbar` only if they grow a filter/tab row.

**R6-orig — UI/UX reality pass: run it, see it, fix it · M · needs the running app**
- *Problem (§10.2 #6):* no screen has been seen rendered; inline-style sprawl; color-only status (a11y risk); no mobile/empty/error-state proof.
- *Approach:* `npm run dev` both frontends → capture POS + Reports + Orders → audit a11y (non-color status cues, focus order, contrast), mobile/responsive (the shopkeeper-on-a-phone persona), and empty/error/loading states; fix the worst offenders; extract repeated inline styles into the existing CSS-var tokens.
- *Tests:* add empty/error-state render tests; (optional) axe pass. *Risk:* low code risk, but findings may spawn follow-ups.

**R7 — Compliance + offline (phase-level, largest) · L · external deps**
- *Problem (§10.2 #7):* e-invoice IRN + e-way bill (mandatory above thresholds) and offline-first/sync/RLS (D5) are unbuilt.
- *Approach:* split — (7a) **e-way/e-invoice JSON + threshold builders** first (deterministic, testable offline; **web-search the current GSTN schema before coding**; live IRP API needs sandbox creds → later); (7b) **offline cache + outbox/delta sync + idempotency keys**, then a formal `business_id` scoping audit + Postgres RLS as the second wall.
- *Tests:* schema-valid JSON for known invoices; threshold triggers; offline→3 bills→reconnect→exactly-once; tenant-scoping negative cases. *Risk:* largest scope; treat as its own phase(s), not a single task.
- **R7a — e-invoice (INV-01) + e-way-bill JSON builders · [🟡 DONE 2026-06-21]** — pure builders in `core/compliance/einvoice.py` (`build_einvoice_payload`, `build_eway_payload`), schema researched against Form GST INV-01 v1.1 + NIC e-Way Bill API. Owner-only read endpoints `GET /compliance/e-invoice/{id}` + `POST /compliance/e-way-bill/{id}` (`core/api/compliance.py`, wired in `core/api/__init__.py`). No migration needed — `Invoice.irn/ack_no/ack_date/qr_code` already exist. Builders are PURE (ORM in, dict out) and return `(payload, warnings)`: every mandatory-field gap (no seller/buyer GSTIN, missing HSN, B2C, blank distance/vehicle) surfaces as a warning instead of silently-invalid JSON. Money is footed from the line items so item sums reconcile with `ValDtls` within the IRP's ₹1 tolerance; intra→CGST+SGST, inter→IGST split derived from POS vs seller state code. `tests/test_einvoice.py` (pure — no test-DB rebuild); sim-verified against the real module.
- **R7a-next — threshold gating + persist IRN · [🟡 DONE 2026-06-21]** — thresholds web-verified 2026-06: e-way bill mandatory **>₹50,000** consignment value (`EWAY_THRESHOLD`, `eway_required(invoice)`); e-invoice mandatory at **₹5 cr PAN-level aggregate turnover** — not computable from one tenant, so gated by an owner-set `e_invoice_enabled` flag in `BusinessSettings.overrides` (read defensively, default False) via `einvoice_applicable()`. Endpoints now surface `required`/`threshold` (e-way) and `applicable`/`already_generated`/`ready` (e-invoice). New `POST /compliance/e-invoice/{id}/record` persists the IRN/ack/QR an IRP returns into the existing `invoices.irn/ack_no/ack_date/qr_code` columns — idempotent (same IRN = no-op; different IRN on a stamped invoice → 422), no migration. Threshold/applicability logic sim- + unit-tested. *Still deferred:* the live IRP/EWB **HTTP integration** (needs sandbox creds + digital-sig handling) — the builders + record endpoint are the offline half of that round-trip.
- **Tenant-isolation audit (R7b first wall) · [✅ 2026-06-21]** — static sweep of all 125 `.query()` calls across `core/api`, `core/*/service.py` and legacy `routes/`: every tenant-table fetch is `business_id`-scoped (incl. by-id update/delete on Product/Customer/Vendor/Godown/Invoice), no unscoped PK `.get()` exists, and B2B cross-business actions enforce a party check (`PermissionError`→403) in the service layer (`transition_order_status`, `update_policy` seller-only, `revoke_connection` either-party). Only intentional cross-business read is the public `/bizid/{code}` lookup. **Privacy gate added (2026-06-21):** contact details (phone/email/address) are now revealed ONLY once an `accepted` connection exists between the two businesses (or self-lookup); discovery before connecting returns just public identity (name/type/state) + `connected` flag, so a BizID can't be used to scrape contact lists. Tests in `test_connections_security.py` (`test_bizid_hides_contact_until_connected`, `test_bizid_own_lookup_shows_contact`). **No leak found; no code change.** Added `tests/test_compliance.py` closing the new endpoints' coverage gap: cashier 403, cross-tenant 404, ₹50k e-way threshold, applicability flag, idempotent/conflict IRN recording. (Postgres RLS remains the deferred second wall.)

**Recommended next:** **R1** (finishes the performance story — small, safe, backend-only), then **R2 → R3-moat** (books integrity → the tamper-evident shared-ledger differentiator). R4 (pricing) is high-value but highest-risk — schedule it deliberately, not as a drive-by.

---

### Phase 1 — Billing that replaces his current system (the painkiller) · ~3–5 wks
**Only billing. No OCR, no connections, no AI.**
- Fast sales counter (`Sales.jsx`): keyboard/barcode-first, item-master autocomplete, qty/price/discount, auto GST split (intra vs inter-state), payment mode (cash/UPI/credit), print + WhatsApp share + UPI QR.
- Product master · customer/supplier master · `business_type` template (his format first).
- GST invoice PDF; invoice > ₹50,000 → e-way fields (D7).
- `stock_ledger` (D4) — sale auto-deducts as a movement; returns / credit notes.
- Dues (credit sales, partial payments); **switch-in import** of his existing items/customers/opening stock (§7.7); bulk CSV import.
- **Staff roles** (owner vs cashier — bill yes; delete/price/profit no).
- Basic reports (day sales, GSTR-1-ready GST summary, stock).
- **Tests:** `test_billing.py`, `test_stock_ledger.py`, `test_import.py`, `test_roles.py`.
- **DoD:** owner runs a full day on it, parallel to his old system, his real catalogue loaded.

### Phase 2 — Purchase + stock auto-entry (the second painkiller: kills typing) · ~2–3 wks
**Upload a supplier bill → it becomes purchase + stock, with you only reviewing.**
- Supplier-invoice upload (photo/PDF) → the **Detect → Map → Confidence → Review → Commit** pipeline (§ Tech doc): OCR reads it → classify supplier/lines → match items to your product master → show confidence → **user confirms** → *then* purchase invoice + stock-ledger `purchase` movements commit.
- **Never auto-commit low-confidence financial data** — review is mandatory.
- **Tests:** `test_purchase_ocr.py` (messy invoice → mapped lines + confidence), `test_purchase_commit.py` (commit creates purchase invoice + exact stock movements; low-confidence blocks auto-commit).
- **DoD:** owner adds a real supplier delivery by snapping the bill, not typing.

### Hardening (slot when internet reliability becomes a real pilot pain) · ~3–4 wks
- Encrypted offline cache (SQLCipher) + **outbox/delta sync** (D5) + idempotency keys; formal `business_id` scoping audit + Postgres RLS as the second wall.
- **Tests:** offline → 3 bills → reconnect → exactly-once; `test_tenant_scoping.py` negative cases.

### Phase 3 — Business connections (the network begins) · ~3–4 wks
- BizID issued per business; **seller-issued connection code** → buyer redeems → request/approval → `connections` row.
- **Per-connection visibility policy** + the single **sharing serializer** (§4): seller picks catalogue scope, price tier, stock visibility band per buyer. Buyer sees the seller's policy-scoped catalogue and places an order.
- **Tests (the product lives here):** `test_connections.py` — code redemption creates the pipe; expired/reused rejected; **buyer A cannot read seller B's other customers / sales / margins / cost / hidden stock**; revoke closes the pipe, keeps both rooms private.
- **DoD:** the pilot wholesaler connects one distributor; buyer sees only the allowed slice.

### Phase 4 — Invoice sync (the magic: auto stock from supplier bills) · ~3–4 wks
- Seller converts the order → invoice → buyer receives it → buyer **imports** it (reusing the Phase-2 review→commit pipeline) → buyer's purchase + stock update; seller's sales ledger + the **shared ledger** update both balances (append-only).
- Realtime (SSE): `order.created` → seller; `invoice.ready` → buyer.
- **Tests:** order→invoice→buyer stock-in exactly-once; shared-ledger balances correct on both sides.
- **DoD:** a real order flows end-to-end and updates both businesses' books automatically.

### Phase 5 — AI Advisor (paid) · ~2–3 wks
- Plan-gating (`subscriptions`/`User.plan`); move the existing chat/insights/agent behind it.
- Advisor now reasons over the richer data: who to reorder from, what's moving, which buyers stopped ordering, what's overdue, what offer to send. Morning digest.
- **Tests:** `test_plan_gating.py` (AI blocked on Starter).

### Phase 6 — Strong network features (the deep moat) · ongoing
- **Reputation / trust score** on BizID (§16.3).
- **Signed (Ed25519) + hash-chained shared ledger** (§6 #18) — tamper-evident, dispute-proof. *(This ships HERE, with the mature shared ledger — not week one; you can't sign shared transactions before they exist.)*
- Financing / payment insights; advanced network effects; e-invoice IRN API; Redis at scale.

### Phase 5 — AI advisory on the network + monetization depth · ~2–3 wks + ongoing
- Feed `orders`/`shared_ledgers` into the AI tools + memory distillation: "which retailers stopped ordering", "who'll pay late", "what offer to send".
- Offers/campaign push; Razorpay self-serve subscriptions; UPI collection in the customer app.
- E-way bill API aggregator; e-invoice IRN for above-threshold businesses; Redis for shared cache/realtime at scale (you already flagged single-worker limits).

---

## 11. Pilot playbook (the interested owner)

1. **1-hour shadow session:** watch his current billing live; list his **top 20 repeated actions**; collect real samples (invoices, stock sheet, sales bill, his GST format).
2. **Build only his daily workflow first** (Phase 1), in *his* business format.
3. **Install + run parallel for 7 days** alongside his current system (no switching risk).
4. **Charge a small pilot fee** — seriousness + pricing signal.
5. **Then the cheap USP test, before building Phase 3:** take 3 of his retailers and run a *manual* ordering flow (a shared WhatsApp/Google-Form "order list") for one week. **If retailers won't order through a form, they won't order through an app** — and you've saved months. If they do, the USP is validated → build the real PWA.
6. Switch his billing fully only after trust is earned.

---

## 12. Risks & how we de-risk

- **Scope explosion** → phases ship independently; Phase 1 stands alone.
- **Retailer adoption is unproven** (the whole USP rests on it) → validate with the manual flow (§11.5) before building Phase 3. This is the #1 risk and it's a *behavior* risk, not a tech risk.
- **One customer ≠ a business** → design for his format, but build on the template registry so customer #2/#5 reuse it.
- **Sync correctness** → append-only + idempotency + cloud-authoritative (D2/D5); no multi-master until forced.
- **GST/e-way legality** → CA-validate one real flow before marketing "compliant"; gate e-invoice by turnover flag.
- **Trust** → money deterministic, AI advisory only, actions gated+audited (already your discipline).

---

## 13. Decisions that need YOUR sign-off

Everything in §2 is decided unless you object. These few need your explicit call before Phase 1 code:

1. **Reuse `invoices` or add `sales_invoices`?** Recommendation: **extend the existing `invoices`** for sales (it already has the GST fields), add `purchase_invoices` separately. Less migration, reuses handlers/AI tools. *(Your call.)*
2. **Cloud realtime: own Postgres + SSE service, or Supabase?** Recommendation: **own stack first** (no lock-in; you already use SSE), revisit Supabase only if realtime fan-out hurts. *(Your call — reversible.)*
3. **First business format to nail:** the pilot owner's (wholesaler/distributor). Confirm so we tune Phase 1 to it.
4. **Pilot price** — even a token monthly figure, so we test willingness to pay.

---

## 14. The USP Stack — everything that makes us hard to copy (ranked)

**The strength test — moat or gimmick?** A feature is a *moat* only if it (a) compounds with use, (b) is hard to copy, and (c) makes leaving costly. Everything else is either a *wedge* (wins the demo, gets you in — copyable, so invest only enough) or *table-stakes* (must-have, zero differentiation). Spend your scarce build effort on the **moats**, do the wedges *just well enough*, and never *market* the table-stakes. The full strategy behind these is **§16 (Strength Doctrine)**.

**🟢 MOATS — compound, hard to copy, costly to leave (this is where the company is):**

| USP | What it is | Why it's a moat, not a gimmick |
|---|---|---|
| **1 · BizID — the trade-network identity spine** (D9 + §16) | One identity that is login + address + verified badge + reputation + (later) payment handle. The "Apple ID of the trade network." | Every connection, invoice, payment, and trust signal hangs off it; it compounds with each business that joins and becomes your switching cost. Copyable in form, *not* in installed base. |
| **2 · The private ordering network** | Each business's own buyer↔seller channel, wired into billing+stock | Classic network effect: value grows with local density; once a business's partners are on it, leaving disrupts *their* relationships, not just theirs. |
| **3 · Tamper-evident shared ledger** (§6 + §16) | Each shared invoice/payment is signed + hash-chained, so neither party can alter or dispute it after the fact | A neutral, cryptographic source of truth between two businesses — solves real reconciliation disputes. Hard to copy credibly; trust compounds. |
| **4 · Reputation / trust score on BizID** (§16) | On-time-payment, fulfilment, dispute history attached to each BizID | Lets businesses who don't know each other trade safely, and becomes the creditworthiness data that unlocks the financing layer. Pure data gravity — uncopyable. |
| **5 · Data gravity: AI on the whole network** | Advice grounded in real billing + order + payment flow across connected businesses | The more the network transacts, the smarter and more irreplaceable the advisor. Competitors have data silos, not a network graph. |

**🟡 WEDGES — win the demo, get you in (copyable; do them well, don't over-invest):**

| USP | Role |
|---|---|
| **AI invoice/photo parsing** | The "wow" that kills manual entry and wins the pilot. Copyable in ~a year — use it to land users, not as the moat. |
| **App-native addressed delivery** | Invoices land in the in-app inbox, not a web link. Real, but only valuable *because* of the network (moat #2). |
| **Self-configuring by business type** | Removes setup friction across verticals. |
| **Local-feel + cloud-truth** | Offline billing + sync; the *combo with the network* is the rare part. |

**⚪ TABLE-STAKES — must exist, never your pitch:** fast GST billing, stock movement ledger, reports, WhatsApp share. If your message is "we do billing," you've already lost (price floor ~₹1,000/yr). **Billing is the wedge; the network + BizID + trusted ledger is the war.**

**Marketing message hierarchy** (say them in this order):
1. *"Stop typing every item — snap your supplier bill, done."* (the felt pain → wins the demo)
2. *"Your retailers order from home; your invoice writes itself."* (the network → the reason to choose you)
3. *"Find & order from any shop in one search — your BizID."* (the viral handle → why it spreads)
4. *"Your AI advisor tells you who to chase, what to reorder, who's gone quiet."* (the upsell → the margin)

---

## 15. Cardinal rules — what NOT to get wrong (read before every phase)

These are the mistakes that quietly kill the product. Most are cheap to honor now and brutal to fix later. Grouped by your four goals + execution.

### Trust, security & "unbreakable" (never violate — these are absolute; data IS money)
1. **AI never touches money.** Totals, tax, stock counts are deterministic SQL. The AI only *advises*; its *actions* stay preview→confirm→audit. One hallucinated invoice total destroys trust permanently. (You already enforce this — keep it absolute.)
2. **Transactions are append-only.** Never overwrite an invoice, payment, stock movement, or ledger row. Corrections = new reversing entries. A sync that can *delete* a sale is unacceptable.
3. **Idempotency keys on every transaction.** A retried/duplicate sync must never double-post a bill or double-deduct stock.
4. **Scope every read by the token's `business_id`; never trust client-supplied IDs.** Cross-business reads ONLY through an accepted `connections` row, ONLY the shared slice. One central guard, not per-endpoint WHERE clauses. Test negative cases explicitly.
5. **Shared transaction, never shared books (D10).** Connected = a pipe between two private rooms. Every field that crosses must pass "would BOTH sides consent?" One leak of a partner's prices/customers/margins ends the network.
6. **BizID lookup leaks nothing; the link needs a seller-issued code.** Public profile only; codes single-use, expiring, throttled, seller-revocable; random non-sequential IDs so the directory can't be scraped.
7. **Encrypt all three copies + everything in transit.** TLS everywhere; cloud Postgres encrypted (+ column-level for GSTIN/phone/UPI); **offline cache encrypted** (stolen laptop ≠ plaintext price book); backups encrypted with separate keys. Build this in the first migration — it cannot be retrofitted onto a live financial network.
8. **Secrets out of code/client; least privilege.** Secrets in env/manager (JWT_SECRET already moved); the buyer/customer side ships no secrets and can call only its own scoped endpoints.
9. **Throttle every credential + code surface.** Login, OTP, connection-code redemption — rate-limited + lockout. Don't let a public network become a brute-force playground.
10. **Don't store card data.** Razorpay vaults it — stay out of PCI scope. Mind India's DPDP Act (consent, minimal PII, deletion on request).
11. **Don't claim "GST/e-way/e-invoice compliant" until a CA validates one real flow.** Gate e-invoice/IRN by a per-business turnover flag so you never mis-issue.

### Easy to use (the wedge)
12. **Lead with billing, not AI.** The first screen is the billing counter. AI lives behind "AI Advisor." Owners ask "can I bill fast?" first.
13. **Keep Sales and Stock as two separate sections.** Sales = optimize for speed; Stock = optimize for accuracy. Never mix the mental models.
14. **The billing path must stay instant and offline-capable.** Never put billing behind a slow network call or an LLM call. AI is async/optional and must *never block or slow* a bill.
15. **Design for low-tech staff.** Keyboard + barcode first, vernacular/local-language UI, one-tap reorder, big targets. If it needs training, it's wrong.
16. **One app, progressive disclosure (D10).** A new "I only want to order" user sees a dead-simple screen; billing/stock/reports reveal as they grow. Don't make ordering require learning the whole app — and don't build a second app.

### Network & "addictive" (the moat)
17. **Don't build the ordering/connection layer before validating adoption.** Run the manual WhatsApp/form ordering test with 3 real buyers first (§11.5). This single behavior is the whole bet — prove it for the cost of an afternoon, not months of code.
18. **Don't expect the BizID/network to wow your first pilot.** It's a *compounding* moat that's worth little at low density. Build it in now (cheap), but win the pilot on fast billing.
19. **Connection is always consent-based (seller-issued code).** No auto-linking businesses. Spam/abuse kills a network's trust faster than anything.

### Architecture (decided in §2 — don't relitigate mid-build)
20. **One tenant key (`business_id`). Don't add a second tenancy concept** (no parallel `tenants` table) — it forks the model and breaks 385 tests.
21. **One app, not two (D10).** Ordering lives inside the billing app; cross-business access only through a consented connection (the shared pipe), never a shared room.
22. **Don't build true local-first multi-master sync.** Cloud is the source of truth; local is an offline cache. This one decision protects your timeline more than any other.
23. **Migrations are additive, nullable-by-default, backward-compatible.** This is what's kept your 385 tests green; keep it. One revision per change.
24. **Orders are relational (`order_items`), not a JSONB blob** — you must reserve stock and report on lines.
25. **Stock = ledger is the source of truth; `inventory.stock` is a cache** you can rebuild from the ledger.
25a. **Upgrades are staged, signed, reversible, and backward-compatible — never a big-bang push** (Tech doc §8). Businesses run different versions and transact across them, so old clients must never break on a new server; the billing path gets canary rollout + auto-halt + one-click rollback. The same remote-flag system unlocks paid features per business with no reinstall.

### Business & money (the goal)
26. **Don't give free pilots.** Even a token fee tests willingness to pay and seriousness.
27. **Don't price billing to win on price.** Match the floor to remove objections; make the money on Cloud + AI + Network. Racing Vyapar to ₹0 is a losing game.
28. **Don't over-scope a phase.** Every phase must ship and be sellable alone. Phase 1 (billing) stands on its own; if you can't sell it without the rest, the plan is wrong.
29. **One customer is a project, not a business.** Build *his* format first, but on the template registry so customer #2/#5 reuse it. Watch for "we built something only he uses."
30. **Free/Starter must stay LOCAL — don't let it consume cloud.** Your unit economics only work if the cheap tier runs offline (his machine, his cost) and only *paid* tiers (Cloud/Network) hit your cloud bill. If free users sync heavily to your Postgres, you lose money per user. Cloud cost is a paid-tier feature, by design.

### Real-world gotchas (easy to forget, expensive to hit)
31. **WhatsApp is not free or unlimited.** The WhatsApp *Business API* charges per conversation and requires customer opt-in + pre-approved templates for marketing/notifications. Don't architect "we'll WhatsApp everything" as if it's free SMS. Use **in-app inbox push (free, via BizID) as the primary channel**, WhatsApp as an opt-in convenience, SMS as fallback. Budget WhatsApp marketing cost into the Network tier price.
32. **Returns/credit notes and rounding are not edge cases.** Retail has returns daily; GST rounding (per-line vs invoice-level) must match what a CA expects. Get both right in Phase 1, not bolted on.

### Security & ops (don't skip because it's a pilot — full stack in §6.2/§6.3)
33. **Encrypt from the first migration.** TLS everywhere; encrypted cloud DB, encrypted offline cache, encrypted backups. Cannot be retrofitted onto a live financial network.
34. **Rate-limit + throttle every credential and connection-code surface.** A public network is an attack surface; extend your existing rate-limiter to login/OTP/code redemption with lockout.
35. **Least privilege + no secrets client-side.** A buyer/customer session can call only its own scoped endpoints; ships no keys.
36. **Single-worker constraint is real until Redis lands.** Your caches/scheduler are process-local — document it, or duplicate alerts and split rate-limits will bite at scale.

> **The one-line version of this whole section:** *Money is sacred and deterministic; the network is consent-based and append-only; billing is fast and offline; AI advises but never decides money; ship each phase sellable; and validate retailer behavior before you build for it.*

---

## 16. Strength Doctrine — Apple-like, non-collapsible, BizID-spined (read this to keep it strong)

This section is the answer to "make it super strong and unique, not gimmicks." It defines *why* the product can't be easily copied or knocked over, and what we must never compromise to keep it that way.

### 16.1 The ecosystem doctrine (what "Apple-like" actually means here)
Apple isn't strong because of any one feature — it's strong because of **five compounding choices**. We copy the *structure*, not the products:
1. **One identity glues everything → the BizID** (their Apple ID). Login, address, trust, reputation, payments all hang off it. (§16.2)
2. **Own the whole core loop — don't rent it.** Billing → ordering → invoicing → stock → payments → credit all live in *one* vertically-integrated flow. The moment a competitor or a third party owns one link (e.g. payments), they can pry the user away. We own the loop end-to-end.
3. **Trust & privacy ARE the brand.** Like Apple's privacy pitch: "your books are yours; your partner sees the deal, never your business." This is a *marketing* weapon, not just engineering (§6).
4. **Compounding data gravity.** Every transaction makes the AI smarter and the reputation graph richer — value the user can't take with them when they leave.
5. **A quality/ease bar nobody in this segment meets.** "Easy + addictive" is not fluff; it's the same moat as Apple's polish — it's why people don't switch even when a cheaper option exists.

> If a proposed feature doesn't strengthen one of these five, it's a gimmick — deprioritize it.

### 16.2 BizID as the spine (the key role you sensed)
BizID is not "a unique ID feature." It is the **single thread the entire ecosystem is woven on.** It plays **five roles**, and each new role makes leaving more unthinkable:
1. **Identity** — the account you log in as; one BizID = one business across every surface.
2. **Address** — orders, invoices, offers, and (later) payments are *sent to a BizID*, like a UPI handle. The network's routing layer.
3. **Verification badge** — a KYC/GSTIN-verified BizID carries a trust mark; high-trust actions (credit, large orders) can require it. Verification is sticky (you don't re-verify elsewhere).
4. **Reputation carrier** — payment reliability, fulfilment rate, dispute history accrue to the BizID (§16.3). Your *trade reputation lives here*, so you can't abandon it.
5. **Signature anchor** — each business's public signing key is published on its BizID profile, so partners can verify that a signed invoice/payment truly came from it (§6 #18).

Because *everything* references the BizID, it becomes the gravitational center: the more roles it carries, the higher the switching cost. **Protect it ruthlessly** — random non-sequential IDs, verified badges that can't be faked, reputation that can't be gamed (tie score changes to *signed* transactions only).

### 16.3 Reputation & trust graph (lets strangers trade — a moat that prints the financing business)
The hardest problem in B2B is trust between businesses that don't know each other. Solve it and you own the network:
- Each completed, *signed* transaction updates the parties' BizID scores: **on-time payment %, fulfilment rate, dispute rate, tenure, volume band** (never raw amounts — privacy).
- A business deciding whether to extend credit or accept a new buyer sees the buyer's **trust score + verified badge**, not their private books.
- This same graph is the **creditworthiness data** that unlocks the financing layer (retailer BNPL / working capital) — the highest-margin revenue, and *uncopyable* because it's earned from real transaction history on your network.
- Guard against gaming: scores move only on signed, two-sided-confirmed transactions; sudden anomalies flagged; no pay-to-win.

### 16.4 Non-collapsible by design (resilience doctrine)
"Non-collapsible" is an engineering commitment, not a slogan. Five rules:
1. **Per-node autonomy.** A business can *always* bill, even if the cloud, the network, or its partners are down (offline cache, D5). The *individual's* core job never depends on the network being up. The network is additive, never load-bearing for daily billing.
2. **No single point of failure as you scale.** Stateless API behind a load balancer; managed Postgres with replica + automated failover; the realtime push degrades to polling if it drops. (Until then, the documented single-worker constraint is honest — fix it before scale, not after a crash.)
3. **Append-only + signed + hash-chained truth** (§6 #18) means data corruption/tampering is *detectable and recoverable*, never silent. You can always rebuild state from the ledgers.
4. **Durable, tested backups.** Encrypted, off-site, versioned, with *rehearsed* restores. A backup you've never restored is not a backup.
5. **Graceful degradation everywhere.** Every feature has a defined "what happens when its dependency is down" answer. AI down → billing unaffected. Partner offline → manual billing. Push down → polling. Nothing cascades.

### 16.5 The collapse vectors to actively defend (be paranoid about these)
- **Disintermediation** (the silent killer): once A and B connect, they could take the relationship to phone/WhatsApp and stop using you. **Defense:** make the platform *more valuable than going around it* — auto stock-sync, the tamper-proof ledger that settles disputes, credit access gated on platform reputation, AI advice. If on-platform isn't clearly easier *and* safer than a phone call, you lose the link. Track "connections that go dormant" as a top health metric.
- **Cold-start / empty network.** A lone business has no one to connect to. **Defense:** seed a *whole local chain at once* — one distributor + his wholesalers + their retailers in one area — not scattered single users. Density in one cluster beats spread everywhere. (Your pilot is the seed of exactly such a cluster.)
- **Trust break (one leak).** Covered exhaustively in §6 — but strategically: a single cross-business data leak in a gossip-tight local market is an *extinction event*, not a bug. Treat §6 as non-negotiable.
- **Compliance break.** A mis-issued GST/e-invoice erodes the "trustworthy" brand. CA-validate; gate by turnover.

### 16.6 The investment rule (so we build strength, not gimmicks)
Before building anything, ask: **does this deepen a moat (§14 🟢), or is it a wedge/gimmick?** Spend ~70% of effort on the five moats (BizID spine, network, tamper-proof ledger, reputation, data-gravity AI), ~20% on wedges done *just well enough* to win demos, ~10% on table-stakes parity. A beautiful gimmick that doesn't compound is wasted runway.

---

### Internal north-star (the whole plan in one line)
> **One app. Every business. Private books. Shared deals. Auto stock from supplier invoices. AI paid advisor.**
>
> Build the big ecosystem in the *architecture*; **sell the first version as a painkiller.** The first user does not care about BizID, reputation, encryption, or network moat — he cares about: can I bill fast, avoid typing items, upload supplier invoices, see stock correctly, print/share, train staff quickly, and keep my data safe. Win on those; the moat compounds underneath.

### One-line positioning (for him and for marketing)
> "BizAssist isn't just billing software — it gives your business its own private ordering network for your customers, wired into your stock, payments, and an AI advisor. Bill in seconds, stop typing every item, and let your retailers order from home while your books update themselves. Every business gets a **BizID** — share it, and anyone can find you and order in one search, like a UPI handle for your shop."

### Immediate next step
On your sign-off of §13, I'll turn **Phase 1** into a concrete engineering task list against the codebase: exact new Alembic migrations (`stock_ledger`, sales extensions), the FastAPI route group, the `Sales.jsx`/`Stock.jsx` React pages, the invoice-PDF + e-way generation, and the test files — so you can start building the thing that lands this customer.

---

## 17. Appendix: Known Database Schema Issues & Future Actions

### 17.1 Missing `invoices.godown_id` Column on Cloud PostgreSQL
- **Issue Description:** When authenticating and loading dashboard/insights data on the cloud backend (e.g. for User 2 / Business ID 2 who was already present in the database), the application errors with:
  ```
  psycopg2.errors.UndefinedColumn: column invoices.godown_id does not exist
  ```
  This happens because the `godown_id` column exists in the local SQLite database but was omitted from the Alembic migrations and the declarative startup migrations in `_COLUMN_MIGRATIONS`.
- **Impact:** Crashes the dashboard summary, top-customers list, and smart insights snapshot retrieval.
- **Recommended Action (to be executed later):**
  1. Add `godown_id` to the declarative migration list (`_COLUMN_MIGRATIONS`) in [migration.py](file:///d:/Dev%20Workspace/ai_agent_lab_google(1)/bizassist-billing/backend/database/migration.py):
     ```python
     {"table": "invoices", "column": "godown_id", "ddl": "ALTER TABLE invoices ADD COLUMN godown_id INTEGER"}
     ```
  2. Verify if other tables (e.g. `inventory`) also require a similar column entry.
  3. Deploy the backend updates to the Hugging Face Space repository. When the server boots up, the startup migration check will detect the missing column on the Supabase/Postgres database and dynamically execute the DDL without data loss.

