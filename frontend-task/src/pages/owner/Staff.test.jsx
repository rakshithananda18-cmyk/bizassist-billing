// @vitest-environment jsdom
import React from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const post = vi.hoisted(() => vi.fn())
vi.mock('../../lib/api', () => ({ api: { post } }))
vi.mock('../../lib/auth', () => ({ useAuth: () => ({}) }))
vi.mock('../../components/ui', () => ({
  Empty: () => null, ErrorNote: () => null, Loader: () => null, PageHeader: () => null,
  useLoad: () => ({}), useToast: () => vi.fn(),
  Modal: ({ children, footer }) => <div>{children}{footer}</div>,
}))
import { StaffForm } from './Staff'

beforeEach(() => post.mockReset())
afterEach(cleanup)

describe('Staff registration phone', () => {
  it('requires a valid phone for a new staff account and sends it with the account', async () => {
    post.mockResolvedValue({})
    const saved = vi.fn()
    render(<StaffForm onSaved={saved} />)
    fireEvent.change(screen.getByLabelText('Full name'), { target: { value: 'Ravi' } })
    fireEvent.change(screen.getByLabelText('Login name'), { target: { value: 'ravi' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'Fieldw0rk!' } })
    expect(screen.getByRole('button', { name: 'Save' }).disabled).toBe(true)
    expect(screen.getByLabelText('Phone (required)').required).toBe(true)
    fireEvent.change(screen.getByLabelText('Phone (required)'), { target: { value: '123' } })
    expect(screen.getByRole('button', { name: 'Save' }).disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('Phone (required)'), { target: { value: '1111111111' } })
    expect(screen.getByRole('button', { name: 'Save' }).disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('Phone (required)'), { target: { value: '+91 98765 43210' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/staff', expect.objectContaining({ phone: '+91 98765 43210', login_name: 'ravi' })))
    expect(saved).toHaveBeenCalled()
  })

  it('allows an existing staff account without a phone to be edited', () => {
    render(<StaffForm staff={{ id: 5, name: 'Legacy staff', login_name: 'legacy', phone: null }} />)
    expect(screen.getByLabelText('Phone').required).toBe(false)
    expect(screen.getByRole('button', { name: 'Save' }).disabled).toBe(false)
  })
})
