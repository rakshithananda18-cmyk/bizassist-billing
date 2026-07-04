// audit T7 — WebLocalOnlyNotice: on the web, a Local-only (free) account sees the
// "your data is on the desktop / log in there" notice; premium or desktop → none.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import React from 'react'

// Force the web platform (jsdom's hostname is 'localhost' → desktop otherwise).
vi.mock('../config', () => ({ IS_LOCAL_APP: false }))

let mockProfile = null
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ profile: mockProfile }) }))

import WebLocalOnlyNotice from '../components/hosting/WebLocalOnlyNotice'

beforeEach(() => { sessionStorage.clear(); mockProfile = null })
afterEach(cleanup)

describe('WebLocalOnlyNotice (T7)', () => {
  it('shows the local-device note for a free account on the web', () => {
    mockProfile = { is_premium: false }
    render(<WebLocalOnlyNotice />)
    expect(screen.getByText(/log in from the local device you used earlier/i)).toBeInTheDocument()
  })

  it('renders nothing for a premium account', () => {
    mockProfile = { is_premium: true }
    const { container } = render(<WebLocalOnlyNotice />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing until the profile has loaded (rollout-safe)', () => {
    mockProfile = null
    const { container } = render(<WebLocalOnlyNotice />)
    expect(container).toBeEmptyDOMElement()
  })

  it('dismiss hides it and remembers for the session', () => {
    mockProfile = { is_premium: false }
    render(<WebLocalOnlyNotice />)
    fireEvent.click(screen.getByText(/continue on web/i))
    expect(sessionStorage.getItem('bizassist_web_localonly_dismissed')).toBe('1')
    expect(screen.queryByText(/log in from the local device/i)).not.toBeInTheDocument()
  })
})
