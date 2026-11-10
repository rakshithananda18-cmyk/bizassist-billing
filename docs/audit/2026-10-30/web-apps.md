# Web application audit — 30 October 2026

Scope: `frontend-billing/`, `frontend-admin/`, `frontend-ai/`, and
`bizassist-landing/` at `f90ea1f`. No product changes, real transactions, external
messages, deployment, or production database access were performed.

## Coverage and confidence

The assigned scope contains **500 tracked files**, comprising 365 Billing, 61
Admin, 61 AI and 13 Landing files. The inventory contains 128,103 text lines,
including package locks, styles and tests. Every tracked file received content
or binary-metadata screening. Higher-risk paths were read and traced across
callers; existing tests and builds were run where dependencies were available.
`web-apps-coverage.csv` distinguishes those levels. Automated screening is not a
claim that all 128,103 lines received a human-equivalent line-by-line review.

This report separates executed reproductions, source-confirmed defects, and
operational gaps. A mocked-network reproduction establishes client behavior;
it does not assert a real production incident occurred. P1 means fix before
depending on the affected money/security flow; P2 means a concrete correctness
or reliability problem; P3 means release hygiene or a lower-impact gap.

## Current issues

### WEB-01 — P1: an in-progress offline flush can submit A's bills as B

**Evidence:** `frontend-billing/src/sync/syncManager.js:50`, `:101`, `:130`,
`:141`; `frontend-billing/src/sync/outbox.js:70`; and
`frontend-billing/src/api/client.js:56`.

`flushOutbox` takes A's store and pending operations, then drains them through
the default API transport. That transport reads `billing_token` again for every
operation. Logout clears the manager's current scope but does not invalidate
the running loop. If A logs out and B logs in while the first queued request is
in flight, the next A operation is sent with B's token. A successful response
removes that operation from A's queue. Physical IndexedDB partitioning and the
existing sequential account-switch test do not protect this active loop.

**Executed proof:** run from the repository root:

```powershell
node --experimental-vm-modules docs/audit/2026-10-30/web-outbox-session-race-repro.cjs
```

The script executes the current manager, outbox, API client, token adapter and
invoice payload builder with mocked fetch and an in-memory store. It queued
`A-1` and `A-2`, paused the first request, performed logout/login scope changes,
and observed `A-2` sent with `Bearer TOKEN_B`; A's queue then contained zero
records. The captured synthetic result is
`web-outbox-session-race-result.json`. No network or database was involved.
Backend domain review confirms name-only sale lines can be valid for the
receiving business, so foreign product-ID rejection is not a sufficient guard.

**Fix:** bind a flush to immutable business, operator, backend, token and session
generation; stop before every subsequent send when the generation changes.
Abort outstanding requests on logout and quarantine unacknowledged operations
under their original scope. Regression-test switches before send, during send,
after response and during ambiguous failures.

### WEB-02 — P1: collection/share links can name the previous business's UPI recipient

**Evidence:** `frontend-billing/src/hooks/useInvoiceActions.jsx:96`;
`frontend-billing/src/pages/Parties.jsx:379` and `:405`;
`frontend-billing/src/components/sales/PosSettingsModals.jsx:158`;
`frontend-billing/src/pages/Sales.jsx:884`.

The current Profile has a business-specific `upi_vpa`, and Sales prefers it.
Invoice sharing and party reminders instead read a device-global
`pos_upi_vpa`, then fall back to hardcoded `bizassist@upi`. The POS settings form
writes the global key; logout does not clear it. After switching businesses,
an invoice/reminder bearing B's name can ask the customer to pay A's VPA.
Without a device override, sharing ignores a correctly configured Profile VPA
and substitutes the hardcoded handle. This can route collection to the wrong
recipient or generate an unusable payment link.

**Executed proof:** `web-payment-share-repro.test.jsx.txt` rendered the real
hook with B's Profile VPA and A's device key; the generated message contained
`pa=previous-business-a@bank` and omitted B's handle. One isolated test passed
while asserting this current defect. No WhatsApp message was sent.

**Fix:** resolve recipients from the authenticated business profile in one
shared helper. Scope any local override by BizID, validate it, and require
explicit recipient setup when absent. Remove guessed phone-derived and
hardcoded payees from actionable payment requests. Show the recipient before
sharing and cover account switching in tests.

### WEB-03 — P2: shared invoice requests ignore credit-note-adjusted outstanding

**Evidence:** `frontend-billing/src/hooks/useInvoiceActions.jsx:89`;
`frontend-billing/src/pages/Parties.jsx:392`; authoritative response fields at
`backend/core/api/sales.py:447` and `:463`.

The two sharing implementations calculate `total_amount - paid_amount` rather
than use the server's `outstanding`, which includes posted credits. For an
unpaid ₹100 invoice with a ₹40 credit note and `outstanding: 60`, they request
₹100. The same hook correctly uses `outstanding` in its Record payment action,
so different actions on the same row disagree.

**Executed proof:** the payment-share reproduction above passed with a ₹100
payment message for a fixture whose authoritative outstanding was ₹60.
**Fix:** use authoritative remaining balance, refresh before requesting payment,
and test partial payments, partial/full returns and zero-balance invoices.

### WEB-04 — P2: AI streaming can mix answers between questions/conversations

**Evidence:** `frontend-ai/src/pages/Chat.jsx:201`, `:207`, `:246`, and `:96`.

The send handler clears `loading` immediately after adding the streaming
placeholder, so a second question can start before the first finishes. Every
stream's `updateLast` edits the latest assistant message rather than the
message created for that request. Session selection/new-chat also does not
abort or invalidate a running stream. Tokens and final metadata can therefore
be assigned to the wrong question or the newly selected conversation.

**Executed proof:** `web-ai-stream-repro.test.jsx.txt` starts two deferred
responses, then emits a token from stream one. The real component puts that
token into the second question's assistant bubble; the first stays empty.
One isolated component test passed while asserting the defect.

**Fix:** give every request/bubble an immutable ID; update by that ID and
session generation. Hold a separate streaming lock until terminal completion,
and abort/invalidate on session or business changes and unmount. Test
overlapping completion, history races and interrupted streams.

### WEB-05 — P2: Billing sign-out does not clear an already-open AI tab

**Evidence:** `frontend-billing/src/contexts/AuthContext.jsx:582`;
`frontend-ai/src/contexts/AuthContext.jsx:23`, `:159`, and `:194`.

Billing logout loads an AI iframe that removes the AI origin's stored user.
An already-open AI window keeps its separate React `user` object and token.
The AI provider subscribes to neither storage changes nor a logout broadcast,
and authenticated requests continue to use that in-memory token. On a shared
counter, signing out of Billing can leave its financial AI dashboard signed in.

**Executed proof:** one case in `web-ai-auth-repro.test.jsx.txt` removes the
stored user, dispatches the cross-window storage event, and observes the old
owner still rendered and its token attached to the next mocked request.
**Fix:** use a validated cross-app logout message and same-origin storage or
BroadcastChannel synchronization. Clear view state and cancel requests in every
window; define whether an explicit session revoke is needed server-side.

### WEB-06 — P2: SSO accepts public origins beginning with localhost

**Evidence:** `frontend-ai/src/contexts/AuthContext.jsx:86`–`:94` and the copied
handler in `frontend-admin/src/contexts/AuthContext.jsx:87` onward.

`event.origin.startsWith('http://localhost')` accepts origins such as
`http://localhost.attacker.invalid`, not just loopback. There is no source-window
binding. A page with a window reference can present its own valid business
ticket and replace the AI tab's session, a login-CSRF/business-confusion risk.
This does not by itself steal the victim's token or grant admin privilege.
Conversely, the exact list omits a separately hosted production Billing origin,
so the configured web Billing→AI repeat-open handoff is rejected unless the
two happen to share an origin. The first URL-ticket mount can still work.

**Executed proof:** the other auth reproduction case dispatches a message from
`http://localhost.attacker.invalid` and observes a mocked ticket redemption and
session switch. Two auth cases passed in total.
**Fix:** parse and compare exact configured origins, allow loopback hostnames
only as exact host values, and bind redemption to the expected opener/channel.
Test real production origins and named-tab reuse.

### WEB-07 — P2: the business billing-profile cache survives account changes

**Evidence:** `frontend-billing/src/hooks/useBillingProfile.js:22`, `:45`,
`:60`, `:72`, and `:90`; logout at `contexts/AuthContext.jsx:582`.

The module cache is keyed only by counter mode (`''` for primary), not business,
operator or backend. Its clear helper is used by Settings/tests but not auth
logout/login. In one page lifetime, A can populate the primary profile, then B
can sign in and receive A's profile without any fetch. This affects entry mode,
customer requirements, fields and invoice defaults. In-flight old responses
can also refill the global cache after a switch.

**Evidence level:** source-confirmed trace; no dedicated execution in this audit.
**Fix:** key caches and in-flight requests by stable business/session/backend
identity, reset on identity changes, and ignore results from an old generation.

### WEB-08 — P2: required financial reads still masquerade as empty records

**Evidence:** `frontend-billing/src/pages/Stock.jsx:218`;
`frontend-billing/src/pages/Purchases.jsx:196`;
`frontend-billing/src/components/payments/InvoicesListView.jsx:61`.

Stock converts HTTP/network failures to empty product/godown/transfer arrays;
Purchase converts failed required HTTP reads to empty lists and silently
catches network errors; the shared invoice list converts failures to `[]`.
An outage or forbidden request can consequently look like an empty business.
Unlike recently repaired Home/Dashboard/Contacts, these surfaces have no
reliable required-read unavailable/retry contract. Overlapping invoice loads
also lack a latest-request guard.

This is a **revalidated open issue** from the 29-October billing-page audit,
not a newly introduced regression. Preserve it in one issue, not duplicate
backlogs. Fix with distinct loading/loaded-empty/unavailable/stale states,
retry, identity reset and request-generation protection.

### WEB-09 — P2: local paging/search hides records beyond the initial fetch cap

**Evidence:** `InvoicesListView.jsx:61`, `:130`;
`frontend-billing/src/pages/Parties.jsx:116`;
`frontend-billing/src/pages/Money.jsx:56`;
`frontend-billing/src/pages/Sales.jsx:1006` and `:1015`.

The shared invoice list retrieves at most 500 records, then filters and pages
that subset in groups of 25. Backend `core/api/sales.py:548` really applies the
limit. Contacts/Money and the checkout customer catalogue also request 500;
Sales loads a capped product catalogue. Records outside the fetched subset
cannot be discovered through client-side filters or additional visual pages.
This is another independently revalidated 29-October open item.

Fix server pagination/search and true counts. Use >500 invoices/customers and
>1,000 products as acceptance fixtures; do not treat a visible local pager as
proof the entire dataset is reachable.

### WEB-10 — P2: admin merchant detail retains stale identity during route/fetch failures

**Evidence:** `frontend-admin/src/pages/admin/AdminBusinessDetail.jsx:50`,
`:59`, `:70`, `:97`, `:104`, and `:153`.

The loader does not reset the prior business/detail state on `id` changes,
guard late responses, or expose required-read errors. `business` changes only
after a successful directory response. Navigate between merchant IDs in the
same mounted route, or let requests resolve out of order, and A's name/data
can remain visible while mutation handlers use current route ID B. The force
logout confirmation interpolates the stale name but submits to B's ID. The
recent Admin directory/dashboard load-state tests do not cover this detail
route. Initial read failure can also look like missing/default information.

**Evidence level:** source-confirmed trace; no destructive admin action run.
**Fix:** clear or key all state by route/session identity, cancel/version loads,
show required-read failure, and disable mutations until the displayed verified
business ID equals the route ID.

### WEB-11 — P2: checkout UPI QR depends on a third-party network service

**Evidence:** `frontend-billing/src/utils/share.js:35` and
`frontend-billing/src/components/sales/CheckoutModal.jsx:1304`.

Checkout builds an `<img>` pointing to `api.qrserver.com`, carrying the payment
URI, merchant identity and amount in its URL. With that service unavailable or
the counter offline, the locally computable payment QR does not render. This
adds an unnecessary external dependency to an offline-first counter and sends
payment metadata outside the application's normal backend boundary.
`qrcode.react` is already a dependency in this app.

**Fix:** render the URI locally using the existing QR library; show a recipient
setup/error state when the VPA is absent. This is a code/design observation,
not a claim that the third-party service was breached or unavailable today.

### WEB-12 — P3: current release checks are not green across the web apps

- Billing: **869 passed / 1 failed**, 111 test files, 122.00 seconds in the
  captured full run. `sidebarNotifications.test.jsx:84` still expects
  `Needs attention`, while `NotificationBell.jsx:333` now says
  `Smart Notifications`. The focused rerun produced **2 passed / 1 failed**.
  The failure appears to be stale test copy; no runtime navigation defect is
  established by it. Update the assertion and retain its behavioral assertions.
- Admin lint: **268 errors and 14 warnings**, 282 problems. They include unused
  variables, prop validation and hook dependency diagnostics. Build/test passes
  therefore do not establish compliance with the repository's advertised lint
  command. Fix actionable logic diagnostics and make any deliberate lint policy
  changes explicit rather than suppressing the whole gate.
- Landing: `npm run build` could not run because local dependencies are absent
  (`vite` is not recognized). No installation/network operation was performed.
  This is an environment verification gap, not evidence that its source build
  is broken.

### WEB-13 — P3: landing's default Mac download can choose the wrong architecture

**Evidence:** `bizassist-landing/src/useLatestRelease.js:46`–`:57`.

For every Mac user agent, architecture detection intentionally returns
`undefined`, causing an available arm64 DMG to be preferred over x64. An Intel
Mac therefore receives the arm64-only installer when both assets exist. Expose
explicit Apple silicon/Intel choices or a universal build; do not silently
guess when browser architecture is unknown. This is conditional on release
assets; no live release was queried.

## Verification record

| Check | Result |
|---|---|
| Billing `npm test -- --reporter=dot` | 869 passed, 1 failed; 111 files; deterministic stale-heading failure |
| Billing focused sidebar notification test | 2 passed, 1 failed with the same assertion |
| Admin `npm test -- --reporter=dot` | 47 passed, 3 files |
| AI `npm test -- --reporter=dot` | 13 passed, 1 file; these are chat-component tests, not full Chat orchestration/auth tests |
| Billing `npm run build` | Passed; main JS 527.82 kB / 142.99 kB gzip, large-chunk warning |
| Admin `npm run build` | Passed; main JS 360.47 kB / 100.01 kB gzip |
| AI `npm run build` | Passed; main JS 357.89 kB / 98.82 kB gzip |
| Landing `npm run build` | Not verified: local Vite dependency unavailable |
| Admin `npm run lint` | Failed: 268 errors, 14 warnings |
| Real-module outbox session-switch reproduction | Passed assertions proving current wrong-token replay; mocked network only |
| Audit-only payment-share reproduction | 1 passed assertion of current wrong-recipient/wrong-amount behavior |
| Audit-only AI stream reproduction | 1 passed assertion of current answer misattribution |
| Audit-only AI auth reproductions | 2 passed assertions of current origin/logout defects |

Audit-only component tests were temporarily placed in their app's
`src/__tests__/` directory for isolated execution, then moved here as `.txt`
artifacts so they do not change the product test suite. The three artifacts
retain app-relative imports. To rerun, copy each back to its corresponding
app's `src/__tests__/audit-*.test.jsx`, run that one test, and remove the
temporary copy. Their passing status means they **assert the observed current
bug**, not that a fix has passed. Logs remain in `scratch/` for this workspace.

No physical printers, live business accounts, actual payment apps, real
offline browser/device transitions, production origin handoffs, deployed
PostgreSQL behavior, or authenticated visual/accessibility sweeps were tested.

## Reconciliation with earlier plans

Reviewed the lean master plan, ecosystem security/privacy doctrine, Admin/SSO,
subscription/devices, invoice-template and phase-completion plans, plus the
29-October billing-page audit. The intended product remains coherent: one
business identity, private books/shared deals, deterministic money, offline
counter autonomy and controlled cloud/AI/network access.

Several earlier improvements are visible and should not be reported as still
missing: Home/Dashboard error handling, reusable saved-invoice templates,
server-outstanding-aware Record payment, saved-receipt lifecycle, scoped
IndexedDB databases, and admin directory/dashboard retry states. The new
findings concern paths that bypass those safeguards or lifecycle transitions
that their tests do not exercise.

The plans explicitly require evidence before green completion stamps. Today's
mix of passing units, one stale test failure, failed lint, untested cross-app
lifecycles, and reproduced identity/payment defects does not meet a full
release assurance bar. The old declaration that SSO/phase work is shipped must
be read as implementation history, not proof of every current deployment mode.

## Priority plan and the most important missing thing

The largest missing piece is a **repeatable release gate for one complete,
identity-bound money journey** across UI, backend, offline queue, reconnect,
account changes, payment recipient, posted balances and rendered/shared
invoice. Hundreds of isolated tests are valuable but have not proved that
those pieces remain attached to the same business and transaction throughout
the lifecycle. More features do not close that gap.

1. Before relying on these flows, close WEB-01 and WEB-02 with negative
   cross-business lifecycle tests. In the same focused work, use authoritative
   outstanding for WEB-03. Keep original queue ownership auditable.
2. Close AI request/session ownership and authentication propagation
   (WEB-04–07); test real configured origins and repeat-open named tabs.
3. Apply one required-read contract and server paging to remaining workspaces
   (WEB-08–10), then remove the external checkout QR dependency (WEB-11).
4. Repair the stale test, triage lint, restore Landing build reproducibility,
   and verify the architecture chooser (WEB-12–13).
5. Run an isolated end-to-end acceptance journey with two businesses and two
   devices: checkout → partial payment → return → correct outstanding →
   receipt/share recipient → offline queued bill → reconnect → logout during
   replay → login as the other business. Require one correct ledger effect,
   original-business ownership, accurate stock and an actionable unavailable
   state after each injected failure. Record build/commit, environment, exact
   results and remaining manual printer/deployment checks in the release ledger.

Do not expand into new ecosystem features until the first two steps are
closed and the last gate has produced current evidence.
