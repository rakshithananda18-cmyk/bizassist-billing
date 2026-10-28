import React, { useState } from 'react'
import { api } from '../../lib/api'
import { fmtDateTime, TASK_TYPES } from '../../lib/format'
import CollectionBalance from '../../components/CollectionBalance'
import { Empty, ErrorNote, Loader, StatusBadge, useLoad } from '../../components/ui'

export default function MyTasks() {
  const [status, setStatus] = useState('pending')
  const { data, error, loading } = useLoad(() => api.get('/api/my/tasks', { status }), [status])
  return (
    <>
      <div className="row-between">
        <div style={{ fontWeight: 700, fontSize: 'var(--fs-lg)' }}>My tasks</div>
        <div className="seg">{['pending', 'done'].map(s => <button key={s} className={status === s ? 'on' : ''} onClick={() => setStatus(s)}>{s}</button>)}</div>
      </div>
      <ErrorNote error={error} />
      {loading && !data ? <Loader /> : !data?.length ? <Empty>No {status} tasks.</Empty> : (
        <div className="list">
          {data.map(t => (
            <div key={t.id} className="list-item">
              <div className="grow">
                <div style={{ fontWeight: 600 }}>{t.title}</div>
                <div className="xs muted">{TASK_TYPES[t.task_type]}{t.shop_name && ` · ${t.shop_name}`}
                  {t.status === 'done' ? ` · ${fmtDateTime(t.completed_at)}` : t.due_at ? ` · by ${fmtDateTime(t.due_at)}` : ''}</div>
                <CollectionBalance task={t} />
                {t.overdue && <span className="badge badge-danger">overdue</span>}
              </div>
              {t.status === 'done'
                ? <span className="points-pill">+{t.points_awarded}</span>
                : <StatusBadge status={t.status} />}
            </div>
          ))}
        </div>
      )}
      {status === 'pending' && <div className="xs muted">Complete route tasks from Today, at the shop.</div>}
    </>
  )
}
