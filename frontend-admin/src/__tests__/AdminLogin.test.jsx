import React from 'react'
import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import AdminLogin from '../pages/admin/AdminLogin'

const auth = vi.hoisted(() => ({ adminLogin: vi.fn() }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => auth }))

function mount() {
  return render(<MemoryRouter initialEntries={['/admin/login']}><Routes>
    <Route path="/admin/login" element={<AdminLogin />} />
    <Route path="/admin/dashboard" element={<h1>Operations overview</h1>} />
    <Route path="/admin/businesses" element={<h1>Business workspace</h1>} />
  </Routes></MemoryRouter>)
}

beforeEach(() => { auth.adminLogin.mockReset(); sessionStorage.clear() })
afterEach(() => { cleanup(); sessionStorage.clear(); vi.unstubAllEnvs() })

describe('admin sign-in workspace', () => {
  it('keeps credentials through the authenticator challenge and returns to the requested admin page', async () => {
    auth.adminLogin.mockRejectedValueOnce(new Error('2FA code required')).mockResolvedValueOnce({})
    sessionStorage.setItem('admin_return_path', '/admin/businesses?plan=pro')
    mount()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Admin Username'), 'operator')
    await user.type(screen.getByLabelText('Password'), 'correct-password')
    await user.click(screen.getByRole('button', { name: 'Admin Sign In' }))

    const code = await screen.findByLabelText('Authenticator Code')
    expect(code).toHaveFocus()
    expect(screen.getByLabelText('Admin Username')).toHaveValue('operator')
    expect(screen.getByLabelText('Password')).toHaveValue('correct-password')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    await user.type(code, '12x3456')
    expect(code).toHaveValue('123456')
    await user.click(screen.getByRole('button', { name: 'Admin Sign In' }))

    await screen.findByRole('heading', { name: 'Business workspace' })
    expect(auth.adminLogin).toHaveBeenNthCalledWith(1, 'operator', 'correct-password', undefined)
    expect(auth.adminLogin).toHaveBeenNthCalledWith(2, 'operator', 'correct-password', '123456')
    expect(sessionStorage.getItem('admin_return_path')).toBeNull()
  })

  it('retains a retryable error, password visibility control and separate merchant sign-in destination', async () => {
    vi.stubEnv('VITE_BILLING_URL', 'https://billing.example.test')
    auth.adminLogin.mockRejectedValue(new Error('Invalid administrator credentials.'))
    mount()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Admin Username'), 'operator')
    const password = screen.getByLabelText('Password')
    await user.type(password, 'incorrect-password')
    await user.click(screen.getByRole('button', { name: 'Toggle password visibility' }))
    expect(password).toHaveAttribute('type', 'text')
    expect(screen.getByRole('button', { name: 'Toggle password visibility' })).toHaveAttribute('aria-pressed', 'true')
    await user.click(screen.getByRole('button', { name: 'Admin Sign In' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid administrator credentials.')
    expect(password).toHaveValue('incorrect-password')
    expect(screen.getByRole('button', { name: 'Admin Sign In' })).toBeEnabled()
    expect(screen.getByRole('link', { name: 'Go to STATER Bill sign in' })).toHaveAttribute('href', 'https://billing.example.test/login')
  })

  it('prevents duplicate submissions while the sign-in request is pending', async () => {
    let resolve
    auth.adminLogin.mockReturnValue(new Promise(done => { resolve = done }))
    mount()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Admin Username'), 'operator')
    await user.type(screen.getByLabelText('Password'), 'correct-password')
    await user.click(screen.getByRole('button', { name: 'Admin Sign In' }))
    const pending = screen.getByRole('button', { name: 'Signing in...' })
    expect(pending).toBeDisabled()
    expect(pending.closest('form')).toHaveAttribute('aria-busy', 'true')
    await user.click(pending)
    expect(auth.adminLogin).toHaveBeenCalledTimes(1)
    await act(async () => { resolve({}) })
    await screen.findByRole('heading', { name: 'Operations overview' })
  })
})
