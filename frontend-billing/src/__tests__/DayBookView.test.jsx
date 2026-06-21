// Render tests for <DayBookView> — the Day Book report view extracted from
// Reports.jsx (R5, Reports decomposition). Pure presentational: summary cards +
// transaction table; `fmt` injected.
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import DayBookView from '../components/reports/DayBookView'

afterEach(cleanup)

const fmt = (v) => `₹${Number(v || 0).toFixed(2)}`

const data = {
  summary: { total_sales: 1000, total_purchases: 400, total_expenses: 100, total_receipts: 800, net_cash_flow: 300 },
  transactions: [
    { date: '2026-06-22', type: 'Sale', ref_no: 'INV-1', entity_name: 'Kirana Mart', payment_mode: 'Cash', status: 'Paid', amount: 1000 },
    { date: '2026-06-22', type: 'Expense', ref_no: 'EXP-1', entity_name: 'Rent', payment_mode: 'Cash', status: '-', amount: 100 },
  ],
}

describe('DayBookView', () => {
  it('renders the summary cards and the transaction rows', () => {
    render(<DayBookView reportData={data} fmt={fmt} />)
    expect(screen.getByText('Total Sales')).toBeInTheDocument()
    expect(screen.getByText('Net Cash Flow')).toBeInTheDocument()
    expect(screen.getByText('Kirana Mart')).toBeInTheDocument()
    expect(screen.getByText('Rent')).toBeInTheDocument()
    expect(screen.getByText('Sale')).toBeInTheDocument()       // type badge
  })

  it('shows the empty-state message when there are no transactions', () => {
    render(<DayBookView reportData={{ summary: {}, transactions: [] }} fmt={fmt} />)
    expect(screen.getByText('No transactions recorded for this period.')).toBeInTheDocument()
  })
})
