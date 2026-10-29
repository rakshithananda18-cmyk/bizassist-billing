import React from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const auth = vi.hoisted(() => ({ signup: vi.fn() }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../config', () => ({ API_BASE: 'https://cloud-api.example', CLOUD_URL: 'https://cloud-api.example', IS_LOCAL_APP: false }))

import Register from '../pages/Register'
import { DESKTOP_DOWNLOAD_URL } from '../config/downloadApp'

const templates = [
  { key: 'general', label: 'General Business' },
  { key: 'hardware', label: 'Hardware / Electricals' },
  { key: 'b2b_supplier', label: 'B2B Supplier' },
]

beforeEach(() => {
  auth.signup.mockReset().mockResolvedValue({})
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ templates }) })))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const renderRegister = () => render(<MemoryRouter><Register /></MemoryRouter>)

describe('Cloud registration storage and business types', () => {
  it('blocks form submission without the required phone even when native validation is bypassed', async () => {
    const { container } = renderRegister()
    await screen.findByText('General Business')
    fireEvent.change(screen.getByPlaceholderText('e.g. Acme Corporation'), { target: { value: 'QA Business' } })
    fireEvent.change(screen.getByPlaceholderText('e.g. store'), { target: { value: 'qa_owner' } })
    fireEvent.change(container.querySelector('#password'), { target: { value: 'Password123!' } })
    fireEvent.change(container.querySelector('#confirmPassword'), { target: { value: 'Password123!' } })
    fireEvent.click(screen.getByLabelText(/I agree to the Terms/))
    fireEvent.submit(container.querySelector('#register-form'))
    expect(await screen.findByRole('alert')).toHaveTextContent(/valid phone number/i)
    expect(auth.signup).not.toHaveBeenCalled()
  })

  it('explains why an already used phone does not receive another trial', async () => {
    auth.signup.mockResolvedValue({ trialUnavailable: true })
    const { container } = renderRegister()
    await screen.findByText('General Business')
    fireEvent.change(screen.getByPlaceholderText('e.g. Acme Corporation'), { target: { value: 'QA Business' } })
    fireEvent.change(screen.getByPlaceholderText('e.g. store'), { target: { value: 'qa_repeat' } })
    fireEvent.change(container.querySelector('#password'), { target: { value: 'Password123!' } })
    fireEvent.change(container.querySelector('#confirmPassword'), { target: { value: 'Password123!' } })
    fireEvent.change(screen.getByLabelText('Phone'), { target: { value: '9876543210' } })
    fireEvent.click(screen.getByLabelText(/I agree to the Terms/))
    fireEvent.submit(container.querySelector('#register-form'))
    expect(await screen.findByTestId('hosting-fallback')).toHaveTextContent(/already used its first-time trial/i)
  })
  it('offers Local + Cloud in the browser and a disabled Local choice with a download', async () => {
    renderRegister()
    await screen.findByText('General Business')
    expect(screen.queryByRole('button', { name: /^Cloud / })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Local only/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /^Local \+ Cloud/ })).toBeEnabled()
    expect(screen.getByRole('button', { name: /^Local \+ Cloud/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText('14 DAYS FREE')).toBeInTheDocument()
    expect(screen.getByLabelText('Phone')).toBeRequired()
    expect(screen.getByText(/This browser uses the cloud database/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Download app for Local' })).toHaveAttribute('href', DESKTOP_DOWNLOAD_URL)
    expect(fetch.mock.calls.every(([url]) => !url.endsWith('/trial-offer'))).toBe(true)
  })

  it('highlights the desktop app download in cloud registration', async () => {
    renderRegister()
    await screen.findByText('General Business')
    expect(screen.getByRole('link', { name: /Download Desktop App/i })).toHaveAttribute('href', DESKTOP_DOWNLOAD_URL)
    expect(screen.getByText(/Recommended for POS & Counters/i)).toBeInTheDocument()
  })

  it('uses the cloud backend safely for the browser part of Local + Cloud', async () => {
    const { container } = renderRegister()
    await screen.findByText('General Business')
    fireEvent.change(screen.getByPlaceholderText('e.g. Acme Corporation'), { target: { value: 'QA Business' } })
    fireEvent.change(screen.getByPlaceholderText('e.g. store'), { target: { value: 'qa_owner' } })
    fireEvent.change(container.querySelector('#password'), { target: { value: 'Password123!' } })
    fireEvent.change(container.querySelector('#confirmPassword'), { target: { value: 'Password123!' } })
    fireEvent.change(screen.getByLabelText('Phone'), { target: { value: '9876543210' } })
    fireEvent.click(screen.getByLabelText(/I agree to the Terms/))
    fireEvent.submit(container.querySelector('#register-form'))
    await waitFor(() => expect(auth.signup).toHaveBeenCalledWith(expect.objectContaining({
      hosting: 'cloud', username: 'qa_owner', business_name: 'QA Business', phone: '+919876543210',
    })))
  })
})
