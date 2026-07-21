# Money Workspace Redesign — plan

*Goal: collapse the scattered Contacts + Transactions pages into ONE "Money"
workspace where each concept has a single home, status is a filter (not a
parallel tab), and you drill into a party instead of hopping between pages.*

Status: **plan only — no code yet.** Approve / mark up before build.

---

## 1. The problem (why it feels cluttered)

Today the same idea lives in two places, so one task touches two pages:

| Concept | Lives in Contacts | Also lives in Transactions |
|---|---|---|
| Outstanding / dues | per-customer column | "Pending Dues" tab |
| Invoices | "Other Invoices" + per-customer "View Invoices" | "Invoices" tab |
| Settle a customer | row button | "Settle Dues" button |
| Returns / credit notes | raise-return modal | "Credit Notes" tab |
| Record a payment | (implied via reminder) | "Record Payment" |

Net: "this customer paid me ₹1000" makes you visit Contacts → note dues →
Transactions → Record/Settle → back to Contacts to confirm. That is the
"going here and there" feeling.

---

## 2. Target information architecture

**One workspace: "Money"** (replaces the Khata Contacts/Transactions split).
Three primary views in a single top bar, each with *filter chips* instead of
sibling tabs:

```
Money
├── Parties        (default)   — who owes what; drill into a party account
├── Invoices                   — every sales document; filter by status
└── Cashbook                   — money in/out (receipts + expenses)
```

Principles enforced:
1. **One concept, one home.** Pending Dues, Other Invoices, per-customer invoice
   lists → all become *filters/drill-downs*, never separate tabs.
2. **Status is a filter, not a tab.** Chips (All · Unpaid · Partial · Paid ·
   Returns) over one list.
3. **Drill-down beats tab-hopping.** Clicking a party opens their whole account
   in place.
4. **One primary action per row; the rest under a "⋯" menu.**

---

## 3. Screen by screen

### 3.1 Parties (default view)
- One list of **customers + vendors** (toggle chip: Customers · Vendors · All),
  each row: name, phone, **outstanding**, **advance on account** (credit), last
  activity.
- Primary action: **Open** (drill-in). Overflow "⋯": Settle · Remind · Edit ·
  Add.
- Balance filter chip: All · Owes me · I owe · Settled (reuses the existing
  "All Balances" control).
- **Absorbs:** the current Customers/Vendors tabs and the per-row button cluster.

### 3.2 Party account (drill-down — the key screen)
Opening a party shows *everything for that party on one screen* — no page hop:
- Header: name, contact, **outstanding**, **advance/credit**, credit limit/days.
- Tabs *within* the party (light): **Ledger** (invoices + payments interleaved),
  **Invoices**, **Payments**, **Returns**.
- Actions in one place: **Settle dues** (FIFO modal, preset to this party) ·
  **Record payment** · **Raise return** · **Send reminder** · **New sale**.
- **Absorbs:** "View Invoices", the party-detail modal, Settle, Send Reminder,
  the return modal — they stop being scattered.
- **Reuses:** `SettleDuesModal` (preset), `InvoiceAccountPanel`, `SaleReturnModal`,
  `GET /customers/{id}/ledger` (already returns entries + `credit_balance`).

### 3.3 Invoices view
- One table of all sales invoices (`GET /invoices`) with **filter chips**:
  All · Unpaid · Partial · Paid · Returns(credit notes) · No-customer(casual).
- Norms-aware **Actions** column (already built in `InvoicesListView`):
  View · Payment (if `can_record_payment`) · Return (if `can_return`).
  **No Edit** on finalized invoices — corrections via credit/debit note.
- **Absorbs:** "Other Invoices" (= No-customer filter) and "Pending Dues"
  (= Unpaid/Partial filter) — they disappear as separate tabs.

### 3.4 Cashbook view
- One running list of **money in/out**: receipts (`/payments`) + expenses
  (`/billing/expenses`), newest first, with chips: All · Received · Paid ·
  Expenses.
- Row → opens the linked invoice account.
- **Absorbs:** the All/Received/Made/Expenses tabs into one filtered cashbook.
- **Credit Notes** show under Invoices → Returns filter (not a separate tab).

---

## 4. Current → new mapping (nothing is lost)

| Today | Tomorrow |
|---|---|
| Khata: Contacts / Transactions tabs | Money workspace: Parties / Invoices / Cashbook |
| Contacts: Customers / Vendors | Parties, with a Customers/Vendors chip |
| Contacts: Other Invoices | Invoices → "No-customer" filter |
| Contacts row: View Invoices | Party account → Invoices tab |
| Contacts row: Settle | Party account action + Parties "⋯" |
| Contacts row: Send Reminder | Party account action + Parties "⋯" |
| Payments: All / Received / Made | Cashbook filters |
| Payments: Pending Dues | Invoices → Unpaid/Partial filter |
| Payments: Invoices | Invoices view (primary) |
| Payments: Credit Notes | Invoices → Returns filter |
| Payments: Expenses | Cashbook → Expenses filter |
| Record Payment / Log Expense / Settle | Kept as actions, surfaced from the relevant view |

---

## 5. Backend — mostly reuse, one small add

Already available and sufficient: `/customers`, `/customers/{id}/ledger`
(+`credit_balance`), `/customers/{id}/settle`, `/vendors`, `/invoices`
(+`can_record_payment`/`can_return`/`editable`), `/invoices/{id}/account`,
`/payments`, `/credit-notes`, `/billing/expenses`.

Optional nicety (one endpoint) to make the party-account screen a single fetch:
- `GET /customers/{id}/account` → `{ profile, outstanding, credit_balance,
  invoices[], payments[], returns[] }` (aggregates what the drill-down needs).
  Not required for v1 — the drill-down can call the existing endpoints.

No schema changes. No money-path changes.

---

## 6. Build order (safe, shippable increments)

0. **Extract the shared invoice pieces FIRST** — `useInvoiceActions(authFetch)`
   (print/share/return/view/recordPayment, lifted from Parties.jsx) + an
   `<InvoiceRow>`/`<InvoiceActions>` component gated by the norms flags. Nothing
   else is consistent until this exists. Prove the seam by pointing the existing
   `InvoicesListView` at it (no visible change).
1. **Party account drill-down** (biggest UX win): a `PartyAccount` screen that
   composes existing pieces (ledger + the shared `<InvoiceRow>` list filtered to
   the customer + `SettleDuesModal` + `SaleReturnModal`). Clicking a party row
   opens it; the old "Invoices for X" modal is retired.
2. **Invoices view with filter chips** — the primary Invoices screen using the
   SAME `<InvoiceRow>`; retire "Pending Dues" / "Other Invoices" tabs as chips.
3. **Cashbook** — merge the payment/expense tabs into one filtered list
   (`<PaymentRow>` + `usePaymentActions`).
4. **Unify the shell** — the "Money" workspace top bar (already themed with
   `WorkspaceTopBar`); keep old routes as redirects so nothing 404s.
5. **De-clutter rows** — collapse secondary buttons into a "⋯" overflow.
6. **Retire the old cluster** — redirect `/parties*` → `/money`, drop the extra
   nav entry, delete `Khata.jsx` + dead parts of `Parties.jsx`/`Payments.jsx`
   and tests. Only after parity is confirmed on real data.

Each step is independently shippable and independently revertible; the current
pages keep working until the step that replaces them.

---

## 7b. The key to "unified & clean": ONE invoice, ONE action set

Every place an invoice appears (Party drill-down, Invoices view, and the old
"Invoices for X" modal) must show the **same row and the same actions** — no
per-screen variants. This is what removes the "different in every place" feeling.

**Shared pieces (build once, reuse everywhere):**

- `useInvoiceActions(authFetch)` — a hook that owns the invoice action logic that
  today lives inline in Parties.jsx:
  - `print(invoiceNo)`       ← existing `handlePrintInvoice`
  - `share(invoice, party)`  ← existing `handleWhatsAppShareInvoice`
  - `openReturn(invoice)`    ← existing `handleOpenReturn` (+ the `SaleReturnModal`)
  - `view(invoiceNo)`        ← open `InvoiceViewerModal`
  - `recordPayment(invoice)` ← open `RecordPaymentModal` preset to the invoice
  Returned as one object so any view wires the same handlers.

- `<InvoiceRow>` / `<InvoiceActions invoice=… norms=…>` — one presentational
  component rendering the columns (Invoice# · Date · Items · Total · Outstanding
  · Status) and the action buttons, **gated by the backend norms flags**
  (`can_record_payment`, `can_return`, `editable`). So:
  - Paid invoice → Print · Share · Return (no Payment).
  - Unpaid invoice → Print · Share · **Payment** · Return.
  - Credit note → Print · Share only.
  - **No Edit** on finalized invoices (norms) — corrections via credit/debit note.

**Where it's used (identical everywhere):**
1. **Party drill-down** — "View Invoices" for a customer = this row list
   **grouped/filtered to that customer** (replaces the old "Invoices for X"
   modal), with the same action buttons.
2. **Invoices view** — the same rows over ALL invoices, with the status filter
   chips on top.
3. The old modal is retired; both surfaces render `<InvoiceRow>`.

Net effect: Return, Print, Share, Payment behave **exactly the same** whether you
reached the invoice from a customer or from the global list — one code path, one
look. `InvoicesListView` (already built) folds into this by adopting
`useInvoiceActions` + `<InvoiceActions>` instead of its own inline buttons.

**Apply the same principle to the other views:**
- **Payments/receipts** → one `<PaymentRow>` + `usePaymentActions` (view linked
  invoice, delete/void where allowed), reused by Cashbook and the party account.
- **Parties** → one `<PartyRow>` (name · phone · outstanding · advance · actions)
  reused by the Parties list and any "pick a customer" surface.

So the rule for the whole workspace: **a thing has one row component and one
actions hook, reused across every screen it appears on.**

---

## 7. Guardrails / risks

- **Keep routes alive:** `/parties/contacts` and `/parties/payments` become
  redirects into the new views so bookmarks/tests don't break.
- **Norms:** no invoice editing of finalized bills (credit/debit note only) —
  already reflected in the `editable` gate.
- **Offline/sync untouched:** this is presentation only; no endpoint or entity
  renames, so the outbox and sync map are unaffected.
- **Tests:** each view keeps/gets component tests; the merged-workspace test
  updates to the new labels.
