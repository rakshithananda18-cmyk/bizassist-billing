import React from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { logger } from '../utils/logger'
import { backupOverdue } from '../utils/backupReminder'
import { BellIcon, CheckIcon, CloseIcon } from './Icons'

/**
 * NotificationBell — one place that answers "is anything wrong right now".
 *
 * The findings come from GET /alerts/notifications, which reads the same rows
 * the scheduled email jobs read. Those jobs have always computed overdue
 * invoices, low stock and expiring batches, then handed them to a mailer that
 * discards everything when SMTP is unconfigured — which is the default. So the
 * app knew and had no way to say.
 *
 * Deliberately NOT a read/unread inbox. Every item here is a live condition, not
 * an event: stock is low until it is restocked, an invoice is overdue until it
 * is paid. There is nothing to mark as read — the item leaves when the situation
 * does. That also means no per-item state to store, sync or reconcile across
 * devices, which is the entire cost of the inbox model avoided.
 *
 * ponytail: polls on open plus a slow background tick. A push would need an
 * event for every write that could change stock or invoice state — most of the
 * application. Upgrade path if the delay ever matters: the `sync-event` stream
 * already fires on those writes, so debounce a refetch off it.
 */

const SEVERITY = {
  danger:  { dot: 'var(--danger, #ef4444)',  tint: 'rgba(239,68,68,0.10)',  edge: 'rgba(239,68,68,0.30)' },
  warning: { dot: 'var(--warning, #f59e0b)', tint: 'rgba(245,158,11,0.10)', edge: 'rgba(245,158,11,0.30)' },
  info:    { dot: 'var(--accent, #3b82f6)',  tint: 'rgba(59,130,246,0.10)', edge: 'rgba(59,130,246,0.30)' },
}

const POLL_MS = 5 * 60 * 1000

export default function NotificationBell() {
  const { authFetch, settings } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = React.useState(false)
  const [data, setData] = React.useState({ items: [], count: 0, severity: null })
  const [loading, setLoading] = React.useState(false)
  const boxRef = React.useRef(null)

  // ── The one item the SERVER cannot answer ────────────────────────────────
  // The offline backup file lands on this device's disk, so "when did you last
  // back up" is a per-device question and the timestamp lives in localStorage.
  // A server-side answer would average across devices and hide exactly the risk
  // this guards: the single machine that never backs up is the one whose disk
  // dies. Computed here and merged with the server's list.
  const backup = React.useMemo(() => {
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
      severity: 'warning',
      title: due.never ? 'No backup taken on this device' : `Backup is ${due.days} days old`,
      detail: 'Download a backup file so a dead disk cannot take the books with it.',
      route: '/settings?tab=advanced',
    }
  }, [settings])

  const load = React.useCallback(async () => {
    setLoading(true)
    try {
      const res = await authFetch('/alerts/notifications')
      if (res.ok) setData(await res.json())
    } catch (err) {
      // A failed check is not itself news — leave the last known list up rather
      // than flashing "all clear", which is the one wrong answer here.
      logger.error('[NOTIFY] could not load notifications:', err)
    } finally {
      setLoading(false)
    }
  }, [authFetch])

  React.useEffect(() => {
    load()
    const t = setInterval(load, POLL_MS)
    return () => clearInterval(t)
  }, [load])

  // Close on outside click / Escape — same affordance as the sync popover.
  React.useEffect(() => {
    if (!open) return
    const onDown = (e) => {
      if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false)
    }
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  // Merged, then re-sorted — the bell's colour has to follow the most urgent
  // item overall, not whichever source it came from.
  const items = React.useMemo(() => {
    const merged = [...(data.items || []), ...(backup ? [backup] : [])]
    const order = { danger: 0, warning: 1, info: 2 }
    return merged.sort((a, b) => (order[a.severity] ?? 3) - (order[b.severity] ?? 3))
  }, [data, backup])

  const count = items.length
  const tone = SEVERITY[items[0]?.severity] || SEVERITY.info

  return (
    <div ref={boxRef} style={{ position: 'relative' }}>
      <button
        type="button"
        onClick={() => { setOpen(o => !o); if (!open) load() }}
        aria-label={count ? `${count} notification${count === 1 ? '' : 's'}` : 'Notifications'}
        aria-expanded={open}
        title={count ? `${count} thing${count === 1 ? '' : 's'} need attention` : 'Nothing needs attention'}
        style={{
          position: 'relative', display: 'inline-flex', alignItems: 'center',
          justifyContent: 'center', width: 34, height: 34, borderRadius: 8,
          background: count ? tone.tint : 'transparent',
          border: `1px solid ${count ? tone.edge : 'var(--border)'}`,
          color: count ? tone.dot : 'var(--text-secondary)',
          cursor: 'pointer',
        }}
      >
        <BellIcon size={16} />
        {count > 0 && (
          <span style={{
            position: 'absolute', top: -5, right: -5, minWidth: 16, height: 16,
            padding: '0 4px', borderRadius: 999, background: tone.dot, color: '#fff',
            fontSize: '0.62rem', fontWeight: 800, lineHeight: '16px', textAlign: 'center',
            fontVariantNumeric: 'tabular-nums',
          }}>{count > 9 ? '9+' : count}</span>
        )}
      </button>

      {open && (
        <div style={{
          position: 'absolute', top: 42, right: 0, zIndex: 1200, width: 320,
          maxHeight: '70vh', overflowY: 'auto',
          background: 'var(--bg-2, #1a1a1a)', border: '1px solid var(--border)',
          borderRadius: 12, boxShadow: '0 18px 48px rgba(0,0,0,0.45)', padding: 12,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
            <strong style={{ fontSize: '0.85rem', color: 'var(--text-primary)' }}>Needs attention</strong>
            <button type="button" onClick={() => setOpen(false)} aria-label="Close"
              style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', display: 'flex' }}>
              <CloseIcon size={14} />
            </button>
          </div>

          {count === 0 ? (
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8, padding: '10px 2px',
              fontSize: '0.78rem', color: 'var(--text-muted)',
            }}>
              <CheckIcon size={14} strokeWidth={2} style={{ color: 'var(--success, #22c55e)' }} />
              {loading ? 'Checking…' : 'Nothing needs attention.'}
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {items.map(item => {
                const t = SEVERITY[item.severity] || SEVERITY.info
                return (
                  <button
                    key={item.kind}
                    type="button"
                    onClick={() => { setOpen(false); if (item.route) navigate(item.route) }}
                    style={{
                      textAlign: 'left', width: '100%', padding: '9px 10px',
                      borderRadius: 8, background: t.tint, border: `1px solid ${t.edge}`,
                      cursor: item.route ? 'pointer' : 'default', color: 'inherit',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                      <span style={{ width: 7, height: 7, borderRadius: 999, background: t.dot, flexShrink: 0 }} />
                      <span style={{ fontSize: '0.79rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                        {item.title}
                      </span>
                    </div>
                    <div style={{ fontSize: '0.73rem', color: 'var(--text-secondary)', marginTop: 3, lineHeight: 1.4 }}>
                      {item.detail}
                    </div>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
