import React, { useEffect, useState } from 'react'
import { api } from '../../lib/api'
import { ago, fmtTime, telHref, todayIST } from '../../lib/format'
import MapView, { escapeHtml } from '../../components/MapView'
import { Empty, ErrorNote, PageHeader, useLoad } from '../../components/ui'

const COLOR = { on_duty: '#1f6b3a', checked_out: '#8e8e93', off: '#9b1c1c' }

export default function Live() {
  const { data, error, reload } = useLoad(() => api.get('/api/track/live'), [])
  const [selected, setSelected] = useState(null)
  const [day, setDay] = useState(todayIST())
  const [trail, setTrail] = useState(null)
  const [trailError, setTrailError] = useState(null)
  const [trailLoading, setTrailLoading] = useState(false)

  useEffect(() => { const t = setInterval(reload, 30000); return () => clearInterval(t) }, [reload])
  useEffect(() => {
    let current = true
    setTrail(null)
    setTrailError(null)
    setTrailLoading(Boolean(selected))
    if (selected) {
      api.get('/api/track/trail', { staff_id: selected, day })
        .then(value => { if (current) setTrail(value) })
        .catch(error => { if (current) setTrailError(error) })
        .finally(() => { if (current) setTrailLoading(false) })
    }
    return () => { current = false }
  }, [selected, day, data])

  const staff = data?.staff || []
  const markers = staff.filter(s => s.location).map(s => ({
    id: s.staff_id, lat: s.location.lat, lng: s.location.lng, color: COLOR[s.duty],
    label: s.name.slice(0, 2).toUpperCase(),
    popup: `<b>${escapeHtml(s.name)}</b><br>${escapeHtml(s.at_shop ? 'At ' + s.at_shop : s.next_shop ? 'Next: ' + s.next_shop : '')}<br>seen ${escapeHtml(ago(s.last_seen_at))} · ±${Math.round(s.location.accuracy || 0)} m`,
  }))
  const events = (trail?.points || []).filter(p => p.event)
  const trailMarkers = events.map((p, i) => ({ id: `e${i}`, lat: p.lat, lng: p.lng, color: '#c15f3c', label: i + 1,
    popup: `${escapeHtml(p.event.replace('_', ' '))} · ${escapeHtml(fmtTime(p.t))}` }))
  const paths = trail ? [{ id: 't', points: trail.points.map(p => [p.lat, p.lng]) }] : []

  return (
    <>
      <PageHeader title="Live map" subtitle="Last known position of each person on duty · refreshes every 30 s">
        {selected && <input type="date" className="form-input" style={{ width: 160 }} value={day} onChange={e => setDay(e.target.value)} />}
        {selected && <button className="btn btn-secondary" onClick={() => setSelected(null)}>Show everyone</button>}
      </PageHeader>
      <ErrorNote error={error} />
      <ErrorNote error={trailError} />
      {trailLoading && <div className="small muted" role="status">Loading route trail…</div>}
      <div className="stack" style={{ gap: 16 }}>
        <MapView markers={selected ? [...trailMarkers, ...markers.filter(m => m.id === selected)] : markers} paths={paths} fitKey={`${selected}-${day}`} />
        {selected && trail && <div className="xs muted">{trail.points.length} points on {day}. The trail has gaps while the agent's phone is locked or the app is closed.</div>}
        {staff.length === 0 ? <Empty>No active staff yet.</Empty> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Staff</th><th>Duty</th><th>Route progress</th><th>Now</th><th>Last seen</th><th /></tr></thead>
              <tbody>
                {staff.map(s => (
                  <tr key={s.staff_id}>
                    <td><strong>{s.name}</strong><div className="xs muted">{s.role}{s.phone && <> · <a href={telHref(s.phone)}>{s.phone}</a></>}</div></td>
                    <td>
                      <span className={`badge ${s.duty === 'on_duty' ? 'badge-success' : 'badge-muted'}`}>{s.duty.replace('_', ' ')}</span>
                      {s.late && <span className="badge badge-warning" style={{ marginLeft: 4 }}>late</span>}
                      {s.check_in_at && <div className="xs muted">in {fmtTime(s.check_in_at)}</div>}
                    </td>
                    <td className="mono">{s.stops_total ? `${s.stops_done}/${s.stops_total} shops` : '—'}</td>
                    <td className="small">{s.at_shop ? `At ${s.at_shop}` : s.next_shop ? `Next: ${s.next_shop}` : '—'}</td>
                    <td className="small">{ago(s.last_seen_at)}{s.location && <div className="xs muted">±{Math.round(s.location.accuracy || 0)} m</div>}</td>
                    <td><button className="btn btn-secondary btn-sm" onClick={() => setSelected(s.staff_id)}>Trail</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  )
}
