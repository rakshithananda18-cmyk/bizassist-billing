import React, { useState } from 'react'
import { api } from '../../lib/api'
import { fmtDateTime } from '../../lib/format'
import { Empty, ErrorNote, Loader, PageHeader, StatusBadge, useLoad, useToast } from '../../components/ui'
import PhoneRecord from '../../components/PhoneRecord'

export default function Requests() {
  const [status, setStatus] = useState('new')
  const toast = useToast()
  const { data, error, loading, reload } = useLoad(() => api.get('/api/requests', { status: status === 'all' ? '' : status }), [status])
  const setTo = async (r, s) => {
    try { await api.patch(`/api/requests/${r.id}`, { status: s }); reload() } catch (e) { toast(e.message, 'error') }
  }
  return (
    <>
      <PageHeader title="Shop requests" subtitle="Order notes and item requirements captured at the shop">
        <div className="seg">{['new', 'acknowledged', 'fulfilled', 'all'].map(s => <button key={s} className={status === s ? 'on' : ''} onClick={() => setStatus(s)}>{s}</button>)}</div>
      </PageHeader>
      <ErrorNote error={error} />
      {loading && !data ? <Loader /> : !data?.length ? <Empty>No requests here.</Empty> : (
        <>
          {/* Desktop Cards */}
          <div className="desktop-only-table">
            <div className="stack">
              {data.map(r => (
                <div key={r.id} className="card plain">
                  <div className="row-between wrap">
                    <div>
                      <div className="row"><strong>{r.shop_name}</strong><StatusBadge status={r.status} /><span className="badge badge-muted">{r.kind}</span></div>
                      <div className="xs muted">{r.staff_name} · {fmtDateTime(r.created_at)}{r.location && <> · <a href={`https://www.google.com/maps?q=${r.location.lat},${r.location.lng}`} target="_blank" rel="noreferrer">where</a></>}</div>
                    </div>
                    <div className="row">
                      {r.status === 'new' && <button className="btn btn-secondary btn-sm" onClick={() => setTo(r, 'acknowledged')}>Mark seen</button>}
                      {r.status !== 'fulfilled' && <button className="btn btn-success btn-sm" onClick={() => setTo(r, 'fulfilled')}>Fulfilled</button>}
                      {r.status !== 'closed' && <button className="btn btn-ghost btn-sm" onClick={() => setTo(r, 'closed')}>Close</button>}
                    </div>
                  </div>
                  <table className="table" style={{ marginTop: 10 }}>
                    <thead><tr><th>Item</th><th className="num">Qty</th><th>Note</th></tr></thead>
                    <tbody>{r.items.map((it, i) => <tr key={i}><td>{it.name}</td><td className="num">{it.qty} {it.unit || ''}</td><td className="small muted">{it.note || ''}</td></tr>)}</tbody>
                  </table>
                  {r.note && <div className="small" style={{ marginTop: 8 }}>“{r.note}”</div>}
                </div>
              ))}
            </div>
          </div>

          {/* Mobile 3-Column Phone Records */}
          <div className="mobile-only-records phone-record-list">
            {data.map(r => (
              <PhoneRecord
                key={r.id}
                title={r.shop_name}
                meta={`${r.staff_name} · ${fmtDateTime(r.created_at)} · ${r.items?.length || 0} items`}
                status={<StatusBadge status={r.status} />}
                amount={r.kind}
                primary={
                  r.status === 'new' ? (
                    <button className="btn btn-secondary btn-sm" onClick={() => setTo(r, 'acknowledged')}>Mark seen</button>
                  ) : r.status !== 'fulfilled' ? (
                    <button className="btn btn-success btn-sm" onClick={() => setTo(r, 'fulfilled')}>Fulfilled</button>
                  ) : r.status !== 'closed' ? (
                    <button className="btn btn-ghost btn-sm" onClick={() => setTo(r, 'closed')}>Close</button>
                  ) : null
                }
              >
                {r.note && <p><strong>Note:</strong> “{r.note}”</p>}
                {r.items?.length > 0 && (
                  <div style={{ width: '100%', marginTop: 4 }}>
                    <strong style={{ fontSize: 11, display: 'block', marginBottom: 4 }}>Requested Items:</strong>
                    <div className="stack" style={{ gap: 4 }}>
                      {r.items.map((it, idx) => (
                        <div key={idx} className="row-between xs" style={{ padding: '3px 6px', background: 'var(--bg-2)', borderRadius: 6 }}>
                          <span>{it.name}</span>
                          <strong>{it.qty} {it.unit || ''}</strong>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                <div className="row wrap" style={{ gap: 6, marginTop: 8 }}>
                  {r.status !== 'closed' && (
                    <button className="btn btn-ghost btn-sm" onClick={() => setTo(r, 'closed')}>Close request</button>
                  )}
                  {r.location && (
                    <a className="btn btn-secondary btn-sm" href={`https://www.google.com/maps?q=${r.location.lat},${r.location.lng}`} target="_blank" rel="noreferrer">
                      View location
                    </a>
                  )}
                </div>
              </PhoneRecord>
            ))}
          </div>
        </>
      )}
    </>
  )
}
