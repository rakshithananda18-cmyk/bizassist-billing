# Billing and admin alignment review — 2026-10-29

Reviewed the user's uncommitted Billing and frontend-admin redesigns together, preserving the new Settings sections, report directory, contextual action toolbars, invoice layout and admin visual direction.

## Issues resolved

- Admin Settings used nonexistent dialog methods, unsupported AI router values/payload fields and the wrong merchant-feedback endpoint. It now uses the actual confirmation API, server-supported legacy/shadow/new modes and `/admin/feedbacks`. Cache/database information uses the backend response contracts rather than fabricated connected status. Unsupported global quota inputs link to the working per-business controls.
- Removed fabricated admin identity/Gateway-health values. Theme controls now update together, and timezone/polling preferences affect telemetry with timer cleanup. HTTP failures from cache/reset/wipe requests cannot display success.
- Admin overview, business directory, usage and metrics now expose retryable loading errors instead of showing zero/empty results or indefinite skeletons. Failed refreshes keep last-known data with a notice; malformed payloads and stale responses are guarded. Zero quotas render finite usage percentages.
- Conflicting legacy CSS hid the admin profile menu and broke the phone drawer. The drawer now focuses its Close control, contains keyboard focus, hides the background from assistive technology and restores focus on Escape. Phone Settings uses a labeled section selector instead of squeezing the entire desktop directory into one row.
- The real local admin directory had 274-pixel rows because its action cell collapsed to about 69 pixels wide. A compact three-column action grid and horizontal table overflow reduce those rows to about 118 pixels without removing actions.
- Moving Support into Settings accidentally blocked cashiers. Cashiers can open General and Support while migration/activity remain restricted. Legacy Support and Import routes continue to resolve into the correct Settings sections.
- Activity refresh could skip a page; category requests could overwrite each other; failed requests looked like empty history. Pagination advances only after successful loads, stale requests are ignored, errors are visible and older events remain reachable during local search. Activity/details/dashboard actions work from the keyboard.
- Invoice Close remains available during loading/error and uses the current callback. The modal handles focus and print-cancellation Escape. Template/Print controls use theme tokens, and the account pane stacks below the preview on phones. Account data no longer reloads on every template/PDF UI change. Zero-value invoices show accessible, finite payment progress.
- Reports uses router query state and ignores stale report/party responses. Changing report/date/party clears outdated results. Fixed phone category selection, conflicting layout selectors and print clipping. Settings/Reports selection styles use shared palette tokens.
- CSV imports require a real preview before approval and prevent concurrent commits. Uncertain network results no longer claim that nothing was saved. Clear Intake also clears supplier/payment/discount state. GRN output escapes imported text before writing HTML.
- Support no longer invents ticket IDs, application versions, sync success or SQLite diagnostics for cloud accounts. Requests enforce the complete backend 8,000-character limit, including metadata, and phone layouts fit their available width.
- Per the user's follow-up, direct support contact channels and WhatsApp follow-up are hidden. Disabled contact configuration uses the confirmed existing landing-page email and 10 AM–6 PM hours; no phone is configured. The support form and FAQs remain available.

## Verification and boundaries

- Browser review signed into the user-specified local admin page and inspected Businesses read-only. Mutating admin operations were tested with mocked responses.
- Separate synthetic previews checked desktop and 390-pixel phone layouts, admin light/dark theme synchronization, drawer focus/Escape, report category navigation and invoice/account sizing. The phone invoice preview/account panes were both about 373 pixels wide within the modal.
- No real merchant registration, invoice, payment, import, cache purge, quota change, subscription change or wipe was performed. The existing two-local-database/shared-cloud rules and cloud-only Pro Field Team model remain unchanged.
- Operational record diagnostics remain separate from this frontend review. No financial records were modified or repaired.

## Final checks

- Billing: **106 test files, 838 tests passed** in 191.67 seconds.
- Admin: **3 test files, 47 tests passed** in 10.64 seconds.
- Both production builds passed. Billing's existing main-chunk warning remains: 516.10 kB / 140.04 kB gzip. Admin's main JavaScript bundle is 360.21 kB / 99.93 kB gzip.
- `git diff --check` passed. This reviewed batch is prepared for the user's explicitly requested publication to the existing GitHub and Hugging Face remotes.
- Temporary browser viewport overrides were reset, the synthetic preview tab/server were closed, and the user-requested local admin Businesses tab was kept open. Logs and previews remain in ignored scratch storage; screenshots contain synthetic data.
