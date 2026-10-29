// Tests for <InvoiceViewer> (plan Phase 1 §1.4 frontend):
//   • fetches the payload once and freezes it
//   • template switching re-renders WITHOUT refetching or mutating the payload
//   • Print button triggers window.print and fires the print_opened beacon
//   • Download PDF fetches a real authenticated PDF independently of printing
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, render, screen, cleanup, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { gstPayload } from './fixtures'

const apiGet = vi.fn()
const apiPost = vi.fn(() => Promise.resolve({ ok: true }))
const apiPut = vi.fn(() => Promise.resolve({}))
const apiRaw = vi.fn()
vi.mock('../../api/client', () => ({
  api: {
    get: (...a) => apiGet(...a),
    post: (...a) => apiPost(...a),
    put: (...a) => apiPut(...a),
    // InvoiceAccountPanel fetches the invoice account via api.raw; return
    // not-ok so the panel renders nothing and these tests stay focused.
    raw: (...a) => apiRaw(...a),
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
  apiRaw.mockImplementation(path => Promise.resolve(path.endsWith('/pdf')
    ? { ok: true, blob: async () => new Blob(['%PDF-1.7 test'], { type: 'application/pdf' }) }
    : { ok: false, json: async () => ({}) }))
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:invoice-viewer-test')
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  window.print = vi.fn()
})

afterEach(() => {
  cleanup()
  const node = document.getElementById('invoice-a4-root')
  if (node) node.remove()
  vi.restoreAllMocks()
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

  it('downloads a real PDF without invoking native printing and leaves a retry link', async () => {
    mount()
    await waitFor(() => screen.getAllByTestId('invoice-classic'))
    await userEvent.click(screen.getByRole('button', { name: 'Download PDF' }))
    const link = await screen.findByRole('link', { name: 'Download PDF' })
    expect(apiRaw).toHaveBeenCalledWith('/sales/INV-42/pdf', undefined, { signal: expect.any(AbortSignal) })
    expect(window.print).not.toHaveBeenCalled()
    expect(URL.createObjectURL).toHaveBeenCalledOnce()
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledOnce()
    expect(link).toHaveAttribute('href', 'blob:invoice-viewer-test')
    expect(link).toHaveAttribute('download', 'INV-42.pdf')
    const actions = apiPost.mock.calls.map(([, body]) => body?.action)
    expect(actions).toContain('pdf_generated')
  })

  it('rejects a printable HTML fallback instead of downloading it as a PDF', async () => {
    apiRaw.mockImplementation(path => Promise.resolve(path.endsWith('/pdf')
      ? { ok: true, blob: async () => new Blob(['<html>fallback</html>'], { type: 'text/html' }) }
      : { ok: false, json: async () => ({}) }))
    mount()
    await waitFor(() => screen.getAllByTestId('invoice-classic'))
    await userEvent.click(screen.getByRole('button', { name: 'Download PDF' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Your invoice is saved')
    expect(URL.createObjectURL).not.toHaveBeenCalled()
    expect(HTMLAnchorElement.prototype.click).not.toHaveBeenCalled()
    expect(window.print).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Download PDF' })).not.toBeDisabled()
  })

  it('aborts an unfinished PDF request when the viewer closes', async () => {
    let resolvePdf
    const pendingPdf = new Promise(resolve => { resolvePdf = resolve })
    apiRaw.mockImplementation(path => path.endsWith('/pdf')
      ? pendingPdf : Promise.resolve({ ok: false, json: async () => ({}) }))
    const view = mount()
    await waitFor(() => screen.getAllByTestId('invoice-classic'))
    await userEvent.click(screen.getByRole('button', { name: 'Download PDF' }))
    expect(screen.getByRole('button', { name: 'Preparing PDF' })).toBeDisabled()
    const request = apiRaw.mock.calls.find(([path]) => path.endsWith('/pdf'))
    view.unmount()
    expect(request[2].signal.aborted).toBe(true)
    await act(async () => {
      resolvePdf({ ok: true, blob: async () => new Blob(['%PDF-test'], { type: 'application/pdf' }) })
      await pendingPdf
    })
    expect(HTMLAnchorElement.prototype.click).not.toHaveBeenCalled()
    expect(URL.createObjectURL).not.toHaveBeenCalled()
  })

  it('revokes a prepared PDF URL when the viewer closes', async () => {
    const view = mount()
    await waitFor(() => screen.getAllByTestId('invoice-classic'))
    await userEvent.click(screen.getByRole('button', { name: 'Download PDF' }))
    await screen.findByRole('link', { name: 'Download PDF' })
    view.unmount()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:invoice-viewer-test')
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
