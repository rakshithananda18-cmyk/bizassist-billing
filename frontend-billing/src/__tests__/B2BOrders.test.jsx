// ============================================================================
// ██  DEAD CODE — COMMENTED OUT 2026-07-31. DO NOT UNCOMMENT WITHOUT READING THIS.
// ============================================================================
// Tested pages/B2BOrders.jsx, which is superseded and now commented out.
// Its coverage is duplicated by __tests__/B2BOrdersTab.test.jsx, which asserts
// the same 'Stock received' badge against the LIVE b2b/components/OrdersTab.jsx.
//
// A test kept alive only to justify keeping the code it tests is the tail
// wagging the dog — and it reports green for a page the app cannot route to.
//
// Commented out rather than deleted so the change is reversible and can soak
// through a release. Full analysis: docs/CLEANUP_PLAN_2026-07-31.md §1c
// ============================================================================

import { describe, it, expect } from 'vitest'

// A fully commented-out test FILE makes vitest fail with "No test suite found",
// which is a hard error, not a skip. So the file keeps one live, skipped suite:
// it documents the retirement, keeps the runner happy, and leaves the original
// body below for the soak period.
describe.skip('B2BOrders (retired 2026-07-31)', () => {
  it('is superseded by B2BOrdersTab.test.jsx against the live component', () => {
    // The behaviour this file covered — the "Stock received" badge on a
    // completed purchase order carrying a seller_invoice_id — is asserted in
    // __tests__/B2BOrdersTab.test.jsx against b2b/components/OrdersTab.jsx,
    // which is the component the app actually renders.
    expect(true).toBe(true)
  })
})


// // Render tests for <Orders> focused on the Phase-4 BUYER auto-stock-in UI:
// //   • a completed outgoing (purchase) order shows the "<ImportIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Stock received" badge
// //     once it carries a seller_invoice_id,
// //   • the same badge does NOT show for a still-in-flight order.
// // AuthContext, AppLayout and the SSE fetch are mocked so the page renders in
// // isolation (the SSE stream resolves immediately as "done").
// import { describe, it, expect, vi, beforeEach } from 'vitest'
// import { render, screen, fireEvent } from '@testing-library/react'
// import B2BOrders from '../pages/B2BOrders'
//
// // Passthrough layout — avoids pulling in router/nav.
// vi.mock('../layouts/AppLayout', () => ({
//   default: ({ children }) => <div>{children}</div>,
// }))
//
// const OUTGOING_ORDERS = [
//   {
//     id: 1, order_number: 'ORD-20260620-AAAA', order_date: '2026-06-20',
//     created_at: '2026-06-20T10:00:00', status: 'completed',
//     buyer_name: 'My Shop', buyer_bizid: 'BA-BUYER', seller_name: 'Acme Supply', seller_bizid: 'BA-SELLER',
//     subtotal: 500, cgst_total: 0, sgst_total: 0, igst_total: 0, total_amount: 500,
//     seller_invoice_id: 42, notes: '', items: [],
//   },
//   {
//     id: 2, order_number: 'ORD-20260620-BBBB', order_date: '2026-06-20',
//     created_at: '2026-06-20T10:00:00', status: 'dispatched',
//     buyer_name: 'My Shop', buyer_bizid: 'BA-BUYER', seller_name: 'Acme Supply', seller_bizid: 'BA-SELLER',
//     subtotal: 200, cgst_total: 0, sgst_total: 0, igst_total: 0, total_amount: 200,
//     seller_invoice_id: null, notes: '', items: [],
//   },
// ]
//
// const authFetch = vi.fn(async (url) => {
//   if (url.includes('/connections/orders')) {
//     return { ok: true, json: async () => OUTGOING_ORDERS }
//   }
//   return { ok: true, json: async () => ([]) }
// })
//
// vi.mock('../contexts/AuthContext', () => ({
//   useAuth: () => ({
//     authFetch,
//     token: 'test-token',
//     user: { id: 1, business_name: 'My Shop' },
//   }),
// }))
//
// beforeEach(() => {
//   authFetch.mockClear()
//   global.fetch = vi.fn(async (url) => {
//     if (String(url).includes('/realtime/ticket')) {
//       return { ok: true, json: async () => ({ ticket: 'test-ticket' }) }
//     }
//     return { ok: true, json: async () => ({}) }
//   })
//   global.EventSource = vi.fn(() => ({
//     close: vi.fn(),
//     onmessage: null,
//     onerror: null,
//   }))
// })
//
// describe('Orders — buyer auto-stock-in UI', () => {
//   it('shows "Stock received" badge on a completed purchase order with a seller invoice', async () => {
//     render(<B2BOrders />)
//     // Switch to the buyer (outgoing/purchases) tab.
//     fireEvent.click(screen.getByText(/Outgoing Orders/))
//     expect(await screen.findByText(/Stock received/)).toBeInTheDocument()
//   })
//
//   it('does NOT show the badge for an order that is not yet completed', async () => {
//     render(<B2BOrders />)
//     fireEvent.click(screen.getByText(/Outgoing Orders/))
//     // Wait for the dispatched order row to render, then assert exactly one badge.
//     await screen.findByText('ORD-20260620-BBBB')
//     expect(screen.getAllByText(/Stock received/)).toHaveLength(1)
//   })
// })
//
// import { ImportIcon } from '../components/Icons'
//