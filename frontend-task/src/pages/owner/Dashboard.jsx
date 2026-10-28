import React, { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../../lib/api'
import { fmtDay, fmtTime, todayIST } from '../../lib/format'
import { Empty, ErrorNote, Loader, PageHeader, StatusBadge, useLoad, useToast } from '../../components/ui'

const pct = (a, b) => (b ? Math.round((100 * a) / b) : 0)

export default function Dashboard() {
  const [day, setDay] = useState(todayIST())
  const toast = useToast()
  const navigate = useNavigate()
  const { data: d, error, loading, reload } = useLoad(() => api.get('/api/dashboard', { day }), [day])

  const generate = async () => {
    try {
      const r = await api.post('/api/runs/generate', { run_date: day })
      toast(r.created.length ? `${r.created.length} run(s) planned from routes` : 'Nothing new to plan — see Day plan', r.created.length ? 'success' : 'info')
      reload()
    } catch (e) { toast(e.message, 'error') }
  }

  const kpiCard = (label, value, sub, color, to) => (
    <div
      key={label}
      className="vsummary-card"
      style={{ borderLeftColor: color, cursor: to ? 'pointer' : 'default' }}
      role={to ? 'button' : undefined}
      tabIndex={to ? 0 : undefined}
      title={to ? `Click to open ${label}` : undefined}
      onClick={() => to && navigate(to)}
      onKeyDown={e => { if (to && (e.key === 'Enter' || e.key === ' ')) navigate(to) }}
      onMouseEnter={e => { if (to) e.currentTarget.style.transform = 'translateY(-1px)' }}
      onMouseLeave={e => { if (to) e.currentTarget.style.transform = 'none' }}
    >
      <div className="vsummary-label">{label}</div>
      <div className="vsummary-value">{value}</div>
      <div className="vsummary-sub">{sub}</div>
    </div>
  )

  return (
    <>
      <PageHeader title="Dashboard" subtitle={fmtDay(day)}>
        <input type="date" className="form-input" style={{ width: 160 }} value={day} onChange={e => setDay(e.target.value)} />
        <button className="btn btn-secondary" onClick={generate}>Plan runs from routes</button>
      </PageHeader>

      <ErrorNote error={error} />

      {loading && !d ? <Loader /> : d && (
        <div className="stack" style={{ gap: 20 }}>
          {/* Signature 4-column KPI strip matching Billing */}
          <div className="vsummary-strip">
            {kpiCard(
              'Attendance',
              `${d.attendance.present}/${d.attendance.staff_total}`,
              `${d.attendance.late} late · ${d.attendance.on_duty} on duty`,
              'var(--accent)',
              '/attendance'
            )}
            {kpiCard(
              'Deliveries',
              `${d.deliveries.done}/${d.deliveries.total}`,
              `${d.deliveries.orders_sent} orders sent · ${pct(d.deliveries.done, d.deliveries.total)}% done`,
              'var(--success)',
              '/plan'
            )}
            {kpiCard(
              'Boxes Delivered',
              `${d.deliveries.boxes_delivered}/${d.deliveries.boxes_planned}`,
              `${pct(d.deliveries.boxes_delivered, d.deliveries.boxes_planned)}% fulfilled`,
              'var(--warning)',
              '/plan'
            )}
            {kpiCard(
              'Tasks Done',
              `${d.tasks.done}/${d.tasks.total}`,
              `${d.tasks.on_time} on time · ${d.tasks.overdue} overdue`,
              'var(--accent)',
              '/tasks'
            )}
          </div>

          {/* 1.2fr : 0.8fr Dashboard Grid matching Billing */}
          <div className="dashboard-grid">
            <div className="card">
              <h3>Routes · {d.runs.total} runs · {d.runs.stops_done}/{d.runs.stops_total} shops</h3>
              {d.runs_list.length === 0 ? (
                <Empty>No runs planned. Use <Link className="muted" to="/plan" style={{ textDecoration: 'underline' }}>Day plan</Link>.</Empty>
              ) : (
                <div className="stack" style={{ gap: 12 }}>
                  {d.runs_list.map(r => (
                    <div key={r.id} className="stack" style={{ gap: 4 }}>
                      <div className="row-between">
                        <div className="ellipsis">
                          <strong>{r.name}</strong> <span className="muted small">· {r.staff_name || 'unassigned'}</span>
                        </div>
                        <StatusBadge status={r.status} />
                      </div>
                      <div className={`progress ${r.stops_done === r.stops_total && r.stops_total ? 'ok' : ''}`}>
                        <span style={{ width: `${pct(r.stops_done, r.stops_total)}%` }} />
                      </div>
                      <div className="xs muted">{r.stops_done}/{r.stops_total} shops{r.started_at ? ` · started ${fmtTime(r.started_at)}` : ''}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="card">
              <h3>Points today</h3>
              {d.leaderboard.length === 0 ? (
                <Empty>No points yet today.</Empty>
              ) : (
                <div className="list">
                  {d.leaderboard.map((r, i) => (
                    <div key={r.staff_id} className="list-item">
                      <strong style={{ width: 22 }}>{i + 1}</strong>
                      <span className="grow">{r.name}</span>
                      <span className="points-pill">{r.points} pts</span>
                    </div>
                  ))}
                </div>
              )}
              {d.open_requests > 0 && (
                <Link to="/requests" className="alert alert-info" style={{ marginTop: 12 }}>
                  {d.open_requests} new shop request(s) waiting →
                </Link>
              )}
            </div>
          </div>

          {/* Recent Activity card */}
          <div className="card plain">
            <h3>Recent activity</h3>
            {d.recent_activity.length === 0 ? (
              <Empty>Nothing yet.</Empty>
            ) : (
              <div className="list">
                {d.recent_activity.map(a => (
                  <div key={a.id} className="list-item small">
                    <span className="muted mono" style={{ width: 70 }}>{fmtTime(a.at)}</span>
                    <strong style={{ minWidth: 80 }}>{a.actor}</strong>
                    <span className="grow ellipsis">{a.action.replace('.', ' · ').replace('_', ' ')}{a.summary ? ` — ${a.summary}` : ''}</span>
                    {a.location && (
                      <a className="xs muted" href={`https://www.google.com/maps?q=${a.location.lat},${a.location.lng}`} target="_blank" rel="noreferrer">
                        map
                      </a>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  )
}
