import React, { useState, useEffect } from 'react'
import { MonitorIcon, CloudIcon, SyncIcon, SettingsIcon, AlertIcon } from '../Icons'
import { CLOUD_URL } from '../../config'
import { logger } from '../../utils/logger'

// Consequence definitions for each transition
const TRANSITIONS = {
  'local→cloud': {
    title: 'Move to Cloud Mode',
    iconType: 'cloud',
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
    iconType: 'local',
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
    title: 'Enable Local + Cloud',
    iconType: 'hybrid',
    bullets: [
      'Local database remains your primary POS (fast checkouts)',
      'Background sync agent will push transactions to cloud',
      'Cloud backups and AI Advisor will be enabled',
      'A one-time initial upload will happen now',
    ],
    danger: [],
    confirmLabel: 'Enable Local + Cloud',
    confirmColor: '#22c55e',
  },
  'cloud→hybrid': {
    title: 'Switch to Local + Cloud',
    iconType: 'hybrid',
    bullets: [
      'Cloud data will be pulled to a local cache on this PC',
      'Future writes go locally first, then sync to cloud',
      'Slight delay in cross-device visibility (eventual consistency)',
    ],
    danger: [],
    confirmLabel: 'Switch to Local + Cloud',
    confirmColor: '#22c55e',
  },
  'hybrid→cloud': {
    title: 'Move to Cloud-Only Mode',
    iconType: 'cloud',
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
    iconType: 'local',
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

export default function ConsequenceModal({ fromMode, toMode, onCancel, onConfirm, onSyncFirst }) {
  const key = `${fromMode}→${toMode}`
  const info = TRANSITIONS[key] || {
    title: `Switch to ${toMode} mode`,
    iconType: 'default',
    bullets: ['Your hosting mode will be changed.'],
    danger: [],
    confirmLabel: 'Confirm',
    confirmColor: 'var(--accent)',
  }

  const [cloudCount, setCloudCount] = useState(null)
  const [loadingCloudCheck, setLoadingCloudCheck] = useState(false)

  useEffect(() => {
    if (fromMode === 'local' && (toMode === 'hybrid' || toMode === 'cloud')) {
      const cloudToken = localStorage.getItem('bizassist_cloud_token')
      if (!cloudToken) return

      setLoadingCloudCheck(true)
      fetch(`${CLOUD_URL}/api/data-transfer/count`, {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${cloudToken}`
        }
      })
      .then(res => res.ok ? res.json() : null)
      .then(counts => {
        if (counts) {
          const total = Object.values(counts).reduce((a, n) => a + (Number(n) > 0 ? Number(n) : 0), 0)
          if (total > 0) {
            setCloudCount(total)
          }
        }
      })
      .catch(err => logger.warn('Failed to check cloud count during pre-switch check:', err))
      .finally(() => setLoadingCloudCheck(false))
    }
  }, [fromMode, toMode])

  const getIcon = (type) => {
    switch (type) {
      case 'cloud':  return <CloudIcon size={24} />
      case 'local':  return <MonitorIcon size={24} />
      case 'hybrid': return <SyncIcon size={24} />
      default:       return <SettingsIcon size={24} />
    }
  }

  return (
    <div
      className="pf-backdrop"
      onMouseDown={onCancel}
      style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', position: 'fixed', inset: 0, zIndex: 9999, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(8px)' }}
    >
      <div
        className="pf-modal"
        style={{ maxWidth: 480, background: 'var(--bg-2, #181818)', border: '1px solid var(--border, rgba(255,255,255,0.12))', borderRadius: 16, padding: '26px 30px', boxShadow: '0 24px 80px rgba(0,0,0,0.5)' }}
        onMouseDown={e => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 18 }}>
          <span style={{ color: 'var(--accent)', display: 'flex', alignItems: 'center' }}>{getIcon(info.iconType)}</span>
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
            <li key={i} style={{ fontSize: '0.84rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              {b}
            </li>
          ))}
        </ul>

        {/* Cloud data warning / sync option box */}
        {cloudCount !== null && (
          <div style={{
            background: 'rgba(79, 70, 229, 0.08)',
            border: '1px solid rgba(79, 70, 229, 0.3)',
            borderRadius: 8,
            padding: '12px 14px',
            marginBottom: 16,
          }}>
            <div style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--accent, #4f46e5)', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6 }} className="text-premium">
              <CloudIcon size={14} /> Existing Cloud Data Detected
            </div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', lineHeight: 1.5, marginBottom: 10 }}>
              We found <strong>{cloudCount} records</strong> in your cloud account. Working locally should align with your cloud data. We recommend pulling this cloud data to your local machine first before switching.
            </div>
            <button
              onClick={onSyncFirst}
              style={{
                width: '100%',
                padding: '8px 12px',
                borderRadius: 6,
                background: 'var(--accent, #4f46e5)',
                color: '#fff',
                border: 'none',
                cursor: 'pointer',
                fontSize: '0.8rem',
                fontWeight: 700,
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 6
              }}
            >
              <SyncIcon size={12} /> Sync Cloud → Local First
            </button>
          </div>
        )}

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
              <AlertIcon size={14} strokeWidth={2.5} /> Warning
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
