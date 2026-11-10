// @vitest-environment jsdom
import React from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
const state = vi.hoisted(() => ({ me: null, token: 'first-session', get: vi.fn(), post: vi.fn(), fix: vi.fn(), trackers: [], day: null }))
vi.mock('../lib/auth', () => ({ useAuth: () => ({ me: state.me, logout: vi.fn() }) }))
vi.mock('../lib/api', () => ({ api: { get: state.get, post: state.post }, tokenStore: { get: () => state.token } }))
vi.mock('../lib/geo', () => ({ getFix: state.fix }))
vi.mock('../lib/tracker', () => ({ Tracker: class {
  constructor(options) { this.options = options; this.stop = vi.fn(); this.keepAwake = vi.fn().mockResolvedValue(false); state.trackers.push(this) }
  start() {}
} }))
import StaffLayout, { useDay } from './StaffLayout'
const first = { public_id: 'BA-FIRST', staff: { id: 1 }, name: 'First worker', business_name: 'First business' }
const day = name => ({ label: name, attendance: { check_in_at: '2026-10-31T09:00:00' }, settings: { ping_interval_s: 60 }, runs: [], other_tasks: [] })
function Capture() { state.day = useDay(); return <div>{state.day.today?.label || 'Loading day'}</div> }
const app = () => <MemoryRouter><Routes><Route element={<StaffLayout />}><Route index element={<Capture />} /></Route></Routes></MemoryRouter>
beforeEach(() => {
  state.me = first; state.token = 'first-session'; state.trackers = []; state.get.mockReset(); state.post.mockReset(); state.fix.mockReset()
  state.get.mockResolvedValue(day('First day'))
})
afterEach(cleanup)
describe('staff action and day ownership', () => {
  it('refuses an action when the account changes while awaiting GPS', async () => {
    let resolveFix
    state.fix.mockReturnValue(new Promise(resolve => { resolveFix = resolve }))
    const view = render(app())
    await screen.findByText('First day')
    let outcome
    act(() => { outcome = state.day.act('/api/requests', { shop_id: 7 }).catch(error => error) })
    state.token = 'second-session'; state.me = { ...first, public_id: 'BA-SECOND', name: 'Second worker' }
    state.get.mockResolvedValue(day('Second day'))
    view.rerender(app())
    await screen.findByText('Second day')
    await act(async () => { resolveFix({ lat: 12, lng: 77 }); await outcome })
    expect((await outcome).message).toContain('Business session changed')
    expect(state.post).not.toHaveBeenCalled()
    expect(state.trackers.map(tracker => tracker.options.scope)).toEqual(['BA-FIRST:1', 'BA-SECOND:1'])
    expect(state.trackers[0].stop).toHaveBeenCalled()
  })
  it('does not replace the current business day with a late previous response', async () => {
    let resolveOld
    state.get.mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve }))
    const view = render(app())
    state.token = 'second-session'; state.me = { ...first, public_id: 'BA-SECOND' }
    state.get.mockResolvedValue(day('Second day'))
    view.rerender(app())
    await screen.findByText('Second day')
    await act(async () => resolveOld(day('Private first day')))
    await waitFor(() => expect(screen.queryByText('Private first day')).toBeNull())
    expect(screen.getByText('Second day')).toBeTruthy()
  })
})
