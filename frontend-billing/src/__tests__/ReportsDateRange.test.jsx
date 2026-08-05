// Regression: changing the date range left the PREVIOUS run's result on screen.
// The reported symptom was a stale "No transactions recorded for this period",
// but the same staleness mislabels a populated report too — the section header
// and every CSV filename are built from the CURRENT dateRange, so old rows were
// shown, and exported, under a period they don't cover.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import Reports from '../pages/Reports'

vi.mock('../layouts/AppLayout', () => ({
  default: ({ children }) => <div>{children}</div>,
}))

const DAY_BOOK = {
  summary: { total_sales: 100, net_cash_flow: 100 },
  transactions: [{ date: '2026-07-02', type: 'Sale', ref_no: 'INV-1', entity_name: 'Acme', payment_mode: 'Cash', status: 'paid', amount: 100 }],
}

const authFetch = vi.fn(async () => ({
  ok: true, status: 200,
  headers: { get: () => null },
  json: async () => DAY_BOOK,
}))

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ authFetch }),
}))

beforeEach(() => { authFetch.mockClear(); localStorage.clear() })

describe('Reports date range', () => {
  it('drops the previous result when the range changes', async () => {
    render(<Reports />)

    fireEvent.click(screen.getByText('Day Book'))
    await screen.findByText('INV-1')          // report ran for the original range

    // Same action the user takes: edit the "from" date.
    const from = document.querySelector('input[type="date"]')
    fireEvent.change(from, { target: { value: '2026-01-01' } })

    // The old row must not survive into a period it doesn't belong to.
    await waitFor(() => expect(screen.queryByText('INV-1')).toBeNull())
    // …and the prompt names the selected report rather than "Select a report",
    // which would be wrong — the report is still chosen, it just needs re-running.
    expect(screen.getByText(/Run Day Book/i)).toBeInTheDocument()
  })
})
