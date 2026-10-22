import React, { useState } from 'react'
import { api } from '../../lib/api'
import { fmtDateTime, rupees, TASK_TYPES, todayIST } from '../../lib/format'
import { Empty, ErrorNote, Loader, Modal, PageHeader, StatusBadge, useLoad, useToast } from '../../components/ui'

function NewTask({ onClose, onSaved }) {
  const toast = useToast()
  const { data } = useLoad(() => Promise.all([api.get('/api/staff'), api.get('/api/shops')]), [])
  const [staff, shops] = data || [[], []]
  const [f, setF] = useState({ title: '', task_type: 'general', staff_id: '', shop_id: '', due_date: todayIST(), due_time: '18:00', points: '', description: '', amount_expected: '', boxes_planned: '' })
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const save = async () => {
    try {
      await api.post('/api/tasks', {
        title: f.title, task_type: f.task_type, staff_id: Number(f.staff_id), shop_id: f.shop_id ? Number(f.shop_id) : null,
        due_date: f.due_date || null, due_time: f.due_time || null, points: f.points === '' ? null : Number(f.points),
        description: f.description || null,
        amount_expected: f.amount_expected === '' ? null : Number(f.amount_expected),
        boxes_planned: f.boxes_planned === '' ? null : Number(f.boxes_planned),
      })
      toast('Task assigned', 'success')
      onSaved()
    } catch (e) { toast(e.message, 'error') }
  }
  return (
    <Modal title="Assign a task" onClose={onClose}
      footer={<><button className="btn btn-ghost" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={!f.title || !f.staff_id} onClick={save}>Assign</button></>}>
      <div className="form-grid">
        <div className="form-group span-2"><label className="form-label">Task</label><input className="form-input" value={f.title} onChange={set('title')} placeholder="e.g. Collect cheque from Apollo" /></div>
        <div className="form-group"><label className="form-label">Type</label>
          <select className="form-select" value={f.task_type} onChange={set('task_type')}>{Object.entries(TASK_TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
        <div className="form-group"><label className="form-label">Assign to</label>
          <select className="form-select" value={f.staff_id} onChange={set('staff_id')}><option value="">Choose…</option>{staff.filter(s => s.is_active).map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></div>
        <div className="form-group span-2"><label className="form-label">Shop (optional)</label>
          <select className="form-select" value={f.shop_id} onChange={set('shop_id')}><option value="">—</option>{shops.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></div>
        <div className="form-group"><label className="form-label">Due date</label><input className="form-input" type="date" value={f.due_date} onChange={set('due_date')} /></div>
        <div className="form-group"><label className="form-label">Due time</label><input className="form-input" type="time" value={f.due_time} onChange={set('due_time')} /></div>
        <div className="form-group"><label className="form-label">Points (blank = default)</label><input className="form-input" type="number" min="0" value={f.points} onChange={set('points')} /></div>
        {f.task_type === 'payment_collect' && <div className="form-group"><label className="form-label">Amount to collect ₹</label><input className="form-input" type="number" min="0" value={f.amount_expected} onChange={set('amount_expected')} /></div>}
        {f.task_type === 'delivery' && <div className="form-group"><label className="form-label">Boxes</label><input className="form-input" type="number" min="0" value={f.boxes_planned} onChange={set('boxes_planned')} /></div>}
        <div className="form-group span-2"><label className="form-label">Notes</label><textarea className="form-textarea" value={f.description} onChange={set('description')} /></div>
      </div>
    </Modal>
  )
}

export default function Tasks() {
  const [status, setStatus] = useState('pending')
  const [staffId, setStaffId] = useState('')
  const [adding, setAdding] = useState(false)
  const toast = useToast()
  const { data: staff } = useLoad(() => api.get('/api/staff'), [])
  const { data, error, loading, reload } = useLoad(() => api.get('/api/tasks', { status, staff_id: staffId }), [status, staffId])
  const cancel = async (t) => {
    try { await api.patch(`/api/tasks/${t.id}`, { status: 'cancelled' }); reload() } catch (e) { toast(e.message, 'error') }
  }
  return (
    <>
      <PageHeader title="Tasks" subtitle="Assigned work, due times and the points earned">
        <div className="seg">{['pending', 'overdue', 'done', 'cancelled'].map(s => <button key={s} className={status === s ? 'on' : ''} onClick={() => setStatus(s)}>{s}</button>)}</div>
        <select className="form-select" style={{ width: 160 }} value={staffId} onChange={e => setStaffId(e.target.value)}>
          <option value="">Everyone</option>{(staff || []).map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <button className="btn btn-primary" onClick={() => setAdding(true)}>+ Assign task</button>
      </PageHeader>
      <ErrorNote error={error} />
      {loading && !data ? <Loader /> : !data?.length ? <Empty>No {status} tasks.</Empty> : (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Task</th><th>Who</th><th>Shop</th><th>Due</th><th>Status</th><th className="num">Points</th><th /></tr></thead>
            <tbody>
              {data.map(t => (
                <tr key={t.id}>
                  <td><strong>{t.title}</strong><div className="xs muted">{TASK_TYPES[t.task_type]}
                    {t.boxes_planned != null && ` · ${t.boxes_delivered ?? 0}/${t.boxes_planned} boxes`}
                    {t.amount_expected != null && ` · ${rupees(t.amount_collected ?? 0)} of ${rupees(t.amount_expected)}`}</div>
                    {t.completion_note && <div className="xs">“{t.completion_note}”</div>}</td>
                  <td>{t.staff_name || '—'}</td>
                  <td>{t.shop_name || '—'}</td>
                  <td className="small">{fmtDateTime(t.due_at)}{t.overdue && <div><span className="badge badge-danger">overdue</span></div>}</td>
                  <td><StatusBadge status={t.status} />{t.completed_at && <div className="xs muted">{fmtDateTime(t.completed_at)}{t.on_time === false && ' · late'}</div>}</td>
                  <td className="num">{t.status === 'done' ? `+${t.points_awarded}` : t.points}</td>
                  <td>{t.status === 'pending' && <button className="btn btn-ghost btn-sm" onClick={() => cancel(t)}>Cancel</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {adding && <NewTask onClose={() => setAdding(false)} onSaved={() => { setAdding(false); reload() }} />}
    </>
  )
}
