// Render tests for <PosTopBar> — the POS bill-tab strip + window controls
// extracted from Sales.jsx (R5). Presentational only: lists tabs, marks the
// active one, and fires its callbacks (select / close / new bill / settings /
// minimize / close POS).
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import PosTopBar from '../components/sales/PosTopBar'

afterEach(cleanup)

const tabs = [
  { id: '1', name: 'Invoice #1001' },
  { id: '2', name: 'Invoice #1002' },
]

const base = {
  tabs,
  activeTabId: '1',
  onSelectTab: () => {},
  onCloseTab: () => {},
  onNewBill: () => {},
  onMinimize: () => {},
  onClose: () => {},
  onOpenSettings: () => {},
}

describe('PosTopBar', () => {
  it('renders every tab and the New Bill button', () => {
    render(<PosTopBar {...base} />)
    expect(screen.getByText('Invoice #1001')).toBeInTheDocument()
    expect(screen.getByText('Invoice #1002')).toBeInTheDocument()
    expect(screen.getByText(/New Bill/)).toBeInTheDocument()
  })

  it('fires onSelectTab when an inactive tab is clicked', () => {
    const onSelectTab = vi.fn()
    render(<PosTopBar {...base} onSelectTab={onSelectTab} />)
    fireEvent.click(screen.getByText('Invoice #1002'))
    expect(onSelectTab).toHaveBeenCalledWith('2')
  })

  it('fires onNewBill, onMinimize, onClose and onOpenSettings', () => {
    const onNewBill = vi.fn()
    const onMinimize = vi.fn()
    const onClose = vi.fn()
    const onOpenSettings = vi.fn()
    render(<PosTopBar {...base} onNewBill={onNewBill} onMinimize={onMinimize} onClose={onClose} onOpenSettings={onOpenSettings} />)
    fireEvent.click(screen.getByText(/New Bill/))
    fireEvent.click(screen.getByTitle('Minimize — go back'))
    fireEvent.click(screen.getByTitle('Close POS'))
    fireEvent.click(screen.getByTitle('Settings'))
    expect(onNewBill).toHaveBeenCalledTimes(1)
    expect(onMinimize).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onOpenSettings).toHaveBeenCalledTimes(1)
  })

  it('fires onCloseTab (with the tab id) when a tab ✕ is clicked', () => {
    const onCloseTab = vi.fn()
    const { container } = render(<PosTopBar {...base} onCloseTab={onCloseTab} />)
    const closers = container.querySelectorAll('.pos-tab-close')
    fireEvent.click(closers[0])
    expect(onCloseTab).toHaveBeenCalled()
    expect(onCloseTab.mock.calls[0][0]).toBe('1')
  })
})
