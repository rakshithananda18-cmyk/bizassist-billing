import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'
import { MemoryRouter } from 'react-router-dom'
import Support from '../pages/Support'
import { SUPPORT_CONTACTS } from '../config/supportContacts'

const mockAuthFetch = vi.fn()
const mockUser = { username: 'testmerchant', id: 42, business_id: 101 }
const mockProfile = { name: 'Test Merchant', biz_id: 'BA-TEST01', phone: '9494747409' }
let mockNetworkMode = 'local'

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: mockUser,
    profile: mockProfile,
    authFetch: mockAuthFetch,
    networkMode: mockNetworkMode,
  }),
  useBusinessConfig: () => ({
    config: {},
    attributesSchema: {},
    refreshConfig: vi.fn(),
    t: (k, fallback) => fallback || k,
  })
}))

// Mock AppLayout to keep the test fast and lightweight
vi.mock('../layouts/AppLayout', () => ({
  default: ({ children, title }) => (
    <div data-testid="app-layout" data-title={title}>
      {children}
    </div>
  ),
}))

describe('Support Page Revamp', () => {
  beforeEach(() => {
    mockNetworkMode = 'local'
    mockAuthFetch.mockReset()
  })
  afterEach(() => { cleanup(); vi.restoreAllMocks() })

  it('renders the header, system status, and BizID', () => {
    render(
      <MemoryRouter>
        <Support />
      </MemoryRouter>
    )

    expect(screen.getByText(/Feedback & Support Desk/i)).toBeInTheDocument()
    expect(screen.getByText('BA-TEST01')).toBeInTheDocument()
    expect(screen.getByText(/Network available/i)).toBeInTheDocument()
    expect(screen.queryByText(/Online & Synced/i)).not.toBeInTheDocument()
  })

  it('renders all issue categories and allows selection', async () => {
    render(
      <MemoryRouter>
        <Support />
      </MemoryRouter>
    )

    expect(screen.getByText('Bug / Issue')).toBeInTheDocument()
    expect(screen.getByText('Printer / Hardware')).toBeInTheDocument()
    expect(screen.getByText('GST & Invoicing')).toBeInTheDocument()
    expect(screen.getByText('Cloud Sync & Backup')).toBeInTheDocument()
    expect(screen.getByText('Feature Request')).toBeInTheDocument()

    // Select Printer / Hardware
    const printerBtn = screen.getByRole('button', { name: /printer \/ hardware/i })
    await userEvent.click(printerBtn)
    expect(printerBtn).toHaveAttribute('aria-pressed', 'true')
  })

  it('submits a ticket with formatted details and logs flag', async () => {
    mockAuthFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ ok: true, message: 'Ticket received' }),
    })

    render(
      <MemoryRouter>
        <Support />
      </MemoryRouter>
    )

    const textarea = screen.getByPlaceholderText(/describe what happened/i)
    await userEvent.type(textarea, 'Thermal printer cuts off receipt totals prematurely')

    const subjectInput = screen.getByPlaceholderText(/brief 1-line summary/i)
    await userEvent.type(subjectInput, 'Thermal printer cutting early')

    const submitBtn = screen.getByRole('button', { name: /submit support ticket/i })
    await userEvent.click(submitBtn)

    await waitFor(() => {
      expect(mockAuthFetch).toHaveBeenCalledTimes(1)
      expect(mockAuthFetch).toHaveBeenCalledWith(
        '/feedback/submit',
        expect.objectContaining({
          method: 'POST',
          body: expect.any(FormData),
        })
      )
    })

    // Check success confirmation
    await waitFor(() => {
      expect(screen.getByText(/submitted successfully/i)).toBeInTheDocument()
    })
    expect(screen.queryByText(/Ticket #BA-/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Follow up on WhatsApp/i })).not.toBeInTheDocument()
    const body = mockAuthFetch.mock.calls[0][1].body
    expect(body.get('message')).toContain('Subject: Thermal printer cutting early')
    expect(body.get('attach_logs')).toBe('true')
  })

  it('shows error validation when submitting empty message', async () => {
    render(
      <MemoryRouter>
        <Support />
      </MemoryRouter>
    )

    const submitBtn = screen.getByRole('button', { name: /submit support ticket/i })
    await userEvent.click(submitBtn)

    expect(screen.getByText(/please provide details/i)).toBeInTheDocument()
    expect(mockAuthFetch).not.toHaveBeenCalled()
  })

  it('toggles FAQ accordions', async () => {
    render(
      <MemoryRouter>
        <Support />
      </MemoryRouter>
    )

    // First FAQ is open by default
    expect(screen.getByText(/Settings > Print/i)).toBeInTheDocument()

    // Click another FAQ
    const offlineFaq = screen.getByText(/Bills saved offline are not syncing/i)
    await userEvent.click(offlineFaq)

    expect(screen.getByText(/Settings > Network & Discovery/i)).toBeInTheDocument()
  })

  it('keeps direct contact data hidden while retaining the request form and FAQs', () => {
    render(<MemoryRouter><Support /></MemoryRouter>)
    expect(screen.getByRole('button', { name: /submit support ticket/i })).toBeInTheDocument()
    expect(screen.getByText('Quick Self-Help & Solutions')).toBeInTheDocument()
    expect(screen.queryByText('Direct Contact Channels')).not.toBeInTheDocument()
    expect(screen.queryByText('WhatsApp Desk')).not.toBeInTheDocument()
    expect(screen.queryByText('Email Desk')).not.toBeInTheDocument()
    expect(screen.queryByText('Support Helpline')).not.toBeInTheDocument()
    expect(document.querySelector('a[href^="tel:"], a[href^="mailto:"]')).toBeNull()
    expect(screen.queryByText(SUPPORT_CONTACTS.email)).not.toBeInTheDocument()
    expect(SUPPORT_CONTACTS).toEqual({ enabled: false, email: 'rakshithananda18@gmail.com', phone: null, hours: '10:00 AM – 6:00 PM' })
  })

  it('includes metadata in the backend message limit and preserves an oversized draft', async () => {
    render(<MemoryRouter><Support /></MemoryRouter>)
    const details = screen.getByRole('textbox', { name: /Detailed Description/i })
    fireEvent.change(details, { target: { value: 'x'.repeat(8000) } })
    await userEvent.click(screen.getByRole('button', { name: /submit support ticket/i }))
    expect(screen.getByRole('alert')).toHaveTextContent('including its summary and contact details')
    expect(details).toHaveValue('x'.repeat(8000))
    expect(mockAuthFetch).not.toHaveBeenCalled()
  })

  it('does not offer desktop log attachments or SQLite diagnostics on a cloud account', async () => {
    mockNetworkMode = 'cloud'
    mockAuthFetch.mockResolvedValue({ ok: true, json: async () => ({ ok: true }) })
    render(<MemoryRouter><Support /></MemoryRouter>)
    const logs = screen.getByRole('checkbox', { name: /Attach application diagnostics/i })
    expect(logs).toBeDisabled()
    expect(logs).not.toBeChecked()
    await userEvent.click(screen.getByRole('button', { name: /Preview diagnostic data/i }))
    expect(screen.queryByText(/SQLite/)).not.toBeInTheDocument()
    await userEvent.type(screen.getByRole('textbox', { name: /Detailed Description/i }), 'Cloud support request')
    await userEvent.click(screen.getByRole('button', { name: /submit support ticket/i }))
    await screen.findByText(/submitted successfully/i)
    expect(mockAuthFetch.mock.calls[0][1].body.get('attach_logs')).toBe('false')
  })

  it('updates the network label when the device goes offline without claiming sync succeeded', () => {
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
    render(<MemoryRouter><Support /></MemoryRouter>)
    expect(screen.getByText('Offline')).toBeInTheDocument()
    expect(screen.queryByText(/Synced/i)).not.toBeInTheDocument()
  })
})
