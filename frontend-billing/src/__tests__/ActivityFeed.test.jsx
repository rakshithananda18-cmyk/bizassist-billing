import React from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'

const authFetch = vi.hoisted(() => vi.fn())
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ authFetch }) }))
import ActivityFeed from '../components/ActivityFeed'

const item = (id, summary = `Event ${id}`, category = 'billing') => ({
  id, summary, category, at: '2026-10-29T10:00:00Z', by_username: 'Owner', action: 'UPDATE',
  changes: { name: { from: 'Before', to: 'After' } },
})
const response = (items, total = items.length) => ({ ok: true, json: async () => ({ items, total }) })
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }

beforeEach(() => { authFetch.mockReset() })
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('Business activity audit feed', () => {
  it('restarts pagination after refresh and does not skip the next page', async () => {
    authFetch.mockImplementation(async path => {
      const offset = Number(new URL(path, 'https://test.invalid').searchParams.get('offset'))
      return response(Array.from({ length: 50 }, (_, i) => item(offset + i + 1)), 150)
    })
    const user = userEvent.setup()
    render(<ActivityFeed />)
    await screen.findByRole('button', { name: 'View activity: Event 1' })
    await user.click(screen.getByRole('button', { name: /Load more events/ }))
    await screen.findByRole('button', { name: 'View activity: Event 51' })
    await user.click(screen.getByRole('button', { name: 'Refresh Feed' }))
    await waitFor(() => expect(screen.queryByRole('button', { name: 'View activity: Event 51' })).not.toBeInTheDocument())
    await user.click(await screen.findByRole('button', { name: /Load more events/ }))
    await screen.findByRole('button', { name: 'View activity: Event 51' })
    expect(authFetch.mock.calls.map(([path]) => Number(new URL(path, 'https://test.invalid').searchParams.get('offset')))).toEqual([0, 50, 0, 50])
  })

  it('ignores an older category response that finishes after the new category', async () => {
    const oldRequest = deferred()
    authFetch.mockReturnValueOnce(oldRequest.promise).mockResolvedValueOnce(response([item(2, 'Stock update', 'stock')]))
    render(<ActivityFeed />)
    await userEvent.click(screen.getByRole('button', { name: 'Stock' }))
    await screen.findByRole('button', { name: 'View activity: Stock update' })
    await act(async () => oldRequest.resolve(response([item(1, 'Old billing result')])))
    expect(screen.queryByText('Old billing result')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Stock' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('shows load failures instead of reporting an empty audit history', async () => {
    authFetch.mockResolvedValueOnce({ ok: false }).mockResolvedValueOnce(response([item(1)]))
    render(<ActivityFeed />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load business activity')
    expect(screen.queryByText(/No activity events found/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Refresh Feed' }))
    await screen.findByRole('button', { name: 'View activity: Event 1' })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('keeps older events reachable while searching loaded results', async () => {
    authFetch.mockResolvedValueOnce(response([item(1, 'Recent event')], 70))
      .mockResolvedValueOnce(response([item(2, 'Older matching entry')], 70))
    render(<ActivityFeed />)
    await screen.findByText('Recent event')
    await userEvent.type(screen.getByRole('textbox', { name: 'Search loaded activity events' }), 'matching')
    expect(screen.getByText(/Searching 1 loaded events out of 70/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Load more events/ }))
    await screen.findByRole('button', { name: 'View activity: Older matching entry' })
  })

  it('opens details from the keyboard, traps focus, and restores the event row on Escape', async () => {
    authFetch.mockResolvedValue(response([item(1, 'Name changed')]))
    const user = userEvent.setup()
    const view = render(<ActivityFeed />)
    const row = await screen.findByRole('button', { name: 'View activity: Name changed' })
    row.focus()
    await user.keyboard('{Enter}')
    const dialog = screen.getByRole('dialog', { name: 'Name changed' })
    expect(view.container).not.toContainElement(dialog)
    expect(within(dialog).getByText('Before', { selector: 'td' })).toBeInTheDocument()
    const closeButtons = within(dialog).getAllByRole('button', { name: 'Close' })
    expect(closeButtons[0]).toHaveFocus()
    await user.tab({ shift: true })
    expect(closeButtons[1]).toHaveFocus()
    fireEvent.keyDown(closeButtons[1], { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(row).toHaveFocus()
  })
})
