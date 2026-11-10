// @vitest-environment jsdom
import React from 'react'
import { MemoryRouter } from 'react-router-dom'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
const state = vi.hoisted(() => ({ day: null, me: null, act: vi.fn(), get: vi.fn() }))
vi.mock('../../layouts/StaffLayout', () => ({ useDay: () => state.day }))
vi.mock('../../lib/auth', () => ({ useAuth: () => ({ me: state.me }) }))
vi.mock('../../lib/api', () => ({ api: { get: state.get } }))
vi.mock('../../components/MapView', () => ({ default: () => <div data-testid="map" />, escapeHtml: value => value }))
import Today from './Today'
const task = { id: 8, title: 'Collect invoice', task_type: 'payment_collect', amount_expected: 50, status: 'pending', points: 2 }
const run = (id, name, status = 'planned') => ({ id, name, status, stops_done: status === 'completed' ? 1 : 0, stops_total: 1, boxes_planned: 0, boxes_delivered: 0, orders_count: 0, stops: [{ id: id * 10, seq: 1, status: status === 'completed' ? 'done' : 'arrived', shop: { id, name: `${name} shop`, lat: 12, lng: 77 }, tasks: status === 'completed' ? [] : [task] }] })
beforeEach(() => {
  localStorage.clear(); state.act.mockReset(); state.act.mockResolvedValue({ on_time: true, points_awarded: 2 })
  state.me = { name: 'Synthetic worker', billing_business: { business_name: 'Synthetic merchant', upi_vpa: 'merchant@upi' } }
  state.day = { today: { today: '2026-10-31', attendance: null, settings: {}, runs: [run(1, 'First route'), run(2, 'Second route')], other_tasks: [] }, onDuty: true, act: state.act, track: { state: 'idle' }, reload: vi.fn() }
})
afterEach(cleanup)
const mount = () => render(<MemoryRouter><Today /></MemoryRouter>)
describe('staff map and payment workflow', () => {
  it('can start and select every assigned route from the default map view', () => {
    mount()
    fireEvent.click(screen.getByText('Start route'))
    expect(state.act).toHaveBeenCalledWith('/api/runs/1/start', {}, 'Route started')
    fireEvent.change(screen.getByLabelText('Route'), { target: { value: '2' } })
    fireEvent.click(screen.getByText('Start route'))
    expect(state.act).toHaveBeenLastCalledWith('/api/runs/2/start', {}, 'Route started')
    expect(screen.queryByText('Cash In')).toBeNull()
  })
  it('does not focus a completed stop as the next stop', () => {
    state.day.today.runs = [run(1, 'Finished route', 'completed')]
    mount()
    expect(screen.getByText('All stops on this route are completed!')).toBeTruthy()
    expect(screen.queryByText('STOP #1')).toBeNull()
  })
  it('renders the configured merchant payment QR locally without confirming collection', async () => {
    mount()
    fireEvent.click(screen.getAllByText('Done')[0])
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByText('UPI'))
    fireEvent.click(within(dialog).getByText('Show UPI QR'))
    expect(within(dialog).getByTitle('Merchant UPI payment QR').closest('svg')).toBeTruthy()
    expect(within(dialog).getByText('UPI ID: merchant@upi')).toBeTruthy()
    expect(dialog.querySelector('img')).toBeNull()
    expect(state.act).not.toHaveBeenCalled()
  })
  it('never substitutes a staff or guessed payee for a missing merchant VPA', async () => {
    state.me.billing_business.upi_vpa = null
    state.me.staff = { upi_vpa: 'personal@upi' }
    mount()
    fireEvent.click(screen.getAllByText('Done')[0])
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByText('UPI'))
    expect(within(dialog).getByText('Show UPI QR').disabled).toBe(true)
    expect(dialog.querySelector('a[href^="upi:"]')).toBeNull()
    expect(dialog.textContent).not.toContain('personal@upi')
    expect(dialog.textContent).toContain('configure their UPI ID in Billing')
  })
})
