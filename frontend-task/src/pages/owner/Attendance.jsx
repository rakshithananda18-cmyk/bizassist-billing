import React, { useState } from 'react'
import { api } from '../../lib/api'
import { fmtDay, fmtTime, telHref, todayIST } from '../../lib/format'
import { Empty, ErrorNote, Loader, PageHeader, StatusBadge, useLoad } from '../../components/ui'

const mapLink = (loc) => loc && <a className="xs" href={`https://www.google.com/maps?q=${loc.lat},${loc.lng}`} target="_blank" rel="noreferrer">±{Math.round(loc.accuracy || 0)} m · map</a>

export default function Attendance() {
  const [day, setDay] = useState(todayIST())
  const { data, error, loading } = useLoad(() => api.get('/api/attendance', { day }), [day])
  return (
    <>
      <PageHeader title="Attendance" subtitle={`${fmtDay(day)} · times are server time, not the phone's clock`}>
        <input type="date" className="form-input" style={{ width: 160 }} value={day} onChange={e => setDay(e.target.value)} />
      </PageHeader>
      <ErrorNote error={error} />
      {loading && !data ? <Loader /> : data && (
        <div className="stack" style={{ gap: 16 }}>
          {data.present.length === 0 ? <Empty>Nobody checked in.</Empty> : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Staff</th><th>Status</th><th>Check-in</th><th>Check-out</th><th>Phone clock</th></tr></thead>
                <tbody>
                  {data.present.map(a => (
                    <tr key={a.id}>
                      <td><strong>{a.staff_name}</strong></td>
                      <td><StatusBadge status={a.status} />{a.minutes_late > 0 && <div className="xs muted">{a.minutes_late} min late</div>}</td>
                      <td className="mono">{fmtTime(a.check_in_at)}<div>{mapLink(a.check_in_location)}</div></td>
                      <td className="mono">{a.check_out_at ? fmtTime(a.check_out_at) : <span className="badge badge-success">on duty</span>}<div>{mapLink(a.check_out_location)}</div></td>
                      <td className="small">{a.client_clock_skew_s == null ? '—' : Math.abs(a.client_clock_skew_s) > 300
                        ? <span className="badge badge-warning">off by {Math.round(Math.abs(a.client_clock_skew_s) / 60)} min</span>
                        : <span className="muted">ok</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {data.absent.length > 0 && (
            <div className="card plain">
              <h3>Not checked in · {data.absent.length}</h3>
              <div className="list">{data.absent.map(s => (
                <div key={s.id} className="list-item"><span className="grow">{s.name}</span>{s.phone && <a className="btn btn-secondary btn-sm" href={telHref(s.phone)}>Call</a>}</div>
              ))}</div>
            </div>
          )}
        </div>
      )}
    </>
  )
}
