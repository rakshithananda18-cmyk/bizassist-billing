// Render tests for <CartFooterRow> — the POS cart "COLUMN TOTALS" footer (R5,
// CartTable slice 4, final). Pure presentational. Rendered inside a <table>.
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import CartFooterRow from '../components/sales/CartFooterRow'

afterEach(cleanup)

const base = {
  columnOrder: ['name', 'qty', 'discount', 'tax', 'total'],
  colVisible: { discount: true, tax: true },
  stickyOffsets: {},
  colFooter: { qty: 5, total: 200, discount: 10 },
  gstAmt: 36,
  grandTotal: 236,
}

function renderFooter(props = {}) {
  return render(<table><CartFooterRow {...base} {...props} /></table>)
}

describe('CartFooterRow', () => {
  it('renders the COLUMN TOTALS label and the summed quantity', () => {
    renderFooter()
    expect(screen.getByText('COLUMN TOTALS')).toBeInTheDocument()
    expect(screen.getByText('5')).toBeInTheDocument()   // colFooter.qty
  })

  it('omits a hidden column (one fewer cell)', () => {
    // leading td + 5 columns + trailing td = 7 cells when all visible…
    const { unmount } = renderFooter()
    const visibleCount = screen.getAllByRole('cell').length
    unmount()
    // …and 6 when the discount column is hidden.
    renderFooter({ colVisible: { discount: false, tax: true } })
    expect(screen.getAllByRole('cell').length).toBe(visibleCount - 1)
  })
})
