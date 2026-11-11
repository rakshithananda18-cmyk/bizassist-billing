import React, { useState } from 'react'
import { api } from '../../lib/api'
import { rupees, todayIST } from '../../lib/format'
import { Empty, ErrorNote, Loader, PageHeader, useLoad } from '../../components/ui'
import PhoneRecord from '../../components/PhoneRecord'

export default function Scorecard() {
  const today = todayIST()
  const [from, setFrom] = useState(today.slice(0, 8) + '01')
  const [to, setTo] = useState(today)
  const { data, error, loading } = useLoad(() => api.get('/api/scorecard', { from, to }), [from, to])
  return (
    <>
      <PageHeader title="Scorecard" subtitle="Points come from tasks finished on time and on-time check-ins — the basis for incentives">
        <input type="date" className="form-input" style={{ width: 150 }} value={from} onChange={e => setFrom(e.target.value)} />
        <input type="date" className="form-input" style={{ width: 150 }} value={to} onChange={e => setTo(e.target.value)} />
      </PageHeader>
      <ErrorNote error={error} />
      {loading && !data ? <Loader /> : !data?.staff.length ? <Empty>No staff yet.</Empty> : (
        <>
          <div className="table-wrap desktop-only-table">
            <table className="table">
              <thead><tr><th>#</th><th>Staff</th><th className="num">Points</th><th className="num">Tasks done</th><th className="num">On time</th><th className="num">Missed</th>
                <th className="num">Deliveries</th><th className="num">Boxes</th><th className="num">Collected</th><th className="num">Days present</th><th className="num">Late days</th></tr></thead>
              <tbody>
                {data.staff.map((s, i) => (
                  <tr key={s.staff_id}>
                    <td>{i + 1}</td>
                    <td><strong>{s.name}</strong></td>
                    <td className="num"><span className="points-pill">{s.points}</span></td>
                    <td className="num">{s.tasks_done}</td>
                    <td className="num">{s.on_time_pct == null ? '—' : `${s.on_time_pct}%`}</td>
                    <td className="num">{s.tasks_missed}</td>
                    <td className="num">{s.deliveries_done}</td>
                    <td className="num">{s.boxes_delivered}</td>
                    <td className="num">{rupees(s.amount_collected)}</td>
                    <td className="num">{s.days_present}</td>
                    <td className="num">{s.days_late}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="phone-record-list mobile-only-records">
            {data.staff.map((s, i) => (
              <PhoneRecord
                key={s.staff_id}
                title={`#${i + 1} ${s.name}`}
                meta={`${s.deliveries_done} deliveries · ${s.tasks_done} tasks (${s.on_time_pct ?? 0}% on-time)`}
                status={<span className="points-pill">{s.points} pts</span>}
                amount={s.amount_collected != null ? rupees(s.amount_collected) : 'Nil'}
                amountTone={s.amount_collected ? 'green' : 'yellow'}
              >
                <p className="xs muted">Boxes delivered: <strong>{s.boxes_delivered}</strong> · Missed tasks: {s.tasks_missed}</p>
                <p className="xs muted">Attendance: <strong>{s.days_present} days</strong> present ({s.days_late} late)</p>
              </PhoneRecord>
            ))}
          </div>
        </>
      )}
    </>
  )
}
