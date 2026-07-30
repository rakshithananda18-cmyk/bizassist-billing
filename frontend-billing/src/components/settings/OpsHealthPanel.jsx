// ============================================================================
// OpsHealthPanel — owner-facing data-health view (Settings → Advanced).
// Surfaces the backend observability endpoints that previously had no UI:
//   GET  /reports/ops-health          → sync backlog, integrity, AI usage
//   GET  /api/sync/conflicts          → unreviewed financial sync conflicts
//   POST /api/sync/conflicts/:id/resolve → clear one after reviewing both sides
// Fails soft: any fetch error shows a muted note, never blocks Settings.
// ============================================================================
import React, { useEffect, useState, useCallback } from 'react'
import { CheckIcon, AlertIcon, SyncIcon } from '../Icons'

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
  const [conflictsPage, setConflictsPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [actionMsg, setActionMsg] = useState(null)
  const [healing, setHealing] = useState(false)
  const PAGE_SIZE = 10

  const load = useCallback(async () => {
    setLoading(true); setError(false)
    try {
      const [hRes, cRes] = await Promise.all([
        authFetch('/reports/ops-health'),
        authFetch('/api/sync/conflicts'),
      ])
      if (hRes.ok) setHealth(await hRes.json())
      if (cRes.ok) setConflicts((await cRes.json()).conflicts || [])

      // Outbox details go through authFetch like every other call here.
      // This previously used a raw fetch() with getApiBase()/getToken(), which
      // bypassed authFetch's base-URL mapping and 401 handling — on a LAN/hybrid
      // setup it could hit the wrong origin, fail silently, and leave the whole
      // Sync Outbox card unrendered with no explanation.
      try {
        const oRes = await authFetch('/api/sync/outbox/details')
        if (oRes.ok) {
          const data = await oRes.json()
          setOutboxItems(data.items || [])
          setOutboxError(false)
        } else {
          setOutboxError(true)
        }
      } catch {
        setOutboxError(true)
      }
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [authFetch])

  useEffect(() => { load() }, [load])

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
        setTimeout(load, 2500)
      } else {
        setActionMsg(`Failed to retry outbox item #${id}.`)
      }
    } catch {
      setActionMsg(`Failed to retry outbox item #${id}.`)
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
    return <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', padding: '8px 0' }}>Checking data health…</div>
  }
  if (error || !health) {
    return <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', padding: '8px 0' }}>Data health unavailable right now. <button className="btn btn-ghost" style={{ fontSize: '0.78rem', padding: '2px 8px' }} onClick={load}>Retry</button></div>
  }

  const ok = health.ok
  const sync = health.sync || {}
  const integrity = health.integrity || {}
  const ai = health.ai_usage || {}

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
          {ok ? 'All systems healthy' : 'Attention needed — review the items below'}
        </span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <button className="btn btn-secondary" style={{ fontSize: '0.76rem', padding: '3px 9px', display: 'inline-flex', alignItems: 'center', gap: 6 }} disabled={healing} onClick={runMasterSelfHealing}>
            {healing && <span className="sync-spinner-small" />}
            {healing ? 'Healing System…' : 'Auto-Repair & Heal System'}
          </button>
          <button className="btn btn-ghost" style={{ fontSize: '0.76rem', padding: '3px 9px', display: 'inline-flex', alignItems: 'center', gap: 5 }} onClick={load}>
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
            <button className="btn btn-ghost" style={{ fontSize: '0.76rem', padding: '2px 8px' }} onClick={load}>Retry</button>
          </div>
        )}

        {!outboxError && outboxItems.length === 0 && (
          <div style={{ padding: '10px 12px', borderTop: '1px solid var(--border)', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            Outbox is empty — every local change has been delivered to the cloud.
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
