import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import AdminBusinesses from '../pages/admin/AdminBusinesses'
import { DialogProvider } from '../contexts/DialogContext'

const auth = vi.hoisted(() => ({ authFetch: vi.fn() }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => auth }))
const business = {
  id: 7, username: 'merchant', business_name: 'Seven Traders', total_revenue: 25,
  email: 'owner@example.com', pan: 'ABCDE1234F', state_code: '29',
  logo: 'https://example.com/logo.png', counter_prefix: 'OW', hosting_mode: 'local',
  plan: 'pro', plan_status: 'trial', address: 'Old street',
}
const response = body => ({ ok: true, json: async () => body })
beforeEach(() => {
  auth.authFetch.mockReset().mockImplementation(async (url, options) => {
    if (options?.method === 'PUT') return response({ status: 'success' })
    if (url.endsWith('/admin/businesses')) return response([business])
    return response([])
  })
})
afterEach(cleanup)

async function openEditor() {
  render(<DialogProvider><MemoryRouter><AdminBusinesses /></MemoryRouter></DialogProvider>)
  await screen.findByRole('button', { name: 'Inspect' })
  await userEvent.click(screen.getByLabelText('More actions for Seven Traders'))
  await userEvent.click(screen.getByRole('button', { name: 'Edit', exact: true }))
  return screen.getByRole('dialog', { name: 'Edit Business & Owner Profile' })
}

it('hydrates every owner field and submits only the changed address without changing the trial', async () => {
  await openEditor()
  expect(screen.getByLabelText('PAN Number')).toHaveValue('ABCDE1234F')
  expect(screen.getByLabelText('State Code')).toHaveValue('29')
  expect(screen.getByLabelText('Counter Prefix')).toHaveValue('OW')
  expect(screen.getByLabelText('Business Logo (URL or image data)')).toHaveValue(business.logo)
  expect(screen.getByLabelText('Store Storage Setup')).toHaveValue('local')
  expect(screen.queryByLabelText('Subscription Plan')).toBeNull()
  fireEvent.change(screen.getByLabelText('Trade / Physical Address'), { target: { value: 'New street' } })
  await userEvent.click(screen.getByRole('button', { name: 'Save Business Details' }))
  await waitFor(() => expect(auth.authFetch.mock.calls.some(([, options]) => options?.method === 'PUT')).toBe(true))
  const request = auth.authFetch.mock.calls.find(([, options]) => options?.method === 'PUT')
  expect(JSON.parse(request[1].body)).toEqual({ address: 'New street' })
})

it('requires an owner email for password changes and preserves password spaces', async () => {
  await openEditor()
  const email = screen.getByLabelText('Owner Email')
  expect(email).not.toBeRequired()
  fireEvent.change(screen.getByLabelText('New Password (leave blank to keep current)'), { target: { value: ' StrongPass1 ' } })
  expect(email).toBeRequired()
  await userEvent.click(screen.getByRole('button', { name: 'Save Business Details' }))
  const request = auth.authFetch.mock.calls.find(([, options]) => options?.method === 'PUT')
  expect(JSON.parse(request[1].body)).toEqual({ password: ' StrongPass1 ' })
})

it('keeps unchanged or unreported fields out of an ordinary save', async () => {
  await openEditor()
  await userEvent.click(screen.getByRole('button', { name: 'Save Business Details' }))
  const request = auth.authFetch.mock.calls.find(([, options]) => options?.method === 'PUT')
  expect(JSON.parse(request[1].body)).toEqual({})
})
