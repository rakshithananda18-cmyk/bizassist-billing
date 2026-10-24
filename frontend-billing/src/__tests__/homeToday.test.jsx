// @vitest-environment jsdom
// pages/Home.jsx — the workspace home: quick actions for everyone, and for
// owners today's money and stock at a glance (from /dashboard-summary).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import React from 'react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

const auth = vi.hoisted(() => ({ value: null }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => auth.value }))
vi.mock('../layouts/AppLayout', () => ({ default: ({ children }) => <div>{children}</div> }))
vi.mock('../components/AnnouncementsCard', () => ({ default: () => null }))

import Home from '../pages/Home'

const SUMMARY = {
  paid_today: 1500, pending_amount: 2360, pending_count: 2,
  overdue_amount: 1180, overdue_count: 1, low_stock_count: 3,
}

function renderHome(role) {
  const authFetch = vi.fn(async () => ({ ok: true, json: async () => SUMMARY }))
  auth.value = { profile: { business_name: 'Sri Lakshmi Medicals' }, user: { role }, authFetch }
  render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/parties/:tab" element={<div>opened parties/:tab</div>} />
        <Route path="/stock/:tab" element={<div>opened stock/:tab</div>} />
      </Routes>
    </MemoryRouter>
  )
  return authFetch
}

describe('Home', () => {
  beforeEach(() => { vi.useFakeTimers({ toFake: ['Date'] }); vi.setSystemTime(new Date(2026, 9, 25, 10, 0)) })
  afterEach(() => { cleanup(); vi.useRealTimers() })

  it('shows an owner today\'s money and stock, each opening its page', async () => {
    const authFetch = renderHome('enterprise')
    expect(authFetch).toHaveBeenCalledWith('/dashboard-summary')
    await waitFor(() => expect(screen.getByText('₹1,500')).toBeInTheDocument())
    expect(screen.getByText('₹2,360')).toBeInTheDocument()
    expect(screen.getByText('2 bills')).toBeInTheDocument()
    expect(screen.getByText('₹1,180')).toBeInTheDocument()
    expect(screen.getByText('1 bill')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Overdue/ }))
    expect(screen.getByText('opened parties/:tab')).toBeInTheDocument()
  })

  it('gives a cashier the counter, not the business totals', () => {
    const authFetch = renderHome('cashier')
    expect(authFetch).not.toHaveBeenCalled()
    expect(screen.getByText('Ready to bill')).toBeInTheDocument()
    expect(screen.queryByText('Your business at a glance')).toBeNull()
  })

  it('opens payments from the Cash Book quick action (it used to land back on Home)', () => {
    renderHome('enterprise')
    fireEvent.click(screen.getByRole('button', { name: /Cash Book/ }))
    expect(screen.getByText('opened parties/:tab')).toBeInTheDocument()
  })

  it('writes the date the Indian way', () => {
    renderHome('enterprise')
    expect(screen.getByText(/SUNDAY 25 OCTOBER, 2026/)).toBeInTheDocument()
  })
})
