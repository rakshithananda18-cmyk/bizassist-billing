import React from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ConfirmChangesModal from '../components/common/ConfirmChangesModal'
afterEach(cleanup)
it('Enter activates the selected credit action instead of the primary paid action', async () => {
  const onConfirm = vi.fn(), onTertiary = vi.fn()
  const user = userEvent.setup()
  render(<ConfirmChangesModal open title="Confirm payment" confirmText="Received · Print invoice"
    tertiaryText="No payment · Add to credit" onConfirm={onConfirm} onTertiary={onTertiary}
    paymentSummary={{ amountReceived: 200, payable: 124, paymentMode: 'cash' }} />)
  await waitFor(() => expect(screen.getByRole('button', { name: 'Received · Print invoice' })).toHaveFocus())
  await user.tab({ shift: true })
  expect(screen.getByRole('button', { name: 'No payment · Add to credit' })).toHaveFocus()
  await user.keyboard('{Enter}')
  expect(onTertiary).toHaveBeenCalledOnce()
  expect(onConfirm).not.toHaveBeenCalled()
})
