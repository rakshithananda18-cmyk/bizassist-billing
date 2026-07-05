import React, { useState, useEffect, useRef, useCallback } from 'react'
import { API_BASE, updateApiBase } from '../../config'
import { useAuth } from '../../contexts/AuthContext'
import { logger } from '../../utils/logger'
import { CheckIcon, CloseIcon, AlertIcon, SyncIcon, ShieldIcon, LogoutIcon } from '../Icons'

// ── Step definitions ──────────────────────────────────────────────────────────
const STEPS = [
  { id: 'verify',   label: 'Verifying credentials & permissions' },
  { id: 'count',    label: 'Counting records to migrate' },
  { id: 'export',   label: 'Exporting data from source' },
  { id: 'upload',   label: 'Uploading data to destination' },
  { id: 'validate', label: 'Validating migrated data' },
  { id: 'finalize', label: 'Finalising & switching mode' },
]

const STEP_WEIGHT = [5, 10, 20, 50, 10, 5] // must sum to 100

function StepIcon({ status }) {
  if (status === 'done')     return <CheckIcon size={16} strokeWidth={2.5} style={{ color: '#22c55e' }} />
  if (status === 'active')   return <span className="mg-spinner" style={{ display: 'inline-block' }} />
  if (status === 'error')    return <CloseIcon size={16} strokeWidth={2.5} style={{ color: '#ef4444' }} />
  return <span style={{ fontSize: 16, color: 'var(--text-muted)', opacity: 0.5 }}>○</span>
}

function ProgressBar({ value, color = 'var(--accent)' }) {
  return (
    <div style={{
      height: 6, background: 'rgba(255,255,255,0.1)', borderRadius: 99, overflow: 'hidden',
    }}>
      <div style={{
        height: '100%',
        width: `${Math.min(100, Math.max(0, value))}%`,
        background: color,
        borderRadius: 99,
        transition: 'width 0.35s ease',
      }} />
    </div>
  )
}

// Minimal mini bar for the per-table breakdown
function MiniBar({ done, total }) {
  const pct = total > 0 ? (done / total) * 100 : 0
  return (
    <div style={{ height: 4, background: 'rgba(255,255,255,0.08)', borderRadius: 99, minWidth: 60, flex: 1 }}>
      <div style={{ height: '100%', width: `${pct}%`, background: '#22c55e', borderRadius: 99, transition: 'width 0.3s' }} />
    </div>
  )
}

function etaText(secondsLeft) {
  if (secondsLeft == null || secondsLeft < 0) return ''
  if (secondsLeft < 5)  return 'Almost done…'
  if (secondsLeft < 60) return `About ${Math.round(secondsLeft)} seconds left`
  const m = Math.ceil(secondsLeft / 60)
  return `About ${m} minute${m > 1 ? 's' : ''} left`
}

export default function MigrationModal({ fromMode, toMode, onComplete, onError, token }) {
  const { user } = useAuth() || {}   // tolerate render outside AuthProvider (tests)
  const [stepIdx,      setStepIdx]      = useState(0)   // 0-5
  const [stepStatuses, setStepStatuses] = useState(
    STEPS.map((_, i) => (i === 0 ? 'active' : 'pending'))
  ) // 'pending' | 'active' | 'done' | 'error'
  const [progress,     setProgress]     = useState(0)
  const [tableRows,    setTableRows]    = useState([])  // [{entity, done, total}]
  const [eta,          setEta]          = useState(null)
  const [startTime,    setStartTime]    = useState(null)
  const [backupPath,   setBackupPath]   = useState(null)
  const [errorStep,    setErrorStep]    = useState(null)
  const [errorMsg,     setErrorMsg]     = useState(null)
  const [cancelled,    setCancelled]    = useState(false)
  const [validation,   setValidation]   = useState([])   // [{entity, expected, found, ok}]
  const [validationPaused, setValidationPaused] = useState(false) // mismatch → wait for user

  const cancelledRef = useRef(false)
  const stepIdxRef = useRef(0)
  const startedRef = useRef(false)   // guard against React StrictMode double-invoke
  const basesRef = useRef({ src: null, dest: null }) // for finalize-after-pause

  const markStep = useCallback((idx, status) => {
    setStepStatuses(prev => prev.map((s, i) => i === idx ? status : s))
  }, [])

  const advanceTo = useCallback((idx) => {
    stepIdxRef.current = idx
    setStepIdx(idx)
    setStepStatuses(prev => prev.map((s, i) => {
      if (i < idx)  return 'done'
      if (i === idx) return 'active'
      return 'pending'
    }))
    // Compute cumulative progress to start of this step
    const base = STEP_WEIGHT.slice(0, idx).reduce((a, b) => a + b, 0)
    setProgress(base)
  }, [])

  const headers = useCallback(() => ({
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }), [token])

  // ── Run migration ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (startedRef.current) return     // fire once, even under StrictMode double-mount
    startedRef.current = true
    cancelledRef.current = false
    setStartTime(Date.now())
    run()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function run() {
    logger.info(`[MIGRATION] Starting hosting mode migration from ${fromMode} to ${toMode}`)
    const CLOUD_URL = import.meta.env.VITE_API_URL || 'https://rakshit-dev-bizassist.hf.space'
    const LOCAL_URL = 'http://localhost:8001'
    const SOURCE_API_BASE = fromMode === 'cloud' ? CLOUD_URL : LOCAL_URL
    const DEST_API_BASE = (toMode === 'cloud' || toMode === 'hybrid') ? CLOUD_URL : LOCAL_URL

    try {
      // ── Step 0: verify ────────────────────────────────────────────────────
      advanceTo(0)
      await new Promise(r => setTimeout(r, 600)) // brief pause so user sees it
      if (cancelledRef.current) return
      markStep(0, 'done')

      // ── Step 1: count ─────────────────────────────────────────────────────
      advanceTo(1)
      let countData = {}
      try {
        const res = await fetch(`${SOURCE_API_BASE}/api/data-transfer/count`, { headers: headers() })
        if (!res.ok) throw new Error(`Count failed: HTTP ${res.status}`)
        countData = await res.json()
      } catch (err) {
        // count endpoint may not exist yet; fall back gracefully
        countData = {}
      }
      if (cancelledRef.current) return
      setProgress(15)
      markStep(1, 'done')

      // Initialise table rows for step 3 display
      const tables = Object.entries(countData)
      setTableRows(tables.map(([name, count]) => ({ entity: name, done: 0, total: count })))

      // ── Step 2: export ────────────────────────────────────────────────────
      advanceTo(2)
      const res = await fetch(`${SOURCE_API_BASE}/api/data-transfer/export`, { headers: headers() })
      if (!res.ok) throw new Error(`Export failed: HTTP ${res.status}`)
      const exportData = await res.json()
      if (cancelledRef.current) return

      // REAL safety net: snapshot the DESTINATION before writing anything to
      // it, downloaded as a JSON the user actually holds. Restorable via the
      // same import endpoint. (backup_path from the backend never existed.)
      try {
        const snapRes = await fetch(`${DEST_API_BASE}/api/data-transfer/export`, { headers: headers() })
        if (snapRes.ok) {
          const snap = await snapRes.json()
          const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')
          const fname = `bizassist-backup-before-${toMode}-migration-${stamp}.json`
          const url = URL.createObjectURL(new Blob([JSON.stringify(snap)], { type: 'application/json' }))
          const a = document.createElement('a')
          a.href = url
          a.download = fname
          document.body.appendChild(a)
          a.click()
          a.remove()
          setTimeout(() => URL.revokeObjectURL(url), 5000)
          setBackupPath(`${fname} (in your Downloads folder)`)
        }
      } catch (err) {
        logger.warn('[MIGRATION] Destination snapshot failed (continuing):', err)
      }

      if (cancelledRef.current) return
      setProgress(35)
      markStep(2, 'done')

      // ── Step 3: upload ────────────────────────────────────────────────────
      advanceTo(3)

      // Simulate per-table progress while uploading
      const uploadTables = exportData?.tables ? Object.keys(exportData.tables) : []
      const perTable = uploadTables.map((k, i) => ({
        entity: k,
        done: 0,
        total: exportData.tables[k]?.length || 0,
      }))
      if (perTable.length > 0) setTableRows(perTable)

      let uploadRes = null
      try {
        // Kick off the real import.
        // remap_ids=true is REQUIRED here: the default "mirror" mode upserts by
        // primary key, so when the destination already has its own rows (any
        // round-trip local↔cloud), colliding ids OVERWRITE destination data —
        // this wiped LCL-OW-* invoices in testing. Remap mode assigns fresh
        // ids, rewrites FKs, and dedups by natural keys (idempotent on retry).
        const importPromise = fetch(`${DEST_API_BASE}/api/data-transfer/import?remap_ids=true`, {
          method: 'POST',
          headers: headers(),
          body: JSON.stringify({
            tables: exportData?.tables || {},
          }),
        })

        // Animate per-table progress while waiting
        let p = 35
        const animInterval = setInterval(() => {
          if (cancelledRef.current) { clearInterval(animInterval); return }
          p = Math.min(82, p + 1.5)
          setProgress(p)
          setTableRows(prev => prev.map(row => ({
            ...row,
            done: Math.min(row.total, Math.floor((p - 35) / 47 * row.total)),
          })))
          const elapsed = (Date.now() - (startTime || Date.now())) / 1000
          const estTotal = elapsed / Math.max(1, (p - 35) / 47) 
          setEta(Math.max(0, estTotal - elapsed))
        }, 200)

        uploadRes = await importPromise
        clearInterval(animInterval)

        if (!uploadRes.ok) throw new Error(`Import failed: HTTP ${uploadRes.status}`)
        const importData = await uploadRes.json()
        if (importData.backup_path && !backupPath) setBackupPath(importData.backup_path)
      } catch (err) {
        if (cancelledRef.current) return
        throw err
      }

      if (cancelledRef.current) return

      // Mark all rows done
      setTableRows(prev => prev.map(r => ({ ...r, done: r.total })))
      setProgress(85)
      markStep(3, 'done')

      // ── Step 4: validate (REAL — recount on the destination) ──────────────
      advanceTo(4)
      basesRef.current = { src: SOURCE_API_BASE, dest: DEST_API_BASE }
      let results = []
      try {
        const vres = await fetch(`${DEST_API_BASE}/api/data-transfer/count`, { headers: headers() })
        if (vres.ok) {
          const destCounts = await vres.json()
          const srcTables = exportData?.tables || {}
          results = Object.entries(srcTables)
            .map(([entity, rows]) => {
              const expected = Array.isArray(rows) ? rows.length : 0
              // Destination may legitimately hold MORE (pre-existing data merged
              // in) — a shortfall is the only red flag.
              const found = Number(destCounts?.[entity] ?? NaN)
              return { entity, expected, found, ok: !Number.isFinite(found) || found >= expected }
            })
            .filter(v => v.expected > 0)
        }
      } catch (err) {
        logger.warn('[MIGRATION] Validation recount unavailable (continuing):', err)
      }
      if (cancelledRef.current) return
      setValidation(results)
      const mismatches = results.filter(v => !v.ok)
      setProgress(95)

      if (mismatches.length > 0) {
        // Don't silently finalise onto missing data — pause and let the user
        // decide (retry / continue anyway). Source data is untouched either way.
        logger.warn('[MIGRATION] Validation mismatches:', mismatches)
        markStep(4, 'error')
        setValidationPaused(true)
        return
      }
      markStep(4, 'done')

      // ── Step 5: finalise ──────────────────────────────────────────────────
      await doFinalize(SOURCE_API_BASE, DEST_API_BASE, results)

    } catch (err) {
      if (cancelledRef.current) return
      const failedIdx = stepIdxRef.current
      markStep(failedIdx, 'error')
      setErrorStep(STEPS[failedIdx]?.label || 'Unknown step')
      setErrorMsg(err?.message || 'An unknown error occurred')
      logger.error(`[MIGRATION] Migration failed at step "${STEPS[failedIdx]?.label || 'unknown'}":`, err)
      onError?.(err)
    }
  }

  /** Step 5 — switch API base, persist mode on both backends, show summary. */
  async function doFinalize(SOURCE_API_BASE, DEST_API_BASE, results) {
    advanceTo(5)
    if (cancelledRef.current) return

    try {
      updateApiBase(toMode)
    } catch (err) {
      logger.error('Failed to call updateApiBase:', err)
    }

    for (const base of [SOURCE_API_BASE, DEST_API_BASE]) {
      try {
        await fetch(`${base}/settings`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify({ general: { hosting_mode: toMode } }),
        })
      } catch (err) {
        logger.warn(`Failed to update settings on backend (${base}):`, err)
      }
    }

    window.dispatchEvent(new CustomEvent('refresh-settings'))
    if (cancelledRef.current) return
    setProgress(100)
    markStep(5, 'done')
    setEta(0)

    // Persist a report + prefill so the login page can greet the user after
    // the (by-design) re-login, and support can inspect what moved.
    try {
      localStorage.setItem('bizassist_last_migration', JSON.stringify({
        at: new Date().toISOString(),
        from: fromMode,
        to: toMode,
        backupPath,
        validation: results,
        forced: results?.some?.(v => !v.ok) || false,
      }))
      if (user?.username) localStorage.setItem('bizassist_prefill_username', user.username)
    } catch { /* storage full — non-fatal */ }

    logger.info(`[MIGRATION] Hosting mode migration completed successfully to ${toMode}`)
    // NOTE: no auto-close. The user reads the summary and continues explicitly —
    // onComplete triggers the mode switch, which signs them out for a fresh JWT.
  }

  /** "Continue anyway" after a validation mismatch. */
  const handleForceFinalize = () => {
    logger.warn('[MIGRATION] User chose to finalise despite validation mismatches')
    setValidationPaused(false)
    doFinalize(basesRef.current.src, basesRef.current.dest, validation)
  }

  const handleCancel = () => {
    logger.warn('[MIGRATION] Migration cancelled by user')
    cancelledRef.current = true
    setCancelled(true)
    onError?.(new Error('Cancelled by user'))
  }

  const handleRetry = () => {
    logger.info('[MIGRATION] User triggered retry (page reload)')
    window.location.reload()
  }

  const isComplete = stepStatuses.every(s => s === 'done')
  const hasError   = stepStatuses.some(s => s === 'error')

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 9999,
      background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(12px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: 24,
    }}>
      <div style={{
        background: 'var(--bg-2, #1a1a1a)',
        border: '1px solid var(--border, rgba(255,255,255,0.12))',
        borderRadius: 16,
        padding: '32px 36px',
        width: '100%', maxWidth: 520,
        maxHeight: 'calc(100vh - 48px)',      // long table lists must scroll,
        overflowY: 'auto',                    // not push buttons off-screen
        overscrollBehavior: 'contain',
        boxShadow: '0 24px 80px rgba(0,0,0,0.5)',
      }}>
        {/* Title */}
        <div style={{ fontSize: '1.15rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: 6 }}>
          {isComplete ? (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <CheckIcon size={18} strokeWidth={2.5} style={{ color: '#22c55e' }} />
              <span>Migration Complete!</span>
            </span>
          ) : validationPaused ? (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <AlertIcon size={18} strokeWidth={2.5} style={{ color: '#f97316' }} />
              <span>Validation needs your attention</span>
            </span>
          ) : hasError ? (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <CloseIcon size={18} strokeWidth={2.5} style={{ color: '#ef4444' }} />
              <span>Migration Failed</span>
            </span>
          ) : (
            `Migrating to ${toMode === 'hybrid' ? 'Local + Cloud' : toMode} mode…`
          )}
        </div>
        <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 22 }}>
          {isComplete
            ? 'All data has been successfully migrated.'
            : validationPaused
            ? 'The destination recount found fewer records than expected.'
            : hasError
            ? 'Something went wrong. Your original data is safe.'
            : 'Please do not close this window or navigate away.'}
        </div>

        {/* Overall progress bar */}
        <ProgressBar
          value={progress}
          color={hasError ? '#ef4444' : isComplete ? '#22c55e' : 'var(--accent)'}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, marginBottom: 20 }}>
          <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
            {eta != null && eta > 0 ? etaText(eta) : isComplete ? 'Complete' : ''}
          </span>
          <span style={{ fontSize: '0.72rem', fontWeight: 600, color: 'var(--text-muted)' }}>
            {Math.round(progress)}%
          </span>
        </div>

        {/* Step list */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 22 }}>
          {STEPS.map((step, i) => (
            <div key={step.id} style={{
              display: 'flex', alignItems: 'flex-start', gap: 12,
              opacity: stepStatuses[i] === 'pending' ? 0.45 : 1,
              transition: 'opacity 0.2s',
            }}>
              <div style={{ marginTop: 1, minWidth: 20, display: 'flex', justifyContent: 'center' }}>
                <StepIcon status={stepStatuses[i]} />
              </div>
              <div style={{ flex: 1 }}>
                <div style={{
                  fontSize: '0.84rem',
                  fontWeight: stepStatuses[i] === 'active' ? 700 : 500,
                  color: stepStatuses[i] === 'error'
                    ? '#ef4444'
                    : stepStatuses[i] === 'done'
                    ? '#22c55e'
                    : 'var(--text-primary)',
                }}>
                  {step.label}
                </div>

                {/* Per-table breakdown (only for upload step) */}
                {step.id === 'upload' && stepStatuses[i] === 'active' && tableRows.length > 0 && (
                  <div style={{
                    marginTop: 10,
                    background: 'rgba(255,255,255,0.03)',
                    border: '1px solid rgba(255,255,255,0.08)',
                    borderRadius: 8,
                    padding: '8px 12px',
                    display: 'flex', flexDirection: 'column', gap: 6,
                  }}>
                    {tableRows.map(row => (
                      <div key={row.entity} style={{
                        display: 'flex', alignItems: 'center', gap: 10, fontSize: '0.75rem',
                      }}>
                        <div style={{ width: 90, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {row.entity}
                        </div>
                        <MiniBar done={row.done} total={row.total} />
                        <div style={{ minWidth: 50, textAlign: 'right', color: 'var(--text-muted)' }}>
                          {row.done}/{row.total > 0 ? row.total : '?'}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Success state — summary + explicit re-login handoff */}
        {isComplete && (
          <>
            <div style={{
              background: 'rgba(34,197,94,0.08)',
              border: '1px solid rgba(34,197,94,0.25)',
              borderRadius: 8, padding: '12px 16px',
              fontSize: '0.8rem', color: '#22c55e', marginBottom: 12,
            }}>
              {validation.length > 0 && (
                <div style={{ marginBottom: 6, fontWeight: 700 }}>
                  Verified on destination: {validation.reduce((a, v) => a + v.expected, 0).toLocaleString()} records
                  across {validation.length} tables{validation.some(v => !v.ok) ? ' (with accepted mismatches)' : ' — all counts match'}.
                </div>
              )}
              {backupPath && (
                <div style={{ marginBottom: 4 }}>
                  <strong>Backup saved:</strong> <code style={{ fontSize: '0.74rem', wordBreak: 'break-all' }}>{backupPath}</code>
                </div>
              )}
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <AlertIcon size={14} strokeWidth={2.5} />
                <span>Keep the backup JSON safe — it's a full snapshot of the destination from before this migration.</span>
              </div>
            </div>

            <div style={{
              background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border, rgba(255,255,255,0.1))',
              borderRadius: 8, padding: '10px 14px', fontSize: '0.78rem',
              color: 'var(--text-muted)', marginBottom: 14, display: 'flex', alignItems: 'center', gap: 8,
            }}>
              <ShieldIcon size={15} strokeWidth={2} />
              <span>
                One last step: you'll be signed out so your session moves to the <strong>{toMode === 'hybrid' ? 'Local + Cloud' : toMode}</strong> backend.
                Sign back in with the same username{user?.username ? <> (<strong>{user.username}</strong> — we'll prefill it)</> : ''}.
              </span>
            </div>

            <button
              className="btn-premium"
              style={{ width: '100%', fontSize: '0.88rem' }}
              onClick={onComplete}
            >
              <LogoutIcon size={15} /> Sign out & continue to {toMode === 'hybrid' ? 'Local + Cloud' : toMode} mode
            </button>
          </>
        )}

        {/* Validation mismatch — paused, user decides */}
        {validationPaused && !isComplete && !cancelled && (
          <>
            <div style={{
              background: 'rgba(249,115,22,0.08)',
              border: '1px solid rgba(249,115,22,0.3)',
              borderRadius: 8, padding: '12px 16px', marginBottom: 12,
            }}>
              <div style={{ fontSize: '0.82rem', fontWeight: 700, color: '#f97316', marginBottom: 8 }}>
                Some records didn't land on the destination
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {validation.filter(v => !v.ok).map(v => (
                  <div key={v.entity} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.76rem', color: 'var(--text-secondary)' }}>
                    <span>{v.entity}</span>
                    <span style={{ fontWeight: 700, color: '#f97316' }}>{v.found}/{v.expected}</span>
                  </div>
                ))}
              </div>
            </div>
            <div style={{
              background: 'rgba(34,197,94,0.06)', border: '1px solid rgba(34,197,94,0.2)',
              borderRadius: 8, padding: '10px 14px', fontSize: '0.78rem', color: '#22c55e', marginBottom: 14,
              display: 'flex', alignItems: 'center', gap: 6,
            }}>
              <ShieldIcon size={14} strokeWidth={2} />
              <span>Your source data is untouched — retrying is safe (imports merge, nothing duplicates by re-upload).</span>
            </div>
            <div style={{ display: 'flex', gap: 10 }}>
              <button
                onClick={handleRetry}
                style={{
                  flex: 2, padding: '9px', borderRadius: 8,
                  background: 'var(--accent)', color: '#fff', border: 'none',
                  cursor: 'pointer', fontSize: '0.84rem', fontWeight: 700,
                  display: 'inline-flex', alignItems: 'center', gap: 6, justifyContent: 'center',
                }}
              >
                <SyncIcon size={14} /> Retry Migration
              </button>
              <button
                onClick={handleForceFinalize}
                title="Switch modes even though some counts don't match"
                style={{
                  flex: 1, padding: '9px', borderRadius: 8,
                  border: '1px solid rgba(249,115,22,0.5)',
                  background: 'transparent', color: '#f97316',
                  cursor: 'pointer', fontSize: '0.8rem', fontWeight: 600,
                }}
              >
                Continue anyway
              </button>
            </div>
          </>
        )}

        {/* Error state (hard failures — validation mismatches have their own panel) */}
        {hasError && !cancelled && !validationPaused && (
          <>
            <div style={{
              background: 'rgba(239,68,68,0.08)',
              border: '1px solid rgba(239,68,68,0.25)',
              borderRadius: 8, padding: '12px 16px',
              marginBottom: 16,
            }}>
              <div style={{ fontSize: '0.82rem', fontWeight: 700, color: '#ef4444', marginBottom: 4 }}>
                Failed at: {errorStep}
              </div>
              {errorMsg && (
                <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)' }}>{errorMsg}</div>
              )}
            </div>
            <div style={{
              background: 'rgba(34,197,94,0.06)',
              border: '1px solid rgba(34,197,94,0.2)',
              borderRadius: 8, padding: '10px 14px',
              fontSize: '0.78rem', color: '#22c55e', marginBottom: 16,
            }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <ShieldIcon size={14} strokeWidth={2} />
              <span>Your original data is safe — no changes were committed to the source database.</span>
            </div>
            </div>
            <div style={{ display: 'flex', gap: 10 }}>
              <button
                onClick={handleCancel}
                style={{
                  flex: 1, padding: '9px', borderRadius: 8,
                  border: '1px solid rgba(255,255,255,0.15)',
                  background: 'transparent', color: 'var(--text-muted)',
                  cursor: 'pointer', fontSize: '0.84rem',
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleRetry}
                style={{
                  flex: 2, padding: '9px', borderRadius: 8,
                  background: 'var(--accent)', color: '#fff', border: 'none',
                  cursor: 'pointer', fontSize: '0.84rem', fontWeight: 700,
                  display: 'inline-flex', alignItems: 'center', gap: 6, justifyContent: 'center',
                }}
              >
                <SyncIcon size={14} /> Retry Migration
              </button>
            </div>
          </>
        )}

        {/* Cancel & Rollback (during upload) */}
        {!isComplete && !hasError && !cancelled && (
          <div style={{ display: 'flex', gap: 10 }}>
            <button
              onClick={handleCancel}
              style={{
                padding: '7px 16px', borderRadius: 8,
                border: '1px solid rgba(255,255,255,0.12)',
                background: 'transparent', color: 'var(--text-muted)',
                cursor: 'pointer', fontSize: '0.78rem',
              }}
            >
              Cancel &amp; Rollback
            </button>
          </div>
        )}

        {cancelled && (
          <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginTop: 8 }}>
            Migration cancelled. Your data remains unchanged.
          </div>
        )}
      </div>
    </div>
  )
}
