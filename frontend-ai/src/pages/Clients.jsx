import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { API_BASE } from '../config'
import { PageHeader } from '../components/ui'
import { Icon } from '../components/icons'

const CLIENTS_PER_PAGE = 10

function fmtAmount(n) {
  if (!n && n !== 0) return '—'
  if (n >= 100000) return '₹' + (n / 100000).toFixed(1) + 'L'
  if (n >= 1000)   return '₹' + Math.round(n / 1000) + 'k'
  return '₹' + Math.round(n)
}

export default function Clients() {
  const { authFetch } = useAuth()
  const navigate = useNavigate()
  const [clients, setClients] = useState([])
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    loadClients()
  }, [])

  async function loadClients() {
    setLoading(true)
    try {
      const res = await authFetch(`${API_BASE}/clients`)
      if (!res.ok) throw new Error('Failed to fetch clients database')
      const data = await res.json()
      setClients(data.clients || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  // intent set -> deterministic /intent (0 AI tokens); else natural-language AI query
  // params -> passed to the intent handler (e.g. { customer })
  function sendChip(query, intent, params) {
    sessionStorage.setItem('prefill_query', query)
    window.dispatchEvent(new CustomEvent('ai-shortcut', { detail: { query, intent, params, label: query } }))
  }

  if (loading) {
    return (
      <>
        <PageHeader title="Clients" subtitle="Customer overview" />
        <div className="widget">
          <div className="vskel"></div>
          <div className="vskel"></div>
          <div className="vskel"></div>
        </div>
      </>
    )
  }

  if (error || clients.length === 0) {
    return (
      <div className="vempty">
        <div className="vempty-icon"><Icon name="users" size={36} /></div>
        <div className="vempty-title">No clients yet</div>
        <div className="vempty-sub">{error || 'Upload invoices to see your client list.'}</div>
        <button
          className="chip upload-btn-highlight"
          style={{ marginTop: 14 }}
          onClick={() => navigate('/upload')}
        >
          + Upload data
        </button>
      </div>
    )
  }

  const maxTotal = clients[0]?.total || 1
  const clientSlice = clients.slice((page - 1) * CLIENTS_PER_PAGE, page * CLIENTS_PER_PAGE)
  const totalPages = Math.ceil(clients.length / CLIENTS_PER_PAGE)

  const barColors = ['#e06535', '#c97c22', '#3a9a5c', '#4a90c9', '#9b59b6', '#e91e63']

  return (
    <>
      <PageHeader
        title={<>Clients <span className="vbadge">{clients.length}</span></>}
        subtitle={`${clients.length} customers tracked`}
        style={{ marginBottom: 0 }}
      />

      {/* CLIENTS GRID */}
      <div className="vclient-grid" style={{ marginTop: 16 }}>
        {clientSlice.map((c, i) => {
          const barW = Math.round((c.total / maxTotal) * 100)
          const absoluteIdx = (page - 1) * CLIENTS_PER_PAGE + i
          const color = barColors[absoluteIdx % barColors.length]

          return (
            <div
              key={c.customer}
              className="vclient-card"
              onClick={() => sendChip(`Summary for ${c.customer}`, 'client_summary', { customer: c.customer })}
              style={{ cursor: 'pointer' }}
            >
              <div className="vclient-top">
                <div
                  className="vclient-avatar"
                  style={{ background: `${color}22`, color: color }}
                >
                  {c.customer.charAt(0).toUpperCase()}
                </div>
                <div className="vclient-info">
                  <div className="vclient-name">{c.customer}</div>
                  <div className="vclient-meta">
                    {c.invoices} invoice{c.invoices !== 1 ? 's' : ''}
                  </div>
                </div>
                <div className="vclient-amount">{fmtAmount(c.total)}</div>
              </div>
              <div className="vclient-bar-track">
                <div className="vclient-bar-fill" style={{ width: `${barW}%`, background: color }} />
              </div>
              <div className="vclient-pills">
                {c.paid > 0 && (
                  <span className="vpill" style={{ color: '#27864a', background: 'rgba(39,134,74,0.10)' }}>
                    {c.paid} paid
                  </span>
                )}
                {c.pending > 0 && (
                  <span className="vpill" style={{ color: '#b06510', background: 'rgba(176,101,16,0.10)' }}>
                    {c.pending} pending
                  </span>
                )}
                {c.overdue > 0 && (
                  <span className="vpill" style={{ color: '#c02a2a', background: 'rgba(192,42,42,0.10)' }}>
                    {c.overdue} overdue
                  </span>
                )}
                <span className="vlink" style={{ marginLeft: 'auto' }}>
                  Ask AI →
                </span>
              </div>
            </div>
          )
        })}
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
    </>
  )
}
