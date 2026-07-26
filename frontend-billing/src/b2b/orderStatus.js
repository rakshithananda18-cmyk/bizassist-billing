// ============================================================================
// B2B order status flow — moved verbatim from pages/B2BOrders.jsx
// (repo restructure) so the page and modal components share one source.
// ============================================================================
export const STATUS_FLOW = {
  pending: { label: 'Pending', variant: 'warning', next: 'accepted', nextLabel: 'Accept' },
  accepted: { label: 'Accepted', variant: 'info', next: 'packed', nextLabel: 'Pack' },
  packed: { label: 'Packed', variant: 'info', next: 'dispatched', nextLabel: 'Ship' },
  dispatched: { label: 'Dispatched', variant: 'info', next: 'completed', nextLabel: 'Deliver' },
  completed: { label: 'Completed', variant: 'success' },
  cancelled: { label: 'Cancelled', variant: 'danger' },
  rejected: { label: 'Rejected', variant: 'danger' }
}
