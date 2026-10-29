import React, { useState, useEffect, useRef, useLayoutEffect, useMemo, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { logger } from '../utils/logger'
import { backupOverdue } from '../utils/backupReminder'
import { HALT_COPY } from '../utils/syncHalt'
import { trialState, trialReminders } from '../utils/trialStatus'
import { IS_LOCAL_APP } from '../config'
import { DESKTOP_DOWNLOAD_URL } from '../config/downloadApp'
import { BellIcon, CheckIcon, CloseIcon, WhatsAppOutlineIcon, AlertIcon } from './Icons'

/**
 * Smart Notification Bell — unified across Billing, Field Team, and Admin.
 *
 * Answers "what needs attention, right now" with distinct color-coding:
 *   - Urgent / Danger (Red): Stockouts, expired batches, sync halts.
 *   - Reminder / Warning (Amber): Invoices overdue, backup reminders, trial countdown.
 *   - Customer Offers (Purple): Active promos with 1-click WhatsApp dispatch.
 *   - Field Team (Sky Blue): Store requests, delivery runs, overdue field tasks.
 *   - Updates (Emerald): What's New v1.2.5 changelog and release notices.
 *
 * Categorized tabs: All | Billing | Field | Offers & Updates.
 */

const SEVERITY = {
  danger:  { dot: 'var(--danger, #ef4444)',  tint: 'rgba(239,68,68,0.08)',  edge: 'rgba(239,68,68,0.25)', label: 'Urgent' },
  warning: { dot: 'var(--warning, #f59e0b)', tint: 'rgba(245,158,11,0.08)', edge: 'rgba(245,158,11,0.25)', label: 'Reminder' },
  offer:   { dot: '#8b5cf6',                 tint: 'rgba(139,92,246,0.08)', edge: 'rgba(139,92,246,0.25)', label: 'Offer' },
  field:   { dot: '#0ea5e9',                 tint: 'rgba(14,165,233,0.08)', edge: 'rgba(14,165,233,0.25)', label: 'Field' },
  update:  { dot: '#10b981',                 tint: 'rgba(16,185,129,0.08)', edge: 'rgba(16,185,129,0.25)', label: 'Update' },
  info:    { dot: 'var(--accent, #3b82f6)',  tint: 'rgba(59,130,246,0.08)', edge: 'rgba(59,130,246,0.25)', label: 'Info' },
}

const CATEGORY_TABS = [
  { id: 'all',     label: 'All' },
  { id: 'billing', label: 'Billing' },
  { id: 'field',   label: 'Field' },
  { id: 'offers',  label: 'Offers & Updates' },
]

const POLL_MS = 5 * 60 * 1000

export default function NotificationBell({ placement = 'bottom-end', onOpen }) {
  const { authFetch, settings, user } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [data, setData] = useState({ items: [], count: 0, severity: null })
  const [activeTab, setActiveTab] = useState('all')
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState(false)
  const [checked, setChecked] = useState(false)
  const requestRef = useRef(0)
  const boxRef = useRef(null)
  const popoverRef = useRef(null)
  const [popoverPosition, setPopoverPosition] = useState({})

  // Modals for Offer WhatsApp dispatch and What's New
  const [offerModalData, setOfferModalData] = useState(null)
  const [showChangelog, setShowChangelog] = useState(false)
  const [customerPhone, setCustomerPhone] = useState('')

  // Positioning
  useLayoutEffect(() => {
    if (!open) return undefined
    const position = () => {
      if (!boxRef.current || !popoverRef.current) return
      const zoom = parseFloat(getComputedStyle(document.documentElement).zoom) || 1
      const rect = boxRef.current.getBoundingClientRect()
      const viewportWidth = window.innerWidth / zoom
      const viewportHeight = window.innerHeight / zoom
      const width = Math.min(360, viewportWidth - 24)
      const height = popoverRef.current.getBoundingClientRect().height / zoom
      const sidebar = placement === 'sidebar' ? boxRef.current.closest('.sidebar') : null
      const desiredLeft = placement === 'sidebar'
        ? (sidebar ? sidebar.getBoundingClientRect().right / zoom + 8 : rect.right / zoom + 12)
        : rect.right / zoom - width
      const left = Math.max(12, Math.min(desiredLeft, viewportWidth - width - 12))
      const desiredTop = placement === 'sidebar' ? rect.bottom / zoom - height : rect.bottom / zoom + 8
      const top = Math.max(12, Math.min(desiredTop, viewportHeight - height - 12))
      const maxHeight = viewportHeight - 24
      setPopoverPosition(previous =>
        previous.left === left && previous.top === top && previous.width === width && previous.maxHeight === maxHeight
          ? previous
          : { left, top, width, maxHeight }
      )
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

  // Offline backup reminder
  const backup = useMemo(() => {
    let lastBackupIso = null
    try { lastBackupIso = localStorage.getItem('bizassist_last_file_backup') } catch { /* ignore */ }
    const g = settings?.general || {}
    const due = backupOverdue({
      autoBackup: g.auto_backup === true,
      reminderDays: g.backup_reminder_days,
      lastBackupIso,
    })
    if (!due) return null
    return {
      kind: 'backup',
      category: 'billing',
      severity: 'warning',
      title: due.never ? 'No backup taken on this device' : `Backup is ${due.days} days old`,
      detail: 'Download a backup file so a dead disk cannot take the books with it.',
      route: '/settings?tab=advanced',
    }
  }, [settings])

  // Sync halt detection
  const [haltReason, setHaltReason] = useState(null)

  const load = useCallback(async () => {
    const request = ++requestRef.current
    setLoading(true)
    setLoadError(false)
    try {
      const res = await authFetch('/alerts/notifications')
      if (!res.ok) throw new Error(`Notifications unavailable: HTTP ${res.status}`)
      const next = await res.json()
      if (!next || !Array.isArray(next.items)) throw new Error('Notifications response was invalid')
      if (request === requestRef.current) {
        setData(next)
        setChecked(true)
      }
    } catch (err) {
      if (request !== requestRef.current) return
      setLoadError(true)
      logger.error('[NOTIFY] could not load notifications:', err)
    } finally {
      if (request === requestRef.current) setLoading(false)
    }
    try {
      const r = await authFetch('/api/sync/queue-depth')
      if (r.ok) {
        const next = (await r.json())?.halt?.reason || null
        if (request === requestRef.current) setHaltReason(next)
      }
    } catch {
      /* ignore */
    }
  }, [authFetch, user?.id])

  useEffect(() => {
    setData({ items: [], count: 0, severity: null })
    setHaltReason(null)
    setChecked(false)
    load()
    const t = setInterval(load, POLL_MS)
    return () => { requestRef.current++; clearInterval(t) }
  }, [load])

  // Outside click / Escape handler
  useEffect(() => {
    if (!open) return
    const onDown = (e) => {
      if (!boxRef.current?.contains(e.target) && !popoverRef.current?.contains(e.target)) {
        setOpen(false)
      }
    }
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const halt = useMemo(() => {
    const copy = haltReason ? HALT_COPY[haltReason] : null
    if (!copy) return null
    return {
      kind: `halt:${haltReason}`,
      category: 'billing',
      severity: copy.severity,
      title: copy.title,
      detail: copy.detail,
      route: '/settings?tab=advanced',
    }
  }, [haltReason])

  // Signup Pro trial
  const trial = useMemo(() => {
    if ((user?.role || '').toLowerCase() === 'cashier') return []
    const rems = trialReminders(trialState(settings?.subscription), {
      isLocalApp: IS_LOCAL_APP,
      downloadUrl: DESKTOP_DOWNLOAD_URL,
    })
    return (rems || []).map(r => ({ ...r, category: 'billing' }))
  }, [settings, user])

  // Full merged list
  const allItems = useMemo(() => {
    const merged = [
      ...(data.items || []),
      ...(halt ? [halt] : []),
      ...(backup ? [backup] : []),
      ...trial,
    ]
    const order = { danger: 0, warning: 1, offer: 2, update: 3, info: 4 }
    return merged.sort((a, b) => (order[a.severity] ?? 5) - (order[b.severity] ?? 5))
  }, [data, halt, backup, trial])

  const count = allItems.length

  // Filtered by active tab
  const filteredItems = useMemo(() => {
    if (activeTab === 'all') return allItems
    if (activeTab === 'billing') return allItems.filter(i => (i.category || 'billing') === 'billing')
    if (activeTab === 'field') return allItems.filter(i => i.category === 'field')
    if (activeTab === 'offers') return allItems.filter(i => i.category === 'offers' || i.category === 'updates')
    return allItems
  }, [allItems, activeTab])

  // Category counts
  const tabCounts = useMemo(() => ({
    all: count,
    billing: allItems.filter(i => (i.category || 'billing') === 'billing').length,
    field: allItems.filter(i => i.category === 'field').length,
    offers: allItems.filter(i => i.category === 'offers' || i.category === 'updates').length,
  }), [allItems, count])

  // Bell tone (urgent danger beats reminder amber beats info)
  const tone = useMemo(() => {
    const mostUrgent = allItems.find(i => i.severity === 'danger')
      || allItems.find(i => i.severity === 'warning')
      || allItems[0]
    return SEVERITY[mostUrgent?.severity] || SEVERITY.info
  }, [allItems])

  const handleSendWhatsApp = (offer) => {
    const phone = customerPhone.trim().replace(/\s+/g, '').replace(/-/g, '')
    const cleanPhone = phone.startsWith('+') ? phone.slice(1) : phone.length === 10 ? `91${phone}` : phone
    const msg = `Exclusive Offer from ${offer.business_name || 'Our Store'}! ${offer.title}: ${offer.discount_text || ''}. Valid till ${offer.valid_until || 'soon'}. Reply to claim!`
    const url = `https://api.whatsapp.com/send?phone=${cleanPhone}&text=${encodeURIComponent(msg)}`
    window.open(url, '_blank', 'noopener')
    setOfferModalData(null)
    setCustomerPhone('')
  }

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
        title={loadError ? 'Notifications could not refresh' : count ? `${count} thing${count === 1 ? '' : 's'} need attention` : checked && !loading ? 'Nothing needs attention' : 'Checking notifications'}
        style={{
          position: 'relative', display: 'inline-flex', alignItems: 'center',
          justifyContent: 'center', width: 28, height: 28, padding: 0,
          background: 'transparent', border: 'none',
          color: count ? tone.dot : (placement === 'sidebar' ? 'var(--sidebar-muted, var(--text-secondary))' : 'var(--text-secondary)'),
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
              <strong style={{ fontSize: '0.88rem', color: 'var(--text-primary)' }}>Smart Notifications</strong>
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
              Notifications couldn&apos;t refresh. The current alert status is unavailable.{' '}
              <button type="button" className="btn btn-secondary btn-sm" style={{ marginTop: 4 }} onClick={load}>
                Retry notifications
              </button>
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
                <span>{loading || !checked ? 'Checking…' : 'Nothing needs attention.'}</span>
              </div>
            )
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {filteredItems.map(item => {
                const t = SEVERITY[item.severity] || SEVERITY.info
                const isOffer = item.action === 'send_offer'
                const isRelease = item.action === 'view_release_notes'

                return (
                  <button
                    key={item.kind}
                    type="button"
                    onClick={() => {
                      if (isOffer) {
                        setOfferModalData(item.offer_data || { title: item.title, discount_text: item.detail })
                      } else if (isRelease) {
                        setShowChangelog(true)
                      } else {
                        setOpen(false)
                        if (item.href) window.open(item.href, '_blank', 'noopener')
                        else if (item.route) navigate(item.route)
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
                        background: t.dot, color: '#fff', textTransform: 'uppercase', letterSpacing: '0.04em',
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
                        {isOffer ? (
                          <>
                            <WhatsAppOutlineIcon size={13} /> Send on WhatsApp &rarr;
                          </>
                        ) : isRelease ? (
                          'What Changed &rarr;'
                        ) : (
                          'View &rarr;'
                        )}
                      </span>
                    </div>
                  </button>
                )
              })}
            </div>
          )}
        </div>, document.body
      )}

      {/* Customer WhatsApp Offer Dispatch Dialog */}
      {offerModalData && createPortal(
        <div style={{
          position: 'fixed', inset: 0, zIndex: 13000, background: 'rgba(0,0,0,0.5)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16,
        }}>
          <div style={{
            background: 'var(--bg-2, #fff)', border: '1px solid var(--border)', borderRadius: 12,
            padding: 18, width: '100%', maxWidth: 360, boxShadow: '0 24px 60px rgba(0,0,0,0.4)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#25d366' }}>
                <WhatsAppOutlineIcon size={18} />
                <strong style={{ fontSize: '0.92rem', color: 'var(--text-primary)' }}>Send Offer to Customer</strong>
              </div>
              <button type="button" onClick={() => setOfferModalData(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)' }}>
                <CloseIcon size={15} />
              </button>
            </div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: 12, lineHeight: 1.4 }}>
              <strong>{offerModalData.title}</strong>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem', marginTop: 2 }}>
                {offerModalData.discount_text || offerModalData.description}
              </div>
            </div>
            <label style={{ display: 'block', fontSize: '0.76rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>
              Customer WhatsApp Number (10 digits):
            </label>
            <input
              type="tel"
              placeholder="e.g. 9876543210"
              value={customerPhone}
              onChange={e => setCustomerPhone(e.target.value)}
              style={{
                width: '100%', padding: '8px 10px', borderRadius: 8, border: '1px solid var(--border)',
                background: 'var(--bg-1, #f4f4f1)', fontSize: '0.84rem', color: 'var(--text-primary)', marginBottom: 14,
              }}
            />
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setOfferModalData(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-sm"
                disabled={!customerPhone.trim()}
                onClick={() => handleSendWhatsApp(offerModalData)}
                style={{ background: '#25d366', color: '#fff', border: 'none', fontWeight: 700 }}
              >
                Open WhatsApp &rarr;
              </button>
            </div>
          </div>
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
            padding: 20, width: '100%', maxWidth: 420, boxShadow: '0 24px 60px rgba(0,0,0,0.4)',
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
                  Categorized tabs for Billing, Field Team, Customer Offers, and System Updates with distinct color-coding.
                </p>
              </div>
              <div>
                <strong style={{ color: 'var(--text-primary)' }}>2. Direct Customer Offer Messaging</strong>
                <p style={{ margin: '2px 0 0', color: 'var(--text-muted)' }}>
                  Send targeted offers, festival deals, and payment reminders directly to customer WhatsApp with 1 click.
                </p>
              </div>
              <div>
                <strong style={{ color: 'var(--text-primary)' }}>3. Field Team & Store Request Sync</strong>
                <p style={{ margin: '2px 0 0', color: 'var(--text-muted)' }}>
                  Live store requirements and field route deliveries now display in the notification hub.
                </p>
              </div>
              <div>
                <strong style={{ color: 'var(--text-primary)' }}>4. High-Resilience Cloud Sync</strong>
                <p style={{ margin: '2px 0 0', color: 'var(--text-muted)' }}>
                  Auto-healing for deferred parent records and zero-leak shutdown protection.
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
