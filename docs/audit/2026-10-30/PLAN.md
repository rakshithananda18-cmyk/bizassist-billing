# Execution plan from the 30 October 2026 audit

Baseline: `f90ea1f`. Scope: remediate verified defects, close essential workflow boundaries and prove the original paid billing pilot. This plan authorizes no live data correction or deployment by itself; the current task delivered an audit and plan only.

## First priority

Make **business identity and posted financial truth invariant across every path**. POS, AI, B2B, Field, reports, reminder links, offline replay and repair tools must refer to the same business and the same receipts/stock/valuation facts. Then prove the journey under failures on the intended deployment topology.

Keep the current modular architecture. The audit does not justify a React/backend/desktop rewrite or new reputation/financing features. Resolve shared contracts first; independent app/sync fixes can then proceed in parallel with separate fixtures and clear ownership.

## Work packages in order

| Order | Work package / suggested owner | Issue IDs / dependency | Deliverable and exit condition |
|---|---|---|---|
| 0 | Contain current wrong-account/wrong-money behavior — billing, sync and release owners | WEB-01/02, BD-01/05/09, TS-03/04, OPS-01/02 | Session-bound queue/recipient fixes; incomplete actions disabled or safely routed; no automatic mismatch re-seal; unsafe donor repair retired; private restoration exports preserved outside source; actual-path negative regressions pass |
| 1 | Establish canonical financial/stock contracts — billing/accounting owner | BD-02/03/04/06/09/10/11/12/13, WEB-03, FT-01; agree schema/read contract before UI work | Exact bucket semantics, base-unit cost, immutable sale valuation, actual receipts/advances/refunds/supplier settlement and one signed-revenue/outstanding projection. Every UI/AI consumer uses it; reopened task reservation enforced |
| 2 | Make synchronization durable and correctly acknowledged — sync owner | TS-01–05, WEB-01; preserve package-1 money rules | Commit-safe transactional change capture, deterministic replay, tombstones, per-feed acknowledgment, durable staff/profile control outbox, revocation and account-bound retries. Failure matrix below produces no omission, foreign attribution or duplicate posting |
| 3 | Prove and complete authorization/session boundaries — security plus app owners | TS-06, BD-07/08, WEB-04–07/10 | Full-schema constrained-role auth/plan/staff/payment/sync gates; policy applied to direct commands; terminal-state graph; request/message IDs and exact-origin/channel checks; all account/route transitions reject stale state |
| 4 | Close recovery, local custody and release controls — operations/release owner | TS-07–09, CI-01, encryption/update/restore plan gaps | Complete consistent exports; fresh cloud/local restore and reconciliation; explicit key recovery/custody decision; valid readiness and secret startup; signed compatible staged releases with tested recovery; CI includes every app and shared contract |
| 5 | Finish operational UX and maintainability — frontend owners | WEB-08/09/11/12/13, DOC-01 | Honest error/stale states, server pagination/search, local QR generation, correct installer choices, passing adopted checks and one current evidence-linked tracker. Refactor risky large components only in measured slices |
| 6 | Run the original paid pilot and small trade-chain acceptance — product owner with merchant | Packages 0–5 for enabled workflows; exclusions explicit | Representative catalogue/imports and printer accepted, seven-day parallel close reconciles, staff complete routine tasks, one supplier/buyer order cycle stays private and accurate. Record paid conversion and repeat orders before adding ecosystem breadth |

These packages are dependency-based, not calendar promises. Supplier payments/refunds may be omitted only if explicitly outside the pilot's supported workflows and disabled/labeled accordingly; do not describe that pilot as complete accounting. Encryption/key recovery and remote offline erasure are product decisions with existing plans, not safe assumptions for an automatic migration.

## Package 0: concrete first patch sequence

1. **WEB-01:** bind each running flush to immutable business/backend/operator/session generation. Check before every send and acknowledgment. Abort or invalidate on logout; retain ambiguous operations in their original queue. Never retag an old operation as the next owner.
2. **WEB-02/03:** one authenticated-business payment recipient resolver and fresh server outstanding. Remove hardcoded/previous-business payee fallbacks from actionable links. Show the recipient before sharing.
3. **BD-01/09:** prevent status-only payment writes and unsupported standalone advance credit increments. Confirmed actions must call a complete idempotent money command. Human confirmation alone is insufficient.
4. **BD-05 / OPS-01:** stop automatic clearing of journal mismatch alarms and guessing invoice donors. Retain trusted hashes, mismatch observations and the sole restoration evidence; use a dry-run reconciliation report before any historical correction.
5. **TS-03/04:** unread-table failures must prevent unsafe progress even when a received row fails; delivered staff password/role changes must invalidate old cloud sessions idempotently.
6. **OPS-02:** privately preserve tracked repair evidence, exclude operational exports from source/builds, and assess published copies. Do not perform a history rewrite or discard restoration evidence as an incidental cleanup.

Exit: reproduce every original failure on the baseline, then run corrected negative tests on real production handlers/client loops. Demonstrate that intended successful checkout/collection/sync paths still work.

## Financial acceptance dataset

Use two isolated businesses, different local/cloud numeric IDs, stable BizIDs, two terminals, one staff member per business, two godowns, batched and unbatched products, and a purchase unit containing multiple base units. Fixtures must be synthetic and never saved as operational repair data in source control.

| Scenario | Required invariant |
|---|---|
| Sale, partial receipt, retry through POS and confirmed AI | Exactly one valid receipt/journal effect; common paid/outstanding across reports, AI, Field, charts and reminders; period/shift locks enforced |
| ₹100 unpaid sale, full return | Net sales 0, actual receipts 0, outstanding 0; no invented refund cash or positive AI collection |
| ₹100 invoice, ₹40 credit, no receipt | Every payment/share surface uses ₹60 outstanding and the same verified recipient |
| Paid return, refund, credit allocation | Credit obligation and actual cash refund are distinct; refund linked/idempotent; allocation does not receive cash again |
| ₹100 standalone advance sent twice with one key | One durable receipt and liability journal; credit ₹100; subsequent application does not double-count cash |
| Purchase 1 carton of 12 units for ₹120 | 12 base units at ₹10 unit cost before separately allocated charges; value ₹120; selling-price policy explicitly uses the right unit |
| B1=5, B2=7, unbatched movement −1 | Ledger and sum of exact cache buckets both equal 11; rebuild is idempotent; product/network view aggregates correctly |
| Change today's product cost | Closed prior-period sale profit and historical return reversal do not change |
| Same-state ₹100 item, CGST9/SGST9/IGST18 stored | Order and final invoice select the same tax heads and both total ₹118 under that fixture's settings |
| Hidden catalogue product submitted directly by ID | Order command denies it without exposing hidden name/price; visible items still work |
| Completed order, cancelled/reopened Field task | Forbidden terminal transitions fail; reopen rechecks locked reservation and current due; duplicate collection evidence cannot be created |
| Altered posted journal content | Verification continues to flag unresolved content mismatch; recovery preserves evidence and requires a justified correction |

For historical books, derive an impact report from an approved backup and preserve before/after facts. Never backfill sale-time cost from current prices or reconstruct missing item identities by amount similarity. Code correctness does not establish that old records are already reconciled.

## Sync protocol and failure matrix

Implement the prior ordered-feed design as a reviewed protocol, with a written explanation of snapshot/commit visibility and acknowledgments. A BIGSERIAL value allocated before commit can become visible out of order; acknowledging a high value while a lower transaction remains open can reproduce data loss. Choose and test a safe mechanism rather than relying on sequence names or wall clocks.

- Append durable changes with the business transaction; replay by a deterministic, visibility-safe cursor; make every apply idempotent and money commands authoritative.
- Keep an operation bound to its originating identity and endpoint for its whole lifetime. A 401/outage/account switch must not erase or migrate its ownership.
- Record row/control-plane deletion tombstones and explicit acknowledgments. Distinguish cloud retirement from deliberate local erasure; preserve pending bills while resolving retirement.
- Give staff/profile mutations their own protected durable retry channel; do not put password-bearing full `users` rows back into generic table replication.
- Keep explicit entity/version conflict policies. Shared catalogue fields may merge under defined rules; posted financial facts require deterministic commands/corrections.

Acceptance injections: more than a page at one timestamp; insert/update after a table SELECT; long transaction spanning a pull; mixed failed table/rejected/deferred row; loss before/after server commit; browser/process crash before acknowledgment; duplicate batch; replay after restart; logout before/during/after send; login as another business; backend switch; offline staff reset/delete then restart/reconnect; out-of-order revocation retry. Require eventual delivery, original ownership and one logical financial effect.

## Authorization, recovery and release gates

1. **Real Postgres application role:** install actual Billing and Field migrations in disposable PostgreSQL; use NOSUPERUSER NOBYPASSRLS runtime credentials. Exercise signup/login, paid-plan reads, owner/staff workflows, public-share/background/bootstrap paths and negative cross-tenant reads/writes across commit/pool reuse. Use separate maintenance/migration privileges. Do not claim success from a superuser suite or miniature policy table alone.
2. **Session lifecycles:** two tabs/apps and two merchants; repeat named-tab SSO, logout, role reset, refresh, stream completion, route change and failed fetch. No stale token/cache/bubble/detail may become the new business's state; admin actions stay disabled until verified display identity matches target.
3. **Backup/restore:** fail any incomplete export. Restore both a local export and cloud backup into fresh disposable deployments, migrate, log in, verify policy enforcement and reconcile document counts/UIDs, receipts, journals, stock buckets and Field collections. Set acceptable RPO/RTO first, measure the drill, and record key recovery plus recovery failures.
4. **Local custody/update:** resolve encryption and recovery using the existing decision record. Verify actual artifact signing and deployment compatibility; canary the packaged checkout path; rehearse interrupted update and forward/rollback recovery without losing offline bills. DPAPI-wrapped JWTs do not establish encrypted business databases or exported backups.
5. **CI matrix:** all four operational frontends plus Landing build, adopted tests/lint, actual migration chains, full-schema app-role tests, Field shared contracts, backend workflow/invariant tests, deterministic fault cases, secret scanning and an explicit dependency-advisory process. Fix stale copy assertions without weakening behavioral checks.
6. **Human/device evidence:** actual 58/80 mm/A4 output as supported, barcode/hotkeys, weak/offline counter behavior, two-device soak, phone GPS/accuracy/battery and documented background limitations. No code-only green stamp substitutes for these checks.

## Return to the original pilot

Re-use the existing master-plan playbook: watch the merchant's top 20 tasks, use representative supplier bills and opening data, validate the chosen business format, charge a pilot fee, and run in parallel for seven business days. Record unexplained stock/cash differences, checkout completion/time, failed/retried documents, staff assistance needed, OCR corrections and repeat orders. Agree numerical speed/usability thresholds with the merchant before judging the trial.

Expand the connected network only after one supplier→buyer→purchase/stock→settlement cycle is correct and private. Test adoption with three retailers and measure repeated use. Reputation/financing, extra AI autonomy, broad native rewrites and notification polish follow demonstrated demand and the integrity gates.

## Definition of completion

An issue closes only with its ID, fix commit, regression that asserts the corrected behavior, affected-surface validation, migration/recovery notes where relevant, and dated environment/results. Separate **implemented**, **automated verified**, **staging/device verified**, and **pilot accepted**. Keep deferred scope explicit. Update the lean master tracker and link this audit as the historical baseline; do not overwrite the history or turn every old plan checkbox green.
