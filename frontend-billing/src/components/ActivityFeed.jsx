// ============================================================================
// ActivityFeed.jsx — Revamped Business Activity & Audit Log for Settings
// Master-detail aligned, real-time audit trail with filtering, diffs, and search.
// ============================================================================
import React, { useState, useEffect, useCallback, useMemo, useRef, useId } from 'react'
import { createPortal } from 'react-dom'
import { useAuth } from '../contexts/AuthContext'
import { logger } from '../utils/logger'
import { CloseIcon, SearchIcon, SyncIcon } from './Icons'

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
}

const IST = 'Asia/Kolkata'
const toDate = (iso) => new Date(iso?.endsWith('Z') || iso?.includes('+') ? iso : (iso || '') + 'Z')
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
    <span title={`Changed by ${n}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
      <span style={{
        width: 22, height: 22, borderRadius: '50%', flexShrink: 0,
        background: 'var(--accent-solid, var(--accent))', color: 'var(--accent-foreground, #fff)', fontSize: '0.62rem', fontWeight: 800,
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      }}>{initials}</span>
      <span style={{ fontSize: '0.74rem', fontWeight: 600, color: 'var(--text-primary)', maxWidth: 100, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {n}
      </span>
    </span>
  )
}

function DetailModal({ item, onClose }) {
  const dialogRef = useRef(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  const titleId = useId()
  useEffect(() => {
    if (!item) return
    const previousFocus = document.activeElement
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    dialogRef.current?.querySelector('button')?.focus()
    return () => {
      document.body.style.overflow = previousOverflow
      if (previousFocus?.isConnected) previousFocus.focus?.()
    }
  }, [item?.id])
  const handleKey = event => {
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      closeRef.current?.()
    } else if (event.key === 'Tab') {
      const controls = dialogRef.current?.querySelectorAll('button:not([disabled]), a[href], [tabindex="0"]') || []
      const first = controls[0], last = controls[controls.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }
  }
  if (!item) return null
  const changed = item.changes && Object.keys(item.changes).length > 0
  const values = item.new_values || item.old_values || {}
  return createPortal(
    <div className="modal-overlay" style={{ zIndex: 3400 }} onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
        ref={dialogRef} onKeyDown={handleKey} style={{ maxWidth: 580, width: '95%', maxHeight: '86vh', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '18px 22px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
          <div>
            <h3 id={titleId} style={{ margin: 0, fontSize: '1.02rem', fontWeight: 700, color: 'var(--text-primary)' }}>{item.summary}</h3>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6, flexWrap: 'wrap' }}>
              <ActorChip name={item.by_username} />
              <span style={{ fontSize: '0.74rem', color: 'var(--text-muted)' }}>
                {dayLabel(item.at)} · {timeOnly(item.at)} · {item.category || item.label} {item.action?.toLowerCase()}
                {item.record_id ? ` · record #${item.record_id}` : ''}
              </span>
            </div>
          </div>
          <button type="button" className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close" style={{ padding: 4 }}>
            <CloseIcon size={16} />
          </button>
        </div>

        <div style={{ padding: '18px 22px', overflowY: 'auto', flex: 1 }}>
          {changed ? (
            <>
              <div style={{ fontSize: '0.72rem', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-muted)', marginBottom: 8 }}>
                What changed (Field Diffs)
              </div>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' }}>
                <thead>
                  <tr style={{ textAlign: 'left', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)' }}>
                    <th style={{ padding: '6px 8px 6px 0', fontWeight: 700 }}>Field</th>
                    <th style={{ padding: '6px 8px', fontWeight: 700 }}>Before</th>
                    <th style={{ padding: '6px 0 6px 8px', fontWeight: 700 }}>After</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(item.changes).map(([k, v]) => (
                    <tr key={k} style={{ borderBottom: '1px dashed var(--border)' }}>
                      <td style={{ padding: '7px 8px 7px 0', fontWeight: 600, verticalAlign: 'top', color: 'var(--text-primary)' }}>{k}</td>
                      <td style={{ padding: '7px 8px', color: 'var(--danger)', wordBreak: 'break-word', verticalAlign: 'top', background: 'var(--danger-dim)', borderRadius: 4 }}>
                        {v.from === null || v.from === undefined ? '—' : String(v.from).slice(0, 300)}
                      </td>
                      <td style={{ padding: '7px 0 7px 8px', color: 'var(--success)', wordBreak: 'break-word', verticalAlign: 'top', background: 'var(--success-dim)', borderRadius: 4 }}>
                        {v.to === null || v.to === undefined ? '—' : String(v.to).slice(0, 300)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : (
            <>
              <div style={{ fontSize: '0.72rem', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-muted)', marginBottom: 8 }}>
                Record Details
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '6px 16px', fontSize: '0.78rem' }}>
                {Object.entries(values).slice(0, 32).map(([k, v]) => (
                  <React.Fragment key={k}>
                    <span style={{ fontWeight: 600, color: 'var(--text-muted)' }}>{k}</span>
                    <span style={{ wordBreak: 'break-word', color: 'var(--text-primary)' }}>{v === null || v === undefined ? '—' : String(v).slice(0, 200)}</span>
                  </React.Fragment>
                ))}
              </div>
            </>
          )}
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', padding: '14px 22px', borderTop: '1px solid var(--border)', background: 'var(--bg-2)' }}>
          <button type="button" className="btn btn-secondary btn-sm" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>, document.body,
  )
}

export default function ActivityFeed() {
  const { authFetch } = useAuth()
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [category, setCategory] = useState('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [detail, setDetail] = useState(null)
  const [offset, setOffset] = useState(0)
  const pageSize = 50
  const requestRef = useRef(0)
  const abortRef = useRef(null)

  const load = useCallback(async (cat, off, append = false) => {
    const requestId = ++requestRef.current
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setLoading(true)
    setError(null)
    if (!append) { setOffset(0); setItems([]); setTotal(0); setDetail(null) }
    try {
      const qs = new URLSearchParams({ limit: String(pageSize), offset: String(off) })
      if (cat !== 'all') qs.set('category', cat)
      const res = await authFetch(`/activity?${qs}`, { signal: controller.signal })
      if (!res.ok) throw new Error('Activity request failed')
      const data = await res.json()
      if (!Array.isArray(data.items)) throw new Error('Invalid activity response')
      if (requestId !== requestRef.current || controller.signal.aborted) return
      setItems(prev => (append ? [...prev, ...data.items] : data.items))
      setTotal(Number.isFinite(data.total) ? data.total : data.items.length)
      // Advance only after a successful page. Refresh starts again from zero.
      setOffset(off)
    } catch (err) {
      if (requestId !== requestRef.current || controller.signal.aborted) return
      logger.warn('[ACTIVITY] load failed', err)
      setError('Could not load business activity. Refresh the feed to try again.')
    } finally {
      if (requestId === requestRef.current) setLoading(false)
    }
  }, [authFetch, pageSize])

  useEffect(() => {
    load(category, 0)
    return () => { ++requestRef.current; abortRef.current?.abort() }
  }, [category, load])

  const filteredItems = useMemo(() => {
    if (!searchQuery.trim()) return items
    const q = searchQuery.trim().toLowerCase()
    return items.filter(it =>
      (it.summary && it.summary.toLowerCase().includes(q)) ||
      (it.by_username && it.by_username.toLowerCase().includes(q)) ||
      (it.category && it.category.toLowerCase().includes(q)) ||
      (it.action && it.action.toLowerCase().includes(q))
    )
  }, [items, searchQuery])

  const grouped = useMemo(() => {
    const groups = []
    let current = null
    for (const it of filteredItems) {
      const label = dayLabel(it.at)
      if (!current || current.label !== label) {
        current = { label, items: [] }
        groups.push(current)
      }
      current.items.push(it)
    }
    return groups
  }, [filteredItems])

  return (
    <div className="activity-section" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Header Banner */}
      <div className="card" style={{ padding: '18px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <h2 style={{ fontSize: '1.08rem', fontWeight: 700, margin: 0, color: 'var(--text-primary)' }}>
              Business Activity &amp; Audit Log
            </h2>
            <span className="badge badge-accent" style={{ fontSize: '0.72rem', fontWeight: 700 }}>
              {total} events
            </span>
          </div>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', margin: '4px 0 0' }}>
            Chronological audit trail of all transactions, stock updates, settings adjustments, and user actions.
          </p>
        </div>

        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={() => load(category, 0)}
          disabled={loading}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 6, height: 32 }}
          title="Reload activity log"
        >
          <SyncIcon size={13} className={loading ? 'spin' : ''} />
          <span>{loading ? 'Refreshing…' : 'Refresh Feed'}</span>
        </button>
      </div>

      {/* Filter and Search Bar */}
      <div className="card" style={{ padding: '14px 18px', display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
          {/* Category Chips */}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {Object.entries(CATEGORY_META).map(([key, meta]) => {
              const isActive = category === key
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => setCategory(key)}
                  style={{
                    padding: '4px 12px',
                    borderRadius: 20,
                    fontSize: '0.74rem',
                    fontWeight: 600,
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                    border: `1px solid ${isActive ? 'var(--page-selection-border, var(--accent))' : 'var(--border)'}`,
                    background: isActive ? 'var(--page-selection-bg, var(--accent-dim))' : 'var(--bg-2)',
                    color: isActive ? 'var(--page-selection-text, var(--accent))' : 'var(--text-secondary)',
                  }}
                  aria-pressed={isActive}
                >
                  {meta.label}
                </button>
              )
            })}
          </div>

          {/* Search box */}
          <div style={{ position: 'relative', width: 220 }}>
            <SearchIcon size={14} style={{ position: 'absolute', left: 9, top: 10, color: 'var(--text-muted)', pointerEvents: 'none' }} />
            <input
              type="text"
              className="form-input"
              placeholder="Search loaded events or user…"
              aria-label="Search loaded activity events"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              style={{ paddingLeft: 28, height: 32, fontSize: '0.8rem', width: '100%' }}
            />
          </div>
        </div>
        {searchQuery.trim() && <p style={{ margin: 0, fontSize: '0.76rem', color: 'var(--text-muted)' }}>
          Searching {items.length} loaded events out of {total}. Load older events below to include them.
        </p>}
      </div>

      {/* Audit Log Timeline Card */}
      <div className="card" style={{ padding: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {error && <div role="alert" style={{ padding: 18, color: 'var(--danger)' }}>{error}</div>}
        {loading && items.length === 0 ? (
          <div style={{ padding: 36, textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.84rem' }}>
            <span className="spinner" style={{ width: 16, height: 16, marginRight: 8, verticalAlign: 'middle' }} />
            Loading business activity log…
          </div>
        ) : !error && filteredItems.length === 0 ? (
          <div style={{ padding: 36, textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.84rem' }}>
            No activity events found {category !== 'all' ? `in ${category}` : ''}{searchQuery ? ` matching "${searchQuery}"` : ''}.
          </div>
        ) : (
          <div>
            {grouped.map(g => (
              <div key={g.label}>
                <div style={{
                  position: 'sticky',
                  top: 0,
                  zIndex: 2,
                  fontSize: '0.68rem',
                  fontWeight: 800,
                  textTransform: 'uppercase',
                  letterSpacing: '0.08em',
                  color: 'var(--text-muted)',
                  padding: '10px 18px',
                  background: 'var(--bg-2)',
                  borderBottom: '1px solid var(--border)',
                  borderTop: '1px solid var(--border)',
                }}>
                  {g.label} · <span style={{ fontWeight: 600 }}>{g.items.length} records</span>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column' }}>
                  {g.items.map(it => {
                    const meta = CATEGORY_META[it.category] || CATEGORY_META.all
                    return (
                      <button
                        key={it.id}
                        type="button"
                        aria-label={`View activity: ${it.summary}`}
                        onClick={() => setDetail(it)}
                        style={{
                          display: 'flex',
                          width: '100%', border: 'none', background: 'transparent', textAlign: 'left',
                          alignItems: 'center',
                          gap: 12,
                          padding: '10px 18px',
                          borderBottom: '1px solid var(--border)',
                          cursor: 'pointer',
                          transition: 'background 0.15s ease',
                        }}
                        onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-2)' }}
                        onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
                        title="Click to view full event changes and diff"
                      >
                        <span
                          style={{
                            width: 9,
                            height: 9,
                            borderRadius: '50%',
                            background: meta.color,
                            flexShrink: 0,
                          }}
                          title={meta.label}
                        />

                        <span style={{ fontSize: '0.74rem', color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums', width: 68, flexShrink: 0 }}>
                          {timeOnly(it.at)}
                        </span>

                        <span style={{
                          flex: 1,
                          minWidth: 0,
                          fontSize: '0.82rem',
                          fontWeight: 600,
                          color: 'var(--text-primary)',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}>
                          {it.summary}
                        </span>

                        <span
                          style={{
                            fontSize: '0.68rem',
                            fontWeight: 600,
                            color: 'var(--text-secondary)',
                            background: `color-mix(in srgb, ${meta.color} 10%, transparent)`,
                            padding: '2px 8px',
                            borderRadius: 6,
                            textTransform: 'capitalize',
                            flexShrink: 0,
                          }}
                        >
                          {it.category || 'general'}
                        </span>

                        <ActorChip name={it.by_username} />
                      </button>
                    )
                  })}
                </div>
              </div>
            ))}

          </div>
        )}
        {offset + pageSize < total && (
          <div style={{ textAlign: 'center', padding: '16px' }}>
            <button type="button" className="btn btn-secondary btn-sm" disabled={loading}
              onClick={() => load(category, offset + pageSize, true)}>
              {loading ? 'Loading…' : `Load more events (${Math.max(0, total - items.length)} remaining)`}
            </button>
          </div>
        )}
      </div>

      <DetailModal item={detail} onClose={() => setDetail(null)} />
    </div>
  )
}
