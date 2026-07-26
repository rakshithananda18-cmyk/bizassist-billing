// ============================================================================
// src/b2b — the B2B commerce module.
// ----------------------------------------------------------------------------
// Everything needed to browse a supplier's catalogue, place an order, track
// fulfilment, and manage who you're connected to. Self-contained on purpose:
// the same module is meant to back a future RETAIL CUSTOMER app, where the
// "supplier" is the shop and the "buyer" is a consumer.
//
// ── Layers, cleanest to most coupled ────────────────────────────────────────
//   b2bClient.js      transport. Takes `authFetch` as an argument — no React,
//                     no context, no imports from this app beyond `config`.
//   useOrderCart.js   the money maths (line totals, GST split, order total).
//                     Pure functions, unit-tested without a DOM.
//   orderStatus.js    the fulfilment state machine.
//   useB2B*.js        state + orchestration. React, but no JSX.
//   components/       rendering. Depends on shared Icons / CustomSelect /
//                     ScanSearchField / useResizableColumns — the only things a
//                     port would need to supply.
//
// ── What a retail customer app would reuse ──────────────────────────────────
// b2bClient + useOrderCart + orderStatus verbatim; useB2BOrders/Connections with
// a different auth transport; OrderDeskTab with a consumer-facing shell instead
// of pages/B2B.jsx. Nothing in this folder imports AppLayout, AuthContext or a
// router — the page above it owns all three.
//
// ── One hard rule ───────────────────────────────────────────────────────────
// Every call travels on the SESSION'S OWN backend. The token is issued by, and
// only valid on, the backend the user logged into — pointing a request at a
// different host makes that host resolve the user id against its own users
// table, where the same integer is a different business. Cloud authority is
// still the model; reaching the cloud is the local BACKEND's job, not the
// browser's. See the header of b2bClient.js.
// ============================================================================

// ── Transport ───────────────────────────────────────────────────────────────
export * as b2bClient from './b2bClient'
export { apiPath } from './b2bClient'

// ── Domain logic (portable, no React) ───────────────────────────────────────
export { computeLine, computeTotals, default as useOrderCart } from './useOrderCart'
export { STATUS_FLOW } from './orderStatus'

// ── State ───────────────────────────────────────────────────────────────────
export { useB2BConnections } from './useB2BConnections'
export { useB2BOrders, counterpartyOf } from './useB2BOrders'
export { useB2BRealtime } from './useB2BRealtime'

// ── UI ──────────────────────────────────────────────────────────────────────
export { default as OrderDeskTab, findByCode } from './components/OrderDeskTab'
export { default as OrdersTab, actionsFor } from './components/OrdersTab'
export { default as ConnectionsTab } from './components/ConnectionsTab'
export { default as OrderDetailModal } from './components/OrderDetailModal'
export { default as OfflineNotice } from './components/OfflineNotice'
