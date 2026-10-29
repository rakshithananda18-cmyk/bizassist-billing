import React, { useState, useEffect, useRef, useLayoutEffect, useMemo, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import { BellIcon, CheckIcon, CloseIcon, AlertIcon } from './Icons'

/**
 * Smart Notification Bell — Field Team App.
 *
 * Unified with Billing and Admin:
 *   - Urgent / Danger (Red): Overdue tasks, halts.
 *   - Reminder / Warning (Amber): Pending route check-ins, reminders.
 *   - Field Team (Sky Blue): New shop requirements, stock requests.
 *   - Offers (Purple): Customer deals.
 *   - Updates (Emerald): What's New v1.2.5 changelog.
 */

const SEVERITY = {
  danger:  { dot: 'var(--danger, #ef4444)',  tint: 'rgba(239,68,68,0.08)',  edge: 'rgba(239,68,68,0.25)', label: 'Urgent' },
  warning: { dot: 'var(--warning, #f59e0b)', tint: 'rgba(245,158,11,0.08)', edge: 'rgba(245,158,11,0.25)', label: 'Reminder' },
  field:   { dot: '#0ea5e9',                 tint: 'rgba(14,165,233,0.08)', edge: 'rgba(14,165,233,0.25)', label: 'Field' },
  offer:   { dot: '#8b5cf6',                 tint: 'rgba(139,92,246,0.08)', edge: 'rgba(139,92,246,0.25)', label: 'Offer' },
  update:  { dot: '#10b981',                 tint: 'rgba(16,185,129,0.08)', edge: 'rgba(16,185,129,0.25)', label: 'Update' },
  info:    { dot: 'var(--accent, #3b82f6)',  tint: 'rgba(59,130,246,0.08)', edge: 'rgba(59,130,246,0.25)', label: 'Info' },
}

const CATEGORY_TABS = [
  { id: 'all',     label: 'All' },
  { id: 'field',   label: 'Field' },
  { id: 'billing', label: 'Billing' },
  { id: 'offers',  label: 'Offers & Updates' },
]

const POLL_MS = 30 * 1000 // 30s quick polling + instant refresh on tab focus

export default function NotificationBell({ placement = 'bottom-end', onOpen }) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [data, setData] = useState({ items: [], count: 0, severity: null })
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState(false)
  const [checked, setChecked] = useState(false)
  const [activeTab, setActiveTab] = useState('all')
  const [showChangelog, setShowChangelog] = useState(false)

  const requestRef = useRef(0)
  const boxRef = useRef(null)
  const popoverRef = useRef(null)
  const [popoverPosition, setPopoverPosition] = useState({})

  useLayoutEffect(() => {
    if (!open) return undefined
    const position = () => {
      if (!boxRef.current || !popoverRef.current) return
      const rect = boxRef.current.getBoundingClientRect()
      const viewportWidth = window.innerWidth
      const viewportHeight = window.innerHeight
      const width = Math.min(340, viewportWidth - 24)
      const height = popoverRef.current.getBoundingClientRect().height
      const sidebar = placement === 'sidebar' ? boxRef.current.closest('.sidebar') : null
      const desiredLeft = placement === 'sidebar'
        ? (sidebar ? sidebar.getBoundingClientRect().right + 8 : rect.right + 12)
        : rect.right - width
      const left = Math.max(12, Math.min(desiredLeft, viewportWidth - width - 12))
      const desiredTop = placement === 'sidebar' ? rect.bottom - height : rect.bottom + 8
      const top = Math.max(12, Math.min(desiredTop, viewportHeight - height - 12))
      const maxHeight = viewportHeight - 24
      setPopoverPosition(prev => prev.left === left && prev.top === top && prev.width === width && prev.maxHeight === maxHeight
        ? prev : { left, top, width, maxHeight })
    }
    position()
    window.addEventListener('resize', position)
    window.addEventListener('scroll', position, true)
    const observer = new ResizeObserver(position)
    observer.observe(popoverRef.current)
    return () => {
      window.removeEventListener('resize', position)
      window.removeEventListener('scroll', position, true)
      observer.disconnect()
    }
  }, [open, placement])

  useEffect(() => {
    if (!open) return undefined
    const onDown = (e) => {
      if (boxRef.current?.contains(e.target)) return
      if (popoverRef.current?.contains(e.target)) return
      setOpen(false)
    }
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('mousedown', onDown, true)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('mousedown', onDown, true)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])

  const load = useCallback(async () => {
    const reqId = ++requestRef.current
    setLoading(true)
    try {
      const res = await api.get('/api/notifications')
      if (reqId !== requestRef.current) return
      const items = Array.isArray(res?.items) ? res.items : []
      setData({ items, count: items.length, severity: res?.severity || null })
      setLoadError(false)
      setChecked(true)
    } catch {
      if (reqId !== requestRef.current) return
      setLoadError(true)
      setChecked(true)
    } finally {
      if (reqId === requestRef.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const timer = setInterval(load, POLL_MS)
    const handleFocus = () => { if (document.visibilityState === 'visible') load() }
    window.addEventListener('focus', handleFocus)
    document.addEventListener('visibilitychange', handleFocus)
    return () => {
      clearInterval(timer)
      window.removeEventListener('focus', handleFocus)
      document.removeEventListener('visibilitychange', handleFocus)
    }
  }, [load])

  const allItems = useMemo(() => {
    const items = data.items || []
    const order = { danger: 0, warning: 1, field: 2, offer: 3, update: 4, info: 5 }
    return [...items].sort((a, b) => (order[a.severity] ?? 6) - (order[b.severity] ?? 6))
  }, [data])

  const count = allItems.length

  const filteredItems = useMemo(() => {
    if (activeTab === 'all') return allItems
    if (activeTab === 'field') return allItems.filter(i => (i.category || 'field') === 'field')
    if (activeTab === 'billing') return allItems.filter(i => i.category === 'billing')
    if (activeTab === 'offers') return allItems.filter(i => i.category === 'offers' || i.category === 'updates')
    return allItems
  }, [allItems, activeTab])

  const tabCounts = useMemo(() => ({
    all: count,
    field: allItems.filter(i => (i.category || 'field') === 'field').length,
    billing: allItems.filter(i => i.category === 'billing').length,
    offers: allItems.filter(i => i.category === 'offers' || i.category === 'updates').length,
  }), [allItems, count])

  const tone = useMemo(() => {
    const mostUrgent = allItems.find(i => i.severity === 'danger')
      || allItems.find(i => i.severity === 'warning')
      || allItems.find(i => i.severity === 'field')
      || allItems[0]
    return SEVERITY[mostUrgent?.severity] || SEVERITY.info
  }, [allItems])

  return (
    <div ref={boxRef} style={{ position: 'relative', display: 'inline-flex', flexShrink: 0 }}>
      <button
        type="button"
        onClick={() => {
          setOpen(o => !o)
          if (!open) { onOpen?.(); load() }
        }}
        aria-label={count ? `${count} notification${count === 1 ? '' : 's'}` : 'Notifications'}
        aria-expanded={open}
        title={loadError ? 'Notifications could not refresh' : count ? `${count} item${count === 1 ? '' : 's'} need attention` : 'Field notifications'}
        style={{
          position: 'relative', display: 'inline-flex', alignItems: 'center',
          justifyContent: 'center', width: 28, height: 28, padding: 0,
          background: 'transparent', border: 'none',
          color: count ? tone.dot : 'var(--text-secondary, #888)',
          cursor: 'pointer',
        }}
      >
        <BellIcon size={16} />
        {count > 0 && (
          <span style={{
            position: 'absolute', top: -2, right: -2, minWidth: 14, height: 14,
            padding: '0 4px', borderRadius: 999, background: tone.dot, color: '#fff',
            fontSize: '0.58rem', fontWeight: 800, lineHeight: '14px', textAlign: 'center',
            fontVariantNumeric: 'tabular-nums', boxShadow: '0 1px 3px rgba(0,0,0,0.25)',
          }}>
            {count > 9 ? '9+' : count}
          </span>
        )}
      </button>

      {open && createPortal(
        <div ref={popoverRef} role="dialog" aria-label="Smart notifications" style={{
          position: 'fixed', zIndex: 12000, ...popoverPosition,
          overflowY: 'auto',
          background: 'var(--bg-2, #ffffff)', border: '1px solid var(--border)',
          borderRadius: 14, boxShadow: '0 20px 50px rgba(0,0,0,0.3)', padding: 14,
          fontFamily: 'inherit',
        }}>
          {/* Header */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ width: 8, height: 8, borderRadius: 999, background: tone.dot }} />
              <strong style={{ fontSize: '0.88rem', color: 'var(--text-primary)' }}>Field Notifications</strong>
            </div>
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close"
              style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', display: 'flex', padding: 4 }}
            >
              <CloseIcon size={14} />
            </button>
          </div>

          {/* Category Filter Tabs */}
          <div style={{
            display: 'flex', gap: 4, background: 'var(--bg-1, rgba(255,255,255,0.06))',
            padding: 3, borderRadius: 8, marginBottom: 12, overflowX: 'auto',
          }}>
            {CATEGORY_TABS.map(tab => {
              const active = activeTab === tab.id
              const tabCount = tabCounts[tab.id] || 0
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setActiveTab(tab.id)}
                  style={{
                    flex: 1, padding: '4px 6px', fontSize: '0.72rem', fontWeight: active ? 700 : 500,
                    borderRadius: 6, border: 'none', cursor: 'pointer',
                    background: active ? 'var(--bg-2, #fff)' : 'transparent',
                    color: active ? 'var(--text-primary)' : 'var(--text-muted)',
                    boxShadow: active ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
                    whiteSpace: 'nowrap', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4,
                  }}
                >
                  <span>{tab.label}</span>
                  {tabCount > 0 && (
                    <span style={{
                      fontSize: '0.62rem', padding: '1px 5px', borderRadius: 999,
                      background: active ? 'var(--accent, #3b82f6)' : 'rgba(128,128,128,0.2)',
                      color: active ? '#fff' : 'inherit',
                    }}>
                      ({tabCount})
                    </span>
                  )}
                </button>
              )
            })}
          </div>

          {/* Load error message */}
          {loadError && (
            <div role="status" style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: 10, background: 'rgba(239,68,68,0.08)', padding: 8, borderRadius: 8 }}>
              Could not refresh notifications.
            </div>
          )}

          {/* Empty state */}
          {filteredItems.length === 0 ? (
            loadError ? null : (
              <div style={{
                display: 'flex', alignItems: 'center', gap: 8, padding: '16px 8px',
                fontSize: '0.8rem', color: 'var(--text-muted)', justifyContent: 'center',
              }}>
                {checked && !loading && <CheckIcon size={16} strokeWidth={2} style={{ color: 'var(--success, #22c55e)' }} />}
                <span>{loading || !checked ? 'Checking…' : 'All clear. No pending items.'}</span>
              </div>
            )
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {filteredItems.map(item => {
                const t = SEVERITY[item.severity] || SEVERITY.info
                const isRelease = item.action === 'view_release_notes'

                return (
                  <button
                    key={item.kind}
                    type="button"
                    onClick={() => {
                      if (isRelease) {
                        setShowChangelog(true)
                      } else {
                        setOpen(false)
                        if (item.route) navigate(item.route)
                      }
                    }}
                    style={{
                      textAlign: 'left', width: '100%', padding: '10px 12px', borderRadius: 10,
                      background: t.tint, border: `1px solid ${t.edge}`,
                      cursor: 'pointer', color: 'inherit',
                      display: 'flex', flexDirection: 'column', gap: 4,
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 7, flex: 1 }}>
                        <span style={{ width: 8, height: 8, borderRadius: 999, background: t.dot, flexShrink: 0 }} />
                        <span style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                          {item.title}
                        </span>
                      </div>
                      <span style={{
                        fontSize: '0.64rem', fontWeight: 700, padding: '2px 6px', borderRadius: 99,
                        background: t.dot, color: '#fff', textTransform: 'uppercase', letterSpacing: '0.04em'
                      }}>
                        {t.label}
                      </span>
                    </div>

                    <div style={{ fontSize: '0.74rem', color: 'var(--text-secondary)', lineHeight: 1.45, marginTop: 2 }}>
                      {item.detail}
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
                      <span style={{
                        color: t.dot, fontSize: '0.74rem', fontWeight: 700,
                        display: 'inline-flex', alignItems: 'center', gap: 4,
                      }}>
                        {isRelease ? "What's New →" : 'View →'}
                      </span>
                    </div>
                  </button>
                )
              })}
            </div>
          )}
        </div>, document.body
      )}

      {/* What's New Release Modal */}
      {showChangelog && createPortal(
        <div style={{
          position: 'fixed', inset: 0, zIndex: 13000, background: 'rgba(0,0,0,0.5)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16,
        }}>
          <div style={{
            background: 'var(--bg-2, #fff)', border: '1px solid var(--border)', borderRadius: 14,
            padding: 20, width: '100%', maxWidth: 400, boxShadow: '0 24px 60px rgba(0,0,0,0.4)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
              <strong style={{ fontSize: '0.96rem', color: 'var(--text-primary)' }}>What&apos;s New in v1.2.5</strong>
              <button type="button" onClick={() => setShowChangelog(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)' }}>
                <CloseIcon size={16} />
              </button>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: '0.78rem', color: 'var(--text-secondary)', lineHeight: 1.5, marginBottom: 16 }}>
              <div>
                <strong style={{ color: 'var(--text-primary)' }}>1. Unified Smart Notifications</strong>
                <p style={{ margin: '2px 0 0', color: 'var(--text-muted)' }}>
                  Categorized tabs for Field Team requests, Billing alerts, Customer Offers, and System Updates.
                </p>
              </div>
              <div>
                <strong style={{ color: 'var(--text-primary)' }}>2. Store Order & Requirement Alerts</strong>
                <p style={{ margin: '2px 0 0', color: 'var(--text-muted)' }}>
                  Live notifications whenever a shop places a requirement or order in the field.
                </p>
              </div>
            </div>
            <button
              type="button"
              className="btn btn-primary"
              style={{ width: '100%', fontSize: '0.84rem' }}
              onClick={() => setShowChangelog(false)}
            >
              Got it
            </button>
          </div>
        </div>, document.body
      )}
    </div>
  )
}
