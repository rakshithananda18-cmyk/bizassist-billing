import React, { useEffect, useState } from 'react'
import { api } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { ErrorNote, Loader, PageHeader, useLoad, useToast } from '../../components/ui'

const NUM = ['max_accuracy_m', 'geofence_radius_m', 'ping_interval_s', 'late_grace_min', 'default_task_points', 'late_points_pct', 'on_time_checkin_points']

export default function Settings() {
  const { refresh } = useAuth()
  const toast = useToast()
  const { data, error, loading } = useLoad(() => api.get('/api/settings'), [])
  const [f, setF] = useState(null)
  useEffect(() => { if (data) setF(data) }, [data])
  if (loading || !f) return <><PageHeader title="Settings" /><ErrorNote error={error} /><Loader /></>
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const save = async () => {
    const body = { ...f }
    NUM.forEach(k => { body[k] = Number(body[k]) })
    try { setF(await api.patch('/api/settings', body)); await refresh(); toast('Saved', 'success') } catch (e) { toast(e.message, 'error') }
  }
  return (
    <>
      <PageHeader title="Settings" subtitle="Rules your field team works under"><button className="btn btn-primary" onClick={save}>Save</button></PageHeader>
      <div className="grid grid-2">
        <div className="card plain stack">
          <h3>Sign-in</h3>
          <label className="checkbox"><input type="radio" name="dp" checked={f.device_policy === 'single_session'} onChange={() => setF({ ...f, device_policy: 'single_session' })} />
            <span><strong>One device at a time</strong><div className="xs muted">Signing in on a new phone signs the old one out.</div></span></label>
          <label className="checkbox"><input type="radio" name="dp" checked={f.device_policy === 'bound'} onChange={() => setF({ ...f, device_policy: 'bound' })} />
            <span><strong>Locked to one phone</strong><div className="xs muted">The first phone a person signs in on is theirs; any other is refused until you release it on the Staff page.</div></span></label>
        </div>
        <div className="card plain stack">
          <h3>Location</h3>
          <div className="form-group"><label className="form-label">Refuse GPS fixes worse than (metres)</label><input className="form-input" type="number" value={f.max_accuracy_m} onChange={set('max_accuracy_m')} /></div>
          <div className="form-group"><label className="form-label">Shop radius (metres)</label><input className="form-input" type="number" value={f.geofence_radius_m} onChange={set('geofence_radius_m')} /></div>
          <label className="checkbox"><input type="checkbox" checked={f.geofence_enforced} onChange={set('geofence_enforced')} /> Refuse “arrived” outside the shop radius (otherwise flagged only)</label>
          <div className="form-group"><label className="form-label">Live tracking: one point every (seconds)</label><input className="form-input" type="number" value={f.ping_interval_s} onChange={set('ping_interval_s')} /></div>
        </div>
        <div className="card plain stack">
          <h3>Attendance</h3>
          <div className="form-group"><label className="form-label">Work starts at</label><input className="form-input" type="time" value={f.workday_start} onChange={set('workday_start')} /></div>
          <div className="form-group"><label className="form-label">Grace before “late” (minutes)</label><input className="form-input" type="number" value={f.late_grace_min} onChange={set('late_grace_min')} /></div>
        </div>
        <div className="card plain stack">
          <h3>Points</h3>
          <div className="form-group"><label className="form-label">Default points per task</label><input className="form-input" type="number" value={f.default_task_points} onChange={set('default_task_points')} /></div>
          <div className="form-group"><label className="form-label">Late task earns (% of its points)</label><input className="form-input" type="number" value={f.late_points_pct} onChange={set('late_points_pct')} /></div>
          <div className="form-group"><label className="form-label">On-time check-in points</label><input className="form-input" type="number" value={f.on_time_checkin_points} onChange={set('on_time_checkin_points')} /></div>
        </div>
      </div>
    </>
  )
}
