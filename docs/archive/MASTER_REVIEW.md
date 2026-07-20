# MASTER REVIEW — BizAssist Billing

> Unified synthesis of **REVIEW_1** (design, bugs, gaps, admin portal) and **REVIEW_2** (AI agent plan, owner pain, moat), reconciled against `REVIEW_1_IMPLEMENTATION_NOTES.md` (batches 1–5).
> Date: 2026-07-11 (fix cycle 2: 2026-07-12). Theme: **make billing bulletproof, then make it agentic** — one robust substrate, agents that own outcomes on top of it.
> Verdict in one line: *the controllable code debt is paid; what remains is production ops + the two product gaps (payments, WhatsApp) that gate every autonomous agent.*

---

## 0. TL;DR

- **Where you are:** a sophisticated *question-answering* billing/POS with genuinely rare depth (hash-chained journal, 4-tier 0-token AI router, per-business memory, B2B graph). Overall **7.0/10** (6.3 → 6.9 → 7.0 across two fix cycles; cycle 2 hardened data integrity + tenant isolation + sync reliability).
- **What's blocking the next level:** not code quality — it's (a) production infrastructure (HF free tier, single worker, unsigned installer, no live monitoring) and (b) two missing channels: **payment links** and **WhatsApp**. Both are prerequisites for the flagship Collections Agent.
- **The move:** do the ~2-hour ops hygiene now → 2–3 weeks of dependency-free engineering hardening → build WhatsApp + payments → ship **one** agent (Collections) with a provable "₹ recovered" number → expand.
- **Honest moat:** no code moat exists. Defensibility = per-business memory compounding + outcome track record + the B2B network graph + compliance depth + cost architecture. Sell **agents-as-staff**, not "AI features."

---

## 1. Unified State Assessment

### 1.1 Ratings (post-implementation)

| Area | Before | Now | Ceiling holding it back |
|---|---|---|---|
| Code quality & hygiene | 8.5 | 8.5 | already strong; new code follows house patterns + tests |
| Domain depth (GST/accounting) | 8 | 8 | genuinely deep; under-marketed |
| Security | 6.5 | **7.5** | unsigned installer, admin 2FA now shipped, live keys in `.env` await rotation |
| Reliability / production readiness | 5 | **6.0** | cycle 2: multi-tenant data leak fixed on local **and** cloud, fail-closed test-DB guard, clean orphan purge, sync auto-disable de-fanged, tombstone + cascade. Still capped by HF free tier, no active uptime monitor, no backup drill |
| Scalability | 4.5 | 4.5 | single worker + in-memory shared state (SSE tickets, rate limits) |
| Frontend architecture | 5.5 | 5.5 | `Sales.jsx` monolith (~3,000 lines) remains |
| Distribution & operability | 5 | **6.5** | admin portal now has drill-down, sync doctor, force-logout, campaigns/offers funnel |
| **AI architecture** | — | **7/10** | excellent router/memory/loop; blocking calls + single provider + no eval harness |
| **AI product impact** | — | **4/10** | nothing runs autonomously; write-side thin; email-only reach |
| **Overall** | 6.3 | **7.0/10** | infra + the two product gaps |

Honest framing: two fix cycles can't move *infrastructure* ratings. Scalability/reliability stay capped until the HF tier, single worker and unsigned installer change. The security and operability gains are real and customer-visible.

### 1.2 What's already solid (don't rebuild)

- **Compliance spine:** hash-chained journal, period locks, GSTR-1/3B, e-invoice payload builders, RLS fail-closed. This is "tamper-evident books" — a real differentiator nobody markets.
- **AI substrate:** 4-tier router (DIRECT 0-token → CACHE → AI_SIMPLE → AI_COMPLEX/LangGraph), agent loop behind flag, BusinessFact memory distillation, deterministic intents (100% on 167-case eval), previewed/confirmed/logged actions.
- **B2B network:** connections, orders, invite codes, cross-merchant transfers — the only true network-effect asset in the codebase.
- **Admin portal:** fleet monitor, telemetry viewer, server-log tail per BizID, sync doctor (R/A/G), business drill-down, force-logout, campaigns/offers with funnel, metrics page. Solid remote-debug + growth foundation.

---

## 2. Robustness Track — make billing bulletproof

The order below is deliberate: **hygiene (hours) → dependency-free engineering (weeks) → spend-gated infra**. Agents are unsafe to run on an unmonitored single worker, so this track comes first and never fully stops.

### 2.1 Closed in the fix cycle (verified by tests)

| Item | What shipped |
|---|---|
| BUG-1 health-check 500 | missing `from sqlalchemy import text` added + regression test |
| BUG-2 gc heap-scan watcher | one bounded startup scan + cached Server ref |
| GAP-1 session model | `token_version` + `tv` JWT claim (30s cache), `/auth/refresh`, `/admin/force-logout/{id}`, `?token=` off by default, `ACCESS_TOKEN_TTL_MINUTES` knob |
| GAP-5 (half) | Sentry hook gated on `SENTRY_DSN`; `sentry-sdk` in requirements |
| GAP-6 backup | `FileBackupCard` — JSON export via data-transfer + non-destructive restore (`import?merge=true`) |
| GAP-8 (tooling) | gitleaks + pre-commit configs; parameterized RLS `set_config()` |
| B6 LLM stalls | shared `groq_client` factory (timeout+retries) across all 8 call sites; `THREADPOOL_LIMIT=80`. Finding: sync routes already run in threadpool — loop was never blocked |
| B8 admin 2FA | stdlib RFC-6238 TOTP, `/admin/2fa/*`, login OTP step, secret never echoed |
| B9 metrics | `/admin/metrics` + page: plan mix, activation funnel, churn-risk, expiring-Pro |
| §4.2 debugging | sync-doctor endpoint, business drill-down, force-logout button |
| §4.3 growth | campaigns/offers engine, in-app announcements + ack funnel + offer redemption |
| Batch 3–5 ops | shift summary printable + `/shifts/{id}/invoices`, Code128 label printing, import preview/approval gate, inventory revamp (full product form + edit + multi-barcode + scan stock-in), adjustment note REQUIRED (anti-tamper), Activity feed over audit, single-table Stock page, dual-mode bulk add |
| Batch 4 sync | BizID-mismatch refusal loop fixed (owner-row fallback by BizID) |

### 2.1b Fix cycle 2 (2026-07-12) — data integrity, tenant isolation & sync reliability (front+back tests green)

| Item | What shipped |
|---|---|
| Multi-tenant data leak (P0) | Test fixtures (`c_XXXX`/`cash_XXXX` cashiers) had polluted **both** the local dev DB (21 rows under a live business) and the **cloud Postgres tenant** (36 rows) — surfaced as phantom counters in the staff-login dropdown. Cleaned both tiers. |
| Fail-closed test-DB guard | Root cause: tests use `os.environ.setdefault("DATABASE_URL", …)`, which does **not** override an inherited/exported URL, so runs launched outside pytest/conftest wrote to real data. `database/db.py` now refuses to build an engine in any test context (`pytest` in modules · `PYTEST_CURRENT_TEST` · `BIZASSIST_TESTING=1` · `test_*` argv) unless the URL contains `test`; `conftest.py` sets the flag + a `pytest_configure` backstop. Can't recur. |
| Centralized purge | Extracted `purge_business_data(user_id, db, delete_owner, delete_staff)` as the single source of truth; `wipe_user_data` (admin) and `reclaim_local` (orphan re-key) both call it. Killed the drift where reclaim's crude `DELETE FROM {table}` loop missed child line-items and stranded staff — the phantom-counter cause. |
| Login reclaim path | On login, an "Identity mismatch" (local mirror holds the OLD BizID of a deleted-and-recreated cloud account) now auto re-keys via `reclaim_local` instead of dead-ending. Same-username re-registration is a clean re-key. |
| Account-lifecycle tombstone | New `deleted_businesses` table + `DeletedBusiness` model; a tombstone is written on admin wipe (`admin_wipe`) and reclaim re-key (`reclaim_rekey`) — "was this account deleted?" is now a recorded fact, not a guess inferred from a signup 400 / reconcile mismatch. |
| `parent_business_id` cascade | FK now `ON DELETE CASCADE` (native on fresh installs; Alembic `d1f4a2c8e6b0` applies it on Postgres; SQLite table-rebuild deliberately skipped). Defense-in-depth behind the app-level purge. FK cascade on the `business_id` data tables was **not** added — those columns aren't FKs and existing orphan data would make the constraint fail. |
| Reconciliation sweep | `scripts/reconcile_orphans.py` (read-only by default) finds staff whose owner is gone + data rows whose `business_id` has no live owner. Already surfaced 21 stray load-test rows under `business_id=5`. |
| Cloud cleanup tool | `scripts/cloud_cleanup_counters.py` — the cloud Postgres isn't directly reachable, so this authenticates over the cloud API and deletes junk cashiers (strict `^(c|cash)_[0-9a-f]{8}$`, no counter_prefix); `--report-json` snapshots. Used to clean the 36 cloud rows. |
| Realtime-sync one-way-door | `useRealtimeLeader` no longer persists `realtime_sync_global=false` after 5 SSE failures (which stranded sync as "Disconnected" forever — the SSE actually connects fine on the HF Space). Now a **session-only** pause that auto-clears on refresh / network-online / manual reconnect; modal copy updated to match. |

### 2.2 Open — do now (ops hygiene, ~2 hours, zero code)

1. **Activate Sentry** — free account → set `SENTRY_DSN` in HF secrets. Hook already in code.
2. **Uptime monitor** — UptimeRobot on `/health` → alert to email/Telegram.
3. **Rotate API keys** in `backend/.env` (Groq/OpenAI/Gemini/Claude + JWT secret); keep prod values only in HF secrets. Then `pre-commit install` so gitleaks guards every commit.
4. **Vercel access protection** on the admin project (password / allowed emails) — 5 minutes, defense in depth.
5. **Set `ADMIN_API_ENABLED=1`** locally for admin dev.

### 2.3 Open — next 2–3 weeks (engineering, no new dependencies, highest value/hour)

6. **Async LLM calls (GAP-3 part 1)** — move Groq to async client / guaranteed threadpool with hard timeouts so one slow 70B call can't pin threads. Biggest latency win available; costs nothing. *(This is also AI Phase-0 debt #1.)*
7. **Backup/restore drill** — the button ships; now document + actually run a restore once. Local-only merchants otherwise have zero disaster recovery.
8. **Business metrics polish (§4.4)** — MRR/plan mix, retention cohorts, churn-risk → wire the churn list directly to a win-back campaign (closes the loop with the campaigns engine).
9. **BUG-4 shared state** — SSE tickets + rate-limit windows are process-memory; every HF restart drops them ("live counter randomly disconnects"). Acceptable on one worker; externalize (Redis/Postgres) when you need >1.
10. **Flaky test residue (BUG-3)** — run the realtime relay/sync tests ~10× in CI to confirm determinism; those are the ones that hide real data-loss bugs.

### 2.4 Open — spend-gated infra (before paying merchants / distribution push)

11. **Move cloud off HF free tier (GAP-2)** — Railway/Fly/Render ~$5–10/mo; move uploaded logs/telemetry/feedback files to Supabase Storage/S3 (container disk can vanish on rebuild). Do before onboarding paying merchants.
12. **Code-signing cert (GAP-7)** — OV cert or Azure Trusted Signing (~$10/mo). SmartScreen "unrecognized app" is the single biggest install-funnel killer for non-technical shop owners; also secures auto-updates.
13. **Verify PyInstaller build excludes `.env`** — the desktop backend must never ship any AI key. Confirm the spec file.

### 2.5 Structural debt (opportunistic, as you touch the files)

- **Split `Sales.jsx`** (~3,000 lines) into cart state machine + checkout + settings; **split `ai_router.py`** (1,364) into route-decision / cache / execution. Every future billing bug is born in that monolith.
- Delete the dead-coded legacy add-product modal in `Stock.jsx`. *(Purge-logic drift between admin-wipe and reclaim is now resolved — centralized in `purge_business_data`.)*
- Migrate `datetime.utcnow()` → `datetime.now(timezone.utc)`; per-business staff username scheme (schema project); customer/vendor import preview parity (~1h each).
- Read-only PWA companion ("today's sales, who owes me, low stock" + AI chat) — closes 80% of the mobile gap cheaply since APIs exist.

---

## 3. AI-Agentic Automation Track — from advisor to autonomous back office

**Core principle carried from R2:** owners don't want a chat box, they want **outcomes**. Every agent owns one pain end-to-end, runs on the existing scheduler + notifier + audit infra, and is a **config** (trigger, tools, policy, caps) on one Agent Runtime — not a new microservice.

### 3.1 The pain map (what to automate, ranked by owner pain)

| # | Pain | You already have | Agent |
|---|---|---|---|
| 1 | **Collections / udhaar** (#1 daily pain — they want the *money*, not a report) | overdue/aging, party ledger, triage rule 0-60/61-180/180+ | **Collections** |
| 2 | Stock-outs & dead stock (reorder is gut-feel; capital stuck) | stock ledger + velocity | Inventory |
| 3 | GST compliance anxiety (deadlines, mismatches, notices) | GSTR-1/3B + e-invoice builders | Compliance |
| 4 | Purchase-entry drudgery (typing bills line-by-line) | `purchase_ocr.py` | Back-office autopilot |
| 5 | Margin blindness (which product/customer actually earns) | insights layer (answers only when asked) | Digest / pricing |
| 6 | Staff theft / leakage | shifts + cash movements + hash-chained journal | (audit story to market, not an agent) |

### 3.2 Phase 0 (Weeks 1–2) — harden the AI substrate

Prerequisite for *any* autonomy. Overlaps with Robustness §2.3.

1. **Async LLM calls** (shared with GAP-3) — no autonomy on a loop one call can stall.
2. **Provider abstraction + fallback** — Groq → Gemini Flash → local. Keys for 4 providers already sit in `.env`; the router doesn't use them. A Groq outage must not kill the flagship feature.
3. **Eval golden-set in CI** — 30–50 curated merchant Q → expected answer/tool-call pairs. Turns "the AI feels worse" into a diff.
4. **Write-tool safety rails** (the thing that makes autonomy shippable): every write tool gets (a) preview object, (b) explicit confirm token, (c) idempotency via the existing `X-Client-Request-Id` wall, (d) journal/audit entry, (e) per-agent daily action caps. You built exactly this for humans (ActionConfirm) — reuse it for agents.
5. Flag token-accounting drift (~4 chars/token fallback) — acceptable now, will drift billing/limits.

### 3.3 Phase 1 (Weeks 3–6) — **Collections Agent** (ship this first)

The one merchants pay for on day one. **Gated on payment links + WhatsApp (§4).**

- **Watches** invoice aging daily (scheduler exists); segments debtors by the existing triage rule.
- **Drafts** tone-aware WhatsApp/SMS reminders (gentle at 7 days, firm at 60) with invoice PDF + UPI payment link.
- **Escalation policy** set once by owner: auto-send gentle; approval-gate firm; never contact flagged parties.
- **Reconciles**: payment-link webhook marks invoice paid → agent stops the sequence → posts to journal.
- **Reports**: *"This week I recovered ₹42,300 from 9 customers."* That sentence is the ad, the retention hook, and the pricing justification.
- **Measurable**: DSO before/after. Anchor the Pro/Agents tier on it.

### 3.4 Phase 2 (Weeks 6–10) — Inventory Agent

Velocity + seasonality per SKU → reorder points; drafts POs to known suppliers (B2B graph supplies the supplier network). Dead-stock detection → clearance discount + promo message to that category's top customers. Expiry/FEFO watch (pharmacy/supermarket templates exist). Autonomy ladder: suggest → one-tap approve → auto-draft PO for repeat suppliers.

### 3.5 Phase 3 (Weeks 10–14) — Compliance Agent

Month-end pre-flight: runs existing GSTR builders, cross-checks the hash-chained journal, lists exactly what blocks filing (missing HSN, B2B buyers without GSTIN — the e-invoice builder already emits these). Files-ready export for the CA; deadline countdown via WhatsApp. Converts compliance anxiety into a monthly ritual your app owns — extremely sticky, and CAs become a distribution channel.

### 3.6 Phase 4 (Weeks 14–20) — Back-Office Autopilot

- **Purchase ingestion**: photo/PDF → `purchase_ocr` → mapped draft → one-tap commit; agent adds the review loop + learning from corrections.
  - **Vision-model OCR upgrade (planned).** Today the image path uses Tesseract (classic OCR) → text-LLM. On a real distributor bill photo (angled, glare, 26 dense multi-column rows, pen marks) Tesseract misreads digits and merges columns, so quantities/rates come out wrong — and if `pytesseract`/tesseract isn't installed the upload errors outright (`OCR dependencies not installed`). Fix: for image uploads, send the image **directly to a vision LLM** (Gemini / Claude / Groq-vision) via the new provider-fallback layer (`services/llm_provider.py`); keep Tesseract as the offline/no-key fallback. Digital PDFs already work well (pypdf → text-LLM). This is the single biggest accuracy win for photo-based bill capture and the foundation of the purchase-OCR autopilot.
- **Daily digest agent** (WhatsApp, 8pm): sales vs same-day-last-week, cash position, top action for tomorrow. Numbers from 0-token DIRECT handlers; one small LLM call for the narrative. Cheap daily touchpoint = habit.
- **Margin/pricing advisor**: flags SKUs sold below target margin; suggests price updates (owner approves).

### 3.7 Phase 5 (research, not commitment) — Cross-merchant intelligence

Anonymized, opt-in benchmarks: *"shops like yours in electronics grew 12%; your dead-stock ratio is 2× peer median."* Needs ≥300–500 active merchants to matter — where the moat and the roadmap converge.

### 3.8 Architecture guardrail

One **Agent Runtime** (extend `agent_loop.py`): scheduled trigger → context assembly (intents/DIRECT handlers, 0 tokens) → LLM planning only where judgment is needed → gated write-tools → journal + notification. Agents = configs, same philosophy as the intent registry. Resist per-agent microservices — you're one team.

---

## 4. The Critical Path — what gates everything

Two product gaps sit between today and the flagship agent. **Sequence them before Phase 1** or the Collections Agent is a demo, not a product.

| Gate | Status | Why it blocks | Options |
|---|---|---|---|
| **GAP-9 Payment collection** | ❌ open | "agent recovered ₹X" needs a payment link + auto-reconcile webhook; also a revenue line (take-rate) | Razorpay / Cashfree payment link + dynamic UPI QR on invoice |
| **GAP-10 WhatsApp channel** | ❌ open | reminders, invoices, digests, campaigns all need it; email is dead weight in Indian SMB. `notifier.py` already accepts and *ignores* WhatsApp | Meta Cloud API direct, or Gupshup / AiSensy |

The campaigns engine already **refuses to activate** email/WhatsApp campaigns until the notifier lands — the honesty guard is in place; the integration is the work.

---

## 5. Moat & Positioning (honest)

**Blunt truth:** any funded competitor can copy any *feature* in a quarter; Vyapar/Zoho will bolt LLM chat on. Code is never the moat. Optimize for "not worth copying because the value lives outside the code":

1. **Per-business memory compounding (strongest).** BusinessFacts + correction history + agent policies + party behavior ("Sharma & Sons pays 15 days late but always pays"). After 6 months, switching makes a competitor *measurably dumber* about their business. Make memory visible ("BizAssist knows 214 facts about your business"), trustworthy, and used in every agent decision.
2. **Outcome track record.** "₹ recovered" ledgers, filing streaks, stock-out-prevention counts. Copyable feature, un-copyable 18-month history.
3. **B2B network graph (the real network effect).** Every wholesaler who invites 10 retailers locks in 11 businesses. Prioritize invite loops: wholesaler onboards → free retailer seats → orders flow through you → collections/payment agents run on the *relationship*.
4. **Compliance depth as trust.** Tamper-evident books + CA-friendly exports → accountants become distribution (a CA brings 50–200 merchants).
5. **Cost architecture as margin moat.** 0-token DIRECT tier + intent promotion + caching = AI COGS a fraction of a naive GPT-wrapper's. At scale that's price room they don't have.

**Not a moat (skip):** prompt engineering, model choice, UI polish, feature count, licensing/DRM. Server-side agents are inherently un-pirateable — **keep the agent runtime cloud-side, ship only the terminal locally.**

**USP sentence:** *"The billing app that collects your money, watches your stock, and files your GST — while you run the shop."*

**Pricing:** Free = local billing forever (top of funnel). Pro = sync + AI chat. **Agents tier (new) = per-agent, framed as staff replacement** ("hire a ₹499/mo collections clerk"). The Collections Agent alone justifies ₹300–500/mo when it recovers one invoice.

---

## 6. Consolidated Sequenced Roadmap

| When | Track | Actions |
|---|---|---|
| **This week** (~2h, no code) | Robustness | Sentry DSN · UptimeRobot on `/health` · rotate keys + `pre-commit install` · Vercel admin protection · `ADMIN_API_ENABLED=1` |
| **Weeks 1–3** (engineering, no new deps) | Robustness + **AI Phase 0** | Async LLM · provider fallback · eval golden-set · write-tool rails · backup drill · metrics→campaign loop · confirm test determinism |
| **Weeks 3–8** (the gates) | Critical path | WhatsApp Business API · payment links + auto-reconcile webhook |
| **Weeks 3–6** (after gates open) | **AI Phase 1** | **Collections Agent** — ship, measure DSO, publish "₹ recovered" |
| **Weeks 6–10** | AI Phase 2 | Inventory Agent (reorder + dead stock) |
| **Weeks 10–14** | AI Phase 3 | Compliance Agent (GST pre-flight + CA export) |
| **Weeks 14–20** | AI Phase 4 | Back-office autopilot (OCR commit + daily WhatsApp digest + pricing) |
| **Spend-gated** | Robustness | Move off HF free tier · code-signing cert · Redis shared state (when >1 worker) · split monoliths · PWA |
| **≥300–500 merchants** | AI Phase 5 | Cross-merchant benchmarks |

### Sequencing logic

Hygiene is an afternoon. The dependency-free engineering makes the current product faster/safer *and* is exactly the AI Phase-0 substrate — do it once, both tracks benefit. The two gates (WhatsApp + payments) are deliberately ordered before agent work. Then ship **one** agent with a provable number before starting the next — one Collections Agent with "₹42,300 recovered" beats five half-agents. Infra spend is gated on the first paying merchant / distribution push.

---

## 7. Risk & Honesty Checklist

- **WhatsApp + payments gate the flagship** — build them before Phase 1 or ship a demo.
- **Autonomy failures are trust-fatal** — one wrong auto-reminder to a merchant's best customer costs the account. Hence Phase-0 rails + default-to-approval on anything customer-facing.
- **LLM cost discipline** — agents run daily × merchants. Keep deterministic-first: agents spend tokens on judgment, never arithmetic.
- **Don't parallelize agents** — Collections first, measure, then Inventory.
- **Infra caps are real** — single worker + in-memory state + HF free tier cap reliability/scalability regardless of feature work.
- **Solo/small-team reality** — this is ~5 months sequenced. Both tracks feed the same scheduler, notifier, and audit infra; build those shared pieces once.
- **Verify before "done"** — every code change lands with tests (pattern already established: ~845+ backend, 224+ frontend passing).

---

## 8. Open Items Ledger

**Ops (your side, no code):** rotate `.env` keys · `SENTRY_DSN` · UptimeRobot · code-signing cert · Vercel admin protection · move off HF before paying customers · label-printer hardware test (3 sizes) · **cycle 2:** re-enable "Global Real-Time Sync" in Settings once (server still holds the old persisted `false`) · **redeploy `frontend-billing`** for the session-only sync-pause fix · **`alembic upgrade head`** on cloud (tombstone + parent-cascade) · review/purge the 21 `business_id=5` orphans (`scripts/reconcile_orphans.py --purge`).

**Engineering next:** WhatsApp + payment links (gate collections) · customer/vendor import preview parity · delete dead legacy add-modal in `Stock.jsx` · per-business staff username scheme · supply-adder shift-gate decision · async LLM + provider fallback + eval set + write rails · **vision-model bill OCR** for image uploads (Gemini/Claude/Groq-vision via `llm_provider.py`, Tesseract fallback — see §3.6) · persist distributor + payment onto a purchase/GRN record from the intake panel.

**Product decisions pending:** shift summary auto-print setting · supply-adder shift exemption · Agents-tier pricing finalization.

---

## 9. Detailed Recommendations — topic-wise · agentic · phase-wise

> Trackable actions. **Priority:** P0 = now · P1 = next 2–3 wks · P2 = spend/scale-gated · P3 = opportunistic. **Effort:** S <½d · M ½–2d · L >2d. **Done when** = acceptance criteria.

### 9.A Topic-wise

**T1 · Data integrity & tenant isolation**  *(cycle-2 focus — mostly closed; finish the tail)*

| ID | Pri | Eff | Action | Done when |
|---|---|---|---|---|
| T1.1 | P0 | S | Purge the 21 `business_id=5` orphan rows the sweep found — `python scripts/reconcile_orphans.py --purge` after eyeballing them | sweep reports 0 orphans on local |
| T1.2 | P0 | S | `alembic upgrade head` on cloud (tombstone + `parent_business_id` cascade) after a cloud backup | `d1f4a2c8e6b0` at head on Postgres |
| T1.3 | P1 | S | Add a reclaim regression test: delete → re-register same username → login → assert clean re-key + 0 stale staff + tombstone row | test in `test_reclaim_local.py` green |
| T1.4 | P1 | M | Schedule `reconcile_orphans.py` (read-only) weekly (cron/CI); alert if >0 orphans | recurring job green, alert wired |
| T1.5 | P2 | L | Give `business_id` real FKs to `users(id)` (currently plain ints) → true DB-level cascade. Blocked until all orphan data cleaned | FKs added; `PRAGMA integrity_check` clean both tiers |

**T2 · Reliability / production readiness**

| ID | Pri | Eff | Action | Done when |
|---|---|---|---|---|
| T2.1 | P0 | S | Re-enable **Settings → Global Real-Time Sync** once (server still holds old persisted `false`); redeploy `frontend-billing` with the session-only sync-pause fix | badge green on web; refresh keeps it green |
| T2.2 | P0 | S | Activate Sentry (`SENTRY_DSN` in HF secrets — hook already in code) | errors landing in Sentry |
| T2.3 | P0 | S | UptimeRobot on `/health` → email/Telegram alert | monitor live, test alert received |
| T2.4 | P1 | M | Backup/restore **drill**: export via `FileBackupCard`, wipe a scratch DB, restore, diff | documented runbook + one successful restore |
| T2.5 | P1 | S | Run realtime relay / sync tests ×10 in CI to confirm determinism (BUG-3) | 10/10 green, no flake |
| T2.6 | P2 | M | Externalize SSE tickets + rate-limit windows (Redis/Postgres) — in-memory today, dropped on every HF restart (BUG-4) | survives a worker restart |

**T3 · Security**

| ID | Pri | Eff | Action | Done when |
|---|---|---|---|---|
| T3.1 | P0 | S | Rotate all `.env` keys (Groq/OpenAI/Gemini/Claude + `JWT_SECRET`); prod values only in HF secrets; then `pre-commit install` | gitleaks guards commits; old keys revoked |
| T3.2 | P1 | S | Vercel access-protection on the admin project (password / allowed emails) | admin URL not publicly loadable |
| T3.3 | P1 | S | Confirm PyInstaller spec **excludes** `.env` — desktop backend must ship no AI key | build audited, no key in bundle |
| T3.4 | P2 | M | Code-signing cert (OV / Azure Trusted Signing) — kills SmartScreen "unknown app"; secures auto-update | signed installer + updates |

**T4 · Scalability / performance**

| ID | Pri | Eff | Action | Done when |
|---|---|---|---|---|
| T4.1 | P1 | M | Async LLM calls / guaranteed threadpool + hard timeouts so one slow 70B call can't pin threads (= AI Phase-0 #1) | p95 latency stable under a slow-provider test |
| T4.2 | P2 | L | Move cloud off HF free tier (Railway/Fly/Render ~$5–10/mo); uploads/telemetry/logs → Supabase Storage/S3 | prod on durable infra before paid onboarding |
| T4.3 | P2 | M | Enable >1 worker once shared state is externalized (T2.6) | horizontal scale possible |

**T5 · Frontend architecture**

| ID | Pri | Eff | Action | Done when |
|---|---|---|---|---|
| T5.1 | P3 | L | Split `Sales.jsx` (~3,000 lines) → cart state machine / checkout / settings | no single POS file >800 lines |
| T5.2 | P3 | M | Split `ai_router.py` (1,364) → route-decision / cache / execution | modules unit-testable in isolation |
| T5.3 | P3 | S | Delete dead-coded legacy add-product modal in `Stock.jsx` | removed, build green |
| T5.4 | P2 | L | Read-only PWA companion (today's sales / who owes me / low stock + AI chat) | installable, closes ~80% of mobile gap |

**T6 · Testing & CI**

| ID | Pri | Eff | Action | Done when |
|---|---|---|---|---|
| T6.1 | P1 | S | CI job that runs the suite with a **prod-like** `DATABASE_URL` set, asserting the new fail-closed guard trips (proves T-isolation can't regress) | CI red if guard removed |
| T6.2 | P1 | S | Wire backend (~865) + frontend vitest (224+13) into CI on every PR | required check on merge |
| T6.3 | P2 | M | Coverage gate on `services/admin_service.py` purge paths + `auth.py` reclaim | ≥80% on those files |

**T7 · Admin / ops & data model**

| ID | Pri | Eff | Action | Done when |
|---|---|---|---|---|
| T7.1 | P1 | M | Business-metrics polish (§4.4): MRR/plan-mix, retention cohorts → wire churn list to a win-back campaign | churn→campaign loop live |
| T7.2 | P2 | M | Per-business staff-username scheme (schema project) — remove global-unique collision namespacing | staff names unique per business only |
| T7.3 | P3 | S | Product decisions: shift-summary auto-print · supply-adder shift-gate exemption · Agents-tier pricing | decisions recorded |

### 9.B AI-agentic — per-agent precise spec

**Phase-0 shared prerequisites (blocking for every agent):** async LLM · provider fallback (Groq→Gemini Flash→local) · eval golden-set in CI (30–50 Q→expected pairs) · write-tool rails (preview object · confirm token · idempotency via `X-Client-Request-Id` · journal/audit entry · per-agent daily caps) · one **Agent Runtime** (`agent_loop.py` extended; agents = configs, not microservices).

| Agent | Extra prereqs | Trigger | Read tools | Write tools (all gated) | Guardrails | Success metric | Autonomy ladder |
|---|---|---|---|---|---|---|---|
| **Collections** (Phase 1, ship first) | Payment link + WhatsApp (§4) | Daily aging scan | overdue/aging, party ledger, triage 0-60/61-180/180+ | send WhatsApp/SMS reminder (+PDF +UPI link); mark-paid on webhook; journal post | auto-send gentle only; approval-gate firm; never contact flagged parties; daily send cap | **DSO before/after; "₹X recovered/week"** | suggest → approve-send → auto-send gentle tier |
| **Inventory** (Phase 2) | — | Daily/weekly velocity scan | stock ledger, velocity, B2B supplier graph | draft PO to known supplier; draft clearance discount + promo to category's top customers | never auto-order; FEFO/expiry per sector template; owner approves POs | stock-out days ↓, dead-stock ratio ↓ | suggest reorder → one-tap approve → auto-draft PO for repeat suppliers |
| **Compliance** (Phase 3) | — | Month-end + deadline countdown | GSTR-1/3B builders, hash-chained journal, e-invoice validator | generate CA-ready export; deadline WhatsApp | read-mostly; never files on behalf; lists exact blockers (missing HSN, B2B buyer w/o GSTIN) | on-time filing rate; blocker list → 0 | pre-flight report → guided fixes → CA export |
| **Back-office autopilot** (Phase 4) | Vision-OCR upgrade (below) | On upload + daily 8pm | `purchase_ocr`, DIRECT 0-token handlers | commit mapped purchase draft; send daily digest | one-tap commit; learns from corrections; digest is read-only | purchase-entry time ↓; daily-open rate | OCR draft → one-tap commit → auto-commit high-confidence |
| **Digest / pricing** (Phase 4) | — | Daily 8pm | margin/insights layer | suggest price update (owner approves) | never auto-reprice | daily touchpoint habit; margin leaks flagged | flag → suggest → owner applies |
| **Cross-merchant** (Phase 5, research) | ≥300–500 merchants; opt-in | Periodic | anonymized aggregates | benchmark report only | opt-in only; anonymized | peer benchmarks shipped | report-only |

**Vision-OCR upgrade (unblocks Back-office autopilot):** image uploads currently go Tesseract→text-LLM and misread real distributor-bill photos (angled/glare/dense multi-column) — and error outright if `pytesseract` is absent. Send the image **directly to a vision LLM** (Gemini/Claude/Groq-vision via `services/llm_provider.py`), Tesseract as offline fallback. Digital PDFs already fine.

### 9.C Phase-wise consolidated plan (entry / exit criteria)

| Phase | When | Track | Entry criteria | Exit criteria (measurable) |
|---|---|---|---|---|
| **Cycle-2 tail** | this week, ~1h | Data integrity | fixes merged, tests green | T1.1–T1.2 done; sweep = 0; cloud at migration head |
| **Ops hygiene** | this week, ~2h | Reliability/Security | — | T2.2, T2.3, T3.1, T3.2 done (Sentry+uptime+keys+admin-lock) |
| **Phase 0** | Wks 1–3 | AI substrate + Robustness | ops hygiene done | async LLM + provider fallback + eval set + write rails; T2.4 backup drill; T6.1 guard-in-CI |
| **Gates** | Wks 3–8 | Critical path | Phase 0 underway | WhatsApp Business API live; payment link + auto-reconcile webhook live |
| **Phase 1 — Collections** | Wks 3–6 (after gates) | AI flagship | gates open + write rails | agent runs daily; first "₹X recovered" report; DSO measured |
| **Phase 2 — Inventory** | Wks 6–10 | AI | Phase 1 shipping a real number | reorder suggestions + PO drafts live; dead-stock flagged |
| **Phase 3 — Compliance** | Wks 10–14 | AI | GSTR builders stable | month-end pre-flight + CA export live |
| **Phase 4 — Back-office** | Wks 14–20 | AI | vision-OCR upgrade done | OCR one-tap commit + daily WhatsApp digest live |
| **Spend-gated infra** | as $ justifies | Robustness | first paying merchant / distribution push | off HF (T4.2); code-signing (T3.4); >1 worker (T4.3); monoliths split |
| **Phase 5 — Benchmarks** | ≥300–500 merchants | AI research | merchant base reached | opt-in anonymized peer benchmarks |

**Sequencing rule:** hygiene (hours) → dependency-free hardening = AI Phase-0 substrate (do once, both tracks win) → open the two gates → ship **one** agent with a provable number before starting the next. Never parallelize agents; never run autonomy on an unmonitored single worker.

---

*Sources: `REVIEW_1_DESIGN_BUGS_GAPS_ADMIN_PORTAL.md`, `REVIEW_2_AI_AGENT_PLAN_AND_MOAT.md`, `REVIEW_1_IMPLEMENTATION_NOTES.md` (batches 1–5).*

---

## 10. Fix cycle 3 (2026-07-17) — Phase-0 substrate closed

Audit finding: async LLM (`groq_client` timeouts/retries), provider fallback (`llm_provider.py`), vision-OCR, CI flaky-guard ×10, fail-closed-guard CI test (T6.1), reclaim regression (T1.3), Stock.jsx dead-modal removal (T5.3), and contact import preview parity were **already shipped** — the plan lagged the code. Newly shipped this cycle:

| Item | What shipped |
|---|---|
| **Write-tool rails** (§3.2 #4 — the autonomy gate) | `services/action_rails.py`: (1) preview mints a stateless HMAC **confirm token** binding (business, action, exact params, 10-min TTL); execute refuses without it (**428**, `ACTION_CONFIRM_REQUIRED=0` escape hatch). (2) `/action/execute` joined the **X-Client-Request-Id ReplayGuard wall** — a double-fired confirm replays, never re-executes. (3) **Per-business daily caps** per action, enforced in the dispatcher so every entry point (HTTP today, agent runtime tomorrow) hits the same wall; `ACTION_DAILY_CAP_<ACTION>`/`_DEFAULT` overrides. Chat.jsx sends token + request-id and surfaces 428/429 details. 21 tests in `test_action_rails.py`. |
| **Eval golden-set in CI** (§3.2 #3) | `tests/golden_set.jsonl` (41 curated merchant Q → expected tier+handler) + `tests/test_golden_set.py` — parametrized, deterministic (classify() only, no keys/models/network), fails CI with the exact re-routed question. Floor asserted at ≥30 cases. |
| Router fixes surfaced by the golden set | "good morning/evening" → CONVERSATIONAL (was a ~300-token AI_SIMPLE call); "low **on** stock" → DIRECT low_stock; "why did/has/does…" → AI_COMPLEX (only "why is" matched before). |
| `datetime.utcnow()` migration (§2.5) | All 99 runtime usages across 22 files → `services.dates.utc_now()` (deliberately naive-UTC — column defaults and comparisons stay consistent; aware-everywhere remains a schema project). Kills the Py3.12+ deprecation in one place. |

Verified: full backend suite (101 files, ~950 tests) + frontend-ai vitest green. Remaining Phase-0 exit criteria: backup **drill** (T2.4) — everything else in the Phase-0 row of §9.C is done.
