import React from 'react'

// Consequence definitions for each transition
const TRANSITIONS = {
  'local→cloud': {
    title: 'Move to Cloud Mode',
    icon: '☁️',
    bullets: [
      'Upload all local data to the cloud database',
      'Internet connection will be required for all future access',
      'Other devices will be able to see your data in real-time',
      'AI Insights and cloud backups will be enabled',
    ],
    danger: [],
    confirmLabel: 'Move to Cloud',
    confirmColor: '#22c55e',
  },
  'cloud→local': {
    title: 'Move to Local Mode',
    icon: '🖥️',
    bullets: [
      'Download a full copy of cloud data to this PC',
      'This device will become the single source of truth',
      'Other devices will lose access to the shared database',
      'AI Insights and cloud backups will be disabled',
    ],
    danger: ['Other devices lose access immediately after switch'],
    confirmLabel: 'Move to Local',
    confirmColor: '#f97316',
  },
  'local→hybrid': {
    title: 'Enable Hybrid Mode',
    icon: '🔄',
    bullets: [
      'Local database remains your primary POS (fast checkouts)',
      'Background sync agent will push transactions to cloud',
      'Cloud backups and AI Advisor will be enabled',
      'A one-time initial upload will happen now',
    ],
    danger: [],
    confirmLabel: 'Enable Hybrid',
    confirmColor: '#22c55e',
  },
  'cloud→hybrid': {
    title: 'Switch to Hybrid Mode',
    icon: '🔄',
    bullets: [
      'Cloud data will be pulled to a local cache on this PC',
      'Future writes go locally first, then sync to cloud',
      'Slight delay in cross-device visibility (eventual consistency)',
    ],
    danger: [],
    confirmLabel: 'Switch to Hybrid',
    confirmColor: '#22c55e',
  },
  'hybrid→cloud': {
    title: 'Move to Cloud-Only Mode',
    icon: '☁️',
    bullets: [
      'All writes will go directly to the cloud database',
      'Local cache will be cleared after migration',
      'Internet connection will be required for every operation',
      'AI Insights and real-time sync across devices enabled',
    ],
    danger: [],
    confirmLabel: 'Switch to Cloud Only',
    confirmColor: '#22c55e',
  },
  'hybrid→local': {
    title: 'Move to Local-Only Mode',
    icon: '🖥️',
    bullets: [
      'Local database becomes the sole source of truth',
      'Cloud sync will be permanently disabled on this device',
      'Other devices connected via hybrid mode will lose access',
      'AI Insights and cloud backups will be disabled',
    ],
    danger: [
      'Sync queue will be cleared — unsynced transactions may be lost',
      'Other devices lose access immediately after switch',
    ],
    confirmLabel: 'Move to Local Only',
    confirmColor: '#ef4444',
  },
}

export default function ConsequenceModal({ fromMode, toMode, onCancel, onConfirm }) {
  const key = `${fromMode}→${toMode}`
  const info = TRANSITIONS[key] || {
    title: `Switch to ${toMode} mode`,
    icon: '⚙️',
    bullets: ['Your hosting mode will be changed.'],
    danger: [],
    confirmLabel: 'Confirm',
    confirmColor: 'var(--accent)',
  }

  return (
    <div
      className="pf-backdrop"
      onMouseDown={onCancel}
    >
      <div
        className="pf-modal"
        style={{ maxWidth: 460 }}
        onMouseDown={e => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 18 }}>
          <span style={{ fontSize: 28 }}>{info.icon}</span>
          <div>
            <div style={{ fontSize: '1.05rem', fontWeight: 700, color: 'var(--text-primary)' }}>
              {info.title}
            </div>
            <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: 2 }}>
              Please review what will happen before continuing
            </div>
          </div>
        </div>

        {/* Normal bullets */}
        <ul style={{
          margin: '0 0 14px 0', padding: '0 0 0 20px',
          display: 'flex', flexDirection: 'column', gap: 6,
        }}>
          {info.bullets.map((b, i) => (
            <li key={i} style={{ fontSize: '0.84rem', color: 'var(--text-secondary, #222)', lineHeight: 1.5 }}>
              {b}
            </li>
          ))}
        </ul>

        {/* Danger bullets */}
        {info.danger.length > 0 && (
          <div style={{
            background: 'rgba(239,68,68,0.08)',
            border: '1px solid rgba(239,68,68,0.3)',
            borderRadius: 8,
            padding: '10px 14px',
            marginBottom: 16,
          }}>
            <div style={{ fontSize: '0.78rem', fontWeight: 700, color: '#ef4444', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
              ⚠️ Warning
            </div>
            <ul style={{ margin: 0, padding: '0 0 0 16px', display: 'flex', flexDirection: 'column', gap: 4 }}>
              {info.danger.map((d, i) => (
                <li key={i} style={{ fontSize: '0.8rem', color: '#ef4444', lineHeight: 1.5 }}>
                  {d}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Actions */}
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
          <button
            onClick={onCancel}
            style={{
              padding: '9px 18px', borderRadius: 8,
              border: '1px solid var(--border, rgba(255,255,255,0.15))',
              background: 'transparent', color: 'var(--text-muted)',
              cursor: 'pointer', fontSize: '0.84rem',
            }}
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            style={{
              padding: '9px 22px', borderRadius: 8,
              background: info.confirmColor, color: '#fff', border: 'none',
              cursor: 'pointer', fontSize: '0.84rem', fontWeight: 700,
            }}
          >
            {info.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
