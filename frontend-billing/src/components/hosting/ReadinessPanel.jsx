import React from 'react'

const CLOUD_URL =
  import.meta.env.VITE_API_URL || 'https://rakshit-dev-bizassist.hf.space'

const LOCAL_URL = 'http://localhost:8000'

function StatusDot({ status }) {
  const classMap = {
    checking: 'rp-dot rp-dot--checking',
    online:   'rp-dot rp-dot--online',
    slow:     'rp-dot rp-dot--slow',
    offline:  'rp-dot rp-dot--offline',
    cors:     'rp-dot rp-dot--offline',
  }
  return <span className={classMap[status] || classMap.checking} />
}

function statusLabel(probe) {
  switch (probe.status) {
    case 'checking': return 'Checking…'
    case 'online':   return probe.ms != null ? `Online (${probe.ms}ms)` : 'Online'
    case 'slow':     return probe.ms != null ? `Slow (${probe.ms}ms)` : 'Slow'
    case 'offline':  return 'Offline'
    case 'cors':     return 'Blocked (CORS)'
    default:         return '—'
  }
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

function ProbeRow({ label, sublabel, probe }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10,
      padding: '6px 0',
      borderBottom: '1px solid rgba(255,255,255,0.06)',
    }}>
      <StatusDot status={probe.status} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-primary)' }}>
          {label}
        </div>
        {sublabel && (
          <div style={{
            fontSize: '0.72rem',
            color: 'var(--text-muted)',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {sublabel}
          </div>
        )}
      </div>
      <div style={{
        fontSize: '0.78rem',
        fontWeight: 600,
        color: statusColor(probe.status),
        whiteSpace: 'nowrap',
      }}>
        {statusLabel(probe)}
      </div>
    </div>
  )
}

export default function ReadinessPanel({ localProbe, cloudProbe, internetProbe, onRecheck }) {
  const now = new Date()
  const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })

  return (
    <div style={{
      background: 'rgba(255,255,255,0.03)',
      border: '1px solid var(--border-color, rgba(255,255,255,0.1))',
      borderRadius: 12,
      padding: '14px 16px',
      marginBottom: 20,
      backdropFilter: 'blur(8px)',
      position: 'relative',
    }}>
      {/* Header row */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 10,
      }}>
        <div style={{ fontSize: '0.76rem', fontWeight: 700, color: 'var(--accent)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
          Connection Status
        </div>
        <button
          onClick={onRecheck}
          title="Recheck now"
          style={{
            background: 'transparent',
            border: '1px solid var(--border-color, rgba(255,255,255,0.15))',
            borderRadius: 6,
            color: 'var(--text-muted)',
            fontSize: '0.76rem',
            padding: '3px 10px',
            cursor: 'pointer',
            display: 'flex', alignItems: 'center', gap: 5,
          }}
        >
          ↻ Recheck
        </button>
      </div>

      <ProbeRow
        label="Internet"
        sublabel="dns.google"
        probe={internetProbe}
      />
      <ProbeRow
        label="Local Backend"
        sublabel={LOCAL_URL}
        probe={localProbe}
      />
      <ProbeRow
        label="Cloud Backend"
        sublabel={CLOUD_URL}
        probe={cloudProbe}
      />

      {/* Last checked */}
      <div style={{
        marginTop: 8,
        fontSize: '0.7rem',
        color: 'var(--text-muted)',
        textAlign: 'right',
        opacity: 0.7,
      }}>
        Last checked: {timeStr}
      </div>
    </div>
  )
}
