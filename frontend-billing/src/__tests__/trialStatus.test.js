// The signup Pro trial, as the app reads it off settings.subscription.
//
// Two mistakes this guards: treating a lapsed trial like an account that was
// always free (the owner's data is in the cloud — they need to hear "your trial
// ended", not "your data is on your desktop"), and a reminder that either never
// shows or never goes away.
import { describe, it, expect } from 'vitest'
import {
  trialState, trialReminders, daysLeftText, TRIAL_ENDED_NOTICE_DAYS,
} from '../utils/trialStatus'

const DAY = 86400000
const NOW = Date.parse('2026-10-23T10:00:00Z')
const END = Date.parse('2026-11-07T00:00:00Z')   // expires_at 2026-11-06 runs to the end of that day
const sub = (over = {}) => ({
  plan: 'pro', status: 'trial', trial: true,
  expires_at: '2026-11-06', ends_at: '2026-11-07T00:00:00Z', ...over,
})

describe('trialState', () => {
  it('is null for an account that never had a trial', () => {
    expect(trialState(null)).toBeNull()
    expect(trialState({ plan: 'free', status: 'none', trial: false })).toBeNull()
  })

  it('is null once the trial became a paid plan', () => {
    expect(trialState({ plan: 'pro', status: 'active', trial: false, expires_at: '2027-10-23' })).toBeNull()
  })

  it('counts whole days left to the exact end', () => {
    expect(trialState(sub(), NOW)).toMatchObject({ active: true, daysLeft: 14 })
  })

  it('says 0 days on the last day', () => {
    expect(trialState(sub(), END - 4 * 3600000).daysLeft).toBe(0)
  })

  it('reads a date-only end from an older backend as the end of that day', () => {
    expect(trialState(sub({ ends_at: undefined, trial: undefined }), NOW).daysLeft).toBe(14)
  })

  it('marks a lapsed trial as ended and counts the days since', () => {
    expect(trialState(sub({ plan: 'free' }), END + 2 * DAY + 3600000))
      .toMatchObject({ active: false, daysLeft: 0, daysSinceEnd: 2 })
  })
})

describe('daysLeftText', () => {
  it('reads naturally', () => {
    expect(daysLeftText(14)).toBe('14 days left')
    expect(daysLeftText(1)).toBe('1 day left')
    expect(daysLeftText(0)).toBe('ends today')
  })
})

describe('trialReminders', () => {
  it('shows the days left for the whole trial, quietly at first', () => {
    const [item] = trialReminders(trialState(sub(), NOW), { isLocalApp: true })
    expect(item).toMatchObject({ kind: 'trial', severity: 'info', title: 'Pro trial: 14 days left' })
  })

  it('gets louder in the last three days, loudest on the last', () => {
    const at = (ms) => trialReminders(trialState(sub(), ms), { isLocalApp: true })[0]
    expect(at(END - 3 * DAY).severity).toBe('warning')
    expect(at(END - 3600000)).toMatchObject({ severity: 'danger', title: 'Your Pro trial ends today' })
  })

  it('points web users to the desktop app while the trial lasts', () => {
    const items = trialReminders(trialState(sub(), NOW), { isLocalApp: false, downloadUrl: 'https://example.test/releases' })
    expect(items.map(i => i.kind)).toEqual(['trial', 'trial:desktop'])
    expect(items[1].href).toBe('https://example.test/releases')
  })

  it('does not offer the desktop app inside the desktop app', () => {
    const items = trialReminders(trialState(sub(), NOW), { isLocalApp: true, downloadUrl: 'https://example.test/releases' })
    expect(items).toHaveLength(1)
  })

  it('says the trial ended, then drops it after a week', () => {
    const ended = (daysAfter) => trialReminders(
      trialState(sub({ plan: 'free' }), END + daysAfter * DAY + 3600000),
      { isLocalApp: false },
    )
    expect(ended(0)[0]).toMatchObject({
      kind: 'trial', title: 'Your Pro trial has ended', route: '/settings?tab=advanced',
    })
    expect(ended(TRIAL_ENDED_NOTICE_DAYS - 1)).toHaveLength(1)
    expect(ended(TRIAL_ENDED_NOTICE_DAYS)).toEqual([])
  })

  it('sends the desktop to the plan row, not the backup file, after the trial', () => {
    const [item] = trialReminders(trialState(sub({ plan: 'free' }), END + 3600000), { isLocalApp: true })
    expect(item.route).toBe('/settings?tab=general')
  })

  it('is empty without a trial', () => {
    expect(trialReminders(null)).toEqual([])
  })
})
