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
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ authFetch }),
}))

import NotificationBell from '../components/NotificationBell'

const ok = (body) => ({ ok: true, status: 200, json: async () => body })
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

beforeEach(() => { authFetch.mockReset() })
afterEach(() => { vi.clearAllTimers() })

describe('NotificationBell', () => {
  it('asks the endpoint through authFetch, not a raw URL', async () => {
    // authFetch attaches THIS session's token and pins the request to THIS
    // backend — a bare fetch to the cloud would resolve the id in the wrong DB.
    authFetch.mockResolvedValue(ok(EMPTY))
    draw()
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/alerts/notifications'))
  })

  it('shows no badge when nothing needs attention', async () => {
    authFetch.mockResolvedValue(ok(EMPTY))
    draw()
    await waitFor(() => expect(authFetch).toHaveBeenCalled())
    expect(screen.getByLabelText('Notifications')).toBeTruthy()
    expect(screen.queryByText('2')).toBeNull()
  })

  it('counts the items and opens to list them', async () => {
    authFetch.mockResolvedValue(ok(TWO))
    draw()
    await waitFor(() => expect(screen.getByText('2')).toBeTruthy())

    fireEvent.click(screen.getByLabelText('2 notifications'))
    expect(screen.getByText('3 batches past expiry')).toBeTruthy()
    expect(screen.getByText('2 overdue invoices')).toBeTruthy()
  })

  it('keeps the last known list when a refresh fails', async () => {
    authFetch.mockResolvedValueOnce(ok(TWO))
    draw()
    await waitFor(() => expect(screen.getByText('2')).toBeTruthy())

    // A later check throws. The badge must NOT drop to zero — "I could not ask"
    // and "there is nothing wrong" are different answers.
    authFetch.mockRejectedValueOnce(new Error('offline'))
    fireEvent.click(screen.getByLabelText('2 notifications'))   // triggers a reload
    await waitFor(() => expect(authFetch).toHaveBeenCalledTimes(2))
    expect(screen.getByText('2')).toBeTruthy()
  })
})
