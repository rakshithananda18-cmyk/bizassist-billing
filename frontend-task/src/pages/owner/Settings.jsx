import React, { useEffect, useState } from 'react'
import { api } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { ErrorNote, Loader, PageHeader, useLoad, useToast } from '../../components/ui'
import { getBillingUrl, getTheme, setTheme } from '../../lib/theme'
import { MonitorIcon, MoonIcon, SunIcon } from '../../components/Icons'

const NUM = ['max_accuracy_m', 'geofence_radius_m', 'ping_interval_s', 'late_grace_min', 'default_task_points', 'late_points_pct', 'on_time_checkin_points']

export default function Settings() {
  const { me, refresh } = useAuth()
  const toast = useToast()
  const { data, error, loading, reload } = useLoad(() => api.get('/api/settings'), [])
  const [f, setF] = useState(null)
  const [saving, setSaving] = useState(false)
  const [theme, setMode] = useState(getTheme)
  useEffect(() => {
    const update = () => setMode(getTheme())
    window.addEventListener('task-theme-change', update)
    return () => window.removeEventListener('task-theme-change', update)
  }, [])
  useEffect(() => { if (data) setF(data) }, [data])
  if (error && !f) return <><PageHeader title="Field Team settings" /><ErrorNote error={error} /><button className="btn btn-secondary" onClick={reload}>Try again</button></>
  if (loading || !f) return <><PageHeader title="Field Team settings" /><Loader /></>
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const save = async () => {
    if (saving) return
    const body = { ...f }
    NUM.forEach(k => { body[k] = Number(body[k]) })
    setSaving(true)
    try {
      const updated = await api.patch('/api/settings', body)
      setF(current => JSON.stringify(current) === JSON.stringify(f) ? updated : current)
      await refresh()
      toast('Field Team settings saved', 'success')
    } catch (e) { toast(e.message, 'error') } finally { setSaving(false) }
  }
  const businessName = me.billing_business?.business_name || me.business_name
  const source = me.data_source?.mode
  const developmentMirror = me.data_source?.development_mirror === true
  return (
    <>
      <PageHeader title="Field Team settings" subtitle="Manage field operations for your Billing business"><button className="btn btn-primary" disabled={saving} onClick={save}>{saving ? 'Saving…' : 'Save changes'}</button></PageHeader>
      <section className="billing-account-card" aria-label="Billing business connection">
        <div className="grow">
          <div className="settings-section-label">Billing business</div>
          <h3 title={businessName}>{businessName}</h3>
          <div className="row wrap small muted"><span className="mono">{me.public_id}</span><span className="badge badge-accent">Pro · Online</span>{source && <span className="badge badge-muted">{developmentMirror || source === 'local' ? 'Development mirror' : 'Shared cloud data'}</span>}</div>
          <p className="small muted">Field Team requires BizAssist Pro and an internet connection. It uses your business's Billing customers and invoices in the shared cloud database. Local Billing changes appear here after they sync to the cloud.</p>
          {developmentMirror && <div className="alert alert-warning" style={{ marginTop: 12 }}>This is an isolated development mirror. Open the online Field Team workspace from Billing to use live cloud customers and invoices.</div>}
        </div>
        <div className="stack">
          <a className="btn btn-secondary btn-sm" href={getBillingUrl('/settings?tab=profile')}>Business profile in Billing</a>
          <a className="btn btn-ghost btn-sm" href={getBillingUrl('/parties')}>Customers & payments in Billing</a>
        </div>
      </section>
      <section className="card plain stack" aria-label="Workspace appearance" style={{ marginBottom: 16 }}>
        <div className="row-between wrap">
          <div><h3>Appearance</h3><p className="small muted">Open Field Team from Billing to bring across your palette and workspace colours.</p></div>
          <a className="btn btn-ghost btn-sm" href={getBillingUrl('/settings?tab=general')}>Appearance in Billing</a>
        </div>
        <div className="theme-mode-options" role="group" aria-label="Display mode">
          {[['light', 'Light', SunIcon], ['dark', 'Dark', MoonIcon], ['system', 'System', MonitorIcon]].map(([mode, label, Icon]) => (
            <button key={mode} type="button" className={`theme-mode-option${theme === mode ? ' selected' : ''}`} aria-pressed={theme === mode} onClick={() => setTheme(mode)}><Icon size={18} />{label}</button>
          ))}
        </div>
        <p className="form-hint">Display mode is saved for this business on this device.</p>
      </section>
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
