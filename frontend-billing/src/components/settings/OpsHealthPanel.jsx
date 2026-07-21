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
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setError(false)
    try {
      const [hRes, cRes] = await Promise.all([
        authFetch('/reports/ops-health'),
        authFetch('/api/sync/conflicts'),
      ])
      if (hRes.ok) setHealth(await hRes.json())
      if (cRes.ok) setConflicts((await cRes.json()).conflicts || [])
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
        <button className="btn btn-ghost" style={{ marginLeft: 'auto', fontSize: '0.76rem', padding: '3px 9px', display: 'inline-flex', alignItems: 'center', gap: 5 }} onClick={load}>
          <SyncIcon size={13} /> Refresh
        </button>
      </div>

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

      {/* Conflict review list */}
      {conflicts.length > 0 && (
        <div style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', overflow: 'hidden' }}>
          <div style={{ padding: '8px 12px', background: 'var(--bg-3)', fontSize: '0.78rem', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Financial edits synced from another device — review &amp; clear
          </div>
          {conflicts.map(c => (
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
          <div style={{ padding: '8px 12px', fontSize: '0.72rem', color: 'var(--text-muted)', borderTop: '1px solid var(--border)' }}>
            The most recent edit is what’s stored. Marking reviewed only clears it from this list — it doesn’t change your data.
          </div>
        </div>
      )}
    </div>
  )
}
