import { useState, useEffect, useCallback } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { API_BASE } from '../config'
import { PageHeader, Table, Section, Spinner } from '../components/ui'
import { Icon } from '../components/icons'

const PAYMENTS_PER_PAGE = 5

// ─── Formatters ───────────────────────────────────────────────────────────────
function fmtAmount(n) {
  if (!n && n !== 0) return '—'
  if (n >= 100000) return '₹' + (n / 100000).toFixed(1) + 'L'
  if (n >= 1000)   return '₹' + Math.round(n / 1000) + 'k'
  return '₹' + Math.round(n)
}

function fmtFull(n) {
  if (!n && n !== 0) return '—'
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

// ─── Activity status pill style ───────────────────────────────────────────────
function statusStyle(status) {
  switch ((status || '').toLowerCase()) {
    case 'sent':   return { background: '#d1fae5', color: '#065f46' }
    case 'failed': return { background: '#fee2e2', color: '#991b1b' }
    case 'logged': return { background: '#e0f2fe', color: '#075985' }
    default:       return { background: 'var(--hover-bg)', color: 'var(--secondary-text)' }
  }
}

// ─── Friendly action labels ───────────────────────────────────────────────────
const ACTION_LABELS = {
  send_payment_reminders: 'Payment Reminder',
  reorder_inventory:      'Inventory Reorder',
  send_daily_summary:     'Daily Summary',
}

// ─── Mini stat card ───────────────────────────────────────────────────────────
function StatCard({ label, value, color }) {
  return (
    <div style={{
      flex: '1 1 100px', minWidth: 90,
      background: 'var(--widget-bg)',
      border: '1px solid var(--widget-border)',
      borderRadius: 10, padding: '12px 16px',
      display: 'flex', flexDirection: 'column', gap: 3,
    }}>
      <div style={{ fontSize: 20, fontWeight: 700, color: color || 'var(--accent-color)', lineHeight: 1.1 }}>{value}</div>
      <div style={{ fontSize: 12, color: 'var(--secondary-text)', fontWeight: 500 }}>{label}</div>
    </div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────
export default function Payments() {
  const { authFetch } = useAuth()

  // tab: 'payments' | 'activity'
  const [tab, setTab] = useState('payments')

  // — Payments state —
  const [paymentsData, setPaymentsData] = useState(null)
  const [overduePage, setOverduePage]   = useState(1)
  const [pendingPage, setPendingPage]   = useState(1)
  const [loadingPay, setLoadingPay]     = useState(true)
  const [errorPay, setErrorPay]         = useState('')

  // — Activity state —
  const [actItems, setActItems]       = useState([])
  const [loadingAct, setLoadingAct]   = useState(false)
  const [errorAct, setErrorAct]       = useState('')
  const [openId, setOpenId]           = useState(null)
  const [actFilter, setActFilter]     = useState('all')
  const [actLoaded, setActLoaded]     = useState(false)  // lazy-load once

  // ── Load payments ─────────────────────────────────────────────────────────
  useEffect(() => { loadPayments() }, [])

  async function loadPayments() {
    setLoadingPay(true)
    try {
      const res = await authFetch(`${API_BASE}/payments`)
      if (!res.ok) throw new Error('Failed to fetch payments')
      const data = await res.json()
      setPaymentsData(data)
    } catch (err) {
      setErrorPay(err.message)
    } finally {
      setLoadingPay(false)
    }
  }

  // ── Load activity (lazy: only when tab switches to 'activity') ────────────
  const loadActivity = useCallback(async () => {
    setLoadingAct(true)
    setErrorAct('')
    try {
      const res = await authFetch(`${API_BASE}/action/history?limit=200`)
      if (!res.ok) throw new Error('Failed to load activity')
      const data = await res.json()
      setActItems(Array.isArray(data.items) ? data.items : [])
      setActLoaded(true)
    } catch (err) {
      setErrorAct(err.message)
    } finally {
      setLoadingAct(false)
    }
  }, [authFetch])

  useEffect(() => {
    if (tab === 'activity') {
      loadActivity()
    }
  }, [tab, loadActivity])

  // ── Chip / Action helpers ─────────────────────────────────────────────────
  function sendChip(query, intent) {
    sessionStorage.setItem('prefill_query', query)
    window.dispatchEvent(new CustomEvent('ai-shortcut', { detail: { query, intent, label: query } }))
  }
  function sendAction(action, label, params) {
    window.dispatchEvent(new CustomEvent('ai-shortcut', { detail: { action, label, params } }))
  }

  // ── Derived activity stats ────────────────────────────────────────────────
  const actTotal   = actItems.length
  const actSent    = actItems.filter(i => i.status === 'sent').length
  const actFailed  = actItems.filter(i => i.status === 'failed').length
  const actPending = actItems.filter(i => i.status === 'logged').length

  const actTypes = ['all', ...Array.from(new Set(actItems.map(i => i.action)))]
  const shownAct = actFilter === 'all' ? actItems : actItems.filter(i => i.action === actFilter)

  // ── Payments derived ──────────────────────────────────────────────────────
  const overdueList = loadingPay || !paymentsData ? [] :
    (paymentsData.invoice_dues || []).filter(p => (p.status || '').toLowerCase() === 'overdue')
  const pendingList = loadingPay || !paymentsData ? [] :
    (paymentsData.invoice_dues || []).filter(p => (p.status || '').toLowerCase() === 'pending')

  const overdueSlice = overdueList.slice((overduePage - 1) * PAYMENTS_PER_PAGE, overduePage * PAYMENTS_PER_PAGE)
  const pendingSlice = pendingList.slice((pendingPage - 1) * PAYMENTS_PER_PAGE, pendingPage * PAYMENTS_PER_PAGE)

  const overdueTotalPages = Math.ceil(overdueList.length / PAYMENTS_PER_PAGE)
  const pendingTotalPages = Math.ceil(pendingList.length / PAYMENTS_PER_PAGE)
  const hasDues = paymentsData ? (paymentsData.overdue_count + paymentsData.pending_count) > 0 : false

  // ── Activity badge for the tab label ─────────────────────────────────────
  const actBadge = actLoaded && actTotal > 0
    ? <span className="vbadge" style={{ background: 'rgba(2,132,199,0.15)', color: '#0284c7', marginLeft: 4 }}>{actTotal}</span>
    : null

  return (
    <>
      {/* PAGE HEADER with tab switcher */}
      <PageHeader
        title="Payments"
        subtitle={tab === 'payments' ? 'Track dues and collections' : 'Audit trail of payment actions'}
        style={{ marginBottom: 0 }}
        actions={
          <>
            <button
              className="chip"
              style={{ opacity: tab === 'payments' ? 1 : 0.55, fontWeight: tab === 'payments' ? 700 : 400 }}
              onClick={() => setTab('payments')}
            >
              Payments
            </button>
            <button
              className="chip"
              style={{ opacity: tab === 'activity' ? 1 : 0.55, fontWeight: tab === 'activity' ? 700 : 400, display: 'inline-flex', alignItems: 'center' }}
              onClick={() => setTab('activity')}
            >
              Activity Log{actBadge}
            </button>
          </>
        }
      />

      {/* ════════════════════════════════════════
          TAB: PAYMENTS
      ════════════════════════════════════════ */}
      {tab === 'payments' && (
        <>
          {/* Loading skeleton */}
          {loadingPay && (
            <div className="widget" style={{ marginTop: 12 }}>
              <div className="vskel" /><div className="vskel" />
            </div>
          )}

          {/* Error */}
          {!loadingPay && (errorPay || !paymentsData) && (
            <div className="vempty">
              <div className="vempty-icon"><Icon name="card" size={36} /></div>
              <div className="vempty-title">No payment data</div>
              <div className="vempty-sub">{errorPay || 'Could not load payments.'}</div>
            </div>
          )}

          {/* Content */}
          {!loadingPay && paymentsData && (
            <>
              {/* SUMMARY CARDS */}
              <div className="vsummary-strip" style={{ gridTemplateColumns: 'repeat(2, 1fr)', gap: 1, marginBottom: 12, marginTop: 12 }}>
                <div
                  className="vsummary-card"
                  style={{ borderLeftColor: '#c02a2a' }}
                  onClick={() => sendChip('Show all overdue invoices with amounts', 'overdue_list')}
                >
                  <div className="vsummary-label">Overdue Amount</div>
                  <div className="vsummary-value" style={{ color: '#c02a2a' }}>{fmtAmount(paymentsData.total_overdue)}</div>
                  <div className="vsummary-sub">{paymentsData.overdue_count} invoice{paymentsData.overdue_count !== 1 ? 's' : ''}</div>
                </div>
                <div
                  className="vsummary-card"
                  style={{ borderLeftColor: '#c97c22' }}
                  onClick={() => sendChip('List all pending payments', 'pending_list')}
                >
                  <div className="vsummary-label">Pending Amount</div>
                  <div className="vsummary-value" style={{ color: '#c97c22' }}>{fmtAmount(paymentsData.total_pending)}</div>
                  <div className="vsummary-sub">{paymentsData.pending_count} invoice{paymentsData.pending_count !== 1 ? 's' : ''}</div>
                </div>
              </div>

              {/* OVERDUE TABLE */}
              {paymentsData.overdue_count > 0 && (
                <Section
                  title="Overdue"
                  count={paymentsData.overdue_count}
                  icon={<Icon name="alert" size={16} />}
                  collapsible
                  noPad
                  style={{ marginBottom: 12 }}
                  actions={
                    <button
                      className="chip"
                      style={{ fontSize: 11, padding: '3px 10px', display: 'inline-flex', alignItems: 'center', gap: 5 }}
                      onClick={() => sendAction('send_payment_reminders', 'Send payment reminders')}
                      title="Preview and log reminder drafts for overdue customers"
                    >
                      <Icon name="bell" size={12} /> Send reminders
                    </button>
                  }
                >
                  <Table head={['Customer', 'Invoice', 'Amount', 'Due Date', '']}>
                    {overdueSlice.map((p, idx) => (
                      <tr key={idx}>
                        <td style={{ fontWeight: 500 }}>{p.customer || '—'}</td>
                        <td>{p.invoice_id || '—'}</td>
                        <td style={{ fontFamily: "'Crimson Pro',serif", fontSize: 15, color: '#c02a2a', fontWeight: 600 }}>
                          {fmtFull(p.amount)}
                        </td>
                        <td style={{ color: 'var(--secondary-text)', fontSize: 12 }}>{p.due_date || '—'}</td>
                        <td>
                          <button className="vlink" onClick={() => sendChip(`How much does ${p.customer} owe me?`)}>
                            Ask AI
                          </button>
                        </td>
                      </tr>
                    ))}
                  </Table>

                  {overdueTotalPages > 1 && (
                    <div className="db-pagination" style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 12, margin: '12px 0' }}>
                      <button
                        className="matte-glass"
                        style={{ padding: '6px 12px', borderRadius: 6, fontSize: 12, border: '1px solid var(--border-color)', background: 'var(--card-color)', color: 'var(--text-color)' }}
                        onClick={() => setOverduePage(overduePage - 1)}
                        disabled={overduePage === 1}
                      >← Previous</button>
                      <span style={{ fontSize: '12.5px', color: 'var(--secondary-text)', fontWeight: 600 }}>
                        Page {overduePage} / {overdueTotalPages}
                      </span>
                      <button
                        className="matte-glass"
                        style={{ padding: '6px 12px', borderRadius: 6, fontSize: 12, border: '1px solid var(--border-color)', background: 'var(--card-color)', color: 'var(--text-color)' }}
                        onClick={() => setOverduePage(overduePage + 1)}
                        disabled={overduePage >= overdueTotalPages}
                      >Next →</button>
                    </div>
                  )}
                </Section>
              )}

              {/* PENDING TABLE */}
              {paymentsData.pending_count > 0 && (
                <Section
                  title="Pending"
                  count={paymentsData.pending_count}
                  icon={<Icon name="clock" size={16} />}
                  collapsible
                  noPad
                  style={{ marginBottom: 12 }}
                >
                  <Table head={['Customer', 'Invoice', 'Amount', 'Due Date', '']}>
                    {pendingSlice.map((p, idx) => (
                      <tr key={idx}>
                        <td style={{ fontWeight: 500 }}>{p.customer || '—'}</td>
                        <td>{p.invoice_id || '—'}</td>
                        <td style={{ fontFamily: "'Crimson Pro',serif", fontSize: 15, fontWeight: 600 }}>
                          {fmtFull(p.amount)}
                        </td>
                        <td style={{ color: 'var(--secondary-text)', fontSize: 12 }}>{p.due_date || '—'}</td>
                        <td>
                          <button className="vlink" onClick={() => sendChip(`Tell me about pending payment from ${p.customer}`)}>
                            Ask AI
                          </button>
                        </td>
                      </tr>
                    ))}
                  </Table>

                  {pendingTotalPages > 1 && (
                    <div className="db-pagination" style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 12, margin: '12px 0' }}>
                      <button
                        className="matte-glass"
                        style={{ padding: '6px 12px', borderRadius: 6, fontSize: 12, border: '1px solid var(--border-color)', background: 'var(--card-color)', color: 'var(--text-color)' }}
                        onClick={() => setPendingPage(pendingPage - 1)}
                        disabled={pendingPage === 1}
                      >← Previous</button>
                      <span style={{ fontSize: '12.5px', color: 'var(--secondary-text)', fontWeight: 600 }}>
                        Page {pendingPage} / {pendingTotalPages}
                      </span>
                      <button
                        className="matte-glass"
                        style={{ padding: '6px 12px', borderRadius: 6, fontSize: 12, border: '1px solid var(--border-color)', background: 'var(--card-color)', color: 'var(--text-color)' }}
                        onClick={() => setPendingPage(pendingPage + 1)}
                        disabled={pendingPage >= pendingTotalPages}
                      >Next →</button>
                    </div>
                  )}
                </Section>
              )}

              {/* ALL CLEAR */}
              {!hasDues && (
                <div className="vempty">
                  <div className="vempty-icon">✓</div>
                  <div className="vempty-title">All clear!</div>
                  <div className="vempty-sub">No overdue or pending payments found.</div>
                </div>
              )}
            </>
          )}
        </>
      )}

      {/* ════════════════════════════════════════
          TAB: ACTIVITY LOG
      ════════════════════════════════════════ */}
      {tab === 'activity' && (
        <>
          {/* Loading */}
          {loadingAct && (
            <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
              <Spinner size={22} />
            </div>
          )}

          {/* Error */}
          {!loadingAct && errorAct && (
            <div className="widget" style={{ color: '#c02a2a', marginTop: 12 }}>{errorAct}</div>
          )}

          {/* Empty */}
          {!loadingAct && !errorAct && actTotal === 0 && (
            <div className="vempty widget" style={{ marginTop: 16, textAlign: 'center', padding: 40 }}>
              <svg xmlns="http://www.w3.org/2000/svg" width="30" height="30" viewBox="0 0 24 24" fill="none"
                stroke="var(--secondary-text)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
              </svg>
              <div style={{ fontWeight: 600, marginTop: 10, fontSize: 15 }}>No activity yet</div>
              <div className="vempty-sub" style={{ marginTop: 4 }}>
                Actions you run — like sending payment reminders — appear here with a full audit trail.
              </div>
            </div>
          )}

          {/* Content */}
          {!loadingAct && !errorAct && actTotal > 0 && (
            <>
              {/* Summary stat cards */}
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 14, marginBottom: 4 }}>
                <StatCard label="Total Actions"   value={actTotal}   color="var(--accent-color)" />
                <StatCard label="Sent"            value={actSent}    color="#059669" />
                <StatCard label="Logged / Queued" value={actPending} color="#0284c7" />
                <StatCard label="Failed"          value={actFailed}  color="#dc2626" />
              </div>

              {/* Filter bar + Refresh */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
                {actTypes.map(k => (
                  <button
                    key={k}
                    className="chip"
                    onClick={() => setActFilter(k)}
                    style={{
                      background: actFilter === k ? 'var(--accent-color)' : undefined,
                      color:      actFilter === k ? '#fff'                 : undefined,
                      fontWeight: actFilter === k ? 700                    : 500,
                      fontSize: 12,
                    }}
                  >
                    {k === 'all' ? 'All actions' : (ACTION_LABELS[k] || k)}
                  </button>
                ))}
                <div style={{ flex: 1 }} />
                <button
                  id="activity-refresh-btn"
                  className="chip"
                  onClick={loadActivity}
                  style={{ fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 5 }}
                  title="Refresh activity log"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none"
                    stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="23 4 23 10 17 10" />
                    <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
                  </svg>
                  Refresh
                </button>
              </div>

              {/* No results for filter */}
              {shownAct.length === 0 && (
                <div className="widget" style={{ marginTop: 12, textAlign: 'center', padding: 20, color: 'var(--secondary-text)' }}>
                  No actions matching this filter.
                </div>
              )}

              {/* Main table */}
              {shownAct.length > 0 && (
                <Section
                  title="Logged actions"
                  count={shownAct.length}
                  icon={
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none"
                      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
                    </svg>
                  }
                  collapsible
                  noPad
                  style={{ marginTop: 14 }}
                >
                  <Table head={['When', 'Action', 'Target', 'Amount', 'Status', '']}>
                    {shownAct.flatMap(it => {
                      const rows = [(
                        <tr key={it.id}>
                          <td style={{ color: 'var(--secondary-text)', fontSize: 13, whiteSpace: 'nowrap' }}>
                            {fmtDate(it.created_at)}
                          </td>
                          <td style={{ fontWeight: 600 }}>
                            {ACTION_LABELS[it.action] || it.action}
                          </td>
                          <td style={{ color: 'var(--secondary-text)', maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {it.target || '—'}
                          </td>
                          <td style={{ fontWeight: 600 }}>
                            {it.amount != null ? fmtFull(it.amount) : '—'}
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
          )}
        </>
      )}
    </>
  )
}
