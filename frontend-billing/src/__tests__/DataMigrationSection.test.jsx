import React from 'react'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import DataMigrationSection from '../components/settings/DataMigrationSection'

const authFetch = vi.fn()
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ authFetch }) }))
vi.mock('../components/ImportReviewModal', () => ({
  default: ({ open, items, onCommit }) => open ? <button onClick={() => onCommit(items)}>Approve reviewed rows</button> : null,
}))
const preview = { preview: true, count: 1, items: [{ name: 'Reviewed Widget', selling_price: 100 }] }
const response = data => ({ ok: true, json: async () => data })
const file = () => new File(['name,selling_price\nReviewed Widget,100'], 'products.csv', { type: 'text/csv' })
function pick(value = file()) { fireEvent.change(screen.getByLabelText('Products CSV file'), { target: { files: [value] } }) }
beforeEach(() => authFetch.mockReset())
afterEach(cleanup)

describe('Reviewed CSV migration', () => {
  it('only parses the CSV until reviewed rows are explicitly approved, and prevents concurrent commits', async () => {
    let resolveCommit
    const pending = new Promise(resolve => { resolveCommit = resolve })
    authFetch.mockResolvedValueOnce(response(preview)).mockReturnValueOnce(pending)
    render(<DataMigrationSection />)
    pick()
    fireEvent.click(screen.getAllByRole('button', { name: 'Import', exact: true })[0])
    const approve = await screen.findByRole('button', { name: 'Approve reviewed rows' })
    expect(authFetch).toHaveBeenCalledTimes(1)
    expect(authFetch.mock.calls[0][0]).toBe('/billing/import/products?preview=1')
    fireEvent.click(approve)
    fireEvent.click(approve)
    expect(authFetch).toHaveBeenCalledTimes(2)
    expect(JSON.parse(authFetch.mock.calls[1][1].body)).toEqual({ items: preview.items })
    await act(async () => resolveCommit(response({ created: 1 })))
    expect(await screen.findByText('Imported 1 product(s).')).toBeInTheDocument()
  })

  it('does not treat a non-preview response as reviewed approval', async () => {
    authFetch.mockResolvedValue(response({ count: 1 }))
    render(<DataMigrationSection />)
    pick()
    fireEvent.click(screen.getAllByRole('button', { name: 'Import', exact: true })[0])
    expect(await screen.findByText(/server did not return an import review/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve reviewed rows' })).not.toBeInTheDocument()
    expect(authFetch).toHaveBeenCalledOnce()
  })

  it('does not claim that nothing saved when an approved import loses its response', async () => {
    authFetch.mockResolvedValueOnce(response(preview)).mockRejectedValueOnce(new Error('Connection lost'))
    render(<DataMigrationSection />)
    pick()
    fireEvent.click(screen.getAllByRole('button', { name: 'Import', exact: true })[0])
    fireEvent.click(await screen.findByRole('button', { name: 'Approve reviewed rows' }))
    expect(await screen.findByText(/result could not be confirmed/i)).toBeInTheDocument()
    expect(screen.queryByText(/nothing was saved/i)).not.toBeInTheDocument()
  })

  it('rejects database files and oversized CSV files before upload', () => {
    render(<DataMigrationSection />)
    pick(new File(['not a CSV'], 'business.db'))
    expect(screen.getByText(/Choose a CSV file/i)).toBeInTheDocument()
    pick(new File([new Uint8Array(10 * 1024 * 1024 + 1)], 'large.csv'))
    expect(screen.getByText(/10 MB or smaller/i)).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Import', exact: true })[0]).toBeDisabled()
    expect(authFetch).not.toHaveBeenCalled()
  })
})
