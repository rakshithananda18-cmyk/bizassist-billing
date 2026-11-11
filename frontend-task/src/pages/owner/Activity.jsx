import React from 'react'
import { api } from '../../lib/api'
import { fmtDateTime } from '../../lib/format'
import { Empty, ErrorNote, Loader, PageHeader, useLoad } from '../../components/ui'
import PhoneRecord from '../../components/PhoneRecord'

export default function Activity() {
  const { data, error, loading } = useLoad(() => api.get('/api/activity', { limit: 200 }), [])
  return (
    <>
      <PageHeader title="Activity" subtitle="Every action, who did it, when (server time) and where" />
      <ErrorNote error={error} />
      {loading && !data ? <Loader /> : !data?.length ? <Empty>Nothing yet.</Empty> : (
        <>
          {/* Desktop list view */}
          <div className="desktop-only-table">
            <div className="list">
              {data.map(a => (
                <div key={a.id} className="list-item small">
                  <span className="muted mono" style={{ width: 120 }}>{fmtDateTime(a.at)}</span>
                  <strong style={{ minWidth: 90 }}>{a.actor}</strong>
                  <span className="grow">{a.action.replace('.', ' · ').replaceAll('_', ' ')}{a.summary ? ` — ${a.summary}` : ''}</span>
                  {a.location && <a className="xs muted" href={`https://www.google.com/maps?q=${a.location.lat},${a.location.lng}`} target="_blank" rel="noreferrer">map</a>}
                </div>
              ))}
            </div>
          </div>

          {/* Mobile 3-column phone records */}
          <div className="mobile-only-records phone-record-list">
            {data.map(a => {
              const actionLabel = a.action.replace('.', ' · ').replaceAll('_', ' ')
              return (
                <PhoneRecord
                  key={a.id}
                  title={a.actor}
                  meta={fmtDateTime(a.at)}
                  status={<span className="badge badge-muted" style={{ textTransform: 'capitalize' }}>{actionLabel}</span>}
                  primary={a.location ? (
                    <a className="btn btn-secondary btn-sm" href={`https://www.google.com/maps?q=${a.location.lat},${a.location.lng}`} target="_blank" rel="noreferrer">
                      Map
                    </a>
                  ) : null}
                >
                  {a.summary && <p><strong>Summary:</strong> {a.summary}</p>}
                  <p className="mono xs muted">Action: {a.action}</p>
                </PhoneRecord>
              )
            })}
          </div>
        </>
      )}
    </>
  )
}
