import React from 'react'
import { api } from '../../lib/api'
import { useDay } from '../../layouts/StaffLayout'
import { rupees } from '../../lib/format'
import { ErrorNote, Loader, Stat, useLoad } from '../../components/ui'

export default function MyScore() {
  const { today } = useDay()
  const { data: s, error, loading } = useLoad(() => api.get('/api/my/scorecard'), [])
  return (
    <>
      <div style={{ fontWeight: 700, fontSize: 'var(--fs-lg)' }}>My score · this month</div>
      <ErrorNote error={error} />
      {loading && !s ? <Loader /> : s && (
        <div className="grid grid-4">
          <Stat label="Points" value={s.points} sub={today ? `${today.points_today} today` : null} />
          <Stat label="On time" value={s.on_time_pct == null ? '—' : `${s.on_time_pct}%`} sub={`${s.tasks_on_time}/${s.tasks_done} tasks`} />
          <Stat label="Deliveries" value={s.deliveries_done} sub={`${s.boxes_delivered} boxes`} />
          <Stat label="Days present" value={s.days_present} sub={`${s.days_late} late`} />
          <Stat label="Missed tasks" value={s.tasks_missed} />
          <Stat label="Collected" value={rupees(s.amount_collected)} />
        </div>
      )}
      <div className="xs muted">Points: finish a task by its due time to earn its points; check in on time for a bonus.</div>
    </>
  )
}
