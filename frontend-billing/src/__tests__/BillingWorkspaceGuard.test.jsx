import React from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import BillingWorkspaceGuard from '../components/BillingWorkspaceGuard'
const auth = vi.hoisted(() => ({ value: {} }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => auth.value }))
afterEach(cleanup)
function show(user) {
  auth.value = { user, loading: false, logout: vi.fn() }
  render(<MemoryRouter initialEntries={['/parties?field_business=BA-ONE']}><BillingWorkspaceGuard>
    <Routes><Route path="/parties" element={<p>Protected billing records</p>} /><Route path="/login" element={<p>Login</p>} /></Routes>
  </BillingWorkspaceGuard></MemoryRouter>)
}
describe('Field Team return business', () => {
  it('blocks a different signed-in Billing account', () => {
    show({ public_id: 'BA-TWO', business_name: 'Other business' })
    expect(screen.getByText('Choose the same business')).toBeInTheDocument()
    expect(screen.queryByText('Protected billing records')).not.toBeInTheDocument()
  })
  it('allows the matching account', () => {
    show({ public_id: 'BA-ONE' })
    expect(screen.getByText('Protected billing records')).toBeInTheDocument()
  })
  it('preserves the requested business while opening login', () => {
    show(null)
    expect(screen.getByText('Login')).toBeInTheDocument()
  })
})
