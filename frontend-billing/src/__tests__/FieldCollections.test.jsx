import React from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import FieldCollections from '../components/payments/FieldCollections'
import api from '../api/client'
import { getApiBase } from '../config'

vi.mock('../api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { public_id: 'BA-OWNER1' } }) }))
vi.mock('../config', () => ({
  getApiBase: vi.fn(() => 'https://billing-api.example.test'),
  PUBLIC_WEB_URL: 'https://billing.example.test',
  isLocalHost: hostname => hostname === 'localhost' || hostname === '127.0.0.1' || /^192\.168\./.test(hostname),
}))
const row = (already_confirmed = 100) => ({
  task_uid: 'task-1', remaining: 400 - already_confirmed, already_confirmed,
  shop: 'Linked customer', staff: 'Staff member', payment_mode: 'Cash',
  bills: [{ invoice_id: 1, number: 'INV-1', balance_due: 1000 - already_confirmed }],
  suggested: [{ invoice_id: 1, amount: 400 - already_confirmed }], unallocated: 0,
})

beforeEach(() => {
  vi.clearAllMocks()
  getApiBase.mockReturnValue('https://billing-api.example.test')
  api.get.mockResolvedValue({ available: true, collections: [row()] })
})
afterEach(cleanup)

describe('Field collection confirmation', () => {
  it.each(['http://localhost:8001', 'http://192.168.1.4:8001', 'http://[::1]:8001'])('opens guarded online collections instead of querying local source %s', async localApi => {
    getApiBase.mockReturnValue(localApi)
    render(<FieldCollections />)
    expect(screen.getByText('Field collections are managed online')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'Open online Billing collections' })
    expect(link).toHaveAttribute('href', 'https://billing.example.test/parties/field?field_business=BA-OWNER1')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    await waitFor(() => expect(api.get).not.toHaveBeenCalled())
    expect(api.post).not.toHaveBeenCalled()
  })

  it('sends the acknowledged total with each partial approval', async () => {
    api.post.mockResolvedValue({ recorded: [{ amount: 300 }], remaining: 0 })
    render(<FieldCollections />)
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm', exact: true }))
    fireEvent.click(screen.getByRole('button', { name: /^Record / }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/field-collections/task-1/confirm', {
      allocations: [{ invoice_id: 1, amount: 300 }], expected_confirmed: 100,
    }))
  })

  it('blocks a stale approval until the owner refreshes the collection', async () => {
    api.post.mockRejectedValue({ status: 409, detail: 'Collection changed. Refresh field collections.' })
    render(<FieldCollections />)
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm', exact: true }))
    fireEvent.click(screen.getByRole('button', { name: /^Record / }))
    expect(await screen.findByText('Collection changed. Refresh field collections.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Record / })).toBeDisabled()
    api.get.mockResolvedValue({ available: true, collections: [row(200)] })
    fireEvent.click(screen.getByRole('button', { name: 'Refresh collection' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm', exact: true }))
    api.post.mockResolvedValue({ recorded: [{ amount: 200 }], remaining: 0 })
    fireEvent.click(screen.getByRole('button', { name: /^Record / }))
    await waitFor(() => expect(api.post).toHaveBeenLastCalledWith('/field-collections/task-1/confirm', {
      allocations: [{ invoice_id: 1, amount: 200 }], expected_confirmed: 200,
    }))
  })
})
