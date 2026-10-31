# Web remediation review — 30 October 2026

Reviewed the **working tree**, including uncommitted edits, on HEAD
`6c527927cc2571cfb6a87de900bfbcd8919421d0`, against audit baseline `f5d715c`.
Package 0's committed work and the subsequent working-tree changes are both
included. No product file, existing test, original audit, index or user change
was edited, staged or reverted by this review. New probes live under `scratch/`;
review artifacts live in this directory.

**Result: 4 fixed and 9 partially fixed of WEB-01–WEB-13.** This measures the
original finding's behavior, not whether a file was changed. There are valuable
repairs and the existing suites are green, but important lifecycle conditions
still reproduce. No real business data, payment, external message or network
mutation was used in the probes.

## Findings by original ID

| ID | Status | What now works | Remaining condition / current evidence |
|---|---|---|---|
| **WEB-01** | **partial** | A generation-bound active flush stops after logout/scope change; its original records remain recoverable. Executed the original real-module scenario with assertions changed to require correct behavior: only A's first request was sent, no B-token replay occurred, and both original operations remained. | **P1 remains through late enqueue.** `usePaymentFlow.js:301`, `:306`, `:398` can finish A's ambiguous request after its component unmounts and B logs in. Its captured `enqueueOffline` calls `syncManager.queue`, which reads the **current** B store/scope at `syncManager.js:90`. Executed the real hook with a deferred network failure: A's bill appeared in B's pending queue. New flush containment then accepts its B identity stamp. Capture intent ownership before the first await and refuse/quarantine late completion under a new identity. `mutate`'s failure branch at `:79` also stamps current scope after an await; it is currently referenced by tests rather than production callers. |
| **WEB-02** | **fixed** | Both invoice-sharing implementations and party reminders use `resolvePaymentVpa` with authenticated profile/user data; no device-global or hardcoded payee is used by those sharing paths. Profile VPA wins over the old global key. Logout clears that old global key. `paymentShareRemediation.test.jsx` passed as part of the full suite. | Fixed for the original share/reminder defect. Related follow-up remains in **checkout**: `Sales.jsx:884` still falls back to `pos_upi_vpa`, guessed `phone@upi`, then `bizassist@upi`; it does not use the new helper. The helper's scoped override at `utils/share.js:25` uses integer user ID rather than stable BizID/backend identity and does not validate VPA syntax. Do not claim all collection surfaces now share one validated recipient contract. |
| **WEB-03** | **fixed** | Both share paths prefer `invoice.outstanding` over `total-paid`: `useInvoiceActions.jsx:89`, `Parties.jsx:394`. The test proves a ₹100 invoice with a ₹40 credit requests ₹60. | The tested correction uses a current row carrying authoritative outstanding. Refresh-before-share and stale-row freshness were recommended improvements, not demonstrated here. No real payment was sent. |
| **WEB-04** | **partial** | Loading now remains true until the stream ends (`Chat.jsx:323`), and message updates use an immutable generated ID (`:196`, `:210`). A safe-behavior probe confirms a second ordinary send is blocked while the first streams. | **Session-switch corruption still reproduces.** When the old target ID is absent, `Chat.jsx:211` deliberately falls back to editing the last assistant. Selecting another session at `:96` replaces history without aborting or invalidating the stream. Executed probe: B's loaded `B HISTORY` became `B HISTORYA OLD TOKEN`. Remove the fallback and bind updates/metadata to request, session and auth generation; cancel/invalidate on session change/unmount. No AbortController/session-generation guard was added. |
| **WEB-05** | **fixed** | AI now handles `storage` removal of `user`, clears its local session metadata and sets its in-memory user null (`frontend-ai/.../AuthContext.jsx:82`). Executed the old scenario with corrected assertions: the already-mounted provider signed out on the cross-window storage event. | This closes the reproduced stale-AI-token condition **when the logout notification arrives**. Cross-origin delivery still depends on the hidden AI iframe; BroadcastChannel is origin-scoped and cannot itself bridge Billing and AI on separate ports/domains. Real cross-origin iframe delivery, late handoff completion after logout, and sign-out propagation to other Billing tabs were not proven. Do not treat this focused fix as evidence of a server-wide revoke or every-tab lifecycle. |
| **WEB-06** | **partial** | URL parsing with exact loopback hostname comparison rejects `http://localhost.attacker.invalid`; an executed negative probe passes. Same repair exists in the copied Admin handler. | `frontend-ai/.../AuthContext.jsx:120` still lists only the AI origin and same-host Billing ports. It has no configured production Billing origin and no `event.source`/opener binding. All ports on localhost/127.0.0.1 are accepted. Executed a correct-behavior probe requiring a source-bound handoff: a known-origin message with `source:null` was redeemed. Named-tab production handoff remains unverified and source acceptance remains broader than the proposed design. |
| **WEB-07** | **partial** | Cache keys now include a locally stored user identifier (`useBillingProfile.js:25`, `:59`); normal logout calls the clear helper (`AuthContext.jsx:586`). This improves sequential switches between distinct IDs. | **Late-response contamination still reproduces.** `useBillingProfile.js:87` writes the cache after the clear without a generation check. `getTenantScope` prioritizes integer `id` over BizID and includes no backend. Executed A-unmount → cache-clear → B with same integer ID/different BizID → late-A-response → B mount: B received A's profile. Effect dependencies at `:99` contain only counter mode, so identity changes in a mounted consumer are not tracked. Key by stable business/operator/backend identity and invalidate old loads. Mode-switch also bypasses the normal logout helper (`AuthContext.jsx:666` onward). |
| **WEB-08** | **partial** | Stock product/godown failures and Purchase HTTP failures now set an unavailable state and provide retry. The changes are present in `Stock.jsx:218` and `Purchases.jsx:197`. | **New error-path regression:** `InvoicesListView.jsx:68` calls `logger.error` without importing or defining `logger`. The ReferenceError occurs before `setLoadError(true)`, so the intended retry state is never reached. Executed the exact current catch callback in isolation: `logger is not defined`, `loadError:false`. Stock transfer HTTP failures still map to `[]` at `Stock.jsx:230`; response-shape validation and latest-load/account-generation guards remain absent in these newly changed loaders. Fix the missing import first, then test 403/503/network/malformed-200/overlapping loads for all required resources. |
| **WEB-09** | **partial** | Shared invoice list now requests `/invoices` without the 500 cap (`InvoicesListView.jsx:60`); the unlimited default makes older invoice rows reachable by local paging. The **backend now supports `page`, `per_page` and `search`** in `core/api/sales.py:519`; root independently ran its new operational pagination/search test successfully. | The invoice frontend does not consume the new backend page/search parameters; it still downloads all invoices and pages locally. Contacts still request 500 customers/vendors (`Parties.jsx:116`), Money requests 500 (`Money.jsx:56`), checkout loads 500 customers and 1,000 products (`Sales.jsx:1006`, `:1015`). Those frontend consumers have no continuation/search requests, so rows outside their initial subsets remain undiscoverable. Backend support is implemented; complete frontend adoption and uncapped reachability are still pending. |
| **WEB-10** | **partial** | Merchant route change clears displayed state (`AdminBusinessDetail.jsx:97`). Force logout and flush cache now require displayed business ID to equal route ID (`:109`, `:124`), containing the original wrong-target action scenario. | The asynchronous loader at `:50` has no cancellation/request-generation check; an old route response can refill A's state under B's route after the reset. Required-read failures are still merely logged and initial failure renders `Business #... not found` at `:221`. Action identity guards mitigate writes, but stale diagnostics and false-not-found remain. Bind each state write to the route/auth generation and expose unavailable/retry; disable unsupported actions visibly rather than silently returning. Source trace verified; no destructive admin operation executed. |
| **WEB-11** | **fixed** | Checkout renders a local `QRCodeSVG` (`CheckoutModal.jsx:1305`) instead of the third-party QR image URL. It uses the already installed QR dependency, and the production build passes. | The obsolete `qrImageUrl` import remains unused. Other unrelated callers of the helper were not part of this issue. Recipient validity is a separate remaining checkout follow-up described under WEB-02. No real UPI app/hardware test was performed. |
| **WEB-12** | **partial** | The stale notification heading assertion was updated. All existing app tests now pass; current relaxed Admin lint passes. | Admin lint was made green largely by disabling `no-unused-vars`, `react-hooks/exhaustive-deps`, `react-refresh/only-export-components`, `react/prop-types` and entity checks in `.eslintrc.cjs:15`. This is a changed gate, not evidence the prior 282 diagnostics were repaired. In particular, disabling hook/unused checks suppresses useful logic signals. Landing build remains unverified because its local Vite dependency is missing. Root also found trailing whitespace at `useInvoiceActions.jsx:103` in `git diff --check f5d715c`. |
| **WEB-13** | **partial** | Explicit Apple Silicon and Intel links now appear when both assets exist (`bizassist-landing/src/App.jsx:106`); a named universal asset is preferred (`useLatestRelease.js:42`). | The main generic `Download for macOS` button still uses `rel.mac` (`App.jsx:70`), and `rel.mac` still prefers arm64 over x64 when no universal build exists (`useLatestRelease.js:48`). An Intel Mac can still take the primary button and receive arm64. Require an architecture choice for that ambiguous case or make the primary button a chooser with its selected architecture visible. Real release assets were not queried; Landing dependencies remain unavailable. |

## Current verification

| Check | Observed result |
|---|---|
| Billing full existing Vitest suite | **871 passed**, **112 files** |
| Admin full existing Vitest suite | **47 passed**, **3 files** |
| AI full existing Vitest suite | **13 passed**, **1 file** |
| Billing production build | Passed; main JS 545.66 kB / 150.08 kB gzip; large-chunk warning |
| Admin production build | Passed |
| AI production build | Passed |
| Landing production build | Not verified: `vite` is unavailable because local dependencies are absent; no install performed |
| Admin lint | Passed under the changed, substantially relaxed rules |
| Correct-behavior outbox replay probe | Passed: one A-token request; stop after generation switch; two original operations retained |
| New safe-behavior component probes | **3 passed / 4 failed**, seven disjoint checks: pass streaming send-lock, prefix-origin rejection and storage logout; fail late checkout enqueue, old-stream session switch, source binding and late-response cache isolation |
| Invoice catch callback execution | Confirmed new `logger is not defined` before error state is set |

The new probe failures above require **correct behavior** and therefore expose
remaining defects. They are different from the old audit tests that asserted
the presence of a bug. The original audit proof's now-failing old assertions
were not counted as regressions.

Self-contained synthetic sources and logs are archived in `web-proof/` with rerun instructions. Original working copies are in `scratch/remediation-web-tests/`,
`scratch/remediation-web-vitest.config.cjs`,
`scratch/remediation-web-probes.log`,
`scratch/remediation-web-latequeue-probe.log`,
`scratch/remediation-web-outbox-replay.cjs` and
`scratch/remediation-web-read-errors.cjs`. A synthetic review evidence summary
is in `web-status.json`. All network operations in the custom probes are mocks.
No product source or existing tests were changed to run them.

## Recommended next work

1. Finish **WEB-01** first: immutable intent ownership must cover both replay
   and asynchronous creation/enqueue. The replay repair alone cannot prevent
   a wrongly stamped operation entering the next account's queue.
2. Fix **WEB-08**'s new missing-import error and add a failure-path component
   assertion. Restore useful lint diagnostics so this kind of issue is visible.
3. Finish the generation boundaries for **WEB-04**, **WEB-06**, **WEB-07** and
   **WEB-10**. Session/route reset is incomplete while old work may refill it.
4. Complete actual record reachability (**WEB-09**) and the Mac primary chooser
   (**WEB-13**), then run the two-business/two-device end-to-end release journey.

The existing green suites show no regression in their covered cases. They do
not close these newly executed account/session lifecycle failures. Deployment,
real two-device/offline/iframe behavior, physical printers and real payment
recipient confirmation remain separate verification gates.
