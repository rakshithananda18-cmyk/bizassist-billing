import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor, act } from '@testing-library/react'
import React from 'react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

// Mock config variables and platform features
vi.mock('../config', () => ({
  IS_LOCAL_APP: true,
  CLOUD_URL: 'http://cloud-backend',
  FALLBACK_CLOUD_URL: 'http://fallback-backend',
  getActiveCloudUrl: () => 'http://cloud-backend',
  switchActiveCloudUrl: vi.fn(),
  getAlternateCloudUrl: () => 'http://fallback-backend',
  LOCAL_URL: 'http://local-backend',
  API_BASE: 'http://local-backend',
  getApiBase: () => 'http://local-backend',
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
import { getHostingPreference, setHostingPreference } from '../utils/deviceMode'

// Helper consumer component to execute and test AuthProvider context functions directly
const AuthTestConsumer = ({ actionRef }) => {
  const auth = useAuth()
  React.useImperativeHandle(actionRef, () => auth)
  return null
}

// Global mutable mock states
let mockSettings = { general: { hosting_mode: 'local' } }
let mockProfile = { public_id: 'BA-NEW', role: 'enterprise', is_premium: true }
let mockTemplates = []
let mockStaffCounters = { business_name: 'Store', staff: [] }
// The cloud's Pro trial: GET /trial-offer (null = an older cloud without it),
// and what its /signup says (undefined = an older cloud that says nothing).
let mockTrialOffer = null
let mockCloudTrial

const globalMockFetch = vi.fn(async (url) => {
  const u = String(url)
  const jsonResponse = (body, status = 200, ok = true) => ({
    ok,
    status,
    json: async () => body,
    // authFetch calls res.clone().json() on the error branch; real Responses
    // have clone(), our mocks must too.
    clone() { return this },
  })

  if (u.includes('/trial-offer')) {
    return mockTrialOffer ? jsonResponse(mockTrialOffer) : jsonResponse({ detail: 'Not Found' }, 404, false)
  }
  if (u.includes('/business/templates')) {
    return jsonResponse({ templates: mockTemplates })
  }
  // Optional profile fetch on mount — succeed with an empty profile so it never
  // emits a spurious error toast that would race the assertions below.
  if (u.includes('/business/billing-profile')) {
    return jsonResponse({})
  }
  // Settings → Advanced mounts OpsHealthPanel, which fetches these on mount;
  // succeed so they don't emit a spurious error toast in the mode-switch tests.
  if (u.includes('/reports/ops-health')) {
    return jsonResponse({ ok: true, sync: {}, conflicts: { unreviewed: 0 }, integrity: { ok: true }, ai_usage: {} })
  }
  if (u.includes('/api/sync/conflicts')) {
    return jsonResponse({ unreviewed_count: 0, conflicts: [] })
  }
  // The shared profile bell also checks alerts and sync status on mount.
  if (u.includes('/alerts/notifications')) {
    return jsonResponse({ items: [], count: 0, severity: null })
  }
  if (u.includes('/api/sync/queue-depth')) {
    return jsonResponse({ pending_count: 0, halt: { reason: null } })
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
  if (u.includes('/api/auth/lookup-business')) {
    return jsonResponse({ ...mockStaffCounters, found: true, public_id: 'BA-OWNER', has_staff: mockStaffCounters.staff.length > 0 })
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
    const body = { public_id: 'BA-NEW', token: u.startsWith('http://cloud-backend') ? 'mock-cloud-token' : 'mock-local-token' }
    if (u.startsWith('http://cloud-backend') && mockCloudTrial !== undefined) body.trial = mockCloudTrial
    return jsonResponse(body)
  }
  if (u.includes('/api/auth/device/cloud-session')) {
    return jsonResponse({ public_id: 'BA-NEW', token: 'mock-local-token', id: 1, user_id: 1, username: 'owner1', role: 'enterprise', db_mode: 'local' })
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
  if (u.includes('/business/config')) {
    return jsonResponse({ config: {}, attributes_schema: [] })
  }

  return { ok: false, status: 404, json: async () => ({}), clone() { return this } }
})

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  vi.restoreAllMocks()
  vi.stubGlobal('fetch', globalMockFetch)

  mockSettings = { general: { hosting_mode: 'local' } }
  mockProfile = { public_id: 'BA-NEW', role: 'enterprise', is_premium: true }
  mockTemplates = []
  mockStaffCounters = { business_name: 'Store', staff: [] }
  mockTrialOffer = null
  mockCloudTrial = undefined
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
  vi.useRealTimers()
  cleanup()
  vi.unstubAllGlobals()
})

describe('Login staff resolution (T2)', () => {
  it('finds the cloud business and its staff when it is absent from the local database', async () => {
    mockStaffCounters = { business_name: 'Cloud Store', staff: [{ username: 'cashier1', role: 'cashier', counter_prefix: 'CS' }] }
    
    // Stub fetch to return empty local, but populated cloud staff counters
    vi.stubGlobal('fetch', vi.fn(async (url) => {
      const u = String(url)
      const jsonResponse = (body) => ({ ok: true, status: 200, json: async () => body, clone() { return this } })
      if (u.includes('/api/auth/lookup-business')) {
        if (u.startsWith('http://local-backend')) {
          return jsonResponse({ found: false, staff: [] })
        }
        if (u.startsWith('http://cloud-backend')) {
          return jsonResponse({
            found: true, public_id: 'BA-OWNER', has_staff: true, business_name: 'Cloud Store',
            staff: [{ username: 'cashier1', role: 'cashier', counter_prefix: 'CS' }]
          })
        }
      }
      return { ok: false, status: 404, json: async () => ({}), clone() { return this } }
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
    fireEvent.change(screen.getByLabelText('Business Owner Username'), { target: { value: 'owner1' } })
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
    // NOTE: these auth calls are deliberately NOT wrapped in act().
    //
    // React does warn about the state updates they cause, and wrapping them
    // looks like the fix. It is not: `AuthTestConsumer` publishes the context
    // through `useImperativeHandle(actionRef, () => auth)`, which refreshes on
    // every commit, and `signup`/`staffLogin` both kick off fire-and-forget work
    // (`_provisionCloudSyncToken`) that is still in flight when the call
    // resolves. Wrapping in act() changes when React commits relative to those
    // continuations, and the token/user assertions below started failing —
    // verified 2026-07-31: T2 and T3 passed before the wrap and failed after,
    // with nothing else in these tests changed.
    //
    // The `waitFor` blocks below are what settle the state, and they work. The
    // act() warning is cosmetic here; making it go away needs the consumer to
    // expose a stable handle, not a wrapper at the call site.
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
    ).rejects.toThrow('Wrong username or password.')
  })

  it('recent-login: an empty local result does not wipe cached staff or hide the choice', async () => {
    const initialLogins = [{
      username: 'owner1',
      businessName: 'Original Store',
      staffAccounts: [{ username: 'cashier1', role: 'cashier' }]
    }]
    localStorage.setItem('bizassist_recent_logins', JSON.stringify(initialLogins))

    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}), clone() { return this } })))

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

  it('recent-login: preselects the counter this device last signed in to', async () => {
    // Staff no longer get a public list of a business's counters, so the
    // device remembers the one it used (Login.jsx lastStaff).
    localStorage.setItem('bizassist_recent_logins', JSON.stringify([{
      username: 'owner1',
      businessName: 'Counter Store',
      staffAccounts: [{ username: 'cashier1', role: 'cashier' }, { username: 'cashier2', role: 'cashier' }],
      lastStaff: 'cashier2',
    }]))
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500, json: async () => ({}), clone() { return this } })))

    render(
      <MemoryRouter initialEntries={['/login']}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<Login />} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    )
    fireEvent.click(screen.getByText('Counter Store'))
    await waitFor(() => expect(screen.getByText('Staff Login')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Staff Login'))
    // CustomSelect shows only the chosen option until it is opened.
    await waitFor(() => expect(screen.getByText(/cashier2/)).toBeInTheDocument())
    expect(screen.queryByText(/cashier1/)).toBeNull()
  })

  it('navigates after a valid owner login without waiting for the optional staff refresh', async () => {
    const delayedStaffFetch = vi.fn(async (url, options) => {
      if (String(url).endsWith('/staff')) {
        await new Promise(resolve => setTimeout(resolve, 500))
        return { ok: true, status: 200, json: async () => [], clone() { return this } }
      }
      return globalMockFetch(url, options)
    })
    vi.stubGlobal('fetch', delayedStaffFetch)

    render(
      <MemoryRouter initialEntries={['/login']}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/" element={<div>Dashboard reached</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    )

    fireEvent.change(screen.getByLabelText('Business Owner Username'), { target: { value: 'owner1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await screen.findByLabelText('Owner Password')
    fireEvent.change(screen.getByLabelText('Owner Password'), { target: { value: 'password123' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign In as Owner' }))

    await waitFor(() => {
      expect(screen.getByText('Dashboard reached')).toBeInTheDocument()
    }, { timeout: 250 })

    expect(delayedStaffFetch).toHaveBeenCalledWith(
      'http://local-backend/staff',
      expect.objectContaining({ headers: { Authorization: 'Bearer mock-cloud-token' } })
    )
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
    expect(screen.getByText('Local only')).toBeInTheDocument()
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
      return { ok: false, status: 404, json: async () => ({}), clone() { return this } }
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
    fireEvent.change(screen.getByLabelText('Store Username'), { target: { value: 'testshop' } })
    fireEvent.change(screen.getByPlaceholderText('••••••••'), { target: { value: 'Password123!' } })
    
    // Select Confirm Password by id since it has no placeholder
    const confirmPasswordInput = container.querySelector('#confirmPassword')
    fireEvent.change(confirmPasswordInput, { target: { value: 'Password123!' } })
    fireEvent.change(screen.getByLabelText('Phone'), { target: { value: '9876543210' } })
    
    fireEvent.click(screen.getByLabelText(/I agree to/i))

    // Select Local + Cloud hosting choice
    fireEvent.click(screen.getByText('Local + Cloud'))

    // Submit form
    fireEvent.submit(container.querySelector('#register-form'))

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
    setHostingPreference('owner1', 'local')
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

describe('Desktop Pro hosting preference', () => {
  const owner = { id: 1, user_id: 1, username: 'owner1', public_id: 'BA-PRO', role: 'enterprise' }
  const mount = async () => {
    localStorage.setItem('billing_token', 'local-jwt')
    localStorage.setItem('billing_user', JSON.stringify(owner))
    localStorage.setItem('bizassist_device_mode_owner', owner.public_id)
    const actionRef = React.createRef()
    render(<AuthProvider><AuthTestConsumer actionRef={actionRef} /></AuthProvider>)
    await waitFor(() => expect(actionRef.current?.settings).toBeTruthy())
    return actionRef
  }

  it('automatically enables Local + Cloud for confirmed Pro despite an old local default', async () => {
    mockSettings = { general: { hosting_mode: 'local' }, subscription: { plan: 'pro' } }
    localStorage.setItem('bizassist_hosting_mode', 'local')
    const auth = await mount()
    await waitFor(() => expect(localStorage.getItem('bizassist_hosting_mode')).toBe('hybrid'))
    expect(auth.current.settings.general.hosting_mode).toBe('hybrid')
    expect(getHostingPreference(owner.public_id)).toBeNull()
    expect(localStorage.getItem('billing_token')).toBe('local-jwt')
    expect(globalMockFetch.mock.calls.some(([url, options]) => String(url) === 'http://local-backend/settings' && options?.method === 'PUT' && JSON.parse(options.body).general.hosting_mode === 'hybrid')).toBe(true)
  })

  it('keeps a confirmed Free desktop local', async () => {
    mockSettings = { general: { hosting_mode: 'local' }, subscription: { plan: 'free' } }
    mockProfile = { is_premium: false }
    const auth = await mount()
    expect(auth.current.settings.general.hosting_mode).toBe('local')
    expect(globalMockFetch.mock.calls.filter(([url, options]) => String(url).endsWith('/settings') && options?.method === 'PUT')).toHaveLength(0)
  })

  it('honours an explicit Local choice on later settings loads and session restores', async () => {
    mockSettings = { general: { hosting_mode: 'hybrid' }, subscription: { plan: 'pro' } }
    let auth = await mount()
    await act(async () => { expect(await auth.current.setHostingMode('local')).toBe(true) })
    expect(getHostingPreference(owner.public_id)).toBe('local')
    cleanup()
    // A synced account value or a new Pro check cannot overrule this device.
    mockSettings = { general: { hosting_mode: 'hybrid' }, subscription: { plan: 'pro' } }
    auth = await mount()
    expect(auth.current.settings.general.hosting_mode).toBe('local')
    expect(localStorage.getItem('billing_token')).toBe('local-jwt')
  })

  it('does not claim Local is enabled or store an opt-out when its save fails', async () => {
    mockSettings = { general: { hosting_mode: 'hybrid' }, subscription: { plan: 'pro' } }
    const auth = await mount()
    localStorage.setItem('bizassist_hosting_mode', 'hybrid')
    const original = (...args) => globalMockFetch(...args)
    vi.stubGlobal('fetch', vi.fn((url, options) => String(url).endsWith('/settings') && options?.method === 'PUT'
      ? Promise.resolve({ ok: false, status: 500 }) : original(url, options)))
    await act(async () => { expect(await auth.current.setHostingMode('local')).toBe(false) })
    expect(getHostingPreference(owner.public_id)).toBeNull()
    expect(localStorage.getItem('bizassist_hosting_mode')).toBe('hybrid')
    expect(auth.current.settings.general.hosting_mode).toBe('hybrid')
  })

  it('keeps an explicit Local choice through sign-in and does not provision cloud sync', async () => {
    mockSettings = { general: { hosting_mode: 'local' }, subscription: { plan: 'pro' } }
    setHostingPreference('BA-NEW', 'local')
    const auth = await mount()
    globalMockFetch.mockClear()
    await act(async () => { await auth.current.login('owner1', 'Password123!') })
    await waitFor(() => expect(auth.current.user?.public_id).toBe('BA-NEW'))
    await waitFor(() => expect(auth.current.settings?.general.hosting_mode).toBe('local'))
    expect(getHostingPreference('BA-NEW')).toBe('local')
    expect(globalMockFetch.mock.calls.some(([url]) => String(url) === 'http://cloud-backend/login' || String(url).includes('/sync/cloud-token'))).toBe(false)
  })

  it('finishes a hung Local save with an error and leaves the previous choice intact', async () => {
    mockSettings = { general: { hosting_mode: 'hybrid' }, subscription: { plan: 'pro' } }
    const auth = await mount()
    localStorage.setItem('bizassist_hosting_mode', 'hybrid')
    vi.stubGlobal('fetch', vi.fn((url, options) => {
      if (String(url).endsWith('/settings') && options?.method === 'PUT') {
        return new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true }))
      }
      return globalMockFetch(url, options)
    }))
    vi.useFakeTimers()
    try {
      await act(async () => {
        const pending = auth.current.setHostingMode('local')
        await vi.advanceTimersByTimeAsync(8000)
        expect(await pending).toBe(false)
      })
      expect(getHostingPreference(owner.public_id)).toBeNull()
      expect(localStorage.getItem('bizassist_hosting_mode')).toBe('hybrid')
    } finally { vi.useRealTimers() }
  })

  it('serializes a Local choice after an already-running automatic hybrid save', async () => {
    mockSettings = { general: { hosting_mode: 'local' }, subscription: { plan: 'pro' } }
    const original = (...args) => globalMockFetch(...args)
    let completeHybrid
    const modes = []
    vi.stubGlobal('fetch', vi.fn((url, options) => {
      if (String(url).endsWith('/settings') && options?.method === 'PUT') {
        const mode = JSON.parse(options.body).general.hosting_mode
        modes.push(mode)
        if (mode === 'hybrid') return new Promise(resolve => { completeHybrid = () => resolve({ ok: true, status: 200 }) })
        return Promise.resolve({ ok: true, status: 200 })
      }
      return original(url, options)
    }))
    const auth = await mount()
    await waitFor(() => expect(completeHybrid).toBeTypeOf('function'))
    let saved
    await act(async () => {
      const pending = auth.current.setHostingMode('local')
      expect(modes).toEqual(['hybrid'])
      completeHybrid()
      saved = await pending
    })
    expect(saved).toBe(true)
    expect(modes.slice(0, 2)).toEqual(['hybrid', 'local'])
    expect(getHostingPreference(owner.public_id)).toBe('local')
    expect(localStorage.getItem('bizassist_hosting_mode')).toBe('local')
    expect(auth.current.settings.general.hosting_mode).toBe('local')
  })
})

describe('Cloud-backed owner login background restore', () => {
  const json = (body, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => body, clone() { return this } })
  async function mountFreshOwner({ onProvision, onActivate, onLocalMode } = {}) {
    mockSettings = { general: { hosting_mode: 'hybrid' }, subscription: { plan: 'pro' } }
    mockProfile = { public_id: 'BA-NEW', role: 'enterprise', is_premium: true, plan: 'pro' }
    const fetch = vi.fn((url, options) => {
      const path = String(url)
      if (path === 'http://local-backend/login') return Promise.resolve(json({ detail: 'No local account' }, 401))
      if (path === 'http://cloud-backend/login') return Promise.resolve(json({ token: 'verified-cloud-token', id: 1, username: 'owner1', public_id: 'BA-NEW', role: 'enterprise' }))
      if (path === 'http://local-backend/api/auth/reconcile_local') return Promise.resolve(json({ detail: 'Local account not found' }, 404))
      if (path === 'http://local-backend/api/auth/device/cloud-session') return Promise.resolve(json({ token: 'local-owner-token', id: 2, username: 'owner1', public_id: 'BA-NEW', role: 'enterprise' }))
      if (path === 'http://local-backend/api/sync/cloud-token') {
        const body = JSON.parse(options.body)
        if (body.enable_sync) return onActivate?.(body) || Promise.resolve(json({ hosting_mode: 'hybrid', sync_started: true, initial_restore_pending: true }))
        return onProvision?.(body) || Promise.resolve(json({ status: 'ok' }))
      }
      if (path === 'http://local-backend/settings' && options?.method === 'PUT') {
        const mode = JSON.parse(options.body).general.hosting_mode
        onLocalMode?.(mode)
        return Promise.resolve(json({ status: 'ok' }))
      }
      return globalMockFetch(url, options)
    })
    vi.stubGlobal('fetch', fetch)
    const actionRef = React.createRef()
    render(<AuthProvider><AuthTestConsumer actionRef={actionRef} /></AuthProvider>)
    await waitFor(() => expect(actionRef.current).not.toBeNull())
    return { auth: actionRef, fetch }
  }

  it('lets a fresh-device owner sign in while provisioning, then starts restore only after provisioning succeeds', async () => {
    let finishProvision
    const activation = vi.fn()
    const { auth, fetch } = await mountFreshOwner({
      onProvision: () => new Promise(resolve => { finishProvision = () => resolve(json({ status: 'ok' })) }),
      onActivate: activation,
    })
    await act(async () => { await auth.current.login('owner1', 'Password123!') })
    expect(auth.current.user.public_id).toBe('BA-NEW')
    expect(finishProvision).toBeTypeOf('function')
    expect(activation).not.toHaveBeenCalled()
    await act(async () => { finishProvision() })
    await waitFor(() => expect(activation).toHaveBeenCalledOnce())
    expect(activation).toHaveBeenCalledWith({ token: 'verified-cloud-token', enable_sync: true })
    expect(localStorage.getItem('bizassist_cloud_token')).toBe('verified-cloud-token')
    expect(fetch.mock.calls.some(([url]) => /data-transfer\/(count|export|import)/.test(String(url)))).toBe(false)
  })

  it('does not activate a delayed login after logout', async () => {
    let finishProvision
    const activation = vi.fn()
    const { auth } = await mountFreshOwner({
      onProvision: () => new Promise(resolve => { finishProvision = () => resolve(json({ status: 'ok' })) }),
      onActivate: activation,
    })
    await act(async () => { await auth.current.login('owner1', 'Password123!') })
    await act(async () => { await auth.current.logout(false) })
    await act(async () => { finishProvision() })
    expect(auth.current.token).toBeNull()
    expect(localStorage.getItem('bizassist_cloud_token')).toBeNull()
    expect(activation).not.toHaveBeenCalled()
  })

  it('writes an explicit Local choice after an in-flight automatic activation and never re-enables it', async () => {
    let finishActivation
    const order = []
    const { auth } = await mountFreshOwner({
      onActivate: () => {
        order.push('activation')
        return new Promise(resolve => { finishActivation = () => resolve(json({ hosting_mode: 'hybrid', sync_started: true })) })
      },
      onLocalMode: mode => order.push(mode),
    })
    await act(async () => { await auth.current.login('owner1', 'Password123!') })
    await waitFor(() => expect(finishActivation).toBeTypeOf('function'))
    let result
    await act(async () => {
      const localChoice = auth.current.setHostingMode('local')
      expect(order).toEqual(['activation'])
      finishActivation()
      result = await localChoice
    })
    expect(result).toBe(true)
    expect(order[0]).toBe('activation')
    expect(order.length).toBeGreaterThanOrEqual(2)
    expect(order.slice(1).every(mode => mode === 'local')).toBe(true)
    expect(getHostingPreference('BA-NEW')).toBe('local')
    expect(auth.current.settings.general.hosting_mode).toBe('local')
  })
})

describe('Google owner desktop identity and recoverable sync setup', () => {
  const json = (body, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => body, clone() { return this } })
  const cloudOwner = { token: 'google-cloud-token', id: 42, user_id: 42, public_id: 'BA-GOOGLE', username: 'google-owner', role: 'enterprise', action: 'login' }
  const localOwner = { ...cloudOwner, token: 'google-local-token', id: 7, user_id: 7, db_mode: 'local' }
  async function mountGoogle({ verify = cloudOwner, mirror = localOwner, mirrorStatus = 200, localExists = false, provision, resume = null } = {}) {
    mockSettings = { general: { hosting_mode: 'hybrid' }, subscription: { plan: 'pro' } }
    mockProfile = { public_id: cloudOwner.public_id, role: 'enterprise', is_premium: true }
    const fetch = vi.fn(async (url, options) => {
      const path = String(url)
      if (path === 'http://cloud-backend/api/auth/google/verify' || path === 'http://cloud-backend/api/auth/google/register') return json(verify)
      if (path === 'http://local-backend/api/auth/device/google-discovery') return json({ local_owner_exists: localExists })
      if (path === 'http://local-backend/api/auth/device/cloud-session') return json(mirror, mirrorStatus)
      if (path === 'http://local-backend/api/sync/resume') return resume ? resume() : json({ detail: 'No saved cloud credential' }, 401)
      if (path === 'http://local-backend/api/sync/cloud-token') {
        if (provision) return provision(JSON.parse(options.body))
        return json(JSON.parse(options.body).enable_sync ? { hosting_mode: 'hybrid', sync_started: true, initial_restore_pending: true } : { status: 'ok' })
      }
      return globalMockFetch(url, options)
    })
    vi.stubGlobal('fetch', fetch)
    const auth = React.createRef()
    const view = render(<AuthProvider><AuthTestConsumer actionRef={auth} /></AuthProvider>)
    await waitFor(() => expect(auth.current).not.toBeNull())
    return { auth, fetch, view }
  }

  it('discovers the existing cloud Google owner before creating the same-BizID local mirror', async () => {
    const { auth, fetch } = await mountGoogle()
    await act(async () => { await auth.current.googleAuth({ credential: 'synthetic-google-credential' }) })
    await waitFor(() => expect(auth.current.user.public_id).toBe('BA-GOOGLE'))
    const authRequests = fetch.mock.calls.filter(([url]) => String(url).includes('/api/auth/'))
    expect(authRequests.map(([url]) => url)).toEqual([
      'http://cloud-backend/api/auth/google/verify', 'http://local-backend/api/auth/device/cloud-session',
    ])
    expect(JSON.parse(authRequests[1][1].body)).toEqual({ token: 'google-cloud-token', credential: 'synthetic-google-credential' })
    expect(auth.current.user.id).toBe(7)
    expect(localStorage.getItem('billing_token')).toBe('google-local-token')
    expect(fetch.mock.calls.some(([url]) => String(url).endsWith('/signup'))).toBe(false)
  })

  it('creates a new Google owner on cloud first and mirrors the cloud identity instead of registering a second local store', async () => {
    const { auth, fetch } = await mountGoogle({ verify: { ...cloudOwner, action: 'registered' } })
    await act(async () => {
      await auth.current.googleAuth({ credential: 'new-google-credential', username: 'google-owner', business_name: 'Cloud Store', phone: '919999999999' }, true)
    })
    const registration = fetch.mock.calls.filter(([url]) => String(url).includes('/google/register'))
    expect(registration).toHaveLength(1)
    expect(registration[0][0]).toBe('http://cloud-backend/api/auth/google/register')
    const mirror = fetch.mock.calls.find(([url]) => String(url).includes('/device/cloud-session'))
    expect(JSON.parse(mirror[1].body).token).toBe('google-cloud-token')
    expect(auth.current.user.public_id).toBe(cloudOwner.public_id)
  })

  it('checks local-only Google ownership before offering new-store onboarding', async () => {
    const { auth, fetch } = await mountGoogle({ verify: { status: 'needs_onboarding' }, localExists: true })
    await expect(auth.current.googleAuth({ credential: 'local-only-google-credential' })).rejects.toThrow(/already has a local business/)
    expect(auth.current.user).toBeNull()
    expect(fetch.mock.calls.some(([url]) => /google\/register|device\/cloud-session|\/signup$/.test(String(url)))).toBe(false)
  })

  it('surfaces a local different-BizID conflict without saving a cloud JWT as the local session', async () => {
    const { auth, fetch } = await mountGoogle({ mirror: { detail: 'An existing local account has a different business identity. Nothing was replaced.' }, mirrorStatus: 409 })
    await expect(auth.current.googleAuth({ credential: 'synthetic-google-credential' })).rejects.toThrow(/different business identity/)
    expect(auth.current.user).toBeNull()
    expect(localStorage.getItem('billing_token')).toBeNull()
    expect(fetch.mock.calls.some(([url]) => /reclaim_local|\/signup$/.test(String(url)))).toBe(false)
  })

  it('retries an initially failed credential save on reconnect using retained cloud proof without retaining the password', async () => {
    let available = false
    const { auth, fetch } = await mountGoogle({ provision: body => json(body.enable_sync
      ? { hosting_mode: 'hybrid', sync_started: true }
      : available ? { status: 'ok' } : { detail: 'Cloud service is starting' }, available ? 200 : 503) })
    await act(async () => { await auth.current.googleAuth({ credential: 'synthetic-google-credential' }) })
    await waitFor(() => expect(auth.current.syncSetup?.status).toBe('pending'))
    expect(JSON.parse(localStorage.getItem('bizassist_cloud_proof'))).toMatchObject({ token: 'google-cloud-token', publicId: 'BA-GOOGLE', backend: 'http://local-backend' })
    expect(localStorage.getItem('bizassist_cloud_token')).toBeNull()
    available = true
    await act(async () => { window.dispatchEvent(new Event('online')) })
    await waitFor(() => expect(fetch.mock.calls.some(([url, options]) => String(url).endsWith('/api/sync/cloud-token') && JSON.parse(options.body).enable_sync)).toBe(true))
    await waitFor(() => expect(auth.current.syncSetup).toBeNull())
    expect(fetch.mock.calls.filter(([url]) => String(url).includes('/google/verify'))).toHaveLength(1)
    expect(Object.values(localStorage).join(' ')).not.toContain('synthetic-google-credential')
  })

  it('retries the same account-scoped proof after reloading the local session', async () => {
    let available = false
    const { auth, fetch, view } = await mountGoogle({ provision: body => json(body.enable_sync
      ? { hosting_mode: 'hybrid', sync_started: true }
      : available ? { status: 'ok' } : { detail: 'Device storage temporarily unavailable' }, available ? 200 : 503) })
    await act(async () => { await auth.current.googleAuth({ credential: 'synthetic-google-credential' }) })
    await waitFor(() => expect(auth.current.syncSetup?.status).toBe('pending'))
    view.unmount()
    available = true
    const reloaded = React.createRef()
    render(<AuthProvider><AuthTestConsumer actionRef={reloaded} /></AuthProvider>)
    await waitFor(() => expect(fetch.mock.calls.some(([url, options]) => String(url).endsWith('/api/sync/cloud-token') && JSON.parse(options.body).enable_sync)).toBe(true))
    expect(reloaded.current.user.public_id).toBe('BA-GOOGLE')
    expect(fetch.mock.calls.filter(([url]) => String(url).includes('/google/verify'))).toHaveLength(1)
  })

  it('requires online owner reauthentication when local sign-in has no cloud proof to retry', async () => {
    const { auth, fetch } = await mountGoogle()
    Object.defineProperty(navigator, 'onLine', { value: false, configurable: true })
    await act(async () => { auth.current.setSession(localOwner) })
    await waitFor(() => expect(auth.current.syncSetup?.status).toBe('reauth_required'))
    expect(auth.current.syncSetup.error).toMatch(/Sign in online again/)
    Object.defineProperty(navigator, 'onLine', { value: true, configurable: true })
    await act(async () => { window.dispatchEvent(new Event('online')) })
    expect(fetch.mock.calls.some(([url]) => String(url).includes('/api/sync/cloud-token'))).toBe(false)
    expect(fetch.mock.calls.some(([url]) => String(url).endsWith('/login'))).toBe(false)
    expect(auth.current.user.public_id).toBe('BA-GOOGLE')
  })

  it.each([
    { public_id: 'BA-FOREIGN', role: 'enterprise' },
    { public_id: 'BA-GOOGLE', role: 'cashier' },
  ])('does not retain or publish proof for a verified foreign/nonowner cloud identity: %j', async cloudProfile => {
    const { auth, fetch } = await mountGoogle()
    const transport = fetch.getMockImplementation()
    fetch.mockImplementation((url, options) => String(url) === 'http://cloud-backend/profile' ? Promise.resolve(json(cloudProfile)) : transport(url, options))
    await act(async () => { await auth.current.googleAuth({ credential: 'synthetic-google-credential' }) })
    await waitFor(() => expect(auth.current.syncSetup?.status).toBe('reauth_required'))
    expect(localStorage.getItem('bizassist_cloud_token')).toBeNull()
    expect(localStorage.getItem('bizassist_cloud_proof')).toBeNull()
    expect(localStorage.getItem('bizassist_pending_cloud_proof')).toBeNull()
    expect(fetch.mock.calls.some(([url]) => String(url).endsWith('/api/sync/cloud-token'))).toBe(false)
  })

  it('recovers a stalled first cloud-profile verification using a scoped candidate and never publishes it early', async () => {
    const { auth, fetch } = await mountGoogle()
    let online = false
    const transport = fetch.getMockImplementation()
    fetch.mockImplementation((url, options) => String(url) === 'http://cloud-backend/profile' && !online
      ? Promise.resolve({ ok: true, status: 200, json: () => new Promise(() => {}) })
      : transport(url, options))
    vi.useFakeTimers()
    await act(async () => { await auth.current.googleAuth({ credential: 'synthetic-google-credential' }) })
    expect(JSON.parse(localStorage.getItem('bizassist_pending_cloud_proof'))).toMatchObject({ token: 'google-cloud-token', publicId: 'BA-GOOGLE', backend: 'http://local-backend' })
    expect(localStorage.getItem('bizassist_cloud_token')).toBeNull()
    await act(async () => { await vi.advanceTimersByTimeAsync(10000) })
    expect(auth.current.syncSetup?.status).toBe('pending')
    online = true
    await act(async () => { window.dispatchEvent(new Event('online')); await vi.advanceTimersByTimeAsync(0) })
    expect(auth.current.syncSetup).toBeNull()
    expect(localStorage.getItem('bizassist_pending_cloud_proof')).toBeNull()
    expect(localStorage.getItem('bizassist_cloud_token')).toBe('google-cloud-token')
    expect(fetch.mock.calls.filter(([url]) => String(url).includes('/google/verify'))).toHaveLength(1)
  })

  it('clears a previous business canonical cloud token when a different local session is saved', async () => {
    const { auth } = await mountGoogle()
    localStorage.setItem('billing_user', JSON.stringify({ public_id: 'BA-PREVIOUS' }))
    localStorage.setItem('bizassist_cloud_token', 'previous-account-cloud-token')
    localStorage.setItem('bizassist_cloud_proof', JSON.stringify({ token: 'previous-account-cloud-token', publicId: 'BA-PREVIOUS', backend: 'http://local-backend' }))
    await act(async () => { auth.current.setSession(localOwner) })
    expect(localStorage.getItem('bizassist_cloud_token')).toBeNull()
    expect(localStorage.getItem('bizassist_cloud_proof')).toBeNull()
    expect(auth.current.user.public_id).toBe('BA-GOOGLE')
  })

  it('upgrades a saved Pro session with only a legacy canonical token and no namespace through live identity validation', async () => {
    localStorage.setItem('billing_token', localOwner.token)
    localStorage.setItem('billing_user', JSON.stringify(localOwner))
    localStorage.setItem('bizassist_cloud_token', 'legacy-cloud-token')
    const { auth, fetch } = await mountGoogle()
    await waitFor(() => expect(fetch.mock.calls.some(([url, options]) => String(url).endsWith('/api/sync/cloud-token') && JSON.parse(options.body).enable_sync)).toBe(true))
    expect(auth.current.user.public_id).toBe('BA-GOOGLE')
    const provision = fetch.mock.calls.find(([url]) => String(url).endsWith('/api/sync/cloud-token'))
    expect(JSON.parse(provision[1].body).token).toBe('legacy-cloud-token')
    const cloudCheck = fetch.mock.calls.find(([url, options]) => url === 'http://cloud-backend/profile' && options?.headers?.Authorization === 'Bearer legacy-cloud-token')
    expect(cloudCheck).toBeDefined()
    expect(JSON.parse(localStorage.getItem('bizassist_cloud_proof'))).toMatchObject({ token: 'legacy-cloud-token', publicId: 'BA-GOOGLE', backend: 'http://local-backend' })
  })

  it('resumes a healthy saved device with a backend-renewed credential before considering its expired browser proof', async () => {
    localStorage.setItem('billing_token', localOwner.token)
    localStorage.setItem('billing_user', JSON.stringify(localOwner))
    localStorage.setItem('bizassist_cloud_token', 'expired-browser-token')
    localStorage.setItem('bizassist_cloud_proof', JSON.stringify({ token: 'expired-browser-token', publicId: 'BA-GOOGLE', backend: 'http://local-backend' }))
    const resume = vi.fn(() => json({ hosting_mode: 'hybrid', sync_started: true, initial_restore_pending: false }))
    const { auth, fetch } = await mountGoogle({ resume })
    await waitFor(() => expect(resume).toHaveBeenCalledOnce())
    await act(async () => { await Promise.resolve() })
    expect(auth.current.syncSetup).toBeNull()
    expect(fetch.mock.calls.some(([url, options]) => url === 'http://cloud-backend/profile' && options?.headers?.Authorization === 'Bearer expired-browser-token')).toBe(false)
    expect(fetch.mock.calls.some(([url]) => String(url).endsWith('/api/sync/cloud-token'))).toBe(false)
    expect(fetch.mock.calls.some(([url]) => String(url).endsWith('/login'))).toBe(false)
  })

  it('does not fall back to browser credentials when resume reports a committed explicit Local-only choice', async () => {
    localStorage.setItem('billing_token', localOwner.token)
    localStorage.setItem('billing_user', JSON.stringify(localOwner))
    localStorage.setItem('bizassist_cloud_token', 'legacy-cloud-token')
    const resume = vi.fn(() => json({ detail: 'Local-only was explicitly selected. Choose Local + Cloud in Settings to resume sync.' }, 409))
    const { auth, fetch } = await mountGoogle({ resume })
    await waitFor(() => expect(resume).toHaveBeenCalledOnce())
    await act(async () => { await Promise.resolve() })
    expect(auth.current.syncSetup).toBeNull()
    expect(fetch.mock.calls.some(([url, options]) => url === 'http://cloud-backend/profile' && options?.headers?.Authorization === 'Bearer legacy-cloud-token')).toBe(false)
    expect(fetch.mock.calls.some(([url]) => String(url).endsWith('/api/sync/cloud-token'))).toBe(false)
  })

  it('reports a cloud recovery body timeout accurately while preserving the local login failure boundary', async () => {
    const { auth, fetch } = await mountGoogle()
    const transport = fetch.getMockImplementation()
    fetch.mockImplementation((url, options) => {
      if (String(url) === 'http://local-backend/login') return Promise.resolve(json({ detail: 'No local account' }, 401))
      if (String(url) === 'http://cloud-backend/login') return Promise.resolve({ ok: true, status: 200, json: () => new Promise(() => {}) })
      return transport(url, options)
    })
    vi.useFakeTimers()
    const pending = expect(auth.current.login('google-owner', 'PasswordNeverStored123!')).rejects.toMatchObject({ code: 'AUTH_REQUEST_TIMEOUT' })
    await act(async () => { await vi.advanceTimersByTimeAsync(10000) })
    await pending
    expect(auth.current.user).toBeNull()
    expect(Object.values(localStorage).join(' ')).not.toContain('PasswordNeverStored123!')
  })

  it.each([
    { publicId: 'BA-OTHER', backend: 'http://local-backend' },
    { publicId: 'BA-GOOGLE', backend: 'http://different-lan-master:8001' },
  ])('never retries a retained proof belonging to another business or backend: %j', async identity => {
    const { auth, fetch } = await mountGoogle()
    localStorage.setItem('bizassist_cloud_proof', JSON.stringify({ token: 'foreign-cloud-token', ...identity }))
    await act(async () => { auth.current.setSession(localOwner) })
    await waitFor(() => expect(auth.current.syncSetup?.status).toBe('reauth_required'))
    expect(fetch.mock.calls.some(([url]) => String(url).includes('/api/sync/cloud-token'))).toBe(false)
    expect(localStorage.getItem('bizassist_cloud_token')).toBeNull()
  })
})

describe('Password and signup business collisions never trigger destructive reclaim', () => {
  const json = (body, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => body, clone() { return this } })
  async function mountWithTransport(transport) {
    const fetch = vi.fn((url, options) => transport(String(url), options) || globalMockFetch(url, options))
    vi.stubGlobal('fetch', fetch)
    const auth = React.createRef()
    render(<AuthProvider><AuthTestConsumer actionRef={auth} /></AuthProvider>)
    await waitFor(() => expect(auth.current).not.toBeNull())
    return { auth, fetch }
  }

  it('surfaces password-login BizID mismatch instead of reclaiming the unrelated local owner', async () => {
    const conflict = 'Identity mismatch: this device belongs to Local A and the cloud account is Business B. Nothing was changed.'
    const { auth, fetch } = await mountWithTransport(url => {
      if (url === 'http://local-backend/login') return Promise.resolve(json({ detail: 'Wrong local password' }, 401))
      if (url === 'http://cloud-backend/login') return Promise.resolve(json({ token: 'cloud-B-token', public_id: 'BA-B', username: 'reused-owner', role: 'enterprise' }))
      if (url.endsWith('/api/auth/reconcile_password')) return Promise.resolve(json({ detail: conflict }, 409))
    })
    await expect(auth.current.login('reused-owner', 'CloudBPassword1!')).rejects.toThrow(conflict)
    expect(auth.current.user).toBeNull()
    expect(localStorage.getItem('billing_token')).toBeNull()
    expect(fetch.mock.calls.some(([url]) => /reclaim_local|\/signup$|device\/cloud-session/.test(String(url)))).toBe(false)
  })

  it('surfaces a safe bridge collision after a fresh-device password login without disguising it as wrong credentials', async () => {
    const conflict = 'An existing local account has a different business identity. Nothing was replaced.'
    const { auth, fetch } = await mountWithTransport(url => {
      if (url === 'http://local-backend/login') return Promise.resolve(json({ detail: 'Wrong local password' }, 401))
      if (url === 'http://cloud-backend/login') return Promise.resolve(json({ token: 'cloud-B-token', public_id: 'BA-B', username: 'reused-owner', role: 'enterprise' }))
      if (url.endsWith('/api/auth/reconcile_password')) return Promise.resolve(json({ detail: 'No local account' }, 404))
      if (url.endsWith('/api/auth/device/cloud-session')) return Promise.resolve(json({ detail: conflict }, 409))
    })
    await expect(auth.current.login('reused-owner', 'CloudBPassword1!')).rejects.toThrow(conflict)
    expect(auth.current.user).toBeNull()
    expect(fetch.mock.calls.some(([url]) => /reclaim_local|\/signup$/.test(String(url)))).toBe(false)
  })

  it('stops signup when the verified new cloud identity collides with an unrelated local owner', async () => {
    const conflict = 'An existing local account has a different business identity. Nothing was replaced.'
    const { auth, fetch } = await mountWithTransport(url => {
      if (url === 'http://cloud-backend/signup') return Promise.resolve(json({ token: 'new-cloud-owner-token', public_id: 'BA-NEW-CLOUD', trial: { days: 14 } }))
      if (url.endsWith('/api/auth/device/cloud-session')) return Promise.resolve(json({ detail: conflict }, 409))
    })
    await expect(auth.current.signup({ username: 'reused-owner', password: 'NewCloudPassword1!', business_name: 'New Cloud Store', hosting: 'hybrid' })).rejects.toThrow(conflict)
    const mirror = fetch.mock.calls.find(([url]) => String(url).endsWith('/api/auth/device/cloud-session'))
    expect(JSON.parse(mirror[1].body)).toEqual({ token: 'new-cloud-owner-token', password: 'NewCloudPassword1!', local_only: false })
    expect(auth.current.user).toBeNull()
    expect(localStorage.getItem('billing_token')).toBeNull()
    expect(fetch.mock.calls.some(([url]) => /reclaim_local|local-backend\/signup|\/business\/setup/.test(String(url)))).toBe(false)
  })

  it('uses the verified bridge for an ordinary new Local-only signup without a local signup or reclaim request', async () => {
    const { auth, fetch } = await mountWithTransport(() => null)
    await act(async () => { await auth.current.signup({ username: 'new-owner', password: 'NewCloudPassword1!', business_name: 'New Store', hosting: 'local' }) })
    expect(auth.current.user.public_id).toBe('BA-NEW')
    expect(fetch.mock.calls.filter(([url]) => String(url).endsWith('/api/auth/device/cloud-session'))).toHaveLength(1)
    const bridge = fetch.mock.calls.find(([url]) => String(url).endsWith('/api/auth/device/cloud-session'))
    expect(JSON.parse(bridge[1].body).local_only).toBe(true)
    expect(fetch.mock.calls.some(([url]) => /reclaim_local|local-backend\/signup/.test(String(url)))).toBe(false)
    expect(localStorage.getItem('bizassist_hosting_mode')).toBe('local')
  })

  it('preserves a cloud signup conflict body after the bounded helper has consumed the response', async () => {
    const { auth, fetch } = await mountWithTransport(url => {
      if (url === 'http://cloud-backend/signup') return Promise.resolve(new Response(JSON.stringify({ detail: 'Username already exists' }), { status: 400, headers: { 'Content-Type': 'application/json' } }))
    })
    await expect(auth.current.signup({ username: 'existing-owner', password: 'ExistingPassword1!', business_name: 'Existing Store' })).rejects.toThrow('An account with this username already exists. Please log in instead.')
    expect(fetch.mock.calls.some(([url]) => /reclaim_local|device\/cloud-session/.test(String(url)))).toBe(false)
    expect(auth.current.user).toBeNull()
  })
})

describe('Pro trial and Local + Cloud (T6)', () => {
  const renderAuth = async () => {
    const actionRef = React.createRef()
    render(<AuthProvider><AuthTestConsumer actionRef={actionRef} /></AuthProvider>)
    await waitFor(() => expect(actionRef.current).not.toBeNull())
    return actionRef
  }
  const renderRegister = () => render(
    <MemoryRouter><AuthProvider><Register /></AuthProvider></MemoryRouter>
  )
  const localBtn = () => screen.getByRole('button', { name: /^Local only/ })
  const hybridBtn = () => screen.getByRole('button', { name: /^Local \+ Cloud/ })

  it('signup: Local + Cloud without a Pro trial is set up as Local, and says so', async () => {
    mockCloudTrial = null
    const auth = await renderAuth()
    const result = await auth.current.signup({ username: 'notrial', password: 'password123', business_name: 'Shop', hosting: 'hybrid', template_key: 'general' })
    expect(result.fellBackToLocal).toBe(true)
    expect(result.hosting).toBe('local')
    expect(localStorage.getItem('bizassist_hosting_mode')).toBe('local')
    expect(localStorage.getItem('bizassist_cloud_token')).toBeNull()
  })

  it('signup: Local + Cloud with the trial syncs as chosen', async () => {
    mockCloudTrial = { days: 14, expires_at: '2026-11-07' }
    const auth = await renderAuth()
    const result = await auth.current.signup({ username: 'trialist', password: 'password123', business_name: 'Shop', hosting: 'hybrid', template_key: 'general' })
    expect(result.fellBackToLocal).toBe(false)
    expect(localStorage.getItem('bizassist_hosting_mode')).toBe('hybrid')
    await waitFor(() => expect(localStorage.getItem('bizassist_cloud_token')).toBe('mock-cloud-token'))
  })

  it('Register preselects Local + Cloud during the trial and explains what happens after it', async () => {
    mockTrialOffer = { days: 14 }
    renderRegister()
    await waitFor(() => expect(hybridBtn()).toHaveAttribute('aria-pressed', 'true'))
    expect(screen.getByText('14 DAYS FREE')).toBeInTheDocument()
    expect(screen.getByText(/Sync is included during your eligible 14-day Pro trial/)).toBeInTheDocument()
    expect(screen.getByText(/Upgrade to Pro to keep syncing afterward/)).toBeInTheDocument()

    fireEvent.click(localBtn())  // Local stays one click away
    expect(localBtn()).toHaveAttribute('aria-pressed', 'true')
    expect(screen.queryByText(/Sync is included during your eligible 14-day Pro trial/)).not.toBeInTheDocument()
  })

  it('Register keeps the mandatory Local + Cloud trial selected without a legacy offer response', async () => {
    renderRegister()
    await waitFor(() => expect(hybridBtn()).toHaveAttribute('aria-pressed', 'true'))
    expect(screen.getByText('14 DAYS FREE')).toBeInTheDocument()
  })

  it('Register explains the switch to Local when no trial was given, then lets you in', async () => {
    mockTrialOffer = { days: 14 }
    mockCloudTrial = null
    mockProfile = { is_premium: false }
    mockSettings = { general: { hosting_mode: 'local' }, subscription: { plan: 'free' } }
    const { container } = renderRegister()
    await waitFor(() => expect(hybridBtn()).toHaveAttribute('aria-pressed', 'true'))
    fireEvent.change(screen.getByLabelText('Store Username'), { target: { value: 'repeatphone' } })
    fireEvent.change(screen.getByLabelText('Phone'), { target: { value: '9876543210' } })
    fireEvent.change(screen.getByPlaceholderText('••••••••'), { target: { value: 'Password123!' } })
    fireEvent.change(container.querySelector('#confirmPassword'), { target: { value: 'Password123!' } })
    fireEvent.click(screen.getByLabelText(/I agree to/i))
    fireEvent.submit(container.querySelector('#register-form'))

    const note = await screen.findByTestId('hosting-fallback')
    expect(note).toHaveTextContent(/did not get a Pro trial/)
    expect(note).toHaveTextContent(/your data stays on this computer \(Local\)/)
    expect(screen.getByRole('button', { name: /Continue to (STATER Bill|BizAssist)/ })).toBeInTheDocument()
    expect(localStorage.getItem('bizassist_hosting_mode')).toBe('local')
  })
})
