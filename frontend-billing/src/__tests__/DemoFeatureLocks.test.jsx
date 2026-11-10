import React from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import Settings from '../pages/Settings'
import POSLiveCounter from '../pages/POSLiveCounter'
import LiveView from '../pages/LiveView'
import B2B from '../pages/B2B'
import { useAuth } from '../contexts/AuthContext'
import Sales from '../pages/Sales'

vi.mock('../layouts/AppLayout', () => ({
  default: ({ children }) => <main>{children}</main>,
}))
vi.mock('../contexts/AuthContext', () => ({
  useAuth: vi.fn(() => { throw new Error('A locked demo must not mount the real workspace') }),
  useBusinessConfig: vi.fn(),
}))
vi.mock('../pages/Sales', () => ({
  default: vi.fn(() => <div>Live sales workspace</div>),
}))

beforeEach(() => {
  cleanup()
  vi.clearAllMocks()
  sessionStorage.setItem('stater_demo_active', '1')
})

describe('Demo feature locks', () => {
  it.each([
    [Settings, 'Store Settings & Configuration'],
    [POSLiveCounter, 'POS Live Counter Terminal'],
    [LiveView, 'POS Live View'],
    [B2B, 'B2B Digital Supply Network'],
  ])('locks %s before real workspace hooks or network activity start', (Page, label) => {
    render(<Page />)

    expect(screen.getByRole('heading', { name: label })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Start Free 14-Day Trial/ })).toHaveAttribute('href', 'https://app.staterbill.com/register')
    expect(useAuth).not.toHaveBeenCalled()
    expect(Sales).not.toHaveBeenCalled()
  })

  it('restores the normal Live View when the demo session ends', () => {
    const { rerender } = render(<LiveView />)
    sessionStorage.removeItem('stater_demo_active')
    rerender(<LiveView />)

    expect(screen.queryByRole('heading', { name: 'POS Live View' })).not.toBeInTheDocument()
    expect(screen.getByText('Live sales workspace')).toBeInTheDocument()
    expect(Sales.mock.calls.at(-1)[0]).toEqual(expect.objectContaining({ isLiveViewMode: true }))
  })
})
