# Execution plan — 31 October 2026

1. Complete the credential response in [SECURITY-RESPONSE.md](SECURITY-RESPONSE.md).
   Source containment is implemented; provider rotation and deployed secret
   updates remain external work.
2. Reconcile the existing financial discrepancies identified by the supplied
   startup log: one excess-receipt invoice, multiple open shifts for two
   operators, and 18 overfilled invoices. Use original documents, actual cash
   counts and a verified private backup. Follow [the log review](LOG-REVIEW.md);
   do not run a guessed or blanket financial repair.
3. Review the [original 40-ID implementation ledger](implementation/STATUS.md)
   and [Field keep/revert review](implementation/web-latest-changes.md).
   Keep the corrected Field work. AI status-only payment and standalone advances
   remain disabled; enabling them is future feature work requiring guarded
   receipt/allocation commands. Exact executed results and skips belong in the
   results files, with overlapping tests counted only once per suite.
4. Rehearse the new schema and protocol rollout in staging: migration account
   first, constrained HTTP runtime and dedicated internal trade service next,
   then compatible clients. Legacy incremental peers must hold their queues and
   require an upgrade rather than advance a lossy cursor. Never substitute
   elevated HTTP credentials as a rollout shortcut.
5. Demonstrate recovery into an isolated database, then a real phone/printer
   acceptance pass: check-in, multiple routes, GPS center/expand, linked
   collection, merchant QR, account switch during GPS, offline reconnect,
   deleted-counterparty print history and client/server restart. Confirm an
   actual merchant-app receipt independently of QR display. Complete packaging
   and signing where relevant to the chosen release.
6. Return to the original product plan's paid daily-billing pilot. Choose the
   first merchant segment and pilot price, operate with reconciled receipts,
   returns, supplier payments, stock and journals, and collect evidence of daily
   use and willingness to pay. Passing code tests is not that product outcome.

This is a continuation of the existing product plan, with implementation and
synthetic verification authorized by the owner. It is not permission to alter
production financial rows, rewrite published history or assume an external
release gate has already passed.
