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
  it('shows cloud storage and explains disabled local options with a desktop download', async () => {
    renderRegister()
    await screen.findByText('General Business')
    expect(screen.getByRole('button', { name: /^Cloud Selected/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /^Cloud Selected/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: /^Local only/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /^Local \+ Cloud/ })).toBeDisabled()
    expect(screen.getByText(/this business uses the cloud database/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Download desktop app' })).toHaveAttribute('href', DESKTOP_DOWNLOAD_URL)
    expect(fetch.mock.calls.every(([url]) => !url.endsWith('/trial-offer'))).toBe(true)
  })

  it('keeps each optional category label paired to its own checkbox', async () => {
    renderRegister()
    const checkbox = await screen.findByLabelText('Hardware / Electricals')
    expect(checkbox).toHaveAttribute('type', 'checkbox')
    expect(checkbox.closest('label')).toHaveClass('registration-extra-option')
    fireEvent.click(checkbox)
    expect(checkbox).toBeChecked()
    expect(screen.getByLabelText('B2B Supplier')).not.toBeChecked()
  })

  it('submits cloud registration with cloud hosting even though local choices are displayed', async () => {
    const { container } = renderRegister()
    await screen.findByText('General Business')
    fireEvent.change(screen.getByPlaceholderText('e.g. Acme Corporation'), { target: { value: 'QA Business' } })
    fireEvent.change(screen.getByPlaceholderText('e.g. store'), { target: { value: 'qa_owner' } })
    fireEvent.change(container.querySelector('#password'), { target: { value: 'Password123!' } })
    fireEvent.change(container.querySelector('#confirmPassword'), { target: { value: 'Password123!' } })
    fireEvent.click(screen.getByLabelText(/I agree to the Terms/))
    fireEvent.submit(container.querySelector('#register-form'))
    await waitFor(() => expect(auth.signup).toHaveBeenCalledWith(expect.objectContaining({
      hosting: 'cloud', username: 'qa_owner', business_name: 'QA Business',
    })))
  })
})
