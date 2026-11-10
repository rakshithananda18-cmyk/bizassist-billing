// @vitest-environment jsdom
import React from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
const state = vi.hoisted(() => ({ score: {} }))
vi.mock('../../layouts/StaffLayout', () => ({ useDay: () => ({ today: null }) }))
vi.mock('../../lib/api', () => ({ api: { get: vi.fn() } }))
vi.mock('../../components/ui', async importOriginal => ({ ...(await importOriginal()), useLoad: () => ({ data: state.score, loading: false, reload: vi.fn() }) }))
import MyScore from './MyScore'
afterEach(cleanup)
describe('attendance score labels', () => {
  it('does not award perfect attendance when none is recorded', () => {
    state.score = { days_present: 0, days_late: 0, amount_collected: 0 }
    render(<MyScore />)
    expect(screen.getByText('No attendance recorded this month')).toBeTruthy()
    expect(screen.queryByText('100% on time')).toBeNull()
    expect(screen.queryByText('Perfect')).toBeNull()
  })
  it('shows the perfect badge only for recorded attendance without lateness', () => {
    state.score = { days_present: 2, days_late: 0, amount_collected: 0 }
    render(<MyScore />)
    expect(screen.getByText('Perfect')).toBeTruthy()
  })
})
