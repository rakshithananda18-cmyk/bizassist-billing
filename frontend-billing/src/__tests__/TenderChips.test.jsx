// Render tests for <TenderChips> — the smart cash-tender chips in the payment
// popup. Chip values come from the pure suggestedTenders(); the component is
// presentational and delegates selection to onSelect(value).
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import TenderChips from '../components/sales/TenderChips'

describe('TenderChips', () => {
  it('renders one chip per suggested tender (1377 -> 4 chips)', () => {
    render(<TenderChips grandTotal={1377} onSelect={() => {}} />)
    // suggestedTenders(1377) = [1377, 1380, 1400, 1500]
    expect(screen.getAllByRole('button')).toHaveLength(4)
  })

  it('labels the exact amount with an "Exact" prefix', () => {
    render(<TenderChips grandTotal={1377} onSelect={() => {}} />)
    expect(screen.getByText(/^Exact /)).toBeInTheDocument()
  })

  it('fires onSelect with the chip value when clicked', () => {
    const onSelect = vi.fn()
    render(<TenderChips grandTotal={1377} onSelect={onSelect} />)
    fireEvent.click(screen.getByText(/^Exact /))   // the exact chip = 1377
    expect(onSelect).toHaveBeenCalledWith(1377)
  })

  it('renders no chips for a zero total', () => {
    render(<TenderChips grandTotal={0} onSelect={() => {}} />)
    expect(screen.queryAllByRole('button')).toHaveLength(0)
  })
})
