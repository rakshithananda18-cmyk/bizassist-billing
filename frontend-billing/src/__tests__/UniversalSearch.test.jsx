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
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'

const authFetch = vi.fn()
let mockUser = { role: 'owner' }
let mockSettings = null
const navigate = vi.fn()

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ authFetch, user: mockUser, settings: mockSettings }),
}))
// vi.hoisted: vi.mock is lifted above the file, so a plain top-level const is
// still in its TDZ when the factory runs.
const { openAiDashboard } = vi.hoisted(() => ({ openAiDashboard: vi.fn() }))
vi.mock('../config/aiDashboard', () => ({
  getAiDashboardUrl: () => 'http://localhost:5173',
  openAiDashboard,
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

/** Each page header declares where the single search trigger belongs. */
const mountHeaderSlot = () => {
  const el = document.createElement('div')
  el.setAttribute('data-header-search-slot', '')
  el.className = 'header-search-slot'
  document.body.appendChild(el)
  return el
}

beforeEach(() => {
  authFetch.mockReset()
  navigate.mockReset()
  mockUser = { role: 'owner' }
  mockSettings = null
  authFetch.mockResolvedValue(ok({ items: [] }))
  localStorage.clear()
})
afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
  document.querySelectorAll('[data-header-search-slot]').forEach(el => el.remove())
})

describe('UniversalSearch', () => {
  it('can hide the Home trigger while keeping the keyboard search available', () => {
    const view = render(<MemoryRouter><UniversalSearch hideTrigger /></MemoryRouter>)
    expect(screen.queryByRole('button', { name: 'Search anything (Ctrl+Space)' })).toBeNull()
    expect(document.querySelector('.usearch-header-fallback')).toBeNull()
    openPalette()
    expect(screen.getByRole('dialog', { name: 'Search' })).toBeTruthy()
    fireEvent.keyDown(window, { key: 'Escape' })
    view.rerender(<MemoryRouter><UniversalSearch /></MemoryRouter>)
    expect(screen.getByRole('button', { name: 'Search anything (Ctrl+Space)' })).toBeTruthy()
  })

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

  it('opens from its page header instead of a bottom floating button', async () => {
    const slot = mountHeaderSlot()
    draw()
    const button = await screen.findByRole('button', { name: 'Search anything (Ctrl+Space)' })
    expect(slot).toContainElement(button)
    expect(document.querySelector('.usearch-dock')).toBeNull()
    fireEvent.click(button)
    expect(screen.getByPlaceholderText(/Search invoices/i)).toBeTruthy()
  })

  it('opens an empty search from the generic placeholder hint', async () => {
    mockSettings = { subscription: { plan: 'pro' } }
    mountHeaderSlot()
    draw()
    const button = await screen.findByRole('button', { name: 'Search anything (Ctrl+Space)' })
    fireEvent.click(button)
    const input = screen.getByPlaceholderText(/Search invoices/i)
    expect(input.value).toBe('')
    expect(screen.queryByRole('button', { name: 'Clear search' })).toBeNull()
    expect(screen.queryByText('Ask the assistant')).toBeNull()
    expect(authFetch).not.toHaveBeenCalled()
  })

  it.each(['{Enter}', ' '])('clears the query with the focused Clear button using %j', async (key) => {
    const user = userEvent.setup()
    const posHandler = vi.fn()
    window.addEventListener('keydown', posHandler)
    try {
      draw()
      openPalette()
      type('print')
      const input = screen.getByPlaceholderText(/Search invoices/i)
      await waitFor(() => expect(input).toHaveFocus())
      await user.tab()
      expect(screen.getByRole('button', { name: 'Clear search' })).toHaveFocus()
      posHandler.mockClear()
      await user.keyboard(key)
      expect(input.value).toBe('')
      expect(input).toHaveFocus()
      expect(screen.getByRole('dialog', { name: 'Search' })).toBeTruthy()
      expect(navigate).not.toHaveBeenCalled()
      expect(posHandler).not.toHaveBeenCalled()
    } finally {
      window.removeEventListener('keydown', posHandler)
    }
  })

  it.each(['{Enter}', ' '])('closes with the focused Close button using %j', async (key) => {
    const user = userEvent.setup()
    const posHandler = vi.fn()
    window.addEventListener('keydown', posHandler)
    try {
      draw()
      openPalette()
      type('print')
      await waitFor(() => expect(screen.getByPlaceholderText(/Search invoices/i)).toHaveFocus())
      await user.tab()
      await user.tab()
      expect(screen.getByRole('button', { name: 'Close search' })).toHaveFocus()
      posHandler.mockClear()
      await user.keyboard(key)
      expect(screen.queryByRole('dialog', { name: 'Search' })).toBeNull()
      expect(navigate).not.toHaveBeenCalled()
      expect(posHandler).not.toHaveBeenCalled()
    } finally {
      window.removeEventListener('keydown', posHandler)
    }
  })

  it.each(['{Enter}', ' '])('opens the focused result instead of the highlighted result using %j', async (key) => {
    const user = userEvent.setup()
    draw()
    openPalette()
    type('print')
    await waitFor(() => expect(screen.getByPlaceholderText(/Search invoices/i)).toHaveFocus())
    const highlighted = screen.getByText('Print Logo').closest('button')
    const focused = screen.getByText('Print Company Name').closest('button')
    focused.focus()
    await user.keyboard('{ArrowDown}')
    expect(highlighted).toHaveAttribute('aria-selected', 'true')
    expect(focused).toHaveFocus()
    await user.keyboard(key)
    expect(navigate).toHaveBeenCalledTimes(1)
    expect(navigate).toHaveBeenCalledWith('/settings?tab=print&field=print_company_name')
  })

  it('moves the highlighted result with arrows and opens it from the query input', async () => {
    const user = userEvent.setup()
    draw()
    openPalette()
    type('print')
    const input = screen.getByPlaceholderText(/Search invoices/i)
    await waitFor(() => expect(input).toHaveFocus())
    await user.keyboard('{ArrowDown}{ArrowDown}{ArrowUp}')
    expect(screen.getByText('Print Company Name').closest('button')).toHaveAttribute('aria-selected', 'true')
    expect(input).toHaveFocus()
    await user.keyboard('{Enter}')
    expect(navigate).toHaveBeenCalledTimes(1)
    expect(navigate).toHaveBeenCalledWith('/settings?tab=print&field=print_company_name')
  })

  it('keeps header search available when the old floating button was hidden', async () => {
    const slot = mountHeaderSlot()
    localStorage.setItem('usearch_fab_hidden', '1')
    draw()
    await waitFor(() => expect(slot.querySelector('.usearch-header-trigger')).toBeTruthy())
    expect(document.querySelector('.usearch-header-fallback')).toBeNull()
  })

  it('reattaches when a loading page creates or replaces its header', async () => {
    draw()
    expect(document.querySelector('.usearch-header-fallback')).toBeTruthy()
    let slot
    act(() => { slot = mountHeaderSlot() })
    await waitFor(() => expect(slot.querySelector('.usearch-header-trigger')).toBeTruthy())
    let replacement
    act(() => { slot.remove(); replacement = mountHeaderSlot() })
    await waitFor(() => expect(replacement.querySelector('.usearch-header-trigger')).toBeTruthy())
    expect(screen.getAllByRole('button', { name: 'Search anything (Ctrl+Space)' })).toHaveLength(1)
  })

  it('keeps a compact top-right trigger where no header slot exists', () => {
    localStorage.setItem('usearch_fab_hidden', '1')
    draw()
    fireEvent.click(document.querySelector('.usearch-header-fallback button'))
    expect(screen.getByPlaceholderText(/Search invoices/i)).toBeTruthy()
  })

  it('rotates suggestions without sending a search or AI request', () => {
    vi.useFakeTimers()
    mountHeaderSlot()
    draw()
    expect(screen.getByText('Find anything')).toBeTruthy()
    act(() => vi.advanceTimersByTime(6500))
    expect(screen.getByText('Find a bill, item or customer')).toBeTruthy()
    expect(authFetch).not.toHaveBeenCalled()
  })

  it('keeps a generic category suggestion out of the query', () => {
    vi.useFakeTimers()
    draw()
    act(() => vi.advanceTimersByTime(6500))
    fireEvent.click(screen.getByRole('button', { name: 'Search anything (Ctrl+Space)' }))
    expect(screen.getByPlaceholderText(/Search invoices/i).value).toBe('')
    expect(authFetch).not.toHaveBeenCalled()
  })

  it('prefills a suggested question without automatically asking AI', () => {
    vi.useFakeTimers()
    mockSettings = { subscription: { plan: 'pro' } }
    draw()
    act(() => vi.advanceTimersByTime(6500))
    fireEvent.click(screen.getByRole('button', { name: 'Search anything (Ctrl+Space)' }))
    expect(screen.getByPlaceholderText(/Search invoices/i).value).toBe('How are sales doing today?')
    expect(screen.getByText('Ask the assistant')).toBeTruthy()
    expect(authFetch).not.toHaveBeenCalled()
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

// ── Ask AI (Phase 1) ─────────────────────────────────────────────────────────
// /ask/stream is Pro-only and refuses cashiers, enforced server-side. The client
// mirrors both so a free plan is never SHOWN a control that would 402.
//
// The load-bearing assertion is that NOTHING fires while typing: /search is
// cheap and debounced, but the AI router costs ~841 tokens per invocation before
// the model answers at all. Per-keystroke would be ruinous.
describe('UniversalSearch — Ask AI', () => {
  const PRO = { subscription: { plan: 'pro' } }

  /** An SSE body, chunked exactly as the endpoint emits it. */
  const sse = (...events) => ({
    ok: true, status: 200,
    body: {
      getReader() {
        const chunks = events.map(e => new TextEncoder().encode(`data: ${JSON.stringify(e)}\n\n`))
        let i = 0
        return { read: async () => (i < chunks.length
          ? { done: false, value: chunks[i++] }
          : { done: true, value: undefined }) }
      },
    },
  })

  const askRow = () => [...document.querySelectorAll('.usearch-row')]
    .find(r => r.textContent.includes('Ask the assistant'))

  it('offers the row to a Pro owner', () => {
    mockSettings = PRO
    draw(); openPalette(); type('why are my sales down')
    expect(askRow()).toBeTruthy()
  })

  it('does not offer it when the owner switches it off', () => {
    mockSettings = { subscription: { plan: 'pro' }, general: { ai_search_enabled: false } }
    draw(); openPalette(); type('why are my sales down')
    expect(askRow()).toBeUndefined()
  })

  it('offers it when the setting has never been saved', () => {
    // An account that predates the key must keep the current behaviour rather
    // than silently lose the row.
    mockSettings = { subscription: { plan: 'pro' }, general: {} }
    draw(); openPalette(); type('why are my sales down')
    expect(askRow()).toBeTruthy()
  })

  it('does not offer it on a free plan', () => {
    mockSettings = { subscription: { plan: 'free' } }
    draw(); openPalette(); type('why are my sales down')
    expect(askRow()).toBeUndefined()
  })

  it('does not offer it to a cashier, even on Pro', () => {
    mockSettings = PRO
    mockUser = { role: 'cashier' }
    draw(); openPalette(); type('why are my sales down')
    expect(askRow()).toBeUndefined()
  })

  it('does not offer it for a short query', () => {
    // 'sugar' is a half-typed product name, not a question.
    mockSettings = PRO
    draw(); openPalette(); type('sugar')
    expect(askRow()).toBeUndefined()
  })

  it('does not offer it for a ONE-WORD navigation query', () => {
    // Reported: 'setting' is 7 chars, cleared the length bar, and the assistant
    // answered about invoice totals and a "Send Reminder" button that does not
    // exist. One word is a page, a product or a customer — all of which the
    // palette already resolves instantly and for free.
    mockSettings = PRO
    draw(); openPalette(); type('setting')
    expect(askRow()).toBeUndefined()
    // ...and the page match is still right there.
    expect(screen.getByText('Settings')).toBeTruthy()
  })

  it('still offers it for a short multi-word question', () => {
    // No question word here, and it must still qualify — a whitelist would
    // train owners to phrase things for the parser.
    mockSettings = PRO
    draw(); openPalette(); type('sales down')
    expect(askRow()).toBeTruthy()
  })

  it('ignores trailing whitespace when counting words', () => {
    mockSettings = PRO
    draw(); openPalette(); type('setting   ')
    expect(askRow()).toBeUndefined()
  })

  it('NEVER calls the AI while typing', async () => {
    mockSettings = PRO
    draw(); openPalette()
    type('why are my sales down this month')
    await waitFor(() => expect(authFetch).toHaveBeenCalled(), { timeout: 2000 })
    const paths = authFetch.mock.calls.map(c => c[0])
    expect(paths.some(p => String(p).includes('/ask'))).toBe(false)
    expect(paths.some(p => String(p).includes('/search'))).toBe(true)
  })

  it('streams an answer only once the row is chosen', async () => {
    mockSettings = PRO
    authFetch.mockImplementation((path) => path.includes('/ask/stream')
      ? Promise.resolve(sse({ type: 'token', content: 'Sales fell ' },
                            { type: 'token', content: '12% in July.' },
                            { type: 'done', source: 'ai' }))
      : Promise.resolve(ok({ items: [] })))

    draw(); openPalette(); type('why are my sales down')
    await act(async () => { fireEvent.click(askRow()) })

    await waitFor(() => expect(document.querySelector('.usearch-ask-body')?.textContent)
      .toContain('Sales fell 12% in July.'))
    // The palette stays open: the records that matched are still the fastest
    // route to what the owner wanted.
    expect(screen.getByPlaceholderText(/Search invoices/i)).toBeTruthy()
  })

  it('hides the row for the session when AI is not configured (503)', async () => {
    mockSettings = PRO
    authFetch.mockImplementation((path) => path.includes('/ask/stream')
      ? Promise.resolve({ ok: false, status: 503, json: async () => ({ detail: "AI features aren't configured on this device." }) })
      : Promise.resolve(ok({ items: [] })))

    draw(); openPalette(); type('why are my sales down')
    await act(async () => { fireEvent.click(askRow()) })

    await waitFor(() => expect(document.querySelector('.usearch-ask-error')?.textContent)
      .toMatch(/aren't configured/i))
    // Offering it again would fail identically every time.
    type('why are my sales down again')
    expect(askRow()).toBeUndefined()
  })

  it('surfaces a mid-stream error instead of spinning', async () => {
    mockSettings = PRO
    authFetch.mockImplementation((path) => path.includes('/ask/stream')
      ? Promise.resolve(sse({ type: 'error', content: 'The model is rate limited.' }))
      : Promise.resolve(ok({ items: [] })))

    draw(); openPalette(); type('why are my sales down')
    await act(async () => { fireEvent.click(askRow()) })
    await waitFor(() => expect(document.querySelector('.usearch-ask-error')?.textContent)
      .toContain('rate limited'))
  })

  it('does not spin forever when the stream ends with no terminal event', async () => {
    // A proxy idle-timeout or container restart ends the reader with done:true
    // and no 'done' event. Without a guard the pane sits on "Thinking…".
    mockSettings = PRO
    authFetch.mockImplementation((path) => path.includes('/ask/stream')
      ? Promise.resolve(sse({ type: 'status', content: 'Thinking…' }))
      : Promise.resolve(ok({ items: [] })))

    draw(); openPalette(); type('why are my sales down')
    await act(async () => { fireEvent.click(askRow()) })
    await waitFor(() => expect(document.querySelector('.usearch-ask-error')?.textContent)
      .toMatch(/ended before an answer/i))
  })

  it('retires the answer when the question is edited', async () => {
    mockSettings = PRO
    authFetch.mockImplementation((path) => path.includes('/ask/stream')
      ? Promise.resolve(sse({ type: 'replace', content: 'An answer.' }, { type: 'done' }))
      : Promise.resolve(ok({ items: [] })))

    draw(); openPalette(); type('why are my sales down')
    await act(async () => { fireEvent.click(askRow()) })
    await waitFor(() => expect(document.querySelector('.usearch-ask-body')).toBeTruthy())

    // Leaving it on screen under new text reads as a reply to the new question.
    type('why are my sales down in august')
    expect(document.querySelector('.usearch-ask')).toBeNull()
  })
})

// ── ACTION hand-off ──────────────────────────────────────────────────────────
// The router returns source:'action' for the five WRITE actions
// (send_payment_reminders, mark_invoice_paid, email_reminder_digest,
// escalate_overdue, draft_reorder_po) — two of which email customers and one of
// which marks an invoice paid. It never executes them; it returns a confirm chip.
//
// The palette deliberately does NOT render that chip. A money-and-email
// confirmation implemented in two surfaces is two places to drift, and
// Ctrl+Space → type → Enter is the wrong ceremony for "email 20 customers".
// It hands off to the AI Advisor, which owns confirmation.
describe('UniversalSearch — action hand-off', () => {
  const PRO = { subscription: { plan: 'pro' } }

  const sse = (...events) => ({
    ok: true, status: 200,
    body: {
      getReader() {
        const chunks = events.map(e => new TextEncoder().encode(`data: ${JSON.stringify(e)}

`))
        let i = 0
        return { read: async () => (i < chunks.length
          ? { done: false, value: chunks[i++] }
          : { done: true, value: undefined }) }
      },
    },
  })
  const askRow = () => [...document.querySelectorAll('.usearch-row')]
    .find(r => r.textContent.includes('Ask the assistant'))

  const ACTION_REPLY = [
    { type: 'replace', content: 'I can send payment reminders for you. Nothing is sent or changed until you confirm.' },
    { type: 'done', source: 'action', suggestions: [{ id: 'send_payment_reminders', confirm: true }] },
  ]

  it('offers the AI Advisor instead of a confirm button', async () => {
    mockSettings = PRO
    authFetch.mockImplementation((path) => path.includes('/ask/stream')
      ? Promise.resolve(sse(...ACTION_REPLY))
      : Promise.resolve(ok({ items: [] })))

    draw(); openPalette(); type('send payment reminders to overdue customers')
    await act(async () => { fireEvent.click(askRow()) })

    await waitFor(() => expect(document.querySelector('.usearch-ask-handoff')).toBeTruthy())
    fireEvent.click(screen.getByText(/Open AI Advisor/i))
    expect(openAiDashboard).toHaveBeenCalled()
  })

  it('never renders a confirm control for a write action', async () => {
    mockSettings = PRO
    authFetch.mockImplementation((path) => path.includes('/ask/stream')
      ? Promise.resolve(sse(...ACTION_REPLY))
      : Promise.resolve(ok({ items: [] })))

    draw(); openPalette(); type('send payment reminders to overdue customers')
    await act(async () => { fireEvent.click(askRow()) })
    await waitFor(() => expect(document.querySelector('.usearch-ask-handoff')).toBeTruthy())

    // Assert on the CONTROLS, not the prose — the hand-off copy legitimately
    // contains the word "Confirming", and matching text made this test fail on
    // its own explanation rather than on behaviour.
    // Accessible name, not text: the dismiss control is icon-only.
    const buttons = [...document.querySelectorAll('.usearch-ask button')]
      .map(b => b.getAttribute('aria-label') || b.textContent.trim())
    expect(buttons).toEqual(['Dismiss answer', 'Open AI Advisor'])
    // And nothing in the palette may reach the execute endpoint.
    expect(authFetch.mock.calls.map(c => String(c[0])).some(p => p.includes('/action'))).toBe(false)
  })

  it('does not hand off for an ordinary answer', async () => {
    mockSettings = PRO
    authFetch.mockImplementation((path) => path.includes('/ask/stream')
      ? Promise.resolve(sse({ type: 'token', content: 'Revenue is down 12%.' },
                            { type: 'done', source: 'ai' }))
      : Promise.resolve(ok({ items: [] })))

    draw(); openPalette(); type('why are my sales down')
    await act(async () => { fireEvent.click(askRow()) })
    await waitFor(() => expect(document.querySelector('.usearch-ask-body')?.textContent)
      .toContain('Revenue is down 12%.'))
    expect(document.querySelector('.usearch-ask-handoff')).toBeNull()
  })
})
