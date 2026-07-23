// components/hosting/FileBackupCard.jsx — offline file backup & restore.
// ======================================================================
// REVIEW_1 GAP-6: local-only merchants previously had ZERO disaster recovery —
// a dead disk meant lost books. This card gives every install (local, hybrid,
// cloud) a one-tap "Download backup file" (full JSON export of this business's
// data via GET /api/data-transfer/export) and a "Restore from file" that
// replays it through POST /api/data-transfer/import?merge=true — the same
// battle-tested non-destructive Last-Write-Wins merge the cloud sync uses, so
// a restore can never clobber newer local rows.
import React, { useState, useRef } from 'react'
import { API_BASE } from '../../config'
import { logger } from '../../utils/logger'
import { ShieldIcon } from '../Icons'
import { useConfirm } from '../../contexts/ConfirmContext'

export default function FileBackupCard({ token, bizId = '' }) {
  const confirm = useConfirm()
  const [busy, setBusy] = useState(null)          // 'backup' | 'restore' | null
  const [msg, setMsg] = useState(null)            // { ok, text }
  const fileRef = useRef(null)

  const headers = { Authorization: `Bearer ${token}` }

  async function downloadBackup() {
    setBusy('backup'); setMsg(null)
    try {
      const res = await fetch(`${API_BASE}/api/data-transfer/export`, { headers })
      if (!res.ok) throw new Error(`Export failed: HTTP ${res.status}`)
      const data = await res.json()
      const stamp = new Date().toISOString().slice(0, 10)
      const name = `bizassist-backup-${(bizId || 'business').toLowerCase()}-${stamp}.json`
      const blob = new Blob([JSON.stringify(data)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = name
      document.body.appendChild(a); a.click(); a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 5000)
      try { localStorage.setItem('bizassist_last_file_backup', new Date().toISOString()) } catch { /* ignore */ }
      setMsg({ ok: true, text: `Backup saved as ${name}. Keep a copy somewhere safe (pen drive / Google Drive).` })
    } catch (err) {
      logger.error('[BACKUP] file backup failed:', err)
      setMsg({ ok: false, text: err.message || 'Backup failed — please try again.' })
    } finally {
      setBusy(null)
    }
  }

  async function restoreFromFile(e) {
    const file = e.target.files?.[0]
    e.target.value = ''                            // allow re-selecting the same file
    if (!file) return
    const ok = await confirm({
      mode: 'update',
      title: 'Restore backup?',
      entity: file.name,
      message: 'This merges the backup into this device — newer records here are kept, nothing is deleted.',
      confirmText: 'Restore',
    })
    if (!ok) return
    setBusy('restore'); setMsg(null)
    try {
      const text = await file.text()
      let payload
      try { payload = JSON.parse(text) } catch { throw new Error('That file is not a valid BizAssist backup (.json).') }
      const res = await fetch(`${API_BASE}/api/data-transfer/import?merge=true&remap_ids=true`, {
        method: 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || `Restore failed: HTTP ${res.status}`)
      }
      const out = await res.json().catch(() => ({}))
      setMsg({ ok: true, text: out.message || 'Restore complete — backup merged into this device.' })
    } catch (err) {
      logger.error('[BACKUP] restore failed:', err)
      setMsg({ ok: false, text: err.message || 'Restore failed — please try again.' })
    } finally {
      setBusy(null)
    }
  }

  const lastBackup = (() => {
    try {
      const iso = localStorage.getItem('bizassist_last_file_backup')
      return iso ? new Date(iso).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' }) : null
    } catch { return null }
  })()

  const btnStyle = (primary) => ({
    flexShrink: 0, padding: '8px 14px', borderRadius: 8,
    background: primary ? 'var(--accent)' : 'rgba(255,255,255,0.06)',
    color: primary ? '#fff' : 'var(--text-primary)',
    border: primary ? 'none' : '1px solid rgba(255,255,255,0.14)',
    cursor: busy ? 'wait' : 'pointer', fontSize: '0.8rem', fontWeight: 700,
    display: 'inline-flex', alignItems: 'center', gap: 6, opacity: busy ? 0.7 : 1,
  })

  return (
    <div style={{
      marginTop: 14, padding: '12px 14px', borderRadius: 10,
      background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)',
    }}>
      <div style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 6 }}>
        <ShieldIcon size={15} /> Backup to file
      </div>
      <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', lineHeight: 1.5, marginBottom: 10 }}>
        Download a complete copy of your business data as one file — your insurance against a
        dead hard disk or a lost laptop. Restoring merges the file back in (newer records win, nothing is deleted).
        {lastBackup && <span> Last file backup: <b>{lastBackup}</b>.</span>}
      </div>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <button onClick={downloadBackup} disabled={!!busy} style={btnStyle(true)}>
          {busy === 'backup' ? 'Preparing…' : 'Download backup file'}
        </button>
        <button onClick={() => fileRef.current?.click()} disabled={!!busy} style={btnStyle(false)}>
          {busy === 'restore' ? 'Restoring…' : 'Restore from file'}
        </button>
        <input ref={fileRef} type="file" accept=".json,application/json" onChange={restoreFromFile} style={{ display: 'none' }} />
      </div>
      {msg && (
        <div style={{ marginTop: 8, fontSize: '0.74rem', fontWeight: 600, color: msg.ok ? '#22c55e' : '#ef4444' }}>
          {msg.ok ? '✓ ' : ''}{msg.text}
        </div>
      )}
    </div>
  )
}
