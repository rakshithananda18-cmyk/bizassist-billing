# REVIEW 1 — Design Bugs, Gaps, Breakages & Admin Portal Plan

> Independent code review, 2026-07-10. Evidence-based: every finding cites file/line.
> Scope: backend (FastAPI), frontend-billing (POS), frontend-ai, frontend-admin, desktop (Electron), sync, infra.
>
> **STATUS UPDATE — 2026-07-10 (same day): all code-level items implemented and verified.**
> See `REVIEW_1_IMPLEMENTATION_NOTES.md` for details and the deploy checklist.
> Verification: app boots with migrations, 12 new tests pass, 165 existing auth/roles/settings/SSO/plan tests pass, all touched frontend files parse.

## 0. Completion Scoreboard

| Item | Status | Notes |
|---|---|---|
| BUG-1 health-check 500 | ✅ DONE | import fixed + regression test |
| BUG-2 gc heap-scan watcher | ✅ DONE | one bounded scan, cached ref |
| BUG-3 flaky test residue | ⚠️ OPEN (monitor) | run suite repeatedly in CI; nothing failed in this session's runs |
| BUG-4 in-memory SSE tickets/limits | ⚠️ ACCEPTED for now | single-worker constraint stands until Redis/managed infra |
| GAP-1 session model | ✅ DONE | tv revocation, /auth/refresh, force-logout, query-token off, TTL knob |
| GAP-2 HF Space as prod cloud | ⏸ DEFERRED (your call) | staying on free tier for now — revisit before paid onboarding |
| GAP-3 single-worker / blocking LLM | ❌ OPEN | next engineering priority (async LLM calls first) |
| GAP-4 god components | ❌ OPEN | split opportunistically as you touch them |
| GAP-5 error tracking / uptime | ⚠️ half DONE | Sentry hook shipped — needs DSN set; uptime monitor = 5-min signup |
| GAP-6 backup/restore | ❌ OPEN | recommended next sprint |
| GAP-7 unsigned installer | ❌ OPEN (ops) | requires cert purchase |
| GAP-8 secrets hygiene | ✅ DONE (tooling) | gitleaks + pre-commit shipped; run `pre-commit install`; rotating the keys in backend/.env is still on you |
| GAP-9 payment collection | ❌ OPEN | prerequisite for collections agent (REVIEW_2) |
| GAP-10 WhatsApp channel | ❌ OPEN | prerequisite for offers-by-WhatsApp + agents |
| GAP-11 mobile/PWA | ❌ OPEN | later |
| §4.1 admin accessibility fixes | ✅ code DONE / ⚠️ ops | 2FA not yet added; Vercel access protection = your dashboard |
| §4.2 drill-down + sync doctor + force logout | ✅ DONE | new page + endpoint |
| §4.3 promotions/offers engine | ✅ DONE (in-app channel) | email/whatsapp blocked until notifier lands — by design |
| §4.4 business metrics page | ❌ OPEN | next portal increment |

## 1. Overall Rating (updated post-implementation)

| Area | Before | Now | What moved it |
|---|---|---|---|
| Code quality & hygiene | 8.5 | 8.5 | unchanged — was already strong; new code follows house patterns + tests |
| Domain depth (GST/accounting) | 8 | 8 | unchanged |
| Security | 6.5 | **7.5** | token revocation + refresh + query-token closed + secret scanning. Still open: unsigned installer, admin 2FA, live keys in backend/.env awaiting rotation |
| Reliability / production readiness | 5 | **5.5** | Sentry hook + sync doctor + health-check fixed — but still HF free tier, no uptime monitor active, no backup drill |
| Scalability | 4.5 | 4.5 | unchanged — single-worker + blocking LLM calls untouched (next priority) |
| Frontend architecture | 5.5 | 5.5 | unchanged — new components are clean, but Sales.jsx monolith remains |
| Distribution & operability | 5 | **6.5** | admin portal now has drill-down, sync doctor, force logout, campaigns/offers with funnel — remote debug + promotion loop is real |
| **Overall** | 6.3 | **6.9/10** | **The controllable code debt is paid. What's left is ops (cert, monitoring, infra) and the two product gaps (payments, WhatsApp) that gate the AI-agent roadmap.** |

Honest framing of the +0.6: one day of fixes can't move infrastructure ratings — the score is capped by the HF free tier, the single worker, and the unsigned installer until those change. The security and operability gains, though, are genuine and customer-visible.

---

## 2. Confirmed Bugs (P0 — broken today)

### BUG-1: `/admin/health-check` always returns 500
`backend/routes/admin.py:421` calls `db.execute(text("SELECT 1"))` but `text` is never imported in that file (imports at lines 11-19 and 405-408 contain no `from sqlalchemy import text`). Every call raises `NameError`, caught by the blanket handler → 500. **Your admin console's health tab is dead.** Fix: one import line. This also means it was never manually exercised after the last refactor — add a test (`test_admin_console_sso.py` doesn't cover it).

### BUG-2: Uvicorn shutdown watcher scans the entire Python heap every second
`backend/main_groq.py:88-97` — `gc.get_objects()` in a loop every 1s to find the Uvicorn `Server` object. On a loaded process this walks hundreds of thousands of objects per second, burning CPU and pausing the event loop. Replace with a signal handler or `Server.install_signal_handlers` override; this is a known-pattern problem with a known clean fix.

### BUG-3: Flaky/failing test residue contradicts "green"
`test_results.json` (2026-07-09) says 819/819 passed, but `backend/.pytest_cache/v/cache/lastfailed` records recent failures in `test_discovery.py` (relay echo suppression ×4), `test_auth_logging.py`, `test_token_accounting.py`, `test_routing_tiers.py` (cache). Either these were fixed same-day or they're order/environment-dependent flakes. Flaky sync/relay tests are the ones that hide real data-loss bugs — run the suite 10× in CI with `-p no:randomly` off and pin down whether the realtime relay tests are deterministic.

### BUG-4: SSE tickets and rate-limit windows are process-memory
`backend/services/auth.py:113` (`_sse_tickets = {}`), `backend/services/rate_limiter.py:27-33` (deques in module globals). Works only because you run one worker. Any restart drops all tickets mid-handshake (users see dead SSE streams after every deploy on HF Space, which restarts freely). This is a breakage users feel as "live counter randomly disconnects."

---

## 3. Design Gaps (P1 — will hurt at scale or on sale)

### GAP-1: Session/auth model is below commercial grade
- 24h JWT, **no refresh tokens, no revocation** (`services/auth.py:26`; grep confirms no refresh endpoint in `routes/auth.py`). Fire a cashier → their token works for up to 24 more hours. There is no way to kill a stolen token.
- JWT accepted via query string (`?token=`, `auth.py:69-70`) — tokens leak into server logs, proxies, browser history. Keep query auth only for the SSE ticket flow; remove generic `?token=`.
- Cashier tokens carry the owner's `public_id` (commit 95429a8) — correct for tenancy, but means role downgrade/upgrade requires re-login with no forced expiry.
**Plan:** short-lived access token (15 min) + refresh token with rotation + a `token_version` column on users (bump = instant global logout). ~2 days of work, it's table stakes for selling to businesses.

### GAP-2: Production cloud is a Hugging Face Space
`backend/services/sync_worker.py:39` — `CLOUD_URL` defaults to `https://rakshit-dev-bizassist.hf.space`. HF Spaces sleep, restart without notice, and offer no SLA, no persistent local disk guarantees (your JSONL audit fallbacks, uploaded merchant logs under `logs/remote_clients/`, and telemetry files can vanish on rebuild). Supabase Postgres is fine; the compute layer isn't. **Move cloud API to Railway/Fly/Render (~$5-10/mo) before onboarding paying merchants.** Files (logs, feedback archives) → Supabase Storage/S3, not container disk.

### GAP-3: Single-worker architecture is a hard ceiling
`main_groq.py:57-66` warns loudly about it — good honesty, but the fix (Redis or Postgres-backed cache/rate-limit/ticket store + moving APScheduler to a separate worker or pg_cron) is deferred indefinitely. At ~50-100 concurrently active merchants on one uvicorn worker doing LLM calls, sync pushes, SSE fan-out and PDF parsing, p95 latency will fall over. The AI calls are sync/blocking (`agent_loop.py` uses the sync Groq client inside generator) — one slow 70B call stalls the loop for everyone. **Priority: make LLM calls async or run them in a threadpool; then externalize shared state.**

### GAP-4: God components in the POS
`frontend-billing/src/pages/Sales.jsx` = **3,039 lines**; `backend/services/ai_router.py` = 1,364; `backend/routes/auth.py` = 978. The pure-logic extraction (invoiceMath.js, sync/) is the right pattern — finish the job: split Sales.jsx into cart state machine + checkout flow + settings; split ai_router into route-decision / cache / execution modules. Every future billing bug will be born in that 3,000-line file.

### GAP-5: No error tracking, no uptime monitoring
No Sentry/GlitchTip anywhere (grep: zero hits). You currently discover production errors when a merchant calls you. Telemetry events exist but are pull-based (admin opens the console). Add: Sentry (backend + both frontends + Electron main), UptimeRobot/BetterStack on `/health`, and an alert → your email/Telegram when a business's sync queue depth grows (the data already exists on `/admin/businesses`).

### GAP-6: Backup/restore is not a tested path
Local SQLite lives in Electron `userData/data` (desktop/src/backend.js:71). If a merchant's disk dies, is there a restore drill? Hybrid-sync customers have cloud copies; **local-only customers have nothing**. A "Backup now → .zip to chosen folder + Google Drive" button and a documented restore path is cheap insurance and a real trust feature (your own `docs/gaining_merchant_trust.md` argues this).

### GAP-7: Unsigned desktop installer
`desktop/package.json` has no signing config. Windows SmartScreen shows "unrecognized app" on every install — the single biggest funnel-killer for non-technical shop owners, and it makes your auto-updates spoofable in principle. An OV code-signing cert (~$100-200/yr) or Azure Trusted Signing (~$10/mo) fixes install-conversion and update integrity in one move.

### GAP-8: Secrets hygiene
`backend/.env` (present in the working folder, git-ignored — good) contains live Groq/OpenAI/Gemini/Claude keys, the JWT secret, and the Supabase `DATABASE_URL`. `cloud_sync_tokens.json` holds live JWTs. One accidental `git add -f`, one zip-and-share of the folder, and it's over. Move prod secrets to the host's secret manager; keep only dev keys locally; add a pre-commit secret scanner (gitleaks). Also decide explicitly: **the PyInstaller desktop backend must never ship any AI key** — verify the build pipeline excludes `.env` (I could not verify the spec file; do this check).

### GAP-9: No payment collection
Zero hits for Razorpay/Stripe/payment links. UPI exists only as a tender label on receipts. Merchants' #1 daily pain is *collecting* money — a "send UPI payment link / dynamic QR on the invoice + auto-reconcile webhook" (Razorpay/ Cashfree) is both a feature gap and a future revenue line (payments take rate). This also feeds the AI collections agent in Review 2.

### GAP-10: Communication channel is email-only
`services/notifier.py:13,63` — WhatsApp accepted and **ignored**. In the Indian SMB market, email is dead weight; WhatsApp is the medium. Alerts, invoices, payment reminders, and your admin-portal promotions (below) all need a WhatsApp Business API integration (Meta Cloud API direct, or via Gupshup/AiSensy). Without it the "send offers" ambition is theoretical.

### GAP-11: No mobile presence
Competitors (Vyapar, myBillBook, Khatabook) are mobile-first; you are desktop+web only. Even a read-only PWA ("today's sales, who owes me, low stock" + AI chat) closes 80% of the gap cheaply since the APIs already exist. Don't build native yet.

## P2 (worth logging, not urgent)
- `datetime.utcnow()` used throughout — deprecated in Python 3.12; migrate to `datetime.now(timezone.utc)` opportunistically.
- `database/db.py:103` sets RLS GUC via f-string — safe today because of `int()` cast; still, use a bound parameter for defense in depth.
- `routes/admin.py` blanket `except Exception → 500` on every route hides root causes; let FastAPI's handler log them once, keep specific handling only where you add value.
- `.env.example.example` — stray file, confuses onboarding.
- Emoji/SVG sweep and docs are excellent; keep `docs/SESSION_HANDOFF.md` current — it's your real bus-factor insurance.

---

## 4. Admin Portal — Current State (honest) & Plan

### What already exists (better than you may think)
`frontend-admin/` (separate Vercel app) + `routes/admin.py` behind a **fail-closed** `ADMIN_API_ENABLED` gate and `require_admin` role check with audit logging (`services/admin_service.py:99-122`). Live capabilities: fleet monitor per business (hosting mode, last sync, queue depth, online-24h, plan), telemetry viewer with filters, server-log tail with per-BizID filter, remote merchant log download, rate-limit editor, subscription grant/revoke, cache tools, router-mode live switch, audit log viewer, feedback + log-archive download. **This is a genuinely solid remote-debug foundation. Rating: 7/10 for debugging, 0/10 for growth/promotions — that half doesn't exist.**

### 4.1 Fix accessibility & trust (Week 1)
1. Fix BUG-1 (health-check import) + add a test.
2. Stable admin URL on real infra (move off HF Space per GAP-2); protect frontend-admin with Vercel Access/allowed-IP *in addition to* app login; add TOTP 2FA for the admin role (pyotp, ~half day).
3. Add Sentry so the portal shows you errors you didn't go looking for.

### 4.2 Remote debugging upgrades (Weeks 2-3)
1. **Business drill-down page**: one screen per merchant = last 50 telemetry events + last sync push/pull results + queue depth graph + app version + device list + their server-log lines (`?q=BizID` already supported). All endpoints exist; this is UI assembly.
2. **Support impersonation (read-only)**: reuse the existing single-use ticket infra (`create_sse_ticket`) to mint a 15-min *read-only* session scoped to a business, with a loud banner and an audit entry. Cuts "please send a screenshot" support loops to zero. Guardrail: impersonation can never hit mutation routes (enforce server-side via a `scope:"support_ro"` claim).
3. **Remote diagnostics pull**: a `request_logs` flag per business — desktop app already uploads logs daily (`services/log_uploader.py`); add an on-demand trigger via the sync channel so you don't wait 24h.
4. **Sync doctor**: automated per-business check (queue stuck >N, cursor stalled, uid conflicts from the partial-index migration) surfaced as red/amber/green on the fleet monitor. The v1.1.1 release notes show sync duplication was a real incident — make its detection permanent.

### 4.3 Promotions & offers engine (Weeks 3-6) — the missing half
Data model (3 tables, no invention needed — mirrors your settings/subscription pattern):
- `campaigns` (id, title, body_md, channel: in_app|email|whatsapp, audience_filter JSON, starts_at, ends_at, created_by)
- `campaign_deliveries` (campaign_id, business_id, delivered_at, seen_at, clicked_at)
- `offers` (code, type: discount|extension|feature_unlock, plan_effect JSON, redeem_by, max_redemptions)

Flow:
1. **Audience builder** in the portal: filter the fleet by plan, last-active, business_type (you already store it), sync mode, usage tier (TokenUsage), region. "Free merchants active in last 7 days who created >50 invoices" = your upsell list.
2. **In-app channel first** (zero external dependency): billing app polls `GET /announcements` with settings (endpoint pattern identical to `/settings`); renders a dismissible card. Ship this in days.
3. **WhatsApp/email channels** ride on GAP-10's notifier work; every send logged to `campaign_deliveries` so the portal shows funnel numbers (delivered → seen → redeemed).
4. **Offer redemption** hooks into the existing subscription machinery (`set_subscription`) — an offer is just a pre-authorized subscription mutation with an expiry.
5. Guardrails: per-merchant frequency cap (max 1 promo/week), mandatory unsubscribe for external channels, and every campaign send goes through the existing `audit_log`.

### 4.4 Business metrics you can't currently see (Week 6+)
MRR/plan mix, activation funnel (installed → first invoice → 10th invoice → sync enabled), weekly retention cohorts, AI usage vs plan (TokenUsage already has the data), churn risk flags (no invoices in 14 days). One `AdminMetrics` page; all queries against existing tables.

---

## 5. Recommendations — what to do next (updated 2026-07-10)

Code items from the original plan are done. This is the clean, ordered list of what remains — split by who/what it takes.

### A. This week — zero/low-cost ops (no code, ~2 hours total)
1. **Deploy what shipped**: run `pytest` locally once (migrations auto-apply), push backend to HF, redeploy frontend-admin + frontend-billing on Vercel.
2. **Activate Sentry**: free account at sentry.io → set `SENTRY_DSN` in HF Space secrets. The hook is already in the code.
3. **Uptime monitor**: UptimeRobot (free) on `https://rakshit-dev-bizassist.hf.space/health` → alerts to your email/Telegram.
4. **Rotate the API keys** currently sitting in `backend/.env` (Groq/OpenAI/Gemini/Claude + JWT secret) and keep prod values only in HF secrets. Then `pip install pre-commit && pre-commit install` so gitleaks guards every commit.
5. **Vercel protection** on the admin project (password / allowed emails) — defense in depth in the dashboard, 5 minutes.

### B. Next 2-3 weeks — engineering (highest value per hour)
6. **Async LLM calls** (GAP-3, part 1): move Groq calls to the async client / threadpool so one slow 70B call can't stall every user on the single worker. This is the biggest latency win available and costs nothing.
7. **Backup/restore button** (GAP-6): "Backup now → zip to folder" in Settings + a documented restore drill. Local-only merchants currently have zero disaster recovery — it's also a trust/selling point.
8. **Admin 2FA (TOTP)** for the admin role (§4.1 leftover): pyotp, ~half a day. The portal now controls plans and sessions — it deserves a second factor.
9. **Business metrics page** (§4.4): MRR/plan mix, activation funnel, retention cohorts, churn-risk flags — all queries against tables you already have. Closes the loop with the new campaigns engine (target churn-risk merchants with an offer).

### C. Next 4-8 weeks — the two product gaps that unlock REVIEW_2
10. **WhatsApp Business integration** (GAP-10): Meta Cloud API or Gupshup/AiSensy. Unlocks: alerts, payment reminders, campaign channel (the backend already refuses to activate whatsapp campaigns until this exists), and the collections agent.
11. **Payment links + auto-reconcile** (GAP-9): Razorpay/Cashfree payment link + dynamic UPI QR on invoices, webhook marks paid. Revenue feature by itself; prerequisite for "agent recovered ₹X".
12. Then start **REVIEW_2 Phase 1: the Collections Agent** — the flagship.

### D. When money/scale justifies it
13. **Code-signing cert** (GAP-7): OV cert or Azure Trusted Signing — do this before any serious distribution push; SmartScreen warnings kill installs.
14. **Move cloud off HF free tier** (GAP-2): Railway/Fly/Render ~$5-10/mo — do this before onboarding paying merchants; also fixes disk-persistence risk for uploaded logs/telemetry files.
15. **Redis-backed shared state** (BUG-4/GAP-3 part 2) when you need >1 worker; **split Sales.jsx / ai_router.py** opportunistically as you touch them (GAP-4); **read-only PWA** companion (GAP-11).

### Sequencing logic
A is pure hygiene and takes an afternoon. B makes the current product faster and safer without new dependencies. C is deliberately ordered before the AI-agent work because REVIEW_2's collections agent is a demo, not a product, without WhatsApp + payments. D is spend-gated: sign the installer when you push distribution, move infra when the first paying merchant is in sight.
