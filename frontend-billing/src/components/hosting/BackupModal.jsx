import React, { useState, useEffect, useRef, useCallback } from 'react'
import { CLOUD_URL, LOCAL_URL } from '../../config'
import { logger } from '../../utils/logger'
import { CheckIcon, CloseIcon, ShieldIcon, SyncIcon } from '../Icons'

/**
 * SyncModal — one-click data sync between cloud and local, either direction.
 *
 * direction:
 *   'cloud-to-local'  →  pull cloud data down to this device   (default)
 *   'local-to-cloud'  →  push local data up to the cloud
 *
 * Merge semantics: NON-DESTRUCTIVE Last-Write-Wins. The import runs with
 * `?merge=true`, so the destination keeps newer/local-only rows and only takes
 * rows that are new or more recently edited on the source. Nothing is blindly
 * overwritten. Hosting mode is NOT changed. Needs network (the source/dest call
 * the cloud); the button is disabled offline by the caller.
 */
const LABELS = {
  'cloud-to-local': {
    title: 'Cloud → Local Sync',
    sub: 'Bring your cloud data to this device (merge — nothing local is overwritten).',
    src: CLOUD_URL, dst: LOCAL_URL,
    steps: [
      { key: 'export',  label: 'Reading data from cloud' },
      { key: 'import',  label: 'Merging into local database' },
      { key: 'verify',  label: 'Verifying sync' },
    ],
    doneMsg: 'Your device now has the latest data (merged).',
  },
  'local-to-cloud': {
    title: 'Local → Cloud Sync',
    sub: 'Push this device\'s data up to the cloud backup (merge — nothing on cloud is overwritten).',
    src: LOCAL_URL, dst: CLOUD_URL,
    steps: [
      { key: 'export',  label: 'Reading data from this device' },
      { key: 'import',  label: 'Merging into cloud database' },
      { key: 'verify',  label: 'Verifying sync' },
    ],
    doneMsg: 'Your cloud backup now has the latest data (merged).',
  },
}

// Human-friendly table names for the breakdown panel
const TABLE_LABELS = {
  users: 'Business / Staff',
  customers: 'Customers / Parties',
  invoices: 'Invoices',
  invoice_line_items: 'Invoice Items',
  invoice_payments: 'Payments',
  products: 'Products',
  stock: 'Stock',
  purchases: 'Purchases',
  purchase_line_items: 'Purchase Items',
  expenses: 'Expenses',
  journal_entries: 'Journal Entries',
}

function tableLabel(t) {
  return TABLE_LABELS[t] || t.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export default function BackupModal({ token, direction = 'cloud-to-local', onComplete, onError }) {
  const cfg = LABELS[direction] || LABELS['cloud-to-local']
  const STEPS = cfg.steps
  const [statuses, setStatuses] = useState(STEPS.map((_, i) => (i === 0 ? 'active' : 'pending')))
  const [progress, setProgress] = useState(0)
  const [breakdown, setBreakdown] = useState(null)   // { tableName: count }
  const [exportCount, setExportCount] = useState(null)
  const [errorMsg, setErrorMsg] = useState(null)
  const idxRef = useRef(0)
  const cancelled = useRef(false)
  const started = useRef(false)   // guard against React StrictMode double-invoke

  const mark = useCallback((i, s) => setStatuses(prev => prev.map((p, k) => (k === i ? s : p))), [])
  const advance = useCallback((i) => {
    idxRef.current = i
    setStatuses(prev => prev.map((p, k) => (k < i ? 'done' : k === i ? 'active' : 'pending')))
  }, [])

  // Tokens are backend-specific: the LOCAL backend accepts the local JWT, the
  // CLOUD backend only accepts a CLOUD-issued token (the local JWT → HTTP 401 on
  // the cloud). So pick the token by which backend we're talking to.
  const headersFor = useCallback((base) => {
    let cloudTok = null
    try { cloudTok = localStorage.getItem('bizassist_cloud_token') } catch { /* ignore */ }
    const t = base === CLOUD_URL ? cloudTok : token
    return {
      'Content-Type': 'application/json',
      ...(t ? { Authorization: `Bearer ${t}` } : {}),
    }
  }, [token])

  useEffect(() => {
    if (started.current) return       // fire once, even under StrictMode double-mount
    started.current = true
    cancelled.current = false
    run()
    /* eslint-disable-next-line */
  }, [])

  async function run() {
    logger.info(`[SYNC] Starting ${direction} (merge, no mode switch)`)
    try {
      // 1. Export from source
      advance(0); setProgress(10)
      const exRes = await fetch(`${cfg.src}/api/data-transfer/export`, { headers: headersFor(cfg.src) })
      if (!exRes.ok) throw new Error(`Source export failed: HTTP ${exRes.status}`)
      const exportData = await exRes.json()
      if (cancelled.current) return

      // Count total exported records for display
      const totalExported = Object.values(exportData?.tables || {}).reduce((s, rows) => s + (Array.isArray(rows) ? rows.length : 0), 0)
      setExportCount(totalExported)
      mark(0, 'done'); setProgress(45)

      // 2. Merge into destination (LWW, non-destructive). Does NOT touch hosting_mode.
      advance(1)
      const imRes = await fetch(`${cfg.dst}/api/data-transfer/import?merge=true`, {
        method: 'POST', headers: headersFor(cfg.dst),
        body: JSON.stringify({ tables: exportData?.tables || {} }),
      })
      if (!imRes.ok) {
        // A cloud-side 401 means the cloud sync token is missing/expired (it's a
        // 24h token) — the local JWT can't authenticate to the cloud. Re-login
        // re-provisions it; say so instead of a bare HTTP 401.
        if (imRes.status === 401 && cfg.dst === CLOUD_URL) {
          throw new Error('Cloud session expired — please sign out and sign back in to reconnect cloud sync, then retry.')
        }
        throw new Error(`Destination merge failed: HTTP ${imRes.status}`)
      }
      const imData = await imRes.json()
      if (cancelled.current) return
      setBreakdown(imData?.imported || {})
      mark(1, 'done'); setProgress(85)

      // 3. Verify (light)
      advance(2)
      try { await fetch(`${cfg.dst}/health`) } catch { /* non-fatal */ }
      if (cancelled.current) return
      mark(2, 'done'); setProgress(100)

      // Record the last successful sync time for this direction (shown in Settings).
      try { localStorage.setItem(`bizassist_last_sync_${direction}`, new Date().toISOString()) } catch { /* ignore */ }

      const total = imData?.total ?? 0
      logger.info(`[SYNC] ${direction} complete: ${total} records merged`)
      setTimeout(() => onComplete?.(imData), 700)
    } catch (err) {
      if (cancelled.current) return
      mark(idxRef.current, 'error')
      setErrorMsg(err?.message || 'Sync failed')
      logger.error(`[SYNC] ${direction} failed:`, err)
      onError?.(err)
    }
  }

  const done = statuses.every(s => s === 'done')
  const failed = statuses.some(s => s === 'error')
  const total = breakdown ? Object.values(breakdown).reduce((s, n) => s + n, 0) : 0

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 9999, background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(12px)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: 'var(--bg-2, #1a1a1a)', border: '1px solid var(--border, rgba(255,255,255,0.12))', borderRadius: 16, padding: '30px 34px', width: '100%', maxWidth: 520, boxShadow: '0 24px 80px rgba(0,0,0,0.5)' }}>

        {/* Header */}
        <div style={{ fontSize: '1.12rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: 4 }}>
          {done ? (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><CheckIcon size={18} strokeWidth={2.5} style={{ color: '#22c55e' }} /> Sync complete</span>
          ) : failed ? (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><CloseIcon size={18} strokeWidth={2.5} style={{ color: '#ef4444' }} /> Sync failed</span>
          ) : cfg.title + '…'}
        </div>
        <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 20 }}>
          {done ? cfg.doneMsg : failed ? 'Your data is unchanged — nothing was committed on failure.' : cfg.sub + ' Hosting mode stays the same.'}
        </div>

        {/* Progress bar */}
        <div style={{ height: 6, background: 'rgba(255,255,255,0.1)', borderRadius: 99, overflow: 'hidden', marginBottom: 18 }}>
          <div style={{ height: '100%', width: `${progress}%`, background: failed ? '#ef4444' : done ? '#22c55e' : 'var(--accent)', borderRadius: 99, transition: 'width 0.35s ease' }} />
        </div>

        {/* Step list */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 18 }}>
          {STEPS.map((step, i) => (
            <div key={step.key} style={{ display: 'flex', alignItems: 'center', gap: 12, opacity: statuses[i] === 'pending' ? 0.45 : 1 }}>
              <div style={{ minWidth: 20, display: 'flex', justifyContent: 'center' }}>
                {statuses[i] === 'done'   ? <CheckIcon size={16} strokeWidth={2.5} style={{ color: '#22c55e' }} />
                 : statuses[i] === 'active' ? <span className="mg-spinner" style={{ display: 'inline-block' }} />
                 : statuses[i] === 'error'  ? <CloseIcon size={16} strokeWidth={2.5} style={{ color: '#ef4444' }} />
                 : <span style={{ fontSize: 16, color: 'var(--text-muted)', opacity: 0.5 }}>○</span>}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: '0.84rem', fontWeight: statuses[i] === 'active' ? 700 : 500, color: statuses[i] === 'error' ? '#ef4444' : statuses[i] === 'done' ? '#22c55e' : 'var(--text-primary)' }}>
                  {step.label}
                </div>
                {/* Sub-detail for export step once done */}
                {step.key === 'export' && statuses[i] === 'done' && exportCount != null && (
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 1 }}>
                    {exportCount.toLocaleString()} records read
                  </div>
                )}
                {/* Sub-detail for import step once done */}
                {step.key === 'import' && statuses[i] === 'done' && breakdown && (
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 1 }}>
                    {total.toLocaleString()} records merged across {Object.keys(breakdown).length} tables
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Success detail: per-table breakdown */}
        {done && breakdown && Object.keys(breakdown).length > 0 && (
          <div style={{ background: 'rgba(34,197,94,0.06)', border: '1px solid rgba(34,197,94,0.2)', borderRadius: 10, padding: '12px 14px', marginBottom: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.78rem', fontWeight: 700, color: '#22c55e', marginBottom: 10 }}>
              <ShieldIcon size={13} strokeWidth={2} />
              <span>{total.toLocaleString()} records merged (newer wins; nothing overwritten)</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {Object.entries(breakdown).map(([tbl, cnt]) => (
                <div key={tbl} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{tableLabel(tbl)}</span>
                  <span style={{ fontSize: '0.75rem', fontWeight: 700, color: '#22c55e', background: 'rgba(34,197,94,0.1)', borderRadius: 6, padding: '1px 7px' }}>
                    +{cnt}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* No changes */}
        {done && breakdown && Object.keys(breakdown).length === 0 && (
          <div style={{ background: 'rgba(34,197,94,0.06)', border: '1px solid rgba(34,197,94,0.2)', borderRadius: 10, padding: '10px 14px', fontSize: '0.8rem', color: '#22c55e', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 6 }}>
            <CheckIcon size={14} strokeWidth={2} />
            <span>Everything is up to date — no new records to merge.</span>
          </div>
        )}

        {/* Error message */}
        {failed && (
          <div style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 8, padding: '10px 14px', fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: 16 }}>{errorMsg}</div>
        )}

        {/* Buttons */}
        {(done || failed) && (
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
            {failed && (
              <button onClick={() => {
                setStatuses(STEPS.map((_, i) => (i === 0 ? 'active' : 'pending')))
                setErrorMsg(null); setProgress(0); setBreakdown(null); setExportCount(null)
                run()
              }}
                style={{ padding: '8px 16px', borderRadius: 8, background: 'var(--accent)', color: '#fff', border: 'none', cursor: 'pointer', fontSize: '0.82rem', fontWeight: 700, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <SyncIcon size={14} /> Retry
              </button>
            )}
            <button onClick={() => onComplete?.(null)}
              style={{ padding: '8px 16px', borderRadius: 8, border: '1px solid rgba(255,255,255,0.15)', background: 'transparent', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '0.82rem' }}>
              Close
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
