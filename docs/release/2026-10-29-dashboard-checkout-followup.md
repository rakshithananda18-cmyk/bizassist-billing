# Dashboard, checkout, settings and registration follow-up — 2026-10-29

## Findings and changes

- The deployed Billing API was running commit `c22ee42` and exposed `/dashboard-charts`. The signed-in online dashboard explicitly showed Privacy Mode enabled, which deliberately hid the charts. A clear privacy card now offers temporary Show/Hide controls and a direct settings link. It does not change the saved privacy preference. Background refreshes keep the panel mounted so a temporary reveal lasts for the dashboard visit; changing business/privacy identity or leaving the page resets it.
- Preserved the user's new centred single-month chart and empty-state handling, Privacy Mode search entry, and explicit Billing Vercel CORS origin. Removed the misleading chart error instruction to complete registration: a data-loading failure does not establish a registration issue. Failed chart data has a retry control and is not rendered as invented zero activity.
- Settings autosave status now lives in the Save button: Saved, Saving, Save Changes and Retry Save. The existing serialized/debounced autosave hook remains authoritative.
- Sidebar child links and page navigation tabs now follow the configured navigation selection hue with a softer background and contrast-adjusted text. Action-button colours remain independent. Theme tests cover built-in/custom light and dark contrast; browser checks verified Ocean's gold selection on both light and dark surfaces.
- Registration's optional business-type checkboxes previously inherited text-field width/padding. Scoped styles now pair each 16-pixel checkbox with its label, using a single column on phones. Cloud registration shows Cloud selected with disabled Local/Local + Cloud choices, a desktop download link and same-account storage guidance. The cloud signup payload explicitly selects cloud hosting; desktop choices and trial handling are preserved.
- Credit invoices previously skipped printing despite the Save & Print label. All invoice payment states now reach the requested print path. PDF printing waits for the document load, retains the saved cart/lock until print preparation settles, times out cleanly, and keeps the iframe/blob alive while print preview can use it. Checkout focus handling allows the confirmation and print frame to receive focus.
- Checkout and payment confirmation share large Amount received and Change to return / Credit rows, with aligned primary/secondary actions. Partial cash/card/UPI tenders preserve the amount and payment method instead of silently marking the full invoice paid. Only an explicit No payment / Add to credit choice records zero received. A remaining balance requires a customer; over-tender applies only the bill total and displays change. Confirmed quick-save amounts also update the receipt form.
- Enter on a focused credit/cancel button now activates that button rather than forcing the primary paid action.

## Verification

- Initial full Billing frontend run: 97 files, 758 tests passed.
- Final focused payment, receipt, dashboard-refresh, registration, save-control and theme regressions: 53 tests passed.
- Final complete Billing frontend suite: **99 files, 762 tests passed** in 111.17 seconds.
- Production build passed: main app 506.02 kB / 136.72 kB gzip; the existing 500 kB chunk warning remains.
- Browser review used an isolated preview with synthetic customers/amounts and no real business API. Desktop and 390-pixel mobile checks covered checkbox alignment, disabled cloud storage choices, Save status, light/dark selection colours, temporary chart reveal, payment confirmation and partial-credit layout. No real signup, invoice, payment or print transaction was submitted. Printer paper/cutter behavior remains unverified.

The earlier two-local-database / shared-cloud-PostgreSQL / cloud-only Pro Field
Team rules remain in place. This follow-up changes no real database, signing
secret, subscription or Field Team deployment configuration.

This reviewed follow-up is prepared for the existing GitHub and Hugging Face
publishing flow authorized by the user. Temporary viewport overrides were reset
and the synthetic preview server was stopped after browser checks.
