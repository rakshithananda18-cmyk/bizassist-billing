# All 40 remediation statuses — 30 October 2026

Reviewed HEAD `6c527927cc2571cfb6a87de900bfbcd8919421d0` plus the unstaged and new files captured in `reviewed-snapshot.json`. Detailed observations, current source locations and individual reports are linked in `issue-status.csv` and JSON. Fixed includes explicit safe containment where a feature was disabled; deployment and historical-data proof remain separate.

| ID | Original priority | Status | Verified change / remaining work |
|---|---|---|---|
| BD-01 | P1 | **fixed** | Contained by disabling the unsafe feature |
| BD-02 | P1 | **fixed** | Exact bucket queries used by ledger writes, rebuild and self-heal projection |
| BD-03 | P1 | **fixed** | Purchase price divided by conversion factor for base-unit cost and default markup |
| BD-04 | P1 | **partial** | Use per-invoice legacy fallback, actual receipt/advance semantics and return-adjusted balances; route every exposed handler/tool/prompt snapshot through the shared contract. |
| BD-05 | P1 | **fixed** | Automatic re-sealing refused for integrity mismatches |
| BD-06 | P1 | **partial** | Use the same rounded deterministic quote/invoice calculator; preserve destination policy and tax facts or explicitly requote when the destination changes. Do not lose the alternate tax rates by zeroing them before final destination is fixed. |
| BD-07 | P1 | **fixed** | Create-order applies the connection's catalogue category predicate |
| BD-08 | P2 | **fixed** | Explicit graph protects terminal states and invalid edges |
| BD-09 | P1 | **fixed** | Contained by refusing unsupported standalone advances |
| BD-10 | P1 | **partial** | Represent unknown historical snapshots as NULL/unknown, not zero; add the actual upgrade migration and an explicit reporting policy for missing history; preserve legitimate zero costs when creating returns. |
| BD-11 | P1 | **open** | Implement the missing commands/models/journals/shift integration or retain an explicit, limited product scope. Keep supplier/refund actions disabled until supported. |
| BD-12 | P2 | **fixed** | Catalogue query sums per-product stock buckets |
| BD-13 | P2 | **partial** | Add an explicit upgrade migration with duplicate diagnostics/reconciliation, install the partial unique index on existing SQLite/PostgreSQL, and verify concurrent allocation/duplicate rejection on a disposable PostgreSQL upgrade. |
| TS-01 | P1 | **partial** | Legacy timestamp worker against new server delivers [1,2] and omits tied row 3; supported mixed versions need capability negotiation/minimum version/recovery. New worker keeps timestamp fallback for old-server responses; no safe mixed-version rollout established. |
| TS-02 | P1 | **partial** | Actual endpoint skips row committed after pull with updated_at 2 seconds before acknowledged boundary. Long transactions, client-clock lag and offline source timestamps require committed-change visibility guarantees, not only wall-clock cutoffs. |
| TS-03 | P1 | **fixed** | Actual AST-extracted cursor branch tested for 9 combinations of rejected-row/unread-table counts; any unread table prevents advance |
| TS-04 | P1 | **fixed** | Actual receiver changes token_version 0 to 1, clears warmed cache, repeats same payload without another bump, clears cache/deletes valid tombstone |
| TS-05 | P1 | **partial** | Commit mutation and replication intent atomically; avoid helper commit ownership. Use valid deletion schema and persist/ack tombstones. Retry control backlog independently of normal data queue or pull setting. Enforce event identity/revision/order/idempotency at receiver and serialize concurrent delivery. Bind events to original BizID/identity generation; purge or quarantine on reset/rekey. Expose pending/error status and establish schema/migration parity. |
| TS-06 | P1 | **partial** | Anonymous login/signup/public-share/background service paths unchanged; no explicit narrow bootstrap/service privilege design. No real full-schema NOSUPERUSER NOBYPASSRLS application verification; current deployed role not inspected. |
| TS-07 | P2 | **fixed** | Actual _fetch_table injected read failure raises RuntimeError; user WP2 outer exportfailure test returns HTTP500 |
| TS-08 | P2 | **fixed** | Actual JSprobe body passes4 mocked transport cases:200 error rejected,200 healthy accepted,malformed JSON rejected,503 rejected |
| TS-09 | P2 | **fixed** | Actual subprocess authimport rejects short configured key; two valid imports retain configured key |
| WEB-01 | P1 | **partial** | Checkout started as A can fail after unmount/logout/login B and enqueue its A payload into current B scope. Executed real-hook safe-behavior probe fails. |
| WEB-02 | P1 | **fixed** | Invoice share and reminders use current profile VPA and omit pay link when missing; old global payee ignored. |
| WEB-03 | P2 | **fixed** | Both sharing paths use authoritative row outstanding, including credit adjustment; current regression test passes. |
| WEB-04 | P2 | **partial** | No stream abort/session generation. Missing-ID fallback appends old-stream tokens into newly selected history; executed probe observes B HISTORYA OLD TOKEN. |
| WEB-05 | P2 | **fixed** | Already-mounted AI provider signs out when cross-window user-removal event is delivered; safe-behavior probe passes. |
| WEB-06 | P2 | **partial** | No event.source/opener binding or configured production Billing origin; all loopback ports trusted. Safe-behavior source-binding probe fails. |
| WEB-07 | P2 | **partial** | Late A response repopulates after clear; B with same integer ID/different BizID receives A profile in executed probe. Key excludes backend; effect excludes identity; no generation. |
| WEB-08 | P2 | **partial** | Invoice-list new catch crashes before setting error; transfer HTTP failure still becomes empty list; no latest-load or identity generation guards. |
| WEB-09 | P2 | **partial** | Frontend invoice list does not consume new backend pagination/search; Contacts/Money/checkout customers remain capped500 and checkout products1000, with no continuation or server-search requests in those consumers. |
| WEB-10 | P2 | **partial** | Old async responses can refill stale merchant info; failed required reads still render not-found/no-data. No generation/cancellation/error state. |
| WEB-11 | P2 | **fixed** | Checkout QR is generated locally using installed QRCodeSVG; production build passes. |
| WEB-12 | P3 | **partial** | Lint green achieved by disabling multiple checks including hook dependencies/unused vars, not repairing all diagnostics. Landing build dependencies missing. Root diff-check finds trailing whitespace. |
| WEB-13 | P3 | **partial** | Generic primary Mac button still chooses arm64 for unknown/Intel architecture when no universal asset exists. Landing build/live assets unverified. |
| FT-01 | P1 | **fixed** | Cancelled-to-pending now resolves and locks linked invoices, repeats exclusivity/current-due checks and checks completed/cancelled run and stop state. |
| OPS-01 | P1 | **partial** | The tool still defaults to backend/bizassist.db and commits writes directly without a dry-run default, explicit approved UID mapping, pre-repair snapshot or ambiguity checks for the remaining number-based donor path. Containment is implemented; the planned operational safety contract is incomplete. |
| CI-01 | P2 | **partial** | Landing/lint/required secret scan remain absent, Field triggers still omit collection and purge/cleanup contracts, and the schema contract still uses create_all with postgres rather than proving actual migrations and full application behavior under the constrained runtime role. No live GitHub Actions run for this working tree was checked. |
| DOC-01 | P2 | **partial** | The linked baseline plan is not evidence that remediation is complete. Reconcile the other historical status boards and attach a current per-issue verification ledger. This remediation review provides that ledger; the original audit's all-open statuses and baseline-hash checks should remain historical rather than be reused as fix validation. |
| OPS-02 | P1 | **open** | Preserve restoration evidence privately, remove operational exports from future source/build contents, use any-depth ignore coverage, and assess published copies separately. Adding .gitignore does not remove tracked files. The duplicated backend-only pattern is also not the intended any-depth rule. |
