# BizAssist → Billing & Ordering Ecosystem — Detailed Product Plan

> ⚠️ **SUPERSEDED — kept for history only.** This was the *first* ecosystem draft and still uses the old **"merchant app + customer app"** two-app language. The final direction is **ONE app for the whole B2B chain** (every business buys above + sells below; connections share the deal, not the books). **Use `BIZASSIST_ECOSYSTEM_MASTER_PLAN.md` as the source of truth**, and `BIZASSIST_TECH_ARCHITECTURE.md` for the stack. Don't build from this file.

*June 2026 · From "AI business assistant" to "the operating system for a local distribution business + its customers"*

---

## 0. The single most important realization

You did not build a BI dashboard that needs a billing system bolted on. **You already built a GST billing data model and mislabeled it as analytics.** Proof, from `database/models.py`:

- `Invoice` carries `GSTFieldsMixin`: `gstin_buyer`, `place_of_supply`, `invoice_type` (B2B/B2C/Export/SEZ), `subtotal`, `cgst_total`, `sgst_total`, `igst_total`, `cess_total`, `total_amount`, **`irn`, `ack_no`, `ack_date`, `qr_code`** (e-invoice fields).
- `InvoiceLineItem`: per-line `hsn_sac`, `quantity`, `unit_price`, `discount`, four tax rates + four tax amounts, `taxable_value`, `line_total`.
- `Customer` (credit_limit, credit_days, GSTIN), `Vendor`, `Product` (HSN, MRP, cost/selling price, tax rates), `PurchaseOrder` + line items.
- Multi-tenant: every table is scoped by `business_id`. `User` already has `gstin`, `state_code`, `pan`.

**So the billing system isn't a new build — it's surfacing and completing a schema that's already there.** The work is UI, invoice generation/PDF, e-way bill, the customer app, and sync — not re-architecting data. This is your unfair head start, and it's why you can credibly say yes to this business owner.

---

## 1. What the business owner actually asked for (decoded)

He gave you, in plain words, a three-sided product. Let me separate the threads so nothing is lost:

**A. A real billing system (his core pain), that:**
1. Kills **manual item entry** — the #1 complaint. Bulk upload + AI invoice/photo parsing + barcode + reusable item master.
2. **Easy invoice generation**, including the legal requirement that a sale > ₹50,000 needs an **e-way bill** (this is the real rule behind "more than 50k" — e-way bill is mandatory above ₹50,000 per invoice).
3. **Everything in one app** — no jumping between tools.
4. **Separate, clean sections**: stock/inventory entry vs sale/billing entry. Don't mix the two mental models.
5. **Easy to learn and use** — staff with no training should bill in under a minute.
6. **Installable locally** (his shop PC) — works without internet, syncs when online.

**B. Multi-business templating:**
- On registration, the business picks a **type/format** (wholesaler, retailer/kirana, pharmacy, restaurant, hardware, garments…) and the billing app **configures itself** to that format (fields, tax defaults, units, invoice layout, workflows).

**C. The customer app (his actual growth idea, and your USP):**
- His **wholesale customers (retailers)** get a **separate, branded app** that shows *only his* catalogue + prices, with **real-time sync**.
- Retailers **order from home** → invoice auto-generates → syncs back into the wholesaler's BizAssist automatically. No phone calls.
- Push **offers / marketing** to those customers in real time.
- The customer app is **scoped to one business** — it does not reveal other shops.

The ecosystem: **wholesaler runs BizAssist; each of his retailers runs his branded ordering app; orders and invoices flow between them automatically.** Multiply that by every wholesaler in your town and you have a network.

---

## 2. Market reality & where the gap is (so we don't build a me-too)

I checked the field. Two separate markets exist, and **almost nobody fuses them for the small local distributor.**

**Billing software (crowded, cheap, commoditized):**
- **Vyapar** — best mobile experience, strong offline, ~₹1,099/yr, 1cr+ users. The benchmark for "simple + offline."
- **myBillBook** — phone-first, WhatsApp invoices, ~₹2,599/yr.
- **Marg ERP** — deep pharma/distribution features, heavier, pricier.
- **Zoho Invoice / Sleek Bill** — free tiers, cloud, more "accountant" flavored.

Takeaway: **you will not win on "another billing app."** Billing is table stakes and the price floor is ~₹1,000/yr. It must be *as easy as Vyapar* just to enter — that's the bar, not the differentiator.

**B2B ordering apps (exists, but enterprise-priced & FMCG-brand-oriented):**
- **BeatRoute, Onsight, B2Sell, OrderEase, Way2Order, RetailCore** — distributor/retailer ordering with catalogues and ERP sync.
- **Retailio** — huge, but pharma-only.

Takeaway: these target **brands and large distributors** with field-sales fleets and ERP integration projects. They are **not** the plug-and-play, self-installing, "my retailer downloads my app and orders" product for a **single local wholesaler**. That segment is underserved.

**The gap (your USP lives here):**
> Billing apps don't give a small wholesaler a **branded customer-ordering app** out of the box. B2B-ordering vendors don't give a small wholesaler a **dead-simple local billing system + AI advisor** out of the box. **Nobody hands a ₹2-crore local distributor: easy billing + his own retailer app + AI business brain, as one self-installing package.** That fusion is the product.

---

## 3. The USP, stated sharply

**"BizAssist gives every local wholesaler their own branded ordering app for their retailers — plus the billing and the AI business brain behind it — installable in a day, no IT team."**

Three reinforcing moats, in priority order:

1. **The branded customer app is the wedge and the lock-in.** Once a wholesaler's 40 retailers are ordering through *his* app, he cannot leave without disrupting his customers. Billing apps have ~0 switching cost; an active customer network has enormous switching cost. **This is the defensible asset.**
2. **AI advisor as a paid upgrade** — grounded in the billing data that's now flowing through the system (you already built this: the 4-tier router, smart insights, agent loop, gated actions). Competitors bolt on dumb "reports"; you have a real advisor.
3. **Self-installing, offline-first, multi-format** — Vyapar-level ease for a multi-sided system, which the enterprise B2B vendors can't match on simplicity or price.

---

## 4. The product, as three surfaces on one platform

Think of it as **one backend (the platform) serving three front-ends**, all keyed by `business_id` (already true today).

```
                         ┌────────────────────────────────────────┐
                         │   BizAssist Platform (FastAPI + PG)     │
                         │   multi-tenant, business_id-scoped       │
                         │   + AI engine (4-tier, your existing)    │
                         └───────────────┬────────────────────────┘
            ┌────────────────────────────┼────────────────────────────┐
            ▼                            ▼                            ▼
  ┌───────────────────┐      ┌────────────────────┐      ┌──────────────────────┐
  │ 1. MERCHANT app    │      │ 2. CUSTOMER app     │      │ 3. AI add-on (a plan)│
  │ (wholesaler/shop)  │      │ (his retailers)     │      │  unlocks chat,       │
  │ • Billing (sale)   │◄────►│ • Browse HIS catalog │      │  insights, agent,    │
  │ • Inventory (stock)│ sync │ • Order from home   │      │  actions             │
  │ • Invoices+e-way   │      │ • Get his offers    │      │  (your current app)  │
  │ • Customers/credit │      │ • See own invoices  │      │                      │
  │ • Dashboard        │      │ • Real-time stock   │      │                      │
  │ • AI (if subscribed)│     └────────────────────┘      └──────────────────────┘
  └───────────────────┘
```

The current dashboard/chat you have **moves into surface #3** (a Profile → "AI Assistant" section that's gated by subscription), exactly as he suggested. Billing becomes the default home.

---

## 5. The Billing module — concrete feature spec (his core ask)

This is the part that must feel like Vyapar on day one. Two clearly separated sections, because he asked for it and because it matches how shop staff think.

### 5.1 SALE section (fast billing — optimize for speed)
- **One-screen billing**: search item → qty → auto-price → auto-tax → total. Keyboard + barcode scanner first; mouse optional. Target: **a 5-line bill in under 45 seconds.**
- **Item master autocomplete** (uses your `Product` table): type 3 letters, pick, done. No re-entering HSN/tax — it's on the product.
- **Auto GST split** (CGST/SGST intra-state vs IGST inter-state, decided by `place_of_supply` vs business `state_code` — fields already exist).
- **Invoice generation → PDF** with the business's letterhead, GSTIN, signature, UPI QR for payment.
- **E-way bill trigger**: when `total_amount > ₹50,000`, the bill flow prompts/auto-prepares the e-way bill payload (Part-A). Phase 2: direct push to the NIC e-way bill API. *This directly answers his "sale more than 50k" requirement.*
- **E-invoice (IRN/QR)**: schema is ready (`irn`, `ack_no`, `qr_code`). Turn on for businesses above the e-invoice turnover threshold (₹5 cr now, trending down to ₹2 cr — so build it, gate it by a per-business flag).
- **Payment modes + partial payments** (you have `paid_amount`, `payment_mode`, `payment_date`).
- **Share invoice on WhatsApp** in one tap (table-stakes — Vyapar/myBillBook both do it; we must too).
- **Hold/resume bills, returns/credit notes, quick discounts.**

### 5.2 STOCK section (inventory — optimize for accuracy)
- **Kill manual entry — four faster paths:**
  1. **Bulk CSV/Excel import** (you already have `column_mapper` + `parser` that normalize messy columns — reuse directly).
  2. **AI invoice/photo parsing**: snap a supplier invoice → your `pdf_parser` + OCR extracts items → review → import. (You already parse PDFs; extend to phone-camera capture.) **This is a wow feature and a real differentiator vs Vyapar.**
  3. **Barcode scan-to-add.**
  4. **Purchase Order → Goods Receipt** auto-increments stock (`PurchaseOrder` + line items already modeled).
- **Stock ledger**: opening, in (purchases/GRN), out (sales), adjustments, closing — auto-maintained as bills are cut.
- **Reorder + expiry alerts** (you already compute low-stock and expiring-soon; surface them here, and they feed the AI advisor and the morning digest you just built).
- **Batch/expiry tracking** (you have `batch_no`, `expiry_date`) — important for pharma/FMCG formats.

### 5.3 Why this is winnable fast
Most of 5.1/5.2's *data layer* exists. The build is **UI + PDF/e-way bill generation + camera capture**, not schema. That's weeks, not quarters.

---

## 6. The Customer App — your USP, specified

This is the part competitors don't hand to a small wholesaler. Build it deliberately.

### 6.1 What the retailer (customer) gets
- **A branded app/PWA** showing **only this wholesaler's** catalogue, *their* negotiated prices, and live stock. (Scoped strictly by `business_id` + a `customer_id` link — your `Customer` table already exists; add an auth identity for the customer.)
- **Order from home/shop**: cart → place order → it lands in the wholesaler's BizAssist as a **pending sale order** in real time.
- **Auto-invoice**: wholesaler confirms (or auto-confirm rule) → invoice generated → **synced back to the retailer's app** and WhatsApp.
- **Their own ledger**: what they've ordered, outstanding dues, payment via UPI.
- **Receive offers/marketing** push notifications (festival schemes, "Basmati Rice 25kg — 5% off this week").
- **Reorder in one tap** from past orders (huge for repeat FMCG buying).

### 6.2 Why it's a USP and a moat
- **Acquisition flywheel**: every wholesaler onboards their *own* retailers for you. You sell to 1 wholesaler, ~40 retailers start using a BizAssist-powered app for free. Some of those retailers are *also* shops who then want BizAssist billing themselves → **bottom-up viral spread through the local trade network.**
- **Lock-in**: the wholesaler's customers now live in his app. Switching billing software = disrupting his customers. No billing competitor creates this.
- **Data**: real demand signals (what retailers browse, abandon, reorder) → fuels the AI advisor's recommendations, which you can sell.

### 6.3 Privacy boundary (he explicitly wants this)
Customer app must **never** show other businesses' data. Enforce at the API: a customer token resolves to `(business_id, customer_id)` and **every** query is filtered by both. This is the same tenant-isolation discipline you already apply with `business_id`; you're adding a second scoping key.

---

## 7. Multi-business-type templating (registration → configured app)

On signup, the business chooses a **format**, and a **template config** drives the whole experience. Implement as a registry (the same pattern you used for intents/actions — config over code).

```jsonc
// business_templates/wholesaler.json (illustrative)
{
  "type": "wholesaler",
  "billing": { "default_invoice_type": "B2B", "show_eway_bill": true,
               "price_lists": true, "credit_terms": true },
  "inventory": { "track_batch": false, "track_expiry": false, "uom": ["Bag","Box","Kg","Piece"] },
  "customer_app": { "enabled": true, "self_order": true },
  "invoice_layout": "tax_invoice_wholesale",
  "ai_pack": "available"
}
```

Ship 5 formats first, matched to your local area: **wholesaler/distributor, kirana/grocery retailer, pharmacy, restaurant/café, hardware/general.** Pharmacy needs batch+expiry+drug license fields (Marg's moat — but you already have batch/expiry columns). Each format = one JSON + one invoice layout, **not** a code fork.

---

## 8. Local + Cloud architecture (offline-first sync)

He wants "installable locally" but also real-time sync with customers. These aren't contradictory if you do **local-first with cloud sync**:

- **Local install** (his shop PC): a packaged build — your FastAPI + a **local SQLite/Postgres**, run as a desktop service (e.g. an installer wrapping the backend + a local web UI, or a Tauri/Electron shell). Billing works 100% offline. This is the Vyapar-style trust ("my data is on my machine, it works when internet is down").
- **Cloud sync layer**: a sync engine pushes/pulls deltas to the cloud when online. Because you've **already migrated to Postgres and have Alembic**, the cloud side is ready; the local side mirrors the same schema.
- **Conflict strategy**: invoices are **append-only and owned by the merchant** (merchant is source of truth for sales); customer **orders** are append-only and owned by the customer until the merchant converts them to an invoice. Append-only + clear ownership avoids 90% of sync conflicts. Use `updated_at` (you have it on every model via `TimestampMixin`) + a per-row `sync_status` + a server-authoritative merge for the rest.
- **Real-time** for the customer app: cloud is the meeting point. Merchant local → cloud → customer app (and back). Use a lightweight push (WebSocket/Server-Sent Events; you already use SSE for chat) so the retailer sees "order accepted / invoice ready" live.

**Decision to make explicitly:** start **cloud-first with offline cache** (faster to ship, sync is simpler) OR **local-first with cloud sync** (matches his ask exactly, harder). My recommendation in §13.

---

## 9. AI as a paid subscription package (his monetization idea)

Exactly right, and you've already built the product — just gate it.

- **Billing module: cheap or free** to win the market (the wedge). Land users.
- **AI Pack (subscription)** unlocks what you already have: the chat assistant, smart insights advisor, the agent loop, gated actions (reminders/escalations/reorder POs), the morning digest, charts. You already log tokens per business and have `RateLimitConfig` with per-plan budgets — **the metering for tiered AI is already in code.**
- Gate at the route level by a `User.plan` flag (you already gate AI/actions conceptually in the blueprint Phase 4). Free users see the AI section with an "Upgrade to unlock" state.

This is clean SaaS: billing = acquisition, AI = margin.

---

## 10. Data-model additions (small — most exists)

You mostly extend, not rebuild:

1. `Order` + `OrderLineItem` (customer-placed B2B orders, before they become invoices). Mirror `Invoice`/`InvoiceLineItem`.
2. `CustomerUser` (auth identity for the retailer using the customer app) → links to `Customer` + `business_id`.
3. `BusinessTemplate` / a `business.format` field + template config loader.
4. `Plan` / `Subscription` (plan, status, period, what's unlocked) — or extend `User.plan`.
5. `EWayBill` / `EInvoice` records (payload, IRN, status) — partly covered by existing `Invoice` GST fields.
6. `SyncLog` / per-row `sync_status` + `updated_at` (you have `updated_at`).
7. `Offer`/`Campaign` (for the marketing push to customers).

That's the whole net-new data surface. Modest.

---

## 11. Build plan — phased, concrete, with a wedge-first sequence

The mistake would be building all three surfaces at once. **Land the one business owner first with the smallest thing that solves his #1 pain, then expand to the moat.**

### Phase 0 — Repackage + decide (1–2 weeks)
- Move current dashboard/chat under a **"AI Assistant"** section gated by plan. Make **Billing** the home.
- Decide cloud-first vs local-first (see §13) and the install mechanism.
- Build the **business-type registry** + signup format picker (5 formats).
- *Outcome:* the app reframes from "BI tool" to "billing app with an AI brain."

### Phase 1 — The Billing MVP that replaces his current system (3–5 weeks) ← **the wedge**
- SALE screen (fast billing, item master, auto-GST, PDF invoice, WhatsApp share, UPI QR).
- STOCK section (bulk import + AI invoice-photo parsing + reorder/expiry).
- E-way bill payload for > ₹50k (Part-A generation; API push can be Phase 2).
- Customer master + credit tracking (exists), payments.
- **This alone wins the customer.** It directly kills manual entry, generates invoices, handles >₹50k, separates stock vs sale, one app, easy.

### Phase 2 — The Customer App (the USP) (4–6 weeks)
- `CustomerUser` auth + branded catalogue (PWA first — installable, no app-store friction, works on any phone).
- Order → real-time into merchant → confirm → auto-invoice → sync back.
- Their ledger + UPI payment + reorder.
- Strict per-business + per-customer data scoping.
- *Outcome:* his retailers order from home; this is the demo that sells the next 10 wholesalers.

### Phase 3 — Sync + Local install hardening (3–4 weeks)
- Offline-first local build + delta sync engine + conflict rules.
- Real-time push (SSE/WebSocket) for order/invoice/offer events.

### Phase 4 — Marketing & monetization layer (2–3 weeks)
- Offers/campaigns push to customer app + WhatsApp.
- Subscription/plan gating for the AI Pack; billing for subscriptions.
- AI advisor now reasons over real billing + order demand data.

### Phase 5 — Multi-format depth + scale
- Pharmacy (drug license, batch/expiry mandatory), restaurant (KOT/tables), etc.
- Redis for shared cache/sync at scale (you already flagged the single-worker constraint).
- E-invoice IRN API for businesses above threshold.

---

## 12. Pricing & monetization (anchored to the market I checked)

The billing floor is ~₹1,000/yr (Vyapar). Don't undercut into unsustainability; **differentiate on the customer app + AI.**

| Tier | Price (illustrative, validate locally) | What's in it |
|---|---|---|
| **Starter (Billing)** | Free or ~₹999/yr | Billing, stock, invoices, e-way bill, WhatsApp share — match Vyapar to remove the reason to say no |
| **Pro (+ Customer App)** | ~₹4,000–8,000/yr | Everything + branded customer ordering app, real-time sync, offers/marketing |
| **AI Pack** | ~₹500–1,500/mo add-on | Chat assistant, insights, agent actions, digest — metered by your existing token budgets |
| **Per-seat/usage** | small | Extra staff logins; very large customer bases |

Money also comes from: **customer-app adoption driving Pro upgrades**, and later **payments/credit** (UPI collection, financing referrals) — a fintech layer once volume exists.

---

## 13. My recommendation (the honest opinionated part)

1. **Say yes to the business owner, but scope it to Phase 1 first.** Win him with the billing MVP that kills manual entry and handles >₹50k. Don't promise the whole ecosystem on day one — deliver the pain-killer, earn the reference.
2. **Go cloud-first with strong offline caching, not local-first, for v1.** Local-first sync is the hardest engineering in this whole plan and will sink your timeline. You already run Postgres + Alembic in the cloud. Ship cloud + a robust offline cache that queues bills when internet drops and syncs on reconnect. Offer a true local install in Phase 3 once the product is proven. Tell him: "works offline, your data syncs and is backed up" — that satisfies the real need (uptime + safety) without the multi-master nightmare.
3. **The customer app is the company, not a feature.** Billing gets you in the door; the branded retailer-ordering network is the moat and the viral loop. Treat Phase 2 as the strategic priority the moment Phase 1 lands.
4. **Lean on what you have, hard.** Your GST schema, column-mapper, PDF parser, multi-tenant scoping, token metering, and the AI engine are all real assets. The narrative "we already have the AI brain and the data model; we're adding the billing skin and the customer network" is both true and compelling to investors/customers.
5. **Pick a vertical to dominate locally first.** Don't be "billing for everyone" on day one. Pick the format your first customer is (wholesaler/distributor), nail it end-to-end including his retailers, own that niche in your town, then template outward. Retailio became huge by owning *only* pharma first.

---

## 14. Risks & how to de-risk

- **Scope explosion** → phase ruthlessly; Phase 1 must stand alone and be sellable.
- **Billing is commoditized** → never compete on billing alone; the customer app is the reason to choose you. If you only ship billing, you're a worse Vyapar.
- **Sync correctness** → append-only + clear ownership + cloud-authoritative; avoid multi-master until forced.
- **GST/e-invoice compliance is legally serious** → get one real e-way bill + e-invoice flow validated by a CA before selling it as compliant. Gate e-invoice by turnover flag so you don't mis-issue.
- **Customer-app adoption depends on the retailers' tech comfort** → PWA (no app store), WhatsApp-native flows, one-tap reorder, vernacular UI.
- **Trust** → it's their money and their customers. Keep the AI's *actions* gated (preview→confirm→audit — you already built this) and the billing numbers deterministic (never AI-generated). This is exactly the discipline your current architecture already enforces.

---

## 15. The one-paragraph pitch (for the business owner / future customers)

> "Replace your billing system with BizAssist — bill in seconds, no more typing every item (snap a supplier invoice or scan a barcode), auto e-way bills above ₹50,000, stock and sales in one clean app that works even when the internet doesn't. Then give *your* retailers their own ordering app with your prices and live stock — they order from home, the invoice generates itself and lands back in your books automatically, and you push them offers in one tap. And whenever you want, ask your AI business advisor what to reorder, who to chase for payment, and how to grow. One app. Your whole business and your customers, connected."

---

### Immediate next step
If you want, I can turn **Phase 1 (Billing MVP)** into a concrete engineering task breakdown against your current codebase — exact new endpoints, the SALE/STOCK React pages, the invoice-PDF + e-way bill generation, and the `Order`/`CustomerUser` schema migrations — so you can start building the thing that lands this customer.
