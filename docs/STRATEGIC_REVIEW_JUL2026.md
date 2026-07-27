# BizAssist — Strategic Expert Review (July 2026)

Senior product-architecture and market review. Every claim below is anchored to the actual repo: `core/` domain modules, `services/` AI stack, `database/` + 36 Alembic migrations, 105 backend test files (~745 test functions), three frontends, desktop shell, and Playwright e2e.

> **Re-audit addendum — 25 Jul 2026.** The repo was swept again end-to-end (142 backend modules / ~37.7k LOC, 113 test files / **779 test functions**, 36 migrations, 4 frontends / ~52.8k LOC, 42 frontend unit tests + 2 Playwright specs, 3 CI workflows). Sections 1–10 below are the original review and are **retained unchanged as the baseline**. Everything new — what has since been closed, what is newly found, and what is newly recommended — lives in **§11–§14**. Read §11 first if you only want the delta.

---

## 1. Executive Verdict

This is not a billing app codebase. It is an early-stage **business operating system** with an unusually disciplined modular-monolith architecture that most funded Series-A SaaS teams do not have.

Three things put it above its stage:

1. **The `core/` vs `services/` split is a real strategic decision, not tidiness.** The core README explicitly states the doctrine: billing/stock/accounting is the painkiller, AI is a paid add-on wired last, `core/` has zero dependency on AI code. That is product strategy encoded in the directory tree — rare.
2. **Financial engineering is taken seriously.** Double-entry posting (`core/accounting/posting.py`) with a SHA-256 tamper-evident hash chain (`_chain_hash`, `GENESIS`, `verify_chain`), fixed-2dp hashing to eliminate float noise, period locks, trial balance tests. This is accounting-grade thinking at prototype stage.
3. **The sync layer already solves the problems that kill offline-first products** — UID-first entity matching, LWW with `ConflictLog`, per-row SAVEPOINTs so one bad row can't stall the outbox forever, FK remap via parent UIDs, integrity-dedupe on concurrent pushes.

**Category verdict:** BizAssist can credibly become the "operating layer" for Indian SME commerce — Tally's ledger rigor + Vyapar's usability + an AI advisor + a BizID-based B2B network none of them have. The foundation supports that thesis. The distance to production is real but it is hardening work, not rearchitecting work.

---

## 2. Highest USPs (ranked)

1. **Local-first billing with real cloud sync** — SQLite local mode, Postgres/Supabase cloud mode, frontend outbox (`frontend-billing/src/sync/outbox.js`, `syncManager.js`, `applyDelta.js`, cursor-based pull), LAN discovery of local backends by BizID (`routes/discovery.py`). Billing works when the internet doesn't — the single most decisive feature for tier-2/3 Indian retail. Vyapar does offline; almost nobody does offline **plus** durable-UID multi-device sync plus LAN discovery.
2. **AI grounded in the business's own ledger, not chat.** Tiered intent routing (`ai_router_decision.py` DIRECT tier, semantic classify, shadow routing), direct query handlers reading real invoices/stock/payments, `memory_service.distill_memory()` producing confidence-scored `BusinessFact` rows, golden-set regression tests (`golden_set.jsonl`). The AI answers "who owes me money" from the actual party ledger.
3. **Preview → Confirm → Audit action lifecycle** (`services/actions.py`): every AI action has a side-effect-free preview, an explicit confirm label, and an audit row per item (`ActionLog`). This is the correct safety architecture for AI touching money — and it's a sellable trust story, not just engineering hygiene.
4. **BizID as network identity** — public-safe BizID lookup API (`core/api/biz_id.py`), invite codes with expiry and single-use (`B2BInviteCode`), explicit `B2BConnection`, buyer/seller `B2BOrder`, and a cross-business `B2BLedger` (order|invoice|payment|credit_note). The schema for a supplier-buyer network already exists.
5. **Supplier-buyer network effects.** Because both sides run the same system, a B2B order can become the seller's sales order and the buyer's purchase order, and the shared `B2BLedger` becomes the single agreed truth for inter-business credit. That's the wedge every "khata" app wanted and none earned.
6. **Accounting-grade auditability** — hash-chained journal entries, `verify_chain`, period locks (`core/accounting/period_lock.py`, `test_period_lock.py`), automatic posting from every commercial document (sale, purchase, payment, expense, credit/debit note). Tamper-evidence is a compliance and lending story, not just a feature.
7. **Deterministic GST engine** in `core/billing/commands.py` — intra/inter-state resolution via place of supply, tax-inclusive/exclusive line math, atomic invoice numbering with collision recovery, plus an e-invoice module (`core/compliance/einvoice.py`) pointing at IRN readiness.
8. **Unified data spine**: one atomic transaction writes Invoice + line items + append-only `StockLedger` + journal entries. Billing, inventory, accounting, and BI are views over one consistent event stream — the structural advantage every "integrations" competitor lacks.
9. **Business-type templates** (`core/templates/configs/*.json`: medical, restaurant, supermarket…) — vertical-aware onboarding without forking the product.
10. **Operational realism for Indian counters**: register shifts with strict gatekeeping and shift-scoped cash tallies, cash movements, godowns, stock transfers, barcode catalog with multi-code packaging revisions (`core/catalog`).
11. **Multi-tenant security as migrations, not intentions** — five RLS migrations including fail-closed policies and init-plan optimization, tested on real Postgres (`test_rls_postgres.py`, `test_db_guard_fail_closed.py`).
12. **Test depth as a moat-in-waiting**: 105 test files spanning accounting invariants, hash chain, sync idempotency, UID cross-db, RLS, AI routing tiers, rate limiting, action rails — the regression net that lets a small team move fast on financial code.

---

## 3. BizID and the Ecosystem Moat

BizID is the difference between a tool and a network. Analyzed layer by layer:

**Identity layer.** A durable public identifier with a safe public-profile lookup (`core/api/biz_id.py` deliberately returns "ONLY safe public profile data"). It already does double duty: network identity in the cloud *and* LAN service discovery locally (`/discover/{biz_id}`). One identifier spanning both worlds is a genuinely original primitive.

**Trust layer.** Connections are consent-based: invite codes are single-use and expiring, connections are explicit rows, and B2B tables got their own RLS hardening migration (`harden_b2b_rls_policies`). Trust is opt-in and revocable — the correct foundation; most B2B marketplaces bolt trust on after spam ruins them.

**Supplier-buyer graph.** `B2BConnection(buyer, seller)` edges over BizID nodes form a real commercial graph. Every order and payment flowing through it is a weighted, verified edge — transaction-backed, not self-reported. This graph cannot be scraped or bought; it can only be earned through daily billing usage.

**Shared catalog / order network.** Seller catalogs exposed over a connection turn a phone-call-and-WhatsApp reorder into a structured `B2BOrder` that lands directly in both parties' systems. Every reorder deepens lock-in on both sides simultaneously — the two-sided switching cost normal billing apps never get.

**Ledger / credit / reputation foundation.** `B2BLedger` is the sleeping giant: a mutually visible inter-business ledger of orders, invoices, payments, and credit notes. Combine it with hash-chained journals and you get **verifiable payment behavior** — the raw material for credit scoring, invoice discounting, and supply-chain finance. In a market where SME credit assessment is the binding constraint, a network of tamper-evident, counterparty-confirmed ledgers is bank-grade data no bureau has.

**Defensibility.** The moat compounds in stages: single-player utility (offline billing) → data gravity (ledger + AI memory) → two-sided switching costs (connected suppliers/buyers) → graph effects (each new business makes the network more valuable) → financial-infrastructure position (credit rails on top of verified ledgers). Stages 3–5 are unreachable for competitors who don't own both sides of the transaction. BizID is defensible **only if** it stays durable, unique, and verification-backed — see P2 recommendations.

---

## 4. Architecture Strengths

**Domain-modular monolith.** `core/{billing, stock, accounting, catalog, purchase, order, connection, compliance, shifts, sync, templates}` each with narrow public APIs via `__init__.py`; one shared SQLAlchemy Base so a sale writes Invoice + StockLedger + Journal in one transaction. The README explicitly rejects premature microservices while keeping file-level ownership clean — the right call, correctly reasoned.

**Command-style write paths.** `create_sale_invoice`, `record_payment`, `create_credit_note` are atomic command handlers owning GST math, stock movement, numbering, and journal posting. One choke point per financial mutation — exactly where invariants belong.

**Accounting core.** Append-only `StockLedger` as inventory truth (with `rebuild_inventory_cache`), double-entry `JournalEntry`/`JournalLine`, hash chain, period locks, per-document posting builders (`build_sale_lines`, `build_purchase_lines`, …).

**Cloud-readiness.** 36 Alembic migrations; SQLite/Postgres dual-mode; Supabase compatibility; RLS evolved through five migrations to fail-closed with performance-tuned policies; per-device hosting mode.

**Sync stack.** Durable UUID `uid` columns on synced models, UID-first matching with legacy id fallback, LWW with conflict logging, parent-FK resolution by UID shared between push and pull-apply, per-row SAVEPOINT isolation, idempotency keys (`core/sync/idempotency.py`), realtime delta relay + SSE hardening (stateless HMAC tickets).

**AI stack.** Router façade split into decision/cache/execution modules; tiered routing (direct handlers vs LLM), shadow-routing telemetry to compare classifiers in production; context engine + cache with salt/scoping tests; rate limiter and token accounting; memory distillation into confidence-scored facts; action rails; agent loop/graph direction.

**Frontend separation.** Billing app (the daily tool, with its own sync engine and Playwright e2e), AI dashboard (the paid add-on), admin console, landing site, desktop shell — clean commercial boundaries matching the "AI wired last" doctrine.

**Testing.** ~745 backend test functions covering exactly the things that must not break: trial balance, hash chain, period locks, party ledger, purchase commit, sync idempotency, UID cross-db, RLS on Postgres, routing tiers, action rails, golden-set AI regressions, plus frontend component tests and e2e.

---

## 5. What Is Unusually Strong

- **Strategy encoded in structure.** The core-vs-AI split with an explicit written doctrine is founder-level product thinking living inside the codebase.
- **Hash-chained journals at this stage.** Nearly no pre-launch SME product has tamper-evident accounting. Most never add it.
- **Sync failure-mode maturity.** Per-row SAVEPOINTs to prevent outbox stalls, UID dedupe on concurrent pushes, FK remap by parent UID — these are lessons teams usually learn from production incidents; here they're pre-solved and tested.
- **AI evaluated like infrastructure**: golden-set regression file, shadow routing, token accounting, cache-scoping tests. Most "AI features" ship with zero eval harness.
- **RLS as an evolved, tested artifact** (five migrations, fail-closed, Postgres-tested) rather than a checkbox.
- **Test-to-code ratio and invariant focus** far above typical early-stage repos.

---

## 6. Highest Risks (practical, ordered)

1. **Financial correctness invariants are enforced by convention, not by the database.** Nothing structurally prevents a code path from writing an Invoice without journal lines, or a payment exceeding the invoice balance. One missed posting silently breaks trial balance.
2. **Multi-tenant identity is `users.id` (integer).** B2B tables FK to `users.id` as "business id". Business ≠ user; multi-user businesses, ownership transfer, and cross-database identity all strain this. The `uid`/BizID columns exist but integer ids are still the join spine.
3. **LWW sync silently discards data.** Conflicts are logged (`ConflictLog`) but the losing write vanishes from the user's view. Two clerks editing the same invoice offline = lost financial data. Acceptable for profiles; not for invoices and payments.
4. **Negative stock and concurrency edges.** Append-only stock ledger is right, but oversell under concurrent offline billing (two devices selling the last unit) needs an explicit policy — block, allow-and-flag, or reconcile.
5. **Invoice numbering under multi-device offline operation.** `_next_invoice_number` + collision recovery works single-node; two offline devices generating sequential GST invoice numbers will collide by design. GST requires unique sequential numbering — this needs per-device series or post-sync renumbering rules.
6. **AI action safety depends on preview honesty.** The rails are right, but previews and executes are separate functions — drift between "what preview showed" and "what execute does" is the failure mode. No structural guarantee execute matches preview.
7. **Migration/data integrity across the SQLite↔Postgres boundary.** Dual dialects + 36 migrations + data-transfer flows = divergence risk; SQLite's weak typing can let bad data into cloud.
8. **Observability is logs-and-telemetry-events, not production SLOs.** No visible error aggregation, sync-lag metrics, trial-balance drift alarms, or hash-chain verification scheduling.
9. **Single-process assumptions** in scheduler, sync worker, rate limiter, and caches. Fine for local mode; cloud mode with many tenants needs shared-state versions (Postgres advisory locks / Redis) before horizontal scale.
10. **Mobile/PWA polish.** The counter is desktop-first, but Indian SME owners live on phones; the AI advisor and B2B ordering in particular are phone-shaped experiences. Nothing in the repo yet treats mobile as first-class.

---

## 7. High-Leverage Recommendations

### P0 — must be correct before serious production usage

| Recommendation | Why / Subsystem / Outcome |
|---|---|
| **DB-level financial invariants.** CHECK constraints + triggers (or post-commit assertions) enforcing: every posted document has balanced journal lines; payments ≤ invoice balance; stock ledger is append-only; period-locked rows immutable. | *Why:* code review can't catch every path; the DB can. *Subsystem:* `core/accounting`, `core/billing`, migrations. *Unlocks:* the "your books are provably correct" claim that justifies premium pricing. |
| **Per-device GST invoice number series** (e.g. `A1/…`, `A2/…` prefixes per registered device) with a tested reconciliation rule at sync. | *Why:* offline collision on sequential numbers is a GST-compliance failure, not a bug. *Subsystem:* `core/billing/commands.py`, sync. *Unlocks:* safe multi-counter offline billing — the flagship promise. |
| **Field-level / document-aware conflict policy for financial entities.** Keep LWW for cosmetic data; for invoices/payments, reject-and-queue-for-review instead of silent overwrite, and surface `ConflictLog` in the UI. | *Why:* silently losing a payment record destroys trust permanently. *Subsystem:* `routes/sync.py`, frontend sync. *Unlocks:* honest multi-device operation. |
| **Explicit negative-stock policy** (per business setting: block / allow-with-flag) enforced inside `create_sale_invoice`. | *Why:* oversell is the most common real-world offline edge. *Subsystem:* `core/stock`, `core/billing`. *Unlocks:* predictable inventory truth. |
| **Structural preview=execute guarantee**: execute consumes the stored preview payload (hash-bound), refusing if state changed since preview. | *Why:* the audit story collapses if execute can diverge from what the user confirmed. *Subsystem:* `services/actions.py`. *Unlocks:* AI actions on payments/inventory without fear. |
| **Scheduled `verify_chain` + trial-balance drift checks with alerting.** | *Why:* tamper-evidence only matters if someone checks. *Subsystem:* accounting, scheduler, telemetry. *Unlocks:* continuously self-auditing books — a marketing weapon. |

### P1 — makes the product trustworthy and scalable

| Recommendation | Why / Subsystem / Outcome |
|---|---|
| **Promote Business to a first-class entity** (Business table, BizID as durable key, users as members with roles) and migrate B2B FKs off `users.id`. | *Why:* the whole ecosystem thesis rests on business identity outliving any user account. *Subsystem:* models, auth, B2B, RLS. *Unlocks:* multi-user businesses, ownership transfer, credible BizID. |
| **Production observability**: Sentry-class error tracking, sync-lag and outbox-depth metrics per tenant, RLS-denial counters, AI cost dashboards. | *Why:* offline-first failures are invisible without measurement. *Subsystem:* backend-wide, telemetry. *Unlocks:* operating hundreds of tenants with a tiny team. |
| **Kill single-process state**: move scheduler/rate-limit/cache state to Postgres (advisory locks, `FOR UPDATE SKIP LOCKED` job queue) or Redis. | *Why:* first horizontal scale event otherwise causes double-sends and double-posts. *Subsystem:* `services/scheduler.py`, `rate_limiter.py`, `sync_worker.py`. *Unlocks:* boring cloud scaling. |
| **Cross-dialect migration CI**: run the full Alembic chain + invariant suite against both SQLite and Postgres on every PR; add data-validation gates to local→cloud transfer. | *Why:* dual-dialect drift is a slow leak. *Subsystem:* alembic, data_transfer. *Unlocks:* safe upgrades for non-technical users. |
| **Mobile-first PWA for the owner surface** (AI advisor, insights, B2B orders, payment reminders) while the counter stays desktop. | *Why:* the buyer of the subscription is the owner, and the owner is on a phone. *Subsystem:* frontends. *Unlocks:* daily-active owners, not just daily-active clerks. |
| **Backup/restore + tenant export as a product feature.** | *Why:* SMEs fear data loss above all; local-first makes them their own DBA. *Subsystem:* data_transfer, desktop. *Unlocks:* trust at the moment of purchase. |

### P2 — market differentiation and ecosystem advantage

| Recommendation | Why / Subsystem / Outcome |
|---|---|
| ⭐ **THE standout move — "BizID Verified Ledger": make the B2B ledger mutually confirmable and export a signed statement.** Both parties' apps counter-sign ledger entries over the existing hash chain; one tap produces a verifiable statement of receivables/payment history a bank or NBFC can trust. | *Why:* this converts daily billing into **creditable financial identity** — the single feature no billing app, khata app, or ERP can copy without owning both sides of the transaction. It is the bridge from software revenue to fintech revenue (invoice discounting, working-capital referrals) and the reason a supplier *requires* their buyers to be on BizAssist. *Subsystem:* `B2BLedger`, `core/accounting` hash chain, BizID. *Unlocks:* the network's killer app and the category-defining moat. |
| **Shared-catalog reordering v1**: supplier publishes catalog to connections; buyer reorders in two taps; order auto-drafts the seller's sales order and the buyer's PO. | *Why:* replaces the WhatsApp+phone reorder ritual; every reorder deepens two-sided lock-in. *Subsystem:* `core/catalog`, `core/order`, `core/connection`. *Unlocks:* viral supplier→buyer distribution (each supplier onboards 50–500 buyers). |
| **Compliance autopilot**: finish e-invoice/IRN, add GSTR-1/3B-ready exports generated from the journal. | *Why:* compliance is the #1 stated reason Indian SMEs pay for software. *Subsystem:* `core/compliance`, accounting. *Unlocks:* accountant-channel distribution — accountants become your sales force. |
| **AI monthly "CA-style review"**: proactive insight digest (margin shifts, dead stock, receivable aging, GST anomalies) built on smart_insights + memory facts. | *Why:* moves AI from novelty chat to a monthly ritual worth paying for. *Subsystem:* `smart_insights`, `memory_service`, notifier. *Unlocks:* retention + the "AI munim" positioning. |
| **BizID public trust profile** (opt-in): tenure on platform, verified GSTIN, connection count, on-time payment badge. | *Why:* seeds reputation before credit products exist. *Subsystem:* `core/api/biz_id.py`, B2B. *Unlocks:* discovery of new trustworthy counterparties — the graph starts growing beyond existing relationships. |

---

## 8. Product Positioning

**Positioning statement:**

> **BizAssist is the operating system for Indian SME commerce: billing that works without internet, books that can't be silently altered, an AI advisor that knows your actual business, and a BizID that connects you to your suppliers and buyers on one shared, trustworthy ledger.**

Against the field:

| Category | They are | BizAssist is |
|---|---|---|
| Billing apps (Vyapar, myBillBook) | Invoice generators with basic reports | A full double-entry, hash-chained accounting spine under every invoice — books a lender can trust |
| POS tools | Single-counter transaction capture | Shift-managed, multi-device, offline-first counters syncing to one cloud truth |
| ERP-lite / Tally | Accountant-operated, single-business, offline silos | Owner-operated, networked across businesses via BizID, with AI on top |
| Khata/ledger apps | Self-reported IOUs | Transaction-backed, counterparty-confirmable B2B ledgers |
| AI chatbots / copilots | Generic answers bolted onto someone else's data | AI grounded in the business's own journal, with preview-confirm-audit rails on every action |

The one-line differentiator: **everyone else digitizes documents; BizAssist digitizes the relationships and the trust between businesses.**

---

## 9. Investor / Founder Narrative

Sixty-plus million Indian MSMEs run on paper, WhatsApp, and memory. The ones that digitize buy billing apps — and hit a ceiling, because a billing app only sees one side of every transaction.

BizAssist starts where the market demands: offline-first GST billing that works in a power cut, on the counter, today. That's the wedge, and it's already engineered for the hard parts — sync, conflicts, multi-device, tamper-evident books.

But every invoice in BizAssist does triple duty. It updates stock, posts double-entry journals into a hash-chained audit trail, and — when the counterparty is also on BizAssist — writes to a **shared B2B ledger both sides agree on**. That last part is the business: a supplier on BizAssist has a reason to pull all their buyers on, each buyer is a new node, and every transaction is a verified edge in a commercial trust graph that cannot be scraped, bought, or replicated.

The endgame is financial infrastructure. Verified, counterparty-confirmed, tamper-evident ledgers are exactly what SME lending lacks. BizAssist doesn't have to become a lender — it becomes the **source of truth lenders pay to trust**, monetizing software today (billing + AI advisor subscriptions), the network next (B2B commerce), and the graph last (credit rails). Tally built a generation-long moat on trust in the books. BizAssist rebuilds that trust networked, offline-capable, AI-assisted — and owned by the platform where both sides of every trade already live.

---

## 10. Scorecard

| Dimension | Score | Basis |
|---|---|---|
| Product depth | **8.5/10** | Billing + stock ledger + double-entry + shifts + godowns + B2B + AI in one spine; thin spots: mobile, reporting UI |
| Architecture quality | **8.5/10** | Disciplined modular monolith, command handlers, façade-split AI router; docked for single-process state and `users.id`-as-business |
| Market relevance | **9/10** | Offline-first + GST + shifts + godowns is exactly the Indian SME reality; compliance autopilot still pending |
| AI differentiation | **8/10** | Grounded handlers, action rails, memory distillation, golden-set evals — far beyond bolt-on chat; agent loop still maturing |
| B2B ecosystem potential | **9/10** | BizID + connections + orders + shared ledger schema all exist; score is potential — the network is unproven in the wild |
| Production readiness | **5.5/10** | Strong tests and RLS, but observability, invariant enforcement, conflict UX, and scale-out state are open |
| Security posture | **7.5/10** | Fail-closed RLS tested on Postgres, TOTP, SSE hardening, audit logs; needs pen-testing, secrets discipline, business-entity auth model |
| Data model maturity | **7/10** | Rich domain coverage with UIDs and mixins; integer-id business identity and dual-dialect drift hold it back |
| UX / commercial readiness | **6/10** | Clear app separation, templates, landing, desktop shell; mobile owner-surface and onboarding polish missing |
| Long-term moat | **8.5/10** | Data gravity + two-sided switching costs + trust graph + hash-chain credibility — contingent on executing BizID-verified ledgers |

**Composite: ~7.8/10 — exceptional foundation, pre-production hardening remaining.**

### The single best move to stand out

Ship the **BizID Verified Ledger** (P2 ⭐) on top of the P0 correctness work: mutually confirmed B2B ledger entries, counter-signed over the existing hash chain, exportable as a bank-trustable statement. It is the only feature in this space that gets *stronger* with every competitor's absence from the network, it converts daily billing into financial identity, and it is the moment BizAssist stops competing with billing apps and starts becoming infrastructure.

---
---

# Part II — Re-Audit Addendum (25 July 2026)

Second full pass over the repository. §1–§10 above are the unchanged baseline. This part records **what closed**, **what is newly found**, and **what is newly recommended**.

**Measured state at this pass**

| Metric | Baseline (§0) | Now | Δ |
|---|---|---|---|
| Backend modules (`core` + `services` + `routes` + `database`) | — | 142 files / ~37,657 LOC | — |
| Backend test files / test functions | 105 / ~745 | **113 / 779** | +8 files, +34 tests |
| Alembic migrations | 36 | 36 | — |
| Frontends | 3 + desktop | 4 (`billing`, `ai`, `admin`, `landing`) + desktop shell | — |
| `frontend-billing` source | — | 213 JS/JSX files, ~52,808 LOC incl. CSS | — |
| Frontend unit tests / e2e specs | — | 42 / 2 | — |
| CI workflows | — | `ci.yml`, `release.yml`, `sonar.yml` | — |
| `TODO`/`FIXME` in `core`+`services`+`routes` | — | **2** | unusually clean |

---

## 11. What Has Been Closed Since the Baseline Review

Four of the six original **P0** items are now genuinely implemented — not stubbed. This is a materially different repo from the one §6/§7 described.

| Baseline item | Status | Evidence in repo |
|---|---|---|
| **P0 — Scheduled `verify_chain` + trial-balance drift checks** | ✅ **Closed** | `core/accounting/integrity.py` composes `posting.verify_chain` with a global `SUM(debit) == SUM(credit)` foot check into a never-raising `run_integrity_check`, plus a raising `assert_books_intact` for guards. Registered as a real scheduled job — `services/scheduler.py` `add_job(run_books_integrity_audit, id="books_integrity_audit")` — and exposed on demand via `core/api/reports.py::report_verify_chain`. |
| **P0 — Explicit negative-stock policy** | ✅ **Closed** | `core/billing/commands.py::_negative_stock_blocked` reads the owner's `transactions.prevent_negative_stock` toggle; `_enforce_negative_stock_policy` is invoked inside the sale command path (line ~408), i.e. enforced at the choke point, not at the route. Default surfaced in `routes/auth.py` settings blob. |
| **P0 — Per-device / per-counter GST invoice series** | ✅ **Closed (with a caveat — see F-1)** | `_next_invoice_number(db, business_id, counter_prefix)` mints an independent series per terminal (`C1-0001`, `C2-0001`, `OW-0001`), falling back to legacy `INV`. `_free_invoice_number` re-numbers *within the same series* on collision rather than merging two distinct bills. |
| **P0 — Structural preview = execute guarantee** | ✅ **Closed** | `services/actions.py::preview_fingerprint` produces a SHA-256 canonical hash of the preview payload (excluding cosmetic keys); `services/action_rails.py` mints and verifies an HMAC `confirm_token` binding `business_id + action + params + expiry`. Execute cannot diverge from the confirmed preview. |
| **P1 — Conflict visibility in the UI** | ✅ **Backend closed** | `GET /api/sync/conflicts` now surfaces `ConflictLog` with an `unreviewed_count` badge counter and both payloads for side-by-side review. The comment in `routes/sync.py` explicitly notes conflicts "were written but never exposed anywhere" — that gap is fixed server-side. Frontend review screen still pending. |
| **P1 — Error tracking** | ⚙️ **Partially closed** | `main_groq.py` has an opt-in `SENTRY_DSN` init path. Still no sync-lag / outbox-depth / RLS-denial metrics. |

**Still open from the baseline:** DB-level financial invariants (no `CHECK` constraints outside the four RLS migrations), Business-as-first-class-entity (§6.2), single-process scheduler/rate-limiter/cache state, cross-dialect migration CI, mobile-first owner PWA.

---

## 12. New Findings

Ordered by severity. Each is anchored to a specific file.

### F-1 · 🔴 Critical — B2B connection is established **without the counterparty's consent**, exposing the full catalog and exact stock

`core/connection/service.py::create_direct_connection` writes `status="accepted"` immediately, and `core/api/connections.py` `POST /connections/connect` calls it with no approval step. Consequences:

- **Anyone who knows your BizID can connect to you as a buyer.** BizID is *designed to be shared publicly* (§3, "public-safe BizID lookup"). One POST creates an `accepted` edge.
- The new default policy is `stock_visibility="exact"`, `price_tier="standard"`, `catalog_category=None` — so `GET /catalog/{seller_bizid}` immediately returns **every active product, its selling/wholesale/distributor tier price, HSN, MRP, and exact on-hand stock count**. This is a competitor-intelligence leak, not a UI bug.
- The seller finds out only by opening the B2B page and noticing a stranger under "My Customers".
- Symmetrically, `connect_as="seller"` lets a stranger unilaterally insert themselves into your "My Suppliers" list — a phishing surface for fake supplier orders.

This directly contradicts §3's claim that "connections are consent-based" — that is true of the **invite-code** path (`B2BInviteCode`, single-use, expiring) but **not** of the BizID path, which is the one the UI actually promotes.

### F-2 · 🔴 Critical — Revocation is reversible by the revoked party

Same function: when a connection row already exists, it does `conn.status = "accepted"` unconditionally. A business you revoked can re-POST `/connections/connect` and **silently restore its own access**. Revocation is therefore not durable, which undermines the entire trust layer described in §3.

### F-3 · 🟠 High — Invoice numbering is `COUNT`-based, so deletions reuse numbers — ✅ **CLOSED (Jul-2026)**

`_next_invoice_number` computes `COUNT(Invoice.id) WHERE invoice_id LIKE '{prefix}-%'` and emits `count + 1`. If any invoice in a series is ever deleted or hard-purged, the next issued number **duplicates a previously issued one**. GST requires numbers to be unique *and never reused* for the financial year. The correct primitive is a persisted per-(business, series) counter row incremented under a row lock, or `MAX(sequence) + 1` over a dedicated integer column — never a row count. This is the caveat on the otherwise-closed P0.

**Resolution (N3).** The counter is now stored, not derived:

- **`core.models.DocumentSequence`** (`document_sequences`, `UNIQUE(business_id, series)`) holds `last_number`. It only ever moves up, so a deletion cannot walk it backwards. Alembic `a7d3f0c9e514`; new table, so the local SQLite path gets it from `Base.metadata.create_all()` — no `_COLUMN_MIGRATIONS` entry is needed.
- **`core/billing/sequence.py`** reserves a value with one `UPDATE … SET last_number = <CASE>`, which takes the row lock on Postgres and the write lock on SQLite. That closes the read-then-write race too — the old `COUNT` let two counters read the same value and both mint it, with `renumber_on_conflict` catching it only after the fact.
- **Reservation lives in the caller's transaction**, so a rolled-back sale (validation failure, negative-stock block) releases its number and leaves no gap. Gaps remain legal and auditable regardless; reuse does not.
- **Credit notes** use the same mechanism on their own `CN` series — Rule 46 applies to them as well, and they had the identical `COUNT`-based bug.
- **Upgrade + drift.** A brand-new counter is seeded from the highest number already in the series, so an existing install continues rather than restarting at 1. The table is deliberately **not** in `sync_map.MODEL_MAP` (it is per-database counter state, exactly as the `COUNT` it replaces was), so rows arriving from the cloud pull or an import can leapfrog a local counter; `next_number` then heals the counter **forward** to the observed maximum. Healing never lowers it.
- Pinned by `backend/tests/test_invoice_sequence.py`.

The partial unique index on `(business_id, invoice_id)` that N3 also called for is **still open** — the allocator now guarantees uniqueness in application code, but the database does not yet enforce it (see N4, DB-level financial invariants).

### F-4 · 🟠 High — B2B order numbers rely on an unbounded random-retry loop

`core/order/service.py::create_order` spins `while True` generating a 4-char suffix from a 32-char alphabet and re-querying the DB until it finds a free one. Collision probability rises with daily volume (birthday bound: ~50% collision risk around 1,000 orders/day), the loop has **no attempt cap**, and the check-then-insert is not atomic — two concurrent requests can both pass the existence check and one will hit the `unique` constraint as a 500. Use a date-scoped sequence or a UUID-derived suffix with a bounded retry.

### F-5 · 🟠 High — B2B list endpoints are unpaginated and N+1

- `GET /connections` → two `.all()` queries, then `_conn_out` issues **two extra `User` queries per connection row**.
- `GET /orders?role=…` → `.all()` over the business's entire order history, then `_order_out` per row.

At a few hundred connections/orders this is already a multi-second page load, and it is the exact surface the B2B revamp is about to put in front of users. Needs `limit`/`offset` (or cursor) plus a joined-load of the counterparty `User`.

### F-6 · 🟡 Medium — Duplicate SSE connections per page

`pages/B2BOrders.jsx` opens its **own** `EventSource` against `/realtime/events` (minting its own ticket) *in addition to* the app-wide `sync-event` listener it also registers. Every page that does this multiplies long-lived server connections per user. Realtime should be a single app-level transport that fans out via the existing `sync-event` custom event.

### F-7 · 🟡 Medium — God components and a monolithic stylesheet

`Sales.jsx` 2,544 lines · `Settings.jsx` 2,309 · `AppLayout.jsx` 1,886 · `Payments.jsx` 1,474 · `CheckoutModal.jsx` 1,399 · `StockIntakeSheet.jsx` 1,304 · `Stock.jsx` 1,269. A **single** `index.css` of 4,775 lines serves the whole app. The `components/` extraction pattern (`components/sales/*`, `components/stock/*`, `lib/posColumns.js`) is clearly the intended direction and is well done where applied — it just hasn't reached the largest files. This is the main brake on frontend velocity and the main source of merge conflicts.

### F-8 · 🟡 Medium — XSS-shaped realtime toasts

`B2BOrders.jsx::handleRealtimeEvent` builds toast strings by interpolating server-supplied `event.buyer_name` into a template that *also contains literal JSX-as-text* (`` `<PackageIcon size={16} … /> New B2B Order placed by ${event.buyer_name}` ``). Today it renders as escaped text inside `{toast.msg}`, so it is a **display bug, not an active vulnerability** — but the pattern is one `dangerouslySetInnerHTML` away from stored XSS via a crafted `business_name`. Toasts should carry structured `{icon, message}`, never markup strings.

### F-9 · 🟡 Medium — Operational scripts tracked as top-level source

19 tracked debug/repair/inspection scripts sit at the repo root and `backend/` root: `debug_fk.py`, `debug_remap.py`, `repair_line_items.py`, `repair_pass2.py`, `check_ledger.py`, `check_upi_biz.py`, `scan_db.py`, `dump_schema.py`, `reset_owner_password.py`, `reset_supabase.py`, … Several mutate production-shaped data (`repair_*`, `reset_supabase`, `reset_owner_password`) and none are covered by tests. They belong under `backend/scripts/` with a guard requiring an explicit `--i-understand` flag plus environment assertion. *(Credit where due: the `.db` binaries and `cloud_sync_tokens.json` are correctly gitignored — verified, not tracked.)*

### F-10 · 🟡 Medium — Connection policy is seller-only, but the buyer bears the credit risk

`update_connection_policy` allows only `seller_business_id` to write. Reasonable for pricing — but `credit_limit` and `outstanding_balance` live on the same row, so the buyer has no ability to record its own view of the relationship, and there is no counter-signature. For the §7-P2 ⭐ *Verified Ledger* to be bank-credible, the credit terms have to be **bilaterally acknowledged**, not seller-declared.

### F-11 · 🔵 Low — Frontend table UX has no persisted column model outside POS

`lib/posColumns.js` is a genuinely good pure-function column model (labels, default order, forward-migration of saved orders) with unit tests. But it governs *order only, not width*, and only the POS cart uses it. Every other data table (`Stock`, `Invoices`, `Parties`, B2B) has hardcoded widths that truncate real Indian product names. *(This is being addressed in the same change-set as this review.)*

### F-12 · 🔵 Low — Fullscreen table overlay is flush to the viewport top

`.table-fullscreen-panel` / `.table-fullscreen-header` in `index.css` (~line 4279) give the expanded-table header no top inset, so it collides with the window chrome in the desktop shell. *(Also addressed in this change-set.)*

---

## 13. New Recommendations

### N-P0 — Correctness and trust (do before any B2B go-live)

| # | Recommendation | Why / Where |
|---|---|---|
| **N1** | **Make B2B connections request→approve.** Default new connections to `status="pending"`, record who initiated (`requested_by_business_id`), and gate `get_supplier_catalog` / `create_order` on `accepted` (they already check this — the bug is purely that nothing is ever `pending`). Add `approve` / `reject` / `cancel` endpoints addressable only by the *counterparty*. | Closes **F-1**. Restores the consent property §3 claims. `core/connection/service.py`, `core/api/connections.py`, new Alembic migration. |
| **N2** | **Make revocation sticky.** A `revoked` row may only return to `accepted` through a fresh request approved by the party that revoked it. | Closes **F-2**. Same module. |
| **N3** | **Replace count-based invoice numbering with a locked sequence row** per `(business_id, series)`, and add a partial unique index on `(business_id, invoice_id)`. | Closes **F-3**. Without it the per-counter series (a closed P0) still mints duplicates after any deletion. |
| **N4** | **DB-level financial invariants** — still the highest-value open item from the baseline. Now cheap to add, because `core/accounting/integrity.py` already defines exactly what "intact" means; promote those assertions into `CHECK` constraints + triggers so they hold against paths that bypass the command layer. | Baseline P0, still open. |
| **N5** | **Bounded, atomic B2B order numbering** — date-scoped sequence or UUID suffix, insert-and-catch rather than check-then-insert, hard retry cap. | Closes **F-4**. |

### N-P1 — Scale and maintainability

| # | Recommendation | Why / Where |
|---|---|---|
| **N6** | **Paginate + eager-load every B2B list endpoint** (`/connections`, `/orders`). Return `{items, total, cursor}`; `joinedload` the counterparty `User`. | Closes **F-5** before the revamped B2B workspace makes these the busiest reads in the app. |
| **N7** | **One realtime transport per app session.** Hoist the `EventSource` into a context/provider that re-broadcasts as `sync-event`; pages subscribe, never connect. | Closes **F-6**. Also removes per-page reconnect storms. |
| **N8** | **Structured notifications.** Toast payloads become `{icon, title, body}`; no markup in strings anywhere. | Closes **F-8** permanently rather than relying on React's escaping. |
| **N9** | **Decompose the seven >1,200-line components** using the pattern already proven in `components/sales/` and `components/stock/`, and split `index.css` into per-domain sheets or CSS modules. Budget: no page component over ~400 lines. | Closes **F-7**. This is the single biggest frontend-velocity unlock. |
| **N10** | **Quarantine operational scripts** into `backend/scripts/` with a shared `_guard.py` requiring explicit environment + `--confirm`. | Closes **F-9**. |
| **N11** | **Reusable table primitives.** One `useResizableColumns` hook (drag-resize, auto-fit-to-content, per-user + per-table localStorage persistence, reset) plus the existing `posColumns` ordering model, adopted by every `data-table`. | Closes **F-11**; makes column UX a platform capability instead of a per-page rewrite. |

### N-P2 — Ecosystem differentiation (extends §7-P2 ⭐)

| # | Recommendation | Why / Where |
|---|---|---|
| **N12** | **Bilateral connection terms.** Both parties counter-sign `credit_limit` and payment terms; store the acknowledgement in `B2BLedger` over the hash chain. | Closes **F-10** and is the missing precondition for the ⭐ *BizID Verified Ledger*: a credit limit only one side asserted is not bank-usable evidence. |
| **N13** | **Connection request inbox as a growth loop.** A pending request is a *notification with a name attached* — the natural place to show "3 businesses want to connect", and the hook that pulls a supplier's buyers onto the platform. Ship it with the approval flow (N1), not after. | Turns the security fix of F-1 into the distribution mechanic §3 depends on. |
| **N14** | **Order lifecycle as a first-class workspace** — dedicated ordering surface (catalog browse → cart → place), separated from the incoming/outgoing fulfilment queues, each with its own filters, saved views and status rail. | The current single-table B2B page treats "place an order" as a modal afterthought; ordering is the daily ritual the network is supposed to own. |

---

## 14. Revised Scorecard

| Dimension | Baseline | Now | Movement |
|---|---|---|---|
| Product depth | 8.5 | **8.5** | — |
| Architecture quality | 8.5 | **8.5** | Backend hardened; frontend god-components offset the gain |
| Market relevance | 9 | **9** | — |
| AI differentiation | 8 | **8.5** | ▲ HMAC-bound preview→confirm→execute is now structural (`preview_fingerprint` + `action_rails`) |
| B2B ecosystem potential | 9 | **8** | ▼ Potential unchanged, but F-1/F-2 mean the trust layer does not currently hold — recoverable in one change-set |
| Production readiness | 5.5 | **6.5** | ▲ Scheduled books-integrity audit, negative-stock policy, per-counter series, conflict API |
| Security posture | 7.5 | **6.5** | ▼ Consent-free connection + unilateral un-revoke is a live data-exposure path on a public identifier |
| Data model maturity | 7 | **7** | — `users.id`-as-business still the join spine |
| UX / commercial readiness | 6 | **6** | — Table ergonomics and B2B workspace being addressed now |
| Long-term moat | 8.5 | **8.5** | — Still contingent on the Verified Ledger |

**Composite: ~7.6/10.** Slightly below the baseline 7.8 — not because the codebase regressed (it clearly improved: +34 tests, four closed P0s, two TODOs across 37k backend LOC) but because this pass found a concrete consent/exposure defect in the B2B layer that the first review took on faith from the schema. Fix N1–N2 and the composite lands at ~8.0.

### The single highest-priority action, restated

**Ship the connection approval flow (N1 + N2) before anything else B2B.** It is simultaneously a security fix, a trust-layer repair, and — via the request inbox (N13) — the growth loop the whole ecosystem thesis rests on. The Verified Ledger (§7-P2 ⭐) remains the destination; consent-based, non-reversible connections are the road to it.

---

# Part III — Money-Model & Security Audit (26 July 2026)

Scope of this pass: (a) the reported "B2B request auto-accepts" defect, (b) whether
every rupee that moves through the POS lands in a durable, reconcilable backend
record, (c) whether hybrid sync reproduces that record faithfully on both sides,
(d) security exposure. Findings are numbered **M-n** (money model) and **S-n**
(security) to keep them distinct from Part II's F-n.

## 15. Closed in this pass

| # | What | Where |
|---|---|---|
| **F-3** | Invoice + credit-note numbering moved off `COUNT` onto a stored monotonic counter. Deletions can no longer reissue a number. | `core/models.DocumentSequence`, `core/billing/sequence.py`, alembic `a7d3f0c9e514`, `tests/test_invoice_sequence.py` |
| **M-1** | **Consent bypass via NULL `requested_by_business_id`** — see below. | `core/connection/service.py`, `core/connection/transfer.py`, `core/api/connections.py`, `tests/test_connection_approval.py` |

### M-1 · 🔴 Critical — F-1 was reopened by a nullable column (FIXED)

The reported symptom was "a B2B request is sent but is immediately accepted".
It is not a UI bug. `requested_by_business_id` is **nullable** — it has to be, it
was added by `ALTER TABLE` to a populated table, and rows also arrive via
`core/connection/transfer.py` imports and the cloud→local mirror without it.

Every consent check compared it with `==` / `!=`, and `None` loses **both**. A
NULL requester therefore read as *"somebody other than you"* everywhere:

```
request_connection(A)   → pending, requested_by = NULL
request_connection(A)   → `NULL == A` is False  → "not my own request"
                        → mutual-intent branch → approve_connection(A)
                        → `NULL == A` is False  → self-approval guard silent
                        → status = "accepted"
```

**Sending the same request twice self-approved it**, with no counterparty
involvement — the exact exposure the July hardening was written to close.
`is_awaiting` carried the mirror of the bug: `NULL != viewer` is True for *both*
parties, so the requester was shown an Approve button on their own request.

A second, quieter instance: the data-transfer importer copied
`requested_by_business_id` **verbatim from the source database**, where it is a
different tenant's `users.id`. Whichever local business happened to hold that
integer became the recorded requester — occasionally the counterparty, which
hands the importer a link nobody agreed to.

**Fix — rule R3: an unknown requester fails closed.** "We cannot prove who asked"
must never collapse into "therefore not you".

- `has_known_requester()` / `is_requester()` make the unknown state explicit and checked.
- `approve_connection` refuses outright when the requester is unknown.
- `request_connection` **claims** an unattributed pending row for the caller (which names the *other* party as approver) instead of auto-accepting it.
- `cancel_request` fails closed (it deletes rows); `reject_connection` stays open (it only ever denies).
- The importer re-points the requester through the same bizid mapping as the two parties; anything unmappable becomes NULL.
- Such rows are no longer invisible: `unclaimed_requests` + `requester_unknown` surface them for re-sending.

**The generalisable lesson, and why it is listed as an architectural rule below:**
a nullable column used in a security decision is a third truth value, and `==`
silently votes "no" for it. Every consent/authorisation comparison must gate on
presence *before* it compares equality.

## 16. New Findings — Money Model

### M-2 · 🔴 Critical — The double-entry journal does not sync

`journal_entries`, `journal_lines` and `period_locks` are **absent from
`database/sync_map.MODEL_MAP`**. Every sale calls `posting.post_sale(db, inv)`
and writes a balanced journal in the same transaction — but on a hybrid install
the invoice, its line items, the stock movements and the payment receipt all push
to the cloud while **the journal does not**.

Consequences, all silent:

- The cloud's trial balance, P&L and party ledger omit every locally-rung sale. Two databases, two different sets of books, no error anywhere.
- Invoices pulled cloud→local arrive with no journal on the local side either.
- `period_locks` not syncing means a period locked by the owner locally is **not** locked in the cloud, so a backdated write can still land there.
- The scheduled books-integrity audit runs per-database, so it reports "balanced" on both — each is internally consistent and jointly wrong.

This is the single largest gap between "the POS recorded it" and "the books
recorded it", and it is exactly the class of failure this audit was asked to find.

**Recommended fix — re-derive, don't replicate.** A journal is a deterministic
function of its source document, and `journal_entries` carries a **hash chain**
whose ordering is per-database; copying rows across would either break the chain
or force a rebuild anyway. So the apply side should re-run `post_sale` /
`post_credit_note` / `post_purchase` when a source document lands, keyed on the
existing `post_entry` source-key so it stays idempotent. `period_locks` is
ordinary owner-scoped data and should simply join `MODEL_MAP`.

### M-3 · 🟠 High — `(business_id, invoice_id)` has no uniqueness constraint

The new sequence allocator guarantees uniqueness *in application code*. The
database does not enforce it, so any path that writes an `Invoice` without going
through `create_sale_invoice` — an import, a sync apply, a repair script — can
still land a duplicate number, and the first thing anyone would notice is a
mismatched GSTR filing. Needs a partial unique index (`WHERE invoice_id IS NOT
NULL`, since CSV-imported rows may carry NULL). This is the open half of N3.

### M-4 · 🟠 High — B2B order numbers: unbounded random retry (F-4, still open)

`core/order/service.py::create_order` spins `while True` over a 4-char random
suffix with a check-then-insert. No attempt cap, not atomic, ~50% collision risk
around 1,000 orders/day. Now that `DocumentSequence` exists, the fix is to route
B2B order numbers through it on a date-scoped series and delete the loop.

### M-5 · 🟡 Medium — Money writes are not uniformly wrapped

37 `except: pass` handlers remain across `core/` + `services/`; the money command
modules themselves are clean (`core/billing`, `core/accounting`, `core/order`,
`core/purchase`, `core/shifts` have zero), but `core/api` and `services` carry
them, and several sit next to a `db.commit()`. Each needs classifying: a swallow
around a cache write is fine, a swallow around a ledger write is a lost rupee.
Needs an audited allow-list rather than a blanket sweep.

### M-6 · 🟡 Medium — Settlement surfaces lack an end-to-end reconciliation test

Shifts, cash movements, settle-dues, advance credit, credit notes and B2B ledger
postings each have unit tests, but there is no single test that rings a day of
mixed transactions through the POS and asserts that **cash drawer + receivables +
stock + journal all reconcile to the same total**. That is the test that would
have caught M-2 on the day it was introduced.

## 17. New Findings — Security

Baseline is genuinely good and worth stating: `JWT_SECRET` is env-required and
fails closed at import, passwords are bcrypt, Postgres RLS policies are `FORCE`
and fail-closed, and the preview→confirm→execute AI rail is HMAC-bound. The
findings below are the deltas.

### S-1 · 🔴 Critical — (= M-1) consent decisions on a nullable column

Listed under money for narrative reasons; it is a security defect first. Fixed.

### S-2 · 🟠 High — Unauthenticated endpoints need an explicit threat note

`routes/discovery.py` (`/discover/register`, `/discover/{biz_id}`) and
`routes/telemetry.py` (`/api/telemetry/log`, `/api/telemetry/import`) take no
auth dependency. Both are plausibly intentional (LAN peer discovery; telemetry
relayed from installs that may not hold a cloud token) — but an unauthenticated
`register` is a spoofing surface, and an unauthenticated `import` is an
unbounded write. Each needs either a shared-secret/HMAC, a strict rate limit, or
a written justification in the route docstring. Right now there is none.

### S-3 · 🟠 High — No DB-level guard behind the tenant filter on SQLite

RLS protects the cloud. Local installs are SQLite, where `business_id` filtering
is application-only — a single missing `.filter(business_id == ...)` is a
cross-tenant read. Desktop installs are usually single-tenant so the blast radius
is small, but the *B2B mirror* now puts a counterparty's rows in the local DB,
which changes that assumption. Needs a query-level audit of the mirror reads.

### S-4 · 🟡 Medium — Cross-backend token confusion has no test

The cross-tenant incident (Part II §8) was fixed by forbidding absolute URLs in
`authFetch`, but the prohibition is enforced by a **code comment**. It needs a
test that fails if `authFetch` regains absolute-URL passthrough, and one that
fails if any `b2b/` call site stops using `apiPath`.

## 18. Architectural Rules Added

9. **A nullable column may never carry a security decision by equality alone.** Check presence first (`has_known_requester`), then compare. `NULL == x` is False and `NULL != x` is True, so an unknown value silently votes for *both* "not the requester" and "not the approver". (M-1)
10. **Derived financial records are re-derived on the destination, never replicated.** Journals are a function of their source document and carry a per-database hash chain; the apply side re-posts them idempotently. (M-2)
11. **Application-level uniqueness is not uniqueness.** Every invariant the allocator guarantees needs a matching database constraint, or the next writer that bypasses the allocator breaks it silently. (M-3)

## 19. Execution Order

Ordered by "silent wrongness" — a defect that produces confidently wrong numbers
outranks one that produces an error.

| Stage | Work | Rationale |
|---|---|---|
| ~~0~~ | ~~M-1 consent bypass~~ · ~~F-3 numbering~~ | ✅ done |
| ~~1~~ | ~~M-2 journal + period-lock sync~~ | ✅ done — see §20 |
| **2** | **M-3 unique index** + **M-4 B2B order numbers** | Both are one-change-set closes now that `DocumentSequence` exists. |
| **3** | **M-6 reconciliation test** | Locks stages 1–2 in place and becomes the regression net for the whole money model. |
| **4** | **M-5 silent-swallow audit** | Wide, low individual risk, best done with the reconciliation test already green. |
| **5** | **S-2 / S-3 / S-4** | Real, but none is currently producing wrong data. |


## 20. M-2 closed — journals re-derived on the destination

Journals are **derived, not replicated**. `core/accounting/repost.py` re-posts
the entry on whichever database a document lands in, from that document, using
that database's own row id.

| Change | Where |
|---|---|
| `repost_synced_row()` — table→poster map, idempotent, savepoint-isolated, returns a `RepostResult` rather than swallowing | `core/accounting/repost.py` |
| `enforce_period_lock` threaded through `post_entry` + all six document posters | `core/accounting/posting.py` |
| Wired into the cloud-side apply, inside the per-row savepoint, after the paid-state reconcile | `routes/sync.py::push_changes` |
| Wired into the local-side pull-apply | `services/sync_worker.py` |
| `period_locks` added to `MODEL_MAP`, `_SYNC_TABLES` and `APPEND_ONLY_DELETE_BLOCKLIST` | `database/sync_map.py`, `database/models.py`, `routes/sync.py` |
| 20 tests | `tests/test_journal_repost_on_sync.py` |

Three decisions worth recording, because each has a failure mode that would
otherwise be discovered the hard way:

**Period locks are bypassed for replication only.** A lock stops a *user*
writing new history into closed books. A document arriving over sync was already
posted, legitimately, where it was authored — the two sides simply closed their
books on different days. Refusing it would leave the destination holding a
document with **no journal entry**, which is worse than a late entry in a closed
period. The flag is passed down the call stack; the first implementation patched
`posting.post_entry` as a module global for the duration of a call, which would
have leaked the bypass into any user-facing sale posting concurrently on another
thread — the sync worker is a background thread. Both behaviours are pinned by
tests.

**`period_locks` needed three registrations, not one.** `MODEL_MAP` alone is
pull-only; without `_SYNC_TABLES` the push side never enqueues it — the exact
asymmetry that previously stranded `register_shifts`. And it belongs in the
delete blocklist: a sync-borne DELETE would erase a close event and silently
re-open locked books. Books are re-opened by an explicit unlock *event*, never
by deleting the lock.

**Failures are collected, not raised and not swallowed.** A document that cannot
be posted must not abort the batch (one bad row would stall the whole outbox
behind it), but a missing journal entry means that database's books are short,
so it is logged at ERROR with the document identified and returned in the push
response as `journal_repost_failures`. The post runs inside its own SAVEPOINT —
catching the exception alone is not enough, because a failed flush leaves the
SQLAlchemy session unusable and would poison every subsequent row in the batch.

### Still open on the money model

`M-3` (unique index on `(business_id, invoice_id)`), `M-4` (B2B order numbers),
`M-6` (end-to-end reconciliation test), `M-5` (silent-swallow audit), then the
`S-` items. Order unchanged.


---

# Part IV — M-7: the sync directions had drifted (26 July 2026)

Reported: *"I synced invoices from cloud to local — the history shows the
payment, but the invoice is still Pending."* Confirmed, root-caused, fixed, and
the existing bad rows repaired. The reporter's instinct that *"many might be
present"* was correct — this was a class, not an instance.

## 21. M-7 · 🔴 Critical — post-apply invariants ran on PUSH only

`Invoice.paid_amount` and `Invoice.status` are a **projection** of the
append-only `invoice_payments` ledger. They must be re-derived whenever either
side of that relationship lands. The cloud did exactly that on every push. The
local pull worker did not.

The reason is structural, not a forgotten line: `_reconcile_invoice_paid_state`
was a **private function inside `routes/sync.py`**, which `services/sync_worker.py`
cannot import. The correction was only ever reachable from one of the two apply
paths, so it ran in one direction. Every invoice pulled cloud→local kept
whatever status was serialised on the cloud at snapshot time.

Batch ordering made it certain rather than intermittent: `invoice_payments` sits
in the pull worker's `_child_last` group, so an invoice is applied **before** its
payment rows exist. Reconciling at invoice time finds an empty ledger and
correctly does nothing — the correction has to fire when the *payment* lands.
Both hooks are required; neither alone closes it.

### The audit that found the class

Diffing what push does against what pull does:

| Safeguard | push | pull |
|---|---|---|
| `resolve_parent_fk_uids` | ✅ | ✅ |
| `_USER_FK_REPOINT_ENTITIES` | ✅ | ✅ |
| `sync_disabled_var` | ✅ | ✅ |
| **`_reconcile_invoice_paid_state`** | ✅ | ❌ **the reported bug** |
| **`_reconcile_parent_invoice_of_payment`** | ✅ | ❌ |
| `FINANCIAL_ENTITIES` conflict logging | ✅ | ❌ |
| `APPEND_ONLY_DELETE_BLOCKLIST` | ✅ | n/a (pull applies no deletes) |

### Why this was predictable

`database/sync_map.py` **already documents this exact failure mode** in its
header (R-7): the table→model map used to be copy-pasted into both sync modules,
and a table added to one but not the other silently stopped syncing in one
direction. That was fixed by extracting the map to a shared module. The *apply
logic* was never given the same treatment, so it drifted the same way, for the
same reason — with a worse symptom. A missing row is visible. Wrong money on
screen is not.

## 22. The fix

| Change | Where |
|---|---|
| New shared module: `run_post_apply` + the paid-state projection, with `derive_paid_state` extracted pure | `core/sync/apply_hooks.py` |
| Push path routes through the shared hook (main path **and** the integrity-dedupe path, which was also skipping it) | `routes/sync.py` |
| Pull path routes through the same hook — previously ran none of it | `services/sync_worker.py` |
| Old private names kept as thin re-exports so existing callers work; a comment forbids reintroducing a local copy | `routes/sync.py` |
| Boot-time repair for rows already written wrong | `database/migration.py::_repair_invoice_paid_state` |
| 30 tests, including the drift guard | `tests/test_sync_paid_state_parity.py` |

**The structural fix is the point.** A new invariant added to `apply_hooks` is
now enforced in both directions automatically. There is no longer a place to add
one to only half the system.

### The drift guard

Three tests fail if this class recurs:

- both sync modules must import `apply_hooks` and call `run_post_apply`
- **neither may re-implement the projection locally** — asserted by looking for an inline `func.sum(InvoicePayment.amount_paid)`, the signature of a local copy
- every entity in `PAID_STATE_ENTITIES` must actually be in `MODEL_MAP`

### Repairing existing data

The code fix only protects future syncs; rows already written stay wrong, and a
wrong status is not cosmetic — it drives receivables, the pending-dues list and
customer chasing. `_repair_invoice_paid_state` runs once on boot and re-derives
from the ledger. It only touches invoices that **have** payment rows (a legacy
paid invoice with no ledger rows has no evidence to overrule it, and clearing it
would invent an unpaid debt), only writes rows that actually disagree, and logs
every correction at WARNING with the invoice numbers. A silent repair of money
data is not a repair, it is a second mystery.

### Ordering detail worth keeping

The projection runs **before** the journal re-derivation inside `run_post_apply`.
`build_sale_lines` reads `paid_amount` to split the entry between Cash and
Accounts Receivable, so posting first would book a settled invoice against the
wrong side. Pinned by test.

## 23. Execution order — updated

| Stage | Work | Status |
|---|---|---|
| 0 | M-1 consent bypass · F-3 numbering | ✅ |
| 1 | M-2 journal + period-lock sync | ✅ |
| 1b | **M-7 push/pull invariant parity** | ✅ |
| **2** | **M-3 unique index** · **M-4 B2B order numbers** | next |
| 3 | M-6 end-to-end reconciliation test | |
| 4 | M-5 silent-swallow audit (37 `except: pass`) | |
| 5 | S-2 / S-3 / S-4 security items | |

**M-8 (new, open).** `FINANCIAL_ENTITIES` conflict logging is still push-only. A
financial row overwritten by an incoming *pull* is the same silent-lost-edit the
push path was hardened against, and it is currently unlogged. It belongs in
`apply_hooks` alongside the others — folded into stage 2.

## 24. Architectural rule added

12. **An invariant that must hold after a sync apply lives in `core/sync/apply_hooks.py`, never inside one of the two sync modules.** There are two apply paths and there will always be two; anything private to one of them is enforced in one direction only. This is the same lesson R-7 recorded for `MODEL_MAP`, relearned on money. (M-7)

---

# Part V — Stage 2 complete (26 July 2026)

Everything outstanding on the money model and the security list is now closed.

## 25. Closed in this pass

| # | Finding | Fix |
|---|---|---|
| **M-3** | `(business_id, invoice_id)` had no DB constraint | Partial unique index (`WHERE invoice_id IS NOT NULL`). Alembic `c8e1b4f7d203` + `_ensure_invoice_number_unique_index`. **Refuses to create over existing duplicates** — it lists them at ERROR instead. Renumbering an issued tax invoice is not a migration's decision: the number may be printed on a customer's copy and filed in a GST return. |
| **M-4** | B2B order numbers: unbounded random retry | `_next_order_number` off `DocumentSequence`, date-scoped series. Scoped to `SEQ.SYSTEM_SCOPE` because `order_number` is globally `unique=True` — a per-buyer counter would have every buyer minting `...-0001` on the same morning. |
| **M-5** | 37 silent-swallow handlers | Audited all 106 in `core/`+`services/`+`routes/`; 14 sit in money paths. Two were real; the rest are parse helpers, now documented as deliberate. |
| **M-6** | No end-to-end reconciliation test | `tests/test_money_reconciliation.py` — 10 invariants over a full trading day. |
| **M-8** | Financial conflict logging was push-only | Moved into `apply_hooks`; the pull path now flags overwrites too. |
| **S-2** | Unauthenticated discovery = credential harvesting | Only non-globally-routable addresses may register; entries capped. |
| **S-4** | Cross-backend token rule enforced by a comment | `CrossBackendTokenGuard.test.js`. |

### M-4 — why the old loop was going to fail as the product grew

`while True` over a 4-char suffix from a 32-char alphabet: 32⁴ ≈ 1.05M values,
but collisions follow the birthday bound, so at ~1,000 orders/day a collision is
already ~50% likely. No attempt cap, so a busy day degrades from "one extra
query" to "hangs". And check-then-insert is not atomic against a `unique=True`
column, so two concurrent orders could both see the number free and one would die
with a 500 *after* the caller believed the order was placed. All three are
properties of **guessing**; counting removes them.

### M-5 — the two that were real

Most of the 14 money-path swallows are honest parse helpers (`int()` on a
user-supplied reference, JSON blobs for presentation). Two were not:

- **`_negative_stock_blocked`** returned `False` on any exception. Fail-open is the right product call — a counter must not stop selling over a malformed settings blob — but it was *silent*, so a JSON parse error meant the owner's negative-stock guard was ignored on **every sale** while still appearing enabled in Settings. Behaviour unchanged; it now logs at ERROR.
- **`_parse_dt`** returned `None` silently, in two identical copies. The `None` is correct and load-bearing (callers read it as "cannot prove newer" and keep what they have, R-5) — but a row whose `updated_at` never parses would **stop syncing forever with no signal**. Now shared in `apply_hooks.parse_dt`, and a non-empty value that fails to parse is logged.

The remaining 92 are outside money paths and are left alone deliberately: a
blanket sweep would add noise without adding safety. The rule is what matters:
*a swallow around a cache or a display string is fine; a swallow around a ledger
write, a money projection or a safety toggle is a defect.*

### M-6 — the test that would have caught M-2 and M-7 on day one

A full trading day — cash sale, credit sale, part payment, later settlement,
return, expense — then asserts: every entry foots; the journal foots; the GL nets
to zero; **Cash & Bank == money actually received less expenses**; **Accounts
Receivable == outstanding invoice balances**; Sales == taxable value net of
returns; GST Payable == tax collected net of returns; stock == opening − sales +
returns; every invoice's paid state agrees with its ledger; the hash chain
verifies; every document has exactly one journal entry.

M-2 and M-7 both shipped because each subsystem was individually correct and
internally consistent. The defects existed only *between* them, where nothing
looked. This is the test that looks there.

### S-2 — the documented threat model was factually wrong

`routes/discovery.py` justified being unauthenticated with "the caller is always
the local backend itself (loopback or LAN, never an untrusted internet client)".
`main_groq.py` mounts the router unconditionally and the local backend registers
with the **cloud** every 30 minutes, so on the cloud deployment it is
internet-reachable. With BizID deliberately public and `GET /discover/{biz_id}`
returning entries **newest-first**:

```
attacker POSTs {biz_id: <victim's public BizID>, ip: <attacker host>}
  → cashier device calls GET /discover/<biz_id> BEFORE login
  → attacker's entry is probed first
  → the owner's credentials go to the attacker
```

Structurally identical to F-1: a public identifier treated as if it conferred
authority. Closed by refusing any address that is globally routable — an attacker
cannot receive traffic at an address unreachable from outside the victim's
network. Stated as `not addr.is_global` rather than a hand-rolled private-range
list, so new reserved allocations are covered without revisiting the predicate.

**Residual risk, stated plainly:** a device already on the same LAN can still
register a competing address. LAN discovery inherently trusts the LAN; closing
that needs the registrant to prove it holds the BizID, which a backend has no way
to do before login. The remote attack is what mattered and is closed.

## 26. Still open

| # | Item | Why it is not closed |
|---|---|---|
| **S-3** | No DB-level tenant guard on SQLite | RLS protects the cloud; local installs rely on application-level `business_id` filtering. Now that the B2B mirror puts a counterparty's rows in the local DB, the single-tenant assumption no longer holds. Needs a query-level audit of the mirror reads — real work, not a one-liner. |
| **N4** | Remaining DB-level financial invariants | e.g. a CHECK that `paid_amount <= total_amount`, FK enforcement on SQLite. |
| **F-7** | God components / monolithic `index.css` | Unchanged; frontend velocity issue, not correctness. |
| — | Business-as-first-class-entity off `users.id` | The long-standing data-model item from the baseline review. |

## 27. Architectural rules added

13. **A swallow is judged by what it protects, not by its shape.** `except: pass` around a cache write is fine; around a ledger write, a money projection or a safety toggle it is a defect. Fail-open is often correct — fail-open *and silent* never is. (M-5)
14. **Guessing does not scale; counting does.** Any identifier generated by "pick at random, check, retry" has a birthday bound, an unbounded loop and a check-then-insert race. Allocate from a sequence. (M-4)
15. **A security justification in a docstring is a claim, and claims about deployment topology must be checked against how the router is actually mounted.** (S-2)
16. **A rule enforced by a comment is not enforced.** Cross-backend token safety, sync-path parity and journal replication are all now asserted by tests that fail on regression. (S-4)

---

# Part VI — Test coverage of the money model, measured (26 July 2026)

The mandate was "**every function should have a unit test case, no silent
kills**". Previous parts fixed defects and added tests *for those defects*. This
part measures the whole money model instead of asserting it is fine.

## 28. The measurement

Method: AST-enumerate every function in the money modules (`core/billing`,
`core/accounting`, `core/order`, `core/purchase`, `core/shifts`, `core/stock`,
`core/sync`, `core/compliance`, the money API routes, both sync modules,
`sync_map`), then check whether each name appears anywhere in the test corpus.

**Name-reference is a crude proxy** and it is stated as such: it over-credits
(a name in a comment counts) and under-credits (an endpoint exercised over HTTP
is not "referenced"). It is a floor, not a score.

| | Before | After |
|---|---|---|
| All money functions | 75/229 · **32.8%** | 100/229 · **43.7%** |
| Pure (no-DB) subset | 31/96 · 32.3% | 56/96 · **58.3%** |

## 29. The finding that mattered

The uncovered set included **the five functions in `core/accounting/posting.py`
that decide which account every rupee lands in**:

```
build_sale_lines · build_credit_note_lines · build_purchase_lines
build_debit_note_lines · build_expense_lines
```

Pure, deterministic, trivially testable — and nothing tested them directly. A
sign error or a swapped account in any one misstates the trial balance, the P&L
and the party ledger simultaneously, while the POS keeps looking perfectly
normal. That is precisely the failure mode of M-2 and M-7: correct-looking
front end, wrong books.

`_chain_hash` was also untested — the function the entire tamper-evidence claim
rests on.

## 30. `tests/test_money_pure_functions.py`

~130 assertions over the deterministic money core. Highlights:

**The load-bearing property.** `test_every_builder_foots_for_every_shape` runs
all five builders across 72 combinations of total × GST rate × paid fraction and
asserts Σ debits == Σ credits every time. An unbalanced builder does not corrupt
the ledger — `post_entry` refuses to write it — which is *worse*: the money moves
and nothing is recorded at all.

**Tamper-evidence, properly.** Every hashed input is asserted to change the hash;
amounts are asserted to change it; line order is asserted to change it; and
float noise (`118.00000000000001`) is asserted **not** to, since a chain that
breaks on its own proves nothing.

**Accounting rules that are easy to get subtly wrong**, now pinned:

- a post-tax cash discount books to `Discount Allowed`; Sales and GST stay **gross** (booking it against Sales would understate revenue and misstate the GST filed)
- GST input credit on a purchase is a **debit**, not a credit
- overpayment must not produce a negative receivable
- an explicit `0.0` GST rate on a line is an **override**, not a missing value — exempt goods must not inherit the product's rate
- `_norm_mode` must never default an unrecognised payment method into the **cash** bucket, or the drawer shows a false shortfall

## 31. One assertion I got wrong

I asserted `amount_in_words(None) == ""`. It actually returns `"Zero Rupees
Only"`, because `_r2(None)` is `0.0` throughout this codebase. The test now
documents real behaviour rather than my assumption, with the reasoning attached:
it is defensible (the numeral on the bill derives from the same value, so words
and figure agree) but worth pinning, because "Zero Rupees Only" is an assertion
about the bill rather than a blank.

Recording this rather than quietly editing the test is the point. A test suite
whose expectations were bent to match whatever the code did is not evidence.

## 32. What is still uncovered, and why it is next

The remaining 129 unreferenced functions are mostly:

- **Report endpoints** (`core/api/reports.py`, 22) — exercised over HTTP in `test_journal.py` / `test_trial_balance.py`, so the true figure is better than 43.7%. They need direct assertions on the numbers each report emits, which is the natural home for the M-6 reconciliation invariants.
- **`core/shifts/service.py` (14)** — `compute_tally`, `close_shift`, `_movement_sums`. This is the cash drawer. It is the largest genuinely-untested money surface left and should be next.
- **`core/billing/print_payload.py` (13)** — customer-facing rendering; `amount_in_words` is now covered, the layout helpers are not.
- **`core/compliance/einvoice.py` (7)** — IRN payload construction. Wrong here means a rejected e-invoice, which fails loudly rather than silently, so it ranks below the shift tally.

## 33. Honest status against the mandate

| Requirement | Status |
|---|---|
| POS billing / settlement recorded with a clean backend record | **Yes** for the write paths; M-2 backfill still to run on existing data |
| No silent failures | Money-path swallows audited; the two real ones fixed (M-5). 92 non-money swallows deliberately untouched |
| Sync perfect, no deviations | M-2, M-7, M-8, M-9 closed; drift guard in place. **S-3 open** |
| Every function unit-tested | **43.7% measured, up from 32.8%.** Not "every". The highest-risk core is now covered; `core/shifts` is the next gap |
| Security cleared | S-2, S-4 closed; **S-3 open** — no DB-level tenant guard on local SQLite, and the B2B mirror now puts a counterparty's rows there |

The gap between "43.7%" and "every function" is real and I am not going to
describe it as done. The order it should close in is §32.

---

# Part VII — Stage 3–5: security list closed, invariants pushed into the DB, the cash drawer covered (26 July 2026)

This pass took the remaining open list — **S-3**, **N4**, and the coverage gap
§32 named — and worked it against the running code rather than against the
document. Everything below was executed, not reasoned about; where I could not
execute something I say so instead of estimating it.

It also found one new defect that no amount of reading would have surfaced,
because it only appears when the suite actually runs: **S-5**.

## 34. S-5 · 🔴 Critical (NEW) — the test suite made authenticated writes against the production cloud

Found by running `tests/test_connection_approval.py` and reading why it failed.
Every step below is measured:

| Step | Evidence |
|---|---|
| The suite runs on SQLite, so `b2b_proxy._is_local_backend()` is True and the middleware engages | `PRAGMA` dialect check in `routes/b2b_proxy.py` |
| `_get_cloud_token(business_id)` reads `backend/cloud_sync_tokens.json` — a real developer artefact, **not** test-scoped | file present, 285 bytes, holding one **276-character live bearer token** keyed to business id `7` |
| The approval fixtures create fresh businesses whose small integer ids **collide** with that map | test log: `[PLAN] login tier=free user=approval_third business=7` |
| `routes/b2b_proxy.py` had **no** test-environment guard | `grep -n "BIZASSIST_TESTING\|PYTEST" routes/b2b_proxy.py` → no matches |
| Result | the middleware forwarded `POST /connections/connections/1/approve` to `https://rakshit-dev-bizassist.hf.space` with a production token |

Two defects, and the second is the worse one:

1. **Safety.** A test run could mutate a real deployment's B2B data. This is the
   network-layer twin of the incident `database/db.py`'s fail-closed DB guard was
   written for — that guard fails closed on the `DATABASE_URL`, and nothing
   failed closed on the socket.
2. **Integrity.** The assertion *"an unrelated business cannot approve"* was
   being answered by **the production server's HTTP status**, not by the local
   authorisation code it claims to cover. It passed while the cloud was reachable
   and failed when it was not, and in neither case did it exercise the code under
   test. Reproduced deliberately: pointing `CLOUD_API_URL` at an unroutable
   address made the "security test" fail with `503`.

   *A security test whose verdict arrives over the network is not evidence.*

**Fix.** `_in_test_context()` + `_proxy_allowed()` in `routes/b2b_proxy.py`. The
proxy is inert whenever `BIZASSIST_TESTING` or `PYTEST_CURRENT_TEST` is set,
unless `BIZASSIST_ALLOW_TEST_CLOUD_PROXY=1` is passed explicitly. Fails **closed**
by default, so a future test entry point inherits the safe behaviour without
knowing the guard exists. `/api/b2b/status` was changed in the same edit: it
reported `proxied · writable` from token presence alone, which under the guard
would have been that endpoint's own documented failure mode — an invisible
degraded state described as healthy.

Pinned by `tests/test_b2b_proxy_test_isolation.py` (13 tests), including a drift
guard asserting the middleware still consults the check *in its early bail-out*,
before any token lookup.

**The generalisable lesson,** recorded as a rule below: the DB guard proved the
team already understood this failure mode. It was implemented for one resource.
Fail-closed is a property of every outbound resource a test can touch, not just
the database.

## 35. S-3 closed — tenant scope is enforced in SQL, and a scanner keeps it that way

S-3 was "no DB-level guard behind the tenant filter on SQLite". I ran an audit
rather than opening files at random: an AST scanner that reads owner columns from
**live SQLAlchemy mapper metadata** (so it can never drift from the schema) and
flags every materialising read on a table carrying one.

**Measured result: 326 tenant-table reads examined, 42 tenant-scoped models, 21
reads with no owner predicate in the chain.** Adjudicated individually:

| Verdict | Count | Notes |
|---|---|---|
| Intentionally cross-tenant | 14 | Admin console (4, each gated by `require_admin` on the first line — verified, not assumed), global uniqueness probes (2), redemption-by-secret (1), public invoice view (1), data-transfer importer (4), scheduled fan-out job (1), conditional barcode scope (1) |
| Scoped a line earlier, invisible to a syntactic check | 6 | Left as-is |
| **Genuinely unscoped** | **1** | `core/connection/service._load` |

`_load` fetched a `B2BConnection` **by primary key alone** and relied on all four
callers following up with `is_party`. All four did — so this was **not a live
exposure, and I am not going to inflate it into one.** It was a convention, and a
convention is one new call site away from a cross-tenant read. Two reasons that
matters more than it used to:

- On a local install there is **no RLS underneath**. Postgres policies protect the
  cloud; SQLite has nothing behind the application filter.
- The B2B mirror now writes a **counterparty's** rows into the local database on
  purpose, so "desktop installs are single-tenant anyway" — the assumption that
  made the gap tolerable — is retired.

**Fix.** `business_id` is now **required and keyword-only** on `_load` (no default:
a default is how a scope becomes optional, and an optional scope is no scope), and
the constraint is in the query as `OR(seller_business_id, buyer_business_id)`.
`update_connection_policy`, which had its own second copy of the fetch, routes
through it. A non-party now gets the *identical* error to a row that does not
exist — distinguishing them leaks the existence of other businesses' connections
to anyone who can count integers.

**The durable half.** An audit is true on the day it runs. The scanner is checked
in as `core/sync/tenant_scope.py` and gated by `tests/test_tenant_scope.py`, so a
new unscoped read **fails the build with a file and line number**. Intentional
cross-tenant reads live in an `ALLOWED` map with a written justification each, and
two further tests keep that list honest: one fails on a stale entry (it caught an
error of my own — I had allow-listed a `users` probe, but `users` is the tenant
*root* and carries no owner column, so it was never scanned), and one fails on an
entry with no substantive reason. The scanner is also tested against a *planted*
unscoped read, because a gate that cannot fail is not a gate.

Stated plainly: the check is syntactic and deliberately generous, so a clean
result is a **floor** on isolation, not a proof of it. What it guarantees is that
the set of unscoped tenant reads cannot grow without someone writing down why.

## 36. N4 closed — money invariants are now enforced by the database

Two independent halves.

### 36.1 The invariants

Declared **once** in `core/accounting/db_invariants.py` as boolean SQL that must
hold, with the DDL generated per dialect — `CHECK` constraints on Postgres,
`BEFORE INSERT/UPDATE … RAISE(ABORT)` triggers on SQLite, because SQLite cannot
add a `CHECK` to an existing table without rebuilding it and rebuilding live money
tables to add a guard is the worse trade. Writing the rule twice, once per
dialect, is exactly the drift rule 12 exists for.

| Invariant | Why it is not cosmetic |
|---|---|
| `invoice_payments.amount_paid > 0` | A refund is a credit note. A negative row silently reduces `paid_amount`, flips a settled invoice back to Pending and puts a paid customer back on the chasing list. |
| `journal_lines`: never both debit **and** credit | **The error that balances and is still wrong.** `post_entry`'s footing guard passes it; the trial balance and the P&L then disagree because each reads one column. |
| `journal_lines`: no negative amounts | Double entry expresses direction with the *column*. Allowing signs gives every amount two representations and weakens the hash chain's tamper-evidence claim. |
| `invoices.paid_amount >= 0` | It is a projection of the ledger; a negative means something other than the projection wrote it — the M-7 class. |
| `document_sequences.last_number >= 0` | The stored counter that replaced `COUNT` numbering is only safe because it never moves backwards. |
| `register_shifts.opening_cash >= 0` | A negative float understates `expected_cash` for a whole shift, so the cashier shows a surplus exactly equal to the error. |

Every one was checked against the real databases in this repo before being added:
**zero existing violations**. Installation **refuses over existing violations** and
logs the offending row ids at ERROR — same discipline as the M-3 index, for the
same reason: rewriting historical money data is not a migration's decision.

`ensure_invariants` **returns a report** rather than logging and forgetting, so the
boot path and the tests can both assert on it; a migration that reports nothing is
indistinguishable from one that did nothing. Wired in at
`database/migration.py::_ensure_money_invariants`, after the column backfills and
never raising — a guard that cannot install must not stop an owner billing.

`tests/test_db_invariants.py` (20 tests) proves enforcement **behaviourally**, by
attempting violating writes in raw SQL. Emitting DDL is not evidence that anything
is enforced, and raw SQL is the point: the claim is that a path *bypassing* the
command layer cannot write a row the books cannot represent, so the test bypasses
it too. It also asserts a legal write still succeeds — a trigger with an inverted
condition would otherwise pass every "is it refused" test in the file.

**One recommendation from the baseline review is deliberately NOT implemented.**
It asked for `CHECK (paid_amount <= total_amount)`. That constraint is **wrong for
this product**: `apply_hooks.reconcile_invoice_paid_state` sets `paid_amount` to
the *uncapped* sum of the payment ledger, because overpayment is a real event
whose excess is booked to Customer Advances. Adding it would reject a legitimate
counter receipt. There is a test asserting its absence, with the reason attached,
so nobody re-adds it from the older document.

### 36.2 SQLite was not enforcing foreign keys at all

Verified, not assumed: a fresh connection reported **`PRAGMA foreign_keys = 0`**.
SQLite ships with enforcement OFF and the setting is **per connection**, so every
`ForeignKey(...)` and every `ondelete="CASCADE"` in `database/models.py` and
`core/models.py` was *declared and never enforced on any local install* — while
the Postgres cloud enforced them. The two halves of a hybrid install disagreed
about what a legal row is: a local delete orphaned children instead of cascading,
and a child could be written pointing at a nonexistent parent, then push to the
cloud and be rejected there forever.

Turned on via a DBAPI-level `connect` listener, scoped to SQLite. This is the
concrete instance of the "dual-dialect drift" §6.7 warned about, landing in the
money layer — and it is not hypothetical: the live database **already holds 18
orphaned rows** created by that gap. See §40.

**The evidence that made this safe to ship**, because a behaviour change here
could plausibly have broken user-facing deletes:

- There is **no invoice delete route** — invoices are append-only from the app's
  perspective (`grep '@router.delete'` across `routes/` and `core/api/`).
- The one bulk-delete path that matters, `admin_service.purge_business_data`
  (behind admin wipe and local reclaim), is **already dependency-ordered** and
  documents itself as such. The application was doing this correctly all along.

**What did break was the test fixtures**, and that is the finding. A static scan
(`fk_teardown_scan`) found **30 test files with at least one parent-before-child
deletion**; most are latent (the child table happens to be empty). Empirically, 6
files failed and are fixed: `test_import.py`, `test_phase3.py`, `test_phase4.py`,
`test_purchase_commit.py`, `test_pending_invoices.py` and three more via a
delete-order correction, plus `test_sync_paid_state_parity.py` — see below. The
remaining 24 are structurally at risk but currently pass; the scan is the artefact
that makes them findable, and consolidating these teardowns onto the production
purge is listed as follow-up rather than claimed as done.

### 36.3 One test was asserting a state the cloud has always rejected

`test_payment_arriving_before_its_invoice_is_reconciled_when_the_invoice_lands`
**persisted a payment row pointing at `invoice_id = 999_999`**. That only ever
worked because SQLite ignored foreign keys. Postgres has always rejected it — so
the test was pinning behaviour that is impossible on the deployment that holds the
real books.

I checked whether forbidding it loses anything before changing it, because if the
pull worker wrote orphans deliberately, enforcing FKs would have **dropped a
payment** — which would have been far worse than the bug I was fixing. It does
not: `resolve_parent_fk_uids` **defers** a record whose parent is not local yet so
it re-applies on a later pull, explicitly to avoid "a stale source-DB integer id
(wrong-row / orphan)". Writing the orphan was the outcome the worker is built to
prevent.

The test is now three tests: the database refuses a persisted orphan; the
child-before-parent reconciliation is exercised **the way the batch actually
orders it** (`invoice_payments` is in the pull worker's `_child_last` group, so the
invoice lands first and the *payment's* hook is the one that must fire); and the
degrade-don't-crash property is kept against a transient object, which is how the
hook really encounters an unresolvable parent.

## 37. The cash drawer is covered — `core/shifts/service.py`

§32 named this as "the largest genuinely-untested money surface left". Measured
before touching it: **11 of its 13 functions had no reference anywhere in the test
corpus** — `get_open_shift`, `require_open_shift`, `suggested_opening_cash`,
`open_shift`, `record_cash_movement`, `_movement_sums`, `compute_tally`,
`close_shift`, `movement_out`, `list_movements`, `shift_out`. `tests/test_shifts.py`
exercises the lifecycle over HTTP — valuable and orthogonal — but it asserts on
route payloads and never names the functions doing the arithmetic.

`tests/test_shift_service_unit.py` — **62 tests, all passing**, against the service
rather than the routes, because a route test cannot distinguish "the tally is
right" from "the route returned the number the test computed the same wrong way".

**Now: 13 of 14 referenced.** The one miss is a nested closure that is not
independently callable.

The load-bearing assertions:

- **Audit-only movements must never enter the tally.** `closing_removal` is
  recorded *after* the count snapshot; counting it would subtract the bank deposit
  a second time and report **every well-run shift as short by exactly the amount
  deposited**.
- **Reconciliation happens on the full count**, with the removal recorded
  afterwards — pinned so the order of operations in `close_shift` cannot be
  "simplified".
- **Discrepancy sign is `actual − expected`.** Backwards, and every cashier with a
  surplus is accused.
- **Float carry-forward is `closing_float`, not the counted cash** — the
  distinction the whole 3b design turns on.
- **First-ever shift records `opening_expected = NULL`, not 0.** "Unknown" and "the
  drawer was empty" are different claims, and filing a variance against a guess
  invents a discrepancy.

### 37.1 A real defect the tests found

`_norm_mode` normalised `None` and `""` to cash but **`"   "` to `other`** —
`(mode or "cash").strip().lower()` let a whitespace-only mode survive the `or`,
strip to empty, match nothing and fall through. Same fact, two answers.

It erred toward a false **surplus** rather than a false shortfall, which is
exactly why nobody had noticed: a drawer with more than expected reads as a
rounding oddity, not as an alarm. The strip now happens before the default. Both
rules are pinned separately, because they pull in opposite directions on purpose —
*absent* means cash; *unrecognised* must mean `other` and never cash, or the
cashier is short for money that never entered the drawer.

## 38. Coverage, re-measured

Same method as §28, and the same caveat: name-reference over-credits (a name in a
comment counts) and under-credits (an endpoint exercised over HTTP is not
"referenced"). It is a floor, not a score.

| | §28 | Now |
|---|---|---|
| All money functions | 100/229 · 43.7% | **128/275 · 46.5%** |
| Like-for-like (excl. the two modules added this pass) | — | **121/255 · 47.5%** |
| Pure (no-DB) subset | 56/96 · 58.3% | **68/115 · 59.1%** |
| `core/shifts/service.py` | 0/14 directly referenced | **13/14** |

**The denominators are not identical (229 → 255) and I am not going to present
them as if they were.** The module set I enumerated is slightly wider than §28's,
and the code itself grew. The percentage move is therefore soft; the `core/shifts`
row is the hard number, and it is the one §32 asked for.

Largest remaining gaps, measured:

| Uncovered / total | Module |
|---|---|
| 22 / 30 | `core/api/reports.py` |
| 13 / 14 | `core/api/parties.py` |
| 12 / 14 | `core/billing/print_payload.py` |
| 12 / 14 | `core/api/sales.py` |
| 10 / 14 | `routes/sync.py` |
| 9 / 12 | `core/api/payments.py` |
| 7 / 7 | `core/api/orders.py` |
| 5 / 11 | `core/compliance/einvoice.py` |

## 39. M-2 backfill — measured on the real database, NOT yet applied

**Correction worth recording, because it nearly became a false clean bill of
health.** My first pass queried `bizassist.db` at the repo ROOT — 4 users, 0
invoices — and I was about to report "nothing to backfill". The database the app
actually uses is **`backend/bizassist.db`** (`.env` sets
`DATABASE_URL=sqlite:///./bizassist.db`, resolved relative to `backend/`). The
root file is a stale 1.3 MB leftover. Two files, one name, and the empty one is
the one that answers first.

The real database, 10.4 MB:

| | count |
|---|---|
| users | 19 |
| invoices | **525** |
| invoice_payments | 42 |
| journal_entries | 87 |
| journal_lines | 241 |
| register_shifts | 6 |

**Sales with no journal entry: 447.** Split by whether there is anything to post:

| | count |
|---|---|
| `total_amount > 0` — **real, must be posted** | **27** |
| `total_amount = 0` — legacy CSV imports, correctly skipped | 420 |

Per business, with the money involved:

| Business | invoices | missing a journal entry | value with no books |
|---|---|---|---|
| 4 | 34 | **24** | **₹22,129** |
| 11 | 2 | **2** | **₹1,728** |
| 8 | 3 | **1** | **₹39** |
| 2 | 420 | 0 | — (zero-value imports) |
| 6 | 38 | 0 | — already backfilled |
| 7 | 28 | 0 | — already backfilled |

`scripts/backfill_journals.py` (dry run) agrees exactly: **27 documents**, biz 4 /
8 / 11. Businesses 6 and 7 — the two the script's own docstring names as the
original M-2 casualties — are now clean, so an earlier run did land.

**A gap I measured and then disproved.** A raw query said 35 of 42 receipts had no
`payment` journal entry, which looked like a second M-2 instance. It is not: all
35 carry `note LIKE 'Initial payment%'`, and an initial receipt is booked *inside
the sale entry* by `build_sale_lines`' Cash/AR split — a separate `payment` entry
would double-count it. Checked before reporting rather than after.

### Not applied, and why — stated plainly

`--apply` **failed**: `sqlite3.OperationalError: disk I/O error`. The database
lives on a mounted filesystem this environment can read but not write. The
transaction never committed, and I verified rather than assumed the consequences:

- a `bizassist.db-journal` hot rollback journal was left behind;
- copying the pair to local disk and opening with write access made SQLite roll it
  back automatically, and the result is `PRAGMA integrity_check: ok` with
  **525 / 87 / 241** — byte-identical counts to the backup taken before the
  attempt. **No data was changed or lost**, and the journal is consumed the next
  time the app opens the file with write access.

**This is the one item on the mandate that still needs a human to run a command.**
On the machine that owns the database:

```
cd backend
python scripts/backfill_journals.py              # expect: 27 documents, biz 4/8/11
python scripts/backfill_journals.py --apply
python scripts/audit_money_integrity.py          # expect: check B clean
```

And separately against the **cloud** Postgres, which I have no access to at all,
so every claim in this document is verified on SQLite only.

## 40. 🟠 High (NEW) — the real database already holds 18 foreign-key violations

`PRAGMA foreign_key_check` on the recovered copy of `backend/bizassist.db`:

| Orphaned rows | Missing parent | Count |
|---|---|---|
| `product_barcodes` | `products` | 5 |
| `invoice_line_items` | `products` | 4 |
| `invoice_line_items` | `invoices` | 4 |
| `stock_ledger` | `products` | 3 |
| `invoices` | `customers` | 1 |
| `register_shifts` | `users` | 1 |
| **total** | | **18** |

This is §36.2 stated as damage rather than as risk. These rows exist *because*
`PRAGMA foreign_keys` was off: something deleted products, invoices, a customer
and a user, and the children were silently left pointing at nothing. Two of them
are squarely in the money model — **4 invoice line items belong to invoices 455
and 806, which do not exist**, and 3 stock-ledger movements reference deleted
products, so the append-only inventory truth has entries for goods the catalog no
longer knows about.

**Consequence of the N4 change, and it needs saying because it is a real edge:**
turning enforcement on does **not** reject these rows at rest — SQLite checks on
write, not on read. They will sit there quietly as before. But **any `UPDATE` that
touches one now fails**, where previously it succeeded. That is the correct
behaviour and it is also a behaviour change on live data, so the rows should be
cleaned rather than left to surface as an error in front of an owner.

Recommended, in this order: run `PRAGMA foreign_key_check` as part of
`audit_money_integrity.py` so this is measured on every audit rather than
discovered; then quarantine the 18 rows (the `scripts/` directory already has the
right precedent in `quarantine_misattached_payments.py` and `reconcile_orphans.py`)
rather than deleting them, because 4 of them are invoice line items and a line
item is evidence of a sale even when its parent has gone missing.

Neither is done. It was found in the last hour of this pass and it is data
surgery on real books, which is not a thing to do quickly.

## 41. What was run

Chunked serial runs (the environment could not hold one full session):

| Suite | Result |
|---|---|
| Money core — reconciliation, pure functions, sequence, accounting, hash chain, trial balance | **245 passed** |
| Journal repost on sync · paid-state parity · connection approval | **69 passed** (after the orphan-payment correction) |
| Shifts (HTTP) + shift service unit + money reconciliation + sync shift hardening | **95 passed** |
| Tenant scope · DB invariants · proxy isolation · shift unit | **104 passed** |
| Hash chain · pure functions · party ledger · period lock · cash discount · stock ledger · financial conflicts · idempotency | **241 passed** |
| Sync migration fixes · pull · shift+push hardening · activity · sales API · review1 hardening · phase4 sync · sync profile · realtime | **54 passed** |
| All 30 structurally FK-at-risk files | **all passing** after 6 fixture fixes |

**Not run, and I am saying so rather than implying a clean sweep:** roughly 40 of
the 126 test files — mostly AI routing, LLM provider and admin-console modules —
were not re-executed in this pass. They are outside the FK-ordering blast radius
(measured, via the teardown scan) and outside the invariant triggers' reach
(no test writes a zero/negative payment or a two-sided journal line — grepped).
`test_rls_postgres.py` needs Docker and could not run at all, so the **Postgres
side of every claim here is untested in this environment**.

The three `test_shadow_routing.py` failures visible in `test_results.json` at the
start of this pass are unrelated to the money model (a signup 500 in an
AI-routing module) and I did not chase them.

## 42. Honest status against the mandate

| Requirement | Status |
|---|---|
| POS billing / settlement recorded with a clean backend record | **Yes** for the write paths, and now enforced *below* them: FK integrity plus six money invariants that hold against paths bypassing the command layer |
| No silent failures | Money-path swallows audited (M-5); the drawer's silent `_norm_mode` inconsistency found and fixed; the invariant installer reports rather than skipping quietly |
| Sync perfect, no deviations | M-2, M-7, M-8 closed with drift guards. **A real local↔cloud deviation closed this pass**: SQLite was not enforcing foreign keys, so the two dialects disagreed about legal rows. **S-3 closed.** |
| Every function unit-tested | **46.5%, up from 43.7%** — and the specific gap §32 named is closed (`core/shifts` 0/14 → 13/14). Still **not "every"**, and the largest remaining gaps are listed in §38 with counts. |
| Security cleared | **S-3 closed. S-5 found and closed.** S-2, S-4 already closed. Nothing on the security list is open — but "cleared" is stronger than I can support: no penetration test has been run, and the Postgres/RLS half is unverified in this environment. |

The two things I would not let anyone describe as finished: coverage is **under
half**, and every claim in this document was verified against **SQLite with empty
transaction tables**. The cloud is where the money actually is.

## 43. Addendum — what the first FULL serial run found (and a correction)

Part VII above was verified in **chunked** runs, because this environment could
not hold a 1,450-test session. A full serial run on the owner's machine
(`run_tests.bat fast`, **1432 passed, 3 failed, 12 errors**) found four things the
chunks structurally could not. Recorded here with the correction to my own claim,
because that claim is the more useful lesson.

### 43.1 The correction: "the app's own delete paths are already correct" was HALF right

I checked `admin_service.purge_business_data`, found it properly
dependency-ordered, and concluded the application was safe. It is — but I checked
one purge path and there are two.

**`admin_service.wipe_all_data` was six unordered `delete()` calls**, sitting
directly above the function whose docstring says it is "the single source of truth
for erasing a business's rows **so callers can't drift**". This was the caller
that drifted, and `POST /admin/wipe-all-data` **returned 500 and wiped nothing**
once foreign keys were enforced.

It had been broken in a worse way before that, silently:

- deleting `invoices` without `invoice_line_items` / `invoice_payments` /
  `payments` left orphaned children — invisible while `PRAGMA foreign_keys` was
  OFF, which is how the 18 orphans in §40 accumulated;
- `journal_entries` links to its source by `source_id`, which is **not** a foreign
  key, so no error was ever possible — entries simply outlived their invoices.
  **That is M-2 in reverse: books describing sales that no longer exist**, with
  nothing anywhere reporting it.

The fix is not "add the missing tables to the list", which just creates two lists
to keep in step. `wipe_all_data` now **delegates to `purge_business_data`** per
business, so there is genuinely one purge implementation and this function only
decides which businesses to run it for.

**The lesson, stated against myself:** I verified the delete paths by reading the
one with the reassuring docstring. The correct check was mechanical —
`grep '@router.delete'` gave me the routes, and I should have followed *every*
service function behind them rather than stopping at the first one that looked
right. A single correct implementation is not evidence that its neighbours call
it.

### 43.2 Global unfiltered deletes across a shared database

`test_import.py`, `test_import_preview_contacts.py` and `test_rag.py` issue
**unfiltered** deletes — `db.query(Product).delete()`, `db.query(Customer).delete()`,
even `db.query(User).delete()`. The whole suite shares one SQLite file, so those
collide with rows from *unrelated* modules: a product still referenced by
`test_purchases`' line items, a customer by `test_billing`'s invoices, a user by
`test_shifts`' register shifts.

Which means the correct delete order for those fixtures is a property of the
**schema**, not of the module — so it is no longer written down. `tests/_fk_cleanup.py`
derives it from `Base.metadata.sorted_tables` (SQLAlchemy sorts parents before
children; reversed, that is a safe deletion order) and updates itself when a model
gains a foreign key.

**Why the chunks missed it, which is the point:** in a chunk these files pass,
because the modules whose rows they collide with were not present. *Partial runs
cannot observe cross-module interaction.* Worth stating rather than rediscovering.

### 43.3 `drop_all` on the shared database

`test_phase4._ensure_schema` called `Base.metadata.drop_all()` and `test_rag`'s
teardown did the same. On a shared file that destroys the **seeded accounts**
(`admin`, `pharmacy`, …) created by the session fixture, so every module running
afterwards fails to log in with a **401 that has nothing to do with the test that
caused it**. Reproduced by bisection: `test_backend` passes alone, fails after
`test_phase4`. Both now clear rows instead of dropping tables.

Pre-existing and order-dependent — it was luck that the alphabetical order mostly
hid it.

**And I reproduced the same mistake once while fixing it,** which is worth
recording. My first replacement for `test_rag`'s `drop_all` was a wipe with
`keep_users=False` — less destructive than dropping the schema, still destructive
enough to leave the next module with no accounts (`401`, `KeyError('token')`). The
fixture never needed the other businesses gone; it only needed its own to exist.
Both its setup and teardown now keep accounts, and the `id=10` business is created
idempotently. *"Clean slate" almost always means "clean slate for me", and on a
shared database those are different requests.*

### 43.4 `database is locked` → signup returns 500

Three failures were `sqlite3.OperationalError: database is locked` on
`db.commit()` inside signup, surfacing as `{"detail":"Internal server signup
error"}`. **This is a production failure mode, not a test artefact:** an owner
cannot create their account because a background thread happened to be mid-write.

Measured cause: `create_engine` passed no `timeout`, and no busy handler was
installed, so a writer that could not take the lock raised **immediately**. This
backend has several concurrent writers on one SQLite file — the request thread,
the sync worker, the scheduler, immediate-sync's force push — so lock contention
is normal operation, not an exceptional condition.

Fixed with `connect_args={"timeout": 30.0}` plus `PRAGMA busy_timeout=30000`
alongside the FK pragma (verified live: `foreign_keys = 1`, `busy_timeout = 30000`).

**`PRAGMA journal_mode=WAL` was considered and deliberately NOT enabled**, and the
reason is recorded in the code: WAL would reduce contention further, but it turns
the database into three files, and this product's backup/restore and local→cloud
transfer paths copy the `.db`. A copy taken without its `-wal` is a copy **missing
the most recent committed transactions, silently** — which is precisely the class
of defect this whole audit exists to remove. WAL is a reasonable next step *only*
together with an audit of every path that copies the database file.

**Honest note:** these three failures are the same symptom as the three
`test_shadow_routing` signup-500s present in `test_results.json` *before* this
pass began, so the fault is pre-existing. I cannot fully rule out that enforcing
foreign keys — which adds parent lookups inside a write transaction — nudged the
timing onto different modules. The busy handler is the correct fix either way, but
"pre-existing" is a claim about the cause, not a claim that I proved it.

### 43.5 Also added

`PRAGMA foreign_key_check` is now check **G** in
`scripts/audit_money_integrity.py`. The 18 orphans in §40 were found only because
someone ran the pragma by hand; on the audit it is measured every time. Verified
against the recovered database: reports all 18 in 6 groups, total issues 27 → 33.

## 44. M-2 closed on real data · FK orphans resolved

### 44.1 The backfill ran

On the owner's machine, after a green full suite (`1432 passed` before this pass's
fixture fixes; **backend PASS / frontend PASS** after):

```
python scripts\backfill_journals.py --apply
  business 4: 24 invoices · business 8: 1 · business 11: 2
  posted 27 entry(ies)
  chain verification:
    business 4: ok (34 entries) · business 8: ok (4) · business 11: ok (3)
```

`journal_entries` 87 → **114**. `audit_money_integrity.py` then reported **A–F all
clean**, including **B. Documents with no journal entry (M-2) — 0**, with the 420
zero-value CSV imports correctly excluded and *said to be excluded* rather than
quietly dropped from the denominator.

**M-2 is now closed on this database, not just in the code.** The remaining
unverified surface is the cloud Postgres, which is still untouched by every claim
in this document.

### 44.2 The 18 orphans — one rule per group, not one rule

`scripts/quarantine_fk_orphans.py`. The tempting shortcut — "delete every row that
fails the FK check" — would have destroyed money evidence, so the disposition
depends on whether the dangling column can be severed and on what the row means.

| Group | Rows | Action | Why |
|---|---|---|---|
| `invoice_line_items` → missing **invoice** | 4 | export + delete | `invoice_id` NOT NULL; unreachable by every query (line items are read only through their invoice). **₹904.93.** Parent deliberately NOT guessed |
| `product_barcodes` → missing product | 5 | export + delete | NOT NULL; a barcode is only a lookup key for a product that is gone |
| `invoice_line_items` → missing product | 4 | **set NULL** | Nullable, and the row carries its own name/qty/`line_total`. 3 belong to invoices 456/457 — **live, Paid invoices**; deleting them would silently alter a settled tax invoice |
| `stock_ledger` → missing product | 3 | **set NULL** | Append-only: movement type, quantity and reference untouched, only the pointer cleared |
| `invoices` → missing customer | 1 | **set NULL** | Nullable, customer NAME stored on the invoice. Exactly what `purge_business_data` already does |
| `register_shifts` → missing operator | 1 | **re-point to `business_id`** | NOT NULL. Same remedy `sync_map._USER_FK_REPOINT_ENTITIES` already applies |

**The shift was more than an FK problem.** Shift 4 (biz 7) is **OPEN with ₹8,113 of
opening float** and its operator, user 9, no longer exists. `get_open_shift` looks
up `(business_id, user_id)` and user 9 cannot log in, so **nobody could ever close
it** and that float sat outside every tally permanently. Re-pointing at the owner
makes it closable. Found while fixing a constraint violation, which is the argument
for enforcing constraints.

**Ordering is load-bearing:** line item 68 is orphaned *both* ways. Group 1 deletes
it, so the product-severing group runs afterwards and touches only survivors — 17
rows changed, not 18. That asymmetry is the ordering working, not a miscount.

### 44.3 Verified on a copy before recommending it

Run against a copy of the real database, with a full money diff:

| | before | after |
|---|---|---|
| invoices · total value | 525 · ₹290,022.25 | 525 · **₹290,022.25** |
| paid total · payments · sum | ₹45,729 · 42 · ₹21,670 | **identical** |
| journal entries · Dr · Cr | 114 · ₹294,392 · ₹294,392 | **identical, still foots** |
| stock rows · net qty | 236 · 8,484 | **identical** |
| invoice_line_items | 257 | **253** (the 4 unreachable orphans) |
| line items on invoices 456/457 | 3 | **3** |
| `foreign_key_check` · `integrity_check` | 18 · — | **0 · ok** |

Not one money figure moves. Every affected row is written to a timestamped JSON
export **before** anything is modified, and nothing is written without `--apply`.

## 45. M-11 · 🔴 Critical (NEW) — an invisible open shift rang ₹2,485 that reached no tally

Found by acting on §44.2 and then **checking the result instead of trusting it.**
Re-pointing the orphaned shift at its owner made business 7 show **two OPEN
shifts**. My first read was that the repair had caused it. It had not — it made a
pre-existing defect visible, and the defect is the most serious money finding of
this whole review after M-2.

### The sequence, from the data

```
shift 2  user=7  CLOSED  float 0        07 Jul 16:31 -> 08 Jul 18:24
shift 3  user=7  CLOSED  float 8113     08 Jul 18:26 -> 10 Jul 22:36
shift 4  user=9  OPEN    float 8113     08 Jul 18:30 -> never closed
shift 6  user=7  OPEN    float 8113     10 Jul 22:37 -> (current)
```

**Shift 4 opened four minutes into shift 3 and was accepted.**

`core/shifts/service.py` opens with "ONE OPEN shift per user at a time", and
`open_shift` enforces it by calling `get_open_shift` first. Both are keyed on
`(business_id, user_id)` — and shift 4 carried `user_id = 9`, a user that does not
exist in this database. So the check was asking *"does operator 9 have an open
shift?"*, the answer was no, and the drawer opened alongside one that was already
open.

Where the wrong `user_id` came from is not a mystery: `register_shifts` is listed
in `sync_map._USER_FK_REPOINT_ENTITIES` **precisely because** a shift arriving from
another database carries that database's integer user id. Shift 4 predates that
re-point.

### What it cost

Three cash sales were rung against shift 4 on 9 July:

| Invoice | Amount | Receipt |
|---|---|---|
| `LCL-C1-0001` | ₹190 | cash |
| `LCL-C1-0002` | ₹1,471 | cash |
| `LCL-C1-0003` | ₹824 | cash |
| | **₹2,485** | |

The invoices are correct. The receipts are correct. The journal is correct. But
`get_open_shift` looks up the logged-in operator, so **no one could see this shift
and no one could ever close it** — `compute_tally` was never run on it, and its
₹2,485 never appeared in any drawer reconciliation. An owner counting the till at
shift 3's close on 10 July would have been **₹2,485 over, with no explanation
available anywhere in the product.**

**This is the M-2 / M-7 shape for the third time:** every subsystem individually
correct and internally consistent, the defect living *between* them in the
reconciliation layer, and nothing looking broken. It is also architecture rule 11
again — the one-open-shift rule was enforced only in application code, keyed on a
column that sync can populate wrongly.

### Closed

| Change | Where |
|---|---|
| Partial unique index `(business_id, user_id) WHERE status='OPEN'` — makes the overlap impossible regardless of what any caller believes about `user_id` | `database/migration.py::_ensure_single_open_shift_index` |
| **Refuses to install over existing overlaps**, reporting them at ERROR | same |
| Audit check **H. Overlapping open shifts** | `scripts/audit_money_integrity.py` |
| The quarantine script now reports a revealed overlap loudly, with each shift's receipts | `scripts/quarantine_fk_orphans.py` |
| 4 tests: second open shift refused · closed shift does not block a new one (the index is PARTIAL on purpose, or an operator could work exactly one shift ever) · two operators may each hold one (multi-counter is the flagship case) · the migration refuses over existing overlaps and installs once resolved | `tests/test_db_invariants.py` |

Verified end to end on a copy: with two open shifts the index **refuses** and logs;
after closing the stale one it **installs**; a third insert is then rejected with
`UNIQUE constraint failed`.

### Deliberately NOT closed automatically

**Shift 4 is still open and must be closed by a human.** Closing a shift writes
`closing_cash_actual`, which is a *counted* figure — somebody looked in the drawer.
A script inventing that number would fabricate a cash count that never happened,
which is a worse defect than the one being fixed and exactly what §22 warned
against ("a silent repair of money data is not a repair, it is a second mystery").

The expected figure is computable — `compute_tally` derives it from the payment
ledger — so closing it from the register screen will show the ₹2,485 and let the
owner record what was actually counted.

### One more thing this surfaced

The repair-script exports (`fk_orphans_export_*.json`,
`quarantined_payments_*.json`) contain **real customer names, invoice numbers and
line items** and were **not gitignored**. Two were already sitting in `backend/`.
Now ignored. `cloud_sync_tokens.json` was already covered; these were not, because
each new script invented its own filename.

## 46. Silent-failure audit of THIS pass's own code

The mandate is "nothing can be silently killed". That has to apply to the code
written to enforce it, so every `except` added in Parts VII–VIII was re-read
against rule 13 (*a swallow is judged by what it protects*). **Three were wrong,
and one was serious.**

| Where | What it did | Verdict |
|---|---|---|
| `tenant_scope.scan` / `unused_allowances` | `except (SyntaxError, UnicodeDecodeError): continue` | 🔴 **A hole in a security gate, reported as green.** A file the analyser could not parse got a **silent free pass on tenant scoping** — the S-3 check would pass while leaving that file unexamined. Unparseable files are now collected, logged at ERROR, returned as part of the result, and **fail the gate**. Pinned by two tests, one of which plants a deliberately broken file. |
| `db_invariants._columns` | `except Exception: return set()` | 🟠 Made an **introspection failure indistinguishable from "the table lacks these columns"**, so a guard that broke was filed as `skipped_missing_table` — the operator would read "table not present" for what was actually an error. Now propagates; the caller records it under `errors` with the real message. |
| `db_invariants.violation_sample` | `except Exception: return []` | 🟡 Acceptable in kind — it only decorates a message whose finding was already established by `find_violations` — but it was **silent**. Now logs at WARNING, with the reasoning written down. |
| `ensure_invariants` rollback | `except Exception: pass` | 🟡 Cleanup inside an already-reported error path. Kept (fail-open is right here) but no longer silent: logs at WARNING, per rule 13's "fail-open *and silent* never is". |

Recording this rather than quietly patching it is the point. The first one is the
same defect as F-1, S-2 and M-11 in a different costume: **a check that cannot see
something reporting that there is nothing to see.**

## 47. What now prevents recurrence — the enforcement inventory

Every defect in this review was found by a human reading code. The purpose of this
pass was to convert as much of that as possible into something that fails by
itself. Current state, by mechanism:

### Enforced by the DATABASE (cannot be bypassed by any code path)

| Guard | Prevents |
|---|---|
| Partial unique index on `(business_id, invoice_id)` | duplicate invoice numbers (M-3) |
| Partial unique index on `(business_id, user_id) WHERE status='OPEN'` | overlapping drawers (M-11) |
| 6 CHECK constraints / triggers | zero-or-negative receipts · two-sided journal lines · negative journal amounts · negative `paid_amount` · negative sequence counter · negative opening float (N4) |
| `PRAGMA foreign_keys=ON` on SQLite | orphaned children — the mechanism that produced the 18 real orphans (N4) |
| `PRAGMA busy_timeout=30000` | a concurrent writer turning into a signup 500 |

All installed by a boot step that **refuses over existing violations and reports
them at ERROR** rather than "fixing" money data.

### Enforced by TESTS that fail the build

| Guard | Prevents |
|---|---|
| `test_tenant_scope.py` | a new unscoped read on any of 42 tenant tables — and now, a file the scanner cannot parse |
| `test_db_invariants.py` | an invariant that is declared but not enforced, or enforced but untested; a `paid_amount <= total_amount` constraint being re-added from the older review |
| `test_b2b_proxy_test_isolation.py` | the suite reaching a real deployment; the status endpoint claiming writable while inert |
| `test_sync_paid_state_parity.py` drift guard | an invariant added to one sync path and not the other |
| `test_money_reconciliation.py` | cash drawer, receivables, stock and journal disagreeing over a trading day |
| `test_shift_service_unit.py` | drawer arithmetic — audit-only movements entering the tally, discrepancy sign, carry-forward |
| `CrossBackendTokenGuard.test.js` | `authFetch` regaining absolute-URL passthrough |

### Measured on demand (`scripts/audit_money_integrity.py`) — 8 checks, exit 1 on failure

A · mis-attached payments · B · documents with no journal · C1–C3 · paid-state vs
ledger · D1–D2 · orphan and cross-tenant payments · E · duplicate numbers · F ·
entries that do not foot · G · **foreign-key violations** · H · **overlapping open
shifts**. G and H were added this pass *because both were found by hand*, which is
the tell that they belonged in the audit.

### Still only convention (the honest remainder)

- **The other 92 non-money `except: pass` handlers** are deliberately untouched
  (M-5). The rule is written down; nothing enforces it.
- **24 test files** still have structurally risky teardown order. `fk_teardown_scan.py`
  finds them; no gate fails on them.
- **No enforcement that a new money route goes through the command layer.** A
  future route could write an `Invoice` directly; the DB invariants would catch a
  malformed row, but not a missing journal entry until the scheduled audit.
- **The scheduled `run_books_integrity_audit`** runs per database, so two
  internally-consistent-but-divergent databases still both report "balanced".

## 48. Revised scorecard — money model and security

Both figures were stated as bare numbers in earlier parts. Here is what they are
made of, so they can be argued with.

### Money model: **8.0 / 10** (revised down after M-14) (was 7.0 at §14 "data model maturity" / production readiness 6.5)

| Component | Score | Basis |
|---|---|---|
| Correctness of the write paths | 9.5 | Double-entry posting, hash chain, GST engine, per-counter sequences, negative-stock policy — all pre-existing and genuinely good |
| Enforcement *below* the write paths | 8.0 | ▲ from ~2. Was convention-only; now 2 unique indexes, 6 invariants and real FK enforcement, all behaviourally tested |
| Sync fidelity | 8.0 | M-2/M-7/M-8/**M-12** closed with drift guards; journals re-derived not replicated; one real local↔cloud divergence closed (FKs). Marked DOWN from 8.5 after M-12: the pull path silently dropped rows and reported success, and that was found by being asked rather than by any check |
| Reconciliation between subsystems | 6.5 | ▼ M-6 trading-day test plus the drawer and report suites — but **M-14 shows the P&L and trial balance never read the journal at all**, so the books and the reports an owner reads are two different systems |
| Verified state of the real data | 8.0 | 8/8 audit checks clean on `bizassist.db` after the backfill and quarantine; **cloud unverified** |
| Test coverage of money functions | 5.5 | **54.0%** measured (pure subset **75.7%**), up from 32.8% at the start of this work. Still the number holding the score down |

### Security posture: **7.5 / 10** (was 6.5 at §14)

| Component | Score | Basis |
|---|---|---|
| Multi-tenant isolation (cloud) | 8.5 | Five RLS migrations, fail-closed, Postgres-tested — pre-existing |
| Multi-tenant isolation (local) | 7.5 | ▲ from ~5. S-3 closed: scope in SQL, keyword-only required arg, 326 reads audited, gate against regression |
| Consent / authorisation model | 8.0 | M-1/F-1/F-2 closed, fail-closed on unknown requester |
| Credential handling | 7.5 | ▲ S-5 closed — the suite no longer authenticates against production. Export files now gitignored |
| Attack surface | 7.0 | S-2 closed (discovery spoofing). LAN residual risk stated |
| Independent validation | 4.0 | **No penetration test. No Postgres/RLS verification in this environment.** This is what caps the score |

**Composite: ~7.9 / 10**, up from 7.6. Coverage is now over half (54.0%), which
lifts it — and M-14 pulls it back down, because a correct ledger that feeds
incorrect reports is not a correct money model from the owner's side of the screen.
Every claim is still verified **on SQLite only**.

### Why not higher

Four of the most serious findings in this review — M-2, M-7, M-11, M-12 — had the
identical shape: **every subsystem individually correct, the defect living in the
seam between them, and nothing looking broken.** Three of those seams now have
tests.

M-12 is the reason the composite does not go higher. It was found because someone
*asked whether sync was really fine* — not by any test, audit check or log review.
A defect class that has now recurred four times, and whose fourth instance was
still discovered by a question, should not be described as under control.

## 49. M-12 · 🔴 Critical (NEW) — the pull dropped rows and reported success

Asked directly: *"is the sync and pull good for all this? previously cloud to local
sync saw many glitches after successful sync."* Audited, and **the reported symptom
has a precise cause.** It is also the finding my own N4 work would have made
*worse*, because foreign-key enforcement, six money invariants and the M-11 unique
index all make the apply path REJECT rows it previously wrote.

### What the code did

`services/sync_worker.py` wrapped every incoming row in a SAVEPOINT — correct, so
one bad row cannot roll back the batch — and then:

```python
except Exception as row_err:
    logger.warning("[SYNC_WORKER] Pull skip %s id=%s: %s", ...)
```

Three consequences, each verified against the source:

| Line | Effect |
|---|---|
| `logger.warning("Pull skip …")` | reported at **WARNING**, un-aggregated, among ordinary sync chatter |
| `_pull_done += len(records)` | the **whole batch** counted as applied, however many rows failed |
| final broadcast `done: _pull_total, total: _pull_total` | UI shows **100% — a clean success** |
| `_PULL_CURSOR[business_id] = _cloud_cursor` | cursor advances **unconditionally — the row is never re-pulled** |

So a row that failed to apply was counted as applied, presented as a successful
sync, and **permanently lost.** That is the glitch: not a sync that fails, a sync
that succeeds while quietly leaving rows behind.

**Third instance of one asymmetry.** M-7 (paid-state), M-8 (conflict logging) and
now M-12: the push path surfaces its failures in the response body where a caller
can see them (`apply_failures`), and the pull path — which no caller inspects —
swallowed them. `database/sync_map.py` documented this exact failure mode for
`MODEL_MAP` in 2026; the *apply* side keeps relearning it.

### Closed

| Change | Where |
|---|---|
| `log_apply_failure()` — records a rejected row as a `ConflictLog` with `resolution="apply_failed"`, at ERROR, never raising | `core/sync/apply_hooks.py` (shared by both paths, rule 12) |
| Pull handler records instead of warning; failures collected and reported at ERROR as a named list | `services/sync_worker.py` |
| `_pull_done` counts **successes only** | same |
| Progress event carries a `failed` count and stops claiming `done == total` on a partial batch | same |
| **Cursor is HELD while rows are failing** so they are re-pulled — bounded by `_PULL_MAX_FAILED_STREAK = 3`, after which it logs CRITICAL and advances | same |
| 12 tests, incl. drift guards asserting the old `"Pull skip"` handler and the unconditional `_pull_done += len(records)` cannot return | `tests/test_sync_pull_failure_visibility.py` |

**Why `ConflictLog` rather than a new table:** it is already exposed by
`GET /api/sync/conflicts` with an `unreviewed_count` badge. Reusing it means a
rejected row becomes visible in the product with no new endpoint — the mechanism
built to stop silent lost *edits* now also stops silent lost *rows*.

**The cursor bound is a deliberate trade, stated:** holding forever would let one
permanently-unappliable row stall every later row behind it — the exact stall that
per-row SAVEPOINTs were introduced to prevent. So retry three times, then escalate
to CRITICAL naming the rows, leave them in the review list, and let the rest
through. Never silent in either branch.

### Two mistakes of mine in this patch, recorded

1. A stray non-ASCII character in a comment (from an editing slip).
2. `len(_row_failures) if "_row_failures" in dir() else 0` — the list was declared
   *inside* the pull block, so on a path where that block never ran the cursor
   logic would raise `NameError`, be caught by the outer handler… **and skip the
   cursor update silently.** A guard against silent skips, failing silently. It is
   now declared at function scope, and a test asserts the declaration precedes its
   use.

### Still open on the pull path

- The **push** path acks a row after a failed uid-dedupe (`processed_count += 1`
  with a WARNING). Narrower than M-12 was — uid-dedupe is the intended resolution
  and non-integrity errors abort the whole batch with a 500, so the batch is
  retried — but it is the same shape and should get the same treatment.
- The **frontend does not yet render** the new `failed` count. The banner no longer
  reports a false 100%, but nothing says *"synced, 3 rows need review"* in words.
  That is the remaining half of making this visible to an owner rather than to a
  log reader.

## 50. M-13 closed — the push acked rows the cloud had rejected

The mirror image of M-12, found by asking the same question of the other
direction. `routes/sync.py`'s `IntegrityError` handler ended:

```python
processed_count += 1  # ack either way so it isn't re-sent every cycle
```

…reached whether or not the uid-dedupe had resolved anything. When
`deduped == "skipped"` the IntegrityError was **not** a uid collision — no uid on
the payload, no uid column, or no existing row carrying it — so the constraint
that fired was something else: a foreign key, one of the N4 money CHECKs, or the
M-11 index. **The row landed nowhere, was logged at `INFO`, and was acked, so the
device's outbox dropped it permanently.**

Worse than M-12 in one respect: M-12 lost cloud→local rows; this lost
**local→cloud** rows — the shop's own sales. And the N4 constraints made it far
more reachable, because they reject rows that previously inserted.

| Change | Where |
|---|---|
| Genuine dedupe (`updated` / `kept-newer-cloud`) separated from outright rejection | `routes/sync.py` |
| Rejections recorded via the shared `log_apply_failure`, logged at ERROR, returned in the response as `rejected` | same |
| The push client reads `rejected` and logs it — reporting into a response nobody reads is the same silence one layer up | `services/sync_worker.py` |
| `rejected` count rides the push progress event | same |
| 6 further tests, incl. one asserting the response body is inspected **after** the status check | `tests/test_sync_pull_failure_visibility.py` |

**The ack stays**, deliberately: refusing it would stall the outbox behind a row
that can never apply — the same poison-row trade the per-row SAVEPOINT and
`_PULL_MAX_FAILED_STREAK` already make. What changed is that it is no longer
silent.

**Also fixed:** a stray CJK character my own M-12 patch left in a comment. On a
Windows console with a non-UTF-8 code page that can turn a log line into a
`UnicodeEncodeError` — a silent-failure source inside the module whose job is
removing them. A test now fails on stray non-ASCII in any of the three sync
modules.

## 51. Sync failures are now visible in the product

The counts existed and nothing rendered them, so an owner still saw a clean
banner. `frontend-billing/src/layouts/AppLayout.jsx`:

- the `sync.progress` handler reads `failed` (M-12) and `rejected` (M-13);
- **the banner no longer auto-dismisses on a partial batch** — the 2.5 s
  auto-clear is now gated on `problems === 0`, because clearing it was literally
  the "green banner over missing data";
- a persistent red panel states *"N records could not be synced — they are saved
  for review, not lost"*, with a manual Dismiss. Worded for an owner, not a
  developer, and it does not auto-hide, because the whole point is that this one
  must be seen.

*Not verified by me:* the frontend suite needs longer than this environment
allows. `AppLayout.jsx` parses clean as JSX and the brace balance is unchanged;
`run_tests.bat` is the check.

## 52. M-14 · 🔴 Critical (NEW) — the P&L and trial balance do not read the journal

Found by `tests/test_reports_agree.py` on its first run, and it is the most
consequential **reporting** defect in this review. The journal is correct; the
reports that owners read are not.

Ground truth for one sale of 5 x ₹100 at 18% GST:

```
invoices        : subtotal 500.00  cgst 45.00  sgst 45.00  total 590.00
journal_lines   : Cash & Bank  Dr 590.00
                  Sales            Cr 500.00
                  GST Payable      Cr  90.00     <- correct double entry
```

What the reports say:

| Report | Says | Should be | Error |
|---|---|---|---|
| P&L "Gross/Net Sales Revenue" | **590.00** | 500.00 | +₹90 — the tax counted as revenue |
| P&L "Gross Profit" | **290.00** | 200.00 | +₹90 |
| P&L "Net Income" | **290.00** | 200.00 | +₹90 |
| Trial balance "Sales" (Cr) | **590.00** | 500.00 | +₹90 |
| Trial balance "GST Payable" | **absent** | Cr 90.00 | a liability to the government is invisible |

**Mechanism, from the code.** Both `report_pnl` and `report_trial_balance` sum
`Invoice.total_amount` — the GST-inclusive grand total — and never touch
`journal_entries`. `report_trial_balance`'s own docstring states the assumption:

> *"This is a single-entry / incomplete-records system (**no posted journal**), so
> the trial balance is derived from the same source figures as the P&L and Balance
> Sheet and balanced with a **Capital (owner's equity) plug**"*

That was true once. It is not true now: there IS a posted, hash-chained journal,
and `report_journal`, `report_general_ledger`, `verify_chain` and the scheduled
`run_books_integrity_audit` all read it. These two reports were never moved over.

**Three consequences, and the third is the reason this is Critical:**

1. **Revenue and profit are overstated by the GST collected.** On an 18% item,
   reported revenue is 18% too high and reported profit is too high by the entire
   tax. GST collected is money held *for the government*, not earnings.
2. **GST Payable appears nowhere** on the trial balance or the balance sheet, so
   the single largest short-term liability a retailer carries is not shown.
3. **The trial balance cannot detect a journal defect, because it does not read
   the journal — and it always foots, because Capital is a plug.** During M-2,
   when business 6 had 38 invoices and *zero* journal entries, this report would
   have shown a perfectly balanced statement. `balanced=True` in its log line is
   not evidence of anything. That is why check B of the audit had to exist.

**Why my first read of this was wrong, recorded.** I initially concluded the P&L
disagreed with the trial balance and could be checked against it. It cannot: both
read `Invoice.total_amount`, so **they agree with each other and both differ from
the journal.** Cross-report agreement is necessary and not sufficient — the
reports must also agree with the ledger. Corrected only because I went to
`journal_lines` for ground truth instead of trusting a second report.

### CLOSED (27 Jul 2026, commit d34de0a) — verified

Fixed by the owner, and **verified against journal ground truth**, not taken on
trust:

| | Now reports | Journal says |
|---|---|---|
| Trial balance "Sales (GST-exclusive)" | Cr **500.00** | Cr 500.00 ✓ |
| Trial balance "GST Payable" | Cr **90.00** — now visible | Cr 90.00 ✓ |
| Trial balance totals | Dr 590 / Cr 590, foots | — |
| P&L "Sales Revenue (Journal, GST-exclusive)" | **500.00** | ✓ |
| P&L "GST Payable (Tax collected — liability, not income)" | **90.00** | ✓ |

The approach taken was **better than the one recommended here**. Rather than
silently restating every owner's profit, the P&L became DUAL-SECTION: the
invoice-basis figures are retained with explicit "GST-inclusive" labels, and a
journal-basis section is added beside them. The trial balance now reads
`journal_lines` for its nominal accounts.

It also added a row this review had not thought to ask for and should have:
**"Journal-Invoice reconciliation delta (0 = fully posted)"** — a self-check that
would have surfaced M-2 the day it happened.

**One gap closed afterwards (this pass):** the only rows named "Gross Profit" and
"Net Income" were still the invoice-basis ones, so an owner reading "Net Income"
saw a figure overstated by the tax collected. Added
**"Gross Profit (Journal basis, GST-exclusive)"** and **"Net Income (Journal
basis, GST-exclusive)"** — verified 200 / 200 against an invoice-basis 290 on a
5 x ₹100 @ 18% day.

### Original hand-back reasoning, retained

**NOT fixed, and this is a deliberate hand-back.** Pointing these two reports at
`journal_entries` is a small code change with a large business consequence: every
owner's reported revenue and profit drops by the tax they collected, and those
figures may already have been used for filings, loan applications or pricing. That
is a decision about what a customer is told their profit was — not a refactor.
Recommended as the top item in §54.

## 53. M-15 · 🟠 High (NEW) — receivables the owner cannot chase

Same test, same run. For an unpaid invoice with **no `customer_id`** (a walk-in
credit sale — "pay me tomorrow", entirely normal at a counter):

| Report | Shows |
|---|---|
| `balance-sheet.assets.receivables` | **₹354.00** |
| `/reports/outstanding` | **`[]`** |

`report_outstanding` aggregates per customer and drops the rest —
`if row.customer_id is not None` — while the balance sheet counts every unpaid
invoice. So the money is on the balance sheet as owed, and on **no chasing list at
all**. Both screens look correct in isolation; the defect is only in the
disagreement.

Encoded as `xfail(strict=True)` rather than left as a comment, so it **flips to a
failure the moment it is fixed** instead of sitting as a permanently-tolerated red
mark.

### CLOSED (27 Jul 2026, commit d34de0a) — verified

`/reports/outstanding` now returns
`{"party_name": "Walk-in / No Customer", "total_amount": 590.0,
"paid_amount": 236.0, "outstanding_amount": 354.0}` — exactly the explicit
null-bucket recommended. **The strict xfail did its job**: it began failing when
the fix landed, forcing the marker to be removed rather than allowing a stale
red mark to accumulate. That is the mechanism working as designed, and it is the
argument for rule 43.

## 54. Recommendations, ordered

1. **M-14 — point `report_pnl` and `report_trial_balance` at `journal_entries`.**
   Needs your decision, not just a commit: reported profit will fall by the GST
   collected. Do it deliberately, with a note to affected owners.
2. **M-15 — include un-attributed unpaid invoices in `/reports/outstanding`**,
   grouped as "Walk-in / no customer". One query change; the xfail test is already
   written and will go green.
3. **Run the backfill and audit against the cloud Postgres.** Still the largest
   unverified surface — every claim in this document is SQLite-only.
4. **Close shift 4** (₹8,113) so the M-11 index can install.
5. **`run_tests.bat`** to confirm the frontend banner change.

## 56. M-16 (owner-found) and M-17 · 🟠 High (NEW) — phantom line items

### M-16 — closed by the owner, and the most valuable single number in this audit

Found independently, not by any check here: **a batch script inserted 63 spurious
`invoice_line_items` rows on 2026-07-17** into businesses 6 and 7. Repaired by
`backend/scripts/repair_duplicate_line_items.py`.

**Brownie Factory's P&L went from a ₹-6,715 fake loss to its real ₹+4,648
profit.** That is the largest correction in this entire review, and it was
invisible to everything: invoice headers were right, the journal footed, the hash
chain verified. Only the *lines* were inflated — and until now nothing compared
the lines to the document they belong to. COGS is computed from
`invoice_line_items x Product.cost_price`, so duplicated lines inflate cost and
sink profit.

### Audit check I added (rule 35)

Needing to find something by hand is the signal it belongs in the automated audit.
`scripts/audit_money_integrity.py` gained check **I**:

```
SUM(line_total)  ==  total_amount + cash_discount - round_off
```

**My first version of this check was wrong** and produced five false positives on
business 7. It compared against `total_amount` alone, but a post-tax cash discount
and the round-off live on the HEADER, not on the lines. Verified on real rows
(`LCL-OW-0027`: 337.65 == 323 + 15 − 0.35). Recording it because a check that
cries wolf is a check people learn to skip — which is exactly how section B's
legacy-import noise nearly buried the real M-2 gaps.

### M-17 — the same corruption, an EARLIER occurrence, still live in business 6

With the formula corrected, check I reports **6 invoices in business 6** whose
lines do not foot, totalling **₹3,298.26 of phantom line value**:

| Invoice | Header | Lines | Delta | Lines |
|---|---|---|---|---|
| `C1-0004` | 566.00 | 2,608.94 | **+2,043.28** | 11 |
| `C1-0001` | 942.00 (+50 disc) | 1,557.64 | **+565.68** | 7 |
| `C1-0003` | 396.00 | 651.31 | **+255.44** | 2 |
| `OW-0003` | 124.00 | 310.21 | **+186.50** | 2 |
| `OW-0001` | 187.00 | 310.21 | **+123.70** | 2 |
| `C1-0002` | 2,533.00 (+500 disc) | 3,157.10 | **+123.66** | 5 |

Every delta equals a whole number of real line items (₹123.70 = Coffee Powder,
₹255.45 = Wheat Flour, ₹186.51 = Sugar), so these are duplicates, not arithmetic
drift. Business 7 is clean.

**Why the M-16 repair did not catch them — mechanism, from the code.** Line 58 of
the repair script scopes itself to a single calendar day:

```sql
WHERE li.created_at >= '2026-07-17' AND li.created_at < '2026-07-18'
```

Business 6's phantom rows were created on **2026-06-29, 06-30, 07-01 and 07-03** —
appended a day or more after each invoice's genuine lines. So the script now
correctly reports "0 rows"; its window is empty, and the corruption outside that
window is untouched. **This is a second, earlier occurrence of the same class**,
which means the inserting process ran more than once.

### M-17 CLOSED — repaired by the invariant, not by a date

`backend/scripts/repair_line_items_by_invariant.py`.

**The discriminator is insertion order, not `created_at`.** Line items are written
with their invoice, so the genuine rows are the ones that came first. The tool
walks the lines in `id` order accumulating `line_total` and finds the PREFIX that
reconciles to the header; everything after it is an intruder. That rule is
self-validating — it only ever acts when the surviving rows match a figure the
invoice already stored independently, and **if no prefix reconciles it deletes
nothing and flags the invoice for a human.**

A date could not have done this. Two of the six invoices have the genuine AND the
phantom row written on the same calendar day:

| Invoice | Target Σ(lines) | Prefix that reconciles | Rows deleted |
|---|---|---|---|
| `C1-0001` | 991.96 | 4 → 991.98 | 3 |
| `C1-0002` | 3,033.44 | 4 → 3,033.40 | 1 |
| `C1-0003` | 395.87 | 1 → 395.86 | 1 |
| `C1-0004` | 565.66 | 3 → 565.66 | 8 |
| `OW-0001` | 186.51 | 1 → 186.51 | 1 *(same-day)* |
| `OW-0003` | 123.71 | 1 → 123.70 | 1 *(same-day)* |

**Proven on a copy of the real database, with a money diff (rule 29):**

| | before | after | delta |
|---|---|---|---|
| invoice_value | 290,949.25 | 290,949.25 | **0** |
| paid_total · payments_sum | 46,352.00 · 22,293.00 | identical | **0** |
| journal Dr · Cr | 295,764.00 · 295,764.00 | identical | **0** |
| stock_rows | 239 | 239 | **0** |
| line_items | 193 | **178** | −15 |
| line_value | 75,079.18 | **71,780.88** | −3,298.30 |

Afterwards: **all nine audit checks A–I clean**, `integrity_check: ok`,
`foreign_key_check: 0`, and the invariant re-checked at 0 repairable / 0 needing
review. Every deleted row exported to timestamped JSON before the first write.

**The business impact.** COGS is `invoice_line_items × Product.cost_price`, so
business 6's cost was overstated by **₹2,422.57** and its gross profit understated:
**219,898.15 → 222,320.72**. Business 7 unchanged (already repaired by M-16).

Pinned by `tests/test_line_item_invariant.py` — 13 tests covering both halves: the
invariant holds for invoices the billing command writes (including with a cash
discount), and the detector separates same-day rows, accounts for the discount,
**refuses when no prefix reconciles**, ignores zero-value CSV imports, and exports
before the first write.

### Original hand-back reasoning, retained

Not repaired at the time: which side is authoritative needed the owner's
judgement. The evidence favoured the header (for `C1-0004`, `subtotal` 505.06 x
1.12 + 0.34 round-off = 566.00, and the three lines dated 06-30 sum to 565.66 — so
the eight rows dated 07-01 are the intruders), but deleting billed line items is
not a call to make from a pattern match. The prefix rule turned that judgement
into something the tool can prove for itself.

### Fixes applied to the repair script itself

| Problem | Fix |
|---|---|
| Lived at repo-root `scripts/`, the only repair script outside `backend/scripts/` (breaks F-9/N10) | Moved to `backend/scripts/` |
| `DB = "backend/bizassist.db"` — relative, so it only ran from the repo root and died from `backend/` | Resolves from `__file__`; `--db` override added; exits with an explicit message rather than guessing |

That relative path mattered more than it looks: the repo root also holds a stale,
**empty** `bizassist.db`, and a relative path can find the wrong one first. That
trap already produced one incorrect "nothing to repair" conclusion earlier in this
audit. It failed loudly rather than silently — verified — but only by luck of the
missing parent directory.

## 57. SonarCloud quality gate — why it was failing

Two independent causes, both measured.

### 1. ~800 new uncovered lines from operational scripts

`sonar.sources=backend` with no coverage exclusions, so `backend/scripts/`
counted as new code:

```
backend/scripts/  ->  798 statements, 0% line coverage
```

audit_money_integrity, backfill_journals, quarantine_fk_orphans,
resolve_duplicate_invoice_numbers, repair_m7_rollback, reconcile_orphans,
cloud_cleanup_counters, quarantine_misattached_payments, fk_teardown_scan. They
are one-shot tools a human runs from a terminal; nothing imports them, by design.
Against the default **Coverage on New Code >= 80%** condition that alone fails the
gate however well the application is tested.

Fixed with `sonar.coverage.exclusions` — **not** `sonar.exclusions`. The
distinction is the point: these files are still fully analysed for bugs, smells
and security hotspots, because several of them delete or rewrite money rows and
are exactly the code that deserves scrutiny. They are only out of the coverage
ratio. The dishonest alternative — tests that import each `main()` — would measure
argparse plumbing and inflate the number without adding safety; they are instead
validated the way §44.3 requires (dry-run, proven on a copy, money diff, JSON
export before the first write).

Also coverage-excluded: `backend/alembic/**`, the root `check_*`/`reset_*`/
`dump_schema`/`scan_db` inspection scripts, `main_groq.py` (ASGI wiring executed
by import side effects), and `**/*.jsx` — the React suite is component-level, so
the frontend coverage number should come from the `.js` logic modules
(sync/outbox, lib/, hooks/, utils/), which are deliberately **not** excluded.

`sonar.cpd.exclusions` for the scripts too: their shared shape (dry-run banner,
`--apply` guard, JSON export, before/after verification) is a safety property, not
duplication to refactor — one shared helper would let a single bug change the
behaviour of every money repair at once.

### 2. Deprecated scanner action

The workflow used `SonarSource/sonarcloud-github-action@master`. That action is
**deprecated** — its own repository description now reads *"Deprecated. Use
https://github.com/SonarSource/sonarqube-scan-action instead."* Since v4.1.0
`sonarqube-scan-action` is the single entrypoint for both SonarQube Server and
Cloud and is a drop-in replacement, but it **requires `SONAR_HOST_URL`**, which the
old action inferred.

Migrated to `SonarSource/sonarqube-scan-action@v4` with
`SONAR_HOST_URL: https://sonarcloud.io`. Pinned to a major version rather than
`@master`: a scanner that can change under you between runs makes "the gate went
red" unattributable.

### Also corrected in the workflow

`DATABASE_URL` was exported at job level. `tests/conftest.py` owns that variable —
it resolves a per-xdist-worker file (or honours `BIZASSIST_TEST_DATABASE_URL` for
the Postgres run) before any module imports, and `database/db.py` fails closed
unless the URL names a test DB. The export was a second source of truth that
conftest then overwrote. Removed, and `CLOUD_API_URL: http://127.0.0.1:9` added as
a belt to the S-5 guard.

## 58. The `setdefault` sweep — verified

46 test files changed `os.environ["DATABASE_URL"] = ...` to
`os.environ.setdefault(...)`. Correct, and it fixes something real: every module
was hard-overwriting the value `conftest.py` had just chosen. Proven empirically —
an `-n 2` run now creates `test_bizassist_gw0.db` and `test_bizassist_gw1.db`,
where before all workers collapsed onto one file, which is the flakiness conftest's
own comment describes. It also un-blocks `BIZASSIST_TEST_DATABASE_URL`, so the
cross-dialect Postgres job was silently running on SQLite for those modules.

Only `conftest.py` still hard-sets it, which is right — it is the authority.

`test_rag.py`'s isolated `test_bizassist_rag.db` is now unreachable as a
consequence; it shares the suite database and clears its rows in the fixture. The
stale filename references are annotated rather than deleted, in case an older run
left a file behind.

## 59. N4b — the line-item overfill guard: prevention, not detection

M-16 and M-17 were the same corruption twice, so detection was not enough. The
write is now **refused by the database**.

### The obvious constraint was unimplementable, and shipping it would have been an outage

The natural rule is `SUM(line_total) == total_amount + cash_discount - round_off`.
As a row-level trigger it rejects almost every legitimate write. Verified in the
code before designing anything, not assumed:

| Path | Order of writes | Consequence |
|---|---|---|
| `create_sale_invoice` | header WITH final total (`total_amount=grand`, `db.add`, `db.flush`) → **then** line items one at a time | after line 1 of 3 the equality is false |
| Sync **pull** | `invoice_line_items` is in `_child_last`, so the invoice lands first carrying its final total, lines arrive after, one row at a time | same transient state, on **every synced document** |

An equality trigger would therefore have rejected every multi-line sale and every
synced line item — the latter landing them in the conflict log via M-12, which is
a far worse failure than the defect being prevented.

### What the guard actually asserts

The asymmetry. A legitimate build-up only ever fills **up to** the header target;
the corruption **exceeds** it:

```
SUM(existing lines) + NEW.line_total  <=  total_amount + cash_discount - round_off + 1.00
```

This is safe because the write surface is small and was verified: the **only** code
that creates `InvoiceLineItem` rows is `create_sale_invoice` and
`create_credit_note`, both inside the transaction that just wrote the header, and
**there is no invoice-edit or add-line route anywhere in the app**.

`database/migration.py::_ensure_line_item_overfill_guard`. Two dialects, because a
Postgres `CHECK` cannot contain a subquery:

* **SQLite** — `BEFORE INSERT … WHEN <subquery condition> … RAISE(ABORT)`
* **Postgres** — a `plpgsql` trigger function raising an exception

Existing over-filled rows do **not** block installation (unlike the M-3/M-11 unique
indexes, a trigger constrains future writes only) but are reported at ERROR with
the repair command, so they are never mistaken for clean.

### Verified — both halves

| Assertion | Result |
|---|---|
| Appending a phantom line to a completed invoice | **refused** — `M-17 guard: line items would exceed the invoice total` |
| Multi-line sale through the API (3 lines) | **201**, lines total 1,534.00 == target |
| Sale with a header cash discount (target > total) | **201** |
| Credit note | passes |
| **Sync apply: header first, then lines one at a time** | **allowed** — the test that protects push/pull |
| Zero-total CSV-imported invoice | guard inert, lines import normally |
| 0.40 paise overshoot | allowed (tolerance 1.00; smallest real phantom row was ₹123.70) |
| Re-running the installer | idempotent |

22 tests in `tests/test_line_item_invariant.py`. Regression-checked against
`test_billing`, `test_money_reconciliation`, `test_sync_pull`,
`test_sync_paid_state_parity`, `test_journal_repost_on_sync`, `test_phase4_sync`,
`test_import`, `test_data_transfer`, `test_uid_cross_db` — all green.

### A failure worth recording

The first version did not install at all: the SQLite trigger body used implicit
string concatenation across lines (`'part one' 'part two'`), which is a Python
construct, not SQL. It failed **loudly** — `_ensure_line_item_overfill_guard` logs
at ERROR and the boot continued — and the test asserting the guard is present
caught it immediately. Recorded because the alternative design (install silently,
assume success) would have shipped an absent guard that every test reported as
working.

## 60. M-18 · 🔴 Critical (NEW) — the corruption reached the two-party table, and B2BLedger has no writer

Two findings from auditing the ecosystem layer. Both measured on the live database.

### M-18 — 2 of 2 live B2B orders have inflated line items

| Order | Header | Σ(lines) | Delta | Lines |
|---|---|---|---|---|
| `ORD-20260630-2QTE` | 836.90 | 1,423.84 | **+586.95** | 6 |
| `ORD-20260702-J17T` | 774.11 | 1,298.27 | **+524.16** | 4 genuine + 2 |

**₹1,111.11 of phantom line value across every B2B order in the system.** Same
signature as M-16/M-17: the first 4 lines sum to exactly the header total, and
lines 5–6 duplicate two earlier products.

This is worse than the single-tenant case. A B2B order is a record **two
businesses quote to each other**. A buyer reading a total the seller does not
recognise is precisely the failure the shared-ledger thesis cannot tolerate.

**What I verified, and what I could not.** Facts:

* `core/order/service.create_order` is **correct** — read line by line. It builds
  one `B2BOrderLineItem` per input item and computes the header totals in the same
  loop, so it cannot produce this.
* All 12 line-item uids are **distinct and non-NULL**, so a uid collision is not
  the cause. *(This disproved my first hypothesis, which was uid-matching failure
  on the cloud→local mirror. Recorded because it was wrong.)*
* All 12 rows carry `created_at = 2026-07-24 20:36:24` while the order dates are
  30 Jun and 2 Jul — a **bulk insert weeks after the fact**.
* No script or route in the tree writes `B2BOrderLineItem` by name.

Unproven hypothesis, stated as such: `b2b_orders` / `b2b_order_line_items` are
`PULL_ONLY` (cloud→local mirror) and the sync apply writes them **generically via
`MODEL_MAP`**, which would not appear in a name search. A mirror rebuild that
re-inserted rows its uid matching could not pair would produce exactly this. I
cannot confirm it without the cloud's uids, which I cannot reach.

### Closed — detection, prevention and repair, all three

| Layer | Change |
|---|---|
| **Detection** | Audit check **J** — B2B order lines vs header. Found both orders immediately |
| **Prevention** | The overfill guard generalised to a table spec and installed on `b2b_order_line_items` as well as `invoice_line_items`. Verified: building up to the header total is allowed, a 4th line is **refused** |
| **Repair** | `repair_line_items_by_invariant.py` driven from the same spec — the prefix rule handles both families |

Proven on a copy: `b2b_lines` 12 → 8, `b2b_line_value` 2,722.12 → 1,611.01
(−1,111.11), **every other figure unchanged** (invoice value, paid, payments,
journal Dr/Cr 295,764 both sides, invoice line items, stock). Audit **A–J clean**,
`integrity_check: ok`, `foreign_key_check: 0`.

`b2b_orders` carries no `cash_discount` / `round_off`, so its target is the plain
`total_amount` — using the invoice expression would reference columns that do not
exist. Pinned by a test.

### B2BLedger has NO WRITER — the ⭐ Verified Ledger rests on an empty table

`grep` across `core/`, `routes/`, `services/`: the only occurrence of
`B2BLedger(` is the class definition. **Nothing ever inserts a row.** Confirmed
empty on the live database (`b2b_ledgers: 0`).

Meanwhile the table is referenced in ~20 places that all treat it as live:
`sync_map.MODEL_MAP`, `_SYNC_TABLES`, `routes/sync.py`,
**`apply_hooks.FINANCIAL_ENTITIES`** (so the system is prepared to log sync
conflicts on a table that can never have rows), `purge_business_data`, the
activity-feed labels, the data-transfer allow-lists, a uid migration, and the pull
ordering.

This is **not a bug** — it is an unimplemented feature whose entire supporting
infrastructure already exists. But §3 of this review calls `B2BLedger` "the
sleeping giant" and §7-P2 ⭐ makes the counter-signed Verified Ledger *the*
standout move. That thesis currently rests on a table with no writer, and the
review said so nowhere. Stating it plainly: the schema is ready, the plumbing is
ready, and the ledger is never written.

### Correction to my own reporting

I previously told the owner that `core/api/orders.py` was "6 of 7 functions
untested" and `core/api/connections.py` "14/14 untested". Those came from the
**name-reference proxy**, which cannot see a function exercised over HTTP. Real
line coverage, measured with `pytest-cov`:

| Module | Real | Name proxy said |
|---|---|---|
| `core/connection/service.py` | **88%** | 13/15 missing |
| `core/api/connections.py` | **76%** | 14/14 missing |
| `core/order/service.py` | **74%** | 3/5 missing |
| `core/api/orders.py` | **72%** | 6/7 missing |
| `core/connection/transfer.py` | ~~**10%**~~ **82%** — see below | — |

The B2B layer is far better covered than I reported.

> **⚠️ Correction, added later — the 10% in this table was also wrong.**
> I wrote that `core/connection/transfer.py` was the real gap at 10% and that the
> next testing effort belonged there. That figure was an artefact of measuring the
> module under the *connections* test file, which does not exercise it;
> `tests/test_b2b_transfer.py` already covered **82%**, since raised to **92%**.
> Two wrong coverage claims in two consecutive reports, both from careless
> measurement rather than from the code changing — see §61 and rules 54 and 57.
> The paragraph above is left standing rather than quietly edited, because the
> mistake is the point.

## 61. M-19 · 🟠 High (NEW) — the B2B importer dropped rows and reported success

Third venue for the M-12/M-13 pattern, found while covering
`core/connection/transfer.py`.

`import_b2b_tables` counted its skips and then **threw the count away** — it
returned `applied` only, and `routes/data_transfer.py` reported that as
`imported[table] = n`. So an import that dropped a counterparty relationship, an
order, or an order line told the operator *"42 rows imported"* and nothing else,
while the rows were simply gone.

The individual skips matter more than the count:

| Skipped | Reason | Consequence |
|---|---|---|
| connection | counterparty BizID absent | the business's B2B network is silently thinner |
| order | party unresolvable | order history missing on one side |
| **order line** | **product absent in this DB** | **the order's lines no longer sum to its header** — the M-18 invariant, broken from the *under-filled* side, by this importer |

**Closed.** `import_b2b_tables(..., skipped_out=[...])` records one dict per
dropped row with its reason; the route collects them, logs at ERROR, and returns
them as `b2b_skipped` in the response. Same shape as the `unparsed` list on the
S-3 scanner and the `rejected` list on the push — reporting what was NOT done is
part of the result, not diagnostics.

### A fourth skip site I missed, and the test that caught it

My first patch wired three of the four `skipped += 1` sites. The fourth — a line
item whose **parent order** is absent — had no `_skip()` call and **no log line at
all**; the row vanished behind a bare counter bump. The symptom was a log reading
`SKIPPED=1 ... rows: []`: a count and a list disagreeing.

A test asserting the two agree now exists, so a fifth site added without recording
the row fails the build rather than shipping. That assertion is worth more than the
four fixes.

### `_remap_requester`'s docstring was lying about its own coverage

Its final line reads *"Pure — takes the raw row, returns an id or None.
**Unit-tested directly.**"* Measured: **nothing in the test corpus named the
function, and no test reached lines 170-176 — its entire branch logic.** This is
the M-1 consent fix, the one that stopped the importer naming a third party as the
requester of a B2B link and thereby letting the importer "approve" a connection
nobody asked for.

A security fix whose documentation asserts coverage it does not have is worse than
one that admits it has none, because it stops anyone looking. Now covered by 8
direct tests, including the third-party case, both parties, the malformed-row
case, and a guard that the mapping compares against SOURCE ids rather than local
ones (matching local ids would look correct in any same-database test and be wrong
in the only case the function exists for). One test asserts the docstring still
makes the claim, so deleting the tests without editing the docstring restores the
lie loudly.

### `_claim_uid` swallowed a failed uniqueness check

`except Exception: taken = False` — a lookup that **failed** was treated as *"the
uid is free"*, which then inserts a possibly-colliding uid and 500s the whole
import on the partial unique index: precisely the outcome the function exists to
prevent. Now mints a fresh uid (the safe direction — one row loses cross-database
identity, nothing breaks) and logs at ERROR. Rule 13: fail-open is often right;
fail-open *and silent* never is.

### Coverage, and a second correction to my own reporting

`core/connection/transfer.py`: **82% → 92%**.

I had told the owner this module was at **10%**. That figure was an artefact of
measuring it under the *connections* test file, which does not exercise it —
`tests/test_b2b_transfer.py` already covered 82%. Two wrong coverage claims in two
consecutive reports, both from measuring carelessly rather than from the code
changing. The lesson is in rule 54 and now in rule 57.

## 62. Architectural rules added

17. **Fail-closed is a property of every outbound resource a test can reach, not just the database.** `database/db.py` refuses a non-test `DATABASE_URL`; nothing refused a production socket, so the suite authenticated against a live deployment with a stored token. Any component that speaks outward with a credential must be inert in a test context by default. (S-5)
18. **A test whose verdict can come from the network is not evidence.** If an assertion's outcome changes with connectivity, it is measuring the environment, not the code. (S-5)
19. **A scope belongs in the query, and it may not be optional.** A tenant filter enforced by every caller remembering is a convention. Make the owner argument required and keyword-only, and constrain it in SQL — and make "not yours" indistinguishable from "does not exist". (S-3)
20. **An audit is true on the day it runs; a test is true on every run.** Where there is no database layer to move a rule into, the rule goes into a checked-in analyser with a gate, and intentional exceptions go in an allow-list with written reasons. (S-3)
21. **Before enforcing a constraint, prove the data and the code can satisfy it.** `paid_amount <= total_amount` reads obviously correct and would have rejected legitimate overpayments at the counter. Every invariant here was checked against real rows first, and installation refuses over existing violations rather than "correcting" history. (N4)
22. **A declared constraint that the engine ignores is documentation.** SQLite's `PRAGMA foreign_keys` defaults OFF and is per connection, so every FK and CASCADE in the models was inert on local installs while the cloud enforced them. Verify enforcement by attempting a violating write, never by reading the schema. (N4)

23. **One implementation is not one code path.** `purge_business_data` documented itself as the single source of truth for deleting rows; `wipe_all_data` sat directly above it and did its own unordered deletes. Verifying the correct implementation says nothing about whether its neighbours call it — enumerate the routes, then follow every service function behind them. (§43.1)
24. **A correct delete order is a property of the schema, not of the module.** Where a fixture or a job deletes without a tenant filter, derive the order from the mapper metadata (`reversed(Base.metadata.sorted_tables)`) instead of listing tables, so it cannot go stale when a model gains a foreign key. (§43.2)
25. **Partial test runs cannot observe cross-module interaction.** Three defects here were invisible in chunked runs and immediate in a full serial run — global deletes and `drop_all` on a shared database only collide when the colliding module is present. A green subset is not a green suite. (§43.2, §43.3)
26. **Contention is normal operation, not an exception.** Several threads write one SQLite file, so "database is locked" was reachable on a plain signup. A concurrent writer needs a busy handler, not an error path. And when the obvious remedy (WAL) changes the on-disk representation, check what copies the file before taking it. (§43.4)
27. **"Fix the orphans" is not one rule.** Whether a row that lost its parent should be severed, re-pointed or removed depends on whether the column is nullable and on what the row is evidence of. Deleting every FK violation is fast and destroys money records: three of four orphaned line items here belonged to live, settled tax invoices. Decide per group, in writing. (§44.2)
28. **Enforcing a constraint finds more than constraint violations.** The single orphaned `register_shifts` row was an OPEN drawer holding ₹8,113 whose operator had been deleted — unclosable, and outside every tally, forever. It surfaced only because a foreign key finally objected. (§44.2)
29. **Repair scripts prove themselves on a copy, with a money diff.** Not "the audit is clean afterwards" — every total (invoice value, paid, receipts, journal debits and credits, stock quantity) is compared before and after and must be identical, and every affected row is exported before the first write. (§44.3)
30. **A repair is not finished until you check what it revealed.** Re-pointing one orphaned shift exposed an overlapping open drawer holding ₹2,485 that had never reached a tally. The instinct that the repair *caused* it was wrong — it made a pre-existing defect visible. Run the audit again after every repair and read the new failures as findings, not as regressions. (§45)
31. **A correctness rule keyed on a column that sync can populate is not enforced.** "One open shift per user" was checked against `user_id`, which arrives from other databases as a foreign integer — so the check silently asked about the wrong operator. Any invariant keyed on a synced column needs a database constraint behind it. (§45, rule 11 again)
32. **Every script that exports rows for reversibility must be gitignored when it is written.** These snapshots hold customer names, invoice numbers and line items. `cloud_sync_tokens.json` was covered; two repair exports were not, because each new script invented its own filename. Add the pattern in the same commit as the script. (§45)
33. **A check that cannot see something must not report that there is nothing to see.** The S-3 scanner skipped unparseable files silently, so a syntax error bought a free pass on tenant scoping and the gate still went green. Any analyser must return what it FAILED to examine, and the gate must fail on it. Same defect as F-1 and M-11 wearing different clothes. (§46)
34. **"Not found" and "the lookup broke" are different answers.** `_columns()` returned an empty set on any exception, so an introspection failure was filed as "the table lacks these columns" and the operator read a benign reason for a broken guard. Never collapse an error into a legitimate empty result. (§46)
35. **Audit what you had to find by hand.** Both checks added to the money audit this pass (G foreign keys, H overlapping shifts) existed only because a human ran a query manually. Needing to look for something by hand is the signal that it belongs in the automated audit. (§47)
36. **A cursor that advances past a failure converts a retry into a loss.** Per-row SAVEPOINTs stop one bad row rolling back a batch; they do not make the row optional. Any incremental sync must decide explicitly whether a rejected row holds the cursor, and bound that hold so one poison row cannot stall the stream. (M-12)
37. **`done == total` is a claim about correctness, not about effort.** A progress counter that increments by batch size cannot represent a partial batch, so it reports success over missing data. Count what actually landed. (M-12)
38. **The pull path is the weaker of the two apply paths, and always will be.** Push answers a caller who checks the response; pull answers nobody. Every safeguard added to push must be added to `core/sync/apply_hooks.py` and asserted in both directions — this has now been relearned four times (M-7, M-8, M-12). (M-12)
39. **Cross-report agreement is necessary, not sufficient — reports must also agree with the LEDGER.** The P&L and the trial balance matched each other perfectly and both differed from the journal by exactly the GST collected, because both read `Invoice.total_amount`. Two views built from the same wrong source agree. Always reconcile a report against the posted entries, not against another report. (M-14)
40. **A statement that balances by construction proves nothing.** The trial balance foots because Capital is a plug, so `balanced=True` is arithmetic, not evidence — during M-2 it would have shown a clean statement for a business with 38 invoices and zero journal entries. A self-balancing report cannot be an integrity check. (M-14)
41. **A docstring's stated assumption is a fact with an expiry date.** `report_trial_balance` still says "no posted journal"; there has been a hash-chained one for months. When an architectural assumption changes, grep for the code that was written under it. (M-14)
42. **Aggregating by a nullable foreign key silently drops rows.** `/reports/outstanding` groups by `customer_id` and skips NULL, so a walk-in credit sale is owed money on no list. Any GROUP BY on a nullable column needs an explicit bucket for the nulls. (M-15, and rule 9 again)
43. **A known, unfixed defect belongs in a strict xfail, not a comment.** `xfail(strict=True)` keeps the suite green while the defect stands and turns into a failure the moment it is fixed, so the test cannot rot into a permanently-ignored red mark. (M-15)
44. **A dated repair is a repair of one day, not of a defect.** The M-16 script scoped itself to `created_at >= '2026-07-17' AND < '2026-07-18'`, so a second, earlier occurrence of the identical corruption survived it and the script still reports "0 rows". Scope a repair by the INVARIANT it restores, not by when you noticed the breakage — and re-run the audit afterwards, not the repair. (M-17)
45. **A repair script must resolve its own database from `__file__`.** A relative path means the script works from one directory and not another, and this repo has two files named `bizassist.db` — one of them empty. A repair that opens the wrong database reports "nothing to repair" and is believed. (M-17)
46. **`sonar.coverage.exclusions` is not `sonar.exclusions`.** Operational scripts should leave the coverage ratio while staying under analysis for bugs and security hotspots. Excluding them from analysis to fix a gate is how you stop scanning the code that rewrites money. (§57)
47. **Do not write tests to satisfy a coverage gate.** Importing a script's `main()` measures argparse, not money. If a class of code cannot honestly be unit-tested, exclude it from the ratio and state how it IS validated instead. (§57)
48. **A pinned toolchain is a precondition for attributing a red build.** `@master` on a scanner action means the gate can change without the code changing. (§57)
49. **Verify the write ORDER before constraining a total.** `SUM(children) == parent.total` is transiently false in every system that writes the parent first, and this one writes the header before its lines on both the command path and the sync apply. Constrain the direction the defect actually moves in — here, "never exceed" — not the equality you wish held. (N4b)
50. **A guard on a shared table must be tested against the SYNC apply, not just the happy path.** The pull applies children after their parent, one row at a time, which is indistinguishable from the corruption at row level. A guard that cannot tell them apart converts a data defect into rejected sync rows, which is worse. (N4b)
51. **Prove a guard installed; never assume DDL succeeded.** The first version of this trigger was invalid SQL and did not exist, while every functional test still passed. A test asserting the guard's PRESENCE is as necessary as the tests asserting its behaviour. (N4b)
52. **A guard proven on one table belongs on every table with the same shape.** The invoice header/lines corruption recurred on `b2b_orders` — and there it is worse, because two businesses quote the same record. Generalise the guard from a table spec rather than copying it, or the second copy drifts. (M-18)
53. **Infrastructure readiness is not implementation.** `B2BLedger` is in the sync map, the financial-conflict set, the purge path, the activity feed and a migration — and has no writer at all. Plumbing that references a table is not evidence the table is used; grep for the INSERT. (M-18)
54. **A name-reference coverage proxy cannot see HTTP-exercised code, and will understate route modules badly.** It said 6/7 untested where real line coverage was 72%. Use it to find candidates, never to report a figure. (M-18)
55. **A counter and the list it summarises must be asserted equal.** Four call sites bumped a skip counter; three recorded the row. The mismatch (`SKIPPED=1 ... rows: []`) is the only visible symptom, so assert the two agree rather than trusting every site is wired. (M-19)
56. **"Unit-tested directly" in a docstring is a claim to verify, not to trust.** `_remap_requester` said it and had zero coverage of its branch logic — on the M-1 consent fix. If a docstring asserts test coverage, add a test that fails when the claim stops being true. (M-19)
57. **Measure coverage with the tests that exercise the module, and say which run produced the number.** A module reported at 10% was at 82%; the difference was the test selection, not the code. A coverage figure without its command is not a measurement. (M-19)
58. **A migration step must roll back its own failed transaction.** On Postgres one failing statement aborts the whole transaction and every later step on that connection dies with `InFailedSqlTransaction`, turning one broken guard into a silently unguarded database — two overfill guards, six money invariants and a backfill, all lost to a single bad `ROUND`. Steps sharing a connection must fail in isolation, and the runner must guarantee it rather than trusting each step to remember. (N4b-PG, §63)
59. **The same money expression on two engines is two implementations.** `ROUND(x, 2)` is one function on SQLite and does not exist on Postgres for `double precision`. When a guard must run on both, prefer an expression that calls *no* dialect-specific function — do the arithmetic in SQL and the formatting in Python — over a portable-looking cast you still cannot execute on the other engine. (N4b-PG, §63)
60. **`commit()` on an aborted transaction rolls back, and does not raise.** Batching many DDL statements into one terminal commit means a single late failure silently discards every earlier success. Commit each unit of schema change on its own. (N4b-PG, §63)
61. **The converse of rule 33: a check that DID look must say what it looked at.** The repair script examined invoices *and* `b2b_orders` but reported "Every **invoice**'s line items reconcile" under an `(M-17)` banner, so a clean B2B result was indistinguishable from a B2B family never examined — and it was read that way. A verdict must print its scope before its conclusion. (§63.6)
62. **A clean verdict over an empty scan is not a clean verdict.** `--business 99` matched no documents and printed the same all-clear as a real one. Zero-in-scope is a distinct outcome and needs a distinct message and exit code. (§63.6)
63. **`absent` is not `0`.** Zero is a measurement; a missing table is the absence of one, and a diff must not be able to claim a quantity it could not read. Guard every figure on the table existing, report a sentinel, and refuse to compute a delta across it — a repair script that crashes on an older schema fails on exactly the installs most likely to need it. (§63.6)
64. **A tool that can only read one dialect can only make claims about one dialect.** Both money scripts called `sqlite3.connect` directly, so every integrity figure in this review was a statement about the local file — and when the cloud guard reported 33 corrupt documents, nothing in the tree could open the database to look. Diagnostic tooling must reach every environment the code runs in, or the environments it cannot reach are the ones that go unexamined. (§65)
65. **A gate with a false negative is worse than no gate.** The first portability analyser exempted any string that did not *look* like SQL, so it skipped `execute("PRAGMA foreign_key_check")` — the one line it existed to police — while reporting green. Prove a gate fails on the defect it was written for, in both directions, before trusting a pass. (§65.7)
66. **Verify inside the transaction, not after the commit.** A repair that commits and then re-checks has nothing left to do when the check comes back dirty. Run the invariant re-scan and the money diff before `COMMIT`, and roll back on any surprise — the difference is invisible next to a local `.bak` and total against a cloud database. (§65.6)
67. **A safety rail must not depend on a failure it does not control.** The `--apply` refusal originally ran after `connect()`, so against a machine without `psycopg2` the operator saw "driver not installed", installed it, re-ran the same command — and the rail had never been what stopped them. Check the refusal on the inputs, before touching anything. (§65.6)
68. **A repair's export is written to disk and pasted into tickets.** It must record a redacted connection label, never the DSN. (§65.5)

## 63. N4b-PG · 🔴 Critical (NEW) — my guard threw on the cloud, and took every other guard with it

### 63.1 My mistake, stated plainly

I wrote the N4b overfill guard in §59 and verified it on SQLite only. I told the
owner the Postgres path was **unverified**. It is now **confirmed broken**, and
it did far more damage than "one guard missing".

The 2026-07-26 22:00 Hugging Face boot log:

```
psycopg2.errors.UndefinedFunction:
    function round(double precision, integer) does not exist
```

`_install_overfill_guard` scanned for already-over-filled parents with
`ROUND(SUM(c.line_total) - (...), 2)`. Every column in that expression is
`Column(Float)` → `double precision` on Postgres, and Postgres has **no**
`round(double precision, integer)` — only the one-argument form and
`round(numeric, integer)`. SQLite's `ROUND` accepts `(real, int)` happily, so the
guard was green locally on every run and threw on its first contact with the
cloud. **Rule 51 already said to prove a guard on every dialect. I wrote the rule
and then did not follow it.**

### 63.2 The real defect was the cascade, not the ROUND

A missing guard is one problem. What actually shipped was *no guards at all*.

All of section 3 of `run_migrations_and_seed` shares **one connection**. On
Postgres a failed statement aborts the entire transaction: every subsequent
statement raises `InFailedSqlTransaction` until someone rolls back. **Not one
`except` block in `database/migration.py` rolled back** — there were zero
occurrences of `rollback` in the file. So one bad `SELECT` produced:

| Step | Outcome on cloud |
|---|---|
| `ck_invoice_line_items_no_overfill` | not installed |
| `ck_b2b_order_line_items_no_overfill` | not installed |
| all 6 N4 money invariants | not installed |
| `_migrate_session_nulls` | skipped |

The production database had none of its money guards while SQLite local had all
of them. Worse for diagnosis: each step caught its *own* `InFailedSqlTransaction`
and logged it as its own local problem, so the boot log showed four unrelated-
looking failures instead of one root cause. This is the §-recurring shape again —
every step individually correct, the defect in the seam.

### 63.3 What was changed

`backend/database/migration.py`, +149 / −31.

1. **No SQL `ROUND` in the scan at all.** `ROUND(CAST(x AS numeric), 2)` is valid
   on both dialects and was the obvious fix — I did not take it. It trades one
   assumption I cannot execute against Postgres for another, and that trade is
   what caused this finding. The difference is now computed in SQL and rounded in
   **Python**, so the query calls no rounding function on any dialect. The
   `HAVING` clause never needed rounding: `TOL` is ₹1.00, orders of magnitude
   wider than float noise.
2. **`_report_existing_overfill` split out of `_install_overfill_guard`.** The
   scan is a *diagnostic*; it shared a `try` with the DDL, so its failure also
   cost us the *prevention*. A failed scan now reports "this is not a clean
   result — it is an unknown one" (rule 33), rolls back, and the guard installs
   anyway.
3. **`_rollback_quietly(conn, where)`** — the rule-58 primitive. Called in every
   `except` on the shared connection, and on the early `return` paths where the
   already-installed probe left an open transaction.
4. **`_step(conn, fn)`** wraps all twelve section-3 steps in the runner. The
   structural guarantee: it does not matter whether a step added next year
   remembers to roll back. It also names the failing step in the log instead of
   letting four downstream `InFailedSqlTransaction` messages hide it. It does not
   re-raise — a guard that cannot install must not stop the owner billing.
5. **`_run_column_migrations` now commits each ALTER individually** and rolls back
   on failure. Postgres has transactional DDL, so batching every ALTER into one
   terminal `commit()` meant a single failure discarded all the *successful* ones
   too — and `commit()` on an aborted transaction rolls back **without raising**,
   so that loss would have been silent.
6. **`_resync_postgres_sequences` no longer swallows silently.** It was
   `except Exception: pass` around the thing that stops the next INSERT colliding
   on a primary key, with no rollback, so the first missing table aborted the
   transaction and every remaining sequence went unresynced in silence. Fail-open
   is right here; silent is not.

### 63.4 What I proved, and what I did not

`backend/tests/test_migration_step_isolation.py` — 9 tests.

The honest problem is that there is no Postgres in CI or in the authoring
sandbox, and "it passed on SQLite" is precisely the evidence that failed. So the
tests attack the two halves separately:

* **The ROUND bug** is asserted on the *generated SQL* — no two-argument `ROUND`,
  no `ROUND` at all. A query that never calls the function cannot depend on which
  dialect implements it. That is a property provable without a server, which is
  the whole reason the fix rounds in Python.
* **The cascade** is tested against a `PgLikeConn` fake that reproduces **Postgres
  abort semantics**: after any failed `execute`, every subsequent statement raises
  `InFailedSqlTransaction` until `rollback()` is called. The real migration
  functions run against it and the cascade either propagates or it does not.

**Run against the pre-fix file (`git show HEAD:...`), 8 of the 9 fail** — including
`test_failed_guard_install_does_not_poison_the_next_step`, which fails with
exactly the shipped symptom: *"the B2B guard was lost because the invoice guard
failed first"*. They are a reproduction, not a rubber stamp.

Executed evidence, post-fix:

| What | Result |
|---|---|
| `tests/test_migration_step_isolation.py` | 9 passed |
| + `test_line_item_invariant` | 33 passed |
| + `test_db_invariants`, `test_sync_migration_fixes`, `test_money_pure_functions` | 239 passed |
| `test_financial_invariants`, `test_money_reconciliation`, `test_shifts`, `test_shift_service_unit`, `test_sync_shift_and_push_hardening` | 101 passed |
| Full `run_migrations_and_seed()` on a fresh SQLite DB | 14 triggers — both overfill guards **and** all 6 N4 invariants |
| Guard behaviour | invoice guard fires; B2B guard fires on the ₹11.11 M-18 shape; 3-line build-up accepted; `LCL-OW-0027` (323 + 15 − 0.35 = 337.65) accepted |
| Existing-corruption scan | corrupted a committed row → boot logged `overfill: 1 invoices row(s) ... (ids: 9003 +300.0)` |
| Column-migration isolation | forced one ALTER to fail — the column before **and** the column after it were both added |

Commands (rule 57):

```
cd backend
CLOUD_API_URL="http://127.0.0.1:9" BIZASSIST_TEST_DATABASE_URL="sqlite:////tmp/test_X.db" \
  python -m pytest -q -p no:cacheprovider --no-header tests/test_migration_step_isolation.py
```

**NOT proved — say it out loud.** None of this executed against a real
PostgreSQL server; the sandbox has no `psycopg2` and cannot install a server. The
trigger DDL and the plpgsql function body themselves are still verified only on
the SQLite branch plus reading. **The verdict on this fix comes from the next HF
boot log**, and until that log is clean, the cloud must be assumed unguarded.
That is the same gap that produced this finding — it is narrower now (the scan
calls no dialect-specific function), but it is not closed.

### 63.5 Correction to the handover: the B2B repair was already done

The open item read *"Run the B2B repair locally: 2 orders, 4 rows, ₹1,111.11."*
Executed on a copy of `backend/bizassist.db` (rule 29 — never on the live file):

* both B2B orders reconcile to their headers **exactly**, diff `0.00`
  (`ORD-20260630-2QTE` 836.90, `ORD-20260702-J17T` 774.11, 4 lines each);
* `repair_line_items_by_invariant.py` → *"Every invoice's line items reconcile to
  its header. Nothing to do."*;
* `audit_money_integrity.py` → **clean**, all ten checks including **I (M-16)**
  and **J (M-18)** at 0.

The copy is faithful: `journal_mode=delete` and no `-wal` alongside the file, so
there are no uncopied commits. **No `--apply` run is needed locally.**

**And the ₹1,111.11 is fully accounted for — the repair was already applied.** I
first wrote that I could not prove when or by what. That was me not checking my
own document. §60 records the repair proven on a copy as `b2b_lines` 12 → 8 and
`b2b_line_value` 2,722.12 → **1,611.01**. Measured on the live file now:

| | §60 post-repair (proven on a copy) | Live `backend/bizassist.db` today |
|---|---|---|
| `b2b_lines` | 8 | **8** |
| `b2b_line_value` | 1,611.01 | **1,611.01** |

The surviving ids are `1,2,3,4` and `7,8,9,10` — exactly four rows deleted,
`5,6` from `ORD-20260630-2QTE` and `11,12` from `ORD-20260702-J17T`, which is
precisely the "4 genuine + 2" split §60 measured on each order. The live state is
the proven post-repair state to the paisa. **The `--apply` run happened; the
handover's open item was stale.**

### 63.6 The repair script's report said less than it knew — fixed

`repair_line_items_by_invariant.py` bannered itself `(M-17)` / "Remove phantom
**invoice** line items" and printed *"Every **invoice**'s line items reconcile to
its header"* — although it has driven both `SPECS` since §60. That is why §63.5
above was nearly written as "the B2B family was never checked": the output named
half of what it examined. **Rule 33's converse: a check that DID look must say
what it looked at.**

It now prints its scope before its verdict:

```
  Scanned:
      invoices         108 document(s) with a non-zero total,   178 line item(s)
      b2b_orders         2 document(s) with a non-zero total,     8 line item(s)

  All 110 document(s) above reconcile to their headers. Nothing to do.
```

Two further defects fell out of writing that, both found by running the script
rather than by reading it:

* **A clean verdict over an empty scan.** `--business 99` matched nothing and
  printed the same reassuring all-clear as a real one. It now says
  `NOTHING WAS SCANNED - 0 documents matched --business 99. This is NOT an
  all-clear.` and exits **2**, so a scripted caller cannot mistake it for success.
* **`money_snapshot` crashed on a database without the B2B mirror tables** —
  `sqlite3.OperationalError: no such table: b2b_order_line_items`, raised *before*
  a single invoice was repaired. A repair script that dies on an older schema
  fails on exactly the installs most likely to need it. Every figure is now
  guarded, an absent table reports the sentinel `TABLE ABSENT` rather than `0`
  (zero is a measurement; absent is not), and the money diff prints
  `NOT MEASURED` instead of subtracting a string.

Six tests added in `tests/test_line_item_invariant.py`. Verified by execution:
real all-clear → exit 0 with both families named; empty scope → exit 2; B2B table
dropped → `NOT SCANNED - table absent`, invoices still scanned and reported.

The `--apply` path was re-proved end-to-end on a copy after these changes: 4
phantom rows removed, `b2b_lines` 12 → 8, `b2b_line_value` 2,236.53 → 1,611.01,
**every other figure delta 0.0** (invoice value, paid, payments, journal Dr/Cr,
invoice line items, stock), invariant re-checked 0/0, `integrity_check: ok`,
`foreign_key_check: 0`.

**An unplanned proof arrived with it.** My first attempt to inject the phantom
rows into the copy failed:

```
sqlite3.IntegrityError: overfill guard: line items would exceed the document
total - refusing to append a line to a completed document
```

The N4b guard is **live on `backend/bizassist.db`** and refused the exact M-18
corruption on real data, unprompted. That is the first evidence in this review of
the guard firing outside a fixture. (The injection had to drop the trigger,
insert, and re-create it before the repair path could be tested at all.)

## 64. Coverage on the money routes — measured first, then written

Rule 54 says the name-reference proxy cannot see HTTP-exercised code. Rule 57
says a coverage figure without its command is not a measurement. Both were needed
here, and **I nearly broke rule 57 again inside this very section**: my first
measurement of `core/api/sales.py` used three plausible test files, showed
`create_sale_invoice_frontend` — the POS "Save Bill" route — at **zero**, and I
was one step from reporting that the most money-critical route in the app was
untested. It is exercised by five *other* files. Measuring the module against the
corpus that actually reaches it moved the figure from 57% to 69%. The lesson has
now cost three wrong claims; the difference this time is that it was caught
before it was written down.

### Measured (pytest-cov line coverage, not the name proxy)

| Module | Start | Now | Statements |
|---|---|---|---|
| `core/api/reports.py` | 76% | **84%** | 727 |
| `core/api/payments.py` | 65% → 70% (corpus) | **78%** | 222 |
| `core/api/sales.py` | 57% → **69%** (corpus) | 69% | 258 |

The producing commands, run from `backend/` with
`COVERAGE_FILE=/tmp/.coverage CLOUD_API_URL="http://127.0.0.1:9" BIZASSIST_TEST_DATABASE_URL="sqlite:////tmp/test_X.db"`:

```
pytest --cov=core.api.reports  tests/test_reports_agree.py tests/test_accounting.py \
       tests/test_party_ledger.py tests/test_phase4.py tests/test_journal.py tests/test_purchases.py
pytest --cov=core.api.payments tests/test_phase1b.py tests/test_accounting.py tests/test_journal.py \
       tests/test_backend.py tests/test_pending_invoices.py tests/test_money_reconciliation.py \
       tests/test_invoice_account.py
pytest --cov=core.api.sales    tests/test_sales_api.py tests/test_billing.py tests/test_cash_discount.py \
       tests/test_line_item_invariant.py tests/test_reports_agree.py tests/test_serial_line_field.py \
       tests/test_shifts.py tests/test_sync_idempotency.py
```

### The real find: `GET /invoices/{invoice_id}/account` was a true zero

Not "under-credited by the proxy" — **no test file in the corpus referenced the
path at all**, and the 55-line block was the largest untested region in
`payments.py`. It is the per-invoice money view: what the bill totalled, what has
been received, what is still owed, every receipt, every return. It is what the
owner reads out when a customer asks what they owe.

Three of its properties were defects already found and fixed *elsewhere in this
review*, living on in this route with nothing pinning them:

| Property | The defect it prevents |
|---|---|
| `paid` derived from `invoice_payments`, not `Invoice.paid_amount` | **M-7.** The column is a projection and a pulled invoice kept it at 0 while receipts existed — the customer chased for money they had paid |
| Credit notes matched on `"Credit note against <no>."` **with the trailing dot** | The route's own comment records that a bare `LIKE` matched `INV-1` inside `INV-10`/`INV-100` and showed a customer **someone else's return** |
| Invoice *and* payments both filtered by `business_id` | Cross-tenant read; "not yours" must be indistinguishable from "does not exist" (rule 19) |

`tests/test_invoice_account.py` — 16 tests, all passing.

**Mutation-tested, because a regression test that does not fail on the bug is
decoration.** Each mutation was applied to `core/api/payments.py`, the suite run,
and the file restored byte-identically (confirmed with `diff` and `git status`):

| Mutation | Result |
|---|---|
| `paid = round(inv.paid_amount or 0.0, 2)` (M-7 returns) | **4 failed** — incl. `test_paid_is_read_from_the_ledger_when_the_column_is_stale` |
| marker loses its trailing `.` | **1 failed** — `test_an_invoice_number_that_is_a_PREFIX_of_another_does_not_steal_returns` |
| payments filter loses `business_id` | **1 failed** — `test_payments_are_scoped_to_the_business_not_only_to_the_invoice` |
| restored | 16 passed |

### What is still uncovered, named rather than rounded away

* `reports.py` — `stock_ledger` (161-210, the largest single block), and the
  error/empty branches of `report_stock_movement`, `report_shift_reconciliations`,
  `report_outstanding` and `report_gstr3b`.
* `payments.py` — branches inside `record_payment` (301-315, 364-369),
  `create_expense` (480-488) and `list_credit_notes` (526-532). `record_payment`
  is a money **write** and is the next target.
* `sales.py` — `get_invoice_pdf` (309-348), `list_invoices` (462-481),
  `post_print_event` (278-292), `products_meta` (431-441), and in the POS route
  the customer-name resolution (518-520), the notes write (560-562) and the
  422/500 handlers (567-572).

**Not proved:** line coverage is not behaviour coverage. 84% of `reports.py`
executing says nothing about whether the numbers are right — that is what §52's
journal-basis work and audit checks A–J are for, and they remain the stronger
evidence.

## 65. The cloud boot verified §63 — and immediately found ₹17,416 of corruption no tool could reach

### 65.1 The fix worked

The 2026-07-27 19:29 Hugging Face boot:

```
19:29:02 [Migration] overfill guard installed on invoice_line_items (postgresql)
19:29:03 [Migration] overfill guard installed on b2b_order_line_items (postgresql)
19:29:22 [Migration] Done.
```

No `UndefinedFunction`. No `InFailedSqlTransaction`. Both guards installed on
Postgres, the cascade did not occur, and §63's "the verdict comes from the next
boot log" is now answered. The rounding fix and rule 58 are **verified on the
dialect that broke**.

### 65.2 What the guard found the moment it could see

| | Rows | Phantom line value |
|---|---|---|
| `invoices` | **31** | **₹17,416.01** across the 25 ids the log printed (6 more truncated) |
| `b2b_orders` (ids 2, 3) | 2 | +586.95 and +524.16 = **₹1,111.11** |

That is larger than M-16 (63 rows) and M-17 (₹3,298.30) combined, on production
data. COGS is `invoice_line_items × cost_price`, so 31 businesses' P&L are
reading low right now.

The B2B pair is the same two deltas as the local M-18, on different row ids —
the cloud copy of corruption already repaired locally.

### 65.3 And nothing in the tree could audit it, let alone repair it

`audit_money_integrity.py:76` and `repair_line_items_by_invariant.py:123` both
called `sqlite3.connect`. **Every integrity claim in this review was a claim
about the local SQLite file only.** The scripts could not open the database that
the guard had just reported 33 corrupt documents in.

### 65.4 `scripts/_dbcompat.py` — one layer, deliberately small

Shaped by §63 rather than by generality. It handles only what cannot be avoided:
paramstyle (`?` vs `%s`, plus psycopg2's `%`-escaping once parameters exist), row
access (`sqlite3.Row` does name AND position; psycopg2 gives tuples), catalogue
lookups, integrity checks, and **engine-enforced read-only** — `?mode=ro` on
SQLite, `default_transaction_read_only` on Postgres.

`ensure()` normalises a bare `sqlite3` connection at each public entry point, so
`find_offenders(sqlite3.connect(...))` — valid for the whole life of these
scripts, and used by the existing tests — keeps working.

### 65.5 Portability defects found and fixed, each one a §63 in waiting

| Defect | Consequence on Postgres |
|---|---|
| **14 two-argument `ROUND`s** across both scripts | `UndefinedFunction` — the exact 2026-07-26 failure, in the tools you would reach for to diagnose it |
| **`HAVING ABS(dr - cr)`** referencing SELECT aliases (audit section F) | SQLite resolves output aliases in `HAVING`; Postgres does **not** — `column "dr" does not exist` |
| **`PRAGMA integrity_check` / `foreign_key_check`** unguarded | Syntax error, which aborts the transaction and takes every later statement with it (rule 58) |
| **`sqlite_master`** | No such catalogue |
| **`?` placeholders** | Syntax error at every parameterised query |
| **Export path joined onto the DB path** | A Postgres URL has no directory; produced a path under `postgresql:/` |
| **Export recorded `args.db`** | Would have written the **DSN password** into a JSON file that gets pasted into tickets. Now `con.label`, redacted at the source |

Every `ROUND` was removed rather than replaced with `ROUND(CAST(x AS numeric), 2)`.
The cast is valid on both — and is a second assumption I still cannot execute
against Postgres. The arithmetic stays in SQL, the rounding moves to Python, and
the queries call no dialect-specific function at all (rules 51, 59).

### 65.6 Production rails on the repair

The old shape deleted, **committed**, then re-checked the invariant and printed
the money diff. If the re-check came back dirty the rows were already gone.
Survivable next to a local `.bak`; not the right shape for a cloud database
serving live businesses.

* **Verify before commit.** The invariant re-scan and the money diff now run
  INSIDE the transaction. If anything outside the line-item counts moved, or any
  document still violates the invariant, it **rolls back and exits 1** having
  changed nothing.
* **`--i-have-a-restorable-backup` is required** for `--apply` against Postgres,
  and is checked on the target string **before the connection is opened**. Ordered
  the other way round the operator's first response is "psycopg2 is not
  installed", they install it, re-run the same command, and the rail was the only
  thing standing between them and a live delete. Not a y/n prompt: this must be
  answerable in a runbook and visible in shell history.
* **`BIZASSIST_AUDIT_DATABASE_URL`, never `DATABASE_URL`.** A money script that
  silently inherits whatever the app is pointed at is one stray shell export away
  from repairing production while you believe you are on a copy.

### 65.7 Proving it with no Postgres server — and the gate's own false negative

`tests/test_dbcompat_and_sql_portability.py`, 42 tests. Two mechanisms:

1. A **fake psycopg2** reproducing its paramstyle (a `?` is a syntax error), its
   `%`-escaping rule, and its abort-on-error semantics.
2. An **AST-based SQL portability gate** over the scripts' own source (rule 20:
   where there is no engine to move the rule into, the rule goes into a
   checked-in analyser with a gate).

**The first gate I wrote had a false negative, and I found it by checking rather
than by trusting it.** It skipped any string literal that did not *look* like SQL,
on the reasoning that such a string must be prose — so
`c.execute("PRAGMA foreign_key_check")`, containing no `SELECT` or `FROM`, was
exempted. The gate was skipping the one line in the tree it was written to
police. A gate with a false negative is worse than no gate: it is a green tick
over an unchecked file.

It also had the opposite failure: a case-insensitive `round\(.*,\s*\d\)` flagged
**Python's** `round(v, 2)` — which is the fix. A gate that fires on correct code
is a gate people switch off.

Both are gone. Docstrings are now identified by the AST, and the real gate walks
`execute()` call sites, reconstructs f-string literals, and asks whether an
enclosing `if` tests the dialect — so a guarded `PRAGMA` passes and an unguarded
one fails.

**Mutation-tested, file restored byte-identically each time (`diff` verified):**

| Mutation | Result |
|---|---|
| Reintroduce `ROUND(SUM(...), 2)` — the 2026-07-26 expression | **caught** |
| Move the `PRAGMA` out of its dialect branch | **caught** |
| (control) unmodified | 42 passed |

Regression: **332 passed** across the money, migration, invariant and coverage
suites. The audit still reports **clean** on a copy of the live SQLite file, and
still **fires on injected corruption** in checks F, I and J — a clean run proves
nothing about SQL that was just rewritten. The `--apply` path was re-proved
end-to-end: 4 rows removed, `b2b_lines` 12 → 8, value 2,236.53 → 1,611.01, every
other delta 0.0, invariant re-checked 0/0 before commit.

One bug was found only by running it: `_Result` had no `rowcount`, which the
repair's `DELETE` needs. It surfaced *after* the export was written and the
transaction rolled back cleanly — which is the behaviour the verify-before-commit
rework exists for, demonstrated by accident.

### 65.8 NOT PROVED — read this before running anything against the cloud

**Nothing here has executed against a real PostgreSQL server.** There is none in
CI, and none could be installed in the sandbox this was written in (`apt` is
denied, `psycopg2` is absent). What is proved is that the SQL calls no function
Postgres lacks, that the translation layer produces what psycopg2 requires, and
that the gate catches the regression. That is strictly more than §63 had, and it
is **not** the same as a successful run.

**Runbook, in this order:**

1. `BIZASSIST_AUDIT_DATABASE_URL=postgresql://... python scripts/audit_money_integrity.py`
   — read-only, engine-enforced. This is the verification. If it completes, the
   portability work is confirmed on the dialect that matters.
2. Read the section I and J output and reconcile it against the boot log's 31 + 2.
3. Take a `pg_dump` / restorable snapshot.
4. Dry run the repair. Read every line it lists.
5. Only then `--apply --i-have-a-restorable-backup`.

Do not skip step 1. It is the step that costs nothing and is the only one that
can tell you whether step 5 is safe.

## 66. M-20 · 🔴 CRITICAL (NEW, LIVE) — the cloud defers a row, the client acks it, the sale is gone

### 66.1 Reproduced on demand, on production, today

A ₹641 sale was rung on BA-Y0DAFT to test whether the §65 journal fix worked.
It never reached the cloud. Both sides logged success.

| Where | Evidence |
|---|---|
| Local `invoices` | id 860, `LCL-OW-0028`, ₹641, 2 lines, 2026-07-27 16:37:26 UTC |
| Local `sync_queue` | row 559 `invoices INSERT`, **`synced_at` = 16:38:16, `error` NULL** |
| Local log | `22:08:16 [SYNC_WORKER] Successfully pushed 5 changes for business_id=7` |
| Cloud log | `22:08:15 sync/push: business_id=42 received 5 changes` |
| Cloud log | `22:08:16 sync/push[invoices.id=860]: deferring invoices — parent register_shifts uid=2419a393-… not in this DB yet` |
| Cloud `invoices` | **NOT PRESENT** — unfiltered search by number and uid |

### 66.2 The mechanism, read from the code

`routes/sync.py::push_changes`:

```python
if resolve_parent_fk_uids(db, model_cls, data, log_prefix=...):
    continue
```

`resolve_parent_fk_uids` returns True when a parent FK cannot be resolved in the
destination database. That is **correct and deliberate** — writing the source
database's integer id would create a wrong-row link, which is M-9, money on the
wrong customer's invoice. Its docstring states the contract:

> "The caller skips it; **it re-applies on a later sign once the parent lands**."

But the `continue` does three things, and only the first is intended:

1. skips the row — correct;
2. does **not** increment `processed_count`;
3. does **not** append to `rejected`.

`rejected.append(...)` appears exactly **once** in the file, inside the
`IntegrityError` handler. A deferred row is therefore invisible in the response:
`{"status": "success", "applied": 4, "rejected": []}` for five rows sent.

And `services/sync_worker.py` never looks:

```python
total_pushed += len(chunk_changes)     # what was SENT
...
for (it, _c) in chunk:
    it.synced_at = now                 # ALL of them, unconditionally
```

It counts what it sent, ignores the `applied` field entirely, and stamps every
row synced. **The later sync the cloud is waiting for never comes**, because the
outbox row is gone.

Two correct-in-isolation halves. The cloud defers and expects a retry; the client
acks and guarantees there won't be one. The defect lives entirely in the contract
between them — the recurring shape of this whole review, now on the one path
where the cost is a deleted sale.

### 66.3 Why M-13's fix did not catch it

M-13 taught the client to read `rejected`, and that machinery works — it logs at
ERROR and extends `_push_rejected`. It cannot help here because **a deferred row
is not a rejected row**. It is a third state that neither side names, and the
response has no field for it.

Worth stating: a rejection is not durable either. It is logged and broadcast, and
nothing else — `sync_logs` has rows for cloud outages and auth failures, none for
"the cloud refused this sale". Money that fails to sync must be queryable, not
merely loggable.

### 66.4 The upstream cause, and why it is not one lost sale

The unresolvable parent is `register_shifts` uid `2419a393-…` — the shift the
sale was rung on. It is not on the cloud.

Measured on the live local database: **shift id=9, status OPEN, uid
`2419a393-…` — the uid the cloud named — has NO `sync_queue` row at all.** The
outbox never captured it, so it cannot arrive and the deferral is permanent, not
transient.

(I first wrote that `register_shifts` had never been queued at all. That was
wrong and is corrected here: the outbox holds 8 such rows historically. The
pattern is sharper than "never":

| shift | opened | queued? |
|---|---|---|
| 1–6 | 2026-07-05 .. 07-10 | **yes** |
| 7 | 2026-07-26 18:56 | no |
| 8 | 2026-07-26 18:58 | no |
| 9 | 2026-07-26 21:50 | no |

Invoices kept queueing throughout — row 559 on 07-27 — so this is not the
hosting-mode gate, which would stop everything. `register_shifts` is in
`_SYNC_TABLES` and is NOT in `PULL_ONLY_TABLES`, so neither of those explains it
either. **Why shift enqueueing stopped on 2026-07-26 is not yet established.**
The remaining candidate in `_queue_change` is `sync_disabled_var` being set at
creation time — i.e. the shift being written inside a pull-apply context, where
suppression is correct — but that is a hypothesis and is recorded as one.)

What IS established: while that parent is absent, **every invoice rung on that
shift is deferred, acked, and lost, indefinitely.** This is not one ₹641 sale; it
is an open register whose takings silently fail to reach the cloud for as long as
the shift stays unresolvable.

The 2026-07-27 boot log shows the related M-11 state on the same business:

```
M-11: cannot enforce one-open-shift-per-operator — 1 operator(s) already hold
more than one OPEN shift: biz 42 user 42 x3
```

### 66.5 What must change

1. **The response needs a `deferred` list**, distinct from `rejected`, and the
   client must NOT stamp `synced_at` on those rows — that is the whole fix for
   the loss. A deferred row is the one case where the outbox genuinely should
   hold the row and retry.
2. **The client must compare `applied` against what it sent** and refuse to
   report success on a mismatch. Had it done so, this was a one-line discrepancy:
   sent 5, applied 4.
3. **Persist rejections and deferrals** to `sync_logs` (or a conflicts table) so
   a lost sale is a query, not a log line that rotates away.
4. **Find out why `register_shifts` was never queued.** Until that is answered,
   the parent cannot land and the retry in (1) would spin.

### 66.6 FIXED — `deferred` is now a first-class state on both sides

| Where | Change |
|---|---|
| `routes/sync.py` | the FK-deferral site appends to a new `deferred` list (entity, row_id, uid, reason) and the response returns it, plus `received` so the device can reconcile |
| `services/sync_worker.py` | reads `deferred` and **does not stamp `synced_at`** on those rows — they stay queued and re-send. THE fix; everything else is reporting |
| `services/sync_worker.py` | `total_pushed += _acked`, not `len(chunk_changes)` — it counts what LANDED, not what it sent |
| `services/sync_worker.py` | reconciles `applied + deferred + rejected` against rows sent; an unexplained shortfall **keeps** the rows (fail closed) |
| `services/sync_worker.py` | writes `push_deferred` / `push_rejected` rows to `sync_logs`, bounded at 50 |
| `services/sync_worker.py` | `_PUSH_MAX_DEFER_STREAK = 3` escalates a never-resolving deferral to CRITICAL — the rows are never discarded, the bound only makes a stuck parent loud |
| broadcast | `deferred` rides alongside `rejected` so the UI can tell three states apart |

A deferral is logged at WARNING on the cloud, not ERROR: on any one cycle it is
a legitimate ordering outcome. It becomes an error only when it never resolves,
and the **client** is the side that can count that.

**Backwards compatible in both directions.** An older client ignores the new
field and behaves exactly as before, no worse. An older cloud sends no `applied`,
so nothing can be concluded and nothing is claimed (rule 33) — the reconciliation
is skipped rather than treated as a shortfall.

### 66.7 Evidence

`tests/test_sync_deferred_rows.py` — 20 tests. The behavioural half runs the
production sequence against a fake cloud: invoice 860 deferred for a missing
`register_shifts` parent, **not acked**, still queued; parent pushed; retry
lands. Plus fail-closed on an unexplained shortfall, rejected rows still
draining (M-13 unchanged), the happy path still draining, and an older cloud.

**Mutation-tested**, both files restored byte-identically (`diff` verified):

| Mutation | Result |
|---|---|
| client acks deferred rows again (the original bug) | **caught** — `test_a_deferred_row_is_not_stamped_synced` |
| `total_pushed += len(chunk_changes)` restored | **caught** — 7 failures |
| cloud stops returning `deferred` | **caught** |
| all restored | 20 passed |

Regression: 57 passed across the sync suites, 58 across sync/journal/realtime,
354 across the money, migration and portability suites.

An existing gate — `test_no_stray_non_ascii_in_the_sync_modules`, written after
an earlier editing slip left a CJK character in this very module — rejected an
emoji in my new comment. It did its job; the comment is now ASCII.

### 66.8 What is still open

* **M-20a: why `register_shifts` stopped being enqueued on 2026-07-26.** See
  §66.9 — the enqueue path is now instrumented, and it contained a swallow that
  could produce exactly this.
* The ₹641 sale is safe locally. It will sync **once the shift does** — the fix
  makes the invoice wait rather than vanish, but it cannot conjure the parent.
* Nothing from §65 has been repaired.

### 66.9 M-20a — the enqueue path had a silent swallow around the sale's only exit

Confirmed live at 2026-07-27 23:36, first push after restarting on the fixed
build:

```
ERROR [SYNC_WORKER] UNACCOUNTED ROWS for biz=7: sent 6, cloud applied 4,
deferred 0, rejected 0 - 2 row(s) vanished with no explanation.
They are being KEPT in the outbox rather than acked.
```

A second sale, `LCL-OW-0029` (₹461), was **held instead of deleted**. Under the
previous build those six rows would have been stamped synced and that sale would
be gone exactly as the ₹641 was. `deferred 0` because the cloud half is not yet
deployed — the arithmetic reconciliation caught it on its own, which is the
belt working without the braces.

**Then reading the enqueue path for M-20a found this**, in
`database/models.py::_queue_change`:

```python
    except Exception as e:
        # Fail silently to prevent blocking main database writes
        pass
```

A bare swallow around **the single INSERT that decides whether a sale ever
leaves the device.** Failing OPEN is right — a sync bookkeeping problem must
never stop the counter taking money. Failing open and SILENT is not: when that
INSERT throws, the row is never queued, never pushed, and never missed, and the
outbox looks perfectly drained. That is precisely the observed M-20a shape.

A second swallow sat around the payload serialisation, which would queue a row
with `payload = NULL` — a promise the outbox cannot keep.

And every early `return` in the function was silent, so "this row is not in the
outbox" had no explanation anywhere.

**All of it now reports:**

| Path | Level | Says |
|---|---|---|
| INSERT fails | ERROR + traceback | names entity, id, operation, business, and that a parent row will strand its children |
| serialisation fails | ERROR + traceback | the row is being queued without a payload |
| `sync_disabled_var` set (pull-apply) | DEBUG | "this row will NEVER be pushed" — the leading M-20a hypothesis |
| not in `_SYNC_TABLES` / `PULL_ONLY` | DEBUG | routine |
| business unresolvable | **WARNING** | a syncable row is being dropped, probably a bug |
| no primary key | **WARNING** | same |

Routine declines are DEBUG because this fires on every write; the two that
indicate a defect are WARNING. Nothing raises into the caller's transaction —
fail-open is preserved and pinned by a test.

Also corrected: `check_local_sync_backlog.py` reported *"the sync WORKER is the
problem — not running, or unable to reach the cloud"* for rows that pushed
perfectly and were **held on purpose**. Opposite situations, identical count. It
now reads the error column and says the data is safe.

And the old-cloud shortfall now feeds the same escalation counter as a deferral.
Without the `deferred` list the whole chunk is held and re-sent every cycle —
safe, but a spin that would have logged the same ERROR forever without ever
escalating.

**Evidence:** 26 tests in `test_sync_deferred_rows.py`. Mutation-tested —
restoring the silent `pass` fails `test_the_sync_queue_insert_no_longer_fails_
silently`; `models.py` restored byte-identically. 82 passed across sync, billing
and shifts. Verified by execution that a hybrid-mode insert still queues (2 rows)
and that the decline reasons actually emit.

**Still not proven:** which of these paths skipped shifts 7/8/9. The
instrumentation makes the next occurrence a single grep rather than a four-hour
investigation, but it cannot explain a decline that has already happened
unlogged. Open a shift and watch for `[SYNC_QUEUE]`.

## 67. Closing out — three of my own defects, and what is genuinely fixed

### 67.1 A correction I owe: the M-20a hypothesis is WEAKER than I said

I called `sync_disabled_var` "the leading hypothesis", and after the
instrumentation caught it firing I wrote that the mechanism was "confirmed live".
The mechanism firing is confirmed. **That it explains shifts 7/8/9 is not, and
the evidence now points away from it.**

`database/db.py:175`:

```python
sync_disabled_var = contextvars.ContextVar("sync_disabled", default=False)
```

It is a **ContextVar**. A shift opened by an HTTP request runs in that request's
own context; the pull-apply sets the flag only in the scheduler thread's
context. So a shift created while a pull happens to be running would **not** be
suppressed. Every suppression actually observed in the logs was correct — rows
that had genuinely arrived from the cloud (`stock_ledger`, `inventory`,
`conflict_logs` during an apply).

For the hypothesis to hold, the shift would have to have been created *by* the
apply path itself, and there is no evidence of that.

**So M-20a's cause is unknown.** I stated more confidence than the evidence
carried, which is the specific failure this review exists to catch.

### 67.2 The symptom is covered without guessing at the cause

`services/sync_worker.find_unqueued_syncable_rows` finds syncable rows that
never reached the outbox — whatever the reason. Parents first, because a missing
parent strands its children.

**The bound is what makes it safe.** It only considers rows newer than the
OLDEST outbox entry for that business. Most of the 861 local invoices predate
hybrid mode and legitimately have no queue row; without that bound the check
would be correct and useless, trying to re-push years of history. A business
with no outbox history at all is left alone entirely, and a table that cannot be
scanned is reported rather than counted clean (rule 33).

### 67.3 Rule 58 reached the pull path

`GET /api/sync/pull` queries ~25 tables on one session and rolled back nowhere,
so on Postgres one failure aborted the transaction and every later table died
with `InFailedSqlTransaction`. Observed 2026-07-28 00:29: **one failure reported
as twenty**.

Same defect as §63, different path. Now: rollback per table, and the response
carries `failed_tables` — because `changes` having no key for a table is
indistinguishable from that table having no changes.

**The half that protects data** is on the client: it now **holds the pull
cursor** when any table failed. Advancing past tables it never received would
skip those rows permanently — M-12's shape, on the read side. Unlike a rejected
row this needs no bound: re-reading a window costs one query, and a table that
fails forever is a cloud defect to fix rather than data to skip.

### 67.4 The tests were not solid; now they are

Most M-20 tests asserted that phrases appeared in the source. That is weak in
both directions, and **both directions happened while the fix was being
written**: they failed twice on harmless comment rewording, and would have
passed on a refactor that kept the strings and broke the behaviour.

The decision was inline in a 200-line function, so string matching was the only
option available. `PushOutcome` extracts it — pure, no DB, no network — and the
worker now calls it, so the tested code is the code that runs.

`tests/test_push_outcome.py`, 25 tests, no string matching. **Mutation-verified
against every defect from this session:**

| Mutation | Result |
|---|---|
| Ack deferred rows (the original M-20) | **7 failed** |
| Add `rejected` to the sum (the `-3` bug) | **9 failed** |
| Don't fail closed on an unexplained shortfall | **2 failed** |
| Treat a missing `applied` as zero | **2 failed** |
| Remove the pull rollback | **1 failed** |
| Advance the cursor on a partial pull | **2 failed** |
| all restored | 35 passed |

Both production incidents are pinned by their exact numbers, plus an exhaustive
property check that the shortfall can never be negative.

### 67.5 My three defects in this fix, recorded

| # | Defect | How it was caught |
|---|---|---|
| 1 | Requeue inserted `payload = NULL`; I documented that the worker rebuilds it. It does not — it pushes `payload: null` and the cloud applies an empty write | The cloud rejected it on NOT NULL: `null value in column "user_id"` |
| 2 | Reconciliation added `rejected` to `applied`, which already contains it | `-3 row(s) vanished` — an impossible negative |
| 3 | Requeue's reopen path cleared `synced_at` without refreshing the payload, so a payload-less row was re-queued to be dead-lettered again, forever | Spotted in the report before it ran a second cycle |

Each was found within minutes, and none lost data — because every check now
states what it can and cannot see. That is the actual result of this session,
more than any individual fix.

A fourth, in the enqueue path rather than mine: `(R-6)`'s corrupt-payload guard
was written for `json.loads` failing and never fired for a payload that was
never there. NULL payloads are now dead-lettered the same way.

### 67.6 Status

**Fixed and verified in production:** M-20 (both halves), the §63 migration
cascade, the money tooling on Postgres, the NULL-payload guard, the enqueue
instrumentation, the pull cascade, the cursor hold.

**Recovered:** all 7 stranded rows, including the ₹641 sale. Reconcile reports
*"Every compared row is present on the cloud."*

**Open, and honestly so:**

* **M-20a's cause** — unknown, hypothesis weakened, symptom covered by the
  safety net but the hole itself is not closed.
* **§65 repairs** — ₹20,525 across 33 documents; 18 of 31 invoices still have no
  reconciling prefix and no known cause.
* **`skipped` not yet deployed** to the Space; until it is, an LWW skip reads as
  an unexplained shortfall and holds the whole chunk.
* Supabase credential rotation, three open cloud shifts, `SUBSCRIPTION_ENFORCED=0`,
  the `.gitattributes` BOM, and the test suite writing into the production log.

69. **A ContextVar-scoped flag does not span threads or requests, so it cannot explain a row missed in a different context.** `sync_disabled_var` was called the leading cause of M-20a and its firing was confirmed in the log — but every observed suppression was correct, and a shift opened by an HTTP request never sees the scheduler thread's flag. Confirming that a mechanism EXISTS is not confirming that it caused the thing you are looking at. (§67.1)
70. **When the cause resists proof, cover the symptom without inventing one.** A syncable row that never reached the outbox is detectable regardless of why, and a self-healing check bounded to rows newer than the oldest outbox entry is safe to run automatically — where the same check unbounded would try to re-push all history and be switched off. (§67.2)
71. **A rule fixed in one place is not a rule applied.** Rule 58 was written for the migration runner after N4b-PG; the pull path queried 25 tables on one session with no rollback and turned one failure into twenty. After fixing a class of defect, grep for the shape rather than the location. (§67.3)
72. **A test that greps source text passes on a refactor that breaks the behaviour and fails on a reworded comment.** Both happened here within hours. If a decision is untestable, that is a reason to extract it, not a reason to test its spelling. (§67.4)
