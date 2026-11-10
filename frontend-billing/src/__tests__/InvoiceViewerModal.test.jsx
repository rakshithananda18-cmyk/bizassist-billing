import React from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
vi.mock('../invoice/InvoiceViewer', () => ({ default: ({ onClose }) => <>
  <button type="button">Invoice action</button>
  <button type="button" aria-label="Close invoice viewer" onClick={onClose}>Close</button>
</> }))
import InvoiceViewerModal from '../components/invoice/InvoiceViewerModal'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('Invoice viewer modal keyboard lifecycle', () => {
  it('focuses the integrated close control, traps Tab and closes with Escape', async () => {
    const onClose = vi.fn()
    render(<InvoiceViewerModal invoiceNo="QA-1" onClose={onClose} />)
    const close = screen.getByRole('button', { name: 'Close invoice viewer' })
    await waitFor(() => expect(close).toHaveFocus())
    await userEvent.tab()
    expect(screen.getByRole('button', { name: 'Invoice action' })).toHaveFocus()
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('keeps the invoice open when Escape is forwarded after cancelling print', () => {
    vi.spyOn(Date, 'now').mockReturnValue(1000)
    const onClose = vi.fn()
    render(<InvoiceViewerModal invoiceNo="QA-1" onClose={onClose} />)
    window.dispatchEvent(new Event('beforeprint'))
    window.dispatchEvent(new Event('afterprint'))
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    expect(onClose).not.toHaveBeenCalled()
    vi.mocked(Date.now).mockReturnValue(1600)
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    expect(onClose).toHaveBeenCalledOnce()
  })
})
