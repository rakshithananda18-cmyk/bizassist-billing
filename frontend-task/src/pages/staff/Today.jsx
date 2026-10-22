import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { useDay } from '../../layouts/StaffLayout'
import { mapsDirectionsUrl } from '../../lib/geo'
import { fmtDateTime, fmtDay, fmtTime, rupees, TASK_TYPES, telHref } from '../../lib/format'
import { CheckIcon, NavigationIcon, PhoneIcon } from '../../components/Icons'
import { ErrorNote, Loader, Modal, StatusBadge } from '../../components/ui'

function TrackLine({ track, awake, toggleAwake }) {
  const fix = track.fix
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div className="geo-status">
        <span className={`duty-dot ${track.state === 'tracking' ? 'on' : ''}`} />
        {track.state === 'tracking' && fix ? `Location on · ±${Math.round(fix.accuracy)} m` :
          track.state === 'error' ? `Location problem: ${track.message}` :
          track.state === 'unsupported' ? 'This browser cannot share location' : 'Waiting for GPS…'}
        {track.buffered > 0 && ` · ${track.buffered} point(s) waiting for network`}
      </div>
      <label className="checkbox xs">
        <input type="checkbox" checked={awake} onChange={toggleAwake} />
        Keep screen on during route (tracking pauses when the screen locks)
      </label>
    </div>
  )
}

function DutyCard() {
  const { today, act, track, awake, toggleAwake } = useDay()
  const [busy, setBusy] = useState(false)
  const att = today.attendance
  const go = async (path, msg) => { setBusy(true); try { await act(path, {}, msg) } catch { /* toast shown */ } finally { setBusy(false) } }
  if (!att) {
    return (
      <div className="card stack">
        <div className="duty-card"><span className="duty-dot" /><strong>Not checked in</strong></div>
        <div className="small muted">{fmtDay(today.today)} · your location and the server time are recorded.</div>
        <button className="btn btn-primary btn-lg btn-block" disabled={busy}
          onClick={() => go('/api/attendance/check-in', r => (r.status === 'late' ? `Checked in · ${r.minutes_late} min late` : `Checked in on time · +${r.points_awarded} pts`))}>
          {busy ? 'Getting location…' : 'Check in'}
        </button>
      </div>
    )
  }
  if (att.check_out_at) {
    return (
      <div className="card plain">
        <div className="duty-card"><span className="duty-dot" /><strong>Checked out at {fmtTime(att.check_out_at)}</strong></div>
        <div className="small muted">In at {fmtTime(att.check_in_at)}. See you tomorrow.</div>
      </div>
    )
  }
  return (
    <div className="card stack">
      <div className="row-between">
        <div className="duty-card">
          <span className={`duty-dot ${att.status === 'late' ? 'late' : 'on'}`} />
          <div><strong>On duty</strong><div className="xs muted">since {fmtTime(att.check_in_at)}{att.status === 'late' && ` · ${att.minutes_late} min late`}</div></div>
        </div>
        <button className="btn btn-secondary btn-sm" disabled={busy}
          onClick={() => { if (window.confirm('Check out for today? Field work stops after check-out.')) go('/api/attendance/check-out', 'Checked out') }}>Check out</button>
      </div>
      <TrackLine track={track} awake={awake} toggleAwake={toggleAwake} />
    </div>
  )
}

function CompleteModal({ task, onClose }) {
  const { act } = useDay()
  const [f, setF] = useState({ boxes: task.boxes_planned ?? '', amount: task.amount_expected ?? '', note: '' })
  const [busy, setBusy] = useState(false)
  const submit = async () => {
    setBusy(true)
    const body = { note: f.note || null }
    if (task.task_type === 'delivery') body.boxes_delivered = Number(f.boxes)
    if (task.task_type === 'payment_collect') body.amount_collected = Number(f.amount)
    try {
      await act(`/api/tasks/${task.id}/complete`, body, r => (r.on_time ? `Done on time · +${r.points_awarded} pts` : `Done (late) · +${r.points_awarded} pts`))
      onClose()
    } catch { setBusy(false) }
  }
  const needsNumber = (task.task_type === 'delivery' && f.boxes === '') || (task.task_type === 'payment_collect' && f.amount === '')
  return (
    <Modal title={task.title} onClose={onClose}
      footer={<><button className="btn btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-success btn-lg" disabled={busy || needsNumber} onClick={submit}>{busy ? 'Getting location…' : 'Mark done'}</button></>}>
      {task.task_type === 'delivery' && (
        <div className="form-group"><label className="form-label">Boxes delivered (planned {task.boxes_planned ?? 0})</label>
          <input className="form-input" type="number" min="0" inputMode="numeric" value={f.boxes} onChange={e => setF({ ...f, boxes: e.target.value })} /></div>
      )}
      {task.task_type === 'payment_collect' && (
        <div className="form-group"><label className="form-label">Amount collected ₹ {task.amount_expected != null && `(due ${rupees(task.amount_expected)})`}</label>
          <input className="form-input" type="number" min="0" inputMode="decimal" value={f.amount} onChange={e => setF({ ...f, amount: e.target.value })} /></div>
      )}
      {task.reference && <div className="small muted">Ref: {task.reference}</div>}
      {task.description && <div className="small">{task.description}</div>}
      <div className="form-group"><label className="form-label">Note (optional)</label>
        <textarea className="form-textarea" value={f.note} onChange={e => setF({ ...f, note: e.target.value })} placeholder="e.g. received by pharmacist" /></div>
      <div className="xs muted">Your location and the server time are saved with this.</div>
    </Modal>
  )
}

const SKIP_REASONS = ['Shop closed', 'Owner not available', 'Refused delivery', 'Could not reach in time']

function SkipModal({ stop, onClose }) {
  const { act } = useDay()
  const [reason, setReason] = useState(SKIP_REASONS[0])
  const [other, setOther] = useState('')
  const submit = async () => {
    try { await act(`/api/run-stops/${stop.id}/skip`, { reason: other.trim() || reason }, 'Shop skipped'); onClose() } catch { /* toast shown */ }
  }
  return (
    <Modal title={`Skip ${stop.shop.name}?`} onClose={onClose}
      footer={<><button className="btn btn-ghost" onClick={onClose}>Back</button><button className="btn btn-danger" onClick={submit}>Skip shop</button></>}>
      {SKIP_REASONS.map(r => (
        <label key={r} className="checkbox"><input type="radio" name="skip" checked={!other && reason === r} onChange={() => { setReason(r); setOther('') }} /> {r}</label>
      ))}
      <input className="form-input" placeholder="Other reason" value={other} onChange={e => setOther(e.target.value)} />
    </Modal>
  )
}

function StopCard({ stop, current, onDuty }) {
  const { act } = useDay()
  const [completing, setCompleting] = useState(null)
  const [skipping, setSkipping] = useState(false)
  const [busy, setBusy] = useState(false)
  const arrive = async () => {
    setBusy(true)
    try { await act(`/api/run-stops/${stop.id}/arrive`, {}, r => (r.outside_geofence ? `Arrived · ${Math.round(r.arrival_distance_m)} m from the shop pin` : `Arrived at ${stop.shop.name}`)) } catch { /* toast */ }
    setBusy(false)
  }
  const doneHere = async () => {
    setBusy(true)
    try { await act(`/api/run-stops/${stop.id}/done`, {}, 'Shop done') } catch { /* toast */ }
    setBusy(false)
  }
  const open = stop.status === 'pending' || stop.status === 'arrived'
  const pendingTasks = stop.tasks.filter(t => t.status === 'pending')
  return (
    <div className={`stop ${stop.status} ${current ? 'current' : ''}`}>
      <div className="stop-head">
        <div className="stop-seq">{stop.status === 'done' ? <CheckIcon size={14} strokeWidth={3} /> : stop.seq}</div>
        <div className="grow">
          <div className="stop-name">{stop.shop.name}</div>
          {(stop.shop.address || stop.shop.area) && <div className="small muted">{stop.shop.address || stop.shop.area}</div>}
          <div className="stop-meta">
            {stop.boxes_planned > 0 && <span className="badge badge-accent">{stop.boxes_delivered}/{stop.boxes_planned} boxes</span>}
            {stop.orders_count > 0 && <span className="badge badge-muted">{stop.orders_count} order(s)</span>}
            {stop.status !== 'pending' && <StatusBadge status={stop.status} />}
            {stop.arrived_at && <span className="xs muted">arrived {fmtTime(stop.arrived_at)}</span>}
          </div>
          {stop.shop.notes && <div className="xs" style={{ marginTop: 4 }}>{stop.shop.notes}</div>}
        </div>
      </div>
      {open && (
        <div className="stop-actions">
          {stop.shop.phone && <a className="btn btn-secondary btn-sm" href={telHref(stop.shop.phone)}><PhoneIcon size={14} /> Call</a>}
          <a className="btn btn-secondary btn-sm" href={mapsDirectionsUrl(stop.shop)} target="_blank" rel="noreferrer"><NavigationIcon size={14} /> Navigate</a>
          {stop.status === 'pending' && <button className="btn btn-primary btn-sm" disabled={!onDuty || busy} onClick={arrive}>{busy ? 'Locating…' : 'I have arrived'}</button>}
          {stop.status === 'arrived' && pendingTasks.length === 0 && <button className="btn btn-success btn-sm" disabled={busy} onClick={doneHere}>Done here</button>}
          {stop.status === 'arrived' && <Link className="btn btn-secondary btn-sm" to={`/request?shop=${stop.shop.id}&stop=${stop.id}`}>Shop order</Link>}
          <button className="btn btn-ghost btn-sm" disabled={!onDuty} onClick={() => setSkipping(true)}>Skip</button>
        </div>
      )}
      {stop.tasks.length > 0 && (
        <div className="stop-tasks">
          {stop.tasks.map(t => (
            <div key={t.id} className={`task-row ${t.status}`}>
              <span className="task-check">{t.status === 'done' && <CheckIcon size={14} strokeWidth={3} />}</span>
              <div className="grow">
                <div className="task-title small" style={{ fontWeight: 600 }}>{t.title}</div>
                <div className="xs muted">{TASK_TYPES[t.task_type]} · {t.status === 'done' ? `+${t.points_awarded} pts${t.on_time === false ? ' (late)' : ''}` : `${t.points} pts by ${fmtTime(t.due_at)}`}
                  {t.amount_expected != null && ` · ${rupees(t.amount_expected)}`}</div>
              </div>
              {t.status === 'pending' && (
                <button className="btn btn-success btn-sm" disabled={stop.status !== 'arrived'} onClick={() => setCompleting(t)}
                  title={stop.status !== 'arrived' ? 'Mark arrival first' : ''}>Done</button>
              )}
            </div>
          ))}
        </div>
      )}
      {completing && <CompleteModal task={completing} onClose={() => setCompleting(null)} />}
      {skipping && <SkipModal stop={stop} onClose={() => setSkipping(false)} />}
    </div>
  )
}

function RunBlock({ run, onDuty }) {
  const { act } = useDay()
  const current = run.stops.find(s => s.status === 'arrived') || run.stops.find(s => s.status === 'pending')
  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="row-between">
        <div>
          <div style={{ fontWeight: 700, fontSize: 'var(--fs-lg)' }}>{run.name}</div>
          <div className="xs muted">{run.stops_done}/{run.stops_total} shops · {run.boxes_delivered}/{run.boxes_planned} boxes · {run.orders_count} orders</div>
        </div>
        {run.status === 'planned'
          ? <button className="btn btn-primary btn-sm" disabled={!onDuty} onClick={() => act(`/api/runs/${run.id}/start`, {}, 'Route started').catch(() => {})}>Start route</button>
          : <StatusBadge status={run.status} />}
      </div>
      <div className={`progress ${run.status === 'completed' ? 'ok' : ''}`}><span style={{ width: `${run.stops_total ? (100 * run.stops_done) / run.stops_total : 0}%` }} /></div>
      {run.notes && <div className="alert alert-info">{run.notes}</div>}
      {run.stops.map(s => <StopCard key={s.id} stop={s} current={current?.id === s.id && run.status !== 'completed'} onDuty={onDuty} />)}
    </div>
  )
}

export default function Today() {
  const { today, error, onDuty } = useDay()
  const [completing, setCompleting] = useState(null)
  if (!today) return error ? <ErrorNote error={error} /> : <Loader label="Loading your day…" />
  return (
    <>
      <DutyCard />
      {!onDuty && today.attendance == null && (today.runs.length > 0 || today.other_tasks.length > 0) &&
        <div className="alert alert-warning">Check in to start your route.</div>}
      {today.runs.length === 0 && today.other_tasks.length === 0 && <div className="empty">No route or tasks assigned for today.</div>}
      {today.runs.map(r => <RunBlock key={r.id} run={r} onDuty={onDuty} />)}
      {today.other_tasks.length > 0 && (
        <div className="stack" style={{ gap: 8 }}>
          <div style={{ fontWeight: 700 }}>Other tasks</div>
          <div className="list">
            {today.other_tasks.map(t => (
              <div key={t.id} className="list-item">
                <div className="grow">
                  <div style={{ fontWeight: 600 }}>{t.title}</div>
                  <div className="xs muted">{TASK_TYPES[t.task_type]}{t.shop_name && ` · ${t.shop_name}`} · {t.points} pts{t.due_at && ` · by ${fmtDateTime(t.due_at)}`}</div>
                  {t.overdue && <span className="badge badge-danger">overdue</span>}
                </div>
                <button className="btn btn-success btn-sm" disabled={!onDuty} onClick={() => setCompleting(t)}>Done</button>
              </div>
            ))}
          </div>
        </div>
      )}
      {completing && <CompleteModal task={completing} onClose={() => setCompleting(null)} />}
    </>
  )
}
