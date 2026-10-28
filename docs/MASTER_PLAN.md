# BizAssist — Master Plan (Core)

*The lean, navigable index of the plan. Last reconciled: 2026-10-28.*

> **Why this file:** the full plan is large. This is the **map**; the full plan is the **territory**. Each section here links to the authoritative detail. Keep both aligned — when a decision or status changes, edit it in the full plan and update the one-line summary here.

**Companion docs:** [Full plan → `BIZASSIST_ECOSYSTEM_MASTER_PLAN.md`](plans/BIZASSIST_ECOSYSTEM_MASTER_PLAN.md) · [Review → `PRODUCT_REVIEW.md`](plans/PRODUCT_REVIEW.md) · [Hosting modes → `HOSTING_MODE_MASTER_PLAN.md`](plans/HOSTING_MODE_MASTER_PLAN.md) · [DoD gate → `PHASE_COMPLETION_CHECKLIST.md`](plans/PHASE_COMPLETION_CHECKLIST.md)

**Current verification:** [2026-10-28 release checks](release/2026-10-28-verification.md) records commands, dated test results, build measurements, UI checks and remaining verification limits. The June review and [August platform ledger](PLATFORM_STATE_AND_PENDING_WORK_2026-08-03.md) remain historical snapshots; their open-item labels need current evidence before being treated as present defects.

---

## 1. Vision (one line)
One app for the whole B2B trade chain — distributor → wholesaler → retailer — connected by a seller-issued code, spined by **BizID**. "Share the deal, not the books." Four goals: **easy to use · secure & unbreakable · addictive · makes money.**
→ Detail: [full plan §1, §3](plans/BIZASSIST_ECOSYSTEM_MASTER_PLAN.md)

## 2. Settled decisions (don't re-litigate)
| ID | Decision | Status |
|---|---|---|
| D1 | Tenancy = `business_id`; **no** separate `tenants` table | ✅ |
| D2 | Sync conflict = **hybrid** LWW (not global LWW) | ✅ |
| D3 | Order storage = relational line items (not JSONB) | ✅ |
| D4 | `stock_ledger` = source of truth; `inventory.stock` = cached projection | ✅ |
| D5 | Cloud is source of truth; local is optional offline cache | ✅ |
| D6 | Payments = Razorpay, manual activation first | ✅ |
| D7 | E-way = compliant PDF first; API aggregator later | ✅ |
| D8 | Customer app = PWA link first, not native | ✅ |
| D9 | **BizID** = public registration ID / network addressing layer | ✅ |
| D10 | **ONE app** for the whole chain (supersedes two-app framing) | ✅ |
→ Detail + rationale: [full plan §2](plans/BIZASSIST_ECOSYSTEM_MASTER_PLAN.md)

## 3. Architecture (essentials)
- **Modular monolith:** thin `main_groq.py` entrypoint; logic in `services/` + `routes/` (AI/ops) and `core/` (billing domain, split by area); two model modules on one shared `Base`.
- **Hosting modes:** local (SQLite) · cloud (Postgres/Supabase, source of truth) · hybrid (local cache + background sync). `DATABASE_URL`-driven; `/health` reports the mode.
- **AI:** 4-tier cost-gated router, grounded, advisory-only. Money is deterministic; AI never writes the books.
- **Sync:** offline outbox + two-wall idempotency + delta-pull cursor + hybrid LWW.
→ Detail: [full plan §4–§5](plans/BIZASSIST_ECOSYSTEM_MASTER_PLAN.md) · [`HOSTING_MODE_MASTER_PLAN.md`](plans/HOSTING_MODE_MASTER_PLAN.md) · [`PRODUCT_REVIEW.md` §B1](plans/PRODUCT_REVIEW.md)

## 4. Security model (essentials)
- JWT HS256 (env secret, 24h) · bcrypt · single-use SSE tickets.
- RBAC: owner vs cashier, single-source guard, backend-authoritative.
- Tenancy in depth: app-layer `business_id` filters **+** Postgres RLS (FORCE, per-table policies). Staff JWT carries the owner's `business_id`.
- Integrity: posted double-entry journal, SHA-256 hash chain, append-only period locks, idempotency.
- **S-1 implementation closed:** fail-closed tenant policies landed in migration `9c2f4b8a1d3e`, with subsequent B2B/policy hardening. Request transactions bind tenant context locally and pooled connections reset it. Named gates: `test_rls_policies.py` and `test_rls_postgres.py`; SQLite/mock passes do not establish a live Postgres deployment result. See the [dated verification record](release/2026-10-28-verification.md).
→ Detail: [full plan §6](plans/BIZASSIST_ECOSYSTEM_MASTER_PLAN.md)

## 5. Build status (reconciled — 2026-10-28)
| Area | Status |
|---|---|
| Phase 1 — Billing/POS/Reports + accounting depth | ✅ |
| Phase 2 — Purchase + OCR | ✅ |
| Phase 3 — B2B connections (security gate passed) | ✅ |
| Phase 4 — B2B invoice sync / shared ledger (core) | ✅ |
| Hardening — Postgres RLS | ✅ fail-closed implementation and automated gates exist; live Postgres verification is recorded separately |
| R7b — Offline client sync | 🟡 built with automated coverage; real offline/reconnect and two-server depth QA remain pending unless demonstrated in the dated record |
| Hosting modes (local/cloud/hybrid switching + sync engine) | 🟡 built; live local/cloud/hybrid switching requires separate evidence |
| UI polish (print/preview, sticky bars) | Current responsive/theme checks are in the dated record; physical printer output remains a separate check |
| **Test suite green-stamp** | Use the dated verification record for each suite's command, pass/fail/skip count and scope; historical counts are not current totals |
→ Authoritative tracker: [full plan §10.0](plans/BIZASSIST_ECOSYSTEM_MASTER_PLAN.md) · current evidence: [2026-10-28 release checks](release/2026-10-28-verification.md)

## 6. USP / moats (where the company is)
**Moats (compound, hard to copy):** BizID identity spine · private ordering network · tamper-evident shared ledger · BizID reputation/trust score · data gravity (AI over the network).
**Wedges (win the demo):** AI bill parsing · in-app addressed delivery · self-configuring by business type · local-feel+cloud-truth.
**Table-stakes (never the pitch):** GST billing, stock ledger, reports, WhatsApp share.
→ Detail + marketing hierarchy: [full plan §14, §16](plans/BIZASSIST_ECOSYSTEM_MASTER_PLAN.md)

## 7. Risks (top)
Adoption of the network USP (behaviour risk #1) · single-worker scaling ceiling · live Postgres/deployment verification · GST/e-way legality (CA-validate) · live sync/restore correctness · the manual checks and environment limits stated in the dated verification record.
→ Detail: [full plan §12](plans/BIZASSIST_ECOSYSTEM_MASTER_PLAN.md) · [`PRODUCT_REVIEW.md` Part A](plans/PRODUCT_REVIEW.md)

## 8. Decisions needing sign-off
1. Reuse `invoices` vs add `sales_invoices` (rec: extend `invoices`). 2. Cloud realtime own-stack vs Supabase (rec: own first). 3. First business format to nail (pilot owner). 4. Pilot price.
→ Detail: [full plan §13](plans/BIZASSIST_ECOSYSTEM_MASTER_PLAN.md)

## 9. Cardinal rules + Definition of Done
Read [full plan §15 (cardinal rules)](plans/BIZASSIST_ECOSYSTEM_MASTER_PLAN.md) and [§16 (strength doctrine)](plans/BIZASSIST_ECOSYSTEM_MASTER_PLAN.md) before every phase. Ship nothing without the 3 gates in [`PHASE_COMPLETION_CHECKLIST.md`](plans/PHASE_COMPLETION_CHECKLIST.md): tests green + named · logging · plan updated.

---
*Maintenance rule: this file holds one-line summaries + links only. Never let it become a second source of truth — the full plan §-numbers are authoritative.*
