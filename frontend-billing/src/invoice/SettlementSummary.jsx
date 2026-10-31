import { inr } from './formatters'

export default function SettlementSummary({ totals }) {
  const changed = ['credited_amount', 'amount_refunded', 'credit_allocated_in', 'credit_allocated_out', 'return_credit'].some(key => Number(totals[key]) > 0)
  if (!changed) return null
  const rows = [
    ['Credit notes', totals.credited_amount],
    ['Adjusted payable', totals.adjusted_total],
    ['Cash received', totals.cash_received],
    ['Refunded', totals.amount_refunded],
    ['Credit applied to this bill', totals.credit_allocated_in],
    ['Credit transferred to another bill', totals.credit_allocated_out],
    ['Return credit remaining', totals.return_credit],
  ]
  return <div aria-label="Posted settlements" style={{ padding: '6px 8px', fontSize: '0.85em', borderTop: '1px solid #bbb' }}>
    {rows.filter(([label, amount]) => amount != null && (Number(amount) !== 0 || label === 'Adjusted payable')).map(([label, amount]) => <div key={label} style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}><span>{label}</span><span>{inr(amount)}</span></div>)}
  </div>
}
