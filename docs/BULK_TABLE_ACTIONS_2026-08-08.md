# Bulk table actions — select, preview, approve, all-or-nothing

**Status 2026-08-09:** approved; **Phase 1 complete** (`ca84c93` + this change).
See *Progress* at the foot of this file for what exists versus what is planned.

## Context

Every list table is read-only per row today. Disabling ten products or reminding
thirty customers means opening them one at a time. The ask: **checkboxes on every
list table**, with the actions appropriate to that table shown beside its
filter/sort controls.

Three constraints from the user shape everything:

1. **All-or-nothing.** Either every selected row applies or none does. Failures
   surface with reasons — no silent partial state.
2. **Preview → approve for every mutating action**, not just destructive ones.
3. **The AI agent must be able to drive the same actions** and show the preview.

Constraint 3 decides the architecture, because that machinery already exists.

### Two corrections to earlier statements in this session

- I said *"no table has row selection"*. Wrong. `pages/Stock.jsx:164-171` already
  has `selectedIds` / `toggleSelected`, passed to `LabelPrintModal` as
  `preselectIds` (`:1437`). **`toggleSelected` is never called** — the state is
  wired with no checkbox to drive it. Catalogue is half-built, not greenfield.
- I said *"`DELETE /expenses/{id}` exists"*. It exists and **returns 405** —
  expenses are append-only (`core/api/payments.py:502-526`) and sit on the sync
  `APPEND_ONLY_DELETE_BLOCKLIST` (`routes/sync.py:355-372`).

---

## Two tiers of action

Separating these is what lets **every** table have selection without inventing
unsafe mutations.

| | Tier A — Export / Print | Tier B — Mutations |
|---|---|---|
| Applies to | **every list table** | tables with a safe, existing per-row mutation |
| Preview step | none — it changes nothing | **always** |
| Backend | none (CSV built from rows already in memory) | action registry entry |
| Risk | zero | needs all-or-nothing + rollback |

Tier A is why "all tables" is achievable: selection is universally useful for
getting data out, even on an append-only ledger.

---

## Architecture for Tier B: the existing action registry

`backend/services/actions.py` already implements preview→approve→execute, and
its own comment states the intent:

> Phase-0 write rail #3: per-business, per-action daily cap — enforced at the
> dispatcher so EVERY entry point (**HTTP route today, agent runtime tomorrow**)
> hits the same wall.

Registering there rather than building `/api/bulk/*` inherits five tested rails:

| Rail | Where | Gives us |
|---|---|---|
| Preview → confirm | `routes/actions.py` `/action/preview`, `/action/execute` | the approval step |
| Fingerprint binding | `actions.py::preview_fingerprint`, re-checked at execute | **428** if data drifted between preview and confirm |
| Replay wall | `core/sync/idempotency.py::ReplayGuard` | a double-fired confirm cannot run twice |
| Daily cap | `services/action_rails.py::check_daily_cap` | per-action budget; a runaway loop cannot mass-mutate |
| Agent access | `services/ai_router.py` ACTION route | AI proposes it, same preview renders |

`ACTIONS` is a plain dict `{key: {"preview": fn, "execute": fn}}`
(`services/actions.py:529`). Each action is two functions and a registry line.

**Rejected:** a parallel `/api/bulk/*` surface — it would duplicate the confirm
flow, fingerprint check and replay guard, and the AI could not reach it. This
codebase has been bitten twice this session by two implementations of one
decision.

**Three existing actions are already bulk actions** needing only a new caller:
`send_payment_reminders`, `mark_invoice_paid`, `email_reminder_digest`.

### Delete and deactivate are always SEPARATE actions

Never one action with a `mode` flag. Separate registry keys give each its own
preview, its own confirm wording and **its own daily cap**, so an accidental
mass-deactivate cannot consume the delete budget or vice versa:

| Action | Reversible | Preview shows |
|---|---|---|
| `bulk_set_product_active` (`{ids, active: bool}`) | yes | the rows and their current state |
| `bulk_delete_products` (`{ids}`) | **no** | the rows **plus per-row history blockers** — anything with invoices/ledger history comes back `blocked` and, under all-or-nothing, stops the whole batch |

Same split for parties: `bulk_set_party_active` exists; there is no party delete.

---

## The all-or-nothing contract

The user chose all-or-nothing, so **no per-row SAVEPOINTs**:

```
preview(user_id, {ids: [...]})  → validate ALL rows → {items, blocked, summary}
execute(user_id, {ids: [...]})  → re-validate ALL; if anything blocked → write nothing;
                                   else apply all in ONE transaction, commit once
```

Every bulk `execute` **returns a structured result, never raises** — the
dispatcher (`services/actions.py:614-617`) swallows exceptions into `None`, which
would lose the reason and contradict "failures showing up":

```python
{"ok": False, "executed": 0,
 "blocked": [{"id": 41, "name": "Toor Dal 5kg", "reason": "has 3 invoices"}],
 "markdown": "Nothing was changed. 12 of 40 items are blocked:"}
```

### Non-negotiable rails (all verified in code)

| Rule | Source |
|---|---|
| Tenant filter in the **id-selection query itself** — `.filter(Product.business_id == bid, Product.id.in_(ids))`. Short results are reported not-found | `core/sync/tenant_scope.py` is a CI-enforced AST gate |
| Bulk delete loops **ORM `db.delete(obj)`**. `query(...).delete()` skips `Mapper.after_delete`, so the deletion never syncs and the row lives on in the cloud forever | `core/api/products.py:405-408` (finding C-6) |
| Never `db.rollback()` inside a row loop | `services/import_data.py:91` — the counter-example that double-counts |
| `guard.store()` **after** `db.commit()` | `core/sync/idempotency.py:32-34` |
| Counters count what **landed** | `docs/ARCHITECTURE.md:117-120` |
| Post-commit triple: `db.commit()` → `trigger_data_sync(bid, db)` → `background_tasks.add_task(realtime_manager.broadcast, …)` | e.g. `core/api/products.py:420-425` |
| Module's existing logger, `[TAG] … biz=%s`, `exc_info=True` on unexpected | `core/api/products.py:426` |

---

## Table matrix — every list table

All get checkbox selection and Tier A. Tier B varies.

| # | Table | Entity | Tier B mutations | Notes / blockers |
|---|---|---|---|---|
| 1 | **Stock → Catalogue** `Stock.jsx:1018` | product | Print labels · Deactivate/Activate · Change category · **Delete** (separate) | Selection state already exists `:164-171`. `LabelPrintModal` already takes `preselectIds`. Per-row `toggleProductActive` `:1078`, `deleteProduct` `:1084`. Delete honours `_PRODUCT_HISTORY_REFS` (`products.py:339-346`) |
| 2 | **Contacts → Customers / Vendors** `Parties.jsx:623` | customer / vendor | Deactivate/Activate · Send reminders | `togglePartyActive` `:749`. Reminders reuse existing `send_payment_reminders` |
| 3 | **Contacts → Other Invoices** `Parties.jsx:623` | invoice | Mark paid | Third `<thead>` variant of the same table |
| 4 | **Transactions → Pending Dues** `Payments.jsx:1138` | outstanding invoice | Send reminders | Pure reuse |
| 5 | **Transactions → main** `Payments.jsx:1348` | union: payment / due / credit note / expense / settlement | *export only* | Mixed row types — a mutation would mean different behaviour per row, which all-or-nothing cannot express cleanly |
| 6 | **Transactions → Expenses** `Payments.jsx:1035` | expense | *export only* | **Append-only.** Delete is a deliberate 405; on the sync delete blocklist. A reversal command does not exist yet — if you want bulk void, that command must be built first |
| 7 | **Transactions → Credit Notes** `Payments.jsx:1240` | credit note | *export only* | Financial documents; reversal is issuing another note |
| 8 | **Invoices list** `InvoicesListView.jsx:217` | invoice | Mark paid · Print | Mounted in **3** places — build once, all benefit |
| 9 | **Money → Parties** `Money.jsx:108` | customer | Send reminders | Per-row `sendReminder` `:133-139` |
| 10 | **Money → Party ledger** `PartyAccount.jsx:79` | invoice | Mark paid · Print | Same actions as #8 |
| 11 | **Money → Cashbook** `CashbookView.jsx:53` | payment / expense | *export only* | Read-only ledger view |
| 12 | **Purchases → Bills / Returns** `Purchases.jsx:599` | purchase bill / debit note | *export only* | Confirming a bill is `accept_supplier_invoice`, a money-posting flow that stays one-at-a-time |
| 13-14 | **B2B → Outgoing / Incoming Orders** `OrdersTab.jsx:234` | B2B order | Change status | Must respect `actionsFor()` `:45-57` — illegal transitions come back `blocked` |
| 15-16 | **B2B → Connections** (suppliers / customers) `ConnectionsTab.jsx:486,570` | connection | Revoke | Per-relationship, but bulk revoke is coherent |
| 17 | **Settings → Staff** `Settings.jsx:2107` | staff | Deactivate | Not delete — removing staff orphans their history |
| 18 | **Stock → Godowns transfers** `Stock.jsx:1206` | stock transfer | *export only* | No per-row action exists today |
| 19 | **Stock → Stock Intake** `StockIntakeSheet.jsx:1057` | draft line | **Remove selected** | Client-only — unsaved drafts, no endpoint, no preview |
| 20 | **Dashboard → Low Stock** `Dashboard.jsx:289` | product | *export only* | Mini list; deep actions belong on Catalogue |
| 21 | **Dashboard → Recent Invoices** `Dashboard.jsx:318` | invoice | *export only* | Same |

**Genuinely not list tables** (no row identity to select): POS cart and its
row components, `components/reports/*` renderings, `ThermalReceipt`, the
`invoice/templates/*` print layouts, Settings invoice-preview mockups, and
single-record editors (`PurchaseDetailModal`, `SettleDuesModal`,
`SaleReturnModal`, `IntakeConfirmSheet`, `OrderDetailModal`). Excluded.

---

## Frontend design

There is **no shared `DataTable`** — every table is a hand-rolled
`<table className="data-table">`. So extract, do not duplicate:

- **`hooks/useRowSelection.js`** — `{selected, toggle, toggleAll, clear, isAllSelected}` over a `Set`. Model on `Stock.jsx:167`.
- **`components/common/BulkActionBar.jsx`** — renders into the existing `WorkspaceTopBar` `actions` slot (`WorkspaceTopBar.jsx:37`), beside `FilterDropdown`/`SortDropdown`, which is where the user asked for it. Shows "N selected" + that table's actions + Clear.
- **`components/common/BulkPreviewModal.jsx`** — the approve step. Calls `/action/preview`, lists what changes and what is **blocked with reasons**, enables Confirm only when the preview says `executable`. Confirm posts `/action/execute`.

**Correction — bulk buttons must NOT carry `ws-bar-action`.** An earlier draft of
this file said they fold into the `⋯` overflow automatically. They do not. The
overflow menus are built from each page's own `toolbarActions` array
(`Stock.jsx:869`), not by scanning the DOM, so a button carrying that class is
merely *hidden* below the container breakpoint with no menu entry to reach it —
the exact trap `index.css:6432` already records for `New Invoice` and `Add
Party`. While rows are selected these are the primary actions, so they stay put.

### The `/action/execute` contract has three load-bearing parts

Only one of them was in the original plan. `frontend-ai`'s `Chat.jsx`
`runAction`/`confirmAction` is the proven caller; `BulkPreviewModal` mirrors it.

1. **`confirm_token`** — `/action/preview` mints an HMAC over (business, action,
   exact params, preview content, expiry) and `/action/execute` refuses without
   it (`routes/actions.py:71-81`). Not optional; omitting it is a 428.
2. **Execute sends the params that were PREVIEWED**, not `preview.params`. The
   preview envelope narrows `params.ids` to the rows that would actually change
   (`services/actions.py:609`), but the token is signed over what the client
   posted to *preview* (`routes/actions.py:56`). Echoing the narrowed set back
   changes the params hash and the token stops verifying.
3. **`X-Client-Request-Id`** — the ReplayGuard wall. One id per confirm intent,
   held across retries of that confirm; a fresh id on retry defeats the wall.

A 428 means the rows drifted under the preview, so the modal **re-previews**
rather than leaving a Confirm button that can only fail again. And a 200 is not
by itself success: `execute` never raises, so a refusal arrives as
`ok: false` with `blocked` attached.
- **`utils/exportRows.js`** — Tier A CSV from in-memory rows. No backend.
- **Checkbox column** — copy the one existing precedent, `components/ImportReviewModal.jsx:107,118`.

Destructive actions get a distinct confirm: the modal requires typing the row
count for `bulk_delete_products`, and the button uses the danger style.

---

## Testing

Backend (`backend/tests/`, self-contained `_signup` per `test_roles.py:33-40`;
`tests/planhelpers.py::grant_pro` where Pro-gated):

- **Rollback** — capture counts → batch with one bad row → assert every touched table's count unchanged and stock untouched. Idiom: `test_negative_stock_policy.py:115-129`.
- **Blocked reporting** — a product with invoice history returns in `blocked` with a reason, and *nothing else in the batch applied*.
- **Delete ≠ deactivate** — deactivate on a history-bearing product succeeds; delete on the same product is blocked. Same ids, opposite outcomes.
- **Tenant isolation** — ids from another business report not-found, never mutate.
- **Fingerprint drift** — preview, mutate underneath, confirm → **428**.
- **Replay** — same `X-Client-Request-Id` twice executes once.
- **Delete syncs** — after bulk delete, assert `sync_queue` rows exist (guards finding C-6).
- **Gating** — 402 free / 403 cashier with `SUBSCRIPTION_ENFORCED` unset (`test_plan_gating.py:103-116`, `test_roles.py:69-130`).
- Order-independent — `pytest-randomly` shuffles (`ci.yml:72`).

Frontend (must be `.test.jsx` or no DOM — `vite.config.js:34-40`): precedent is
`PartyDeactivate.test.jsx` (real page, mocked `AuthContext`/`AppLayout`,
`closest('tr')`, `fireEvent`). Cover select-one / select-all / clear, bar hidden
with no selection, Confirm disabled while blocked, correct ids sent, and export
producing the right CSV rows.

---

## Phases

1. **Shared plumbing + Catalogue** — `useRowSelection`, `BulkActionBar`, `BulkPreviewModal`, `exportRows`, checkbox column in Stock; actions: print labels, `bulk_set_product_active`. Proves preview, rollback and tests end-to-end.
2. **Tier A everywhere** — checkbox + Export on all remaining tables. Cheap once the hook exists, and satisfies "all tables" immediately.
3. **Reminders** — Contacts, Pending Dues, Money wired to the existing `send_payment_reminders`.
4. **`bulk_delete_products`** — history blockers, ORM-loop delete, typed confirmation, sync-queue test.
5. **Invoices + B2B + Staff** — `mark_invoice_paid`; B2B status respecting `actionsFor()`; staff deactivate.
6. **Intake "remove selected"** — client-only.

---

## Verification

- `cd backend && python -m pytest tests/ -n auto --dist loadscope -q` (2260 passing today)
- `cd frontend-billing && npx vitest run` (545 today) and `npx vite build`
- Manually: select 3 products → Deactivate → preview lists 3 → confirm → rows show inactive. Then select a product **with invoice history** → Delete → preview shows it blocked with the reason and Confirm stays disabled, while Deactivate on the same row still succeeds.
- After a bulk change, confirm `sync_queue` has one row per changed entity.


---

## Progress

### Done (`ca84c93`)

- `backend/services/actions.py` — `bulk_set_product_active` registered:
  `_bulk_products_lookup` (tenant filter inside the id query),
  `_bulk_active_preview`, `_bulk_active_execute`. One transaction, one commit,
  returns a structured result and never raises.
- `backend/services/action_rails.py` — explicit `bulk_set_product_active: 200`
  cap. Note the unit: **batches per day**, because the action writes one
  `ActionLog` per batch, not per row. Different unit from the emailing actions.
- `backend/tests/test_bulk_product_active.py` — 11 tests. All-or-nothing and
  cross-tenant isolation verified by disabling the guard and confirming three
  tests fail.
- `frontend-billing/src/hooks/useRowSelection.js` + 9 tests. Replaces the dead
  `selectedIds`/`toggleSelected` pair in `pages/Stock.jsx:164-171`.

### Done — Phase 1 complete

- `components/common/BulkActionBar.jsx` — "N selected" + actions + Clear, into
  the `WorkspaceTopBar` `actions` slot. Action shape matches `ContextMenu` and
  `toolbarActions`, so one array can feed a bar or a menu unchanged.
- `components/common/BulkPreviewModal.jsx` — owns the whole preview → confirm →
  execute round trip, so a table only says `{ action, params, label }`. Honours
  the three-part contract above and re-previews on 428.
- Checkbox column in the `pages/Stock.jsx` catalogue, wired to `useRowSelection`,
  the bar, and the existing `LabelPrintModal preselectIds` (which was reading
  the dead Set).
- `__tests__/BulkActions.test.jsx` — 7 tests: the wire contract (previewed
  params echoed, token sent, request id sent, 428 re-previews, blocked disables
  Confirm, `ok:false` surfaces) plus the Stock wiring (no bar until ticked,
  exact ids sent, select-all, Clear). 561 frontend tests green, `vite build` clean.

`'select'` had to be registered with `useResizableColumns` even though its
header carries no grip: the hook maps a column key to a body cell **by index**
(`useResizableColumns.js:107`), so an unregistered *leading* column shifts every
measurement one cell left and auto-fit sizes the wrong column. Trailing extras
are safe — leading ones are not.

### Next, in order

1. Phase 2 — Tier A (`utils/exportRows.js` + checkbox column) on the remaining
   tables. The two components are now shared, so each table is a wiring job.
2. Then phases 3-6 as listed above.
