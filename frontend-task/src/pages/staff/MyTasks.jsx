import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../lib/api'
import { fmtDateTime, TASK_TYPES } from '../../lib/format'
import CollectionBalance from '../../components/CollectionBalance'
import { Empty, ErrorNote, Loader, StatusBadge, useLoad } from '../../components/ui'
import { RefreshIcon } from '../../components/Icons'
import PhoneRecord from '../../components/PhoneRecord'

export default function MyTasks() {
  const [status, setStatus] = useState('pending')
  const { data, error, loading, reload } = useLoad(() => api.get('/api/my/tasks', { status }), [status])

  return (
    <>
      <div className="row-between" style={{ alignItems: 'center' }}>
        <h2 style={{ fontSize: 'var(--fs-lg)', fontWeight: 800, margin: 0 }}>My Tasks</h2>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          style={{ gap: 4, fontWeight: 600 }}
          onClick={reload}
          title="Refresh task list"
        >
          <RefreshIcon size={14} /> Refresh
        </button>
      </div>

      <div className="seg" style={{ width: '100%' }}>
        <button
          type="button"
          className={status === 'pending' ? 'on' : ''}
          style={{ fontWeight: 700 }}
          onClick={() => setStatus('pending')}
        >
          Pending Tasks
        </button>
        <button
          type="button"
          className={status === 'done' ? 'on' : ''}
          style={{ fontWeight: 700 }}
          onClick={() => setStatus('done')}
        >
          Completed
        </button>
      </div>

      <ErrorNote error={error} />

      {loading && !data ? (
        <Loader label="Loading your tasks…" />
      ) : !data?.length ? (
        <Empty>No {status} tasks found.</Empty>
      ) : (
        <div className="phone-record-list" style={{ marginTop: 12 }}>
          {data.map(t => (
            <PhoneRecord
              key={t.id}
              title={t.title}
              meta={`${TASK_TYPES[t.task_type] || 'Task'}${t.shop_name ? ` · ${t.shop_name}` : ''}`}
              status={<StatusBadge status={t.status} />}
              amount={t.status === 'done' ? `+${t.points_awarded} pts` : `⭐ ${t.points} pts`}
              amountTone={t.status === 'done' ? 'green' : undefined}
              primary={
                <Link to="/" className="btn btn-secondary btn-sm" style={{ textDecoration: 'none' }}>
                  View
                </Link>
              }
            >
              <CollectionBalance task={t} />
              {t.due_at && <p><strong>Due:</strong> {fmtDateTime(t.due_at)}</p>}
              {t.completed_at && <p><strong>Completed:</strong> {fmtDateTime(t.completed_at)}</p>}
              {t.overdue && <p><span className="badge badge-danger">Overdue</span></p>}
            </PhoneRecord>
          ))}
        </div>
      )}

      {status === 'pending' && (
        <div className="card plain xs muted" style={{ textAlign: 'center', borderRadius: 12 }}>
          💡 Complete route tasks on the <Link to="/" style={{ fontWeight: 700, color: 'var(--accent)' }}>Today</Link> screen when you arrive at the shop.
        </div>
      )}
    </>
  )
}
