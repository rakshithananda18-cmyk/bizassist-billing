// @vitest-environment jsdom
import React from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
const auth = vi.hoisted(() => ({ ownerLogin: vi.fn(), staffLogin: vi.fn(), notice: null }))
vi.mock('../lib/auth', () => ({ useAuth: () => auth, lastBizId: () => '' }))
vi.mock('../lib/theme', () => ({ getBillingUrl: path => 'https://billing.example' + path }))
import Login from './Login'
afterEach(cleanup)

describe('Field owner onboarding', () => {
  it('routes new owners to the shared Billing registration and trial flow', () => {
    render(<Login />)
    fireEvent.click(screen.getByRole('tab', { name: 'Owner Login' }))
    expect(screen.getByRole('link', { name: 'Register in Billing' }).getAttribute('href')).toBe('https://billing.example/register')
    expect(screen.getByText(/14-day Pro trial in Billing/)).toBeTruthy()
    expect(screen.queryByLabelText('Phone (optional)')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Create Account' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Sign In as Owner' })).toBeTruthy()
  })
})
