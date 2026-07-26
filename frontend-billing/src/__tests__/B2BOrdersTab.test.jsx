// Render tests for <OrdersTab> — the shared incoming/outgoing order queue in
// the unified B2B workspace. Covers:
//   • the Phase-4 buyer auto-stock-in badge (shown only for a COMPLETED order
//     that carries a seller_invoice_id),
//   • the direction-dependent action rail (actionsFor),
//   • the counterparty column flipping between buyer and supplier.
// Pure renderer, so no auth/router/SSE mocking is needed.
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import OrdersTab, { actionsFor } from '../b2b/components/OrdersTab'

const ORDERS = [
  {
    id: 1, order_number: 'ORD-20260620-AAAA', order_date: '2026-06-20',
    created_at: '2026-06-20T10:00:00', status: 'completed',
    buyer_name: 'My Shop', buyer_bizid: 'BA-BUYER',
    seller_name: 'Acme Supply', seller_bizid: 'BA-SELLER',
    subtotal: 500, cgst_total: 0, sgst_total: 0, igst_total: 0, total_amount: 500,
    seller_invoice_id: 42, notes: '', items: [],
  },
  {
    id: 2, order_number: 'ORD-20260620-BBBB', order_date: '2026-06-20',
    created_at: '2026-06-20T10:00:00', status: 'dispatched',
    buyer_name: 'My Shop', buyer_bizid: 'BA-BUYER',
    seller_name: 'Acme Supply', seller_bizid: 'BA-SELLER',
    subtotal: 200, cgst_total: 0, sgst_total: 0, igst_total: 0, total_amount: 200,
    seller_invoice_id: null, notes: '', items: [],
  },
]

const STATS = { count: 2, open: 1, openValue: 200, awaitingMe: 0 }

function renderTab(direction = 'outgoing', overrides = {}) {
  return render(
    <OrdersTab
      direction={direction}
      userId={1}
      orders={ORDERS}
      loading={false}
      stats={STATS}
      search="" setSearch={vi.fn()}
      statusFilter="" setStatusFilter={vi.fn()}
      sort={{ key: '', direction: '' }} toggleSort={vi.fn()}
      onChangeStatus={vi.fn()}
      onOpenOrder={vi.fn()}
      justInvoiced={new Set()}
      onGoToOrderDesk={vi.fn()}
      {...overrides}
    />
  )
}

describe('OrdersTab — buyer auto-stock-in UI', () => {
  it('shows "Stock received" on a completed purchase order with a seller invoice', () => {
    renderTab('outgoing')
    expect(screen.getByText(/Stock received/)).toBeInTheDocument()
  })

  it('shows it exactly once — the in-flight order must not be flagged', () => {
    renderTab('outgoing')
    expect(screen.getByText('ORD-20260620-BBBB')).toBeInTheDocument()
    expect(screen.getAllByText(/Stock received/)).toHaveLength(1)
  })

  it('never shows the badge on the incoming (seller) side', () => {
    renderTab('incoming')
    expect(screen.queryByText(/Stock received/)).toBeNull()
  })

  it('flags an order the SSE stream reported as invoiced, before a reload lands', () => {
    const pending = [{ ...ORDERS[0], seller_invoice_id: null }]
    renderTab('outgoing', { orders: pending, justInvoiced: new Set(['ORD-20260620-AAAA']) })
    expect(screen.getByText(/Stock received/)).toBeInTheDocument()
  })
})

describe('OrdersTab — counterparty column', () => {
  it('shows the supplier when I am the buyer', () => {
    renderTab('outgoing')
    expect(screen.getByText('Supplier')).toBeInTheDocument()
    expect(screen.getAllByText('Acme Supply').length).toBeGreaterThan(0)
  })

  it('shows the buyer when I am the seller', () => {
    renderTab('incoming')
    expect(screen.getByText('Buyer')).toBeInTheDocument()
    expect(screen.getAllByText('My Shop').length).toBeGreaterThan(0)
  })
})

describe('actionsFor — who may move an order', () => {
  it('gives the seller the next fulfilment step', () => {
    expect(actionsFor({ status: 'pending' }, 'incoming').map(a => a.key)).toContain('accepted')
    expect(actionsFor({ status: 'accepted' }, 'incoming').map(a => a.key)).toContain('packed')
    expect(actionsFor({ status: 'packed' }, 'incoming').map(a => a.key)).toContain('dispatched')
  })

  it('lets the seller reject only while the order is still early', () => {
    expect(actionsFor({ status: 'pending' }, 'incoming').map(a => a.key)).toContain('rejected')
    expect(actionsFor({ status: 'dispatched' }, 'incoming').map(a => a.key)).not.toContain('rejected')
  })

  it('lets the buyer cancel only before it is packed', () => {
    expect(actionsFor({ status: 'pending' }, 'outgoing').map(a => a.key)).toEqual(['cancelled'])
    expect(actionsFor({ status: 'packed' }, 'outgoing')).toEqual([])
  })

  it('offers nothing on a terminal order', () => {
    expect(actionsFor({ status: 'completed' }, 'incoming')).toEqual([])
    expect(actionsFor({ status: 'cancelled' }, 'outgoing')).toEqual([])
  })

  it('never lets the buyer drive the seller-side rail', () => {
    expect(actionsFor({ status: 'accepted' }, 'outgoing').map(a => a.key)).not.toContain('packed')
  })
})
