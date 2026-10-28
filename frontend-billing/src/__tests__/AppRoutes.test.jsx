import React from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'

const auth = vi.hoisted(() => ({ user: null }))
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ user: auth.user, loading: false }),
  AuthProvider: ({ children }) => children,
}))
vi.mock('../pages/Login', () => ({ default: () => <h1>Sign in</h1> }))
vi.mock('../pages/Home', () => ({ default: () => <h1>Home</h1> }))
vi.mock('../pages/Sales', () => ({ default: () => <h1>Billing counter</h1> }))
vi.mock('../layouts/AppLayout', () => ({ default: ({ children }) => children }))
vi.mock('../pages/Dashboard', () => ({ default: () => <h1>Business dashboard</h1> }))
vi.mock('../pages/Settings', () => ({ default: () => <h1>App settings</h1> }))

import { AppRoutes } from '../App'

function Location() {
  const location = useLocation()
  return <output aria-label="Current page">{location.pathname}{location.search}</output>
}

function renderAt(path) {
  return render(<MemoryRouter initialEntries={[path]}><AppRoutes /><Location /></MemoryRouter>)
}

beforeEach(() => { auth.user = null })
afterEach(cleanup)

describe('deferred workspace routes', () => {
  it('redirects an unauthenticated workspace request to sign-in', async () => {
    renderAt('/dashboard')
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.getByLabelText('Current page')).toHaveTextContent('/login')
    expect(screen.queryByRole('heading', { name: 'Business dashboard' })).not.toBeInTheDocument()
  })

  it('opens the requested deferred workspace after authentication', async () => {
    auth.user = { id: 1, role: 'owner' }
    renderAt('/dashboard')
    expect(await screen.findByRole('heading', { name: 'Business dashboard' })).toBeInTheDocument()
    expect(screen.getByLabelText('Current page')).toHaveTextContent('/dashboard')
  })

  it('keeps the legacy profile redirect inside the settings workspace', async () => {
    auth.user = { id: 1, role: 'owner' }
    renderAt('/profile')
    expect(await screen.findByRole('heading', { name: 'App settings' })).toBeInTheDocument()
    expect(screen.getByLabelText('Current page')).toHaveTextContent('/settings?tab=profile')
  })

  it('keeps the offline billing counter immediately available as a core route', () => {
    auth.user = { id: 1, role: 'cashier' }
    renderAt('/sales')
    expect(screen.getByRole('heading', { name: 'Billing counter' })).toBeInTheDocument()
    expect(screen.queryByRole('status', { name: 'Loading BizAssist Billing' })).not.toBeInTheDocument()
  })
})
