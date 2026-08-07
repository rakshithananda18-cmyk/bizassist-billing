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

/** AppLayout renders this inside the sidebar; the palette portals into it. */
const mountSidebarSlot = () => {
  const el = document.createElement('div')
  el.id = 'usearch-slot'
  document.body.appendChild(el)
  return el
}

beforeEach(() => {
  authFetch.mockReset()
  navigate.mockReset()
  mockUser = { role: 'owner' }
  authFetch.mockResolvedValue(ok({ items: [] }))
  localStorage.clear()
})
afterEach(() => {
  vi.clearAllTimers()
  // querySelectorAll, not getElementById: the reload case below mounts a
  // second slot, and one left behind would leak into the next test.
  document.querySelectorAll('#usearch-slot').forEach(el => el.remove())
})

describe('UniversalSearch', () => {
  it('opens on Ctrl+Space', () => {
    // The advertised shortcut. `code` is asserted alongside `key` because a
    // modified space does not report `' '` consistently across browsers.
    draw()
    fireEvent.keyDown(document.body, { key: ' ', code: 'Space', ctrlKey: true })
    expect(screen.getByPlaceholderText(/Search invoices/i)).toBeTruthy()
    fireEvent.keyDown(window, { key: ' ', code: 'Space', ctrlKey: true })
    expect(screen.queryByPlaceholderText(/Search invoices/i)).toBeNull()
  })

  it('leaves an unmodified space alone', () => {
    // Typing a space in the query must not toggle the palette shut.
    draw()
    openPalette()
    fireEvent.keyDown(screen.getByPlaceholderText(/Search invoices/i), { key: ' ', code: 'Space' })
    expect(screen.getByPlaceholderText(/Search invoices/i)).toBeTruthy()
  })

  it('counts each group in its heading', () => {
    draw()
    openPalette()
    type('print')
    // The number is that group's own size, not the whole result list's — the
    // settings half is capped at 4 while pages also match 'print'.
    const headings = [...document.querySelectorAll('.usearch-group')]
    const settings = headings.find(h => h.textContent.startsWith('Settings'))
    expect(settings.textContent).toBe('Settings4')
    expect(headings.length).toBeGreaterThan(0)
  })

  it('does not repeat the group name on every row in it', () => {
    // A settings row hinting "Settings" under a "Settings" heading is noise.
    // The tab it lives on is the fact worth the space.
    draw()
    openPalette()
    type('logo')
    expect(screen.getByText('Print Logo').closest('.usearch-row').textContent)
      .toMatch(/Print$/)
  })

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

  it('stops the OPENING Ctrl+K reaching the POS too', () => {
    // Ctrl+K is free in DEFAULT_FUNC_KEYS, but lib/posKeys.js merges whatever
    // sits in localStorage.pos_func_keys over those defaults and the shortcuts
    // modal lets an owner rebind anything. So an owner who put saveInvoice on
    // Ctrl+K would otherwise open the palette AND save the bill on one press.
    //
    // Fired at document.body, not window: dispatching ON window makes window the
    // target, which collapses capture/bubble to registration order and lets the
    // handler registered first win. A real keypress reaches window's capture
    // listener before any bubble listener, which is what this asserts.
    const posHandler = vi.fn()
    window.addEventListener('keydown', posHandler)      // bubble, like Sales.jsx
    try {
      draw()
      fireEvent.keyDown(document.body, { key: 'k', ctrlKey: true })
      expect(screen.getByPlaceholderText(/Search invoices/i)).toBeTruthy()
      expect(posHandler).not.toHaveBeenCalled()
    } finally {
      window.removeEventListener('keydown', posHandler)
    }
  })

  it('collapses into the sidebar when dismissed, and stays there', async () => {
    mountSidebarSlot()
    const { unmount } = draw()

    await waitFor(() => expect(document.querySelector('.usearch-close')).toBeTruthy())
    fireEvent.click(document.querySelector('.usearch-close'))

    expect(document.querySelector('.usearch-dock')).toBeNull()
    const row = document.querySelector('#usearch-slot .usearch-slot-btn')
    expect(row).toBeTruthy()
    expect(row.textContent).toMatch(/Find anything/i)

    // A dismiss that a reload undoes is decoration, not a control.
    unmount()
    document.querySelectorAll('#usearch-slot').forEach(el => el.remove())
    mountSidebarSlot()
    draw()
    await waitFor(() => expect(document.querySelector('#usearch-slot .usearch-slot-btn')).toBeTruthy())
    expect(document.querySelector('.usearch-dock')).toBeNull()
  })

  it('opens the palette from the sidebar row', async () => {
    mountSidebarSlot()
    localStorage.setItem('usearch_fab_hidden', '1')
    draw()

    const row = await waitFor(() => {
      const el = document.querySelector('#usearch-slot .usearch-slot-main')
      expect(el).toBeTruthy()
      return el
    })
    fireEvent.click(row)
    expect(screen.getByPlaceholderText(/Search invoices/i)).toBeTruthy()
  })

  it('puts the floating trigger back from the sidebar row', async () => {
    // Dismissing is reversible or it is a trap: the expand glyph is the only
    // way back, so it gets a test rather than a hope.
    mountSidebarSlot()
    localStorage.setItem('usearch_fab_hidden', '1')
    draw()

    const expand = await waitFor(() => {
      const el = document.querySelector('#usearch-slot .usearch-slot-expand')
      expect(el).toBeTruthy()
      return el
    })
    fireEvent.click(expand)

    expect(document.querySelector('.usearch-dock')).toBeTruthy()
    expect(document.querySelector('#usearch-slot .usearch-slot-btn')).toBeNull()
    expect(localStorage.getItem('usearch_fab_hidden')).toBeNull()   // survives a reload
  })

  it('offers the way back from inside the palette too', async () => {
    // The sidebar row's glyph is display:none in the 56px collapsed rail, so
    // it cannot be the only restore. This one is reachable in every state.
    mountSidebarSlot()
    localStorage.setItem('usearch_fab_hidden', '1')
    draw()
    await waitFor(() => expect(document.querySelector('.usearch-slot-btn')).toBeTruthy())

    openPalette()
    fireEvent.click(screen.getByText(/Show floating button/i))

    expect(document.querySelector('.usearch-dock')).toBeTruthy()
    expect(localStorage.getItem('usearch_fab_hidden')).toBeNull()
    // Restoring closes the palette, or the change happens behind an overlay.
    expect(screen.queryByPlaceholderText(/Search invoices/i)).toBeNull()
  })

  it('keeps the floating trigger where there is no sidebar to fall back to', async () => {
    // /sales renders no sidebar. Honouring the stored dismiss there would
    // leave the page with no visible way into search at all.
    localStorage.setItem('usearch_fab_hidden', '1')
    draw()
    await waitFor(() => expect(document.querySelector('.usearch-dock')).toBeTruthy())
    expect(document.querySelector('.usearch-close')).toBeNull()   // nothing to dismiss into
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
