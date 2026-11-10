// @vitest-environment jsdom
import React from 'react'
import { MemoryRouter } from 'react-router-dom'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
const state = vi.hoisted(() => ({ act: vi.fn(), get: vi.fn() }))
vi.mock('../../lib/api', () => ({ api: { get: state.get } }))
vi.mock('../../layouts/StaffLayout', () => ({ useDay: () => ({ onDuty: true, act: state.act, today: { runs: [{ stops: [{ id: 10, shop: { id: 1, name: 'First shop' } }, { id: 20, shop: { id: 2, name: 'Second shop' } }] }] } }) }))
import NewRequest from './NewRequest'
beforeEach(() => { state.act.mockReset(); state.act.mockResolvedValue({}); state.get.mockReset(); state.get.mockResolvedValue([]) })
afterEach(cleanup)
describe('shop order requests', () => {
  it('links a changed shop to its own stop rather than the old launch URL', async () => {
    render(<MemoryRouter initialEntries={['/request?shop=1&stop=10']}><NewRequest /></MemoryRouter>)
    fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: '2' } })
    fireEvent.change(screen.getByPlaceholderText('Medicine / Item name'), { target: { value: 'Synthetic item' } })
    fireEvent.change(screen.getByPlaceholderText('Qty'), { target: { value: '2' } })
    fireEvent.click(screen.getByText('Send to Distributor'))
    await waitFor(() => expect(state.act).toHaveBeenCalled())
    expect(state.act.mock.calls[0][1]).toMatchObject({ shop_id: 2, run_stop_id: 20, items: [{ name: 'Synthetic item', qty: 2, unit: 'Box' }] })
  })
  it('shows a failed source request instead of claiming no orders exist', async () => {
    state.get.mockRejectedValue(new Error('Synthetic source unavailable'))
    render(<MemoryRouter><NewRequest /></MemoryRouter>)
    await screen.findByText('Synthetic source unavailable')
    expect(screen.queryByText('No orders or requirement lists recorded yet.')).toBeNull()
  })
})
