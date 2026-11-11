# STATER Bill: pricing, AI automation and mobile experience

Date: 11 November 2026 (Asia/Calcutta)

Status: agreed product direction. Pricing, credit quantities and paid desktop enforcement are not published or activated by this document. Mobile implementation and verification are tracked below.

## 1. Product offer

Keep two paid plans for new businesses: Local and one Pro. Pro includes automation; there is no separate Pro Plus or automation subscription. Pro also includes Local, so a business never buys desktop access twice.

| Plan | Target price before applicable taxes | Billing term |
| --- | --- | --- |
| Local | INR 2,499 | Paid annually; renews each year, not a perpetual licence |
| Pro Monthly | INR 599 | Monthly subscription |
| Pro Yearly | INR 5,999 | Annual subscription; same capabilities as Pro Monthly |

These are the agreed starting prices to validate with paying pilot customers. Annual Pro customers receive their included AI allowance monthly. Do not describe an annual Local subscription as a one-time lifetime purchase.

Local includes one business/location and one billing counter: billing, stock, purchases, contacts, reports, local backups, ordinary CSV/Excel imports and locally stored product images. Keep manual purchase-order work in the core product.

Pro adds Local + Cloud synchronization, owner web access, cloud backups, B2B, Field Team, Stater AI and approved business automations. The initial packaging discussed two billing counters. Final staff-seat, storage, backup-retention and AI allowances require cost testing before publication; do not promise unlimited usage.

Use a bounded 14-day full trial and the sample-data demo for evaluation. Existing free-use promises require grandfathering or a clearly communicated voluntary migration; this plan does not silently change existing customers' access. Credit unused Local subscription value when a customer upgrades to Pro.

## 2. AI credit wallet

- Include a monthly allowance with every active Pro subscription.
- Use one shared wallet for AI chat, agent-assisted PO work, OCR/document processing and voice usage, with clearly published operation rates.
- Proposed recharge purchase amounts: INR 199, INR 499 and INR 999. Credit quantities are deliberately undecided until actual inference, OCR, speech, infrastructure and support costs have been measured.
- Keep purchased credits separate from the included monthly allowance so a refill cannot erase purchased balances. Publish expiry and subscription-lapse behaviour before selling packs.
- Show balance, usage history, estimated cost before expensive work and an explicit recharge action. Automatic recharge must be opt-in with a customer-controlled limit.
- At zero balance, pause AI-dependent tasks and explain which tasks need credits. Core billing, stock, purchases, reports, paid cloud sync and deterministic rules continue while the subscription is valid.
- Do not charge AI credits for ordinary stock arithmetic, scheduled threshold checks or standard app actions that do not call an AI service.
- Prevent duplicate debits on retries. Release reservations/refund credits for platform failures; record the operation, business, allowance/recharge source and final charge in an auditable server-side ledger.
- Outbound telephone calls consume more than in-app voice commands. Account for speech, model, telephony, retries and messaging costs before choosing rates.

## 3. Positioning

Primary descriptor: **STATER Bill — Agentic billing for growing businesses.**

Headline: **From everyday billing to intelligent business automation.**

Product explanation: **Ask. Review. Approve. Get work done. Prepare purchase orders, check supplier bills and follow up on business tasks through chat and voice.**

Publish capabilities as available only after they are implemented and verified. The current reorder action records recommendations; complete PO creation/delivery and voice integration remain implementation work.

## 4. Automation delivery sequence

Detailed workflow, Automation-page, recurring-billing and runtime specification: [Agentic billing and everyday automations](2026-11-11-STATER-AGENTIC-BILLING-AND-AUTOMATION-PLAN.md).

The detailed plan refines the rollout: first prove the shared runtime with a small daily-work/recurring-billing private pilot, then deliver a complete purchasing-agent workflow: **draft → review → approve → send → track**. The purchasing scope below remains required; a recommendation log does not complete it.

1. Supplier-grouped reorder proposals using normalized stock, minimums, units/pack sizes, preferred suppliers, agreed prices and existing open inbound orders.
2. Chat and voice instructions that prepare PO drafts within the owner's budget. Collect supplier lead times before claiming demand-based ordering.
3. Approval of the exact recipient, items, quantities and totals before supplier submission. Recheck changed stock/prices; apply owner/staff permissions and spending limits.
4. Open-order tracking and overdue-delivery follow-up drafts.
5. Supplier invoice OCR matched against approved POs, with discrepancies reviewed before purchase, inventory or ledger posting.
6. Daily owner summaries, expiry/stock exceptions and approved collection reminders.

Prerequisites include a durable rule/run store, stable business/product/supplier IDs, timezone-aware schedules, duplicate-run protection, an external-send outbox and action/audit history. Existing batch-level reorder recommendations must not create duplicate product orders. Keep all paid access and credit enforcement server-side; a hidden button is not entitlement enforcement.

## 5. Licensing, local use and synchronization

The subscription grants capabilities. Local Only versus Local + Cloud selects synchronization behaviour; it does not buy, cancel or downgrade the subscription.

- A confirmed Pro desktop session defaults to Local + Cloud.
- A deliberate Local Only choice is saved for that business on that device. Explain that local changes stay there and cloud/other-device changes are not downloaded until Local + Cloud is enabled again.
- A Local-plan customer sees Upgrade to Pro for connected capabilities. A Pro customer who has paused synchronization sees Enable Local + Cloud where current shared data is required.
- Internet loss does not imply subscription expiry. Hybrid should queue changes and reconcile after reconnection. Show last successful sync, pending changes, conflicts and actionable server/database health.
- A normal Local + Cloud → Local change uses the same local database; it must not depend on cloud preflight, clear queues or erase data. A legacy cloud-routed desktop needs a local login rather than reuse of a cloud JWT.
- Maintain three separate dates: paid-through date, offline-verification deadline and any explicitly published renewal grace. A proposed 30-day offline verification window is not an extension of an unpaid subscription; final grace/remote-shop extension policy needs approval before rollout.
- Future desktop enforcement needs a signed entitlement tied to the business and authorized device, usable offline through its permitted dates. Enforce cloud capabilities live on the server. Provide device replacement/transfer rather than charging for every reinstall.
- After the final paid period and agreed grace, the proposed model pauses new production transactions while keeping history, printing, export and local backups accessible. Existing Free customers remain subject to the transition policy above.

Related architecture: [hosting master plan](HOSTING_MODE_MASTER_PLAN.md) and [activation/device plan](SUBSCRIPTION_ACTIVATION_AND_DEVICES_PLAN.md). Historical free-tier and three-mode descriptions in older plans do not represent a newly activated pricing policy.

## 6. Mobile UI work authorized today

Scope: the Billing app at phone widths (768px and below). Preserve desktop layouts, all existing calculations, permissions, demo protections and API behaviour.

- Landing-inspired outlined, rounded, floating top bar with STATER Bill branding, current business context, menu and account actions.
- Matching bottom navigation using recognizable SVG icons only; preserve accessible names and selected-route indication without visible text labels.
- Safe-area spacing, usable touch targets and no content hidden under either bar.
- Stock and purchases: responsive tabs/search/filter/actions, readable item and purchase summaries, reachable edit/intake/detail actions and contained wide data.
- Billing: usable portrait mode, product selection, current bill, quantity/details controls, totals and payment flow; remove the landscape-only block on phones.
- Reports: responsive filters/date controls, summary cards and contained report tables/columns, with exports and report navigation reachable.

Verification targets: 320px, 390px and 430px phone widths; keyboard/accessibility interactions; desktop smoke check; appropriate existing regressions and production build. Use isolated sample data for state-changing QA.

Implementation status: mobile UI work completed and verified on 11 November 2026.

- Added the outlined floating top bar and SVG-only bottom navigation, including accessible names, selected routes, safe-area spacing and portrait Billing access.
- Stock includes touch-friendly workspace controls, inventory overview filters and a contained table. Purchase bills reflow into supplier cards.
- Billing includes Products / Current bill views, quantity controls, expandable item details, persistent totals and a scrolling checkout sheet. Price selection remains visible from either mobile pane; catalogue search shows all matches while desktop autocomplete retains its eight-result limit. The checkout Close action stays above the customer dropdown's dismiss layer.
- Reports include phone report selection, paired date fields, scrollable period shortcuts, stacked summaries, contained wide tables and a reachable fullscreen Close action. Phone-only CSS is screen-scoped so narrow paper sizes retain print layouts.
- Browser QA covered 320px, 390px and 430px widths, plus a 1366px desktop smoke check. Inventory/report tables scroll internally without widening the document. Billing price selection, wholesale rate, quantity changes, detail expansion and checkout opening/cancellation were verified with demo data; no invoice was saved. Reports were reviewed with an isolated synthetic-data fixture because the production demo remains protected.
- Validation: 221 tests passed across 27 modules, including mobile navigation/pricing, stock/purchases, reports, hosting-mode changes and health checks. The 12 checkout tests also passed after the final header adjustment. Production build and `git diff --check` passed. Vite retains its bundle-size warning; it does not prevent the build.

Pricing activation, AI-wallet enforcement, signed desktop licensing, executable PO delivery and voice integration remain separate implementation work described above. This mobile delivery does not publish or activate those capabilities.

## 7. Commercial validation before publishing

Measure monthly contribution separately for Local and Pro:

`recognized revenue - payment fees - variable hosting/database - storage/backup/egress - AI/OCR/speech - support provision`

Validate with the first 20–30 paying businesses. Track trial conversion, paid retention, support time, sync reliability, action success and cost per active paid business. Set credit and seat allowances using measured costs rather than competitor prices alone.

Reference models discussed: [Tally licensing](https://help.tallysolutions.com/licensing-tallyprime/), [BUSY pricing](https://busy.in/pricing/), [Adobe offline use](https://helpx.adobe.com/creative-cloud/apps/manage-apps/creative-cloud-apps/internet-connection-creative-cloud-apps.html), [QuickBooks view-only access](https://quickbooks.intuit.com/learn-support/en-us/help-article/cancel-products-services/renew-subscription-use-view-mode-quickbooks-2023/L4IUEYTMg_US_en_US), [Zoho Agent Wallet](https://www.zoho.com/agents/pricing.html), [Salesforce agent pricing](https://www.salesforce.com/agentforce/pricing/) and [voice-agent usage pricing](https://elevenlabs.io/pricing/agents). These inform the model; STATER's proposed prices and allowances are its own product decisions.
