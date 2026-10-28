import React from 'react'
import { collectionAmounts } from '../lib/invoices'
import { rupees } from '../lib/format'

export default function CollectionBalance({ task }) {
  if (task.task_type !== 'payment_collect' || task.status !== 'pending') return null
  const balance = collectionAmounts(task)
  if (!balance.available) return <div className="xs" style={{ color: 'var(--warning)' }}>Billing balance unavailable · refresh before collecting</div>
  if (!balance.linked) return balance.planned == null ? null : <div className="xs muted">Planned collection {rupees(balance.planned)}</div>
  return (
    <div className="xs muted">
      {rupees(balance.currentDue)} currently due in Billing
      {balance.planned != null && balance.planned !== balance.currentDue && ` · planned target ${rupees(balance.planned)}`}
    </div>
  )
}
