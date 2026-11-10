// @vitest-environment jsdom
import React from 'react'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const state = vi.hoisted(() => ({
  get: vi.fn(), reload: vi.fn(),
  data: { staff: [
    { staff_id: 1, name: 'First', duty: 'off', role: 'delivery' },
    { staff_id: 2, name: 'Second', duty: 'off', role: 'delivery' },
  ] },
}))
vi.mock('../../lib/api', () => ({ api: { get: state.get } }))
vi.mock('../../components/MapView', () => ({ default: ({ paths }) => <div data-testid="trail-map">{JSON.stringify(paths)}</div>, escapeHtml: value => value }))
import Live from './Live'

const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
beforeEach(() => { state.get.mockReset() })
afterEach(cleanup)

describe('Live map trail requests', () => {
  it('does not display the old staff trail after selecting another person', async () => {
    const first = deferred(), second = deferred()
    state.get.mockImplementation((url, query) => url.endsWith('/live') ? Promise.resolve(state.data)
      : query.staff_id === 1 ? first.promise : second.promise)
    render(<Live />)
    await screen.findByText('First')
    fireEvent.click(screen.getAllByText('Trail')[0])
    fireEvent.click(screen.getAllByText('Trail')[1])
    await act(async () => second.resolve({ points: [{ lat: 22, lng: 23 }] }))
    expect(screen.getByTestId('trail-map').textContent).toContain('[[22,23]]')
    await act(async () => first.resolve({ points: [{ lat: 11, lng: 12 }] }))
    expect(screen.getByTestId('trail-map').textContent).toContain('[[22,23]]')
    expect(screen.getByTestId('trail-map').textContent).not.toContain('[[11,12]]')
  })

  it('shows a failed trail request and clears it when returning to everyone', async () => {
    state.get.mockImplementation(url => url.endsWith('/live') ? Promise.resolve(state.data)
      : Promise.reject(new Error('Trail connection failed')))
    render(<Live />)
    await screen.findByText('First')
    fireEvent.click(screen.getAllByText('Trail')[0])
    await act(async () => {})
    expect(screen.getByText('Trail connection failed')).toBeTruthy()
    fireEvent.click(screen.getByText('Show everyone'))
    expect(screen.queryByText('Trail connection failed')).toBeNull()
    expect(screen.getByTestId('trail-map').textContent).toBe('[]')
  })
})
