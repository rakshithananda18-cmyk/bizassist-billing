// The review step between building a stock intake and committing it.
//
// The property that matters: it is shown BEFORE the write. Confirm performs the
// save; Edit returns to the sheet having written nothing. A review shown after
// the rows were already posted would offer an "Edit" that reopens committed
// stock, and a second Save All would post it twice — on the one screen where a
// duplicate is real inventory that never arrived.
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import IntakeConfirmSheet from '../components/stock/IntakeConfirmSheet'

const ROWS = [
  { _key: 'a', name: 'Basmati Rice', qty: 10, free: 2, cost_price: 100, cgst_rate: 9, sgst_rate: 9 },
  { _key: 'b', name: 'Sugar 50kg', qty: 4, free: 0, cost_price: 50, cgst_rate: 2.5, sgst_rate: 2.5 },
]

const renderSheet = (over = {}) => render(
  <IntakeConfirmSheet
    open
    rows={ROWS}
    adjustments={{}}
    distributor={{ name: 'Acme Distributors', invoice_no: 'INV-9' }}
    onEdit={vi.fn()}
    onConfirm={vi.fn()}
    {...over}
  />
)

describe('IntakeConfirmSheet', () => {
  it('renders nothing until opened', () => {
    const { container } = render(<IntakeConfirmSheet open={false} rows={ROWS} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('lists every row and names the supplier', () => {
    renderSheet()
    expect(screen.getByText('Basmati Rice')).toBeInTheDocument()
    expect(screen.getByText('Sugar 50kg')).toBeInTheDocument()
    expect(screen.getByText(/Acme Distributors/)).toBeInTheDocument()
    expect(screen.getByText(/INV-9/)).toBeInTheDocument()
  })

  it('says plainly that nothing is recorded yet', () => {
    // Without this the screen reads like a receipt for work already done.
    renderSheet()
    expect(screen.getByText(/nothing is recorded until you confirm/i)).toBeInTheDocument()
  })

  it('totals the columns: 10+4 qty, 2 free, ₹1,200 taxable, ₹190 tax', () => {
    renderSheet()
    const foot = document.querySelector('tfoot tr')
    const cells = within(foot).getAllByRole('cell').map(c => c.textContent)
    expect(cells).toContain('14')          // qty
    expect(cells).toContain('2')           // free
    expect(cells.join(' ')).toMatch(/1,200\.00/)   // 10×100 + 4×50
    expect(cells.join(' ')).toMatch(/190\.00/)     // 180 @18% + 10 @5%
    expect(cells.join(' ')).toMatch(/1,390\.00/)   // net
  })

  it('covers EXISTING products as well as new ones', () => {
    // Both kinds go through one intake and one confirmation. `NEW` is a label
    // on a row, never a filter — an existing product being restocked is the
    // commoner case and must not skip the review.
    const mixed = [
      { _key: 'n', _type: 'new', name: 'Brand New Item', qty: 5, cost_price: 20, cgst_rate: 9, sgst_rate: 9 },
      { _key: 'e', _type: 'existing', product_id: 42, name: 'Already Stocked', qty: 3, cost_price: 100, cgst_rate: 9, sgst_rate: 9 },
    ]
    renderSheet({ rows: mixed })

    expect(screen.getByText('Brand New Item')).toBeInTheDocument()
    expect(screen.getByText('Already Stocked')).toBeInTheDocument()

    // Only the new one is badged.
    expect(screen.getAllByText('NEW')).toHaveLength(1)
    const existingRow = screen.getByText('Already Stocked').closest('tr')
    expect(within(existingRow).queryByText('NEW')).toBeNull()

    // And the existing row's value counts towards the totals: 5×20 + 3×100.
    const foot = document.querySelector('tfoot tr')
    expect(within(foot).getAllByRole('cell').map(c => c.textContent).join(' '))
      .toMatch(/400\.00/)
  })

  it('Confirm is what triggers the write', () => {
    const onConfirm = vi.fn()
    renderSheet({ onConfirm })
    fireEvent.click(screen.getByRole('button', { name: /confirm & record/i }))
    expect(onConfirm).toHaveBeenCalledTimes(1)
  })

  it('Edit goes back without writing', () => {
    const onEdit = vi.fn()
    const onConfirm = vi.fn()
    renderSheet({ onEdit, onConfirm })
    fireEvent.click(screen.getByRole('button', { name: /^edit$/i }))
    expect(onEdit).toHaveBeenCalledTimes(1)
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('cannot be double-submitted while saving', () => {
    const onConfirm = vi.fn()
    renderSheet({ onConfirm, saving: true })
    const btn = screen.getByRole('button', { name: /recording/i })
    expect(btn).toBeDisabled()
    fireEvent.click(btn)
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('refuses to confirm an empty sheet', () => {
    renderSheet({ rows: [] })
    expect(screen.getByRole('button', { name: /confirm & record/i })).toBeDisabled()
  })
})
