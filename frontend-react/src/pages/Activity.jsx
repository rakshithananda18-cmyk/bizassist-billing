import { useState, useEffect, useCallback } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { API_BASE } from '../config'
import { PageHeader, Table, Section, Spinner } from '../components/ui'
import { Icon } from '../components/icons'

// ─── Human-readable labels for action keys ────────────────────────────────────
const ACTION_LABELS = {
  send_payment_reminders: 'Payment Reminder',
  reorder_inventory:      'Inventory Reorder',
  send_daily_summary:     'Daily Summary',
}

// ─── Status pill colours ──────────────────────────────────────────────────────
function statusStyle(status) {
  switch ((status || '').toLowerCase()) {
    case 'sent':    return { background: '#d1fae5', color: '#065f46' }   // green
    case 'failed':  return { background: '#fee2e2', color: '#991b1b' }   // red
    case 'logged':  return { background: '#e0f2fe', color: '#075985' }   // blue
    default:        return { background: 'var(--hover-bg)', color: 'var(--secondary-text)' }
  }
}

function fmtMoney(n) {
  if (n == null) return '—'
  return '₹' + Number(n).toLocaleString('en-IN')
}

function fmtDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d)) return iso
  return d.toLocaleString('en-IN', {
    day: 'numeric', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

// ─── Mini stat card ───────────────────────────────────────────────────────────
function StatCard({ label, value, color }) {
  return (
    <div style={{
      flex: '1 1 120px', minWidth: 110,
      background: 'var(--widget-bg)',
      border: '1px solid var(--widget-border)',
      borderRadius: 10, padding: '14px 18px',
      display: 'flex', flexDirection: 'column', gap: 4,
    }}>
      <div style={{ fontSize: 22, fontWeight: 700, color: color || 'var(--accent-color)', lineHeight: 1.1 }}>{value}</div>
      <div style={{ fontSize: 12, color: 'var(--secondary-text)', fontWeight: 500 }}>{label}</div>
    </div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────
export default function Activity() {
  const { authFetch } = useAuth()
  const [items, setItems]     = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState('')
  const [openId, setOpenId]   = useState(null)   // expanded detail row
  const [filter, setFilter]   = useState('all')  // 'all' | action key

  const loadHistory = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await authFetch(`${API_BASE}/action/history?limit=200`)
      if (!res.ok) throw new Error('Failed to load activity')
      const data = await res.json()
      setItems(Array.isArray(data.items) ? data.items : [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [authFetch])

  useEffect(() => { loadHistory() }, [loadHistory])

  // ── Derived stats ────────────────────────────────────────────────────────
  const total   = items.length
  const sent    = items.filter(i => i.status === 'sent').length
  const failed  = items.filter(i => i.status === 'failed').length
  const pending = items.filter(i => i.status === 'logged').length

  // ── Unique action types for filter bar ───────────────────────────────────
  const actionTypes = ['all', ...Array.from(new Set(items.map(i => i.action)))]

  // ── Filtered list ────────────────────────────────────────────────────────
  const shown = filter === 'all' ? items : items.filter(i => i.action === filter)

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <>
      <PageHeader
        title="Activity Log"
        subtitle="Audit trail of every agentic action run in your account"
        style={{ marginBottom: 0 }}
      />

      {/* ── Summary stat cards ─── */}
      {!error && !loading && total > 0 && (
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 14, marginBottom: 2 }}>
          <StatCard label="Total Actions"   value={total}   color="var(--accent-color)" />
          <StatCard label="Sent"            value={sent}    color="#059669" />
          <StatCard label="Logged / Queued" value={pending} color="#0284c7" />
          <StatCard label="Failed"          value={failed}  color="#dc2626" />
        </div>
      )}

      {/* ── Filter bar + Refresh ─── */}
      {!error && !loading && total > 0 && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8, marginTop: 12,
          flexWrap: 'wrap',
        }}>
          {actionTypes.map(k => (
            <button
              key={k}
              onClick={() => setFilter(k)}
              className="chip"
              style={{
                background: filter === k ? 'var(--accent-color)' : undefined,
                color:      filter === k ? '#fff'                 : undefined,
                fontWeight: filter === k ? 700                    : 500,
                fontSize: 12,
              }}
            >
              {k === 'all' ? 'All actions' : (ACTION_LABELS[k] || k)}
            </button>
          ))}

          {/* spacer */}
          <div style={{ flex: 1 }} />

          <button
            id="activity-refresh-btn"
            className="chip"
            onClick={loadHistory}
            style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 5 }}
            title="Refresh activity log"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="23 4 23 10 17 10"></polyline>
              <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
            </svg>
            Refresh
          </button>
        </div>
      )}

      {/* ── Loading ─── */}
      {loading && (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
          <Spinner size={22} />
        </div>
      )}

      {/* ── Error ─── */}
      {!loading && error && (
        <div className="widget" style={{ color: '#c02a2a', marginTop: 12 }}>{error}</div>
      )}

      {/* ── Empty state ─── */}
      {!loading && !error && total === 0 && (
        <div className="widget vempty" style={{ marginTop: 16, textAlign: 'center', padding: 40 }}>
          <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none"
            stroke="var(--secondary-text)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10"></circle>
            <polyline points="12 6 12 12 16 14"></polyline>
          </svg>
          <div style={{ fontWeight: 600, marginTop: 10, fontSize: 15 }}>No activity yet</div>
          <div className="vempty-sub" style={{ marginTop: 4 }}>
            Actions you run — like sending payment reminders — will appear here with a full audit trail.
          </div>
        </div>
      )}

      {/* ── No results for current filter ─── */}
      {!loading && !error && total > 0 && shown.length === 0 && (
        <div className="widget vempty" style={{ marginTop: 12, textAlign: 'center', padding: 28 }}>
          <div style={{ fontWeight: 600 }}>No actions matching this filter</div>
        </div>
      )}

      {/* ── Main table ─── */}
      {!loading && !error && shown.length > 0 && (
        <Section
          title="Logged actions"
          count={shown.length}
          icon={
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10"></circle>
              <polyline points="12 6 12 12 16 14"></polyline>
            </svg>
          }
          collapsible
          noPad
          style={{ marginTop: 14 }}
        >
          <Table head={['When', 'Action', 'Target', 'Amount', 'Status', '']}>
            {shown.flatMap(it => {
              const rows = [(
                <tr key={it.id}>
                  <td style={{ color: 'var(--secondary-text)', fontSize: 13, whiteSpace: 'nowrap' }}>
                    {fmtDate(it.created_at)}
                  </td>
                  <td style={{ fontWeight: 600 }}>
                    {ACTION_LABELS[it.action] || it.action}
                  </td>
                  <td style={{ color: 'var(--secondary-text)', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {it.target || '—'}
                  </td>
                  <td style={{ fontWeight: 600 }}>
                    {it.amount != null ? fmtMoney(it.amount) : '—'}
                  </td>
                  <td>
                    <span className="vpill" style={statusStyle(it.status)}>
                      {it.status || 'logged'}
                    </span>
                  </td>
                  <td>
                    {it.detail && (
                      <button
                        className="chip"
                        style={{ fontSize: 11, padding: '2px 8px' }}
                        onClick={() => setOpenId(openId === it.id ? null : it.id)}
                        title="Toggle message detail"
                      >
                        {openId === it.id ? 'Hide' : 'View'}
                      </button>
                    )}
                  </td>
                </tr>
              )]

              if (openId === it.id && it.detail) {
                rows.push(
                  <tr key={`${it.id}-detail`}>
                    <td colSpan={6} style={{ background: 'var(--hover-bg)', padding: 0 }}>
                      <pre style={{
                        whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: 12.5,
                        color: 'var(--secondary-text)', margin: 0,
                        padding: '10px 16px', lineHeight: 1.6,
                        borderLeft: '3px solid var(--accent-color)',
                      }}>
                        {it.detail}
                      </pre>
                    </td>
                  </tr>
                )
              }

              return rows
            })}
          </Table>
        </Section>
      )}
    </>
  )
}
