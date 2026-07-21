// Tests for <InvoiceViewer> (plan Phase 1 §1.4 frontend):
//   • fetches the payload once and freezes it
//   • template switching re-renders WITHOUT refetching or mutating the payload
//   • Print button triggers window.print and fires the print_opened beacon
//   • Download PDF calls its handler; beacons never block the UI
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { gstPayload } from './fixtures'

const apiGet = vi.fn()
const apiPost = vi.fn(() => Promise.resolve({ ok: true }))
const apiPut = vi.fn(() => Promise.resolve({}))
vi.mock('../../api/client', () => ({
  api: {
    get: (...a) => apiGet(...a),
    post: (...a) => apiPost(...a),
    put: (...a) => apiPut(...a),
    // InvoiceAccountPanel fetches the invoice account via api.raw; return
    // not-ok so the panel renders nothing and these tests stay focused.
    raw: () => Promise.resolve({ ok: false, json: async () => ({}) }),
  },
}))

import InvoiceViewer from '../../invoice/InvoiceViewer'

function mount(invoiceNo = 'INV-42') {
  return render(
    <MemoryRouter initialEntries={[`/invoice/${invoiceNo}/view`]}>
      <Routes>
        <Route path="/invoice/:invoiceNo/view" element={<InvoiceViewer />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  apiGet.mockResolvedValue(gstPayload())
  window.print = vi.fn()
})

afterEach(() => {
  cleanup()
  const node = document.getElementById('invoice-a4-root')
  if (node) node.remove()
})

describe('InvoiceViewer', () => {
  it('fetches the payload once and renders the default (classic) template', async () => {
    mount()
    await waitFor(() => expect(screen.getAllByTestId('invoice-classic').length).toBeGreaterThan(0))
    expect(apiGet).toHaveBeenCalledTimes(1)
    expect(apiGet).toHaveBeenCalledWith('/sales/INV-42/print-payload')
  })

  it('switches templates without refetching or mutating the payload', async () => {
    const payload = gstPayload()
    apiGet.mockResolvedValue(payload)
    const snapshot = JSON.parse(JSON.stringify(payload))
    mount()
    await waitFor(() => screen.getAllByTestId('invoice-classic'))

    await userEvent.click(screen.getByRole('tab', { name: 'BizAssist' }))
    await waitFor(() => expect(screen.getAllByTestId('invoice-modern').length).toBeGreaterThan(0))
    expect(screen.queryAllByTestId('invoice-classic')).toHaveLength(0)

    await userEvent.click(screen.getByRole('tab', { name: 'Classic' }))
    await waitFor(() => expect(screen.getAllByTestId('invoice-classic').length).toBeGreaterThan(0))

    expect(apiGet).toHaveBeenCalledTimes(1)                 // never refetched
    expect(payload).toEqual(snapshot)                       // never mutated
    expect(Object.isFrozen(payload)).toBe(true)             // frozen on load
    // template_selected beacon fired for the switch
    const actions = apiPost.mock.calls.map(([, body]) => body?.action)
    expect(actions).toContain('template_selected')
  })

  it('Print triggers window.print and the print_opened beacon', async () => {
    mount()
    await waitFor(() => screen.getAllByTestId('invoice-classic'))
    await userEvent.click(screen.getByTestId('invoice-print-btn'))
    expect(window.print).toHaveBeenCalledTimes(1)
    const actions = apiPost.mock.calls.map(([, body]) => body?.action)
    expect(actions).toContain('print_opened')
  })

  it('Download PDF calls the pdf handler (print-to-PDF in Phase 1)', async () => {
    mount()
    await waitFor(() => screen.getAllByTestId('invoice-classic'))
    await userEvent.click(screen.getByRole('button', { name: 'Download PDF' }))
    expect(window.print).toHaveBeenCalledTimes(1)
    const actions = apiPost.mock.calls.map(([, body]) => body?.action)
    expect(actions).toContain('pdf_generated')
  })

  it('Set as default persists via PUT /settings', async () => {
    mount()
    await waitFor(() => screen.getAllByTestId('invoice-classic'))
    await userEvent.click(screen.getByRole('button', { name: 'Set as default' }))
    await waitFor(() =>
      expect(apiPut).toHaveBeenCalledWith('/settings', { print: { invoice_template: 'classic' } }))
  })

  it('remembers the per-user last-used template in localStorage', async () => {
    mount()
    await waitFor(() => screen.getAllByTestId('invoice-classic'))
    await userEvent.click(screen.getByRole('tab', { name: 'BizAssist' }))
    expect(localStorage.getItem('invoice.template.BA-XY12AB')).toBe('modern')
  })

  it('uses meta.template_default from the payload when no local preference', async () => {
    apiGet.mockResolvedValue(gstPayload({
      meta: { ...gstPayload().meta, template_default: 'modern' },
    }))
    mount()
    await waitFor(() => expect(screen.getAllByTestId('invoice-modern').length).toBeGreaterThan(0))
  })

  it('shows an error state when the payload fetch fails', async () => {
    apiGet.mockRejectedValue(new Error('boom'))
    mount()
    await waitFor(() => screen.getByTestId('invoice-viewer-error'))
    expect(screen.getByText(/boom|Could not load/)).toBeInTheDocument()
  })

  it('mounts the print portal on document.body', async () => {
    mount()
    await waitFor(() => screen.getAllByTestId('invoice-classic'))
    expect(document.getElementById('invoice-a4-root')).not.toBeNull()
  })
})
