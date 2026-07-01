import React, { useEffect } from 'react'
import { CheckIcon, CloseIcon, DownloadIcon, SyncIcon } from '../Icons'

// Which probes each mode needs
const MODE_REQUIREMENTS = {
  local:  { p1: true,  p2: false, p3: false },
  cloud:  { p1: false, p2: true,  p3: true  },
  hybrid: { p1: true,  p2: true,  p3: true  },
}

function statusColor(status) {
  switch (status) {
    case 'online':   return '#22c55e'
    case 'slow':     return '#f97316'
    case 'offline':  return '#ef4444'
    case 'cors':     return '#ef4444'
    case 'checking': return 'var(--text-muted)'
    default:         return 'var(--text-muted)'
  }
}

function CheckRow({ label, probe, required }) {
  if (!required) return null

  const isChecking = probe.status === 'checking'
  const isPassed   = probe.status === 'online' || probe.status === 'slow'
  const isFailed   = !isChecking && !isPassed

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12,
      padding: '10px 14px',
      borderRadius: 8,
      background: isChecking ? 'rgba(255,255,255,0.03)'
                : isPassed   ? 'rgba(34,197,94,0.08)'
                :               'rgba(239,68,68,0.08)',
      border: `1px solid ${isChecking ? 'rgba(255,255,255,0.1)'
                          : isPassed   ? 'rgba(34,197,94,0.25)'
                          :               'rgba(239,68,68,0.25)'}`,
      marginBottom: 8,
      transition: 'all 0.2s',
    }}>
      <div style={{ fontSize: 16, lineHeight: 1, minWidth: 24, display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
        {isChecking ? <span className="pf-spinner" /> : isPassed ? <CheckIcon size={16} strokeWidth={2.5} style={{ color: '#22c55e' }} /> : <CloseIcon size={16} strokeWidth={2.5} style={{ color: '#ef4444' }} />}
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: '0.84rem', fontWeight: 600, color: 'var(--text-primary)' }}>
          {label}
        </div>
        {probe.error && isFailed && (
          <div style={{ fontSize: '0.72rem', color: '#ef4444', marginTop: 2 }}>
            {probe.error}
          </div>
        )}
        {probe.status === 'slow' && (
          <div style={{ fontSize: '0.72rem', color: '#f97316', marginTop: 2 }}>
            Slow connection ({probe.ms}ms) — may impact performance
          </div>
        )}
        {probe.status === 'cors' && (
          <div style={{ fontSize: '0.72rem', color: '#ef4444', marginTop: 2 }}>
            Browser blocked access to local app (mixed-content)
          </div>
        )}
      </div>
      {!isChecking && (
        <div style={{
          fontSize: '0.78rem', fontWeight: 700,
          color: statusColor(probe.status),
        }}>
          {isPassed
            ? probe.ms != null ? `${probe.ms}ms` : 'OK'
            : probe.status === 'cors' ? 'BLOCKED' : 'FAIL'
          }
        </div>
      )}
    </div>
  )
}

export default function PreflightModal({
  targetMode,
  localProbe,
  cloudProbe,
  internetProbe,
  onClose,
  onProceed,
}) {
  const req = MODE_REQUIREMENTS[targetMode] || {}

  // Derive aggregate states
  const checks = [
    req.p1 && localProbe,
    req.p2 && cloudProbe,
    req.p3 && internetProbe,
  ].filter(Boolean)

  const isChecking  = checks.some(p => p.status === 'checking')
  const hasCorBlock  = checks.some(p => p.status === 'cors')
  const hasFail      = checks.some(p => p.status === 'offline')
  const allPass      = !isChecking && !hasCorBlock && !hasFail

  // Auto-proceed when all pass
  useEffect(() => {
    if (allPass) {
      // Give user a moment to see the green ticks
      const t = setTimeout(onProceed, 600)
      return () => clearTimeout(t)
    }
  }, [allPass, onProceed])

  const modeLabel = {
    local:  'Local Mode',
    cloud:  'Cloud Mode',
    hybrid: 'Hybrid Mode',
  }[targetMode] || targetMode

  return (
    <div
      className="pf-backdrop"
      onMouseDown={(e) => {
        // Block close while checking
        if (!isChecking) onClose()
      }}
    >
      <div
        className="pf-modal"
        onMouseDown={e => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: '1.05rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: 4 }}>
            Switch to {modeLabel}
          </div>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            Running preflight checks…
          </div>
        </div>

        {/* Check rows */}
        <CheckRow label="Local Backend (P1)"  probe={localProbe}    required={req.p1} />
        <CheckRow label="Cloud Backend (P2)"  probe={cloudProbe}    required={req.p2} />
        <CheckRow label="Internet Access (P3)" probe={internetProbe} required={req.p3} />

        {/* Action area */}
        <div style={{ marginTop: 20, display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          {isChecking && (
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', alignSelf: 'center' }}>
              Checking connectivity…
            </div>
          )}

          {hasCorBlock && !isChecking && (
            <>
              <button
                onClick={onClose}
                style={{
                  padding: '9px 18px', borderRadius: 8, border: '1px solid var(--border, rgba(255,255,255,0.15))',
                  background: 'transparent', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '0.84rem',
                }}
              >
                Close
              </button>
              <a
                href="https://github.com/rakshithananda18-cmyk/bizassist-billing/releases"
                target="_blank"
                rel="noreferrer"
                style={{
                  padding: '9px 18px', borderRadius: 8,
                  background: 'var(--accent)', color: '#fff', border: 'none',
                  cursor: 'pointer', fontSize: '0.84rem', fontWeight: 600,
                  textDecoration: 'none',
                  display: 'inline-flex', alignItems: 'center', gap: 6,
                }}
              >
                <DownloadIcon size={14} /> Download Desktop App
              </a>
            </>
          )}

          {hasFail && !isChecking && !hasCorBlock && (
            <>
              <button
                onClick={onClose}
                style={{
                  padding: '9px 18px', borderRadius: 8, border: '1px solid var(--border, rgba(255,255,255,0.15))',
                  background: 'transparent', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '0.84rem',
                }}
              >
                Cancel
              </button>
              <button
                onClick={onClose}
                style={{
                  padding: '9px 20px', borderRadius: 8,
                  background: 'var(--accent)', color: '#fff', border: 'none',
                  cursor: 'pointer', fontSize: '0.84rem', fontWeight: 600,
                  display: 'inline-flex', alignItems: 'center', gap: 6,
                }}
              >
                <SyncIcon size={14} /> Retry All
              </button>
            </>
          )}

          {allPass && (
            <button
              onClick={onProceed}
              style={{
                padding: '9px 20px', borderRadius: 8,
                background: '#22c55e', color: '#fff', border: 'none',
                cursor: 'pointer', fontSize: '0.84rem', fontWeight: 700,
              }}
            >
              Continue →
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
