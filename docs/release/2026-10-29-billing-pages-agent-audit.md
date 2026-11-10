# Billing page and UI robustness survey — 29 October 2026

## Scope and evidence

Reviewed every route in `frontend-billing/src/App.jsx`, the current page/subpage
orchestrators, shared navigation/search/notification/theme components, relevant
existing component tests, and the current hosting/realtime/ecosystem plans.
This agent did not log into a live business, submit a registration, change live
settings, create a payment/return, or operate a printer. No financial database
was used. The root agent owns signup/trial/phone verification; the money agent
owns accounting calculations and backend financial invariants; the Field agent
owns the separate Field Team application.

The survey is source and isolated component evidence. Passing component tests
does not prove live deployment behavior, visual contrast at every viewport,
two-device convergence, scanner behavior, or physical printing.

## Confirmed issues fixed

| Priority | Finding and change | Evidence |
|---|---|---|
| P1 | Dashboard revenue/pending/overdue cards navigated to nonexistent `/payments`; purchase summary navigated to nonexistent `/purchases`. These fell through to Home. Corrected to `/parties/invoices` and `/stock/purchase`. Keyboard activation prevents unintended page scrolling. | `Dashboard.jsx`; `DashboardRefresh.test.jsx` route tests |
| P1 | New supplier payments were offered even though the existing payment command records customer receipts. The backend money audit rejects unsupported `made`; the UI disables that option, explains the limitation, disables a stale unsupported form and blocks submission. Historical Made transactions remain visible. | `RecordPaymentModal.jsx`, `Payments.jsx`; `RecordPaymentType.test.jsx` |
| P2 | Home's owner money/stock summary stayed stale while the page remained open. Added committed-change/reconnect/manual-sync and throttled foreground refresh, request coalescing, identity reset and late-response rejection, plus unavailable/retry state. | `Home.jsx`; `homeToday.test.jsx` |
| P2 | Failed Dashboard summary/payment reads looked like zero counts or no activity. Failed summaries now show an unavailable/retry state; failed payment activity is identified explicitly. Prior account responses cannot overwrite a new account's figures. Existing chart unavailable/privacy controls remain. | `Dashboard.jsx`; `DashboardRefresh.test.jsx` |
| P2 | The alternative Money customer page presented loading/errors as no customers. Added distinct loading/unavailable/retry states and request versioning. | `Money.jsx`; `MoneyPageLoading.test.jsx` |
| P2 | Contacts and Transactions converted failed required reads to empty arrays. Added explicit unavailable/retry states and latest-request protection. A failed Transactions load hides its summary panel rather than presenting zero totals. | `Parties.jsx`, `Payments.jsx`; `WorkspaceLoadFailures.test.jsx` |
| P2 | Settings could remain forever on its initial loader after HTTP/network failure. Added a read-error state and retry. Debounced saves, write serialization, unsaved-draft recovery and navigation flush behavior were retained. | `useSettingsAutosave.js`, `Settings.jsx`; `useSettingsAutosave.test.jsx` |
| P2 | The notification bell's first failed load could say Nothing needs attention. It now distinguishes checking, successfully checked and unavailable, supports retry, preserves previous successful alerts, and rejects prior-account responses. | `NotificationBell.jsx`; `NotificationBell.test.jsx` |
| P2 | Desktop Contacts/B2B header tabs were hidden while the collapsed rail also removed sidebar subpages. Header tabs now appear when the sidebar is a rail; the expanded-sidebar arrangement is retained. | `pageTabs.css`; source rule and existing navigation tests; live rail visual check still required |
| P2 | Sales return mapping discarded saved tax/discount snapshots and previous return quantities. The modal recalculated GST on gross unit prices. Return rows now retain snapshots and source quantities; estimated amounts prorate saved components and original header discounts/rounding. Purchase return uses the same estimate helper. Both clearly label estimates and identify the saved server note as final. | `returnPreview.js`, `SaleReturnModal.jsx`, `PurchaseReturnModal.jsx`, `Parties.jsx`, `Purchases.jsx`, `useInvoiceActions.jsx`; `returnPreview.test.js` |

## Complete route and subpage inventory

“Component evidence” below refers to existing/focused isolated tests and source
inspection, not an authenticated end-to-end browser run by this agent.

| Route / surface | Pages and states reviewed | Evidence and limit |
|---|---|---|
| `/login` | Recent business selection; owner business → role → sign-in; staff selection; manual owner/staff entry; invalid credentials; system check | `Login.jsx`, existing accessibility/routes/hosting-auth tests. No real credential entry. |
| `/register` | Business/category/extra modes; storage choices; phone/password/terms; trial/fallback | Root owns the mandatory valid-phone and 14-day first-time trial change. Previous root browser evidence is in the import/lifecycle review. This agent did not overwrite signup changes. |
| `/` | Owner greeting, quick actions, collected/pending/overdue/stock cards, announcements; cashier counter view | Fixed freshness and unavailable handling; Home tests cover owner/cashier, routing, Indian date, failure/retry and account switch. |
| `/dashboard` | Revenue/pending/overdue/inventory/customer/purchase/margin cards; privacy-aware charts; business feed; stock alerts; invoice viewer | Corrected routes/errors/races. Dashboard/chart tests cover temporary chart reveal and keyboard actions. Deployed graphs and real records still require browser verification after deployment. |
| `/sales` | Product/counter/cart, customer/tenders, payment confirmation, receipt viewer, print/share, minimized cart | Source route/layout review; checkout/math/printing tests belong to root/money verification. No live transaction or physical print. |
| `/live-view` | `Sales` in live-view mode | Explicit shared implementation in `LiveView.jsx`; no independent financial code. Live cross-terminal behavior not exercised here. |
| `/pos-live-counter` | Owner/staff visibility, staff list, draft/counter activity, sync-event updates, last-seen refresh | Source review. Real concurrent terminals, stale sessions and network drop need live smoke coverage. |
| `/stock` → `/stock/inventory` | Stock & Items; product/catalogue data, intake, godowns, transfer, adjust, labels/export/add/edit flows | Canonical URL, role hiding and PageTabs reviewed; merged-workspace/navigation and stock-specific tests exist. Required-read false-empty issue remains open below. |
| `/stock/purchase` | Pending Review, Confirmed, Returns/Debit Notes; upload/OCR/review/confirm; supplier filter; return dialog | Wrapper/router and source review; SmartStockPurchasesAndMigration tests cover components. Return preview changed as above. Required-read false-empty remains open. |
| `/parties` → `/parties/contacts` | Customers, Vendors, legacy Other Invoices; active/inactive filter, account/contact edit, ledger/credit drawer, invoice/purchase drill-down, reminders/returns | Source and merged-workspace/party/credit tests; read-error state fixed. Large data and live external sharing not tested. |
| `/parties/payments` | All, Received, historical Made, Expenses, Pending Dues, Credit Notes and invoice surfaces; record receipt, settle dues, log expense | Read-error state and supplier-entry guard fixed. Backend money semantics are reported separately. Historical misposted payments require reconciliation rather than UI relabeling. |
| `/parties/invoices` | Status chips, customer filter, list/page controls, view/print/share/record-payment/return | `InvoicesPage` uses shared `InvoicesListView` and `useInvoiceActions`; component tests exist. Its load-error false-empty and fixed fetch cap remain open. |
| `/parties/field` | Cloud-only owner confirmation of Field collections; local-mode explanation/link | `FieldCollections` explicitly handles local/cloud availability and errors; FieldCollections tests exist. Real Field→Billing settlement is separate integration evidence. |
| `/money`, `/money/parties` | Parallel party account view with outstanding/advance, search, drill-down and settle | Fixed loading/unavailable state. Still a parallel route rather than the primary sidebar workspace; avoid claiming the old workspace retired. |
| `/money/invoices` | Shared invoice actions/list | Source/component review; inherits the shared invoice-list open issue. |
| `/money/cashbook` | Cashbook view, filters and ledger drill-down | `MoneyViews.test.jsx`/Cashbook source; accounting totals are the money agent's scope. |
| `/b2b?tab=order` | Supplier catalogue, order cart and submit; offline notice | Source, B2B cart/connect tests; no order submitted. |
| `/b2b?tab=outgoing` | Buyer order states/detail/export and supplier identity | URL-driven selection, hook error states and OrdersTab tests; fulfillment race/accounting review elsewhere. |
| `/b2b?tab=incoming` | Seller order handling, status rail/details | Same shared B2B hooks/components; no real dispatch or invoice posting. |
| `/b2b?tab=connections` | Pending/sent/approved links and consent actions | Source and connection tests; no real consent or counterparty mutation. |
| `/reports` | GST Report, GSTR-1 B2B, GSTR-1 B2CS, GSTR-1 HSN, GSTR-3B; Sales Register, Purchase Register, Day Book, Outstanding Ledger, Stock Movement, Shift Reconciliations; P&L, Balance Sheet, Trial Balance; Party Ledger, General Journal, General Ledger, Audit Journal | All 18 report entries inventoried in `REPORTS`; navigation/date-range/view tests exist. Source includes per-request cancellation/versioning for report and party selection. Financial reconciliation and real data are separate evidence. |
| `/settings?tab=general` | Display/zoom, appearance, accent/palette/theme, AI-search preference, backup settings | Appearance/settings tests; initial read-error recovery fixed. All palette contrast combinations not visually verified. |
| `…tab=profile` | Embedded business identity, logo, address/GST/contact/payment metadata, save feedback | Profile integration/validation tests; source preserves edited form fields and clear error messages. No real profile changes. |
| `…tab=staff` | Staff list, roles, counter prefixes, create/reset/remove | Source of validation/loading/retry and owner/cashier visibility reviewed; destructive actions not executed. |
| `…tab=transactions` | Invoice/counter, dues and checkout settings | Settings persistence tests; backend financial enforcement audited separately. |
| `…tab=inventory` | Barcode, stock and item preferences | Settings/stock source; scanner/hardware not exercised. |
| `…tab=print` | Thermal/A4 layout preview, logo/header/fields, paper/display controls | Settings/print component tests; no physical printer proof. |
| `…tab=network` | Local/cloud readiness, hosting transition and discovery | Source and hosting component tests. Real two-server/offline/LAN lifecycle remains a deployment gate. |
| `…tab=migration` | Import/export, manual sync, backups and hosting migration | Root's previous import partial-result/rollback changes retained; current tests cover failure UI. No real data migration executed. |
| `…tab=activity` | Business audit/event log | ActivityFeed source/tests; live event retention and event ordering not verified. |
| `…tab=ops_health` | Health/diagnostic panels and queue states | OpsHealthPanel tests/source; production failures remain operational evidence. |
| `…tab=support` | Ticket/feedback/diagnostic submission; hidden contact data policy | Support tests/source; no ticket sent. |
| `…tab=advanced` | Security/locks, resets and backup-related controls | Source and lock/hosting tests; no reset/deletion or credential change performed. |
| `/invoice/:invoiceNo/view` | Authenticated template viewer, print/share, document actions | Routes and invoice-view/template tests; real browser popup/printer needs explicit testing. |
| `/public/invoice/:uid` | Public token-based invoice read; loading/error/template | Source review only. Fixed white paper is intentional; loading/error contrast against persistent dark mode should be checked. No public invoice token requested. |
| Legacy redirects | `/profile`, `/staff`, `/support`, `/import`, `/b2b-network`, `/b2b-orders`; unknown URL fallback | AppRoutes/merged navigation tests; destination routes enforce authentication. |
| Shared chrome | Expanded/rail/mobile sidebar, active tree, workspace tabs, footer profile/bell, universal search, long business-name pan | Navigation/appearance/search/notification tests; reduced-motion rule is present. Rail tab recovery changed in CSS. No agent-owned browser tabs were used. |
| External apps | AI dashboard and Field Team launch/plan/cloud-data guards and handoff code | Billing launch source/config tests; the other apps' complete pages are separate agent reports. |

## Open issues and recommendations

1. **P2 — Required reads still look like empty data in Stock, Purchase and the
   shared invoice list.** `Stock.jsx` required product/godown/transfer reads use
   `r.ok ? r.json() : []` plus empty fallbacks. `Purchases.jsx`'s purchase/debit-note
   load does the same; its OCR review catalogue fetch can also fail silently.
   `InvoicesListView.jsx` maps failed invoice reads to `[]`. These were deliberately
   left open after the root agent bounded this survey. Apply a shared loading /
   loaded-empty / unavailable-with-retry contract, retain request versioning, and
   test offline, HTTP 403/503 and account-switch failures. These pages are **not**
   cleared for failure-state robustness by this review.
2. **P2 — Fetch caps can hide records.** Contacts/Money/shared invoice lists fetch
   up to 500 rows and filter/page locally. A visual 25-row pager does not retrieve
   records beyond that backend fetch cap. Use server pagination/search and server
   counts; verify businesses exceeding 500 customers/invoices before calling
   large-business support complete.
3. **P2 — Exact return preview needs a server quote.** Current DTOs do not expose
   actual prior credit-note monetary allocations, so the client cannot reproduce
   cumulative cent allocation exactly. The UI now calls it an estimate and the
   backend is authoritative. Next add a non-mutating return quote endpoint using
   the same command allocation code, with an explicit source-line identifier for
   repeated product rows. Keep refunds tied to the saved credit/debit note.
4. **P2 — Supplier settlement remains unsupported.** Disabling the misleading
   entry prevents new customer-receipt misposts, but does not implement vendor
   settlement or repair historical records. A separate idempotent supplier-payment
   command, vendor ledger posting and its own form are required before enabling it.
5. **P2 — Role visibility should use one permission map.** Some pages use only
   `role === 'cashier'` to determine owner cards, while other surfaces recognise
   `supply adder` or `supply_adder`. Server permission checks remain authoritative;
   unify UI capabilities so staff do not see links that lead to forbidden data.
6. **P3 — Finish visual/accessibility sweep in authenticated fixtures.** Check all
   theme presets/custom accents in light/dark/system, narrow and short windows,
   zoom and reduced motion; focus order and selected-tab contrast; public invoice
   loading/error contrast; oversized business names. Shared PageTabs keyboard
   navigation exists, but full tab-to-panel ARIA relationships can be improved.
7. **Release gate — live end-to-end evidence.** Check deployed Dashboard charts,
   return/receipt completion totals, checkout print popup/retry, actual thermal/A4
   printers, two authenticated devices, offline/reconnect, expired sessions and
   Field collection confirmation in disposable businesses. No isolated frontend
   result proves these.

## Test record

- Initial page/navigation/settings/theme/search/notification set: **154 passed**.
- Expanded 18-file set after Home/Dashboard/Money/rail changes: **162 passed**.
- Primary Contacts/Transactions/Settings read-failure plus existing relevant
  regression set: **23 passed**.
- Final NotificationBell/supplier-entry/return-preview/affected-workspace set:
  **57 passed / 9 files**, including all latest notification, supplier-entry and
  return-preview edits. Non-failing React `act` warnings remain in existing bell
  tests. An old Settings fixture returned `[]` for `/settings`; it now returns
  an object matching the actual API contract. Root will run the final full
  frontend suite after all agents finish edits. Earlier counts overlap and
  must not be summed.

No git staging, commit, push or deployment was performed by this agent.
