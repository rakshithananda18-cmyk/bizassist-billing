import React, { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../../lib/api'
import { useDay } from '../../layouts/StaffLayout'
import { fmtDateTime } from '../../lib/format'
import { Empty, StatusBadge, useLoad } from '../../components/ui'

const UNITS = ['Strip', 'Box', 'Bottle', 'Case', 'Nos', 'Kg']

export default function NewRequest() {
  const { today, act, onDuty } = useDay()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const { data: shops } = useLoad(() => api.get('/api/shops'), [])
  const { data: mine, reload } = useLoad(() => api.get('/api/my/requests'), [])
  const routeShops = useMemo(() => (today?.runs || []).flatMap(r => r.stops.map(s => ({ ...s.shop, stop_id: s.id }))), [today])
  const [shopId, setShopId] = useState(params.get('shop') || '')
  const [kind, setKind] = useState('order')
  const [items, setItems] = useState([{ name: '', qty: '', unit: 'Box' }])
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const stopId = params.get('stop') || routeShops.find(s => String(s.id) === String(shopId))?.stop_id || null
  const upd = (i, patch) => setItems(items.map((x, j) => (j === i ? { ...x, ...patch } : x)))
  const valid = shopId && items.some(i => i.name.trim() && Number(i.qty) > 0)
  const submit = async () => {
    setBusy(true)
    try {
      await act('/api/requests', {
        shop_id: Number(shopId), run_stop_id: stopId ? Number(stopId) : null, kind, note: note || null,
        items: items.filter(i => i.name.trim() && Number(i.qty) > 0).map(i => ({ name: i.name.trim(), qty: Number(i.qty), unit: i.unit })),
      }, 'Sent to the owner')
      setItems([{ name: '', qty: '', unit: 'Box' }]); setNote('')
      reload()
      if (params.get('stop')) navigate('/')
    } catch { /* toast shown */ } finally { setBusy(false) }
  }
  const others = (shops || []).filter(s => !routeShops.some(r => r.id === s.id))
  return (
    <>
      <div style={{ fontWeight: 700, fontSize: 'var(--fs-lg)' }}>Shop order / requirement</div>
      {!onDuty && <div className="alert alert-warning">Check in first — requests are recorded with your location.</div>}
      <div className="card plain stack">
        <div className="form-group"><label className="form-label">Shop</label>
          <select className="form-select" value={shopId} onChange={e => setShopId(e.target.value)}>
            <option value="">Choose shop…</option>
            {routeShops.length > 0 && <optgroup label="On today's route">{routeShops.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</optgroup>}
            {others.length > 0 && <optgroup label="All shops">{others.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</optgroup>}
          </select></div>
        <div className="seg">
          <button className={kind === 'order' ? 'on' : ''} onClick={() => setKind('order')}>Order</button>
          <button className={kind === 'requirement' ? 'on' : ''} onClick={() => setKind('requirement')}>Requirement list</button>
        </div>
        {items.map((it, i) => (
          <div key={i} className="row">
            <input className="form-input grow" placeholder="Item name" value={it.name} onChange={e => upd(i, { name: e.target.value })} />
            <input className="form-input" style={{ width: 72 }} type="number" min="0" inputMode="decimal" placeholder="Qty" value={it.qty} onChange={e => upd(i, { qty: e.target.value })} />
            <select className="form-select" style={{ width: 92 }} value={it.unit} onChange={e => upd(i, { unit: e.target.value })}>{UNITS.map(u => <option key={u}>{u}</option>)}</select>
            {items.length > 1 && <button className="btn btn-ghost btn-sm" onClick={() => setItems(items.filter((_, j) => j !== i))}>✕</button>}
          </div>
        ))}
        <button className="btn btn-secondary btn-sm" style={{ alignSelf: 'flex-start' }} onClick={() => setItems([...items, { name: '', qty: '', unit: 'Box' }])}>+ Add item</button>
        <textarea className="form-textarea" placeholder="Note (delivery date, scheme asked, etc.)" value={note} onChange={e => setNote(e.target.value)} />
        <button className="btn btn-primary btn-lg btn-block" disabled={!valid || busy || !onDuty} onClick={submit}>{busy ? 'Getting location…' : 'Send to owner'}</button>
      </div>
      <div style={{ fontWeight: 700 }}>Sent recently</div>
      {!mine?.length ? <Empty>Nothing sent yet.</Empty> : (
        <div className="list">
          {mine.map(r => (
            <div key={r.id} className="list-item">
              <div className="grow"><strong>{r.shop_name}</strong>
                <div className="xs muted">{r.items.map(i => `${i.name} × ${i.qty}`).join(', ')} · {fmtDateTime(r.created_at)}</div></div>
              <StatusBadge status={r.status} />
            </div>
          ))}
        </div>
      )}
    </>
  )
}
