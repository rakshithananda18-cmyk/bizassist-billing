import React from 'react'
import { cleanup, render, screen, fireEvent, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import DataMigrationSection from '../components/settings/DataMigrationSection'
import Purchases from '../pages/Purchases'
import Stock from '../pages/Stock'
import Settings from '../pages/Settings'
import Import from '../pages/Import'
import B2B from '../pages/B2B'
import Reports from '../pages/Reports'

const mockAuthFetchImpl = async (path) => {
  if (typeof path === 'string' && path.includes('/bizid')) {
    return {
      ok: true,
      headers: { get: () => null },
      json: async () => ({ public_id: 'BA-JABXGD' }),
    }
  }
  if (typeof path === 'string' && path.includes('/activity')) {
    return {
      ok: true,
      headers: { get: () => null },
      json: async () => ({
        items: [
          { id: 1, summary: 'Invoice created', by_username: 'Rakshith', at: new Date().toISOString(), category: 'billing', action: 'CREATE', changes: {} }
        ],
        total: 1,
      }),
    }
  }
  return {
    ok: true,
    headers: { get: () => null },
    json: async () => ([]),
    blob: async () => new Blob(['test'], { type: 'text/csv' }),
  }
}
const mockAuthFetch = vi.fn(mockAuthFetchImpl)
const mockUser = { id: 1, role: 'owner', email: 'owner@test.com' }

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: mockUser,
    token: 'tok-123',
    authFetch: mockAuthFetch,
    settings: {
      subscription: { plan: 'pro' },
      general: {},
      transactions: {},
      inventory: {},
      print: {},
    },
    fetchSettings: vi.fn().mockResolvedValue({}),
    switchMode: vi.fn(),
    setHostingMode: vi.fn(),
    networkMode: 'cloud',
  }),
  useBusinessConfig: () => ({
    config: { currency_symbol: '₹' },
    refreshConfig: vi.fn(),
  }),
}))

vi.mock('../contexts/ConfirmContext', () => ({
  useConfirm: () => vi.fn().mockResolvedValue(true),
  ConfirmProvider: ({ children }) => children,
}))

vi.mock('../contexts/LockContext', () => ({
  useLock: () => ({
    hasLock: false,
    setupPasscode: vi.fn(),
    clearPasscode: vi.fn(),
  }),
}))

vi.mock('../layouts/AppLayout', () => ({
  default: ({ children, title }) => (
    <div data-testid="app-layout" data-title={title}>
      {children}
    </div>
  ),
}))

beforeEach(() => { localStorage.clear(); mockUser.role = 'owner'; mockAuthFetch.mockReset().mockImplementation(mockAuthFetchImpl) })
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('Data Migration in Settings', () => {
  it('renders DataMigrationSection with CSV import and export panels', () => {
    render(
      <MemoryRouter>
        <DataMigrationSection />
      </MemoryRouter>
    )

    expect(screen.getByText('Data Migration & Backup')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Import Data' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Export Data' })).toBeInTheDocument()
    expect(screen.getByText('Import Guidelines')).toBeInTheDocument()
  })

  it('renders DataMigrationSection inside Settings when activeTab is migration', async () => {
    render(
      <MemoryRouter initialEntries={['/settings?tab=migration']}>
        <Settings />
      </MemoryRouter>
    )

    expect(await screen.findByText('Data Migration & Backup')).toBeInTheDocument()
    // SettingsSaveButton is hidden for migration tab
    expect(screen.queryByRole('button', { name: /save changes/i })).not.toBeInTheDocument()
  })

  it('Import page component redirects to /settings?tab=migration', () => {
    render(
      <MemoryRouter initialEntries={['/import']}>
        <Routes>
          <Route path="/import" element={<Import />} />
          <Route path="/settings" element={<div>SETTINGS_REDIRECTED</div>} />
        </Routes>
      </MemoryRouter>
    )

    expect(screen.getByText('SETTINGS_REDIRECTED')).toBeInTheDocument()
  })
})

describe('Purchases contextual actions and smart alignment', () => {
  it('highlights Record Return as primary on Returns (Debit Notes) tab', async () => {
    render(
      <MemoryRouter>
        <Purchases inlinePage={true} />
      </MemoryRouter>
    )

    // Switch to Returns tab
    const returnsTab = screen.getByRole('button', { name: /Returns \(Debit Notes\)/i })
    fireEvent.click(returnsTab)

    // On Returns tab, Record Return should have btn-primary class
    const recordReturnBtn = screen.getByRole('button', { name: /Record Return/i })
    expect(recordReturnBtn).toHaveClass('btn-primary')

    // Upload Bill should now be secondary
    const uploadBtn = screen.getByRole('button', { name: /Upload Bill/i })
    expect(uploadBtn).toHaveClass('btn-secondary')
  })

  it('highlights Upload Bill as primary on Pending Review tab', async () => {
    render(
      <MemoryRouter>
        <Purchases inlinePage={true} />
      </MemoryRouter>
    )

    const pendingTab = screen.getByRole('button', { name: /Pending Review/i })
    fireEvent.click(pendingTab)

    const uploadBtn = screen.getByRole('button', { name: /Upload Bill/i })
    expect(uploadBtn).toHaveClass('btn-primary')

    const recordReturnBtn = screen.getByRole('button', { name: /Record Return/i })
    expect(recordReturnBtn).toHaveClass('btn-secondary')
  })
})

describe('Stock contextual actions per view', () => {
  it('renders New Product as primary on Catalogue view', async () => {
    render(
      <MemoryRouter>
        <Stock inlinePage={true} />
      </MemoryRouter>
    )

    const catalogueTab = screen.getByRole('button', { name: /Catalogue/i })
    fireEvent.click(catalogueTab)

    const newProductBtn = screen.getByRole('button', { name: /New Product/i })
    expect(newProductBtn).toHaveClass('btn-primary')

    const adjustBtn = screen.getByRole('button', { name: /Adjust Stock/i })
    expect(adjustBtn).toHaveClass('btn-secondary')
  })

  it('renders Transfer Stock as primary on Godowns view', async () => {
    render(
      <MemoryRouter>
        <Stock inlinePage={true} />
      </MemoryRouter>
    )

    const godownsTab = screen.getByRole('button', { name: /Godowns/i })
    fireEvent.click(godownsTab)

    // On Godowns view, Transfer Stock should be primary
    const transferBtns = screen.getAllByRole('button', { name: /Transfer Stock/i })
    const primaryTransfer = transferBtns.find(b => b.classList.contains('btn-primary'))
    expect(primaryTransfer).toBeDefined()
  })

  it('renders Print GRN as primary on Intake view when items are present', async () => {
    localStorage.setItem('bizassist_intake_rows', JSON.stringify([
      { _key: 'row-1', name: 'Sample Item', selling_price: '100', cost_price: '80', quantity: 2 }
    ]))

    render(
      <MemoryRouter>
        <Stock inlinePage={true} />
      </MemoryRouter>
    )

    const intakeTab = screen.getByRole('button', { name: /Stock Intake/i })
    fireEvent.click(intakeTab)

    const printGrnBtn = screen.getByRole('button', { name: /Print GRN/i })
    expect(printGrnBtn).toHaveClass('btn-primary')

    const clearBtn = screen.getByRole('button', { name: /Clear Intake/i })
    expect(clearBtn).toBeInTheDocument()
  })

  it('clears the supplier, discounts and payment when starting a new intake', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    localStorage.setItem('bizassist_intake_rows', JSON.stringify([{ _key: 'old', name: 'Old Item', qty: 2, cost_price: 10 }]))
    localStorage.setItem('bizassist_intake_distributor', JSON.stringify({ name: 'Old Supplier', invoice_no: 'OLD-INV' }))
    localStorage.setItem('bizassist_intake_adjustments', JSON.stringify({ item_disc: '20', cess: '5', cash_disc: '3' }))
    localStorage.setItem('bizassist_intake_payment', JSON.stringify({ mode: 'Cash', due_date: '2026-10-01' }))
    render(<MemoryRouter><Stock inlinePage /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: /Stock Intake/i }))
    fireEvent.click(screen.getByRole('button', { name: /Clear Intake/i }))
    await waitFor(() => expect(JSON.parse(localStorage.getItem('bizassist_intake_rows'))).toEqual([]))
    expect(JSON.parse(localStorage.getItem('bizassist_intake_distributor'))).toEqual(expect.objectContaining({ name: '', invoice_no: '' }))
    expect(JSON.parse(localStorage.getItem('bizassist_intake_adjustments'))).toEqual({ item_disc: '', cess: '', cash_disc: '' })
    expect(JSON.parse(localStorage.getItem('bizassist_intake_payment'))).toEqual({ mode: 'Credit', due_date: '' })
  })

  it('escapes imported product and supplier names before constructing the GRN print document', () => {
    const write = vi.fn()
    vi.spyOn(window, 'open').mockReturnValue({ document: { write, close: vi.fn() }, focus: vi.fn(), print: vi.fn() })
    localStorage.setItem('bizassist_intake_rows', JSON.stringify([{ _key: 'unsafe', name: '<img src=x onerror=alert(1)>', qty: 2, cost_price: 10 }]))
    localStorage.setItem('bizassist_intake_distributor', JSON.stringify({ name: '<script>unsafe()</script>' }))
    render(<MemoryRouter><Stock inlinePage /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: /Stock Intake/i }))
    fireEvent.click(screen.getByRole('button', { name: /Print GRN/i }))
    expect(write).toHaveBeenCalledOnce()
    const html = write.mock.calls[0][0]
    expect(html).toContain('&lt;img src=x onerror=alert(1)&gt;')
    expect(html).toContain('&lt;script&gt;unsafe()&lt;/script&gt;')
    expect(html).not.toContain('<script>unsafe()')
  })
})

describe('B2B BizID Header Copy Button', () => {
  it('renders BizID button next to search and copies to clipboard on click', async () => {
    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn().mockResolvedValue(),
      },
    })

    render(
      <MemoryRouter initialEntries={['/b2b?tab=connections']}>
        <B2B />
      </MemoryRouter>
    )

    const bizIdBtn = await screen.findByRole('button', { name: /Copy BizID: BA-JABXGD/i })
    expect(bizIdBtn).toBeInTheDocument()
    expect(bizIdBtn).toHaveTextContent('BA-JABXGD')

    fireEvent.click(bizIdBtn)
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('BA-JABXGD')
    expect(await screen.findByText('Copied!')).toBeInTheDocument()
  })

  it('does not claim a BizID was copied when clipboard permission is denied', async () => {
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockRejectedValue(new Error('Denied')) } })
    render(<MemoryRouter initialEntries={['/b2b?tab=connections']}><B2B /></MemoryRouter>)
    fireEvent.click(await screen.findByRole('button', { name: /Copy BizID: BA-JABXGD/i }))
    expect(await screen.findByText(/Clipboard access is unavailable/i)).toBeInTheDocument()
    expect(screen.queryByText('Copied!')).not.toBeInTheDocument()
  })
})

describe('Reports Split-Pane Architecture and Category Directory', () => {
  it('renders report categories and allows selecting reports from the sidebar', async () => {
    render(
      <MemoryRouter>
        <Reports />
      </MemoryRouter>
    )

    // Sidebar directory categories
    expect(screen.getAllByText('GST & Compliance').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Operations & Registers').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Financial Statements').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Books & Ledgers').length).toBeGreaterThan(0)

    // Can find GST Report in sidebar
    const gstReportItem = screen.getByRole('tab', { name: /GST Report/i })
    expect(gstReportItem).toBeInTheDocument()

    // Click to select GST Report
    fireEvent.click(gstReportItem)

    // Verify report title and canvas toolbar are visible
    expect(await screen.findByRole('heading', { level: 2, name: /GST Report/i })).toBeInTheDocument()
    expect(screen.getByText('From')).toBeInTheDocument()
    expect(screen.getByText('To')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /This Month/i })).toBeInTheDocument()
  })

  it('toggles reports sub-sidebar collapse and expand state', async () => {
    localStorage.removeItem('reports_sidebar_collapsed')
    render(
      <MemoryRouter>
        <Reports />
      </MemoryRouter>
    )

    const collapseBtn = screen.getByRole('button', { name: /Collapse Reports Directory/i })
    expect(collapseBtn).toBeInTheDocument()

    // Collapse the sidebar
    fireEvent.click(collapseBtn)

    // Expand button should appear in canvas toolbar
    const expandBtn = await screen.findByRole('button', { name: /Expand Reports Directory/i })
    expect(expandBtn).toBeInTheDocument()

    // Expand it again
    fireEvent.click(expandBtn)
    expect(screen.getByRole('button', { name: /Collapse Reports Directory/i })).toBeInTheDocument()
  })

  it('supports vertical collapse of category head topics and tracks recent reports on top', async () => {
    localStorage.removeItem('reports_collapsed_categories')
    localStorage.removeItem('reports_recent_ids')

    render(
      <MemoryRouter>
        <Reports />
      </MemoryRouter>
    )

    // Category header is collapsible
    const gstCategoryHeader = screen.getByRole('button', { name: /GST & Compliance/i })
    expect(gstCategoryHeader).toBeInTheDocument()

    // Collapse GST & Compliance
    fireEvent.click(gstCategoryHeader)
    expect(gstCategoryHeader).toHaveAttribute('aria-expanded', 'false')

    // Re-expand GST & Compliance
    fireEvent.click(gstCategoryHeader)
    expect(gstCategoryHeader).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('tab', { name: /GST Report/i })).toBeInTheDocument()

    // Selecting a report adds it to Recent on top
    fireEvent.click(screen.getByRole('tab', { name: /GST Report/i }))
    expect(await screen.findByText('Recent')).toBeInTheDocument()
  })
})

describe('Business Activity in Settings', () => {
  it('renders ActivitySection inside Settings without Save button', async () => {
    render(
      <MemoryRouter initialEntries={['/settings?tab=activity']}>
        <Settings />
      </MemoryRouter>
    )

    expect(await screen.findByText('Business Activity & Audit Log')).toBeInTheDocument()
    expect(screen.getByText('1 events')).toBeInTheDocument()
    expect(screen.getByText('Invoice created')).toBeInTheDocument()
    // Save button should be hidden on activity tab
    expect(screen.queryByRole('button', { name: /save changes/i })).not.toBeInTheDocument()
  })

  it('preserves support access for cashiers after moving it into Settings', async () => {
    mockUser.role = 'cashier'
    render(<MemoryRouter initialEntries={['/settings?tab=support']}><Settings /></MemoryRouter>)
    expect(await screen.findByRole('heading', { name: 'Feedback & Support Desk' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /save changes/i })).not.toBeInTheDocument()
    expect(screen.queryByText('Data Migration & Backup')).not.toBeInTheDocument()
  })

  it('continues to restrict data migration for cashiers', async () => {
    mockUser.role = 'cashier'
    render(<MemoryRouter initialEntries={['/settings?tab=migration']}><Settings /></MemoryRouter>)
    expect(screen.queryByText('Data Migration & Backup')).not.toBeInTheDocument()
    expect(await screen.findByRole('tab', { name: 'General' })).toHaveAttribute('aria-selected', 'true')
  })
})
