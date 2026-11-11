// @vitest-environment jsdom
import React from 'react'
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('../lib/auth', () => ({ useAuth: () => ({ me: { kind: 'owner', public_id: 'QA-ONE', business_name: 'Sample store' }, logout: vi.fn() }) }))
vi.mock('../lib/theme', () => ({ getTheme: () => 'light', setTheme: vi.fn() }))
vi.mock('../components/ui', () => ({ useToast: () => vi.fn() }))
vi.mock('../components/NotificationBell', () => ({ default: () => null }))
vi.mock('../components/WorkspaceSwitcher', () => ({ default: () => <div>Billing and Field Team</div> }))
vi.mock('../components/UniversalSearchModal', () => ({ default: ({ open, onClose }) => open ? <div role="dialog" aria-label="Search workspaces"><button onClick={onClose}>Close search</button></div> : null }))
import OwnerLayout from './OwnerLayout'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); localStorage.clear() })
function mount(phone) {
  const media = { matches: phone, addEventListener: vi.fn(), removeEventListener: vi.fn() }
  vi.stubGlobal('matchMedia', vi.fn(() => media))
  render(<MemoryRouter><Routes><Route element={<OwnerLayout />}><Route index element={<button>Workspace action</button>} /></Route></Routes></MemoryRouter>)
  return media
}

describe('Owner workspace navigation', () => {
  it('keeps tablet navigation as the full sidebar and supports search from the keyboard', () => {
    mount(false)
    expect(screen.queryByRole('navigation', { name: 'Primary' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Open navigation menu' })).toBeNull()
    expect(screen.getByRole('link', { name: 'Day plan' })).toBeTruthy()
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
    expect(screen.getByRole('dialog', { name: 'Search workspaces' })).toBeTruthy()
  })

  it('offers five accessible icon-only phone destinations and closes the drawer when returning to tablet', () => {
    const media = mount(true)
    const links = within(screen.getByRole('navigation', { name: 'Primary' })).getAllByRole('link')
    expect(links).toHaveLength(5)
    links.forEach(link => { expect(link.getAttribute('aria-label')).toBeTruthy(); expect(link.querySelector('svg')).toBeTruthy(); expect(link.textContent).toBe('') })
    fireEvent.click(screen.getByRole('button', { name: 'Open navigation menu' }))
    expect(screen.getByRole('dialog', { name: 'Navigation menu' }).getAttribute('aria-hidden')).toBe(null)
    const change = media.addEventListener.mock.calls.find(([type]) => type === 'change')[1]
    act(() => { media.matches = false; change() })
    expect(screen.queryByRole('dialog', { name: 'Navigation menu' })).toBeNull()
    expect(window.matchMedia.mock.calls[0][0]).toBe('screen and (max-width: 600px)')
  })

  it('dismisses the phone account menu when clicking in the workspace', () => {
    mount(true)
    fireEvent.click(document.querySelector('.mobile-user-avatar'))
    expect(document.querySelector('#mobile-account-menu')).toBeTruthy()
    fireEvent.mouseDown(screen.getByRole('button', { name: 'Workspace action' }))
    expect(document.querySelector('#mobile-account-menu')).toBeNull()
  })
})
