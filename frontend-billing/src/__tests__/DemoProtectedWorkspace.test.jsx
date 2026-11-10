import React from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
const auth = vi.hoisted(() => ({ value: { user: { is_demo: true } } }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => auth.value }))
vi.mock('../layouts/AppLayout', () => ({ default: ({ children }) => <main>{children}</main> }))
import DemoProtectedWorkspace from '../pages/DemoProtectedWorkspace'
afterEach(cleanup)

describe('protected companion workspace previews', () => {
  it.each([['ai', 'Stater AI'], ['field-team', 'Field Team']])('renders only a protected view for %s', (route, name) => {
    auth.value = { user: { is_demo: true } }
    render(<MemoryRouter initialEntries={[`/demo-preview/${route}`]}><Routes><Route path="/demo-preview/:feature" element={<DemoProtectedWorkspace />} /></Routes></MemoryRouter>)
    expect(screen.getByRole('heading', { name })).toBeInTheDocument()
    expect(screen.getByText('Protected demo view')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Start Free 14-Day Trial/ })).toHaveAttribute('href', 'https://app.staterbill.com/register')
  })
  it('keeps signed-in real accounts on the ordinary application route', () => {
    auth.value = { user: { role: 'owner' }, isDemoMode: false }
    render(<MemoryRouter initialEntries={['/demo-preview/ai']}><Routes><Route path="/demo-preview/:feature" element={<DemoProtectedWorkspace />} /><Route path="/" element={<p>Store home</p>} /></Routes></MemoryRouter>)
    expect(screen.getByText('Store home')).toBeInTheDocument()
  })
})
