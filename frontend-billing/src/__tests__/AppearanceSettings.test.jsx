import React from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { appearanceStorageKey, CUSTOM_THEME_DEFAULTS } from '../utils/appearance'

const auth = vi.hoisted(() => ({ user: { id: 1, public_id: 'SHOP-A' } }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => auth }))

import AppearanceSettings from '../components/settings/AppearanceSettings'
import { useAppearance } from '../hooks/useAppearance'

// normalizeAppearance always includes these extra fields
const extras = { customColors: CUSTOM_THEME_DEFAULTS, windowGradient: false, darkerSidebar: false }

let prefersDark = false
let listeners
const originalMatchMedia = window.matchMedia
function Consumer() {
  const { theme, accent, resolvedTheme } = useAppearance()
  return <output>{`${theme}/${accent}/${resolvedTheme}`}</output>
}

beforeEach(() => {
  auth.user = { id: 1, public_id: 'SHOP-A' }
  prefersDark = false
  listeners = new Set()
  window.matchMedia = () => ({
    matches: prefersDark,
    addEventListener: (_, fn) => listeners.add(fn),
    removeEventListener: (_, fn) => listeners.delete(fn),
  })
  document.documentElement.classList.remove('dark-mode')
  localStorage.clear()
})
afterEach(() => { cleanup(); window.matchMedia = originalMatchMedia })

describe('Appearance settings', () => {
  it('applies a mode and palette immediately and shares them with the app layout', () => {
    render(<><Consumer /><AppearanceSettings /></>)
    fireEvent.click(screen.getByRole('button', { name: 'Dark mode' }))
    fireEvent.click(screen.getByRole('button', { name: 'Ocean palette' }))
    expect(screen.getByText('dark/ocean/dark')).toBeInTheDocument()
    expect(document.documentElement).toHaveClass('dark-mode')
    expect(document.documentElement.dataset.accent).toBe('ocean')
    expect(document.documentElement.style.getPropertyValue('--accent-solid')).toBe('#245eac')
    expect(JSON.parse(localStorage.getItem(appearanceStorageKey(auth.user)))).toEqual({ theme: 'dark', accent: 'ocean', ...extras })
    expect(screen.getByRole('button', { name: 'Ocean palette' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('restores each account without carrying the other account colours over', () => {
    const view = render(<AppearanceSettings />)
    fireEvent.click(screen.getByRole('button', { name: 'Dark mode' }))
    fireEvent.click(screen.getByRole('button', { name: 'Rose palette' }))
    auth.user = { id: 2, public_id: 'SHOP-A' }
    view.rerender(<AppearanceSettings />)
    expect(screen.getByRole('button', { name: 'System mode' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Terracotta palette' })).toHaveAttribute('aria-pressed', 'true')
    auth.user = { id: 1, public_id: 'SHOP-A' }
    view.rerender(<AppearanceSettings />)
    expect(screen.getByRole('button', { name: 'Dark mode' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Rose palette' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('follows the system colour mode until a fixed mode is chosen', () => {
    render(<AppearanceSettings />)
    act(() => { prefersDark = true; listeners.forEach(fn => fn({ matches: true })) })
    expect(document.documentElement).toHaveClass('dark-mode')
    fireEvent.click(screen.getByRole('button', { name: 'Light mode' }))
    act(() => { listeners.forEach(fn => fn({ matches: true })) })
    expect(document.documentElement).not.toHaveClass('dark-mode')
  })

  it('supports creating a custom palette and deleting it from a separate keyboard-accessible button', async () => {
    const user = userEvent.setup()
    render(<><Consumer /><AppearanceSettings /></>)

    // Open add custom palette modal
    fireEvent.click(screen.getByRole('button', { name: 'Add custom palette' }))
    expect(screen.getByText('Create Custom Palette')).toBeInTheDocument()

    // Fill in palette name
    const nameInput = screen.getByRole('textbox', { name: 'Palette Name' })
    fireEvent.change(nameInput, { target: { value: 'Sunset Gold' } })

    // Save palette
    fireEvent.click(screen.getByRole('button', { name: 'Save Palette' }))

    // Modal closed and custom palette card rendered and selected
    expect(screen.queryByText('Create Custom Palette')).not.toBeInTheDocument()
    const customBtn = screen.getByRole('button', { name: 'Sunset Gold palette' })
    expect(customBtn).toBeInTheDocument()
    expect(customBtn).toHaveAttribute('aria-pressed', 'true')

    // Delete custom palette
    const deleteBtn = screen.getByRole('button', { name: 'Delete Sunset Gold palette' })
    expect(deleteBtn.tagName).toBe('BUTTON')
    expect(deleteBtn).toHaveAttribute('type', 'button')
    expect(customBtn).not.toContainElement(deleteBtn)
    expect(customBtn.querySelector('button, [role="button"]')).toBeNull()
    customBtn.focus()
    await user.tab()
    expect(deleteBtn).toHaveFocus()
    await user.keyboard('{Enter}')

    // Palette removed and reverted to default terracotta
    expect(screen.queryByRole('button', { name: 'Sunset Gold palette' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Terracotta palette' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('closes the custom palette dialog on Escape and returns focus to Add', async () => {
    const user = userEvent.setup()
    render(<AppearanceSettings />)
    const addButton = screen.getByRole('button', { name: 'Add custom palette' })
    await user.click(addButton)
    expect(screen.getByRole('dialog', { name: 'Create Custom Palette' })).toHaveAttribute('aria-modal', 'true')
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Palette Name' })).toHaveFocus())
    await user.keyboard('{Escape}')
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Create Custom Palette' })).not.toBeInTheDocument()
      expect(addButton).toHaveFocus()
    })
  })

  it('restores custom palettes only for the account that created them', () => {
    const view = render(<AppearanceSettings />)
    fireEvent.click(screen.getByRole('button', { name: 'Add custom palette' }))
    fireEvent.change(screen.getByRole('textbox', { name: 'Palette Name' }), { target: { value: 'My Private Palette' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save Palette' }))
    expect(screen.getByRole('button', { name: 'My Private Palette palette' })).toHaveAttribute('aria-pressed', 'true')

    auth.user = { id: 2, public_id: 'SHOP-A' }
    view.rerender(<AppearanceSettings />)
    expect(screen.queryByRole('button', { name: 'My Private Palette palette' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete My Private Palette palette' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Terracotta palette' })).toHaveAttribute('aria-pressed', 'true')

    auth.user = { id: 1, public_id: 'SHOP-A' }
    view.rerender(<AppearanceSettings />)
    expect(screen.getByRole('button', { name: 'My Private Palette palette' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Delete My Private Palette palette' })).toBeInTheDocument()
  })

  it.each([
    'Accent & Brand Colour',
    'Sidebar Navigation Colour',
    'Card / Canvas Surface',
  ])('requires valid hex in the labelled %s field before saving', (label) => {
    render(<AppearanceSettings />)
    fireEvent.click(screen.getByRole('button', { name: 'Add custom palette' }))
    const hexInput = screen.getByRole('textbox', { name: label })
    const picker = screen.getByLabelText(`${label} picker`)
    expect(picker).toHaveAttribute('type', 'color')
    const saveButton = screen.getByRole('button', { name: 'Save Palette' })
    expect(saveButton).toBeEnabled()
    fireEvent.change(hexInput, { target: { value: '#zzzzzz' } })
    expect(saveButton).toBeDisabled()
    expect(screen.getByRole('alert')).toBeVisible()
    fireEvent.click(saveButton)
    expect(screen.getByRole('dialog', { name: 'Create Custom Palette' })).toBeInTheDocument()
    fireEvent.change(hexInput, { target: { value: '#2468ac' } })
    expect(saveButton).toBeEnabled()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(picker).toHaveValue('#2468ac')
  })
})
