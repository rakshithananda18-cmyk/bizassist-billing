import React, { useMemo, useState } from 'react'
import { api } from '../../lib/api'
import { fmtDay, fmtTime, rupees, TASK_TYPES, telHref, todayIST } from '../../lib/format'
import { summarizeInvoices } from '../../lib/invoices'
import InvoicePicker from '../../components/InvoicePicker'
import { ConfirmDialog, Empty, ErrorNote, Loader, Modal, PageHeader, StatusBadge, useLoad, useToast } from '../../components/ui'

const EXTRA_TYPES = Object.entries(TASK_TYPES).filter(([k]) => k !== 'delivery')

function StopEditor({ shops, stops, setStops }) {
  const [pick, setPick] = useState('')
  const [picking, setPicking] = useState(null) // index of the stop choosing invoices
  const used = new Set(stops.map(s => s.shop_id))
  const upd = (i, patch) => setStops(stops.map((s, j) => (j === i ? { ...s, ...patch } : s)))
  // Picked bills fill the numbers and orders, and boxes when the bills count them.
  const applyInvoices = (i, invoices) => {
    const sum = summarizeInvoices(invoices)
    upd(i, {
      invoices, invoice_ids: sum.invoice_ids, reference: sum.reference, orders_count: sum.orders_count,
      boxes: sum.boxes ?? stops[i].boxes, collect_due: sum.balance_due > 0 && !!stops[i].collect_due,
    })
    setPicking(null)
  }
  const move = (i, d) => {
    const j = i + d
    if (j < 0 || j >= stops.length) return
    const next = [...stops];
    [next[i], next[j]] = [next[j], next[i]]
    setStops(next)
  }
  return (
    <div className="stack">
      {stops.map((s, i) => {
        const shop = shops.find(x => x.id === s.shop_id)
        const due = summarizeInvoices(s.invoices).balance_due
        return (
          <div key={s.shop_id} className="card plain" style={{ padding: 12 }}>
            <div className="row-between">
              <strong>{i + 1}. {shop?.name}</strong>
              <div className="row">
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => move(i, -1)}>↑</button>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => move(i, 1)}>↓</button>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setStops(stops.filter((_, j) => j !== i))}>Remove</button>
              </div>
            </div>
            <div className="form-grid" style={{ marginTop: 8 }}>
              <div className="form-group"><label className="form-label">Boxes</label>
                <input className="form-input" type="number" min="0" inputMode="numeric" value={s.boxes ?? ''} onChange={e => upd(i, { boxes: e.target.value === '' ? null : Number(e.target.value) })} /></div>
              <div className="form-group"><label className="form-label">Orders sent</label>
                <input className="form-input" type="number" min="0" inputMode="numeric" value={s.orders_count ?? ''} onChange={e => upd(i, { orders_count: e.target.value === '' ? null : Number(e.target.value) })} /></div>
              <div className="form-group span-2"><label className="form-label">Invoice / order numbers</label>
                <input className="form-input" value={s.reference || ''} onChange={e => upd(i, { reference: e.target.value })} placeholder="INV-101, INV-102" /></div>
            </div>
            {shop?.customer_id && (
              <div className="row wrap" style={{ marginTop: 8 }}>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => setPicking(i)}>
                  {s.invoices?.length ? `Billing invoices (${s.invoices.length})` : 'Pick billing invoices'}
                </button>
                {s.invoices?.length > 0 && (
                  <button type="button" className="btn btn-ghost btn-sm"
                    onClick={() => upd(i, { invoices: [], invoice_ids: [], collect_due: false })}>Clear</button>
                )}
                {due > 0 && (
                  <label className="checkbox small">
                    <input type="checkbox" checked={!!s.collect_due} onChange={e => upd(i, { collect_due: e.target.checked })} />
                    Also collect {rupees(due)} due
                  </label>
                )}
              </div>
            )}
            {(s.tasks || []).map((t, k) => (
              <div key={k} className="row wrap" style={{ marginTop: 8 }}>
                <select className="form-select" style={{ width: 180 }} value={t.task_type}
                  onChange={e => upd(i, { tasks: s.tasks.map((x, y) => (y === k ? { ...x, task_type: e.target.value, title: x.title || TASK_TYPES[e.target.value] } : x)) })}>
                  {EXTRA_TYPES.map(([k2, v]) => <option key={k2} value={k2}>{v}</option>)}
                </select>
                <input className="form-input grow" value={t.title} placeholder="What to do"
                  onChange={e => upd(i, { tasks: s.tasks.map((x, y) => (y === k ? { ...x, title: e.target.value } : x)) })} />
                {t.task_type === 'payment_collect' && (
                  <input className="form-input" style={{ width: 120 }} type="number" min="0" placeholder="₹ amount" value={t.amount_expected ?? ''}
                    onChange={e => upd(i, { tasks: s.tasks.map((x, y) => (y === k ? { ...x, amount_expected: e.target.value === '' ? null : Number(e.target.value) } : x)) })} />
                )}
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => upd(i, { tasks: s.tasks.filter((_, y) => y !== k) })}>✕</button>
              </div>
            ))}
            <button type="button" className="btn btn-ghost btn-sm" style={{ marginTop: 6, alignSelf: 'flex-start' }}
              onClick={() => upd(i, { tasks: [...(s.tasks || []), { task_type: 'return_pickup', title: 'Collect returns' }] })}>
              + Add task at this shop (returns, payment, order…)
            </button>
          </div>
        )
      })}
      <div className="row">
        <select className="form-select grow" value={pick} onChange={e => setPick(e.target.value)}>
          <option value="">Add a shop…</option>
          {shops.filter(s => s.is_active && !used.has(s.id)).map(s => <option key={s.id} value={s.id}>{s.name}{s.area ? ` · ${s.area}` : ''}</option>)}
        </select>
        <button type="button" className="btn btn-secondary" disabled={!pick}
          onClick={() => { setStops([...stops, { shop_id: Number(pick), boxes: null, orders_count: null, tasks: [] }]); setPick('') }}>Add</button>
      </div>
      {picking != null && (
        <InvoicePicker shop={shops.find(x => x.id === stops[picking].shop_id)} taskType="delivery"
          initial={stops[picking].invoice_ids || []} onClose={() => setPicking(null)}
          onPick={(invoices) => applyInvoices(picking, invoices)} />
      )}
    </div>
  )
}

function PlanModal({ day, onClose, onSaved }) {
  const toast = useToast()
  const { data } = useLoad(() => Promise.all([api.get('/api/routes'), api.get('/api/staff'), api.get('/api/shops')]), [])
  const [routes, staff, shops] = data || [[], [], []]
  const [f, setF] = useState({ route_id: '', staff_id: '', name: '', due_time: '18:00', notes: '' })
  const [stops, setStops] = useState([])
  const [busy, setBusy] = useState(false)
  const chooseRoute = (id) => {
    const r = routes.find(x => x.id === Number(id))
    setF({ ...f, route_id: id, name: r?.name || f.name, staff_id: r?.default_staff_id ? String(r.default_staff_id) : f.staff_id, due_time: r?.due_time || f.due_time })
    if (r) setStops(r.stops.map(s => ({ shop_id: s.shop.id, boxes: null, orders_count: null, tasks: [] })))
  }
  const save = async () => {
    setBusy(true)
    try {
      await api.post('/api/runs', {
        run_date: day, staff_id: Number(f.staff_id), route_id: f.route_id ? Number(f.route_id) : null,
        name: f.name || null, due_time: f.due_time, notes: f.notes || null,
        // `invoices` is display-only; the server reads invoice_ids.
        stops: stops.map(({ invoices, ...s }) => ({ ...s, tasks: (s.tasks || []).filter(t => t.title?.trim()) })),
      })
      toast('Run planned', 'success')
      onSaved()
    } catch (e) { toast(e.message, 'error') } finally { setBusy(false) }
  }
  return (
    <Modal title={`Plan a run · ${fmtDay(day)}`} onClose={onClose} wide
      footer={<><button className="btn btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={busy || !f.staff_id || !stops.length} onClick={save}>Save run</button></>}>
      <div className="form-grid">
        <div className="form-group"><label className="form-label">Route template (optional)</label>
          <select className="form-select" value={f.route_id} onChange={e => chooseRoute(e.target.value)}>
            <option value="">— none —</option>{routes.filter(r => r.is_active).map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select></div>
        <div className="form-group"><label className="form-label">Delivery person</label>
          <select className="form-select" value={f.staff_id} onChange={e => setF({ ...f, staff_id: e.target.value })}>
            <option value="">Choose…</option>{staff.filter(s => s.is_active).map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select></div>
        <div className="form-group"><label className="form-label">Run name</label>
          <input className="form-input" value={f.name} onChange={e => setF({ ...f, name: e.target.value })} placeholder="e.g. Jayanagar beat" /></div>
        <div className="form-group"><label className="form-label">Deliver by</label>
          <input className="form-input" type="time" value={f.due_time} onChange={e => setF({ ...f, due_time: e.target.value })} /></div>
      </div>
      <StopEditor shops={shops} stops={stops} setStops={setStops} />
      <div className="form-hint">Each shop with boxes, orders or billing invoices gets a delivery task. Points are earned when each task is completed by the deliver-by time.</div>
    </Modal>
  )
}

export default function Plan() {
  const [day, setDay] = useState(todayIST())
  const [planning, setPlanning] = useState(false)
  const [runToCancel, setRunToCancel] = useState(null)
  const toast = useToast()
  const { data: runs, error, loading, reload } = useLoad(() => api.get('/api/runs', { day }), [day])
  const { data: staff } = useLoad(() => api.get('/api/staff'), [])
  const totals = useMemo(() => (runs || []).reduce((a, r) => ({ boxes: a.boxes + r.boxes_planned, orders: a.orders + r.orders_count, shops: a.shops + r.stops_total }), { boxes: 0, orders: 0, shops: 0 }), [runs])

  const generate = async () => {
    try {
      const r = await api.post('/api/runs/generate', { run_date: day })
      toast(`${r.created.length} planned${r.skipped.length ? ` · ${r.skipped.length} skipped (${r.skipped.map(s => `${s.route}: ${s.reason}`).join('; ')})` : ''}`, 'info')
      reload()
    } catch (e) { toast(e.message, 'error') }
  }
  const reassign = async (run, staff_id) => {
    try { await api.patch(`/api/runs/${run.id}`, { staff_id: Number(staff_id) }); reload() } catch (e) { toast(e.message, 'error') }
  }
  const cancel = async (run) => {
    try { await api.post(`/api/runs/${run.id}/cancel`); reload() } catch (e) { toast(e.message, 'error') }
  }

  return (
    <>
      <PageHeader title="Day plan" subtitle={`${fmtDay(day)} · ${runs?.length || 0} runs · ${totals.shops} shops · ${totals.boxes} boxes · ${totals.orders} orders`}>
        <input type="date" className="form-input" style={{ width: 160 }} value={day} onChange={e => setDay(e.target.value)} />
        <button className="btn btn-secondary" onClick={generate}>From routes</button>
        <button className="btn btn-primary" onClick={() => setPlanning(true)}>+ Plan a run</button>
      </PageHeader>
      <ErrorNote error={error} />
      {loading && !runs ? <Loader /> : runs?.length === 0 ? <Empty>No runs for this day. Plan one, or create Routes and use “From routes”.</Empty> : (
        <div className="stack" style={{ gap: 16 }}>
          {runs?.map(run => (
            <div key={run.id} className="card plain">
              <div className="row-between wrap">
                <div>
                  <div className="row"><strong style={{ fontSize: 'var(--fs-md)' }}>{run.name}</strong><StatusBadge status={run.status} /></div>
                  <div className="xs muted">{run.stops_done}/{run.stops_total} shops · {run.boxes_delivered}/{run.boxes_planned} boxes · {run.orders_count} orders
                    {run.started_at && ` · started ${fmtTime(run.started_at)}`}{run.completed_at && ` · finished ${fmtTime(run.completed_at)}`}</div>
                </div>
                <div className="row">
                  <select className="form-select" style={{ width: 170 }} value={run.staff_id || ''} disabled={run.status !== 'planned' && run.status !== 'in_progress'}
                    onChange={e => reassign(run, e.target.value)}>
                    {(staff || []).map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                  {run.status !== 'completed' && run.status !== 'cancelled' && <button type="button" className="btn btn-danger btn-sm" onClick={() => setRunToCancel(run)}>Cancel</button>}
                </div>
              </div>
              <div className="table-wrap" style={{ marginTop: 12 }}>
                <table className="table">
                  <thead><tr><th>#</th><th>Shop</th><th className="num">Boxes</th><th className="num">Orders</th><th>Tasks</th><th>Status</th></tr></thead>
                  <tbody>
                    {run.stops.map(st => (
                      <tr key={st.id}>
                        <td>{st.seq}</td>
                        <td><strong>{st.shop.name}</strong><div className="xs muted">{st.shop.phone && <a href={telHref(st.shop.phone)}>{st.shop.phone}</a>}</div></td>
                        <td className="num">{st.boxes_delivered}/{st.boxes_planned}</td>
                        <td className="num">{st.orders_count}</td>
                        <td className="small">{st.tasks.map(t => (
                          <div key={t.id}>{t.status === 'done' ? '✓' : '○'} {TASK_TYPES[t.task_type]}{t.points_awarded ? ` · +${t.points_awarded}` : ''}{t.on_time === false ? ' · late' : ''}
                            {t.invoices?.length > 0 && <div className="xs muted">{t.invoices.map(x => x.number).join(', ')}</div>}</div>
                        ))}</td>
                        <td>
                          <StatusBadge status={st.status} />
                          {st.arrived_at && <div className="xs muted">arrived {fmtTime(st.arrived_at)}{st.arrival_distance_m != null && ` · ${Math.round(st.arrival_distance_m)} m`}</div>}
                          {st.outside_geofence && <div className="xs" style={{ color: 'var(--warning)' }}>outside shop radius</div>}
                          {st.skip_reason && <div className="xs muted">{st.skip_reason}</div>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      )}
      {planning && <PlanModal day={day} onClose={() => setPlanning(false)} onSaved={() => { setPlanning(false); reload() }} />}
      {runToCancel && <ConfirmDialog
        title={`Cancel ${runToCancel.name}?`}
        message="Pending tasks on this run will be cancelled."
        confirmLabel="Cancel run"
        onCancel={() => setRunToCancel(null)}
        onConfirm={() => { const run = runToCancel; setRunToCancel(null); cancel(run) }}
      />}
    </>
  )
}
