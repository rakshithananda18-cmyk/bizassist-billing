// Render tests for <PosTotalBar> — the always-visible POS totals bar (piece b)
// extracted from Sales.jsx. Presentational only: shows the right amounts and
// fires its two callbacks.
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import PosTotalBar from '../components/sales/PosTotalBar'

const base = {
  subtotal: 200,
  gstAmt: 36,
  grandTotal: 236,
  onShowShortcuts: () => {},
  onPay: () => {},
}

describe('PosTotalBar', () => {
  it('shows subtotal, tax and grand total', () => {
    render(<PosTotalBar {...base} />)
    expect(screen.getByText('Subtotal')).toBeInTheDocument()
    expect(screen.getByText('Tax')).toBeInTheDocument()
    expect(screen.getByText('Grand Total')).toBeInTheDocument()
    expect(screen.getByText('₹200')).toBeInTheDocument()   // subtotal
    expect(screen.getByText('₹36')).toBeInTheDocument()    // tax
    expect(screen.getByText('₹236')).toBeInTheDocument()   // grand total
  })

  it('fires onPay when the Pay button is clicked', () => {
    const onPay = vi.fn()
    render(<PosTotalBar {...base} onPay={onPay} />)
    fireEvent.click(screen.getByText(/Pay/))
    expect(onPay).toHaveBeenCalledTimes(1)
  })

  it('fires onShowShortcuts when the ? button is clicked', () => {
    const onShowShortcuts = vi.fn()
    render(<PosTotalBar {...base} onShowShortcuts={onShowShortcuts} />)
    fireEvent.click(screen.getByTitle(/Keyboard Shortcuts/))
    expect(onShowShortcuts).toHaveBeenCalledTimes(1)
  })
})
