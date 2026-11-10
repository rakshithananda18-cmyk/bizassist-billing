import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../lib/api'
import { fmtDateTime, TASK_TYPES } from '../../lib/format'
import CollectionBalance from '../../components/CollectionBalance'
import { Empty, ErrorNote, Loader, StatusBadge, useLoad } from '../../components/ui'
import { RefreshIcon } from '../../components/Icons'

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
        <div className="list" style={{ borderRadius: 14, overflow: 'hidden' }}>
          {data.map(t => (
            <div key={t.id} className="list-item" style={{ padding: '14px 16px' }}>
              <div className="grow" style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 700, fontSize: 'var(--fs-base)' }}>{t.title}</div>
                <div className="xs muted" style={{ marginTop: 2 }}>
                  <span style={{ fontWeight: 600, color: 'var(--accent)' }}>{TASK_TYPES[t.task_type]}</span>
                  {t.shop_name && ` · ${t.shop_name}`}
                  {t.status === 'done'
                    ? ` · ${fmtDateTime(t.completed_at)}`
                    : t.due_at
                    ? ` · Due by ${fmtDateTime(t.due_at)}`
                    : ''}
                </div>
                <CollectionBalance task={t} />
                {t.overdue && <span className="badge badge-danger" style={{ marginTop: 4 }}>overdue</span>}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6, flexShrink: 0 }}>
                {t.status === 'done' ? (
                  <span className="points-pill" style={{ fontWeight: 700 }}>
                    +{t.points_awarded} pts
                  </span>
                ) : (
                  <>
                    <StatusBadge status={t.status} />
                    <span className="xs muted" style={{ fontWeight: 600 }}>⭐ {t.points} pts</span>
                  </>
                )}
              </div>
            </div>
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
