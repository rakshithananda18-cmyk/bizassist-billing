/**
 * backupOverdue — is it time to take another offline backup?
 *
 * `auto_backup` and `backup_reminder_days` have existed in Settings, been
 * persisted by the backend, and been covered by a test that they round-trip —
 * while NOTHING anywhere read them to actually remind anyone. A toggle labelled
 * "periodically request backup files" that has never once asked for one.
 *
 * Everything needed was already there: `FileBackupCard` stamps
 * `bizassist_last_file_backup` on every download. This is the missing half.
 *
 * Deliberately client-side. The timestamp is per DEVICE, because the backup file
 * lands on that device's disk — a backup taken on the counter PC says nothing
 * about whether the back-office machine has one. A server-side "last backup"
 * would average away exactly the risk this guards: the one machine that never
 * backs up is the one whose disk dies.
 *
 * Returns null when nothing is due, or { days, never } describing the gap.
 */
export function backupOverdue({ autoBackup, reminderDays, lastBackupIso, now = Date.now() }) {
  // The toggle is the owner's decision, and off means off. This is a reminder,
  // not an opinion about how they should run their shop.
  if (!autoBackup) return null

  const days = Number(reminderDays) > 0 ? Number(reminderDays) : 7

  // No stamp, or a stamp we cannot read, both mean the same thing: there is no
  // backup we can point at. Treated as overdue rather than quietly passing —
  // "I don't know" must not render as "you're covered".
  const ts = lastBackupIso ? Date.parse(lastBackupIso) : NaN
  if (Number.isNaN(ts)) return { days: null, never: true }

  const elapsed = Math.floor((now - ts) / 86400000)
  // `>=`: a 7-day reminder fires ON day 7, not on day 8.
  return elapsed >= days ? { days: elapsed, never: false } : null
}
