import React, { useState } from 'react'
import { api } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { ago, fmtDateTime, telHref } from '../../lib/format'
import { Empty, ErrorNote, Loader, Modal, PageHeader, useLoad, useToast } from '../../components/ui'
import PhoneRecord from '../../components/PhoneRecord'

const ROLES = { delivery: 'Delivery agent', field: 'Field staff', supervisor: 'Supervisor' }

function validPhone(value) {
  const raw = value.trim()
  if (!/^\+?[0-9 ()\-.]+$/.test(raw)) return false
  let digits = raw.replace(/\D/g, '')
  if (new Set(digits).size === 1) return false
  if (!raw.startsWith('+')) {
    if (digits.length === 10) digits = `91${digits}`
    else if (!(digits.length === 12 && digits.startsWith('91'))) return false
  }
  return digits.length >= 8 && digits.length <= 15 && !digits.startsWith('0') && new Set(digits).size > 1 && (!digits.startsWith('91') || digits.length === 12)
}

export function StaffForm({ staff, onClose, onSaved }) {
  const toast = useToast()
  const [f, setF] = useState({ name: staff?.name || '', login_name: staff?.login_name || '', phone: staff?.phone || '', role: staff?.role || 'delivery', password: '' })
  const [saving, setSaving] = useState(false)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const phoneValid = validPhone(f.phone)
  const canSave = f.name.trim() && (staff || (f.login_name.trim() && f.password && phoneValid)) && (!f.phone.trim() || phoneValid)
  const save = async () => {
    if (!canSave || saving) return
    setSaving(true)
    try {
      if (staff) {
        const body = { name: f.name, phone: f.phone, role: f.role }
        if (f.password) body.password = f.password
        await api.patch(`/api/staff/${staff.id}`, body)
      } else {
        await api.post('/api/staff', f)
      }
      onSaved()
    } catch (e) { toast(e.message, 'error') }
    finally { setSaving(false) }
  }
  return (
    <Modal title={staff ? `Edit ${staff.name}` : 'Add staff'} onClose={onClose}
      footer={<><button className="btn btn-ghost" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={!canSave || saving} onClick={save}>{saving ? 'Saving…' : 'Save'}</button></>}>
      <div className="form-grid">
        <div className="form-group"><label className="form-label" htmlFor="staff-full-name">Full name</label><input id="staff-full-name" className="form-input" value={f.name} onChange={set('name')} /></div>
        <div className="form-group"><label className="form-label" htmlFor="staff-account-name">Login name</label>
          <input id="staff-account-name" className="form-input" value={f.login_name} onChange={set('login_name')} disabled={!!staff} autoCapitalize="none" placeholder="e.g. ravi" /></div>
        <div className="form-group"><label className="form-label" htmlFor="staff-phone">{staff ? 'Phone' : 'Phone (required)'}</label><input id="staff-phone" className="form-input" type="tel" inputMode="tel" value={f.phone} onChange={set('phone')} required={!staff} aria-invalid={f.phone.trim() && !phoneValid ? 'true' : undefined} />
          <span className="form-hint">Enter a 10-digit Indian number, or include the country code (for example +91).</span></div>
        <div className="form-group"><label className="form-label" htmlFor="staff-role">Role</label>
          <select id="staff-role" className="form-select" value={f.role} onChange={set('role')}>{Object.entries(ROLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
        <div className="form-group span-2"><label className="form-label" htmlFor="staff-new-password">{staff ? 'New password (leave empty to keep)' : 'Password'}</label>
          <input id="staff-new-password" className="form-input" type="text" value={f.password} onChange={set('password')} autoComplete="new-password" />
          <span className="form-hint">You set it and share it with them. 8+ characters, upper-case, lower-case and a number.{staff && ' Changing it signs them out.'}</span></div>
      </div>
    </Modal>
  )
}

export default function Staff() {
  const { me } = useAuth()
  const toast = useToast()
  const { data, error, loading, reload } = useLoad(() => api.get('/api/staff'), [])
  const [editing, setEditing] = useState(null)
  const act = async (path, msg, body) => {
    try { await (body ? api.patch(path, body) : api.post(path)); toast(msg, 'success'); reload() } catch (e) { toast(e.message, 'error') }
  }
  const policy = me.settings.device_policy
  return (
    <>
      <PageHeader title="Staff" subtitle={`Staff find your business with BizID ${me.public_id} or your account details, then select their name · ${policy === 'bound' ? 'locked to one phone each' : 'one device at a time'}`}>
        <button className="btn btn-primary" onClick={() => setEditing({})}>+ Add staff</button>
      </PageHeader>
      <ErrorNote error={error} />
      {loading && !data ? <Loader /> : !data?.length ? <Empty>No staff yet. Add your delivery agents and set their passwords.</Empty> : (
        <>
          <div className="table-wrap desktop-only-table">
            <table className="table">
              <thead><tr><th>Name</th><th>Login</th><th>Device</th><th>Last seen</th><th className="num">Points</th><th /></tr></thead>
              <tbody>
                {data.map(s => (
                  <tr key={s.id} style={s.is_active ? undefined : { opacity: 0.55 }}>
                    <td><strong>{s.name}</strong><div className="xs muted">{ROLES[s.role]}{s.phone && <> · <a href={telHref(s.phone)}>{s.phone}</a></>}</div></td>
                    <td className="mono">{s.login_name}{!s.is_active && <div><span className="badge badge-danger">disabled</span></div>}</td>
                    <td className="small">
                      {s.signed_in ? <span className="badge badge-success">signed in</span> : <span className="badge badge-muted">signed out</span>}
                      <div className="xs muted">{s.active_device_label || '—'}</div>
                      {s.device_bound && <div className="xs">locked: {s.bound_device_label || 'device'} · {fmtDateTime(s.bound_at)}</div>}
                    </td>
                    <td className="small">{ago(s.last_seen_at)}</td>
                    <td className="num"><span className="points-pill">{s.points}</span></td>
                    <td>
                      <div className="row wrap" style={{ justifyContent: 'flex-end' }}>
                        <button className="btn btn-ghost btn-sm" onClick={() => setEditing(s)}>Edit</button>
                        {s.device_bound && <button className="btn btn-secondary btn-sm" onClick={() => act(`/api/staff/${s.id}/release-device`, 'Device released — next sign-in binds the new phone')}>Release device</button>}
                        {s.signed_in && <button className="btn btn-ghost btn-sm" onClick={() => act(`/api/staff/${s.id}/sign-out`, 'Signed out')}>Sign out</button>}
                        <button className={`btn btn-sm ${s.is_active ? 'btn-danger' : 'btn-secondary'}`} onClick={() => act(`/api/staff/${s.id}`, s.is_active ? 'Disabled' : 'Enabled', { is_active: !s.is_active })}>{s.is_active ? 'Disable' : 'Enable'}</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="phone-record-list mobile-only-records">
            {data.map(s => (
              <PhoneRecord
                key={s.id}
                title={s.name}
                meta={[ROLES[s.role], s.phone, s.login_name].filter(Boolean).join(' · ')}
                status={<span className={`badge ${s.is_active ? 'badge-success' : 'badge-muted'}`}>{s.is_active ? 'Active' : 'Disabled'}</span>}
                amount={s.signed_in ? 'Signed in' : 'Signed out'}
                amountTone={s.signed_in ? 'green' : 'yellow'}
                primary={<button className="btn btn-secondary btn-sm" onClick={() => setEditing(s)}>Edit</button>}
              >
                <p className="xs muted">Points: <strong>{s.points}</strong> · Last seen: {ago(s.last_seen_at)}</p>
                {s.device_bound && <p className="xs">Locked device: {s.bound_device_label || 'phone'}</p>}
                <div className="row wrap" style={{ gap: 6, marginTop: 4 }}>
                  {s.device_bound && <button className="btn btn-secondary btn-sm" onClick={() => act(`/api/staff/${s.id}/release-device`, 'Device released')}>Release device</button>}
                  {s.signed_in && <button className="btn btn-ghost btn-sm" onClick={() => act(`/api/staff/${s.id}/sign-out`, 'Signed out')}>Sign out</button>}
                  <button className={`btn btn-sm ${s.is_active ? 'btn-danger' : 'btn-secondary'}`} onClick={() => act(`/api/staff/${s.id}`, s.is_active ? 'Disabled' : 'Enabled', { is_active: !s.is_active })}>{s.is_active ? 'Disable' : 'Enable'}</button>
                </div>
              </PhoneRecord>
            ))}
          </div>
        </>
      )}
      {editing && <StaffForm staff={editing.id ? editing : null} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); reload() }} />}
    </>
  )
}
