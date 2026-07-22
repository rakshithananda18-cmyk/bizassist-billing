// ============================================================================
// InvoiceActions — compact row of icon-only action buttons for invoice items.
// Actions offered (gated by backend norms flags):
//   👁 View · 🖨 Print · 🔗 Share · 💰 Record Payment (if unpaid) · ↩ Return (if eligible)
// ============================================================================
import React from 'react'
import { EyeIcon, PrinterIcon, Share2Icon, CashIcon, ReturnArrowIcon } from '../Icons'
import { useDocLabels } from '../../hooks/useDocLabels'

export default function InvoiceActions({ invoice, actions, customer = null }) {
  const label = useDocLabels()
  const sz = 14
  const cls = `btn btn-secondary btn-sm`
  const btnStyle = { padding: '0 8px', height: 28, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }

  return (
    <div style={{ display: 'flex', gap: 4, justifyContent: 'flex-end', flexWrap: 'nowrap', alignItems: 'center' }}>
      <button className={cls} style={btnStyle} onClick={() => actions.view(invoice.invoice_number || invoice.invoice_no)} title="View invoice">
        <EyeIcon size={sz} />
      </button>
      <button className={cls} style={btnStyle} onClick={() => actions.print(invoice.invoice_number || invoice.invoice_no)} title="Print / PDF">
        <PrinterIcon size={sz} />
      </button>
      <button className={cls} style={btnStyle} onClick={() => actions.share(invoice, customer)} title="Share on WhatsApp">
        <Share2Icon size={sz} />
      </button>
      {invoice.can_record_payment && (
        <button className="btn btn-sm" style={{ ...btnStyle, backgroundColor: '#166534', color: '#fff', border: 'none' }} onClick={() => actions.recordPayment(invoice)} title="Record payment">
          <CashIcon size={sz} />
        </button>
      )}
      {invoice.can_return && (
        <button className={cls} style={btnStyle} onClick={() => actions.openReturn(invoice)} title={`Raise return / ${label('sale_return')}`}>
          <ReturnArrowIcon size={sz} />
        </button>
      )}
    </div>
  )
}
