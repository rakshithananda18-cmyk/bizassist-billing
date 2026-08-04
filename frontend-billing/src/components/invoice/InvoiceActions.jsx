// ============================================================================
// InvoiceActions — compact row of icon-only action buttons for invoice items.
// Actions offered (gated by backend norms flags):
//   👁 View · 🖨 Print · 🔗 Share · 💰 Record Payment (if unpaid) · ↩ Return (if eligible)
//
// The list is declared ONCE in `useInvoiceActionItems` and rendered two ways:
// as this button row, and as right-click ContextMenu items (InvoicesListView).
// Same shape ContextMenu already takes — { label, icon, action } — so the two
// renderings cannot drift apart as the norms gating changes.
// ============================================================================
import React from 'react'
import { EyeIcon, PrinterIcon, Share2Icon, CashIcon, ReturnArrowIcon } from '../Icons'
import { useDocLabels } from '../../hooks/useDocLabels'

// Plain function, not a hook, so a table can build items for every row inside a
// .map() — callers pass `label` from their own useDocLabels().
export function invoiceActionItems(invoice, actions, customer, label) {
  const no = invoice.invoice_number || invoice.invoice_no
  return [
    { label: 'View invoice',  icon: <EyeIcon size={14} />,         action: () => actions.view(no) },
    { label: 'Print / PDF',   icon: <PrinterIcon size={14} />,     action: () => actions.print(no) },
    { label: 'Share on WhatsApp', icon: <Share2Icon size={14} />,  action: () => actions.share(invoice, customer) },
    ...(invoice.can_record_payment
      ? [{ label: 'Record payment', icon: <CashIcon size={14} />,  action: () => actions.recordPayment(invoice), accent: true }]
      : []),
    ...(invoice.can_return
      ? [{ label: `Raise return / ${label('sale_return')}`, icon: <ReturnArrowIcon size={14} />, action: () => actions.openReturn(invoice) }]
      : []),
  ]
}

export default function InvoiceActions({ invoice, actions, customer = null }) {
  const label = useDocLabels()
  const items = invoiceActionItems(invoice, actions, customer, label)
  const btnStyle = { padding: '0 8px', height: 28, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }

  return (
    <div style={{ display: 'flex', gap: 4, justifyContent: 'flex-end', flexWrap: 'nowrap', alignItems: 'center' }}>
      {items.map(item => (
        <button
          key={item.label}
          className={item.accent ? 'btn btn-sm' : 'btn btn-secondary btn-sm'}
          style={item.accent ? { ...btnStyle, backgroundColor: '#166534', color: '#fff', border: 'none' } : btnStyle}
          onClick={item.action}
          title={item.label}
        >
          {item.icon}
        </button>
      ))}
    </div>
  )
}
