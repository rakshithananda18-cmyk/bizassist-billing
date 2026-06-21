// Render tests for the POS settings modals extracted from Sales.jsx (R5):
// <PosCounterSettingsModal> (gear) and <PosHotkeyModal>. Presentational leaf
// modals — assert they render and fire their key callbacks.
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { PosCounterSettingsModal, PosHotkeyModal } from '../components/sales/PosSettingsModals'

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
}

describe('PosCounterSettingsModal', () => {
  it('renders and reflects the saved UPI VPA', () => {
    render(<PosCounterSettingsModal {...counterBase} />)
    expect(screen.getByText(/POS Counter Settings/)).toBeInTheDocument()
    expect(screen.getByDisplayValue('shop@upi')).toBeInTheDocument()
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
    render(<PosCounterSettingsModal {...counterBase} onMoveColumn={onMoveColumn} />)
    // idx 0 ▲ is disabled; the second ▲ (idx 1) is enabled.
    const ups = screen.getAllByText('▲')
    fireEvent.click(ups[1])
    expect(onMoveColumn).toHaveBeenCalledWith(1, 'up')
  })
})

describe('PosHotkeyModal', () => {
  const hotkeyBase = {
    onClose: () => {},
    funcKeys: {},
    setFuncKeys: () => {},
    defaultFuncKeys: { qtyFocus: 'F2' },
  }

  it('renders the hotkey configuration', () => {
    render(<PosHotkeyModal {...hotkeyBase} />)
    expect(screen.getByText(/Configure POS Hotkeys/)).toBeInTheDocument()
    expect(screen.getByText('Standard Control Shortcuts')).toBeInTheDocument()
  })

  it('Reset Defaults restores the default key map', () => {
    const setFuncKeys = vi.fn()
    render(<PosHotkeyModal {...hotkeyBase} setFuncKeys={setFuncKeys} />)
    fireEvent.click(screen.getByText('Reset Defaults'))
    expect(setFuncKeys).toHaveBeenCalledWith({ qtyFocus: 'F2' })
  })

  it('fires onClose', () => {
    const onClose = vi.fn()
    render(<PosHotkeyModal {...hotkeyBase} onClose={onClose} />)
    fireEvent.click(screen.getByText('Close'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
