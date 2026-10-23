// components/InvoicePicker.jsx — choose a shop's BizAssist Billing invoices for
// a delivery or a collection. Bills already on a live task of the same kind
// can't be picked again (the server refuses them too).
import React, { useState } from 'react'
import { api } from '../lib/api'
import { fmtDay, rupees, TASK_TYPES } from '../lib/format'
import { summarizeInvoices, takenBy } from '../lib/invoices'
import { Empty, ErrorNote, Loader, Modal, useLoad } from './ui'

const RANGES = [30, 60, 90, 180]

function lineText(lines) {
  const shown = lines.slice(0, 3).map(l => `${l.product_name} × ${l.quantity}${l.unit ? ` ${l.unit}` : ''}`)
  return shown.join(' · ') + (lines.length > 3 ? ` · +${lines.length - 3} more` : '')
}

export default function InvoicePicker({ shop, taskType = 'delivery', initial = [], onClose, onPick }) {
  const [days, setDays] = useState(30)
  const { data, error, loading } = useLoad(
    () => (shop.customer_id ? api.get(`/api/shops/${shop.id}/billing-invoices`, { days }) : Promise.resolve(null)),
    [shop.id, shop.customer_id, days],
  )
  const [picked, setPicked] = useState(() => new Set(initial))
  const rows = data?.invoices || []
  const chosen = rows.filter(i => picked.has(i.id))
  const sum = summarizeInvoices(chosen)
  const toggle = (id) => { const s = new Set(picked); s.has(id) ? s.delete(id) : s.add(id); setPicked(s) }

  return (
    <Modal title={`Billing invoices · ${shop.name}`} onClose={onClose} wide
      footer={<>
        {chosen.length > 0 && <span className="small muted grow">{chosen.length} picked · {sum.boxes ?? '?'} box(es) · {rupees(sum.balance_due)} due</span>}
        <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={!chosen.length} onClick={() => onPick(chosen)}>Use {chosen.length || ''}</button>
      </>}>
      {!shop.customer_id ? (
        <Empty>{shop.name} isn’t linked to a billing customer. Link it from Shops → Edit, or import it from billing.</Empty>
      ) : (
        <>
          <div className="row">
            <span className="small muted grow">Bills from the last</span>
            <select className="form-select" style={{ width: 120 }} value={days} onChange={e => setDays(Number(e.target.value))}>
              {RANGES.map(d => <option key={d} value={d}>{d} days</option>)}
            </select>
          </div>
          <ErrorNote error={error} />
          {loading && !data ? <Loader /> : rows.length === 0 ? <Empty>No bills in the last {days} days and nothing unpaid.</Empty> : (
            <div className="list" style={{ maxHeight: 420, overflowY: 'auto' }}>
              {rows.map(inv => {
                const taken = takenBy(inv, taskType)
                return (
                  <label key={inv.id} className="list-item checkbox" style={taken ? { opacity: 0.6 } : undefined}>
                    <input type="checkbox" disabled={!!taken} checked={picked.has(inv.id)} onChange={() => toggle(inv.id)} />
                    <span className="grow">
                      <strong>{inv.number}</strong>{inv.date && <span className="xs muted"> · {fmtDay(inv.date)}</span>}
                      {inv.lines.length > 0 && <div className="xs muted">{lineText(inv.lines)}</div>}
                      {taken && <div className="xs">Already on {TASK_TYPES[taken.task_type]?.toLowerCase()} task #{taken.task_id} ({taken.status})</div>}
                    </span>
                    <span className="num small">
                      {rupees(inv.total)}
                      {inv.balance_due > 0
                        ? <div className="xs" style={{ color: 'var(--warning)' }}>{rupees(inv.balance_due)} due</div>
                        : <div className="xs muted">paid</div>}
                      {inv.boxes != null && <div className="xs muted">{inv.boxes} box(es)</div>}
                    </span>
                  </label>
                )
              })}
            </div>
          )}
          <div className="form-hint">Boxes come from box, carton and case lines; type them yourself if the bill counts strips or pieces. Older bills stay listed while money is still due on them. Bills made in the BizAssist desktop app appear here after it syncs.</div>
        </>
      )}
    </Modal>
  )
}
