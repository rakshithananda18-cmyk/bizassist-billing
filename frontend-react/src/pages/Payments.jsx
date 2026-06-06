import { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { API_BASE } from '../config'
import { PageHeader, Table, Section } from '../components/ui'
import { Icon } from '../components/icons'

const PAYMENTS_PER_PAGE = 5

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

export default function Payments() {
  const { authFetch } = useAuth()
  const [paymentsData, setPaymentsData] = useState(null)
  const [overduePage, setOverduePage] = useState(1)
  const [pendingPage, setPendingPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    loadPayments()
  }, [])

  async function loadPayments() {
    setLoading(true)
    try {
      const res = await authFetch(`${API_BASE}/payments`)
      if (!res.ok) throw new Error('Failed to fetch payments database')
      const data = await res.json()
      setPaymentsData(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  // intent set -> deterministic /intent (0 AI tokens); else natural-language AI query
  function sendChip(query, intent) {
    sessionStorage.setItem('prefill_query', query)
    window.dispatchEvent(new CustomEvent('ai-shortcut', { detail: { query, intent, label: query } }))
  }

  if (loading) {
    return (
      <>
        <PageHeader title="Payments" subtitle="Dues and recovery" />
        <div className="widget">
          <div className="vskel"></div>
          <div className="vskel"></div>
        </div>
      </>
    )
  }

  if (error || !paymentsData) {
    return (
      <div className="vempty">
        <div className="vempty-icon"><Icon name="card" size={36} /></div>
        <div className="vempty-title">No payment data</div>
        <div className="vempty-sub">{error || 'Could not load payments.'}</div>
      </div>
    )
  }

  const overdueList = (paymentsData.invoice_dues || []).filter(p => (p.status || '').toLowerCase() === 'overdue')
  const pendingList = (paymentsData.invoice_dues || []).filter(p => (p.status || '').toLowerCase() === 'pending')

  const overdueSlice = overdueList.slice((overduePage - 1) * PAYMENTS_PER_PAGE, overduePage * PAYMENTS_PER_PAGE)
  const pendingSlice = pendingList.slice((pendingPage - 1) * PAYMENTS_PER_PAGE, pendingPage * PAYMENTS_PER_PAGE)

  const overdueTotalPages = Math.ceil(overdueList.length / PAYMENTS_PER_PAGE)
  const pendingTotalPages = Math.ceil(pendingList.length / PAYMENTS_PER_PAGE)

  const hasDues = (paymentsData.overdue_count + paymentsData.pending_count) > 0

  return (
    <>
      <PageHeader title="Payments" subtitle="Track dues and collections" style={{ marginBottom: 0 }} />

      {/* SUMMARY CARDS */}
      <div className="vsummary-strip" style={{ gridTemplateColumns: 'repeat(2, 1fr)', gap: 1, marginBottom: 12 }}>
        <div className="vsummary-card" style={{ borderLeftColor: '#c02a2a' }} onClick={() => sendChip('Show all overdue invoices with amounts', 'overdue_list')}>
          <div className="vsummary-label">Overdue Amount</div>
          <div className="vsummary-value" style={{ color: '#c02a2a' }}>{fmtAmount(paymentsData.total_overdue)}</div>
          <div className="vsummary-sub">{paymentsData.overdue_count} invoice{paymentsData.overdue_count !== 1 ? 's' : ''}</div>
        </div>
        <div className="vsummary-card" style={{ borderLeftColor: '#c97c22' }} onClick={() => sendChip('List all pending payments', 'pending_list')}>
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

          {/* Overdue Pagination */}
          {overdueTotalPages > 1 && (
            <div className="db-pagination" style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 12, marginTop: 12, marginBottom: 12 }}>
              <button
                className="matte-glass"
                style={{ padding: '6px 12px', cursor: 'pointer', borderRadius: 6, fontSize: 12, border: '1px solid var(--border-color)', background: 'var(--card-color)', color: 'var(--text-color)' }}
                onClick={() => setOverduePage(overduePage - 1)}
                disabled={overduePage === 1}
              >
                ← Previous
              </button>
              <span style={{ fontSize: '12.5px', color: 'var(--secondary-text)', fontWeight: 600 }}>
                Page {overduePage} / {overdueTotalPages}
              </span>
              <button
                className="matte-glass"
                style={{ padding: '6px 12px', cursor: 'pointer', borderRadius: 6, fontSize: 12, border: '1px solid var(--border-color)', background: 'var(--card-color)', color: 'var(--text-color)' }}
                onClick={() => setOverduePage(overduePage + 1)}
                disabled={overduePage >= overdueTotalPages}
              >
                Next →
              </button>
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

          {/* Pending Pagination */}
          {pendingTotalPages > 1 && (
            <div className="db-pagination" style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 12, marginTop: 12, marginBottom: 12 }}>
              <button
                className="matte-glass"
                style={{ padding: '6px 12px', cursor: 'pointer', borderRadius: 6, fontSize: 12, border: '1px solid var(--border-color)', background: 'var(--card-color)', color: 'var(--text-color)' }}
                onClick={() => setPendingPage(pendingPage - 1)}
                disabled={pendingPage === 1}
              >
                ← Previous
              </button>
              <span style={{ fontSize: '12.5px', color: 'var(--secondary-text)', fontWeight: 600 }}>
                Page {pendingPage} / {pendingTotalPages}
              </span>
              <button
                className="matte-glass"
                style={{ padding: '6px 12px', cursor: 'pointer', borderRadius: 6, fontSize: 12, border: '1px solid var(--border-color)', background: 'var(--card-color)', color: 'var(--text-color)' }}
                onClick={() => setPendingPage(pendingPage + 1)}
                disabled={pendingPage >= pendingTotalPages}
              >
                Next →
              </button>
            </div>
          )}
        </Section>
      )}

      {/* EMPTY STATE */}
      {!hasDues && (
        <div className="vempty">
          <div className="vempty-icon">✓</div>
          <div className="vempty-title">All clear!</div>
          <div className="vempty-sub">No overdue or pending payments found.</div>
        </div>
      )}
    </>
  )
}
