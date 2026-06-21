// Render tests for the accounting report views extracted from Reports.jsx (R5):
// BalanceSheetView, TrialBalanceView, PartyLedgerView. Pure presentational; `fmt`
// injected.
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import BalanceSheetView from '../components/reports/BalanceSheetView'
import TrialBalanceView from '../components/reports/TrialBalanceView'
import PartyLedgerView from '../components/reports/PartyLedgerView'

afterEach(cleanup)

const fmt = (v) => `₹${Number(v || 0).toFixed(2)}`

describe('BalanceSheetView', () => {
  it('renders the assets/liabilities sides and the net-worth callout', () => {
    const data = {
      assets: { cash_bank: 100, receivables: 50, inventory_valuation: 200, total_assets: 350 },
      liabilities: { payables: 80, total_liabilities: 80 },
      net_worth: 270,
    }
    render(<BalanceSheetView reportData={data} fmt={fmt} />)
    expect(screen.getByText('ASSETS')).toBeInTheDocument()
    expect(screen.getByText('TOTAL ASSETS')).toBeInTheDocument()
    expect(screen.getByText('Net Asset Equity (Net Worth)')).toBeInTheDocument()
  })
})

describe('TrialBalanceView', () => {
  it('renders accounts and the balanced banner when Dr == Cr', () => {
    const data = {
      accounts: [{ account: 'Cash & Bank', group: 'Asset', debit: 100, credit: 0 }],
      totals: { total_debit: 100, total_credit: 100, balanced: true },
      memo: { capital_owner_equity: 50 },
    }
    render(<TrialBalanceView reportData={data} fmt={fmt} />)
    expect(screen.getByText('Cash & Bank')).toBeInTheDocument()
    expect(screen.getByText('✓ Balanced — Debits equal Credits')).toBeInTheDocument()
  })

  it('shows the out-of-balance warning when not balanced', () => {
    const data = { accounts: [], totals: { total_debit: 100, total_credit: 90, balanced: false }, memo: {} }
    render(<TrialBalanceView reportData={data} fmt={fmt} />)
    expect(screen.getByText('⚠ Out of balance — check data')).toBeInTheDocument()
  })
})

describe('PartyLedgerView', () => {
  it('renders the party header, opening row and entries', () => {
    const data = {
      party: { name: 'Kirana Mart', type: 'customer' },
      summary: { balance_type: 'Receivable', abs_closing: 500, total_debit: 500, total_credit: 0, closing_balance: 500 },
      opening_balance: 0,
      entries: [{ date: '2026-06-01', type: 'Sale', ref_no: 'INV-1', debit: 500, credit: 0, balance: 500 }],
    }
    render(<PartyLedgerView reportData={data} fmt={fmt} />)
    expect(screen.getByText('Kirana Mart')).toBeInTheDocument()
    expect(screen.getByText('Opening Balance')).toBeInTheDocument()
    expect(screen.getByText('INV-1')).toBeInTheDocument()
  })

  it('shows the empty-state when there are no entries', () => {
    const data = { party: { name: 'X', type: 'vendor' }, summary: {}, opening_balance: 0, entries: [] }
    render(<PartyLedgerView reportData={data} fmt={fmt} />)
    expect(screen.getByText('No transactions in this period.')).toBeInTheDocument()
  })
})
