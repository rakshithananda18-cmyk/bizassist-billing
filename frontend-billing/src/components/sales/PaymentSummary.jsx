import React from 'react'
import { paymentBalance } from '../../utils/invoiceMath'
import './paymentSummary.css'

export const paymentMoney = value => `₹${Number(value || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`

export function PaymentAmountRow({ label, hint, value, tone = 'accent', children }) {
  return (
    <div className={`pos-payment-amount-row ${tone}`}>
      <div className="pos-payment-amount-copy">
        <div className="pos-payment-amount-label">{label}</div>
        {hint && <div className="pos-payment-amount-hint">{hint}</div>}
      </div>
      <div className="pos-payment-amount-value">{children || paymentMoney(value)}</div>
    </div>
  )
}

export function PaymentBalanceRow({ amountReceived, payable, isCredit = false }) {
  const balance = paymentBalance(amountReceived, payable)
  const due = balance < 0
  return (
    <PaymentAmountRow
      label={due ? (isCredit ? 'Credit to customer account' : 'Balance still due') : 'Change to return'}
      hint={due ? 'Remaining amount will be saved on credit' : (balance > 0 ? 'Hand exact change to customer' : 'Exact payment — no change')}
      value={Math.abs(balance)}
      tone={due ? 'credit' : 'success'}
    />
  )
}

export default function PaymentConfirmationSummary({ amountReceived, payable, isCredit, paymentMode }) {
  return (
    <div className="pos-payment-summary" aria-label="Payment summary">
      <div className="pos-payment-summary-total"><span>Invoice payable</span><strong>{paymentMoney(payable)}</strong></div>
      <PaymentAmountRow label="Amount received" hint={amountReceived > 0 ? `Received via ${(paymentMode || 'cash').toUpperCase()}` : 'No payment received now'} value={amountReceived} />
      <PaymentBalanceRow amountReceived={amountReceived} payable={payable} isCredit={isCredit} />
    </div>
  )
}
