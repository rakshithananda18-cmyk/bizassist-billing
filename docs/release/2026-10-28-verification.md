# Release verification — 2026-10-28

This record covers the accepted billing UI changes, the completed Settings and Field Team edits supplied by the user, the release review fixes, and route loading improvements. It records local verification, not a claim that every deployment or hardware scenario has passed.

## Changes reviewed and fixed

- Kept the accepted Terracotta palette and profile-style sidebar hover. The later Sunset/selection colour experiments remain reverted.
- Centered the sign-in steps and added accessible step labels.
- Preserved the new Settings section sidebar, responsive tabs and integrated business profile.
- Serialized Settings autosaves, manual saves and navigation flushes. New mounts wait for pending writes; failed drafts recover during navigation in the same auth session. The status only reports Saved after the current edits are acknowledged. Failed drafts are held in memory and do not survive a full browser reload or new login.
- Made the mobile billing drawer inert while closed, with focus placement, Tab containment, Escape dismissal and focus restoration when open.
- Kept purchase-table empty messages inside the visible viewport on phones.
- Corrected Field Team's hidden sidebar expand button, clipped staff scrolling, and unreachable tall signup forms.
- Validated backup file structure before import, retained legacy tables-only compatibility, preserved export timestamps, and provided an explicit reload action after restore. Restores add missing rows and keep existing rows.
- Deferred 14 billing routes with loading/recovery UI. Login, Home and Sales stay eager so checkout's existing offline entry path is retained.
- Reconciled the roadmap and testing guide with current implementation evidence; historical June/August assessments remain dated history.

## Automated checks

| Check | Result | Scope |
|---|---|---|
| Billing Vitest full suite | 86 files, 703 tests passed in 255.37 seconds | Route recovery, settings, themes, search, payments, invoices, print components, sync/outbox and backup components |
| Field Team Vitest | 6 files, 19 tests passed | Existing plan, tracker, invoices, collection, coordinates and formatting suites |
| Selected backend workflow suite | 153 tests passed in 73.96 seconds | Billing, purchases, purchase commit, stock ledger, negative stock, data transfer, print payloads, print helpers and sync parity/idempotency |
| Tenant policy suite | 8 passed; 1 module skipped | Application/policy checks passed; real Postgres module skipped because psycopg2 was unavailable |
| Billing production build | Passed | Main JavaScript 659.35 kB; gzip 185.79 kB |
| Field Team production build | Passed | Main JavaScript 441.62 kB; gzip 130.26 kB |
| Git whitespace checks | Passed | All release changes |

Commands (from the relevant frontend directory):

```powershell
npm test -- --pool=forks --poolOptions.forks.maxForks=2 --poolOptions.forks.minForks=1
npm run build
```

Backend selection (from `backend/`, with test dependencies installed and a disposable test database):

```powershell
python -m pytest -q tests/test_billing.py tests/test_purchases.py tests/test_purchase_commit.py tests/test_stock_ledger.py tests/test_negative_stock_policy.py tests/test_data_transfer.py tests/test_print_payload.py tests/test_print_and_einvoice_pure.py tests/test_sync_idempotency.py tests/test_sync_paid_state_parity.py
python -m pytest -q -rs tests/test_rls_policies.py tests/test_rls_postgres.py
```

The local backend run used an ignored Python 3.12 environment and a guarded runner that forced `test_bizassist.db`, disabled telemetry/chat memory, and denied external network access. Windows sandboxing blocked the loopback socket pair required by TestClient; the successful run used the same guarded runner outside that sandbox. No live business records were created or restored. This was a selected backend suite, not the entire backend test collection.

## Loading measurements

The billing main entry decreased from 1,419.23 kB (gzip 368.91 kB) to 659.35 kB (gzip 185.79 kB): about 54% less raw JavaScript and 50% less compressed JavaScript in the initial entry. The total application still downloads additional routes when needed; this is not a measured 54% improvement in page-load time.

Settings is deferred at 184.37 kB (gzip 44.59 kB), Stock at 192.80 kB (gzip 49.49 kB), and Contacts/Payments at 75.46 kB (gzip 17.10 kB). Vite still warns that the eager main chunk exceeds 500 kB. Further Sales/runtime splitting can be considered separately while preserving checkout's offline behavior.

## Browser checks

Reviewed in the Codex in-app browser against localhost:

- Light and dark billing views at phone dimensions, including Home/Dashboard, navigation, Settings/Profile, custom palette editor, search and Purchase Bills.
- Narrow 360-pixel Stock, Reports and Contacts pages: no document-wide horizontal overflow; wide tables/toolbars retain their internal scrolling.
- Purchase empty state centered within a 390-pixel viewport.
- Billing Counter's portrait rotation guard and usable 844-by-390 landscape layout. No sale or payment was submitted.
- Desktop Settings/Profile at 1280 pixels: one visible settings tablist and aligned fields/section navigation.
- Mobile drawer keyboard opening, Tab/Shift+Tab containment, Escape dismissal and restored toggle focus.
- Field Team signup at 360-by-640: the top is reachable and the tall form scrolls. Authenticated Field Team routes were reviewed in code, not exercised using a live staff account.

Theme was restored to Light after the temporary dark-mode checks. Temporary viewport overrides were reset after review. Screenshots remain local review artifacts and are not included in Git.

## Remaining verification boundaries

- Physical 58/80 mm thermal output requires the actual printer. Print payload/component tests do not establish paper alignment.
- Live two-server/offline reconnect, multi-terminal behavior and local/cloud mode transitions still require a staging exercise on separate endpoints/devices.
- Full deployed Postgres backup recovery and real RLS enforcement require a disposable staging Postgres database. Fail-closed RLS is implemented in migration `9c2f4b8a1d3e` with subsequent hardening, but the skipped live suite is not a deployment pass.
- No current authenticated Playwright multi-server E2E or production data repair was performed in this release review.

Publishing to GitHub and the Hugging Face repository updates Git. Hugging Face serves the backend; frontend deployment/build status must be checked through its own hosting pipeline.
