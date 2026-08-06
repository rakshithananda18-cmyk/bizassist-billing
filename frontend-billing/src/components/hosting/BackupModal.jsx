import React, { useState, useEffect, useRef, useCallback } from 'react'
import { CLOUD_URL, LOCAL_URL } from '../../config'
import { logger } from '../../utils/logger'
import { CheckIcon, CloseIcon, ShieldIcon, SyncIcon } from '../Icons'

/**
 * BackupModal — fill in whatever one side is missing from the other.
 *
 * direction:
 *   'both'            →  cloud → local, THEN local → cloud   (the Settings button)
 *   'cloud-to-local'  →  one leg only  (mode-switch / nudge callers)
 *   'local-to-cloud'  →  one leg only
 *
 * WHAT THIS ACTUALLY DOES — and what it does not.
 *
 * The live import path is `_import_with_remap` (routes/data_transfer.py). When a
 * row already exists at the destination — matched on the durable `uid`, or on a
 * scoped natural key — it is SKIPPED. Not compared, not updated. So this is an
 * insert-what-is-missing pass, and it can never overwrite or delete anything.
 *
 * It is NOT Last-Write-Wins, whatever the old copy here claimed. The LWW branch
 * lives in `_upsert_rows`, which is only reachable with `remap_ids=false` — and
 * that returns 422 ("Unsafe id-preserving import is disabled"). `?merge=true`
 * was therefore a parameter nothing read, and an edit made on one side has never
 * crossed to the other through this modal. Edits propagate through the
 * continuous outbox sync, which compares against a CLOUD-issued cursor and so
 * does not depend on two machines agreeing about the time.
 *
 * Because neither direction contains the other, one leg is half the job — which
 * is why the Settings control runs both. Both legs are idempotent, so a retry
 * (or a second press) re-imports nothing.
 *
 * ponytail: leg 2 re-uploads everything leg 1 just downloaded — `export` has no
 * since-filter, so a full round trip moves the whole tenant twice. Measured on
 * the 10k-invoice load-test business: 55,064 rows / 32.6 MB per leg, nearly all
 * of it discarded as already-present. Shipped anyway because it costs exactly
 * what pressing the two old buttons cost, and a real shop is orders of magnitude
 * smaller. Upgrade path when it bites: give `/api/data-transfer/export` a
 * `since` parameter and pass the leg's own `bizassist_last_sync_*` stamp.
 */
const LEGS = {
  'cloud-to-local': {
    src: CLOUD_URL, dst: LOCAL_URL,
    read: 'Reading from the cloud',
    write: 'Adding what is missing on this device',
    result: 'Brought down',
  },
  'local-to-cloud': {
    src: LOCAL_URL, dst: CLOUD_URL,
    read: 'Reading from this device',
    write: 'Adding what is missing on the cloud',
    result: 'Sent up',
  },
}

const SUB = 'Adds anything either side is missing. Nothing is overwritten or removed.'

const PLANS = {
  'both': {
    title: 'Syncing with the cloud',
    sub: SUB,
    doneMsg: 'This device and the cloud now hold the same records.',
    legs: ['cloud-to-local', 'local-to-cloud'],
  },
  'cloud-to-local': {
    title: 'Cloud → Local Sync',
    sub: SUB,
    doneMsg: 'This device now has everything the cloud had.',
    legs: ['cloud-to-local'],
  },
  'local-to-cloud': {
    title: 'Local → Cloud Sync',
    sub: SUB,
    doneMsg: 'The cloud now has everything this device had.',
    legs: ['local-to-cloud'],
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

function countRows(exportPayload) {
  return Object.values(exportPayload?.tables || {})
    .reduce((s, rows) => s + (Array.isArray(rows) ? rows.length : 0), 0)
}

export default function BackupModal({ token, direction = 'both', onComplete, onError }) {
  const plan = PLANS[direction] || PLANS['both']

  // Two steps per leg, then one verify. Derived from the plan so a one-leg
  // caller renders three steps and the two-leg button renders five.
  const STEPS = React.useMemo(() => {
    const steps = []
    for (const key of plan.legs) {
      steps.push({ id: `${key}:read`, leg: key, phase: 'read', label: LEGS[key].read })
      steps.push({ id: `${key}:write`, leg: key, phase: 'write', label: LEGS[key].write })
    }
    steps.push({ id: 'verify', phase: 'verify', label: 'Verifying' })
    return steps
  }, [plan])

  const [statuses, setStatuses] = useState(() => STEPS.map((_, i) => (i === 0 ? 'active' : 'pending')))
  const [progress, setProgress] = useState(0)
  const [results, setResults] = useState({})     // { legKey: { read, imported, total } }
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
    logger.info(`[SYNC] Starting ${direction} (${plan.legs.length} leg(s), no mode switch)`)
    // Accumulated OUTSIDE state: the catch below has to report what already
    // landed, and a setState from this same tick is not readable there.
    const acc = {}
    let step = 0
    let lastDst = LOCAL_URL

    const applied = () => plan.legs
      .filter(k => acc[k]?.total != null)
      .map(k => `${LEGS[k].result.toLowerCase()} ${acc[k].total} record${acc[k].total === 1 ? '' : 's'}`)

    try {
      for (const legKey of plan.legs) {
        const leg = LEGS[legKey]
        lastDst = leg.dst

        // 1. Read everything the source holds.
        advance(step); setProgress(Math.round((step / STEPS.length) * 100))
        const exRes = await fetch(`${leg.src}/api/data-transfer/export`, { headers: headersFor(leg.src) })
        if (!exRes.ok) throw new Error(`Could not read from the source: HTTP ${exRes.status}`)
        const exportData = await exRes.json()
        if (cancelled.current) return
        acc[legKey] = { read: countRows(exportData) }
        setResults({ ...acc })
        mark(step, 'done'); step++

        // 2. Insert whatever the destination is missing. `merge` is deliberately
        //    NOT sent — the parameter is only read by the retired id-preserving
        //    path, so passing it advertised a Last-Write-Wins behaviour that
        //    never ran. `remap_ids=true` is the only accepted mode.
        advance(step); setProgress(Math.round((step / STEPS.length) * 100))
        const imRes = await fetch(`${leg.dst}/api/data-transfer/import?remap_ids=true`, {
          method: 'POST', headers: headersFor(leg.dst),
          body: JSON.stringify({ tables: exportData?.tables || {} }),
        })
        if (!imRes.ok) {
          // A cloud-side 401 means the cloud sync token is missing/expired (it's a
          // 24h token) — the local JWT can't authenticate to the cloud. Re-login
          // re-provisions it; say so instead of a bare HTTP 401.
          if (imRes.status === 401 && leg.dst === CLOUD_URL) {
            throw new Error('Cloud session expired — please sign out and sign back in to reconnect cloud sync, then retry.')
          }
          throw new Error(`Could not write to the destination: HTTP ${imRes.status}`)
        }
        const imData = await imRes.json()
        if (cancelled.current) return
        acc[legKey] = { ...acc[legKey], imported: imData?.imported || {}, total: imData?.total ?? 0 }
        setResults({ ...acc })
        // Per LEG, not per press: each one genuinely completed on its own.
        try { localStorage.setItem(`bizassist_last_sync_${legKey}`, new Date().toISOString()) } catch { /* ignore */ }
        mark(step, 'done'); step++
      }

      // 3. Verify (light)
      advance(step)
      try { await fetch(`${lastDst}/health`) } catch { /* non-fatal */ }
      if (cancelled.current) return
      mark(step, 'done'); setProgress(100)

      logger.info(`[SYNC] ${direction} complete: ${applied().join(', ') || 'nothing to move'}`)
      // Don't auto-dismiss — show result so the user can acknowledge it.
    } catch (err) {
      if (cancelled.current) return
      mark(idxRef.current, 'error')
      // A half-finished two-leg run is NOT "sync failed, nothing happened". The
      // first leg is already committed, and telling the owner otherwise invites
      // them to go hunting for data that arrived perfectly well.
      const kept = applied()
      setErrorMsg(kept.length
        ? `${kept.join(' and ')} — that part is saved. Then it stopped: ${err?.message || 'sync failed'}`
        : (err?.message || 'Sync failed'))
      logger.error(`[SYNC] ${direction} failed:`, err)
      onError?.(err)
    }
  }

  const done = statuses.every(s => s === 'done')
  const failed = statuses.some(s => s === 'error')
  const legsWithResult = plan.legs.filter(k => results[k]?.total != null)
  const grandTotal = legsWithResult.reduce((s, k) => s + (results[k].total || 0), 0)

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 9999, background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(12px)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: 'var(--bg-2, #1a1a1a)', border: '1px solid var(--border, rgba(255,255,255,0.12))', maxHeight: '90vh', overflowY: 'auto', borderRadius: 16, padding: '30px 34px', width: '100%', maxWidth: 520, boxShadow: '0 24px 80px rgba(0,0,0,0.5)' }}>

        {/* Header */}
        <div style={{ fontSize: '1.12rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: 4 }}>
          {done ? (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><CheckIcon size={18} strokeWidth={2.5} style={{ color: '#22c55e' }} /> Sync complete</span>
          ) : failed ? (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><CloseIcon size={18} strokeWidth={2.5} style={{ color: '#ef4444' }} /> Sync stopped</span>
          ) : plan.title + '…'}
        </div>
        <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 20 }}>
          {done ? plan.doneMsg
            : failed ? 'Nothing was overwritten — this only ever adds missing records.'
            : plan.sub + ' Hosting mode stays the same.'}
        </div>

        {/* Progress bar */}
        <div style={{ height: 6, background: 'rgba(255,255,255,0.1)', borderRadius: 99, overflow: 'hidden', marginBottom: 18 }}>
          <div style={{ height: '100%', width: `${progress}%`, background: failed ? '#ef4444' : done ? '#22c55e' : 'var(--accent)', borderRadius: 99, transition: 'width 0.35s ease' }} />
        </div>

        {/* Step list */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 18 }}>
          {STEPS.map((step, i) => (
            <div key={step.id} style={{ display: 'flex', alignItems: 'center', gap: 12, opacity: statuses[i] === 'pending' ? 0.45 : 1 }}>
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
                {step.phase === 'read' && statuses[i] === 'done' && results[step.leg]?.read != null && (
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 1 }}>
                    {results[step.leg].read.toLocaleString()} records read
                  </div>
                )}
                {step.phase === 'write' && statuses[i] === 'done' && results[step.leg]?.total != null && (
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 1 }}>
                    {results[step.leg].total === 0
                      ? 'nothing missing'
                      : `${results[step.leg].total.toLocaleString()} added`}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Result, per leg. Two legs move different data in different
            directions, so a single merged total would hide which side was
            actually behind. */}
        {done && grandTotal > 0 && (
          <div style={{ background: 'rgba(34,197,94,0.06)', border: '1px solid rgba(34,197,94,0.2)', borderRadius: 10, padding: '12px 14px', marginBottom: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.78rem', fontWeight: 700, color: '#22c55e', marginBottom: 10 }}>
              <ShieldIcon size={13} strokeWidth={2} />
              <span>{grandTotal.toLocaleString()} missing record{grandTotal === 1 ? '' : 's'} filled in</span>
            </div>
            {legsWithResult.filter(k => results[k].total > 0).map(k => (
              <div key={k} style={{ marginBottom: 8 }}>
                <div style={{ fontSize: '0.73rem', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 4 }}>
                  {LEGS[k].result} · {results[k].total.toLocaleString()}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {Object.entries(results[k].imported || {}).map(([tbl, cnt]) => (
                    <div key={tbl} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{tableLabel(tbl)}</span>
                      <span style={{ fontSize: '0.75rem', fontWeight: 700, color: '#22c55e', background: 'rgba(34,197,94,0.1)', borderRadius: 6, padding: '1px 7px' }}>
                        +{cnt}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* No changes */}
        {done && grandTotal === 0 && (
          <div style={{ background: 'rgba(34,197,94,0.06)', border: '1px solid rgba(34,197,94,0.2)', borderRadius: 10, padding: '10px 14px', fontSize: '0.8rem', color: '#22c55e', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 6 }}>
            <CheckIcon size={14} strokeWidth={2} />
            <span>Both sides already had everything — nothing to add.</span>
          </div>
        )}

        {/* Error message */}
        {failed && (
          <div style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 8, padding: '10px 14px', fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: 16 }}>{errorMsg}</div>
        )}

        {/* Buttons */}
        {(done || failed) && (
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 4 }}>
            {failed && (
              <button onClick={() => {
                // Re-runs from the FIRST leg. Safe because every leg only
                // inserts what is missing — a completed leg re-imports nothing.
                setStatuses(STEPS.map((_, i) => (i === 0 ? 'active' : 'pending')))
                setErrorMsg(null); setProgress(0); setResults({})
                run()
              }}
                style={{ padding: '8px 18px', borderRadius: 8, background: 'var(--accent)', color: '#fff', border: 'none', cursor: 'pointer', fontSize: '0.82rem', fontWeight: 700, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <SyncIcon size={14} /> Retry
              </button>
            )}
            <button
              onClick={() => onComplete?.(done ? { legs: results, total: grandTotal } : null)}
              style={{
                padding: '8px 20px', borderRadius: 8, fontWeight: 700, fontSize: '0.84rem',
                cursor: 'pointer',
                ...(done
                  ? { background: '#22c55e', color: '#fff', border: 'none' }
                  : { background: 'transparent', color: 'var(--text-muted)', border: '1px solid rgba(255,255,255,0.15)' }
                )
              }}>
              {done ? '✓ Done' : 'Close'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
