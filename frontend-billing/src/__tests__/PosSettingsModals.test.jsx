// Render tests for the POS settings modals extracted from Sales.jsx (R5):
// <PosCounterSettingsModal> (gear). Presentational leaf modal — asserts it
// renders tabs and fires key callbacks.
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { PosCounterSettingsModal } from '../components/sales/PosSettingsModals'

afterEach(cleanup)

const counterBase = {
  onClose: () => {},
  upiVpa: 'shop@upi',
  setUpiVpa: () => {},
  merchantState: '29',
  setMerchantState: () => {},
  settings: { transactions: {} },
  onToggleColumn: () => {},
  columnOrder: ['name', 'qty', 'price'],
  colVisible: { sku: true, mrp: true, hsn: true, unit: true, discount: true, tax: true, batch: true, price_option: true, rate: true },
  colLabels: { name: 'Item', qty: 'Qty', price: 'Total' },
  onMoveColumn: () => {},
  funcKeys: {},
  setFuncKeys: () => {},
  onAdvancedSettings: () => {},
  defaultFuncKeys: { qtyFocus: 'F2' },
}

describe('PosCounterSettingsModal', () => {
  it('renders and reflects the saved UPI VPA on general settings tab', () => {
    render(<PosCounterSettingsModal {...counterBase} />)
    expect(screen.getByText(/POS Counter Settings/)).toBeInTheDocument()
    expect(screen.getByDisplayValue('shop@upi')).toBeInTheDocument()
  })

  it('renders column settings when the Columns tab is clicked', () => {
    render(<PosCounterSettingsModal {...counterBase} />)
    fireEvent.click(screen.getByText('Table Columns'))
    
    // Check that column reorder and column visible headings are shown
    expect(screen.getByText('Visible Columns')).toBeInTheDocument()
    expect(screen.getByText('Rearrange Columns')).toBeInTheDocument()
  })

  it('renders shortcut settings when the Shortcuts tab is clicked', () => {
    render(<PosCounterSettingsModal {...counterBase} />)
    fireEvent.click(screen.getByText('Shortcuts / Keys'))
    
    expect(screen.getByText('Payment Flow Navigation')).toBeInTheDocument()
    expect(screen.getByText('F-Key / Action Mappings')).toBeInTheDocument()
    expect(screen.getByText(/Standard Control Shortcuts/)).toBeInTheDocument()
  })

  it('Reset Defaults restores the default key map on shortcuts tab', () => {
    const setFuncKeys = vi.fn()
    render(<PosCounterSettingsModal {...counterBase} setFuncKeys={setFuncKeys} initialTab="shortcuts" />)
    fireEvent.click(screen.getByText('Reset Defaults'))
    expect(setFuncKeys).toHaveBeenCalledWith({ qtyFocus: 'F2' })
  })

  it('fires onClose and onAdvancedSettings', () => {
    const onClose = vi.fn()
    const onAdvancedSettings = vi.fn()
    render(<PosCounterSettingsModal {...counterBase} onClose={onClose} onAdvancedSettings={onAdvancedSettings} />)
    fireEvent.click(screen.getByText('Close'))
    fireEvent.click(screen.getByText(/Advanced Settings/))
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onAdvancedSettings).toHaveBeenCalledTimes(1)
  })

  it('fires onMoveColumn from the reorder arrows', () => {
    const onMoveColumn = vi.fn()
    render(<PosCounterSettingsModal {...counterBase} onMoveColumn={onMoveColumn} initialTab="columns" />)
    // idx 0 ▲ is disabled; the second ▲ (idx 1) is enabled.
    const ups = screen.getAllByText('▲')
    fireEvent.click(ups[1])
    expect(onMoveColumn).toHaveBeenCalledWith(1, 'up')
  })
})
