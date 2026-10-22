import React, { useState } from 'react'
import { api } from '../../lib/api'
import { WEEKDAYS } from '../../lib/format'
import { Empty, ErrorNote, Loader, Modal, PageHeader, useLoad, useToast } from '../../components/ui'

function RouteForm({ route, onClose, onSaved }) {
  const toast = useToast()
  const { data } = useLoad(() => Promise.all([api.get('/api/staff'), api.get('/api/shops')]), [])
  const [staff, shops] = data || [[], []]
  const [f, setF] = useState({
    name: route?.name || '', description: route?.description || '', weekdays: route?.weekdays || [],
    default_staff_id: route?.default_staff_id || '', due_time: route?.due_time || '18:00', is_active: route?.is_active ?? true,
  })
  const [ids, setIds] = useState(route?.stops?.map(s => s.shop.id) || [])
  const [pick, setPick] = useState('')
  const toggleDay = (d) => setF({ ...f, weekdays: f.weekdays.includes(d) ? f.weekdays.filter(x => x !== d) : [...f.weekdays, d] })
  const move = (i, d) => { const j = i + d; if (j < 0 || j >= ids.length) return; const n = [...ids]; [n[i], n[j]] = [n[j], n[i]]; setIds(n) }
  const save = async () => {
    const body = { ...f, default_staff_id: f.default_staff_id ? Number(f.default_staff_id) : null, shop_ids: ids }
    try {
      if (route) await api.put(`/api/routes/${route.id}`, body)
      else await api.post('/api/routes', body)
      onSaved()
    } catch (e) { toast(e.message, 'error') }
  }
  const byId = Object.fromEntries(shops.map(s => [s.id, s]))
  return (
    <Modal title={route ? 'Edit route' : 'New route'} onClose={onClose} wide
      footer={<><button className="btn btn-ghost" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={!f.name.trim()} onClick={save}>Save</button></>}>
      <div className="form-grid">
        <div className="form-group"><label className="form-label">Route name</label><input className="form-input" value={f.name} onChange={e => setF({ ...f, name: e.target.value })} placeholder="e.g. Monday – Jayanagar" /></div>
        <div className="form-group"><label className="form-label">Usual delivery person</label>
          <select className="form-select" value={f.default_staff_id} onChange={e => setF({ ...f, default_staff_id: e.target.value })}>
            <option value="">—</option>{staff.filter(s => s.is_active).map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></div>
        <div className="form-group span-2"><label className="form-label">Runs on</label>
          <div className="row wrap">{WEEKDAYS.map((w, i) => (
            <button key={w} type="button" className={`btn btn-sm ${f.weekdays.includes(i + 1) ? 'btn-primary' : 'btn-secondary'}`} onClick={() => toggleDay(i + 1)}>{w}</button>
          ))}</div><span className="form-hint">None selected = any day (plan it manually).</span></div>
        <div className="form-group"><label className="form-label">Deliver by</label><input className="form-input" type="time" value={f.due_time} onChange={e => setF({ ...f, due_time: e.target.value })} /></div>
        <div className="form-group"><label className="form-label">Active</label><label className="checkbox"><input type="checkbox" checked={f.is_active} onChange={e => setF({ ...f, is_active: e.target.checked })} /> Used by “From routes”</label></div>
      </div>
      <div className="form-label">Shops in visiting order</div>
      <div className="list">
        {ids.length === 0 && <Empty>No shops yet.</Empty>}
        {ids.map((id, i) => (
          <div key={id} className="list-item">
            <strong style={{ width: 22 }}>{i + 1}</strong>
            <span className="grow">{byId[id]?.name}<div className="xs muted">{byId[id]?.area}</div></span>
            <button className="btn btn-ghost btn-sm" onClick={() => move(i, -1)}>↑</button>
            <button className="btn btn-ghost btn-sm" onClick={() => move(i, 1)}>↓</button>
            <button className="btn btn-ghost btn-sm" onClick={() => setIds(ids.filter(x => x !== id))}>Remove</button>
          </div>
        ))}
      </div>
      <div className="row">
        <select className="form-select grow" value={pick} onChange={e => setPick(e.target.value)}>
          <option value="">Add a shop…</option>
          {shops.filter(s => s.is_active && !ids.includes(s.id)).map(s => <option key={s.id} value={s.id}>{s.name}{s.area ? ` · ${s.area}` : ''}</option>)}
        </select>
        <button className="btn btn-secondary" disabled={!pick} onClick={() => { setIds([...ids, Number(pick)]); setPick('') }}>Add</button>
      </div>
    </Modal>
  )
}

export default function RoutesPage() {
  const { data, error, loading, reload } = useLoad(() => api.get('/api/routes'), [])
  const { data: staff } = useLoad(() => api.get('/api/staff'), [])
  const [editing, setEditing] = useState(null)
  const names = Object.fromEntries((staff || []).map(s => [s.id, s.name]))
  return (
    <>
      <PageHeader title="Routes" subtitle="Reusable beats: which shops, in what order, on which days">
        <button className="btn btn-primary" onClick={() => setEditing({})}>+ New route</button>
      </PageHeader>
      <ErrorNote error={error} />
      {loading && !data ? <Loader /> : !data?.length ? <Empty>No routes yet. A route turns into a day’s run with one click on Day plan.</Empty> : (
        <div className="grid grid-2">
          {data.map(r => (
            <div key={r.id} className="card" style={r.is_active ? undefined : { opacity: 0.6 }}>
              <div className="row-between">
                <strong style={{ fontSize: 'var(--fs-md)' }}>{r.name}</strong>
                <button className="btn btn-ghost btn-sm" onClick={() => setEditing(r)}>Edit</button>
              </div>
              <div className="xs muted" style={{ margin: '4px 0 10px' }}>
                {r.weekdays.length ? r.weekdays.map(d => WEEKDAYS[d - 1]).join(', ') : 'Any day'} · by {r.due_time} · {names[r.default_staff_id] || 'no default person'}
              </div>
              <div className="small">{r.stops.map(s => s.shop.name).join(' → ') || <span className="muted">No shops</span>}</div>
            </div>
          ))}
        </div>
      )}
      {editing && <RouteForm route={editing.id ? editing : null} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); reload() }} />}
    </>
  )
}
