// The signup trial in the bell, on the WEB: the countdown plus the one step that
// matters most while the trial lasts — getting the desktop app. Separate from
// NotificationBell.test.jsx because this file forces the web platform (jsdom's
// 'localhost' would otherwise read as the desktop app).
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../config', async (importOriginal) => ({ ...(await importOriginal()), IS_LOCAL_APP: false }))

const authFetch = vi.fn()
let mockSettings = null
let mockUser = null
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ authFetch, settings: mockSettings, user: mockUser }),
}))

import NotificationBell from '../components/NotificationBell'
import { DESKTOP_DOWNLOAD_URL } from '../config/downloadApp'

const DAY = 86400000
const ok = (body) => ({ ok: true, status: 200, json: async () => body })
const draw = () => render(<MemoryRouter><NotificationBell /></MemoryRouter>)
const onTrial = (daysAhead) => ({
  general: {},
  subscription: {
    plan: 'pro', status: 'trial', trial: true,
    ends_at: new Date(Date.now() + daysAhead * DAY + 3600000).toISOString(),
  },
})

beforeEach(() => {
  authFetch.mockReset()
  authFetch.mockImplementation((path) => Promise.resolve(ok(
    path === '/api/sync/queue-depth' ? { halt: { reason: null } } : { items: [], count: 0, severity: null },
  )))
  mockSettings = null
  mockUser = { role: 'enterprise' }
})
afterEach(() => { vi.restoreAllMocks() })

describe('NotificationBell — Pro trial on the web', () => {
  it('lists the countdown and the desktop app', async () => {
    mockSettings = onTrial(14)
    draw()
    await waitFor(() => expect(screen.getByText('2')).toBeTruthy())
    fireEvent.click(screen.getByLabelText('2 notifications'))
    expect(screen.getByText('Pro trial: 14 days left')).toBeTruthy()
    expect(screen.getByText('Get the desktop app')).toBeTruthy()
  })

  it('opens the download page in a new tab instead of routing inside the app', async () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    mockSettings = onTrial(5)
    draw()
    await waitFor(() => expect(screen.getByText('2')).toBeTruthy())
    fireEvent.click(screen.getByLabelText('2 notifications'))
    fireEvent.click(screen.getByText('Get the desktop app'))
    expect(open).toHaveBeenCalledWith(DESKTOP_DOWNLOAD_URL, '_blank', 'noopener')
  })

  it('keeps trial items away from cashiers', async () => {
    mockSettings = onTrial(14)
    mockUser = { role: 'cashier' }
    draw()
    await waitFor(() => expect(authFetch).toHaveBeenCalled())
    expect(screen.getByLabelText('Notifications')).toBeTruthy()
  })
})
