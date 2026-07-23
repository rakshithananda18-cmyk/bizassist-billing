// components/ActivityFeed.jsx — everything that happens in the business.
// ======================================================================
// v2 (owner feedback): less "page reading", more glanceable —
//   • grouped by day (Today / Yesterday / date headers)
//   • WHO made the change is a bold initials chip on every row
//   • compact card mode for the dashboard: recent items + one wide
//     "View full Business Activity" button that opens the complete feed
//     (category chips, pagination, detail diffs) in a full-screen modal.
// Reads GET /activity (audit trail → human summaries + what-changed diffs).
import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { useAuth } from '../contexts/AuthContext'
import { logger } from '../utils/logger'

const CATEGORY_META = {
  all:       { label: 'All',       color: 'var(--accent)' },
  billing:   { label: 'Billing',   color: '#f97316' },
  stock:     { label: 'Stock',     color: '#22c55e' },
  payments:  { label: 'Payments',  color: '#3b82f6' },
  purchases: { label: 'Purchases', color: '#a855f7' },
  shifts:    { label: 'Shifts',    color: '#eab308' },
  settings:  { label: 'Settings',  color: '#ef4444' },
  contacts:  { label: 'Contacts',  color: '#14b8a6' },
  b2b:       { label: 'B2B',       color: '#6366f1' },
  books:     { label: 'Books',     color: '#8b5cf6' },
  ai:        { label: 'AI',        color: '#ec4899' },
}

const IST = 'Asia/Kolkata'
const toDate = (iso) => new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z')
const timeOnly = (iso) => iso ? toDate(iso).toLocaleTimeString('en-IN', { timeZone: IST, hour: '2-digit', minute: '2-digit', hour12: true }) : '—'

function dayLabel(iso) {
  if (!iso) return 'Unknown'
  const d = toDate(iso)
  const key = d.toLocaleDateString('en-CA', { timeZone: IST })
  const today = new Date().toLocaleDateString('en-CA', { timeZone: IST })
  const yesterday = new Date(Date.now() - 86400000).toLocaleDateString('en-CA', { timeZone: IST })
  if (key === today) return 'Today'
  if (key === yesterday) return 'Yesterday'
  return d.toLocaleDateString('en-IN', { timeZone: IST, weekday: 'short', day: '2-digit', month: 'short' })
}

function ActorChip({ name }) {
  const n = name || 'system'
  const initials = n.slice(0, 2).toUpperCase()
  return (
    <span title={`Changed by ${n}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, flexShrink: 0 }}>
      <span style={{
        width: 20, height: 20, borderRadius: '50%', flexShrink: 0,
        background: 'var(--accent)', color: '#fff', fontSize: '0.58rem', fontWeight: 800,
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      }}>{initials}</span>
      <span style={{ fontSize: '0.7rem', fontWeight: 700, color: 'var(--text-primary)', maxWidth: 90, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {n}
      </span>
    </span>
  )
}

function DetailModal({ item, onClose }) {
  if (!item) return null
  const changed = item.changes && Object.keys(item.changes).length > 0
  const values = item.new_values || item.old_values || {}
  return (
    <div className="modal-overlay" style={{ zIndex: 3400 }} onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 560, width: '95%', maxHeight: '84vh', overflowY: 'auto' }}>
        <div style={{ padding: '18px 22px' }}>
          <h3 style={{ margin: 0, fontSize: '1rem' }}>{item.summary}</h3>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6, flexWrap: 'wrap' }}>
            <ActorChip name={item.by_username} />
            <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
              {dayLabel(item.at)} · {timeOnly(item.at)} · {item.label} {item.action.toLowerCase()}
              {item.record_id ? ` · record #${item.record_id}` : ''}
            </span>
          </div>

          {changed ? (
            <>
              <div style={{ fontSize: '0.72rem', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-muted)', margin: '14px 0 6px' }}>
                What changed
              </div>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' }}>
                <thead>
                  <tr style={{ textAlign: 'left', borderBottom: '1px solid var(--border)' }}>
                    <th style={{ padding: '4px 6px 4px 0' }}>Field</th>
                    <th style={{ padding: '4px 6px' }}>Before</th>
                    <th style={{ padding: '4px 0 4px 6px' }}>After</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(item.changes).map(([k, v]) => (
                    <tr key={k} style={{ borderBottom: '1px dashed var(--border)' }}>
                      <td style={{ padding: '5px 6px 5px 0', fontWeight: 600, verticalAlign: 'top' }}>{k}</td>
                      <td style={{ padding: '5px 6px', color: '#ef4444', wordBreak: 'break-word', verticalAlign: 'top' }}>
                        {v.from === null || v.from === undefined ? '—' : String(v.from).slice(0, 300)}
                      </td>
                      <td style={{ padding: '5px 0 5px 6px', color: '#22c55e', wordBreak: 'break-word', verticalAlign: 'top' }}>
                        {v.to === null || v.to === undefined ? '—' : String(v.to).slice(0, 300)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : (
            <>
              <div style={{ fontSize: '0.72rem', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-muted)', margin: '14px 0 6px' }}>
                Record details
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '4px 14px', fontSize: '0.78rem' }}>
                {Object.entries(values).slice(0, 24).map(([k, v]) => (
                  <React.Fragment key={k}>
                    <span style={{ fontWeight: 600, color: 'var(--text-muted)' }}>{k}</span>
                    <span style={{ wordBreak: 'break-word' }}>{v === null || v === undefined ? '—' : String(v).slice(0, 200)}</span>
                  </React.Fragment>
                ))}
              </div>
            </>
          )}

          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 16 }}>
            <button className="btn btn-secondary" onClick={onClose}>Close</button>
          </div>
        </div>
      </div>
    </div>
  )
}

function Row({ it, onOpen }) {
  const meta = CATEGORY_META[it.category] || CATEGORY_META.all
  return (
    <button
      onClick={() => onOpen(it)}
      style={{
        display: 'flex', alignItems: 'center', gap: 10, width: '100%',
        padding: '7px 6px', border: 'none', borderBottom: '1px dashed var(--border)',
        background: 'transparent', cursor: 'pointer', textAlign: 'left',
      }}
      onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-3, rgba(0,0,0,0.03))' }}
      onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
    >
      <span style={{ flexShrink: 0, width: 8, height: 8, borderRadius: '50%', background: meta.color }} title={meta.label} />
      <span style={{ flexShrink: 0, fontSize: '0.68rem', color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums', width: 62 }}>
        {timeOnly(it.at)}
      </span>
      <span style={{ flex: 1, minWidth: 0, fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
        {it.summary}
      </span>
      <ActorChip name={it.by_username} />
    </button>
  )
}

/** Full feed — chips, day groups, pagination, detail modal. */
function FullFeed({ pageSize = 40 }) {
  const { authFetch } = useAuth()
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [category, setCategory] = useState('all')
  const [loading, setLoading] = useState(true)
  const [detail, setDetail] = useState(null)
  const [offset, setOffset] = useState(0)

  const load = useCallback(async (cat, off, append = false) => {
    setLoading(true)
    try {
      const qs = new URLSearchParams({ limit: String(pageSize), offset: String(off) })
      if (cat !== 'all') qs.set('category', cat)
      const res = await authFetch(`/activity?${qs}`)
      if (res.ok) {
        const data = await res.json()
        setItems(prev => (append ? [...prev, ...data.items] : data.items))
        setTotal(data.total)
      }
    } catch (err) {
      logger.warn('[ACTIVITY] load failed', err)
    } finally {
      setLoading(false)
    }
  }, [authFetch, pageSize])

  useEffect(() => { setOffset(0); load(category, 0) }, [category, load])

  const grouped = useMemo(() => {
    const groups = []
    let current = null
    for (const it of items) {
      const label = dayLabel(it.at)
      if (!current || current.label !== label) {
        current = { label, items: [] }
        groups.push(current)
      }
      current.items.push(it)
    }
    return groups
  }, [items])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, minHeight: 0, flex: 1 }}>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {Object.entries(CATEGORY_META).map(([key, meta]) => (
          <button key={key} onClick={() => setCategory(key)}
            style={{
              padding: '3px 11px', borderRadius: 999, fontSize: '0.72rem', fontWeight: 700,
              cursor: 'pointer', transition: 'all 0.15s',
              border: `1px solid ${category === key ? meta.color : 'var(--border)'}`,
              background: category === key ? `${meta.color}22` : 'transparent',
              color: category === key ? meta.color : 'var(--text-muted)',
            }}>
            {meta.label}
          </button>
        ))}
        <span style={{ marginLeft: 'auto', fontSize: '0.7rem', color: 'var(--text-muted)', alignSelf: 'center' }}>{total} events</span>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
        {loading && items.length === 0 ? (
          <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.8rem' }}>Loading activity…</div>
        ) : items.length === 0 ? (
          <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.8rem' }}>No activity in this category yet.</div>
        ) : grouped.map(g => (
          <div key={g.label}>
            <div style={{
              position: 'sticky', top: 0, zIndex: 1,
              fontSize: '0.66rem', fontWeight: 800, textTransform: 'uppercase',
              letterSpacing: '0.08em', color: 'var(--text-muted)',
              padding: '8px 6px 4px', background: 'var(--bg-1, var(--card, inherit))',
              borderBottom: '1px solid var(--border)',
            }}>{g.label}</div>
            {g.items.map(it => <Row key={it.id} it={it} onOpen={setDetail} />)}
          </div>
        ))}

        {items.length < total && (
          <div style={{ textAlign: 'center', padding: 10 }}>
            <button className="btn btn-secondary btn-sm" disabled={loading}
              onClick={() => { const next = offset + pageSize; setOffset(next); load(category, next, true) }}>
              {loading ? 'Loading…' : `Load more (${total - items.length} older)`}
            </button>
          </div>
        )}
      </div>

      <DetailModal item={detail} onClose={() => setDetail(null)} />
    </div>
  )
}

/**
 * Default export.
 *   compact=false → the full feed inline (chips, groups, pagination).
 *   compact=true  → dashboard card: recent few + wide "View full" button
 *                   opening the full feed in a full-screen modal.
 */
export default function ActivityFeed({ compact = false, recentCount = 6 }) {
  const { authFetch } = useAuth()
  const [recent, setRecent] = useState(null)
  const [detail, setDetail] = useState(null)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    if (!compact) return
    let cancelled = false
    authFetch(`/activity?limit=${recentCount}`)
      .then(r => (r && r.ok ? r.json() : null))
      .then(d => { if (!cancelled && d) setRecent(d) })
      .catch(err => logger.warn('[ACTIVITY] recent load failed', err))
    return () => { cancelled = true }
  }, [compact, recentCount, authFetch, expanded])

  if (!compact) {
    return (
      <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div>
          <div style={{ fontWeight: 700, color: 'var(--text-primary)' }}>Business Activity</div>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
            Every action across the app — click a row for the before/after detail.
          </div>
        </div>
        <FullFeed />
      </div>
    )
  }

  return (
    <>
      <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ fontWeight: 700, color: 'var(--text-primary)' }}>Business Activity</div>
          <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>{recent?.total ?? '…'} events</span>
        </div>

        <div>
          {recent == null ? (
            <div style={{ padding: 14, textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.78rem' }}>Loading…</div>
          ) : recent.items.length === 0 ? (
            <div style={{ padding: 14, textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.78rem' }}>No activity yet.</div>
          ) : recent.items.map(it => <Row key={it.id} it={it} onOpen={setDetail} />)}
        </div>

        <button
          onClick={() => setExpanded(true)}
          className="btn btn-secondary"
          style={{ width: '100%', fontWeight: 700, justifyContent: 'center' }}
        >
          View full Business Activity →
        </button>
      </div>

      <DetailModal item={detail} onClose={() => setDetail(null)} />

      {expanded && createPortal(
        <div className="modal-overlay" style={{ zIndex: 3300 }} onClick={e => e.target === e.currentTarget && setExpanded(false)}>
          <div className="modal" style={{ maxWidth: 860, width: '96%', height: '86vh', display: 'flex', flexDirection: 'column' }}>
            <div style={{ padding: '16px 22px', display: 'flex', flexDirection: 'column', gap: 10, flex: 1, minHeight: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ fontWeight: 800, fontSize: '1.02rem' }}>Business Activity</div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                    Everything, by everyone — grouped by day, click any row for the before/after.
                  </div>
                </div>
                <button className="btn btn-ghost btn-icon" onClick={() => setExpanded(false)} aria-label="Close" style={{ fontSize: 20 }}>×</button>
              </div>
              <FullFeed />
            </div>
          </div>
        </div>,
        document.body,
      )}
    </>
  )
}
