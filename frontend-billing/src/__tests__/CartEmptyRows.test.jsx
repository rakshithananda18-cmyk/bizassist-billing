// Render tests for <CartEmptyRows> — the blank filler rows in the POS cart when
// it's empty (R5, CartTable slice 2). Pure presentational. Rendered inside a
// <table><tbody> since it returns a fragment of <tr>.
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import CartEmptyRows from '../components/sales/CartEmptyRows'

afterEach(cleanup)

function renderRows(props = {}) {
  const base = { rowCount: 5, columnOrder: ['sku', 'name', 'qty'], colVisible: { sku: true }, stickyOffsets: {} }
  return render(
    <table>
      <tbody>
        <CartEmptyRows {...base} {...props} />
      </tbody>
    </table>
  )
}

describe('CartEmptyRows', () => {
  it('renders exactly rowCount filler rows', () => {
    renderRows({ rowCount: 7 })
    expect(screen.getAllByRole('row')).toHaveLength(7)
  })

  it('renders a leading cell plus one cell per visible column', () => {
    renderRows({ rowCount: 1, columnOrder: ['sku', 'name', 'qty'], colVisible: { sku: true } })
    // 1 leading "#" td + 3 column tds
    expect(screen.getAllByRole('cell')).toHaveLength(4)
  })

  it('omits a hidden column', () => {
    renderRows({ rowCount: 1, columnOrder: ['discount', 'qty'], colVisible: { discount: false } })
    // leading td + qty only (discount hidden) = 2
    expect(screen.getAllByRole('cell')).toHaveLength(2)
  })
})
