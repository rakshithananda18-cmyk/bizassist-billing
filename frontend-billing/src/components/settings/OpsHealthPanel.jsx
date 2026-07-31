// ============================================================================
// OpsHealthPanel — owner-facing data-health view (Settings → Ops & Health).
//
// Surfaces the backend observability endpoints that have no other UI:
//   GET  /reports/ops-health              → sync backlog, integrity, AI usage
//   GET  /api/sync/conflicts              → unreviewed financial sync conflicts
//   POST /api/sync/conflicts/:id/resolve  → clear one after reviewing both sides
//   GET  /api/sync/outbox/details         → local rows not yet delivered UP
//   POST /api/sync/outbox/:id/retry       → re-attempt one, and run the sync
//   GET  /api/sync/inbox/details          → cloud rows not yet applied DOWN
//   POST /api/sync/inbox/:id/retry        → re-attempt one, and run the pull
//
// BOTH DIRECTIONS, AND LIVE — the two things this panel used to lack.
//
// Only the outbox was ever shown, so a device could report a clean, empty queue
// while rows the cloud had sent sat un-applied and invisible. That asymmetry is
// how deferred pull rows were dropped for months without anyone noticing, and
// the Sync Inbox card is the half that was missing.
//
// It also loaded exactly once. The queues it reports drain on BACKEND timers —
// a 15 s sync tick, per-row inbox backoff — none of which the frontend hears
// about, so the numbers froze at whatever was true when Settings was opened. A
// console whose whole job is live queue depth cannot be a snapshot. It now
// refreshes on sync activity, on a 10 s poll while visible, and on returning to
// the tab; the badge in the header states which and how old the data is, and can
// be paused so rows hold still while they are being read.
//
// Fails soft: any fetch error shows a muted note, never blocks Settings.
// ============================================================================
import React, { useEffect, useState, useCallback, useRef } from 'react'
import { CheckIcon, AlertIcon, SyncIcon } from '../Icons'
import { useForegroundRefresh } from '../../hooks/useForegroundRefresh'
// The shared empty/loading primitives (plan Phase 4.2). Adopted here 2026-07-31:
// they existed, were tested, styled in index.css — and nothing rendered them, so
// every card in this panel had its own ad-hoc "no data" div and its own
// "Checking…" line. That is the drift these components were built to prevent.
import EmptyState from '../common/EmptyState'
import { SkeletonTable } from '../common/Skeleton'

// How often the panel re-reads itself while it is on screen. The outbox drains
// and the inbox retries on BACKEND timers — a 15 s sync tick and a per-row
// backoff — and neither emits anything the frontend hears. Without a poll the
// console showed whatever was true the moment it mounted and then quietly went
// stale, which for a page whose entire job is reporting live queue depth is the
// same failure as showing nothing.
const POLL_MS = 10000

// `sync-event` fires per entity during a push or pull, so a single invoice with
// eight line items produces a burst. Coalesce them into one refresh.
const EVENT_DEBOUNCE_MS = 800

/** "just now" / "12s ago" / "3m ago". Re-rendered by <LiveDot>'s own ticker, so
 *  the age stays truthful between refreshes instead of freezing at the value it
 *  had when the last fetch landed. */
function agoLabel(ts) {
  if (!ts) return '—'
  const s = Math.max(0, Math.round((Date.now() - ts) / 1000))
  if (s < 5) return 'just now'
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  return `${Math.floor(m / 60)}h ago`
}

/** The live badge: a state, its age, and a switch to turn it off.
 *
 *  All three matter. A number with no age cannot be trusted; a live view with no
 *  off switch cannot be read while it changes underneath you — which is exactly
 *  what happens when an owner is trying to copy an error message out of a row
 *  that keeps being replaced.
 */
function LiveDot({ live, refreshing, lastUpdated, onToggle }) {
  const [, force] = useState(0)
  // Own ticker: `lastUpdated` only changes on a fetch, so without this the label
  // would read "just now" indefinitely on an idle panel.
  useEffect(() => {
    const t = setInterval(() => force(n => n + 1), 5000)
    return () => clearInterval(t)
  }, [])

  const color = !live ? 'var(--text-muted)'
    : refreshing ? 'var(--warning, #f59e0b)'
    : '#22c55e'

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: '0.72rem', color: 'var(--text-muted)' }}>
      <span
        aria-hidden="true"
        style={{
          width: 7, height: 7, borderRadius: '50%', background: color, flexShrink: 0,
          boxShadow: live && !refreshing ? '0 0 0 3px rgba(34,197,94,0.18)' : 'none',
          transition: 'background 180ms ease, box-shadow 180ms ease',
        }}
      />
      <span>
        {live ? (refreshing ? 'Updating…' : 'Live') : 'Paused'}
        {' · '}
        {agoLabel(lastUpdated)}
      </span>
      <button
        className="btn btn-ghost"
        style={{ fontSize: '0.68rem', padding: '1px 6px' }}
        onClick={onToggle}
        title={live
          ? 'Stop auto-refreshing so rows hold still while you read them'
          : 'Resume auto-refresh'}
        aria-pressed={live}
      >
        {live ? 'Pause' : 'Resume'}
      </button>
    </span>
  )
}

function Stat({ label, value, tone }) {
  const color = tone === 'bad' ? 'var(--danger, #ef4444)'
    : tone === 'warn' ? 'var(--warning, #f59e0b)'
    : 'var(--text-primary)'
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 120 }}>
      <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{label}</span>
      <span style={{ fontSize: '1rem', fontWeight: 700, color }}>{value}</span>
    </div>
  )
}

export default function OpsHealthPanel({ authFetch }) {
  const [health, setHealth] = useState(null)
  const [conflicts, setConflicts] = useState([])
  const [outboxItems, setOutboxItems] = useState([])
  const [outboxError, setOutboxError] = useState(false)
  const [outboxPage, setOutboxPage] = useState(1)
  // Inbox = rows the CLOUD sent that this device could not apply. Until this
  // existed the console showed only half the picture: a device could report a
  // clean, empty outbox while pulled rows sat un-applied and invisible — which
  // is precisely how deferred rows were dropped for so long without anyone
  // noticing.
  const [inboxItems, setInboxItems] = useState([])
  const [inboxStats, setInboxStats] = useState(null)
  const [inboxError, setInboxError] = useState(false)
  const [inboxPage, setInboxPage] = useState(1)
  const [conflictsPage, setConflictsPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [actionMsg, setActionMsg] = useState(null)
  const [healing, setHealing] = useState(false)
  // Live-refresh state. `lastUpdated` is what makes the panel honest: a number
  // on screen is only meaningful if the reader can tell how old it is.
  const [lastUpdated, setLastUpdated] = useState(null)
  const [refreshing, setRefreshing] = useState(false)
  const [live, setLive] = useState(true)
  const PAGE_SIZE = 10

  // Guards against overlapping loads. A slow backend plus a 10 s poll plus a
  // burst of sync events would otherwise stack requests, and the LAST one to
  // return would win regardless of which was newest — a classic out-of-order
  // render where the panel settles on stale data.
  const inFlightRef = useRef(false)
  const reqSeqRef = useRef(0)
  const debounceRef = useRef(null)
  const liveRef = useRef(live)
  useEffect(() => { liveRef.current = live }, [live])

  /**
   * @param {object}  [opts]
   * @param {boolean} [opts.silent] Background refresh: do NOT flip `loading`.
   *   The first load may blank the panel and show a spinner; a poll must not,
   *   or the console would flash empty every 10 seconds and be unreadable.
   */
  const load = useCallback(async (opts = {}) => {
    const silent = !!opts.silent
    if (inFlightRef.current) return          // never stack
    inFlightRef.current = true
    const seq = ++reqSeqRef.current
    const isCurrent = () => seq === reqSeqRef.current

    if (silent) setRefreshing(true)
    else setLoading(true)
    setError(false)
    try {
      const [hRes, cRes] = await Promise.all([
        authFetch('/reports/ops-health'),
        authFetch('/api/sync/conflicts'),
      ])
      // `isCurrent()` on every write: a response from a superseded request must
      // not overwrite a newer one's data.
      if (hRes.ok && isCurrent()) setHealth(await hRes.json())
      if (cRes.ok && isCurrent()) setConflicts((await cRes.json()).conflicts || [])

      // Outbox details go through authFetch like every other call here.
      // This previously used a raw fetch() with getApiBase()/getToken(), which
      // bypassed authFetch's base-URL mapping and 401 handling — on a LAN/hybrid
      // setup it could hit the wrong origin, fail silently, and leave the whole
      // Sync Outbox card unrendered with no explanation.
      try {
        const oRes = await authFetch('/api/sync/outbox/details')
        if (oRes.ok) {
          const data = await oRes.json()
          if (isCurrent()) { setOutboxItems(data.items || []); setOutboxError(false) }
        } else if (isCurrent()) {
          setOutboxError(true)
        }
      } catch {
        if (isCurrent()) setOutboxError(true)
      }

      // Inbox details, fetched separately for the same reason the outbox is:
      // one card failing must not blank the rest of the console.
      try {
        const iRes = await authFetch('/api/sync/inbox/details')
        if (iRes.ok) {
          const data = await iRes.json()
          if (isCurrent()) {
            setInboxItems(data.items || [])
            setInboxStats(data.stats || null)
            setInboxError(false)
          }
        } else if (isCurrent()) {
          setInboxError(true)
        }
      } catch {
        if (isCurrent()) setInboxError(true)
      }
      if (isCurrent()) setLastUpdated(Date.now())
    } catch {
      if (isCurrent()) setError(true)
    } finally {
      inFlightRef.current = false
      if (silent) setRefreshing(false)
      else setLoading(false)
    }
  }, [authFetch])

  useEffect(() => { load() }, [load])

  // ── LIVE: poll while visible ────────────────────────────────────────────────
  // Paused when the tab is hidden. A background tab polling every 10 s costs the
  // backend real queries for a panel nobody is looking at, and on a hybrid setup
  // those queries land on the owner's own local machine.
  useEffect(() => {
    if (!live) return
    let timer = null
    const tick = () => {
      if (document.visibilityState === 'visible' && liveRef.current) {
        load({ silent: true })
      }
    }
    timer = setInterval(tick, POLL_MS)
    const onVisible = () => {
      // Returning to the tab: refresh at once rather than waiting out the
      // remainder of an interval that elapsed while hidden.
      if (document.visibilityState === 'visible') tick()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [live, load])

  // ── LIVE: react to sync activity immediately ────────────────────────────────
  // The poll is the floor, not the mechanism. When a push or pull actually
  // happens the queue depth changes NOW, and waiting up to 10 s to show it makes
  // the Retry buttons feel broken.
  //
  // Unlike the pages that filter `sync-event` by entity, this panel wants ALL of
  // them: any synced row changes an outbox or inbox count.
  useEffect(() => {
    const onSyncActivity = () => {
      if (!liveRef.current) return
      if (debounceRef.current) clearTimeout(debounceRef.current)
      debounceRef.current = setTimeout(() => load({ silent: true }), EVENT_DEBOUNCE_MS)
    }
    window.addEventListener('sync-event', onSyncActivity)
    window.addEventListener('sync-flushed', onSyncActivity)
    window.addEventListener('sync-status-change', onSyncActivity)
    return () => {
      window.removeEventListener('sync-event', onSyncActivity)
      window.removeEventListener('sync-flushed', onSyncActivity)
      window.removeEventListener('sync-status-change', onSyncActivity)
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [load])

  // Returning after a long absence. Respects the pause: "Paused" has to mean
  // the rows hold still, or the one moment the reader most needs them to — while
  // they tab away to copy an error into a ticket — is exactly when they move.
  // A paused panel is not misleading, because the age label next to the badge
  // keeps counting up and says how stale it is.
  useForegroundRefresh({
    onResume: () => { if (liveRef.current) load({ silent: true }) },
    staleMs: 15000,
  })

  // Keep pagination inside the data. A background refresh can shrink a list
  // (rows drained) while the reader is on page 4 — without this the card renders
  // an empty page with working Previous buttons, which reads as data loss.
  useEffect(() => {
    const max = Math.max(1, Math.ceil(outboxItems.length / PAGE_SIZE))
    setOutboxPage(p => Math.min(p, max))
  }, [outboxItems.length])
  useEffect(() => {
    const max = Math.max(1, Math.ceil(inboxItems.length / PAGE_SIZE))
    setInboxPage(p => Math.min(p, max))
  }, [inboxItems.length])
  useEffect(() => {
    const max = Math.max(1, Math.ceil(conflicts.length / PAGE_SIZE))
    setConflictsPage(p => Math.min(p, max))
  }, [conflicts.length])

  const resolveConflict = async (id) => {
    try {
      const r = await authFetch(`/api/sync/conflicts/${id}/resolve`, { method: 'POST' })
      if (r.ok) {
        setConflicts(prev => prev.filter(c => c.id !== id))
        load()
      }
    } catch { /* ignore — row stays until next refresh */ }
  }

  const retryOutboxRow = async (id) => {
    try {
      const r = await authFetch(`/api/sync/outbox/${id}/retry`, { method: 'POST' })
      if (r.ok) {
        setActionMsg(`Outbox item #${id} re-queued — sync run started.`)
        // The retry schedules a background sync run, so the row's state changes
        // a moment after the response. Refresh twice: once now for the cleared
        // error, once after the run has had time to land.
        load()
        setTimeout(() => load({ silent: true }), 2500)
      } else {
        setActionMsg(`Failed to retry outbox item #${id}.`)
      }
    } catch {
      setActionMsg(`Failed to retry outbox item #${id}.`)
    }
  }

  const retryInboxRow = async (id) => {
    try {
      const r = await authFetch(`/api/sync/inbox/${id}/retry`, { method: 'POST' })
      if (r.ok) {
        setActionMsg(`Held row #${id} re-queued — pull run started.`)
        // Same two-stage refresh as the outbox: the retry schedules a background
        // run, so the row's state changes a moment after the response returns.
        load()
        setTimeout(() => load({ silent: true }), 2500)
      } else {
        setActionMsg(`Failed to retry held row #${id}.`)
      }
    } catch {
      setActionMsg(`Failed to retry held row #${id}.`)
    }
  }

  const runMasterSelfHealing = async () => {
    setHealing(true)
    try {
      setActionMsg('Running System Auto-Repair & Self-Healing…')
      const r = await authFetch('/reports/integrity/self-heal', { method: 'POST' })
      if (r && r.ok) {
        const res = await r.json()
        const acct = res.hash_chain_healed || 0
        // Count what was actually REPAIRED, not what was detected.
        // drift_detected_count is a diagnostic counter; inventory_rows_fixed is
        // the repair counter, and missing_inventory_rows_created was being
        // omitted entirely, so real repairs went unreported.
        const st = res.stock_summary || {}
        const stock = (st.inventory_rows_fixed || 0)
          + (st.missing_inventory_rows_created || 0)
          + (st.import_ledger_entries_created || 0)
        const sy = res.sync_summary || {}
        const syncRes = (sy.payloads_patched || 0)
          + (sy.errors_reset || 0)
          + (sy.corrupt_repaired || 0)
          + (sy.redundant_children_cleared || 0)
        const total = acct + stock + syncRes
        setActionMsg(total === 0
          ? 'Auto-Repair complete — no problems found, nothing needed repairing.'
          : `Auto-Repair complete. Repaired ${acct} hash signature(s), ${stock} stock ledger item(s), ${syncRes} sync queue item(s).`)
        load()
      } else {
        setActionMsg('Auto-Repair encountered a temporary error.')
      }
    } catch (e) {
      setActionMsg(`Auto-Repair notification: ${e.message || 'Complete'}`)
    } finally {
      setHealing(false)
    }
  }

  if (loading) {
    // A shaped placeholder rather than a line of text: this panel loads four
    // endpoints and lands as three cards, so a skeleton tells the reader what is
    // arriving instead of making them guess whether anything is.
    return (
      <div style={{ padding: '4px 0' }} aria-busy="true">
        <SkeletonTable rows={4} cols={3} testId="ops-health-loading" />
      </div>
    )
  }
  if (error || !health) {
    return <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', padding: '8px 0' }}>Data health unavailable right now. <button className="btn btn-ghost" style={{ fontSize: '0.78rem', padding: '2px 8px' }} onClick={() => load()}>Retry</button></div>
  }

  const sync = health.sync || {}
  const integrity = health.integrity || {}
  const ai = health.ai_usage || {}
  const inboxPending = inboxStats?.pending_count ?? inboxItems.length
  const inboxStuck = inboxStats?.stuck_count ?? 0

  // `health.ok` is computed server-side from the OUTBOX, integrity and AI usage
  // — it predates the inbox and knows nothing about it. Reporting "All systems
  // healthy" while rows the cloud sent sit un-applied would be the banner
  // telling the owner the exact thing that was untrue for months.
  const ok = health.ok && inboxStuck === 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* Overall banner */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px',
        borderRadius: 'var(--radius-md)',
        background: ok ? 'rgba(34,197,94,0.10)' : 'rgba(245,158,11,0.12)',
        border: `1px solid ${ok ? 'rgba(34,197,94,0.35)' : 'rgba(245,158,11,0.4)'}`,
      }}>
        {ok ? <CheckIcon size={16} style={{ color: '#22c55e' }} /> : <AlertIcon size={16} style={{ color: '#f59e0b' }} />}
        <span style={{ fontSize: '0.86rem', fontWeight: 600, color: 'var(--text-primary)' }}>
          {ok
            ? 'All systems healthy'
            : inboxStuck > 0
              ? `${inboxStuck} row${inboxStuck === 1 ? '' : 's'} from the cloud could not be applied — see Sync Inbox below`
              : 'Attention needed — review the items below'}
        </span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <LiveDot
            live={live}
            refreshing={refreshing}
            lastUpdated={lastUpdated}
            onToggle={() => setLive(v => !v)}
          />
          <button className="btn btn-secondary" style={{ fontSize: '0.76rem', padding: '3px 9px', display: 'inline-flex', alignItems: 'center', gap: 6 }} disabled={healing} onClick={runMasterSelfHealing}>
            {healing && <span className="sync-spinner-small" />}
            {healing ? 'Healing System…' : 'Auto-Repair & Heal System'}
          </button>
          {/* Explicit refresh is NOT silent — the reader asked for it, so the
              spinner is the acknowledgement that it happened. */}
          <button className="btn btn-ghost" style={{ fontSize: '0.76rem', padding: '3px 9px', display: 'inline-flex', alignItems: 'center', gap: 5 }} onClick={() => load()}>
            <SyncIcon size={13} /> Refresh
          </button>
        </div>
      </div>

      {actionMsg && (
        <div style={{ fontSize: '0.8rem', padding: '6px 10px', background: 'var(--bg-2)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}>
          {actionMsg}
        </div>
      )}

      {/* Stats row */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 20, padding: '4px 2px' }}>
        <Stat label="Pending sync" value={sync.pending ?? 0}
              tone={(sync.failed ?? 0) > 0 ? 'bad' : (sync.pending ?? 0) > 0 ? 'warn' : 'ok'} />
        <Stat label="Sync errors" value={sync.failed ?? 0} tone={(sync.failed ?? 0) > 0 ? 'bad' : 'ok'} />
        <Stat label="Books integrity"
              value={integrity.ok === false ? 'Broken' : integrity.ok === true ? 'OK' : '—'}
              tone={integrity.ok === false ? 'bad' : 'ok'} />
        <Stat label="Journal drift" value={integrity.journal_drift ?? '—'}
              tone={integrity.journal_drift ? 'bad' : 'ok'} />
        <Stat label="AI tokens today" value={ai.tokens_today ?? '—'} />
        {/* The pull-side counterpart of "Pending sync". Its absence is why rows
            the cloud sent could sit un-applied indefinitely while the console
            reported a perfectly clean device. `stuck` is called out separately
            because those have stopped retrying and will not clear themselves. */}
        <Stat label="Held from cloud" value={inboxPending}
              tone={inboxStuck > 0 ? 'bad' : inboxPending > 0 ? 'warn' : 'ok'} />
        <Stat label="Needs attention" value={inboxStuck}
              tone={inboxStuck > 0 ? 'bad' : 'ok'} />
        <Stat label="Conflicts to review" value={conflicts.length}
              tone={conflicts.length > 0 ? 'warn' : 'ok'} />
      </div>

      {/* Outbox Details Queue (Paginated at 10 items) — ALWAYS rendered.
          Previously this whole card was behind `outboxItems.length > 0`, so an
          empty queue and a failed request both looked identical: the Sync Outbox
          section simply vanished from the page with no explanation. */}
      <div style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', overflow: 'hidden' }}>
        <div style={{ padding: '8px 12px', background: 'var(--bg-3)', fontSize: '0.78rem', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.04em', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>Sync Outbox Queue &amp; Quarantined Items ({outboxItems.length})</span>
          {outboxItems.length > PAGE_SIZE && (
            <span style={{ fontSize: '0.72rem', fontWeight: 500, color: 'var(--text-muted)' }}>
              Page {outboxPage} of {Math.ceil(outboxItems.length / PAGE_SIZE)}
            </span>
          )}
        </div>

        {outboxError && (
          <div style={{ padding: '10px 12px', borderTop: '1px solid var(--border)', fontSize: '0.8rem', color: 'var(--warning, #f59e0b)' }}>
            Couldn’t load the outbox queue. It may be unavailable in this hosting mode, or the backend is unreachable.{' '}
            <button className="btn btn-ghost" style={{ fontSize: '0.76rem', padding: '2px 8px' }} onClick={() => load()}>Retry</button>
          </div>
        )}

        {!outboxError && outboxItems.length === 0 && (
          <div style={{ borderTop: '1px solid var(--border)' }}>
            <EmptyState
              compact
              icon={<CheckIcon size={18} />}
              title="Outbox is empty"
              hint="Every local change has been delivered to the cloud."
              testId="outbox-empty"
            />
          </div>
        )}
      </div>

      {outboxItems.length > 0 && (
        <div style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', overflow: 'hidden' }}>
          <div style={{ padding: '8px 12px', background: 'var(--bg-3)', fontSize: '0.78rem', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.04em', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>Queued items detail</span>
            <span style={{ fontSize: '0.72rem', fontWeight: 500, color: 'var(--text-muted)' }}>
              Page {outboxPage} of {Math.ceil(outboxItems.length / PAGE_SIZE)}
            </span>
          </div>
          {outboxItems.slice((outboxPage - 1) * PAGE_SIZE, outboxPage * PAGE_SIZE).map(item => (
            <div key={item.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 12px', borderTop: '1px solid var(--border)' }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                  {item.entity} #{item.entity_id} ({item.operation})
                </div>
                {item.last_error && (
                  <div style={{ fontSize: '0.74rem', color: 'var(--danger, #ef4444)', marginTop: 2 }}>
                    Error: {item.last_error}
                  </div>
                )}
                <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                  Created: {item.created_at || '—'} · Status:{' '}
                  <span style={{ color: item.status === 'failed' ? 'var(--danger, #ef4444)' : 'var(--text-muted)', fontWeight: item.status === 'failed' ? 600 : 400 }}>
                    {item.status === 'failed' ? 'Failed — awaiting retry' : 'Queued'}
                  </span>
                </div>
              </div>
              <button className="btn btn-secondary" style={{ fontSize: '0.74rem', padding: '3px 10px' }} onClick={() => retryOutboxRow(item.id)}>
                Retry Item
              </button>
            </div>
          ))}
          {outboxItems.length > PAGE_SIZE && (
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 12px', background: 'var(--bg-2)', borderTop: '1px solid var(--border)' }}>
              <button className="btn btn-ghost" style={{ fontSize: '0.72rem', padding: '2px 8px', opacity: outboxPage <= 1 ? 0.4 : 1, cursor: outboxPage <= 1 ? 'not-allowed' : 'pointer' }} disabled={outboxPage <= 1} onClick={() => setOutboxPage(p => Math.max(1, p - 1))}>
                ← Previous 10
              </button>
              <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Showing {(outboxPage - 1) * PAGE_SIZE + 1}–{Math.min(outboxPage * PAGE_SIZE, outboxItems.length)} of {outboxItems.length}</span>
              <button className="btn btn-ghost" style={{ fontSize: '0.72rem', padding: '2px 8px', opacity: outboxPage >= Math.ceil(outboxItems.length / PAGE_SIZE) ? 0.4 : 1, cursor: outboxPage >= Math.ceil(outboxItems.length / PAGE_SIZE) ? 'not-allowed' : 'pointer' }} disabled={outboxPage >= Math.ceil(outboxItems.length / PAGE_SIZE)} onClick={() => setOutboxPage(p => p + 1)}>
                Next 10 →
              </button>
            </div>
          )}
        </div>
      )}

      {/* ── Sync Inbox: rows the CLOUD sent that this device could not apply ──
          The pull-side mirror of the outbox above, and it is deliberately always
          rendered for the same reason that one is: an empty inbox and a failed
          request must not look identical.

          Before this card existed the two failure modes it reports were both
          invisible. A DEFERRED row (parent not local yet) was dropped at a bare
          `continue` and counted as applied. A REJECTED row produced a CRITICAL
          log line saying it "needs a human", in a log no human was reading. */}
      <div style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', overflow: 'hidden' }}>
        <div style={{ padding: '8px 12px', background: 'var(--bg-3)', fontSize: '0.78rem', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.04em', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>Sync Inbox — rows received but not yet applied ({inboxItems.length})</span>
          {inboxItems.length > PAGE_SIZE && (
            <span style={{ fontSize: '0.72rem', fontWeight: 500, color: 'var(--text-muted)' }}>
              Page {inboxPage} of {Math.ceil(inboxItems.length / PAGE_SIZE)}
            </span>
          )}
        </div>

        {inboxError && (
          <div style={{ padding: '10px 12px', borderTop: '1px solid var(--border)', fontSize: '0.8rem', color: 'var(--warning, #f59e0b)' }}>
            Couldn’t load the sync inbox. It may be unavailable in this hosting mode, or the backend is unreachable.{' '}
            <button className="btn btn-ghost" style={{ fontSize: '0.76rem', padding: '2px 8px' }} onClick={() => load()}>Retry</button>
          </div>
        )}

        {!inboxError && inboxItems.length === 0 && (
          <div style={{ borderTop: '1px solid var(--border)' }}>
            <EmptyState
              compact
              icon={<CheckIcon size={18} />}
              title="Inbox is empty"
              hint="Every row the cloud sent has been applied here."
              testId="inbox-empty"
            />
          </div>
        )}

        {!inboxError && inboxStats && inboxItems.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, padding: '8px 12px', borderTop: '1px solid var(--border)', fontSize: '0.74rem', color: 'var(--text-muted)' }}>
            <span>Waiting on a parent: <strong style={{ color: 'var(--text-primary)' }}>{inboxStats.deferred_count ?? 0}</strong></span>
            <span>Rejected: <strong style={{ color: (inboxStats.rejected_count ?? 0) > 0 ? 'var(--danger, #ef4444)' : 'var(--text-primary)' }}>{inboxStats.rejected_count ?? 0}</strong></span>
            {/* Past the automatic retry limit. NOT deleted and NOT hidden —
                this number is the whole reason the card exists. */}
            <span>Needs attention: <strong style={{ color: (inboxStats.stuck_count ?? 0) > 0 ? 'var(--danger, #ef4444)' : 'var(--text-primary)' }}>{inboxStats.stuck_count ?? 0}</strong></span>
          </div>
        )}

        {inboxItems.slice((inboxPage - 1) * PAGE_SIZE, inboxPage * PAGE_SIZE).map(item => (
          <div key={item.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 12px', borderTop: '1px solid var(--border)' }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                {item.entity} {item.uid ? `uid ${String(item.uid).slice(0, 8)}…` : `#${item.remote_id}`}
              </div>
              {item.last_error && (
                <div style={{ fontSize: '0.74rem', color: 'var(--danger, #ef4444)', marginTop: 2 }}>
                  Error: {item.last_error}
                </div>
              )}
              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                Received: {item.created_at || '—'} · Attempts: {item.attempts} · Status:{' '}
                <span style={{ color: item.stuck ? 'var(--danger, #ef4444)' : 'var(--text-muted)', fontWeight: item.stuck ? 600 : 400 }}>
                  {item.stuck
                    ? 'Needs attention — automatic retries exhausted'
                    : item.reason === 'deferred'
                      ? 'Waiting for its parent record to arrive'
                      : 'Rejected — will retry'}
                </span>
              </div>
            </div>
            <button className="btn btn-secondary" style={{ fontSize: '0.74rem', padding: '3px 10px' }} onClick={() => retryInboxRow(item.id)}>
              Retry Item
            </button>
          </div>
        ))}

        {inboxItems.length > PAGE_SIZE && (
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 12px', background: 'var(--bg-2)', borderTop: '1px solid var(--border)' }}>
            <button className="btn btn-ghost" style={{ fontSize: '0.72rem', padding: '2px 8px', opacity: inboxPage <= 1 ? 0.4 : 1, cursor: inboxPage <= 1 ? 'not-allowed' : 'pointer' }} disabled={inboxPage <= 1} onClick={() => setInboxPage(p => Math.max(1, p - 1))}>
              ← Previous 10
            </button>
            <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Showing {(inboxPage - 1) * PAGE_SIZE + 1}–{Math.min(inboxPage * PAGE_SIZE, inboxItems.length)} of {inboxItems.length}</span>
            <button className="btn btn-ghost" style={{ fontSize: '0.72rem', padding: '2px 8px', opacity: inboxPage >= Math.ceil(inboxItems.length / PAGE_SIZE) ? 0.4 : 1, cursor: inboxPage >= Math.ceil(inboxItems.length / PAGE_SIZE) ? 'not-allowed' : 'pointer' }} disabled={inboxPage >= Math.ceil(inboxItems.length / PAGE_SIZE)} onClick={() => setInboxPage(p => p + 1)}>
              Next 10 →
            </button>
          </div>
        )}
      </div>

      {/* Conflict review list (Paginated at 10 items) */}
      {conflicts.length > 0 && (
        <div style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', overflow: 'hidden' }}>
          <div style={{ padding: '8px 12px', background: 'var(--bg-3)', fontSize: '0.78rem', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.04em', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>Financial edits synced from another device — review &amp; clear ({conflicts.length})</span>
            <span style={{ fontSize: '0.72rem', fontWeight: 500, color: 'var(--text-muted)' }}>
              Page {conflictsPage} of {Math.ceil(conflicts.length / PAGE_SIZE)}
            </span>
          </div>
          {conflicts.slice((conflictsPage - 1) * PAGE_SIZE, conflictsPage * PAGE_SIZE).map(c => (
            <div key={c.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 12px', borderTop: '1px solid var(--border)' }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: '0.84rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                  {c.entity} #{c.entity_id}
                </div>
                <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)' }}>
                  This device: {c.local_updated_at || '—'} · Cloud: {c.cloud_updated_at || '—'}
                </div>
              </div>
              <button className="btn btn-secondary" style={{ fontSize: '0.76rem', padding: '4px 12px' }} onClick={() => resolveConflict(c.id)}>
                Mark reviewed
              </button>
            </div>
          ))}
          {conflicts.length > PAGE_SIZE && (
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 12px', background: 'var(--bg-2)', borderTop: '1px solid var(--border)' }}>
              <button className="btn btn-ghost" style={{ fontSize: '0.72rem', padding: '2px 8px' }} disabled={conflictsPage <= 1} onClick={() => setConflictsPage(p => Math.max(1, p - 1))}>
                ← Previous 10
              </button>
              <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Showing {(conflictsPage - 1) * PAGE_SIZE + 1}–{Math.min(conflictsPage * PAGE_SIZE, conflicts.length)} of {conflicts.length}</span>
              <button className="btn btn-ghost" style={{ fontSize: '0.72rem', padding: '2px 8px' }} disabled={conflictsPage >= Math.ceil(conflicts.length / PAGE_SIZE)} onClick={() => setConflictsPage(p => p + 1)}>
                Next 10 →
              </button>
            </div>
          )}
          <div style={{ padding: '8px 12px', fontSize: '0.72rem', color: 'var(--text-muted)', borderTop: '1px solid var(--border)' }}>
            The most recent edit is what’s stored. Marking reviewed only clears it from this list — it doesn’t change your data.
          </div>
        </div>
      )}
    </div>
  )
}
