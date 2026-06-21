// Render tests for <CartTableHeader> — the POS cart <thead> extracted from
// Sales.jsx (R5, first slice of CartTable). Pure presentational: renders the
// column headers in order and respects per-column visibility. Rendered inside a
// <table> since it returns a <thead>.
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import CartTableHeader from '../components/sales/CartTableHeader'

afterEach(cleanup)

const t = (_key, fallback) => fallback   // identity-ish i18n stub → "item"

const allCols = ['sku', 'name', 'mrp', 'hsn', 'qty', 'unit', 'rate', 'price', 'discount', 'tax', 'total', 'batch', 'price_option']
const allVisible = { sku: true, mrp: true, hsn: true, unit: true, discount: true, tax: true, batch: true, price_option: true, rate: true }

function renderHeader(props = {}) {
  return render(
    <table>
      <CartTableHeader columnOrder={allCols} colVisible={allVisible} stickyOffsets={{}} t={t} hasItems {...props} />
    </table>
  )
}

describe('CartTableHeader', () => {
  it('renders the visible column headers', () => {
    renderHeader()
    expect(screen.getByText('ITEM CODE')).toBeInTheDocument()       // sku
    expect(screen.getByText('ITEM NAME')).toBeInTheDocument()       // name (t fallback "item")
    expect(screen.getByText('MRP (₹)')).toBeInTheDocument()
    expect(screen.getByText('HSN')).toBeInTheDocument()
    expect(screen.getByText('QTY')).toBeInTheDocument()
    expect(screen.getByText('UNIT')).toBeInTheDocument()
    expect(screen.getByText('DISCOUNT (₹)')).toBeInTheDocument()
    expect(screen.getByText('TAX APPLIED(%)')).toBeInTheDocument()
    expect(screen.getByText('BATCH')).toBeInTheDocument()
    expect(screen.getByText('PRICE OPTION')).toBeInTheDocument()
  })

  it('hides a column whose visibility flag is false', () => {
    renderHeader({ colVisible: { ...allVisible, discount: false } })
    expect(screen.queryByText('DISCOUNT (₹)')).not.toBeInTheDocument()
    expect(screen.getByText('QTY')).toBeInTheDocument()   // others unaffected
  })

  it('respects the column order', () => {
    render(
      <table>
        <CartTableHeader columnOrder={['qty', 'sku']} colVisible={allVisible} stickyOffsets={{}} t={t} hasItems={false} />
      </table>
    )
    const headers = screen.getAllByRole('columnheader').map(th => th.textContent)
    // first is the leading "#" cell, then qty before sku per the given order
    expect(headers.indexOf('QTY')).toBeLessThan(headers.indexOf('ITEM CODE'))
  })
})
