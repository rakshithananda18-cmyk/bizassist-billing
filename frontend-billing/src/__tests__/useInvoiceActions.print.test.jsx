import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { role: 'owner' }, profile: null }) }))
vi.mock('../components/invoice/InvoiceViewerModal', () => ({ default: () => null }))
vi.mock('../components/parties/SaleReturnModal', () => ({ default: () => null }))
vi.mock('../components/payments/RecordPaymentModal', () => ({ default: () => null }))
import useInvoiceActions from '../hooks/useInvoiceActions'

beforeEach(() => {
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:invoice-action')
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
})
afterEach(() => { cleanup(); document.querySelectorAll('iframe').forEach(frame => frame.remove()); vi.restoreAllMocks() })

it('encodes invoice numbers and installs a renderable, managed PDF frame before printing', async () => {
  const authFetch = vi.fn(async () => ({ ok: true, blob: async () => new Blob(['%PDF-invoice'], { type: 'application/pdf' }) }))
  const hook = renderHook(() => useInvoiceActions(authFetch))
  let done
  act(() => { done = hook.result.current.print('INV/2026 #5') })
  await waitFor(() => expect(document.querySelector('iframe[data-invoice-print]')).not.toBeNull())
  expect(authFetch).toHaveBeenCalledWith('/sales/INV%2F2026%20%235/pdf', expect.objectContaining({ signal: expect.anything() }))
  const frame = document.querySelector('iframe[data-invoice-print]')
  expect(frame.style.display).not.toBe('none')
  const print = vi.spyOn(frame.contentWindow, 'print').mockImplementation(() => {})
  vi.spyOn(frame.contentWindow, 'focus').mockImplementation(() => {})
  await act(async () => { frame.onload(); await done })
  expect(print).toHaveBeenCalledOnce()
  hook.unmount()
  expect(frame).not.toBeInTheDocument()
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:invoice-action')
})

it('rejects a successful HTML fallback instead of opening a print frame', async () => {
  const events = vi.fn(); window.addEventListener('show_toast', events)
  const authFetch = vi.fn(async () => ({ ok: true, blob: async () => new Blob(['<html>PDF unavailable</html>'], { type: 'text/html' }) }))
  const hook = renderHook(() => useInvoiceActions(authFetch))
  await act(async () => { await hook.result.current.print('INV-1') })
  expect(document.querySelector('iframe')).toBeNull()
  expect(URL.createObjectURL).not.toHaveBeenCalled()
  expect(events.mock.calls.at(-1)?.[0].detail.msg).toMatch(/PDF|printing/i)
  window.removeEventListener('show_toast', events)
})

it('does not open a delayed invoice PDF after leaving the page', async () => {
  let deliver
  const authFetch = vi.fn(() => new Promise(resolve => { deliver = resolve }))
  const hook = renderHook(() => useInvoiceActions(authFetch))
  let done
  act(() => { done = hook.result.current.print('INV-2') })
  hook.unmount()
  expect(authFetch.mock.calls[0][1]?.signal.aborted).toBe(true)
  await act(async () => { deliver({ ok: true, blob: async () => new Blob(['%PDF-delayed'], { type: 'application/pdf' }) }); await done })
  expect(document.querySelector('iframe')).toBeNull()
  expect(URL.createObjectURL).not.toHaveBeenCalled()
})
