import React from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import PartyCreditDrawer from '../components/parties/PartyCreditDrawer'
afterEach(() => { cleanup(); vi.restoreAllMocks() })
describe('party account statement', () => {
  it.each([['supplier', 'Payable', 'vendor'], ['customer', 'Advance', 'customer']])('does not request customer payment for %s %s balances', async (partyType, balance_type, queryType) => {
    const authFetch = vi.fn(async () => ({ ok: true, json: async () => ({ summary: { abs_closing: 500, balance_type }, entries: [] }) }))
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    render(<PartyCreditDrawer party={{ id: 1, name: 'Account', phone: '9876543210' }} partyType={partyType} authFetch={authFetch} user={{ upi_vpa: 'merchant@upi' }} onClose={vi.fn()} onSettle={vi.fn()} />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'WhatsApp Statement' })).toBeEnabled())
    expect(authFetch.mock.calls[0][0]).toContain(`party_type=${queryType}`)
    expect(screen.queryByText('Settle Credit')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'WhatsApp Statement' }))
    expect(decodeURIComponent(open.mock.calls[0][0])).not.toContain('upi://pay')
    expect(decodeURIComponent(open.mock.calls[0][0])).toContain(balance_type)
  })
})
