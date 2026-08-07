// The backup reminder that never reminded anyone.
//
// `auto_backup` and `backup_reminder_days` have been in Settings, persisted by
// the backend, and covered by a round-trip test — while nothing anywhere read
// them. A toggle reading "periodically request backup files" that had never
// once asked. `FileBackupCard` was already stamping every download; this is the
// half that was missing.
import { describe, it, expect } from 'vitest'
import { backupOverdue } from '../utils/backupReminder'

const DAY = 86400000
const NOW = Date.parse('2026-08-07T12:00:00Z')
const ago = (d) => new Date(NOW - d * DAY).toISOString()

describe('backupOverdue', () => {
  it('says nothing when the owner turned it off', () => {
    // Off means off. This is a reminder, not an opinion about how they run the
    // shop — and a nag you cannot silence is one people learn to ignore.
    expect(backupOverdue({
      autoBackup: false, reminderDays: 7, lastBackupIso: ago(400), now: NOW,
    })).toBeNull()
  })

  it('stays quiet while the last backup is recent', () => {
    expect(backupOverdue({
      autoBackup: true, reminderDays: 7, lastBackupIso: ago(3), now: NOW,
    })).toBeNull()
  })

  it('fires ON the reminder day, not the day after', () => {
    // A 7-day reminder that first speaks on day 8 is a 8-day reminder.
    expect(backupOverdue({
      autoBackup: true, reminderDays: 7, lastBackupIso: ago(7), now: NOW,
    })).toEqual({ days: 7, never: false })
  })

  it('treats a device that has never backed up as overdue', () => {
    // The whole point is the machine whose disk dies. "No backup at all" is the
    // worst case, so it cannot be the quiet case.
    expect(backupOverdue({
      autoBackup: true, reminderDays: 7, lastBackupIso: null, now: NOW,
    })).toEqual({ days: null, never: true })
  })

  it('treats an unreadable timestamp as no backup', () => {
    // "I cannot tell" must never render as "you are covered".
    expect(backupOverdue({
      autoBackup: true, reminderDays: 7, lastBackupIso: 'not-a-date', now: NOW,
    })).toEqual({ days: null, never: true })
  })

  it('falls back to 7 days when the interval is missing or nonsense', () => {
    for (const bad of [undefined, null, 0, -3, 'abc']) {
      expect(backupOverdue({
        autoBackup: true, reminderDays: bad, lastBackupIso: ago(8), now: NOW,
      }), `reminderDays=${bad}`).toEqual({ days: 8, never: false })
      expect(backupOverdue({
        autoBackup: true, reminderDays: bad, lastBackupIso: ago(2), now: NOW,
      }), `reminderDays=${bad}`).toBeNull()
    }
  })

  it('honours a longer interval the owner chose', () => {
    expect(backupOverdue({
      autoBackup: true, reminderDays: 30, lastBackupIso: ago(20), now: NOW,
    })).toBeNull()
    expect(backupOverdue({
      autoBackup: true, reminderDays: 30, lastBackupIso: ago(31), now: NOW,
    })).toEqual({ days: 31, never: false })
  })
})
