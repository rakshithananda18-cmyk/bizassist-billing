# R5 — `Sales.jsx` Decomposition Plan

**Goal:** break the ~2,856-line `frontend-billing/src/pages/Sales.jsx` god-component into
focused, testable pieces **without changing behaviour**, one extraction at a time, each
verified by `npm run dev` before the next. No money-math or state-ownership changes —
pure structural moves.

**Why incremental + verify-each-step:** the POS counter is the painkiller. A silent
render break here is high-cost, and the frontend can't be rendered/verified by the agent.
So every step below is independently shippable and independently revertible.

---

## Current state

- `Sales.jsx`: **2,856 lines**, one `export default function Sales()` with ~30 `useState`
  hooks, the multi-tab POS, product search, price selector, cart table, totals bar,
  payment flow, the thermal receipt, and several inline modals.
- Already extracted (good): `components/sales/CheckoutModal.jsx`, `PosTotalBar.jsx`,
  `TotalBreakupModal.jsx`, `TenderChips.jsx`, `InvoiceBreakdownCard.jsx`;
  `hooks/usePaymentFlow.js`; `utils/invoiceMath.js`, `utils/printLayout.js`.
- Pure helpers already importable: `lineTotal`, `gstSlabBreakdown`, `changeDue`,
  `numberToWords`, `getHeaderLayout`.

## Target structure

```
pages/Sales.jsx                  ← orchestration + state owner only (~1,200 lines target)
components/sales/
  ThermalReceipt.jsx             ← step 1 (presentational; print portal)
  CartTable.jsx                  ← step 3 (item rows + footer)
  ProductSearchBar.jsx           ← step 4 (search + dropdown + price selector)
  PosTabBar.jsx                  ← step 5 (bill tabs)
  PrintSettingsModal.jsx         ← step 6
  HotkeySettingsModal.jsx        ← step 6
hooks/
  usePosTabs.js                  ← step 7 (tabs state machine) — OPTIONAL, higher risk
```

---

## Extraction order (lowest risk → highest)

### Step 1 — `ThermalReceipt` (DO THIS FIRST)
Lines ~2583–2853 (the `createPortal` block) **plus** `renderReceiptHeaderLine` (772–797).
Purely presentational; owns no state. Move both into `components/sales/ThermalReceipt.jsx`
and render `<ThermalReceipt … />` in place.

**Props contract (all read-only):**
`settings`, `profile`, `activeTab`, `form`, `customers`, `user`, `isIntrastate`,
`subtotal`, `billDiscountAmt`, `cgstAmt`, `sgstAmt`, `igstAmt`, `cashDiscountAmt`,
`roundOff`, `grandTotal`, `payable`, `changeToReturn`, `colFooter`.
Internal imports: `getHeaderLayout`, `lineTotal`, `gstSlabBreakdown`, `numberToWords`,
`getTodayDateStr`.

**Why first:** zero state moves, one JSX block + one helper, biggest line reduction
(~290 lines) for the least risk. `renderReceiptHeaderLine` only reads `settings`+`profile`.

**Verify:** `npm run dev` → ring up a bill → print/preview the thermal receipt; confirm
header alignment, item rows, per-slab GST table, cash-discount/round-off/payable lines,
FSSAI/terms/signature blocks all render exactly as before (compare to `BENCHMARK_RECEIPT_MR_TRADERS.md`).

### Step 2 — receipt unit test (optional, cheap)
With `ThermalReceipt` isolated, add a render test (React Testing Library) feeding the
M.R. Traders benchmark line items and asserting payable + "You have Saved" text.

### Step 3 — `CartTable`
The item-rows table + column-order/footer block in the main return (~1482–2128, excluding
`<PosTotalBar>`). Owns no state but calls handlers — pass them as props
(`onQtyChange`, `onSelectPrice`, `onRemoveRow`, `handleMoveColumn`, …) + `columnOrder`,
`funcKeys`, `products`, `form`. Medium risk (many handlers); verify keyboard/barcode entry,
qty edit, price selector, column reorder.

### Step 4 — `ProductSearchBar`
Search input + results dropdown + price selector popover (~1024–1134 logic + its JSX).
Pass `searchQuery`, `selectedIndex`, results, `onSelectProduct`, `onSearchKeyDown`.

### Step 5 — `PosTabBar`
The bill-tabs strip. Reads `tabs`, `activeTabId`; calls `onNewBill`, `onSwitchTab`,
`onCloseTab`. Low–medium risk.

### Step 6 — `PrintSettingsModal` + `HotkeySettingsModal`
The two inline modals behind `showSettingsModal` / `showHotkeySettingsModal`. Self-contained;
pass the relevant settings slice + an `onSave`/`onClose`.

### Step 7 (OPTIONAL, defer) — `usePosTabs` hook
Extract the tab state machine (`tabs`, `activeTabId`, `handleNewBill`, `handleMinimize`,
`closeTab`, localStorage sync) into a hook. **Highest risk** (owns core state); do last,
only if the component is still unwieldy after 1–6.

---

## Rules for every step
1. **One extraction per commit.** Move code verbatim; only add the `props` boundary.
2. **No logic edits** during a move — if you spot a bug, fix it in a *separate* commit.
3. **Verify in `npm run dev`** before starting the next step (checklist above).
4. Keep `usePaymentFlow` as the seam for payment state — components stay presentational.
5. Money math stays in `utils/invoiceMath.js`; never inline a calculation into a component.

## Done when
`Sales.jsx` is orchestration + state only (~1,200 lines), each extracted piece is a
focused file with an explicit prop contract, and the full POS flow (search → cart →
checkout → receipt → new bill) is visually verified unchanged.
