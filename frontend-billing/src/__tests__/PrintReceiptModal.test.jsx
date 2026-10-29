import React from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import PrintReceiptModal from '../components/sales/PrintReceiptModal'
import { requestReceiptPrint } from '../utils/receiptPrintEvents'

afterEach(() => { cleanup(); vi.restoreAllMocks() })
const ready = { invoiceNo: 'QA-1', format: 'thermal', status: 'ready', error: null, pdfLoading: false, pdfUrl: null, offline: false }
function show(job = ready) {
  const onPrint = vi.fn(), onPreparePdf = vi.fn(), onDone = vi.fn()
  const view = render(<PrintReceiptModal job={job} onPrint={onPrint} onPreparePdf={onPreparePdf} onDone={onDone} />)
  return { ...view, onPrint, onPreparePdf, onDone }
}

describe('Saved receipt print dialog', () => {
  it('does not render without a saved print job', () => {
    show(null)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
  it('keeps the receipt screen open while Print only invokes the print callback', async () => {
    const callbacks = show()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Print receipt' }))
    await user.click(screen.getByRole('button', { name: 'Print receipt' }))
    expect(callbacks.onPrint).toHaveBeenCalledTimes(2)
    expect(callbacks.onDone).not.toHaveBeenCalled()
    expect(callbacks.onPreparePdf).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog', { name: 'Invoice saved — print receipt' })).toBeInTheDocument()
    expect(screen.getByText('QA-1')).toBeInTheDocument()
  })
  it('offers independent open and real download links for a prepared PDF', () => {
    show({ ...ready, format: 'pdf', pdfUrl: 'blob:invoice-qa-1' })
    expect(screen.getByRole('link', { name: 'Open PDF' })).toHaveAttribute('href', 'blob:invoice-qa-1')
    expect(screen.getByRole('link', { name: 'Open PDF' })).toHaveAttribute('target', '_blank')
    expect(screen.getByRole('link', { name: 'Open PDF' })).toHaveAttribute('rel', 'noopener noreferrer')
    expect(screen.getByRole('link', { name: 'Download PDF' })).toHaveAttribute('href', 'blob:invoice-qa-1')
    expect(screen.getByRole('link', { name: 'Download PDF' })).toHaveAttribute('download', 'QA-1.pdf')
    expect(screen.queryByRole('button', { name: 'Prepare PDF' })).not.toBeInTheDocument()
  })
  it('shows PDF loading, disables premature PDF printing and closes on Escape', async () => {
    const callbacks = show({ ...ready, format: 'pdf', status: 'preparing', pdfLoading: true })
    expect(screen.getByRole('button', { name: 'Print receipt' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Preparing PDF…' })).toBeDisabled()
    expect(screen.getByText('Preparing your receipt…')).toBeInTheDocument()
    await userEvent.setup().keyboard('{Escape}')
    expect(callbacks.onDone).toHaveBeenCalledOnce()
    expect(callbacks.onPrint).not.toHaveBeenCalled()
  })
  it('allows direct Ctrl+P printing of a thermal receipt without invoking Done', () => {
    const callbacks = show({ ...ready, status: 'preparing' })
    expect(screen.getByRole('button', { name: 'Print receipt' })).not.toBeDisabled()
    const shortcut = new KeyboardEvent('keydown', { key: 'p', ctrlKey: true, bubbles: true, cancelable: true })
    window.dispatchEvent(shortcut)
    expect(shortcut.defaultPrevented).toBe(true)
    expect(callbacks.onPrint).toHaveBeenCalledOnce()
    expect(callbacks.onDone).not.toHaveBeenCalled()
  })
  it('prepares a PDF only when requested and explains offline availability', async () => {
    const callbacks = show()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Prepare PDF' }))
    expect(callbacks.onPreparePdf).toHaveBeenCalledOnce()
    callbacks.rerender(<PrintReceiptModal job={{ ...ready, offline: true }} />)
    expect(screen.queryByRole('button', { name: 'Prepare PDF' })).not.toBeInTheDocument()
    expect(screen.getByText(/PDF download needs a connection/)).toBeInTheDocument()
  })
  it('traps Tab within receipt controls and lets Enter activate Done', async () => {
    const callbacks = show({ ...ready, pdfUrl: 'blob:invoice-qa-1' })
    const user = userEvent.setup()
    expect(screen.getByRole('button', { name: 'Print receipt' })).toHaveFocus()
    await user.tab({ shift: true })
    expect(screen.getByRole('button', { name: 'Done' })).toHaveFocus()
    await user.keyboard('{Enter}')
    expect(callbacks.onDone).toHaveBeenCalledOnce()
    expect(callbacks.onPrint).not.toHaveBeenCalled()
    await user.tab()
    expect(screen.getByRole('button', { name: 'Print receipt' })).toHaveFocus()
  })
  it('keeps a background barcode focus from stealing receipt controls', () => {
    const input = document.createElement('input')
    document.body.appendChild(input)
    show()
    fireEvent.focusIn(input)
    expect(screen.getByRole('button', { name: 'Print receipt' })).toHaveFocus()
    input.remove()
  })
  it('keeps the receipt open when Escape is forwarded after cancelling native print', () => {
    vi.spyOn(Date, 'now').mockReturnValue(1000)
    const callbacks = show()
    window.dispatchEvent(new Event('beforeprint'))
    window.dispatchEvent(new Event('afterprint'))
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(callbacks.onDone).not.toHaveBeenCalled()
    vi.mocked(Date.now).mockReturnValue(1600)
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(callbacks.onDone).toHaveBeenCalledOnce()
  })
  it('also protects cancellation of PDF frame printing from closing the receipt screen', () => {
    vi.spyOn(Date, 'now').mockReturnValue(1000)
    const callbacks = show({ ...ready, format: 'pdf' })
    requestReceiptPrint(() => {})
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(callbacks.onDone).not.toHaveBeenCalled()
    vi.mocked(Date.now).mockReturnValue(1600)
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(callbacks.onDone).toHaveBeenCalledOnce()
  })
})
