// Render tests for the remaining report views extracted from Reports.jsx (R5):
// JournalView (journal + audit-journal), GeneralLedgerView, RegisterView.
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import JournalView from '../components/reports/JournalView'
import GeneralLedgerView from '../components/reports/GeneralLedgerView'
import RegisterView from '../components/reports/RegisterView'

afterEach(cleanup)

const fmt = (v) => `₹${Number(v || 0).toFixed(2)}`

describe('JournalView', () => {
  const data = {
    entries: [{
      date: '2026-06-22', type: 'Sale', ref_no: 'INV-1', narration: 'Sale — Kirana',
      lines: [{ account: 'Cash & Bank', debit: 100, credit: 0 }, { account: 'Sales', debit: 0, credit: 100 }],
    }],
    totals: { balanced: true, total_debit: 100, total_credit: 100 },
  }

  it('renders entries, lines and the balanced footer', () => {
    render(<JournalView reportData={data} fmt={fmt} isAudit={false} />)
    expect(screen.getByText('Cash & Bank')).toBeInTheDocument()
    expect(screen.getByText('Sales')).toBeInTheDocument()
    expect(screen.getByText(/Balanced/)).toBeInTheDocument()
    expect(screen.getByText(/1 entries/)).toBeInTheDocument()
    expect(screen.queryByText(/Posted at transaction time/)).not.toBeInTheDocument()
  })

  it('shows the posted-audit banner when isAudit', () => {
    render(<JournalView reportData={data} fmt={fmt} isAudit />)
    expect(screen.getByText(/Posted at transaction time/)).toBeInTheDocument()
  })
})

describe('GeneralLedgerView', () => {
  it('renders one card per account with postings', () => {
    const data = { ledgers: [{ account: 'Cash & Bank', closing_balance: 100, postings: [{ date: '2026-06-22', type: 'Sale', ref_no: 'INV-1', debit: 100, credit: 0, balance: 100 }] }] }
    render(<GeneralLedgerView reportData={data} fmt={fmt} />)
    expect(screen.getByText('Cash & Bank')).toBeInTheDocument()
    expect(screen.getByText('INV-1')).toBeInTheDocument()
  })

  it('shows the empty state when there are no ledgers', () => {
    render(<GeneralLedgerView reportData={{ ledgers: [] }} fmt={fmt} />)
    expect(screen.getByText('No postings for this period')).toBeInTheDocument()
  })
})

describe('RegisterView', () => {
  it('renders a generic table with upper-cased headers and formatted amounts', () => {
    render(<RegisterView reportData={[{ invoice_no: 'INV-1', amount: 1000 }]} colKeys={['invoice_no', 'amount']} />)
    expect(screen.getByText('INVOICE NO')).toBeInTheDocument()
    expect(screen.getByText('AMOUNT')).toBeInTheDocument()
    expect(screen.getByText('INV-1')).toBeInTheDocument()
    expect(screen.getByText('₹1,000')).toBeInTheDocument()   // en-IN grouped, amount column
  })

  it('shows the no-data empty state for an empty array', () => {
    render(<RegisterView reportData={[]} colKeys={[]} />)
    expect(screen.getByText('No data for this period')).toBeInTheDocument()
  })
})
