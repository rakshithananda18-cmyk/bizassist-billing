import { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { API_BASE } from '../config'
import { PageHeader, Section, Table } from '../components/ui'
import { Icon } from '../components/icons'

const INVOICES_PER_PAGE = 10

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

function StatusPill({ status }) {
  const s = (status || '').toLowerCase()
  const map = {
    paid:    { color: '#27864a', bg: 'rgba(39,134,74,0.10)' },
    pending: { color: '#b06510', bg: 'rgba(176,101,16,0.10)' },
    overdue: { color: '#c02a2a', bg: 'rgba(192,42,42,0.10)' },
  }
  const style = map[s] || { color: 'var(--secondary-text)', bg: 'var(--accent-softer)' }
  return (
    <span className="vpill" style={{ color: style.color, background: style.bg }}>
      {status || '—'}
    </span>
  )
}

export default function Invoices() {
  const { authFetch } = useAuth()
  const [invoices, setInvoices] = useState([])
  const [filter, setFilter] = useState('all')
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    loadInvoices()
  }, [])

  async function loadInvoices() {
    setLoading(true)
    try {
      const res = await authFetch(`${API_BASE}/database`)
      if (!res.ok) throw new Error('Failed to fetch invoices database')
      const data = await res.json()
      setInvoices(data.invoices || [])
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
        <PageHeader title="Invoices" subtitle="All billing records" />
        <div className="widget">
          <div className="vskel"></div>
          <div className="vskel"></div>
          <div className="vskel"></div>
        </div>
      </>
    )
  }

  if (error) {
    return (
      <div className="vempty">
        <div className="vempty-icon"><Icon name="file" size={36} /></div>
        <div className="vempty-title">No invoices found</div>
        <div className="vempty-sub">{error}</div>
      </div>
    )
  }

  const all = invoices
  const filtered = filter === 'all'
    ? all
    : all.filter(i => (i.status || '').toLowerCase() === filter)

  const paidCount = all.filter(i => (i.status || '').toLowerCase() === 'paid').length
  const pendingCount = all.filter(i => (i.status || '').toLowerCase() === 'pending').length
  const overdueCount = all.filter(i => (i.status || '').toLowerCase() === 'overdue').length
  const totalAmount = all.reduce((s, i) => s + (i.amount || 0), 0)

  const totalPages = Math.ceil(filtered.length / INVOICES_PER_PAGE)
  const slicedInvoices = filtered.slice((page - 1) * INVOICES_PER_PAGE, page * INVOICES_PER_PAGE)

  const tabs = ['all', 'paid', 'pending', 'overdue'].map(t => {
    const count = t === 'all' ? all.length : all.filter(i => (i.status || '').toLowerCase() === t).length
    const active = t === filter ? ' vtab-active' : ''
    return (
      <button key={t} className={`vtab${active}`} onClick={() => { setFilter(t); setPage(1) }}>
        {t.charAt(0).toUpperCase() + t.slice(1)} <span className="vtab-count">{count}</span>
      </button>
    )
  })

  return (
    <>
      <PageHeader
        title={<>Invoices <span className="vbadge">{all.length}</span></>}
        subtitle={`${all.length} total · ${fmtAmount(totalAmount)} revenue`}
        style={{ marginBottom: 0 }}
      />

      {/* SUMMARY STRIP — same card style as Dashboard / Payments / Database */}
      <div className="vsummary-strip" style={{ marginBottom: 16 }}>
        <div className="vsummary-card" style={{ borderLeftColor: 'var(--accent-color)' }} onClick={() => sendChip('What is my total revenue?', 'total_revenue')}>
          <div className="vsummary-label">Total</div>
          <div className="vsummary-value">{fmtAmount(totalAmount)}</div>
          <div className="vsummary-sub">{all.length} invoices</div>
        </div>
        <div className="vsummary-card" style={{ borderLeftColor: '#3a9a5c' }} onClick={() => sendChip('Show my paid invoices summary', 'invoice_count')}>
          <div className="vsummary-label">Paid</div>
          <div className="vsummary-value" style={{ color: '#27864a' }}>{paidCount}</div>
          <div className="vsummary-sub">settled</div>
        </div>
        <div className="vsummary-card" style={{ borderLeftColor: '#c97c22' }} onClick={() => sendChip('List all pending invoices', 'pending_list')}>
          <div className="vsummary-label">Pending</div>
          <div className="vsummary-value" style={{ color: '#b06510' }}>{pendingCount}</div>
          <div className="vsummary-sub">awaiting</div>
        </div>
        <div className="vsummary-card" style={{ borderLeftColor: '#c02a2a' }} onClick={() => sendChip('List all overdue invoices with amounts', 'overdue_list')}>
          <div className="vsummary-label">Overdue</div>
          <div className="vsummary-value" style={{ color: '#c02a2a' }}>{overdueCount}</div>
          <div className="vsummary-sub">needs recovery</div>
        </div>
      </div>

      {/* FILTER TABS */}
      <div className="vtabs">{tabs}</div>

      {/* TABLE */}
      <Section
        title="Invoice Records"
        count={filtered.length}
        icon={<Icon name="card" size={16} />}
        collapsible
        noPad
        style={{ marginTop: 12 }}
      >
        <Table head={['Invoice ID', 'Customer', 'Amount', 'Status', '']}>
          {slicedInvoices.length === 0 ? (
                <tr>
                  <td colSpan="5" className="vtable-empty">
                    No {filter} invoices found.
                  </td>
                </tr>
              ) : (
                slicedInvoices.map((inv, idx) => (
                  <tr key={idx}>
                    <td>
                      <span style={{ fontFamily: "'Geist Mono',monospace", fontSize: 12, opacity: 0.7 }}>
                        {inv.invoice_id || '—'}
                      </span>
                    </td>
                    <td style={{ fontWeight: 500 }}>{inv.customer || '—'}</td>
                    <td style={{ fontFamily: "'Crimson Pro',serif", fontSize: 15, fontWeight: 600 }}>
                      {fmtFull(inv.amount)}
                    </td>
                    <td>
                      <StatusPill status={inv.status} />
                    </td>
                    <td>
                      <button
                        className="vlink"
                        onClick={() =>
                          sendChip(`Invoice ${inv.invoice_id} for ${inv.customer}: status and amount`)
                        }
                      >
                        Ask AI
                      </button>
                    </td>
                  </tr>
                ))
              )}
        </Table>
      </Section>

      {/* PAGINATION CONTROLS */}
      {totalPages > 1 && (
        <div className="db-pagination" style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 12, marginTop: 16, marginBottom: 12, flexShrink: 0 }}>
          <button
            className="matte-glass"
            style={{ padding: '6px 12px', cursor: 'pointer', borderRadius: 6, fontSize: 12, border: '1px solid var(--border-color)', background: 'var(--card-color)', color: 'var(--text-color)' }}
            onClick={() => setPage(page - 1)}
            disabled={page === 1}
          >
            ← Previous
          </button>
          <span style={{ fontSize: '12.5px', color: 'var(--secondary-text)', fontWeight: 600 }}>
            Page {page} / {totalPages}
          </span>
          <button
            className="matte-glass"
            style={{ padding: '6px 12px', cursor: 'pointer', borderRadius: 6, fontSize: 12, border: '1px solid var(--border-color)', background: 'var(--card-color)', color: 'var(--text-color)' }}
            onClick={() => setPage(page + 1)}
            disabled={page >= totalPages}
          >
            Next →
          </button>
        </div>
      )}
    </>
  )
}
