# Original 40 findings — implementation ledger, 31 October 2026

**38 implemented; 2 safely contained.**
The two contained workflows are unavailable; they are not completed features.
These counts describe code behavior. External credential rotation, deployment
configuration, existing financial discrepancies and device acceptance remain separate.

| ID | Priority | Status | Original finding |
| --- | --- | --- | --- |
| BD-01 | P1 | contained | AI mark-paid bypasses receipts, amount and journal |
| BD-02 | P1 | implemented | NULL warehouse/batch cache duplicates aggregate stock |
| BD-03 | P1 | implemented | Purchase pack price becomes base-unit cost |
| BD-04 | P1 | implemented | AI counts positive credit notes as revenue and collections |
| BD-05 | P1 | implemented | Automatic journal re-sealing clears integrity alarm on altered content |
| BD-06 | P1 | implemented | B2B order quote and invoice disagree on tax heads |
| BD-07 | P1 | implemented | Direct order IDs bypass catalogue category restriction |
| BD-08 | P2 | implemented | Completed orders can become rejected without reversal |
| BD-09 | P1 | contained | Standalone advances lack durable receipt and replay safety |
| BD-10 | P1 | implemented | Historical profit uses mutable current product cost |
| BD-11 | P1 | implemented | Supplier settlements and linked customer refunds are incomplete |
| BD-12 | P2 | implemented | Supplier catalogue overwrites multi-bucket quantity |
| BD-13 | P2 | implemented | Debit-note count-based numbering has no unique constraint |
| TS-01 | P1 | implemented | Timestamp ties skip rows across pull pages |
| TS-02 | P1 | implemented | Response-end watermark misses writes during table reads |
| TS-03 | P1 | implemented | Rejected row branch advances past an unread table |
| TS-04 | P1 | implemented | Replicated staff changes preserve existing cloud token version |
| TS-05 | P1 | implemented | Staff/profile push has no durable retry |
| TS-06 | P1 | implemented | Auth and plan guards conflict with constrained FORCE-RLS runtime role |
| TS-07 | P2 | implemented | Export failure becomes successful empty table |
| TS-08 | P2 | implemented | Desktop accepts disconnected DB health response as ready |
| TS-09 | P2 | implemented | Short JWT secrets acquire random per-process suffix |
| WEB-01 | P1 | implemented | Running offline flush can submit old account invoice with new token |
| WEB-02 | P1 | implemented | Share/reminder can use previous business UPI recipient |
| WEB-03 | P2 | implemented | Payment requests ignore credit-adjusted outstanding |
| WEB-04 | P2 | implemented | AI streams can write answer into another question |
| WEB-05 | P2 | implemented | Billing sign-out leaves existing AI tab authenticated |
| WEB-06 | P2 | implemented | SSO accepts localhost-prefix public origins |
| WEB-07 | P2 | implemented | Billing profile cache survives account changes |
| WEB-08 | P2 | implemented | Required reads appear as empty financial records |
| WEB-09 | P2 | implemented | Client paging hides records outside initial fetch caps |
| WEB-10 | P2 | implemented | Merchant detail can show stale identity while actions target current route |
| WEB-11 | P2 | implemented | UPI QR requires third-party network service |
| WEB-12 | P3 | implemented | Billing test assertion fails; admin lint fails; landing build unverified |
| WEB-13 | P3 | implemented | Mac download defaults to arm64 when architecture unknown |
| FT-01 | P1 | implemented | Cancelled task reopen permits duplicate invoice collection evidence |
| OPS-01 | P1 | implemented | Equal-total donor repair fabricates unrelated invoice lines |
| CI-01 | P2 | implemented | Routine CI misses admin and some Field/Billing dependency contracts |
| DOC-01 | P2 | implemented | Historical plans and current completion state remain inconsistent |
| OPS-02 | P1 | implemented | Financial repair snapshots with invoice/payment/ledger records are tracked |

## Evidence and limitations

[Machine-readable ledger](issues.json) preserves the implementation evidence
and remaining limits for every ID. [CSV copy](issues.csv) has identical rows.

Domain, trust, web and root results are recorded separately; overlapping
test runs must not be added together as a unique-test count.

- [Backend domain](backend-domain.md)
- [Trust, sync and operations](trust-sync-ops.md)
- [Latest Field changes: keep with corrections](web-latest-changes.md)
- [Root acceptance results](root-results.json)
- [New pasted-log findings](../LOG-REVIEW.md)
- [External credential response](../SECURITY-RESPONSE.md)
- [Execution and release plan](../PLAN.md)
