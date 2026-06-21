# BizAssist — Technology Architecture & Stack Decisions

*June 2026 · Companion to the Master Plan. Decision-first: each layer gives the options, pros/cons in a clear table, the **recommendation**, and **why** — mapped to your four needs: smooth & easy (bill / purchase / add / check), strong security, encrypted transactions, and **share only what should be visible, customizable per connection**.*

> Reading rule: **keep what already works** (React, FastAPI, Postgres, Groq, MiniLM, APScheduler). This doc recommends what to *add*, not rip out. "Pilot" = build now; "Scale" = add when you have many businesses. Don't pay the scale cost early.
>
> ⚠ Fast-moving tools (sync engines, managed clouds) change pricing/status often — verify current state before committing.

---

## 1. Architecture at a glance

```
 ┌──────────────────────────── ONE APP (per business, role/plan-aware) ───────────────────────────┐
 │  React + Vite PWA   ·  offline-capable  ·  keyboard/barcode-first billing  ·  installable        │
 └───────────────┬──────────────────────────────────────────────────────────────────┬─────────────┘
                 │ HTTPS / WSS (TLS)                                                  │ offline queue
                 ▼                                                                    ▼
 ┌──────────────────────────── FastAPI (API + scoping + sharing policy) ──────────────────────────┐
 │  auth (JWT+refresh, OTP) · per-business scope guard · selective-sharing serializer ·            │
 │  signing + hash-chain · rate-limit · AI router (existing) · OCR/classification automation       │
 └───────┬───────────────────────┬───────────────────────┬───────────────────────┬───────────────┘
         ▼                       ▼                       ▼                       ▼
   Postgres (cloud,         Realtime push          Object store           Razorpay (pay)
   encrypted, RLS)          (SSE → WSS)            (invoices/photos)       MSG91 (OTP/SMS)
         ▲                                                                  Groq + MiniLM (AI)
         │ delta sync (cloud-authoritative)
   SQLite/SQLCipher (encrypted offline cache, per device)
```

---

## 2. Layer-by-layer decisions

### 2.1 Front-end (the app)
| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **React + Vite as a PWA** *(recommended)* | You already have it; one codebase web+install; offline via service worker; instant updates; cheapest path | PWA hardware access (some printers) slightly limited vs native | ✅ **Use** — it's built, it's enough, it installs |
| React Native / Flutter (native mobile) | Best mobile feel, full hardware | Second codebase, app-store delays, more team | ⏳ Later, only if mobile retention demands it |
| Rebuild in Next.js / other | — | Throws away working code for no real gain | ❌ No |

**Why:** the win is *speed of billing*, not native polish. A well-built PWA bills in <1s and installs to the home screen. Don't fork into native until data says you must.

### 2.2 Offline desktop shell (the "install locally" feel)
| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **PWA "install to desktop"** *(pilot)* | Zero extra build; works today; auto-updates | No deep OS integration | ✅ **Pilot** |
| **Tauri** (Rust shell) *(scale)* | Tiny (~5MB), fast, real desktop app, bundles local DB, secure | New toolchain to learn | ✅ **Scale** — the real "local install" |
| Electron | Mature, lots of examples | Heavy (100MB+), RAM-hungry | ⚠ Avoid — Tauri is the modern, lighter choice |

**Why:** PWA gives the offline feel for the pilot. When a customer truly wants "an app on my PC," Tauri wraps the *same* React app + an encrypted local SQLite — far lighter than Electron.

### 2.3 Back-end API
| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **FastAPI (Python)** *(recommended)* | Already built + 385 tests; great for the AI layer; async; auto-docs | Python slower than Go for raw throughput (irrelevant at your scale) | ✅ **Keep** |
| Node/NestJS | One language with frontend | Rewrite; lose your AI/Python ecosystem | ❌ No |
| Go | Fastest, tiny memory | Rewrite; weaker AI/data-science libs | ❌ No |

**Why:** your moat work (AI router, embeddings, OCR) is Python-native. Throughput is a non-issue for thousands of local shops. Keep it.

### 2.4 Primary database (cloud, source of truth)
| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **PostgreSQL** *(decided)* | You migrated already; JSONB, RLS (row-level security = a second isolation wall), strong integrity, `pgcrypto` | Needs a managed host | ✅ **Keep** |
| MySQL/MariaDB | Familiar | Weaker RLS/JSON; no reason to switch | ❌ No |
| MongoDB | Flexible schema | Wrong for money/relations/ledgers — you need ACID + joins | ❌ No |

**Managed host:** **Neon** (serverless PG, branching, cheap to start) or **Supabase** (PG + realtime + auth bundled) for pilot; **AWS RDS / GCP Cloud SQL** at scale. Recommendation: **Neon for pilot** (cheap, pure PG, no lock-in), revisit at scale.

### 2.5 Offline DB + sync engine — *the hard one, choose carefully*
This is the single most complex technical decision. The buyer/seller chain forces sync.

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **Custom: encrypted SQLite + outbox queue + delta pull** *(recommended for pilot)* | Full control; append-only + idempotency make it tractable; no third-party lock-in/cost; matches D2/D5 | You build & test the sync logic | ✅ **Pilot** — cloud is authoritative; device queues writes offline, pulls deltas on reconnect |
| **PowerSync** (Postgres↔SQLite sync service) | Purpose-built for exactly this; handles conflicts/partial replication | New dependency, cost, maturity to verify | ✅ **Evaluate at scale** |
| **ElectricSQL** (Postgres sync) | Local-first, reactive | Younger; verify current status | ⏳ Watch |
| **RxDB / WatermelonDB** (client DBs + sync) | Good offline UX | You still write the server sync; another abstraction | ⚠ Maybe |
| Full local-first multi-master (CouchDB/PouchDB) | True offline-first | The "nightmare" — multi-master conflicts on money. **Master plan D5 says no** | ❌ No |

**Why:** because money is **append-only** and the cloud is **authoritative** (D2/D5), you don't need a heavy sync framework for the pilot — a simple **outbox** (queue local writes) + **delta pull** (since-last-sync) + **idempotency keys** is enough and fully under your control. Adopt PowerSync only if hand-rolled sync becomes a burden at scale. **Do not** attempt multi-master.

### 2.6 Realtime (order pings, invoice-ready)
| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **SSE (server-sent events)** *(pilot)* | You already use it for chat; dead simple; one-way is all you need; works over plain HTTP | One-directional (fine here); long connections need tuning | ✅ **Pilot** |
| **WebSocket** *(scale)* | Bi-directional, lower latency | More infra (sticky sessions / a hub) | ✅ **Scale** if you need two-way |
| Managed (Ably / Pusher / Supabase Realtime) | No infra; scales for you | Cost; external dependency | ⏳ Scale option |

**Why:** orders/invoices are server→client notifications — SSE is the perfect, cheap fit you've already proven. Upgrade to WSS or a managed bus only when fan-out hurts (ties to your single-worker→Redis note).

### 2.7 Auth & identity (incl. OTP + BizID)
| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **JWT access + refresh (self-managed)** *(recommended)* | Already built (bcrypt + JWT); full control; cheap; works offline-ish | You own rotation/revocation | ✅ **Keep + add refresh + server-side revocation** |
| Managed (Clerk / Auth0 / Supabase Auth) | OTP, social, MFA out of the box; less code | Cost per MAU; lock-in; another dependency | ⏳ Consider if auth becomes a burden |
| **Phone OTP** for the buyer/light side | Indian SMBs live on phone numbers; low friction | Per-SMS cost | ✅ Add via **MSG91** (India) or Twilio |

**BizID** is issued at signup (random `BA-XXXXXX`, collision-checked) and is the public identity (Master Plan §16.2). Auth stays internal; BizID is the *public* handle.

### 2.8 Encryption & key management (the "strong security")
| Concern | Technology | Notes |
|---|---|---|
| **In transit** | TLS 1.2+ everywhere (HTTPS/WSS). Caddy (auto-HTTPS) or the managed host's TLS | Non-negotiable; HSTS on |
| **At rest — DB** | Managed PG storage encryption + **`pgcrypto` / app-level AES-256-GCM** for sensitive columns (GSTIN, phone, UPI, KYC) | Column-level for the crown jewels |
| **At rest — offline cache** | **SQLCipher** (encrypted SQLite) | A stolen laptop ≠ a plaintext price book |
| **At rest — backups** | Encrypted with separate keys | Tested restores |
| **Signing transactions** | **Ed25519** via libsodium / PyNaCl; per-business keypair; public key on the BizID | Tamper-evidence (Master Plan §6 #18) |
| **Hash-chain ledger** | SHA-256 chaining of shared-ledger entries | Detects any past-entry tampering |
| **Key store** | Cloud KMS (AWS/GCP) or **HashiCorp Vault**; envelope encryption | Keys never in code/DB; scheduled rotation |

**Why this combination:** TLS + at-rest covers the basics every app needs; **signing + hash-chain** is the *differentiator* (a neutral, tamper-proof record between two businesses — a real moat, not a checkbox).

### 2.9 Selective data sharing — *"share only what's visible, customizable per connection"* (your key ask)
This deserves its own engine. See **§4** for the full model. Tech choices:

| Approach | Pros | Cons | Verdict |
|---|---|---|---|
| **Server-side sharing policy + scoped serializer** *(recommended)* | One place decides what crosses a connection; seller customizes per buyer/tier; enforceable + testable; AI/search still work | Server (you) can technically read the data | ✅ **Use** — the right default |
| **Field-level encryption for crown jewels** | Even a DB dump doesn't expose GSTIN/UPI/KYC | Can't index/search encrypted fields | ✅ **Add for the few most-sensitive fields** |
| **End-to-end encryption (E2E) of shared docs** | Even *you* can't read a shared invoice; ultimate privacy pitch | **Breaks server-side AI, search, analytics on that data**; key management on phones is hard | ⚠ **Selective only** — consider for specific ultra-sensitive shares later; not the default (it would kill your AI moat) |

**Recommendation:** default to **server-enforced selective sharing** (a per-connection visibility policy) + **field-level encryption** for the handful of crown-jewel fields. Hold E2E in reserve for specific cases — it's a great privacy story but it would blind your AI advisor, which is a moat. Be deliberate about that trade.

### 2.10 Payments
| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **Razorpay** *(recommended, India)* | UPI/cards/wallets, subscriptions, payouts, vaulting (keeps you out of PCI scope), good docs | India-focused (fine) | ✅ **Use** |
| Cashfree / PhonePe PG | Competitive India options | Compare fees at signup time | ⏳ Alternatives |
| Stripe | Best DX globally | Weaker India/UPI footprint | ❌ For India, no |

**Rule:** never store card data — Razorpay vaults it. Manual plan activation for the pilot; self-serve checkout later.

### 2.11 AI & intelligent automation (the "smooth" + the classification you mentioned)
Reuse what you built; add the automation that removes manual work.

| Capability | Technology | Role in "smooth & easy" |
|---|---|---|
| **Query/intent routing** | Your existing 4-tier + LLM router (Groq `llama-3.1-8b`) | Already done; powers the AI Advisor |
| **Invoice/photo OCR → items** | OCR (Tesseract / a cloud OCR / a vision-LLM) → your `pdf_parser` + column-mapper → review | **Kills manual entry** when adding stock/purchases (the wedge wow) |
| **Item auto-classification & mapping** | Reuse the router/classification pattern: map messy supplier names → your product master; suggest HSN/GST/category | Smooths "add product" — no manual tagging |
| **Smart autofill at billing** | Local item index + frequency ranking; "frequently bought together"; last-price recall | A 5-line bill in seconds |
| **Embeddings/memory** | MiniLM (local, free) — already built | Semantic search, advisor memory |

**On "the classification / big process that suits us" — the named pipeline:** reuse the router's *classification* idea **inside billing/stock**, as one explicit, testable flow:

> **Detect → Map → Confidence → Review → Commit**
> 1. **Detect** — OCR reads the supplier invoice; classify supplier, invoice type, line items.
> 2. **Map** — match supplier item names to *your* product master (fuzzy + embeddings); suggest HSN / tax slab / category for anything new.
> 3. **Confidence** — every mapped line carries a confidence score.
> 4. **Review** — the user sees the result and confirms/corrects (high-confidence rows pre-ticked; low-confidence flagged).
> 5. **Commit** — only *then* do the purchase invoice + stock-ledger movements write.

**The hard rule: never auto-commit low-confidence financial data.** Money never moves on a guess — a human confirms. This same pipeline powers (a) supplier-invoice upload (Phase 2) and (b) the buyer importing a synced invoice (Phase 4). Build it once as a module; reuse it. It mirrors the LLM router's "structured output + confidence + confirm" discipline, so it stays accurate and auditable.

### 2.12 Invoice/PDF + e-way
| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **WeasyPrint** (HTML/CSS → PDF) *(recommended)* | Design invoices in HTML/CSS (easy, themeable per business); clean output | Heavier render | ✅ **Use** — per-format invoice layouts as HTML templates |
| ReportLab | Precise, fast | Layout in code = painful to theme | ⚠ If you need pixel control |
| wkhtmltopdf / Puppeteer | HTML→PDF | Extra binary/headless browser | ⚠ Heavier ops |
| Thermal printer | ESC/POS library | Hardware-specific | ✅ Add for retail counters |

### 2.13 Background jobs
| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **APScheduler** *(pilot)* | Already used (alerts/digest); in-process; simple | Process-local (your single-worker note) | ✅ **Pilot** |
| **Celery + Redis** *(scale)* | Distributed, reliable, retries | More infra | ✅ **Scale** when multi-worker |
| RQ | Simpler than Celery | Fewer features | ⚠ Middle option |

### 2.14 Hosting / infra
| Stage | Recommendation | Why |
|---|---|---|
| **Pilot** | A managed PaaS (Render / Railway / Fly.io) + **Neon** Postgres + object storage (S3/R2) | Fast, cheap, low-ops; ship in days |
| **Scale** | AWS/GCP (RDS, ECS/GKE, KMS, S3) or stay on a managed PaaS with a read-replica + Redis | Failover, replicas, KMS, no single point of failure (Master Plan §16.4) |

### 2.15 Cache / rate-limit / realtime-fanout store
- **Pilot:** in-process (what you have). Honestly documented single-worker constraint.
- **Scale:** **Redis** — shared cache, rate-limit windows, scheduler lock, realtime fan-out. This is the named fix for your single-worker limitation.

---

## 2.16 Code architecture — modular monolith (NOT microservices) + the patterns

**Decision: a modular monolith.** One backend, one database, one frontend — but with **clean, independent internal modules**. Microservices would slow you down badly at this stage (deploys, network calls, distributed transactions, ops). Your FastAPI app can carry the whole thing if it's structured well. Split into services *only* if a specific module ever needs independent scale — and probably never for years.

**The modules (clean boundaries inside one app):**
`billing` · `purchase` · `stock` · `product` · `customer_supplier` · `connection` · `order` · `shared_invoice` · `ai_advisor` · `subscription` · `security_audit`

Each module owns its tables, services, and tests; modules talk through clear function/interfaces, not by reaching into each other's internals.

**The patterns to use (clean + testable — not heavy OOP inheritance):**
| Pattern | Where | Why |
|---|---|---|
| **Domain services** | billing, stock, orders, sync | One place per domain owns its rules; thin routes call them |
| **Command handlers** | `CreateSaleInvoice`, `AcceptSupplierInvoice`, `PlaceOrder`, `ConvertOrderToInvoice` | Every money-changing action is one explicit, testable command — easy to audit, retry (idempotency), and log |
| **State machines** | order (`pending→accepted→packed→dispatched→completed`), invoice (`draft→issued→paid`) | Illegal transitions become impossible, not just discouraged |
| **Strategy pattern** | business-type templates | Add a format (pharma, restaurant) = a strategy + config, no forks |
| **Policy engine / sharing serializer** | connection visibility (§4) | The single gate deciding what a connected buyer may see |
| **Outbox pattern** | sync + realtime events | Write the event in the same DB transaction as the data → no lost/duplicated events on sync/push |
| **Append-only ledger** | stock + shared transactions | Source of truth; rebuildable; tamper-evident |

> Keep it clean and testable: commands + domain services + state machines + the sharing serializer give you a system that's easy to reason about and hard to corrupt — far better than deep class hierarchies.

---

## 3. "Smooth & easy" — how each action stays instant (the UX engineering)

Smoothness is a *technical* commitment, not a design wish. Per action:

- **Bill (Sales):** item master cached **locally** → autocomplete is instant (no network). Keyboard-first: type→Enter→qty→Enter→pay→Enter→printed. **Optimistic UI** (the bill shows immediately; sync happens in the background). Billing **never** waits on the cloud, AI, or an LLM call. Target: 5-line bill < 45s, works fully offline.
- **Purchase / add stock:** the four fast paths (scan, bulk import, **OCR a supplier bill → auto-map**, PO→receipt). The OCR/classification does the typing for you; you only *review & confirm*.
- **Check (stock / dues / reports):** read from the **local cache** first (instant), reconcile with cloud in the background. "Why is stock 3?" answered from the stock ledger instantly.
- **Order (from a supplier):** the supplier's catalogue is cached after connect → browse/cart offline → the order queues and sends on connect. The reply (accepted/invoice) arrives via SSE.

**The rule (also a cardinal rule):** the daily money path (bill / add / check) is **local-first + optimistic**; the network and AI are **additive, never blocking.** That's what makes it feel instant even on a weak shop connection.

---

## 4. The selective-sharing & visibility model (your "customize what retailers can see")

This is a first-class subsystem — the technical form of "share only the deal, not the books" (Master Plan D10/§6).

**Concept:** every **connection** carries a **visibility policy** the *seller* controls. When a buyer reads anything about the seller, the data passes through **one server-side "sharing serializer"** that returns only what the policy allows — never raw rows.

**What the seller can customize per buyer (or per price-tier):**
- **Catalogue scope:** all products / only selected / per-category.
- **Price:** which **tier** price this buyer sees (standard/silver/gold); hide MRP/cost (cost is *never* shared).
- **Live stock visibility:** show exact stock / show "in stock / low / out" band / hide entirely.
- **Credit terms:** their credit limit & dues (their own, never others').
- **Offers:** which campaigns this buyer/segment receives.
- **Documents:** which of *their* invoices/ledger entries they can see (always only their own).

**How it's enforced (so it can't leak):**
1. A `connection` row + a `sharing_policy` (JSON config) per connection.
2. **One** `SharingSerializer` that every cross-business endpoint must pass through — it takes (viewer_business_id, target_business_id, data) and returns only policy-allowed fields. No endpoint hand-rolls this.
3. **Postgres Row-Level Security** as a second wall, so even a buggy query can't cross a tenant.
4. **Negative tests** assert a buyer can never receive a disallowed field (cost, other customers, totals).

**Result:** a wholesaler can give Retailer A live stock + gold pricing, and Retailer B banded stock + standard pricing, from the *same* catalogue — fully customizable, and provably leak-proof.

---

## 5. Transaction security & encrypted exchange (detailed)

The lifecycle of a shared invoice, end to end:
1. Seller creates the invoice → **signed with the seller's Ed25519 private key**.
2. The shared-ledger entry includes the **hash of the previous entry** (hash-chain) → tampering with any past entry is detectable.
3. Sent over **TLS**; stored **encrypted at rest**; the sensitive fields **column-encrypted**.
4. Buyer's app **verifies the signature** against the seller's public key (published on the seller's BizID) → proves authenticity + integrity.
5. The buyer sees only the **policy-allowed** fields (§4).
6. Both ledgers update; balances reconcile; the record is **append-only** (corrections = new signed reversing entries).

**Net guarantees:** authenticity (it really came from that BizID), integrity (not altered), confidentiality (encrypted + field-scoped), non-repudiation (signed + chained), availability (append-only + backups). That's "strong encrypted transaction" done properly — and it doubles as your dispute-resolution moat.

---

## 6. Recommended stack — one-glance summary

| Layer | Pilot (build now) | Scale (add later) |
|---|---|---|
| App | React + Vite **PWA** | Tauri desktop wrap; native mobile if needed |
| API | **FastAPI** (existing) | + horizontal scaling behind LB |
| DB | **Postgres** on **Neon** | RDS/Cloud SQL + read replica + RLS |
| Offline+sync | **SQLCipher + outbox/delta** (custom) | evaluate **PowerSync** |
| Realtime | **SSE** (existing) | WebSocket / managed bus |
| Auth | **JWT+refresh** + **MSG91 OTP** | managed (Clerk/Auth0) if needed |
| Crypto | TLS, pgcrypto/AES-GCM, **Ed25519 sign + SHA-256 chain**, SQLCipher | Cloud **KMS** / Vault |
| Sharing | **Server sharing serializer + RLS** | + field-level enc; selective E2E |
| Payments | **Razorpay** (manual activation) | self-serve + UPI collection |
| AI | **Groq + MiniLM** (existing) + **OCR/classification** | fine-tune, more tools |
| PDF | **WeasyPrint** + thermal | e-way API aggregator |
| Jobs | **APScheduler** | **Celery + Redis** |
| Infra | managed PaaS + Neon + S3/R2 | AWS/GCP + **Redis** + KMS |

---

## 7. Don't over-build — pilot vs scale

The fastest way to fail is to build the scale stack for one pilot shop. **For the pilot, the only *new* infrastructure you truly need is:** a managed Postgres, an object store, Razorpay, an OTP provider, and the **encrypted offline cache + simple sync**. Everything else (Redis, KMS, Celery, PowerSync, Tauri, WebSocket) is a *scale* upgrade with a clear trigger. Build the moats (BizID, signing/hash-chain, sharing serializer) **correctly from day one** because they're foundational; defer the scale plumbing until load demands it.

---

## 8. Update & release delivery — "send upgrades" safely

A core requirement: when you improve the app, **every business gets it without reinstalling** — and you can also **unlock features/plans remotely**. This is an Apple-like strength *and* a danger: on a financial app, one bad update that breaks billing for everyone at once is an extinction event. So "send upgrades" must mean **staged, signed, reversible, backward-compatible** updates — never a big-bang push.

### 8.1 Two kinds of "upgrade"
1. **Software updates** — new app code / fixes / features pushed to all installs.
2. **Feature & plan unlocks** — turn on AI Pro, the Network tier, a new capability for *one business* (or a cohort) **instantly, server-side, no reinstall**. Same machinery (remote flags) drives your monetization upsells.

### 8.2 How updates reach each surface
| Surface | Mechanism | Notes |
|---|---|---|
| **PWA (pilot)** | Service worker fetches the new build; user gets a **"New version — refresh"** prompt on next open | Near-instant, no app store, no reinstall. **A key reason PWA wins for the pilot.** |
| **Tauri desktop (scale)** | Built-in **auto-updater** checks a release endpoint → downloads a **signed** update → installs | Updates must be **cryptographically signed** so no one can push malware to your users |
| **Backend/API** | You deploy centrally (managed PaaS) | The risk isn't deploying — it's *breaking old clients*; see §8.4 |

### 8.3 Never break billing — the safe-rollout rules
1. **Staged rollout (canary):** release to 1 → 5% → 25% → 100%, watching error rates. Never 0→100.
2. **Kill-switch + instant rollback:** any release can be reverted in one click; feature flags can disable a broken feature *without* a redeploy.
3. **Feature flags / remote config:** ship code "dark" (off), turn it on per cohort. This is also how you **unlock paid features per business** (§8.1).
4. **Billing path is sacrosanct:** the daily money flow (bill/add/check) gets extra rollout caution and its own health metric. If billing error rate ticks up, auto-halt the rollout.
5. **Health-gated:** rollout pauses automatically if crash/error/latency crosses a threshold.

### 8.4 Backward compatibility — the non-obvious hard part (Apple-like "nothing breaks")
Because the network is **distributed and offline-tolerant**, at any moment businesses run **different app versions** — and two of them on different versions still have to transact. So:
- **Versioned API + inter-business contract:** the server supports the last N client versions; the shared invoice/order "contract" between two businesses is version-tagged and tolerant (new fields optional, old fields never removed). An old client must never be broken by a new server.
- **Additive client-side migrations:** when an update changes the local (SQLite) schema, run additive, nullable, reversible migrations on the device — same discipline as your Alembic chain, client-side. A failed migration must not corrupt local data.
- **Min-supported-version gate:** for a *critical security* update only, a soft gate ("please update to continue"); otherwise updates are optional and seamless.

### 8.5 Update security
- Updates (especially Tauri) are **signed**; the client verifies the signature before installing. Ties to your KMS/signing keys (§2.8).
- Remote-config/flag changes are **authenticated + audited** (who flipped what, when) — a flag that unlocks a paid feature is a money event.

### 8.6 What to build when
- **Pilot:** PWA auto-update (basically free) + a simple **feature-flag/remote-config** table (`business.plan` + a `feature_flags` config you already partly have) so you can unlock features and dark-ship. That's enough to "send upgrades" on day one.
- **Scale:** Tauri signed auto-updater, a proper staged-rollout/flag service (e.g. self-hosted Unleash or a managed flag tool), automated health-gating, and formal API-version support.

> **The rule:** *upgrades are staged, signed, reversible, and backward-compatible — never a big-bang push, and never able to break the billing path.* That's how you ship constant improvements (the "always getting better" Apple feel) on a system people run their money on.

---

## 9. Decisions this surfaces (add to Master Plan §13)
1. **Managed Postgres host:** Neon (recommended, no lock-in) vs Supabase (bundled realtime/auth, more lock-in) vs RDS.
2. **Sync:** custom outbox/delta now (recommended) vs adopt PowerSync early.
3. **Sharing privacy level:** server-enforced + field-encryption (recommended) vs add selective E2E (and accept it blinds AI on those fields).
4. **OTP/SMS provider:** MSG91 (India) vs Twilio.
5. **Desktop install:** PWA now, Tauri later (recommended) — confirm the owner actually needs a true desktop install or if PWA suffices.
6. **Update tooling:** PWA auto-update + a simple feature-flag table now (recommended) vs adopt a managed flag/rollout service early.
