import React, { useState } from 'react'
import { api } from '../../lib/api'
import { parseCoords } from '../../lib/coords'
import { getFix } from '../../lib/geo'
import { telHref } from '../../lib/format'
import MapView, { escapeHtml } from '../../components/MapView'
import { Empty, ErrorNote, Loader, Modal, PageHeader, useLoad, useToast } from '../../components/ui'

function ShopForm({ shop, onClose, onSaved }) {
  const toast = useToast()
  const [f, setF] = useState({
    name: shop?.name || '', contact_name: shop?.contact_name || '', phone: shop?.phone || '', address: shop?.address || '',
    area: shop?.area || '', notes: shop?.notes || '', lat: shop?.lat ?? '', lng: shop?.lng ?? '', is_active: shop?.is_active ?? true,
  })
  const [customerId, setCustomerId] = useState(shop?.customer_id ? String(shop.customer_id) : '')
  // Linking is offered when editing: new shops come from "Import from billing".
  const { data: customers } = useLoad(() => (shop ? api.get('/api/billing/customers') : Promise.resolve([])), [shop?.id])
  const [paste, setPaste] = useState('')
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const fromPaste = (text) => {
    setPaste(text)
    const c = parseCoords(text)
    if (c) setF(x => ({ ...x, lat: c.lat, lng: c.lng }))
  }
  const here = async () => {
    try { const fix = await getFix(); setF({ ...f, lat: fix.lat, lng: fix.lng }); toast(`Pinned here (±${Math.round(fix.accuracy)} m)`, 'success') } catch (e) { toast(e.message, 'error') }
  }
  const save = async () => {
    const body = { ...f, lat: f.lat === '' ? null : Number(f.lat), lng: f.lng === '' ? null : Number(f.lng) }
    try {
      if (shop) await api.patch(`/api/shops/${shop.id}`, { ...body, customer_id: customerId ? Number(customerId) : null })
      else await api.post('/api/shops', body)
      onSaved()
    } catch (e) { toast(e.message, 'error') }
  }
  return (
    <Modal title={shop ? 'Edit shop' : 'Add shop'} onClose={onClose}
      footer={<><button className="btn btn-ghost" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={!f.name.trim()} onClick={save}>Save</button></>}>
      <div className="form-grid">
        <div className="form-group span-2"><label className="form-label">Shop name</label><input className="form-input" value={f.name} onChange={set('name')} /></div>
        <div className="form-group"><label className="form-label">Contact person</label><input className="form-input" value={f.contact_name} onChange={set('contact_name')} /></div>
        <div className="form-group"><label className="form-label">Phone</label><input className="form-input" inputMode="tel" value={f.phone} onChange={set('phone')} /></div>
        <div className="form-group span-2"><label className="form-label">Address</label><textarea className="form-textarea" value={f.address} onChange={set('address')} /></div>
        <div className="form-group"><label className="form-label">Area</label><input className="form-input" value={f.area} onChange={set('area')} placeholder="e.g. Jayanagar" /></div>
        <div className="form-group"><label className="form-label">Active</label>
          <label className="checkbox"><input type="checkbox" checked={f.is_active} onChange={e => setF({ ...f, is_active: e.target.checked })} /> On routes</label></div>
        <div className="form-group span-2"><label className="form-label">Location</label>
          <input className="form-input" value={paste} onChange={e => fromPaste(e.target.value)} placeholder="Paste a Google Maps link or “12.97, 77.59”" />
          <div className="row wrap">
            <input className="form-input" style={{ width: 140 }} placeholder="Latitude" value={f.lat} onChange={set('lat')} />
            <input className="form-input" style={{ width: 140 }} placeholder="Longitude" value={f.lng} onChange={set('lng')} />
            <button type="button" className="btn btn-secondary btn-sm" onClick={here}>Use my location</button>
          </div>
          <span className="form-hint">Leave empty and the first delivery visit pins it automatically.</span></div>
        <div className="form-group span-2"><label className="form-label">Notes for the agent</label><textarea className="form-textarea" value={f.notes} onChange={set('notes')} /></div>
        {shop && (
          <div className="form-group span-2"><label className="form-label">BizAssist Billing customer</label>
            <select className="form-select" value={customerId} onChange={e => setCustomerId(e.target.value)}>
              <option value="">— not linked —</option>
              {(customers || []).filter(c => !c.linked || c.id === shop.customer_id).map(c => <option key={c.id} value={c.id}>{c.name}{c.phone ? ` · ${c.phone}` : ''}</option>)}
            </select>
            <span className="form-hint">A linked shop can plan deliveries and collections from that customer’s invoices.</span></div>
        )}
      </div>
    </Modal>
  )
}

function ImportBilling({ onClose, onSaved }) {
  const toast = useToast()
  const { data, error, loading } = useLoad(() => api.get('/api/billing/customers'), [])
  const [picked, setPicked] = useState(new Set())
  const [q, setQ] = useState('')
  const rows = (data || []).filter(c => !c.linked && c.is_active && (!q || c.name?.toLowerCase().includes(q.toLowerCase())))
  const toggle = (id) => { const s = new Set(picked); s.has(id) ? s.delete(id) : s.add(id); setPicked(s) }
  const run = async () => {
    try {
      const r = await api.post('/api/shops/import-billing', { customer_ids: [...picked] })
      toast(`${r.created.length} shop(s) added from BizAssist Billing`, 'success')
      onSaved()
    } catch (e) { toast(e.message, 'error') }
  }
  return (
    <Modal title="Import from BizAssist Billing customers" onClose={onClose}
      footer={<><button className="btn btn-ghost" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={!picked.size} onClick={run}>Import {picked.size || ''}</button></>}>
      <ErrorNote error={error} />
      <input className="form-input" placeholder="Search customers" value={q} onChange={e => setQ(e.target.value)} />
      <div className="row"><button className="btn btn-ghost btn-sm" onClick={() => setPicked(new Set(rows.map(r => r.id)))}>Select all shown</button></div>
      {loading ? <Loader /> : data && data.length === 0 && !error ? (
        <Empty>No billing customers here yet. Billing in the BizAssist desktop app? Set it to Local + Cloud (Settings → Advanced) so your customers and bills reach Field Team.</Empty>
      ) : rows.length === 0 ? <Empty>No unlinked billing customers.</Empty> : (
        <div className="list" style={{ maxHeight: 360, overflowY: 'auto' }}>
          {rows.map(c => (
            <label key={c.id} className="list-item checkbox">
              <input type="checkbox" checked={picked.has(c.id)} onChange={() => toggle(c.id)} />
              <span className="grow"><strong>{c.name}</strong><div className="xs muted">{[c.phone, c.address].filter(Boolean).join(' · ')}</div></span>
            </label>
          ))}
        </div>
      )}
      <div className="form-hint">Imported shops stay linked to the billing customer, so future orders and dues line up.</div>
    </Modal>
  )
}

export default function Shops() {
  const { data, error, loading, reload } = useLoad(() => api.get('/api/shops'), [])
  const [editing, setEditing] = useState(null)
  const [importing, setImporting] = useState(false)
  const [q, setQ] = useState('')
  const shops = (data || []).filter(s => !q || `${s.name} ${s.area || ''} ${s.phone || ''}`.toLowerCase().includes(q.toLowerCase()))
  const markers = shops.filter(s => s.lat != null).map(s => ({ id: s.id, lat: s.lat, lng: s.lng, label: '', color: '#c15f3c', popup: `<b>${escapeHtml(s.name)}</b><br>${escapeHtml(s.phone || '')}` }))
  return (
    <>
      <PageHeader title="Shops" subtitle={`${data?.length || 0} delivery points · ${(data || []).filter(s => s.lat != null).length} pinned on map`}>
        <input className="form-input" style={{ width: 200 }} placeholder="Search" value={q} onChange={e => setQ(e.target.value)} />
        <button className="btn btn-secondary" onClick={() => setImporting(true)}>Import from Billing</button>
        <button className="btn btn-primary" onClick={() => setEditing({})}>+ Add shop</button>
      </PageHeader>
      <ErrorNote error={error} />
      {loading && !data ? <Loader /> : (
        <div className="stack" style={{ gap: 16 }}>
          {markers.length > 0 && <MapView className="map small" markers={markers} />}
          {shops.length === 0 ? <Empty>No shops yet. Add them, or import your billing customers.</Empty> : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Shop</th><th>Contact</th><th>Area</th><th>Location</th><th /></tr></thead>
                <tbody>
                  {shops.map(s => (
                    <tr key={s.id} style={s.is_active ? undefined : { opacity: 0.55 }}>
                      <td><strong>{s.name}</strong>{s.customer_id && <span className="badge badge-muted" style={{ marginLeft: 6 }}>billing</span>}<div className="xs muted">{s.address}</div></td>
                      <td>{s.contact_name}<div className="small">{s.phone && <a href={telHref(s.phone)}>{s.phone}</a>}</div></td>
                      <td>{s.area || '—'}</td>
                      <td className="small">{s.lat != null ? <a href={`https://www.google.com/maps?q=${s.lat},${s.lng}`} target="_blank" rel="noreferrer">pinned{s.location_source === 'staff' ? ' by staff' : ''}</a> : <span className="muted">not pinned</span>}</td>
                      <td><button className="btn btn-ghost btn-sm" onClick={() => setEditing(s)}>Edit</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
      {editing && <ShopForm shop={editing.id ? editing : null} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); reload() }} />}
      {importing && <ImportBilling onClose={() => setImporting(false)} onSaved={() => { setImporting(false); reload() }} />}
    </>
  )
}
