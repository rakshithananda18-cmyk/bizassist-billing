// @vitest-environment jsdom
import React from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
const auth = vi.hoisted(() => ({ ownerLogin: vi.fn(), staffLogin: vi.fn(), googleLogin: vi.fn(), notice: null }))
const lookup = vi.hoisted(() => vi.fn())
const google = vi.hoisted(() => vi.fn())
vi.mock('../lib/auth', () => ({ useAuth: () => auth, lastBizId: () => '' }))
vi.mock('../lib/api', () => ({ api: { post: lookup } }))
vi.mock('../lib/googleAuth', () => ({ renderGoogleButton: google }))
vi.mock('../lib/theme', () => ({ getBillingUrl: path => 'https://billing.example' + path, getTheme: () => 'light', cycleTheme: () => 'dark' }))
import Login from './Login'
beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  google.mockResolvedValue(true)
})
afterEach(cleanup)
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
const business = (name = 'Sri Medicals', id = 'BA-ABC123', username = 'ravi') => ({
  found: true, business_name: name, public_id: id, has_staff: true,
  staff: [{ id: 12, name: 'Ravi Kumar', username }],
})
const findBusiness = identifier => {
  fireEvent.change(screen.getByLabelText('Business Identifier'), { target: { value: identifier } })
  fireEvent.click(screen.getByRole('button', { name: 'Find business' }))
}

describe('Field owner onboarding', () => {
  it('routes new owners to the shared Billing registration and trial flow', () => {
    render(<Login />)
    fireEvent.click(screen.getByRole('tab', { name: 'Owner Login' }))
    expect(screen.getByRole('link', { name: 'Register in Billing' }).getAttribute('href')).toBe('https://billing.example/register')
    expect(screen.getByText(/14-day Pro trial in Billing/)).toBeTruthy()
    expect(screen.queryByLabelText('Phone (optional)')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Create Account' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Sign In as Owner' })).toBeTruthy()
  })

  it('reveals field benefits on keyboard focus and dismisses them with Escape', () => {
    render(<Login />)
    const point = screen.getByRole('button', { name: 'Plan the day' })
    fireEvent.focus(point)
    expect(screen.getByRole('tooltip').textContent).toContain('routes, shops and daily assignments')
    fireEvent.keyDown(point, { key: 'Escape' })
    expect(screen.queryByRole('tooltip')).toBeNull()
  })

  it('selects an account from the confirmed business and submits its BizID', async () => {
    lookup.mockResolvedValue({ ...business(), staff: [...business().staff, { id: 13, name: 'Mina', username: 'mina' }] })
    render(<Login />)
    expect(screen.getByLabelText('Your Staff Account').disabled).toBe(true)
    findBusiness('owner@example.com')
    await screen.findByText('Sri Medicals')
    expect(lookup).toHaveBeenCalledWith('/api/auth/lookup-business', { identifier: 'owner@example.com' })
    expect(screen.getByRole('option', { name: 'Ravi Kumar (ravi)' })).toBeTruthy()
    fireEvent.change(screen.getByLabelText(/Your Staff Account/), { target: { value: 'mina' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'Fieldw0rk!' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start Shift' }))
    await waitFor(() => expect(auth.staffLogin).toHaveBeenCalledWith('BA-ABC123', 'mina', 'Fieldw0rk!'))
  })

  it('clears business, account and password immediately when the identifier changes', async () => {
    lookup.mockResolvedValue(business())
    render(<Login />)
    findBusiness('+919876543210')
    await screen.findByText('Sri Medicals')
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'Fieldw0rk!' } })
    fireEvent.change(screen.getByLabelText('Business Identifier'), { target: { value: 'another-owner' } })
    expect(screen.queryByText('Sri Medicals')).toBeNull()
    expect(screen.queryByRole('option', { name: 'Ravi Kumar (ravi)' })).toBeNull()
    expect(screen.getByLabelText('Password').value).toBe('')
    expect(screen.getByRole('button', { name: 'Start Shift' }).disabled).toBe(true)
    expect(auth.staffLogin).not.toHaveBeenCalled()
  })

  it('ignores an older lookup that finishes after the new business lookup', async () => {
    const oldLookup = deferred()
    lookup.mockImplementationOnce(() => oldLookup.promise).mockResolvedValueOnce(business('New business', 'BA-NEW123', 'mina'))
    render(<Login />)
    findBusiness('old-owner')
    findBusiness('new-owner')
    await screen.findByText('New business')
    await act(async () => oldLookup.resolve(business('Old business', 'BA-OLD123')))
    expect(screen.queryByText('Old business')).toBeNull()
    expect(screen.getByText('New business')).toBeTruthy()
    expect(screen.getByLabelText(/Your Staff Account/).value).toBe('mina')
  })

  it('does not retain a roster after a lookup failure', async () => {
    lookup.mockResolvedValueOnce(business()).mockRejectedValueOnce(new Error('Lookup unavailable'))
    render(<Login />)
    findBusiness('owner')
    await screen.findByText('Sri Medicals')
    fireEvent.click(screen.getByRole('button', { name: 'Find business' }))
    await screen.findByText('Lookup unavailable')
    expect(screen.queryByRole('option', { name: 'Ravi Kumar (ravi)' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Start Shift' }).disabled).toBe(true)
  })

  it('routes Google credentials through the auth provider and keeps password sign-in available', async () => {
    render(<Login />)
    fireEvent.click(screen.getByRole('tab', { name: 'Owner Login' }))
    await waitFor(() => expect(google).toHaveBeenCalled())
    await act(async () => google.mock.calls.at(-1)[1].onCredential('verified-google-id-token'))
    expect(auth.googleLogin).toHaveBeenCalledWith('verified-google-id-token')
    expect(lookup).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText('Username, Email, or Phone'), { target: { value: 'owner@example.com' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'Fieldw0rk!' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign In as Owner' }))
    await waitFor(() => expect(auth.ownerLogin).toHaveBeenCalledWith('owner@example.com', 'Fieldw0rk!'))
  })
})
