# Post-checkout printing follow-up — 2026-10-29

## Findings and changes

- A later unconditional `#thermal-receipt { display: none !important }` rule overrode the print rule while the application itself was hidden for printing. Restricted that hide rule to screen media so the thermal receipt can appear in print output.
- Successful Save & Print now opens a persistent **Invoice saved — print receipt** dialog with a direct Print action, PDF preparation, Open PDF, Download PDF and Done. Automatic printing remains best effort. Retrying print never repeats the invoice/payment POST.
- The receipt holds a snapshot of the accepted invoice number, items and totals before the counter resets for the next sale. The committed cart's save lock stays held until the receipt dialog closes. Pending print preparation aborts on close/unmount and its frames/blob URLs are disposed.
- Cloud checkout retires the committed cart before its background invoice-list refresh, preventing an early Done click from exposing the saved cart again. A prepared PDF remains printable for the entire saved-receipt dialog lifetime rather than expiring after one minute.
- The dialog captures Ctrl+P as print-only and keeps focus in its own controls. An Escape forwarded after cancelling native print preview no longer dismisses the saved receipt as well.
- PDF preparation failures leave the saved receipt available for retry. The Billing API can return HTML with HTTP 200 when PDF rendering is unavailable; the frontend rejects that content instead of creating an invalid PDF download or opening an active HTML blob.
- The private invoice viewer's Download PDF action previously invoked the same browser print function. It now fetches the actual saved invoice PDF through the authenticated API, keeps a direct download link for retry, and cancels stale requests. Its server PDF uses the saved layout; the independent Print action continues to print the selected preview layout.

## Verification

- Focused checkout, payment hook, PDF lifecycle, saved-receipt dialog and thermal receipt tests: **50 passed**.
- Private invoice viewer tests: **12 passed**.
- Final payment-hook/PDF regressions, including slow cloud refresh, long-lived PDF printing and empty responses: **28 passed**.
- Complete Billing frontend suite after the final changes: **100 files, 787 tests passed** in 137.28 seconds.
- Production frontend build passed. The existing large main-chunk warning remains (513.93 kB / 139.45 kB gzip).
- An isolated local fixture used synthetic invoice/payment responses only. Native print invocation paused the browser automation until cancellation, and the fixture received the native afterprint event. No real business invoice, payment or registration was created.
- Final visual verification of the new dialog/native print preview could not be completed: Computer Use stopped because it could not confidently identify the Windows browser URL. An earlier host-window screenshot was also blocked to avoid capturing unrelated conversation content. No further browser interaction was attempted after the stop. Physical printer output remains unverified.

No database, payment API, plan gating or Billing/Field storage configuration is changed by this follow-up. Release logs and the synthetic fixture remain in ignored scratch storage.
