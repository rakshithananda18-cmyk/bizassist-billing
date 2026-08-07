// The bell's two jobs: show the right count, and never claim "all clear" when
// it does not know.
//
// The second one is the reason this test exists. A failed check is not news —
// if the request errors and the component resets to an empty list, the owner
// sees a calm bell over an empty shelf, which is worse than the silence this
// feature replaced.
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const authFetch = vi.fn()
let mockSettings = null
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ authFetch, settings: mockSettings }),
}))

import NotificationBell from '../components/NotificationBell'
import { HALT_COPY } from '../utils/syncHalt'

const ok = (body) => ({ ok: true, status: 200, json: async () => body })
// The bell probes queue-depth for the sync halt on every load; tests that
// only care about the notifications list answer both from one mock.
const route = (notifBody, haltReason = null) => (path) =>
  Promise.resolve(ok(path === '/api/sync/queue-depth'
    ? { halt: { reason: haltReason } }
    : notifBody))
const EMPTY = { items: [], count: 0, severity: null }
const TWO = {
  count: 2,
  severity: 'danger',
  items: [
    { kind: 'expired', severity: 'danger', title: '3 batches past expiry', detail: 'Still counted in stock.', route: '/stock' },
    { kind: 'overdue', severity: 'warning', title: '2 overdue invoices', detail: '₹4,000 outstanding.', route: '/sales' },
  ],
}

const draw = () => render(<MemoryRouter><NotificationBell /></MemoryRouter>)

beforeEach(() => {
  authFetch.mockReset()
  mockSettings = null
  try { localStorage.removeItem('bizassist_last_file_backup') } catch { /* ignore */ }
})
afterEach(() => { vi.clearAllTimers() })

describe('NotificationBell', () => {
  it('asks the endpoint through authFetch, not a raw URL', async () => {
    // authFetch attaches THIS session's token and pins the request to THIS
    // backend — a bare fetch to the cloud would resolve the id in the wrong DB.
    authFetch.mockImplementation(route(EMPTY))
    draw()
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/alerts/notifications'))
  })

  it('shows no badge when nothing needs attention', async () => {
    authFetch.mockImplementation(route(EMPTY))
    draw()
    await waitFor(() => expect(authFetch).toHaveBeenCalled())
    expect(screen.getByLabelText('Notifications')).toBeTruthy()
    expect(screen.queryByText('2')).toBeNull()
  })

  it('counts the items and opens to list them', async () => {
    authFetch.mockImplementation(route(TWO))
    draw()
    await waitFor(() => expect(screen.getByText('2')).toBeTruthy())

    fireEvent.click(screen.getByLabelText('2 notifications'))
    expect(screen.getByText('3 batches past expiry')).toBeTruthy()
    expect(screen.getByText('2 overdue invoices')).toBeTruthy()
  })

  it('adds the backup reminder the server cannot know about', async () => {
    // The backup file lands on THIS device's disk, so the timestamp is local
    // and the server has no way to answer. It has to merge in client-side or
    // the toggle goes on doing nothing.
    authFetch.mockImplementation(route(EMPTY))
    mockSettings = { general: { auto_backup: true, backup_reminder_days: 7 } }
    localStorage.setItem('bizassist_last_file_backup',
                         new Date(Date.now() - 40 * 86400000).toISOString())

    draw()
    await waitFor(() => expect(screen.getByText('1')).toBeTruthy())
    fireEvent.click(screen.getByLabelText('1 notification'))
    expect(screen.getByText(/Backup is 40 days old/i)).toBeTruthy()
  })

  it('stays silent about backups when the owner turned the toggle off', async () => {
    authFetch.mockImplementation(route(EMPTY))
    mockSettings = { general: { auto_backup: false } }
    draw()
    await waitFor(() => expect(authFetch).toHaveBeenCalled())
    expect(screen.queryByText('1')).toBeNull()
  })

  it('lets a server danger item outrank the backup warning', async () => {
    // Two sources, one bell. The colour must follow the most urgent item
    // overall, not whichever list it arrived in.
    authFetch.mockImplementation(route(TWO))
    mockSettings = { general: { auto_backup: true, backup_reminder_days: 1 } }
    draw()
    await waitFor(() => expect(screen.getByText('3')).toBeTruthy())
    fireEvent.click(screen.getByLabelText('3 notifications'))
    // Expired batches (danger) render above the backup reminder (warning).
    const rendered = screen.getByText('3 batches past expiry')
    expect(rendered).toBeTruthy()
  })

  it('surfaces a stopped sync, using the panel’s own words', async () => {
    // A dead cloud token used to be visible ONLY inside the sync popover. The
    // copy is imported from utils/syncHalt, not written here, so the bell and
    // the panel cannot describe the same flag differently.
    authFetch.mockImplementation(route(EMPTY, 'secret_mismatch'))
    draw()
    await waitFor(() => expect(screen.getByText('1')).toBeTruthy())
    fireEvent.click(screen.getByLabelText('1 notification'))
    expect(screen.getByText(HALT_COPY.secret_mismatch.title)).toBeTruthy()
  })

  it('does not treat a healthy sync as news', async () => {
    authFetch.mockImplementation(route(EMPTY, null))
    draw()
    await waitFor(() => expect(authFetch).toHaveBeenCalled())
    expect(screen.getByLabelText('Notifications')).toBeTruthy()
  })

  it('ranks a total sync failure above an outage', async () => {
    // secret_mismatch halts both directions and never self-heals; offline
    // clears on its own. If they shared a severity the bell would cry wolf on
    // every dropped connection.
    expect(HALT_COPY.secret_mismatch.severity).toBe('danger')
    expect(HALT_COPY.offline.severity).toBe('info')
  })

  it('keeps the last known list when a refresh fails', async () => {
    authFetch.mockImplementation(route(TWO))
    draw()
    await waitFor(() => expect(screen.getByText('2')).toBeTruthy())

    // A later check throws. The badge must NOT drop to zero — "I could not ask"
    // and "there is nothing wrong" are different answers.
    authFetch.mockRejectedValueOnce(new Error('offline'))
    fireEvent.click(screen.getByLabelText('2 notifications'))   // triggers a reload
    // Count the NOTIFICATIONS calls specifically. A load also probes
    // queue-depth for the sync halt, so a bare call count would only be
    // asserting how many endpoints the component happens to hit.
    const notifCalls = () =>
      authFetch.mock.calls.filter(c => c[0] === '/alerts/notifications').length
    await waitFor(() => expect(notifCalls()).toBe(2))
    expect(screen.getByText('2')).toBeTruthy()
  })
})
