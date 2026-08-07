// The search palette: what it asks, what it shows before the network answers,
// and that it cannot be opened into a dead end.
//
// The keyboard assertions matter more than they look. The POS binds Escape,
// Ctrl+S, Ctrl+P and `+` at the WINDOW (pages/Sales.jsx) without always checking
// whether focus is in an input — so a palette that lets keys through would, on
// /sales, close itself AND proceed to payment on one Escape.
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const authFetch = vi.fn()
let mockUser = { role: 'owner' }
const navigate = vi.fn()

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ authFetch, user: mockUser }),
}))
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => navigate }
})

import UniversalSearch from '../components/UniversalSearch'

const ok = (body) => ({ ok: true, status: 200, json: async () => body })
const draw = () => render(<MemoryRouter><UniversalSearch /></MemoryRouter>)

const openPalette = () => {
  fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
}
const type = (value) =>
  fireEvent.change(screen.getByPlaceholderText(/Search invoices/i), { target: { value } })

beforeEach(() => {
  authFetch.mockReset()
  navigate.mockReset()
  mockUser = { role: 'owner' }
  authFetch.mockResolvedValue(ok({ items: [] }))
})
afterEach(() => { vi.clearAllTimers() })

describe('UniversalSearch', () => {
  it('opens on Ctrl+K and closes on Escape', () => {
    draw()
    expect(screen.queryByPlaceholderText(/Search invoices/i)).toBeNull()
    openPalette()
    expect(screen.getByPlaceholderText(/Search invoices/i)).toBeTruthy()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByPlaceholderText(/Search invoices/i)).toBeNull()
  })

  it('shows page matches before the network answers', async () => {
    // Static entries are matched locally, so they must paint on the keystroke
    // rather than waiting for /search. A never-resolving lookup proves it.
    authFetch.mockImplementation(() => new Promise(() => {}))
    draw()
    openPalette()
    type('gst')
    expect(screen.getByText('GST Summary')).toBeTruthy()
  })

  it('asks the backend through authFetch, not a raw URL', async () => {
    // authFetch pins the request to THIS session's backend; a bare fetch to the
    // cloud would resolve the business id in the wrong database.
    draw()
    openPalette()
    type('ram')
    await waitFor(() => {
      expect(authFetch).toHaveBeenCalledWith(expect.stringContaining('/search?q=ram'))
    }, { timeout: 2000 })
  })

  it('sends an invoice to its record route, keyed by number', async () => {
    authFetch.mockResolvedValue(ok({ items: [
      { kind: 'invoice', id: 'INV-42', title: 'INV-42', subtitle: 'Acme · ₹250' },
    ] }))
    draw()
    openPalette()
    type('INV-42')
    await waitFor(() => expect(screen.getByText('INV-42')).toBeTruthy(), { timeout: 2000 })
    fireEvent.click(screen.getByText('INV-42'))
    expect(navigate).toHaveBeenCalledWith('/invoice/INV-42/view')
  })

  it('sends a product to the stock list, seeded with its name', async () => {
    // Products have no record route; the palette seeds the destination's own
    // search box instead of inventing a deep link that does not exist.
    authFetch.mockResolvedValue(ok({ items: [
      { kind: 'product', id: 7, title: 'Sugar 50kg', subtitle: 'SKU9' },
    ] }))
    draw()
    openPalette()
    type('sugar')
    await waitFor(() => expect(screen.getByText('Sugar 50kg')).toBeTruthy(), { timeout: 2000 })
    fireEvent.click(screen.getByText('Sugar 50kg'))
    expect(navigate).toHaveBeenCalledWith('/stock/inventory?q=Sugar%2050kg')
  })

  it('deep-links a settings field to its row', async () => {
    draw()
    openPalette()
    type('logo')
    fireEvent.click(screen.getByText('Print Logo'))
    expect(navigate).toHaveBeenCalledWith('/settings?tab=print&field=print_logo')
  })

  it('offers a cashier nothing they cannot open', () => {
    // Reports and Settings refuse a cashier, so surfacing them is a dead end.
    mockUser = { role: 'cashier' }
    draw()
    openPalette()
    type('gst')
    expect(screen.queryByText('GST Summary')).toBeNull()
    type('logo')
    expect(screen.queryByText('Print Logo')).toBeNull()
  })

  it('stops keys reaching the POS handlers while open', () => {
    // Fired at the INPUT, not at window — that is what a real keystroke does,
    // and the distinction decides the test. Dispatching on window makes window
    // the target, and at the target node capture/bubble ordering collapses to
    // registration order, so whichever listener was added first wins and the
    // shield looks broken. A real keypress travels window(capture) → input →
    // window(bubble), so the capture guard runs first and the event never
    // reaches Sales.jsx's window-level handler.
    const posHandler = vi.fn()
    window.addEventListener('keydown', posHandler)      // bubble, like Sales.jsx
    try {
      draw()
      openPalette()
      const input = screen.getByPlaceholderText(/Search invoices/i)
      posHandler.mockClear()                            // ignore the opening Ctrl+K
      fireEvent.keyDown(input, { key: 's', ctrlKey: true })   // POS: save invoice
      fireEvent.keyDown(input, { key: '+' })                  // POS: bump last line
      fireEvent.keyDown(input, { key: 'Escape' })             // POS: proceed to payment
      expect(posHandler).not.toHaveBeenCalled()
    } finally {
      window.removeEventListener('keydown', posHandler)
    }
  })

  it('keeps working when the record lookup fails', async () => {
    // The static half is local. A backend blip must not empty the palette.
    authFetch.mockRejectedValue(new Error('network'))
    draw()
    openPalette()
    type('gst')
    expect(screen.getByText('GST Summary')).toBeTruthy()
  })
})
