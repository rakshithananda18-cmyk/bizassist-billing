import { API_BASE } from '../config'

/**
 * downloadBackupFile — save this business's full data export as a JSON file.
 *
 * Shared by the Settings backup card and the trial-ended screen, so the file a
 * web-only owner takes away when their trial ends is exactly the one "Restore
 * from file" in the desktop app expects. GET /api/data-transfer/export is never
 * plan-gated: taking your own data out is not a paid feature.
 *
 * Stamps `bizassist_last_file_backup` (read by the backup reminder) and returns
 * the file name. Throws on a failed export.
 */
export async function downloadBackupFile({ token, bizId = '' }) {
  const res = await fetch(`${API_BASE}/api/data-transfer/export`, {
    headers: { Authorization: `Bearer ${token}` },
  })
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
  return name
}
