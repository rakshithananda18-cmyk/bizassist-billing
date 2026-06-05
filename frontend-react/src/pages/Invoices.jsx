import { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { API_BASE } from '../config'

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

  function sendChip(query) {
    sessionStorage.setItem('prefill_query', query)
    // Dispatch a custom event to notify AppLayout to change view and input query
    window.dispatchEvent(new CustomEvent('ai-shortcut', { detail: { query } }))
  }

  if (loading) {
    return (
      <>
        <div className="vheader" style={{ marginBottom: 16 }}>
          <div>
            <div className="vheader-title">Invoices</div>
            <div className="vheader-sub">All billing records</div>
          </div>
        </div>
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
        <div className="vempty-icon">📋</div>
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
      <div className="vheader">
        <div>
          <div className="vheader-title">
            Invoices <span className="vbadge">{all.length}</span>
          </div>
          <div className="vheader-sub">{all.length} total · {fmtAmount(totalAmount)} revenue</div>
        </div>
      </div>

      {/* FILTER TABS */}
      <div className="vtabs">{tabs}</div>

      {/* TABLE */}
      <div className="widget" style={{ padding: 0, overflow: 'hidden', marginTop: 12 }}>
        <div className="vtable-wrap">
          <table>
            <thead>
              <tr>
                <th>Invoice ID</th>
                <th>Customer</th>
                <th>Amount</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
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
            </tbody>
          </table>
        </div>
      </div>

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

      {/* SUMMARY STRIP — below table+pagination, matching legacy */}
      <div className="vsummary-strip">
        <div className="vsummary-item" onClick={() => sendChip('List all paid invoices')}>
          <div className="vsummary-val" style={{ color: '#27864a' }}>{paidCount}</div>
          <div className="vsummary-key">Paid</div>
        </div>
        <div className="vsummary-item" onClick={() => sendChip('List all pending invoices')}>
          <div className="vsummary-val" style={{ color: '#b06510' }}>{pendingCount}</div>
          <div className="vsummary-key">Pending</div>
        </div>
        <div className="vsummary-item" onClick={() => sendChip('List all overdue invoices with amounts')}>
          <div className="vsummary-val" style={{ color: '#c02a2a' }}>{overdueCount}</div>
          <div className="vsummary-key">Overdue</div>
        </div>
        <div className="vsummary-item" onClick={() => sendChip('What is my total revenue?')}>
          <div className="vsummary-val">{fmtAmount(totalAmount)}</div>
          <div className="vsummary-key">Total</div>
        </div>
      </div>

    </>
  )
}
