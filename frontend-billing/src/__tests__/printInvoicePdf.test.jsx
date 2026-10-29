import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { printInvoicePdf } from '../utils/printInvoicePdf'

beforeEach(() => {
  vi.useFakeTimers()
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:receipt-test')
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
})
afterEach(() => { document.querySelectorAll('iframe[data-invoice-print]').forEach(el => el.remove()); vi.clearAllTimers(); vi.useRealTimers(); vi.restoreAllMocks() })

describe('PDF receipt print lifecycle', () => {
  it('waits for PDF load, requests printing, then cleans up after preview', async () => {
    const ready = printInvoicePdf(new Blob(['%PDF-test'], { type: 'application/pdf' }))
    const frame = document.querySelector('iframe[data-invoice-print]')
    vi.spyOn(frame.contentWindow, 'focus').mockImplementation(() => {})
    const print = vi.spyOn(frame.contentWindow, 'print').mockImplementation(() => {})
    expect(print).not.toHaveBeenCalled()
    frame.onload()
    await ready
    expect(print).toHaveBeenCalledOnce()
    expect(frame).toBeInTheDocument()
    await vi.advanceTimersByTimeAsync(60000)
    expect(frame).not.toBeInTheDocument()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:receipt-test')
  })
  it('rejects a timeout and releases the frame and blob', async () => {
    const ready = printInvoicePdf(new Blob(['%PDF-test']), { timeoutMs: 100 })
    const failed = expect(ready).rejects.toThrow('timed out')
    await vi.advanceTimersByTimeAsync(100)
    await failed
    expect(document.querySelector('iframe[data-invoice-print]')).toBeNull()
    expect(URL.revokeObjectURL).toHaveBeenCalledOnce()
  })
})
