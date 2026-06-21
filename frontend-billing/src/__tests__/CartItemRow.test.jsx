// Render tests for <CartItemRow> — one POS cart line (R5, CartTable slice 3).
// Verifies the editable cells render, the callbacks fire, and — critically — the
// qty input keeps the `qty-input` class that Sales.jsx's keyboard cell-navigation
// targets by DOM query (`.pos-cart-table tbody tr input.qty-input`). Rendered
// inside a <table><tbody> since the component returns a <tr>.
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import CartItemRow from '../components/sales/CartItemRow'

afterEach(cleanup)

const item = { product: 'Rice', product_id: 1, sku: 'RICE-1', qty: 2, price: 100, discount: 0, cgst_rate: 2.5, sgst_rate: 2.5 }

const base = {
  item,
  index: 0,
  columnOrder: ['sku', 'name', 'qty', 'total'],
  colVisible: { sku: true },
  stickyOffsets: {},
  products: [],
  productBatches: {},
  setProductBatches: () => {},
  isIntrastate: true,
  setItem: () => {},
  onQtyChange: () => {},
  onRemove: () => {},
  setForm: () => {},
  getPriceOptions: () => [],
  authFetch: () => {},
  logger: { error: () => {} },
}

function renderRow(props = {}) {
  return render(<table><tbody><CartItemRow {...base} {...props} /></tbody></table>)
}

describe('CartItemRow', () => {
  it('shows the product name and the row number', () => {
    renderRow()
    expect(screen.getByText('Rice')).toBeInTheDocument()
    expect(screen.getByText('1')).toBeInTheDocument()   // index + 1
  })

  it('renders the qty input with the keyboard-nav class and current value', () => {
    const { container } = renderRow()
    const qty = container.querySelector('input.qty-input')   // class the F-key nav targets
    expect(qty).not.toBeNull()
    expect(qty.value).toBe('2')
  })

  it('fires onQtyChange when the qty is edited', () => {
    const onQtyChange = vi.fn()
    const { container } = renderRow({ onQtyChange })
    fireEvent.change(container.querySelector('input.qty-input'), { target: { value: '5' } })
    expect(onQtyChange).toHaveBeenCalledWith(0, '5')
  })

  it('fires onRemove when the ✕ button is clicked', () => {
    const onRemove = vi.fn()
    renderRow({ onRemove })
    fireEvent.click(screen.getByLabelText('Close'))
    expect(onRemove).toHaveBeenCalledWith(0)
  })

  it('renders an editable name input for custom items', () => {
    const onSetItem = vi.fn()
    renderRow({ item: { ...item, is_custom: true, product: 'Loose tea' }, setItem: onSetItem })
    const nameInput = screen.getByPlaceholderText('Type item name…')
    fireEvent.change(nameInput, { target: { value: 'Loose sugar' } })
    expect(onSetItem).toHaveBeenCalledWith(0, 'product', 'Loose sugar')
  })
})
