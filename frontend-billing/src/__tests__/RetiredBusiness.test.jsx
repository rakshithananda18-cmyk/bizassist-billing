import React from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { actionsFor } from '../b2b/components/OrdersTab'
import OrderDetailModal from '../b2b/components/OrderDetailModal'
import DeletedPartyNotice from '../invoice/DeletedPartyNotice'
afterEach(cleanup)
it('keeps archived order identities and amounts visible without new-trade actions', () => {
  const order = { id: 1, order_number: 'ARCHIVE-1', buyer_name: 'Original buyer', buyer_bizid: 'BA-BUYER', seller_name: 'Original seller', seller_bizid: 'BA-SELLER', seller_deleted: true, status: 'pending', items: [], total_amount: 100 }
  expect(actionsFor(order, 'incoming')).toEqual([])
  expect(actionsFor(order, 'outgoing')).toEqual([])
  render(<OrderDetailModal selectedOrder={order} setSelectedOrder={vi.fn()} activeTab="outgoing" notes={{}} handleStatusChange={vi.fn()} />)
  expect(screen.getByText('Original seller')).toBeInTheDocument()
  expect(screen.getByText('BA-SELLER')).toBeInTheDocument()
  expect(screen.getByText(/Business account deleted/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Cancel Order' })).not.toBeInTheDocument()
})
it('labels the retired party on printable records', () => {
  render(<DeletedPartyNotice seller={{ deleted: true }} buyer={{ deleted: false }} />)
  expect(screen.getByRole('status')).toHaveTextContent('Business account deleted (seller)')
})
