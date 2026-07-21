// ============================================================================
// CashbookView — one running list of money in/out (receipts + expenses),
// replacing the parallel All/Received/Made/Expenses tabs with filter chips.
// Reads /payments and /billing/expenses.
// ============================================================================
import React, { useEffect, useState, useCallback } from 'react'
import { SyncIcon } from '../Icons'

const fmt = (n) => `₹${Number(n || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
const CHIPS = ['All', 'Received', 'Paid', 'Expenses']

export default function CashbookView({ authFetch, reloadKey = 0 }) {
  const [rows, setRows] = useState([])
  const [chip, setChip] = useState('All')
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([
      authFetch('/payments').then(r => r.ok ? r.json() : []).catch(() => []),
      authFetch('/billing/expenses').then(r => r.ok ? r.json() : []).catch(() => []),
    ]).then(([pays, exps]) => {
      const p = (Array.isArray(pays) ? pays : []).map(x => ({
        id: `p${x.id}`, date: x.date, kind: x.type === 'made' ? 'Paid' : 'Received',
        party: x.party_name || x.customer_name || '—', ref: x.invoice_number || x.reference || '',
        method: x.method || 'Cash', amount: x.amount, dir: x.type === 'made' ? -1 : 1,
      }))
      const e = (Array.isArray(exps) ? exps : []).map(x => ({
        id: `e${x.id}`, date: x.expense_date || x.date, kind: 'Expenses',
        party: x.category || 'Expense', ref: x.note || '', method: x.payment_mode || 'Cash',
        amount: x.amount, dir: -1,
      }))
      const all = [...p, ...e].sort((a, b) => String(b.date || '').localeCompare(String(a.date || '')))
      setRows(all)
    }).finally(() => setLoading(false))
  }, [authFetch])

  useEffect(() => { load() }, [load, reloadKey])

  const filtered = rows.filter(r => chip === 'All' ? true : r.kind === chip)

  if (loading) return <div style={{ padding: 20, color: 'var(--text-muted)', fontSize: '0.85rem' }}>Loading cashbook…</div>

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '4px 0 10px', flexWrap: 'wrap' }}>
        {CHIPS.map(c => (
          <button key={c} className={`tab${chip === c ? ' active' : ''}`} style={{ margin: 0, padding: '4px 12px', fontSize: '0.8rem' }} onClick={() => setChip(c)}>{c}</button>
        ))}
        <button className="btn btn-ghost btn-sm" style={{ marginLeft: 'auto' }} onClick={load} title="Refresh"><SyncIcon size={14} /></button>
      </div>
      <div className="data-table-wrap" style={{ overflowX: 'auto' }}>
        <table className="data-table" style={{ width: '100%', fontSize: '0.84rem' }}>
          <thead>
            <tr>
              <th>Date</th><th>Type</th><th>Party / Category</th><th>Ref</th><th>Method</th>
              <th style={{ textAlign: 'right' }}>Amount</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr><td colSpan={6} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 24 }}>Nothing here yet.</td></tr>
            ) : filtered.map(r => (
              <tr key={r.id}>
                <td>{r.date || '—'}</td>
                <td>{r.kind}</td>
                <td className="td-primary">{r.party}</td>
                <td style={{ color: 'var(--text-muted)' }}>{r.ref}</td>
                <td>{r.method}</td>
                <td style={{ textAlign: 'right', fontWeight: 600, color: r.dir > 0 ? 'var(--success, #166534)' : 'var(--danger, #b4462f)' }}>
                  {r.dir > 0 ? '+' : '−'}{fmt(r.amount)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
