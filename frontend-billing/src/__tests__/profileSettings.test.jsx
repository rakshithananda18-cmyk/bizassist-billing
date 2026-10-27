import React from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const auth = vi.hoisted(() => ({ value: null }))
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => auth.value,
  useBusinessConfig: () => ({ config: {}, refreshConfig: vi.fn() }),
}))
vi.mock('../layouts/AppLayout', () => ({ default: ({ children }) => <div data-testid="app-layout">{children}</div> }))
vi.mock('../components/settings/AppearanceSettings', () => ({ default: () => <div>Appearance preferences</div> }))
vi.mock('../contexts/LockContext', () => ({ useLock: () => ({ hasLock: false }) }))

import Profile from '../pages/Profile'
import Settings from '../pages/Settings'

const PROFILE = {
  business_name: 'Sri Lakshmi Medicals', gstin: '29ABCDE1234F1Z5', pan: 'ABCDE1234F',
  phone: '9876543210', email: 'billing@example.com', address: 'Market Road, Bengaluru',
  state_code: '29', logo: '', upi_vpa: 'store@upi',
}

beforeEach(() => {
  auth.value = {
    user: { id: 1, role: 'owner' }, profile: PROFILE, fetchProfile: vi.fn(async () => {}),
    authFetch: vi.fn(async () => ({ ok: true, json: async () => ({ general: {} }) })),
  }
})
afterEach(cleanup)

describe('business profile in Settings', () => {
  it('saves edited business details and preserves every billing identity field', async () => {
    render(<Profile embedded />)
    fireEvent.change(screen.getByLabelText('Business name'), { target: { value: '  Lakshmi Pharmacy  ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save business profile' }))

    await screen.findByRole('status')
    expect(auth.value.authFetch).toHaveBeenCalledWith('/profile', expect.objectContaining({ method: 'PUT' }))
    expect(JSON.parse(auth.value.authFetch.mock.calls[0][1].body)).toEqual({ ...PROFILE, business_name: 'Lakshmi Pharmacy' })
    expect(auth.value.fetchProfile).toHaveBeenCalledOnce()
    expect(screen.queryByTestId('app-layout')).not.toBeInTheDocument()
  })

  it('keeps the form available and explains a failed profile save', async () => {
    auth.value.authFetch.mockResolvedValue({ ok: false, json: async () => ({ detail: 'GSTIN is already registered' }) })
    render(<Profile embedded />)
    fireEvent.click(screen.getByRole('button', { name: 'Save business profile' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('GSTIN is already registered')
    expect(screen.getByLabelText('GSTIN')).toHaveValue(PROFILE.gstin)
    expect(auth.value.fetchProfile).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Save business profile' })).toBeEnabled()
  })

  it('renders Profile within the Settings shell with its own save action', async () => {
    render(<MemoryRouter initialEntries={['/settings?tab=profile']}><Settings /></MemoryRouter>)
    expect(await screen.findByRole('heading', { name: 'Business profile' })).toBeInTheDocument()
    expect(screen.getAllByTestId('app-layout')).toHaveLength(1)
    expect(screen.queryByRole('button', { name: 'Save Changes' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save business profile' })).toBeInTheDocument()
  })

  it('keeps a cashier profile deep link within General preferences', async () => {
    auth.value.user = { id: 2, role: 'cashier' }
    render(<MemoryRouter initialEntries={['/settings?tab=profile']}><Settings /></MemoryRouter>)
    await waitFor(() => expect(screen.getByText('Appearance preferences')).toBeInTheDocument())
    expect(screen.queryByRole('heading', { name: 'Business profile' })).not.toBeInTheDocument()
    expect(screen.queryByText('Business Profile')).not.toBeInTheDocument()
  })
})
