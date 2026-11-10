import React, { useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../../lib/api'
import { useDay } from '../../layouts/StaffLayout'
import { fmtDateTime } from '../../lib/format'
import { Empty, ErrorNote, Loader, StatusBadge, useLoad } from '../../components/ui'
import { PlusIcon, RefreshIcon } from '../../components/Icons'

const UNITS = ['Box', 'Strip', 'Bottle', 'Case', 'Nos', 'Kg']

export default function NewRequest() {
  const { today, act, onDuty } = useDay()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const { data: shops, error: shopsError, loading: shopsLoading, reload: reloadShops } = useLoad(() => api.get('/api/shops'), [])
  const { data: mine, error: requestsError, loading: requestsLoading, reload } = useLoad(() => api.get('/api/my/requests'), [])
  const routeShops = useMemo(
    () => (today?.runs || []).flatMap(r => r.stops.map(s => ({ ...s.shop, stop_id: s.id }))),
    [today],
  )
  const [shopId, setShopId] = useState(params.get('shop') || '')
  const [kind, setKind] = useState('order')
  const [items, setItems] = useState([{ name: '', qty: '', unit: 'Box' }])
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const submitting = useRef(false)
  const selectedRouteShop = routeShops.find(s => String(s.id) === String(shopId) && String(s.stop_id) === params.get('stop')) || routeShops.find(s => String(s.id) === String(shopId))
  const stopId = selectedRouteShop?.stop_id || null
  const upd = (i, patch) => setItems(items.map((x, j) => (j === i ? { ...x, ...patch } : x)))
  const validItems = items.filter(i => i.name.trim() && Number.isFinite(Number(i.qty)) && Number(i.qty) > 0)
  const valid = shopId && validItems.length > 0

  const submit = async () => {
    if (!valid || !onDuty || submitting.current) return
    submitting.current = true
    setBusy(true)
    try {
      await act(
        '/api/requests',
        {
          shop_id: Number(shopId),
          run_stop_id: stopId ? Number(stopId) : null,
          kind,
          note: note || null,
          items: validItems
            .map(i => ({ name: i.name.trim(), qty: Number(i.qty), unit: i.unit })),
        },
        'Sent to the distributor',
      )
      setItems([{ name: '', qty: '', unit: 'Box' }])
      setNote('')
      reload()
      if (params.get('stop')) navigate('/')
    } catch {
      /* toast shown */
    } finally {
      submitting.current = false
      setBusy(false)
    }
  }

  const others = (shops || []).filter(s => !routeShops.some(r => r.id === s.id))

  return (
    <>
      <div className="row-between" style={{ alignItems: 'center' }}>
        <h2 style={{ fontSize: 'var(--fs-lg)', fontWeight: 800, margin: 0 }}>Shop Order / Demand</h2>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          style={{ gap: 4, fontWeight: 600 }}
          onClick={() => { reload(); reloadShops() }}
          title="Refresh orders"
        >
          <RefreshIcon size={14} /> Refresh
        </button>
      </div>

      <ErrorNote error={shopsError || requestsError} />
      {shopsLoading && !shops && <Loader label="Loading shops…" />}

      {!onDuty && (
        <div className="alert alert-warning" style={{ borderRadius: 12, fontWeight: 600 }}>
          Check in first on Today screen — customer orders are recorded with your GPS location stamp.
        </div>
      )}

      <div className="card stack" style={{ borderRadius: 16, border: '1px solid var(--border)' }}>
        <div className="form-group">
          <label className="form-label" style={{ fontWeight: 700 }}>Select Shop</label>
          <select
            className="form-select"
            style={{ fontWeight: 600, height: 44, borderRadius: 10 }}
            value={shopId}
            onChange={e => setShopId(e.target.value)}
          >
            <option value="">Choose shop…</option>
            {routeShops.length > 0 && (
              <optgroup label="📍 On Today's Route">
                {routeShops.map(s => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </optgroup>
            )}
            {others.length > 0 && (
              <optgroup label="🏪 Other Customers">
                {others.map(s => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
        </div>

        <div className="seg" style={{ width: '100%' }}>
          <button
            type="button"
            className={kind === 'order' ? 'on' : ''}
            style={{ fontWeight: 700 }}
            onClick={() => setKind('order')}
          >
            Order Request
          </button>
          <button
            type="button"
            className={kind === 'requirement' ? 'on' : ''}
            style={{ fontWeight: 700 }}
            onClick={() => setKind('requirement')}
          >
            Requirement Inquiry
          </button>
        </div>

        <div className="stack" style={{ gap: 8 }}>
          <label className="form-label" style={{ fontWeight: 700 }}>Item List</label>
          {items.map((it, i) => (
            <div key={i} className="row" style={{ gap: 6, alignItems: 'center' }}>
              <input
                className="form-input grow"
                placeholder="Medicine / Item name"
                style={{ fontWeight: 600, height: 42, borderRadius: 10 }}
                value={it.name}
                onChange={e => upd(i, { name: e.target.value })}
              />
              <input
                className="form-input"
                style={{ width: 72, textAlign: 'center', fontWeight: 700, height: 42, borderRadius: 10 }}
                type="number"
                min="0"
                inputMode="decimal"
                placeholder="Qty"
                value={it.qty}
                onChange={e => upd(i, { qty: e.target.value })}
              />
              <select
                className="form-select"
                style={{ width: 92, fontWeight: 600, height: 42, borderRadius: 10 }}
                value={it.unit}
                onChange={e => upd(i, { unit: e.target.value })}
              >
                {UNITS.map(u => (
                  <option key={u}>{u}</option>
                ))}
              </select>
              {items.length > 1 && (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm btn-icon"
                  style={{ width: 32, height: 32, borderRadius: 8, color: 'var(--danger)' }}
                  onClick={() => setItems(items.filter((_, j) => j !== i))}
                  aria-label="Remove item"
                >
                  ✕
                </button>
              )}
            </div>
          ))}
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            style={{ alignSelf: 'flex-start', borderRadius: 10, fontWeight: 600, gap: 4 }}
            onClick={() => setItems([...items, { name: '', qty: '', unit: 'Box' }])}
          >
            <PlusIcon size={14} /> Add item
          </button>
        </div>

        <div className="form-group">
          <label className="form-label" style={{ fontWeight: 700 }}>Notes / Instructions</label>
          <textarea
            className="form-textarea"
            style={{ borderRadius: 10 }}
            placeholder="e.g. Delivery needed by tomorrow morning, asked for 10% scheme"
            value={note}
            onChange={e => setNote(e.target.value)}
          />
        </div>

        <button
          type="button"
          className="btn btn-primary btn-lg btn-block"
          style={{ height: 48, fontWeight: 700, borderRadius: 12 }}
          disabled={!valid || busy || !onDuty}
          onClick={submit}
        >
          {busy ? 'Stamping location…' : 'Send to Distributor'}
        </button>
      </div>

      <div style={{ fontWeight: 800, fontSize: 'var(--fs-md)', marginTop: 8 }}>Recently Sent Requests</div>
      {requestsLoading && !mine ? <Loader label="Loading recent requests…" /> : requestsError && !mine ? null : !mine?.length ? (
        <Empty>No orders or requirement lists recorded yet.</Empty>
      ) : (
        <div className="list" style={{ borderRadius: 14, overflow: 'hidden' }}>
          {mine.map(r => (
            <div key={r.id} className="list-item" style={{ padding: '14px 16px' }}>
              <div className="grow" style={{ minWidth: 0 }}>
                <strong style={{ fontSize: 'var(--fs-base)' }}>{r.shop_name}</strong>
                <div className="xs muted" style={{ marginTop: 2 }}>
                  {r.items.map(i => `${i.name} × ${i.qty} ${i.unit}`).join(', ')} · {fmtDateTime(r.created_at)}
                </div>
                {r.note && <div className="xs" style={{ marginTop: 4, color: 'var(--text-secondary)' }}>Note: {r.note}</div>}
              </div>
              <StatusBadge status={r.status} />
            </div>
          ))}
        </div>
      )}
    </>
  )
}
