// Render tests for <ProductSearchBar> — the POS barcode/search input + the
// autocomplete results overlay extracted from Sales.jsx (R5). Presentational +
// forwardRef (the parent keeps `barcodeRef` so the global keydown handler can
// focus the input).
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createRef } from 'react'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import ProductSearchBar from '../components/sales/ProductSearchBar'

afterEach(cleanup)

const products = [
  { id: 1, name: 'Basmati Rice', sku: 'RICE-1', barcode: '8901', selling_price: 120 },
  { id: 2, name: 'Sunflower Oil', sku: 'OIL-1', barcode: '8902', selling_price: 380 },
]

const base = {
  searchQuery: '',
  onSearchChange: () => {},
  onKeyDown: () => {},
  placeholder: 'Scan barcode…',
  onAddCustom: () => {},
  filteredProducts: [],
  selectedIndex: -1,
  onHoverIndex: () => {},
  onPick: () => {},
}

describe('ProductSearchBar', () => {
  it('renders the input with the placeholder and reflects the query', () => {
    render(<ProductSearchBar {...base} searchQuery="rice" />)
    const input = screen.getByPlaceholderText('Scan barcode…')
    expect(input).toBeInTheDocument()
    expect(input.value).toBe('rice')
  })

  it('fires onSearchChange with the typed value', () => {
    const onSearchChange = vi.fn()
    render(<ProductSearchBar {...base} onSearchChange={onSearchChange} />)
    fireEvent.change(screen.getByPlaceholderText('Scan barcode…'), { target: { value: 'oil' } })
    expect(onSearchChange).toHaveBeenCalledWith('oil')
  })

  it('fires onAddCustom when the Custom Item button is clicked', () => {
    const onAddCustom = vi.fn()
    render(<ProductSearchBar {...base} onAddCustom={onAddCustom} />)
    fireEvent.click(screen.getByText(/Custom Item/))
    expect(onAddCustom).toHaveBeenCalledTimes(1)
  })

  it('shows the results overlay and fires onPick on a result click', () => {
    const onPick = vi.fn()
    render(<ProductSearchBar {...base} filteredProducts={products} onPick={onPick} />)
    expect(screen.getByText('Basmati Rice')).toBeInTheDocument()
    expect(screen.getByText('Sunflower Oil')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Basmati Rice'))
    expect(onPick).toHaveBeenCalledWith(products[0])
  })

  it('hides the overlay when there are no matches', () => {
    render(<ProductSearchBar {...base} filteredProducts={[]} />)
    expect(screen.queryByText('Basmati Rice')).not.toBeInTheDocument()
  })

  it('forwards the ref to the input (so the parent can focus it)', () => {
    const ref = createRef()
    render(<ProductSearchBar {...base} ref={ref} />)
    expect(ref.current).not.toBeNull()
    expect(ref.current.tagName).toBe('INPUT')
  })
})
