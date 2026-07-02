// Tests for the counter mode switcher + sticky-mode hook plumbing (Chunk A):
//   • hidden for single-type businesses
//   • renders one pill per registered type, active = current mode
//   • switching writes localStorage ('pos.counter_mode') and dispatches the
//     live-update event; selecting the primary clears the override
//   • useBillingProfile follows the device mode and refetches per mode
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, waitFor, fireEvent, renderHook, act } from '@testing-library/react'

const apiGet = vi.fn()
vi.mock('../../api/client', () => ({
  api: { get: (...a) => apiGet(...a), post: vi.fn(() => Promise.resolve({})), put: vi.fn() },
}))

import CounterModeSwitcher, { humanizeModeKey } from '../../components/sales/CounterModeSwitcher'
import { useBillingProfile, setCounterMode, getCounterMode, clearBillingProfileCache } from '../../hooks/useBillingProfile'

const profileFor = (mode, types) => ({
  profile: {
    mode_key: mode, business_types: types,
    customer_required: false, terminology: {}, entry_mode: 'search',
  },
})

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  clearBillingProfileCache()
})

afterEach(cleanup)

describe('humanizeModeKey', () => {
  it('formats vertical keys for display', () => {
    expect(humanizeModeKey('supermarket')).toBe('Supermarket')
    expect(humanizeModeKey('b2b_supplier')).toBe('B2B Supplier')
    expect(humanizeModeKey('repair')).toBe('Repair')
  })
})

describe('CounterModeSwitcher', () => {
  it('renders nothing for a single-type business', async () => {
    apiGet.mockResolvedValue(profileFor('supermarket', ['supermarket']))
    render(<CounterModeSwitcher />)
    await waitFor(() => expect(apiGet).toHaveBeenCalled())
    expect(screen.queryByTestId('counter-mode-switcher')).not.toBeInTheDocument()
  })

  it('shows a pill per type with the current mode active', async () => {
    apiGet.mockResolvedValue(profileFor('supermarket', ['supermarket', 'repair']))
    render(<CounterModeSwitcher />)
    await waitFor(() => screen.getByTestId('counter-mode-switcher'))
    const active = screen.getByRole('tab', { name: 'Supermarket' })
    expect(active).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'Repair' })).toHaveAttribute('aria-selected', 'false')
  })

  it('switching to a secondary type persists the sticky device mode', async () => {
    apiGet.mockImplementation((path, q) =>
      Promise.resolve(q?.mode === 'repair'
        ? profileFor('repair', ['supermarket', 'repair'])
        : profileFor('supermarket', ['supermarket', 'repair'])))
    render(<CounterModeSwitcher />)
    await waitFor(() => screen.getByTestId('counter-mode-switcher'))

    fireEvent.click(screen.getByRole('tab', { name: 'Repair' }))
    expect(getCounterMode()).toBe('repair')
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Repair' })).toHaveAttribute('aria-selected', 'true'))

    // back to primary → override cleared (primary needs no localStorage entry)
    fireEvent.click(screen.getByRole('tab', { name: 'Supermarket' }))
    expect(getCounterMode()).toBeNull()
  })
})

describe('useBillingProfile mode plumbing', () => {
  it('follows the sticky device mode and refetches on switch', async () => {
    apiGet.mockImplementation((path, q) =>
      Promise.resolve(q?.mode === 'repair'
        ? profileFor('repair', ['supermarket', 'repair'])
        : profileFor('supermarket', ['supermarket', 'repair'])))

    const r = renderHook(() => useBillingProfile())
    await waitFor(() => expect(r.result.current.profile?.mode_key).toBe('supermarket'))

    act(() => setCounterMode('repair'))
    await waitFor(() => expect(r.result.current.profile?.mode_key).toBe('repair'))
    expect(apiGet).toHaveBeenCalledWith('/business/billing-profile', { mode: 'repair' })

    act(() => setCounterMode(null))
    await waitFor(() => expect(r.result.current.profile?.mode_key).toBe('supermarket'))
  })

  it('per-mode results are cached (no duplicate requests)', async () => {
    apiGet.mockResolvedValue(profileFor('supermarket', ['supermarket']))
    const a = renderHook(() => useBillingProfile())
    await waitFor(() => expect(a.result.current.loading).toBe(false))
    const b = renderHook(() => useBillingProfile())
    await waitFor(() => expect(b.result.current.loading).toBe(false))
    expect(apiGet).toHaveBeenCalledTimes(1)
  })

  it('explicit mode argument wins over the device override', async () => {
    localStorage.setItem('pos.counter_mode', 'repair')
    apiGet.mockResolvedValue(profileFor('services', ['services']))
    const r = renderHook(() => useBillingProfile('services'))
    await waitFor(() => expect(r.result.current.loading).toBe(false))
    expect(apiGet).toHaveBeenCalledWith('/business/billing-profile', { mode: 'services' })
  })
})
