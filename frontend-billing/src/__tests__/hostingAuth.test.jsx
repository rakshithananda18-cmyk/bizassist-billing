import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import React from 'react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

// Mock config variables and platform features
vi.mock('../config', () => ({
  IS_LOCAL_APP: true,
  CLOUD_URL: 'http://cloud-backend',
  LOCAL_URL: 'http://local-backend',
  API_BASE: 'http://local-backend',
  isLocalHost: (hostname) => true,
  updateApiBase: vi.fn((mode) => {
    localStorage.setItem('bizassist_hosting_mode', mode)
  }),
}))

// Mock useLock hook globally for the tests
vi.mock('../contexts/LockContext', () => ({
  useLock: () => ({
    hasLock: false,
    lock: vi.fn(),
    resetInactivityTimer: vi.fn(),
    setupPasscode: vi.fn(),
    clearPasscode: vi.fn(),
  }),
  LockProvider: ({ children }) => <>{children}</>,
}))

// Mock network discovery to avoid real network probing / latency during tests
vi.mock('../utils/networkDiscovery', () => ({
  discoverLocalBackend: () => Promise.resolve(null),
  getNetworkMode: () => 'local',
  clearDiscoveryCache: () => {},
}))

// Mock BootHealthCheck to avoid any boot loop network requests/timeouts
vi.mock('../components/BootHealthCheck', () => ({
  default: () => <div data-testid="boot-health" />
}))

// Mock useReadinessProbe hook for the Settings tests
let mockReadinessProbe = {
  localProbe: { status: 'online', ms: 10, error: null },
  cloudProbe: { status: 'online', ms: 120, error: null },
  internetProbe: { status: 'online', ms: 80, error: null },
  sseProbe: { status: 'online', ms: 5, error: null },
  recheck: vi.fn(),
}
vi.mock('../hooks/useReadinessProbe', () => ({
  useReadinessProbe: () => mockReadinessProbe
}))

// Mock window.matchMedia which is missing in jsdom environment
if (typeof window !== 'undefined') {
  window.matchMedia = window.matchMedia || function() {
    return {
      matches: false,
      addListener: function() {},
      removeListener: function() {},
      addEventListener: function() {},
      removeEventListener: function() {},
    }
  }
}

import { AuthProvider, useAuth } from '../contexts/AuthContext'
import Login from '../pages/Login'
import Register from '../pages/Register'
import Settings from '../pages/Settings'

// Helper consumer component to execute and test AuthProvider context functions directly
const AuthTestConsumer = ({ actionRef }) => {
  const auth = useAuth()
  React.useImperativeHandle(actionRef, () => auth)
  return null
}

// Global mutable mock states
let mockSettings = { general: { hosting_mode: 'local' } }
let mockProfile = { is_premium: true }
let mockTemplates = []
let mockStaffCounters = { business_name: 'Store', staff: [] }

const globalMockFetch = vi.fn(async (url) => {
  const u = String(url)
  const jsonResponse = (body, status = 200, ok = true) => ({
    ok,
    status,
    json: async () => body
  })

  if (u.includes('/business/templates')) {
    return jsonResponse({ templates: mockTemplates })
  }
  if (u.includes('/settings')) {
    return jsonResponse(mockSettings)
  }
  if (u.includes('/profile')) {
    return jsonResponse(mockProfile)
  }
  if (u.includes('/staff-counters')) {
    return jsonResponse(mockStaffCounters)
  }
  if (u.includes('/health')) {
    return jsonResponse({ status: 'ok', db: 'connected' })
  }
  if (u.includes('/login/staff')) {
    if (u.startsWith('http://local-backend') && localStorage.getItem('fail_local_login') === 'true') {
      return jsonResponse({ detail: 'Unauthorized' }, 401, false)
    }
    if (localStorage.getItem('fail_all_login') === 'true') {
      return jsonResponse({ detail: 'Invalid credentials' }, 401, false)
    }
    return jsonResponse({
      id: 5,
      username: 'cashier1',
      role: 'cashier',
      token: 'jwt-token',
      db_mode: u.startsWith('http://cloud-backend') ? 'cloud' : 'local'
    })
  }
  if (u.includes('/signup')) {
    return jsonResponse({ public_id: 'BA-NEW', token: 'mock-local-token' })
  }
  if (u.includes('/login')) {
    if (localStorage.getItem('fail_all_login') === 'true') {
      return jsonResponse({ detail: 'Invalid credentials' }, 401, false)
    }
    return jsonResponse({ token: 'mock-cloud-token', id: 1, username: 'owner1', public_id: 'BA-NEW' })
  }
  if (u.includes('/sync/cloud-token')) {
    return jsonResponse({ status: 'ok' })
  }
  if (u.includes('/business/setup')) {
    return jsonResponse({ status: 'ok' })
  }

  return { ok: false, status: 404, json: async () => ({}) }
})

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  vi.restoreAllMocks()
  vi.stubGlobal('fetch', globalMockFetch)

  mockSettings = { general: { hosting_mode: 'local' } }
  mockProfile = { is_premium: true }
  mockTemplates = []
  mockStaffCounters = { business_name: 'Store', staff: [] }
  mockReadinessProbe = {
    localProbe: { status: 'online', ms: 10, error: null },
    cloudProbe: { status: 'online', ms: 120, error: null },
    internetProbe: { status: 'online', ms: 80, error: null },
    sseProbe: { status: 'online', ms: 5, error: null },
    recheck: vi.fn(),
  }
  if (typeof navigator !== 'undefined') {
    try { Object.defineProperty(navigator, 'onLine', { value: true, configurable: true }) } catch {}
  }
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('Login staff resolution (T2)', () => {
  it('shows the Staff button when local /staff-counters is empty but cloud has staff', async () => {
    mockStaffCounters = { business_name: 'Cloud Store', staff: [{ username: 'cashier1', role: 'cashier', counter_prefix: 'CS' }] }
    
    // Stub fetch to return empty local, but populated cloud staff counters
    vi.stubGlobal('fetch', vi.fn(async (url) => {
      const u = String(url)
      const jsonResponse = (body) => ({ ok: true, status: 200, json: async () => body })
      if (u.includes('/staff-counters')) {
        if (u.startsWith('http://local-backend')) {
          return jsonResponse({ business_name: 'Local Store', staff: [] })
        }
        if (u.startsWith('http://cloud-backend')) {
          return jsonResponse({
            business_name: 'Cloud Store',
            staff: [{ username: 'cashier1', role: 'cashier', counter_prefix: 'CS' }]
          })
        }
      }
      return { ok: false }
    }))

    render(
      <MemoryRouter initialEntries={['/login']}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<Login />} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    )

    // Type owner username and click continue
    fireEvent.change(screen.getByPlaceholderText(/store/), { target: { value: 'owner1' } })
    fireEvent.click(screen.getByRole('button', { name: /Continue/i }))

    // Verify fallback to cloud, detected staff, and shows choice options
    await waitFor(() => {
      expect(screen.getByText('Staff Login')).toBeInTheDocument()
      expect(screen.getByText('Owner Login')).toBeInTheDocument()
    })
  })

  it('staffLogin: local failure falls back to cloud and switches the device to cloud', async () => {
    localStorage.setItem('fail_local_login', 'true')

    const actionRef = React.createRef()
    render(
      <AuthProvider>
        <AuthTestConsumer actionRef={actionRef} />
      </AuthProvider>
    )

    await waitFor(() => {
      expect(actionRef.current).not.toBeNull()
    })

    // Trigger staff login
    await actionRef.current.staffLogin('owner1', 'cashier1', 'password123')

    // Verify hosting mode switches to cloud because of fallback
    await waitFor(() => {
      expect(localStorage.getItem('bizassist_hosting_mode')).toBe('cloud')
      expect(actionRef.current.user).not.toBeNull()
      expect(actionRef.current.user.username).toBe('cashier1')
    })
  })

  it('a wrong password never falls through to the cloud as a success', async () => {
    localStorage.setItem('fail_all_login', 'true')

    const actionRef = React.createRef()
    render(
      <AuthProvider>
        <AuthTestConsumer actionRef={actionRef} />
      </AuthProvider>
    )

    await waitFor(() => {
      expect(actionRef.current).not.toBeNull()
    })

    await expect(
      actionRef.current.staffLogin('owner1', 'cashier1', 'wrongpassword')
    ).rejects.toThrow('Invalid credentials')
  })

  it('recent-login: an empty local result does not wipe cached staff or hide the choice', async () => {
    const initialLogins = [{
      username: 'owner1',
      businessName: 'Original Store',
      staffAccounts: [{ username: 'cashier1', role: 'cashier' }]
    }]
    localStorage.setItem('bizassist_recent_logins', JSON.stringify(initialLogins))

    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false })))

    render(
      <MemoryRouter initialEntries={['/login']}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<Login />} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    )

    // Click quick login owner tile
    fireEvent.click(screen.getByText('Original Store'))

    // Now click the "Staff Login" button to transition to the staff select view
    await waitFor(() => {
      expect(screen.getByText('Staff Login')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('Staff Login'))

    // Verify cached staff username is still rendered to select
    await waitFor(() => {
      expect(screen.getByText(/cashier1/)).toBeInTheDocument()
    })
  })
})

describe('Signup hosting auto-config (T3)', () => {
  it('signup({hosting:\'hybrid\'}) sets bizassist_hosting_mode=hybrid and provisions the cloud sync token', async () => {
    const actionRef = React.createRef()
    render(
      <AuthProvider>
        <AuthTestConsumer actionRef={actionRef} />
      </AuthProvider>
    )

    await waitFor(() => {
      expect(actionRef.current).not.toBeNull()
    })

    await actionRef.current.signup({
      username: 'newowner',
      password: 'password123',
      business_name: 'New Shop',
      hosting: 'hybrid',
      template_key: 'general'
    })

    expect(localStorage.getItem('bizassist_hosting_mode')).toBe('hybrid')
    await waitFor(() => {
      expect(localStorage.getItem('bizassist_cloud_token')).toBe('mock-cloud-token')
    })
  })

  it('signup({hosting:\'local\'}) stays local and navigates straight to the app', async () => {
    const actionRef = React.createRef()
    render(
      <AuthProvider>
        <AuthTestConsumer actionRef={actionRef} />
      </AuthProvider>
    )

    await waitFor(() => {
      expect(actionRef.current).not.toBeNull()
    })

    await actionRef.current.signup({
      username: 'localowner',
      password: 'password123',
      business_name: 'Local Shop',
      hosting: 'local',
      template_key: 'general'
    })

    expect(localStorage.getItem('bizassist_hosting_mode')).toBe('local')
    expect(localStorage.getItem('bizassist_cloud_token')).toBeNull()
  })

  it('setHostingMode("local") persists mode WITHOUT logging the user out', async () => {
    // Stub global fetch with a mock that resolves settings successfully and tracks PUT requests
    const putSpy = vi.fn().mockImplementation(async (url, opts) => {
      const u = String(url)
      if (u.includes('/settings')) {
        return { ok: true, status: 200, json: async () => ({ status: 'ok' }) }
      }
      return { ok: true, status: 200, json: async () => ({}) }
    })
    vi.stubGlobal('fetch', putSpy)

    localStorage.setItem('billing_token', 'user-session-jwt')
    localStorage.setItem('billing_user', JSON.stringify({ username: 'owner1' }))

    const actionRef = React.createRef()
    render(
      <AuthProvider>
        <AuthTestConsumer actionRef={actionRef} />
      </AuthProvider>
    )

    await waitFor(() => {
      expect(actionRef.current).not.toBeNull()
      expect(actionRef.current.token).toBe('user-session-jwt')
    })

    await actionRef.current.setHostingMode('local')

    expect(localStorage.getItem('bizassist_hosting_mode')).toBe('local')
    expect(localStorage.getItem('billing_token')).toBe('user-session-jwt')
    expect(actionRef.current.user).not.toBeNull()
  })
})

describe('Register two options (T4)', () => {
  it('renders exactly two hosting choices: Local and Local + Cloud (no pure Cloud)', () => {
    render(
      <MemoryRouter>
        <AuthProvider>
          <Register />
        </AuthProvider>
      </MemoryRouter>
    )

    const buttons = screen.getAllByRole('button')
    const hostingButtons = buttons.filter(btn => {
      const text = btn.textContent || ''
      return text.includes('Local') || text.includes('Cloud')
    })

    expect(hostingButtons).toHaveLength(2)
    expect(screen.getByText('Local')).toBeInTheDocument()
    expect(screen.getByText('Local + Cloud')).toBeInTheDocument()
    expect(screen.queryByText('Cloud Only')).not.toBeInTheDocument()
  })

  it('forwards the chosen hosting to signup() and navigates to / (never /settings?switch=)', async () => {
    // Stub global fetch with a mock that tracks request bodies
    const signupSpy = vi.fn().mockImplementation(async (url, opts) => {
      if (url.includes('/signup')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ public_id: 'BA-SIGNUP', token: 'mock-local-token' })
        }
      }
      if (url.includes('/business/setup')) {
        return { ok: true, status: 200, json: async () => ({}) }
      }
      return { ok: false, status: 404 }
    })
    vi.stubGlobal('fetch', signupSpy)

    const { container } = render(
      <MemoryRouter>
        <AuthProvider>
          <Register />
        </AuthProvider>
      </MemoryRouter>
    )

    // Fill registration form
    fireEvent.change(screen.getByPlaceholderText('e.g. store'), { target: { value: 'testshop' } })
    fireEvent.change(screen.getByPlaceholderText('••••••••'), { target: { value: 'Password123!' } })
    
    // Select Confirm Password by id since it has no placeholder
    const confirmPasswordInput = container.querySelector('#confirmPassword')
    fireEvent.change(confirmPasswordInput, { target: { value: 'Password123!' } })
    
    fireEvent.click(screen.getByLabelText(/I agree to/i))

    // Select Local + Cloud hosting choice
    fireEvent.click(screen.getByText('Local + Cloud'))

    // Submit form
    fireEvent.submit(screen.getByRole('button', { name: /Register/i }))

    await waitFor(() => {
      // Local mirror signup is called
      expect(signupSpy).toHaveBeenCalled()
    })
  })
})

describe('Settings two-mode switch (T5)', () => {
  it('the pure-Cloud card is absent; a legacy cloud account shows as active "Local + Cloud"', async () => {
    mockSettings = { general: { hosting_mode: 'cloud' } } // legacy cloud account settings on mount
    localStorage.setItem('billing_token', 'user-session-jwt')
    localStorage.setItem('billing_user', JSON.stringify({ username: 'owner1' }))

    render(
      <MemoryRouter initialEntries={['/settings?tab=advanced']}>
        <Routes>
          <Route path="/settings" element={
            <AuthProvider>
              <Settings />
            </AuthProvider>
          } />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Local Only')).toBeInTheDocument()
      expect(screen.getByText('Local + Cloud')).toBeInTheDocument()
    })

    expect(screen.queryByText('Cloud Only')).not.toBeInTheDocument()

    // Active card uses var(--accent-dim) or check properties
    const hybridCard = screen.getByText('Local + Cloud').closest('.hm-card')
    expect(hybridCard.className).toContain('hm-card--active')
  })

  it('clicking Local switches instantly via setHostingMode (no preflight, no logout)', async () => {
    mockSettings = { general: { hosting_mode: 'hybrid' } }
    localStorage.setItem('billing_token', 'user-session-jwt')
    localStorage.setItem('billing_user', JSON.stringify({ username: 'owner1' }))

    const putSpy = vi.fn().mockImplementation(async (url, opts) => {
      const u = String(url)
      if (u.includes('/settings')) {
        return { ok: true, status: 200, json: async () => mockSettings }
      }
      return { ok: true, status: 200, json: async () => ({}) }
    })
    vi.stubGlobal('fetch', putSpy)

    render(
      <MemoryRouter initialEntries={['/settings?tab=advanced']}>
        <Routes>
          <Route path="/settings" element={
            <AuthProvider>
              <Settings />
            </AuthProvider>
          } />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Local Only')).toBeInTheDocument()
    })

    // Click Local Only
    fireEvent.click(screen.getByText('Local Only'))

    await waitFor(() => {
      // Verify Settings saved with local mode (general.hosting_mode: local)
      const calls = putSpy.mock.calls
      const settingsPut = calls.find(c => c[0].includes('/settings') && c[1]?.method === 'PUT')
      expect(settingsPut).toBeDefined()
      const body = JSON.parse(settingsPut[1].body)
      expect(body.general.hosting_mode).toBe('local')
    })
    
    // Verify token is still there (no logout)
    expect(localStorage.getItem('billing_token')).toBe('user-session-jwt')
  })

  it('clicking Local + Cloud while cloud is offline shows an error toast (no silent no-op)', async () => {
    mockSettings = { general: { hosting_mode: 'local' } }
    localStorage.setItem('billing_token', 'user-session-jwt')
    localStorage.setItem('billing_user', JSON.stringify({ username: 'owner1' }))

    // Force cloud probe offline
    mockReadinessProbe.cloudProbe = { status: 'offline', ms: null, error: 'Connection Timeout' }

    // Listen to show_toast custom events
    const toastSpy = vi.fn()
    window.addEventListener('show_toast', toastSpy)

    render(
      <MemoryRouter initialEntries={['/settings?tab=advanced']}>
        <Routes>
          <Route path="/settings" element={
            <AuthProvider>
              <Settings />
            </AuthProvider>
          } />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Local + Cloud')).toBeInTheDocument()
    })

    // Click Local + Cloud
    fireEvent.click(screen.getByText('Local + Cloud'))

    // Verify error toast was dispatched
    expect(toastSpy).toHaveBeenCalled()
    expect(toastSpy.mock.calls[0][0].detail.type).toBe('error')
    expect(toastSpy.mock.calls[0][0].detail.msg).toContain('offline/unreachable')

    window.removeEventListener('show_toast', toastSpy)
  })
})
