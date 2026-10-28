import React, { lazy, useState } from 'react'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import RouteBoundary from '../components/RouteBoundary'

vi.mock('../utils/logger', () => ({ logger: { error: vi.fn() } }))

afterEach(() => { cleanup(); vi.restoreAllMocks() })

const draw = (children, resetKey = '/') => (
  <MemoryRouter><RouteBoundary resetKey={resetKey}>{children}</RouteBoundary></MemoryRouter>
)

describe('route loading and recovery', () => {
  it('shows the loading state until a deferred page becomes available', async () => {
    let finish
    const Page = lazy(() => new Promise(resolve => { finish = resolve }))
    render(draw(<Page />))
    expect(screen.getByRole('status', { name: 'Loading BizAssist Billing' })).toBeInTheDocument()
    await act(async () => { finish({ default: () => <h1>Reports ready</h1> }) })
    expect(screen.getByRole('heading', { name: 'Reports ready' })).toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('offers recovery for a failed page download and allows another route to open', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const Page = lazy(() => Promise.reject(new Error('Download unavailable')))
    const view = render(draw(<Page />, '/reports'))
    expect(await screen.findByRole('alert')).toHaveTextContent('This page couldn’t load')
    expect(screen.getByRole('button', { name: 'Reload page' })).toBeEnabled()
    expect(screen.getByRole('link', { name: 'Go to Home' })).toHaveAttribute('href', '/')
    view.rerender(draw(<h1>Home ready</h1>, '/'))
    expect(await screen.findByRole('heading', { name: 'Home ready' })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('retains a healthy workspace state when only its route parameter changes', () => {
    function Workspace() {
      const [count, setCount] = useState(0)
      return <button onClick={() => setCount(value => value + 1)}>Draft items: {count}</button>
    }
    const view = render(draw(<Workspace />, '/parties'))
    fireEvent.click(screen.getByRole('button', { name: 'Draft items: 0' }))
    view.rerender(draw(<Workspace />, '/parties/payments'))
    expect(screen.getByRole('button', { name: 'Draft items: 1' })).toBeInTheDocument()
  })
})
