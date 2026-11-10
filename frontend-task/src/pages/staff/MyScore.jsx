import React from 'react'
import { api } from '../../lib/api'
import { useDay } from '../../layouts/StaffLayout'
import { rupees } from '../../lib/format'
import { ErrorNote, Loader, Stat, useLoad } from '../../components/ui'
import { AwardIcon, ClockIcon, RefreshIcon, SparklesIcon, TruckIcon } from '../../components/Icons'

export default function MyScore() {
  const { today } = useDay()
  const { data: s, error, loading, reload } = useLoad(() => api.get('/api/my/scorecard'), [])

  return (
    <>
      <div className="row-between" style={{ alignItems: 'center' }}>
        <h2 style={{ fontSize: 'var(--fs-lg)', fontWeight: 800, margin: 0 }}>Monthly Performance</h2>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          style={{ gap: 4, fontWeight: 600 }}
          onClick={reload}
          title="Refresh scorecard"
        >
          <RefreshIcon size={14} /> Refresh
        </button>
      </div>

      <ErrorNote error={error} />

      {loading && !s ? (
        <Loader label="Calculating your monthly score…" />
      ) : s && (
        <>
          {/* Hero Points Card */}
          <div
            className="card"
            style={{
              borderRadius: 18,
              background: 'linear-gradient(135deg, rgba(193, 95, 60, 0.12) 0%, var(--bg-2) 100%)',
              border: '1px solid var(--accent)',
              boxShadow: 'var(--shadow-sm)',
              padding: '20px',
            }}
          >
            <div className="row-between" style={{ alignItems: 'flex-start' }}>
              <div>
                <span className="xs muted" style={{ textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 700 }}>
                  Total Points Earned
                </span>
                <div style={{ fontSize: '2.4rem', fontWeight: 900, color: 'var(--accent)', lineHeight: 1.1, marginTop: 4 }}>
                  {s.points}
                </div>
              </div>
              <div
                style={{
                  width: 48,
                  height: 48,
                  borderRadius: 14,
                  background: 'var(--accent)',
                  color: '#fff',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <AwardIcon size={26} strokeWidth={2} />
              </div>
            </div>
            {today && (
              <div className="row" style={{ marginTop: 12, alignItems: 'center', gap: 6 }}>
                <span className="badge badge-accent" style={{ fontWeight: 700 }}>
                  +{today.points_today} pts earned today
                </span>
                <span className="xs muted">Keep up the streak!</span>
              </div>
            )}
          </div>

          {/* Metric Grid */}
          <div className="grid grid-2" style={{ gap: 12 }}>
            <Stat
              label="Punctuality"
              value={s.on_time_pct == null ? '—' : `${s.on_time_pct}%`}
              sub={`${s.tasks_on_time}/${s.tasks_done} on-time tasks`}
              progress={s.on_time_pct}
              icon={<ClockIcon size={18} />}
            />
            <Stat
              label="Deliveries"
              value={s.deliveries_done}
              sub={`${s.boxes_delivered} total boxes`}
              icon={<TruckIcon size={18} />}
            />
            <Stat
              label="Attendance"
              value={`${s.days_present} Days`}
              sub={s.days_present > 0 ? (s.days_late > 0 ? `${s.days_late} days late` : '100% on time') : 'No attendance recorded this month'}
              badge={s.days_present > 0 && s.days_late === 0 ? 'Perfect' : undefined}
            />
            <Stat
              label="Collections"
              value={rupees(s.amount_collected)}
              sub="Total received"
            />
          </div>

          {s.tasks_missed > 0 && (
            <div className="alert alert-warning" style={{ borderRadius: 12, fontWeight: 600 }}>
              ⚠️ {s.tasks_missed} task(s) missed or skipped this month.
            </div>
          )}

          {/* Gamification Tip Card */}
          <div
            className="card plain"
            style={{
              borderRadius: 14,
              border: '1px solid var(--border)',
              padding: '14px 16px',
              display: 'flex',
              gap: 12,
              alignItems: 'center',
            }}
          >
            <div
              style={{
                width: 36,
                height: 36,
                borderRadius: '50%',
                background: 'var(--accent-dim)',
                color: 'var(--accent)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
              }}
            >
              <SparklesIcon size={18} />
            </div>
            <div className="xs muted" style={{ lineHeight: 1.4 }}>
              <strong style={{ color: 'var(--text-primary)', display: 'block', marginBottom: 2 }}>How Points Work</strong>
              Finish assigned tasks before due time to earn full points. Check in on-time each morning for bonus points!
            </div>
          </div>
        </>
      )}
    </>
  )
}
