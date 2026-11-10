import React from 'react'
import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import PaymentConfirmationSummary from '../components/sales/PaymentSummary'
afterEach(cleanup)
describe('POS payment figures', () => {
  it('shows received amount and exact change in separate large rows', () => {
    render(<PaymentConfirmationSummary amountReceived={200} payable={124} paymentMode="cash" />)
    expect(screen.getByText('Amount received')).toBeInTheDocument()
    expect(screen.getByText('₹200')).toBeInTheDocument()
    expect(screen.getByText('Change to return')).toBeInTheDocument()
    expect(screen.getByText('₹76')).toBeInTheDocument()
  })
  it('identifies the remaining customer credit instead of showing negative change', () => {
    render(<PaymentConfirmationSummary amountReceived={40} payable={100} isCredit paymentMode="cash" />)
    expect(screen.getByText('Credit to customer account')).toBeInTheDocument()
    expect(screen.getByText('₹60')).toBeInTheDocument()
    expect(screen.queryByText('Change to return')).not.toBeInTheDocument()
  })
})
