// OpsHealthPanel: owner-facing data-health view that surfaces the ops-health
// and sync-conflicts endpoints, and lets the owner clear a reviewed conflict.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, waitFor, fireEvent, act } from '@testing-library/react'
import React from 'react'

import OpsHealthPanel from '../components/settings/OpsHealthPanel'

function makeFetch({ ok = true, conflicts = [], inbox = null, outbox = [] } = {}) {
  return vi.fn(async (path, opts) => {
    if (path === '/reports/ops-health') {
      return { ok: true, json: async () => ({
        ok, business_id: 1,
        sync: { pending: ok ? 0 : 2, failed: ok ? 0 : 1, oldest_pending_at: null },
        conflicts: { unreviewed: conflicts.length },
        integrity: { ok: true, hash_chain_ok: true, journal_drift: 0.0 },
        ai_usage: { queries_today: 3, tokens_today: 1200, tokens_limit: 100000 },
      }) }
    }
    if (path === '/api/sync/conflicts') {
      return { ok: true, json: async () => ({ unreviewed_count: conflicts.length, conflicts }) }
    }
    if (path.startsWith('/api/sync/conflicts/') && opts?.method === 'POST') {
      return { ok: true, json: async () => ({ ok: true }) }
    }
    if (path === '/api/sync/outbox/details') {
      return { ok: true, json: async () => ({ count: outbox.length, items: outbox }) }
    }
    if (path === '/api/sync/inbox/details') {
      const items = inbox?.items || []
      return { ok: true, json: async () => ({
        count: items.length,
        stats: inbox?.stats || {
          pending_count: items.length, entity_counts: {},
          stuck_count: items.filter(i => i.stuck).length,
          deferred_count: items.filter(i => i.reason === 'deferred').length,
          rejected_count: items.filter(i => i.reason === 'rejected').length,
        },
        items,
      }) }
    }
    if (path.startsWith('/api/sync/inbox/') && opts?.method === 'POST') {
      return { ok: true, json: async () => ({ ok: true, requeued: true }) }
    }
    return { ok: false, json: async () => ({}) }
  })
}

const heldRow = (over = {}) => ({
  id: 5, entity: 'invoice_line_items', uid: 'abcdef1234', remote_id: 501,
  reason: 'deferred', attempts: 1, stuck: false,
  created_at: '2026-07-31T10:00:00', next_attempt_at: null, last_error: null,
  ...over,
})

afterEach(cleanup)

describe('OpsHealthPanel', () => {
  it('renders a healthy snapshot', async () => {
    render(<OpsHealthPanel authFetch={makeFetch({ ok: true })} />)
    await waitFor(() => expect(screen.getByText('All systems healthy')).toBeInTheDocument())
    expect(screen.getByText('AI tokens today')).toBeInTheDocument()
  })

  it('lists conflicts and clears one when marked reviewed', async () => {
    const conflicts = [{ id: 7, entity: 'invoices', entity_id: 42,
                         local_updated_at: '2026-07-20', cloud_updated_at: '2026-07-19' }]
    const authFetch = makeFetch({ ok: false, conflicts })
    render(<OpsHealthPanel authFetch={authFetch} />)
    await waitFor(() => expect(screen.getByText('invoices #42')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Mark reviewed'))
    // POST resolve was dispatched for id 7
    await waitFor(() =>
      expect(authFetch).toHaveBeenCalledWith('/api/sync/conflicts/7/resolve', { method: 'POST' })
    )
  })

  it('shows a soft fallback when the endpoint errors', async () => {
    const authFetch = vi.fn(async () => { throw new Error('offline') })
    render(<OpsHealthPanel authFetch={authFetch} />)
    await waitFor(() => expect(screen.getByText(/unavailable/i)).toBeInTheDocument())
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// SYNC INBOX — the pull-side half of the console
//
// Only the outbox was ever rendered, so a device could report a clean, empty
// queue while rows the cloud had sent sat un-applied and invisible. That is how
// deferred pull rows were dropped for months without anyone noticing.
// ─────────────────────────────────────────────────────────────────────────────
describe('OpsHealthPanel — Sync Inbox', () => {
  it('renders the card even when the inbox is empty', async () => {
    // An empty inbox and a failed request must not look identical — the same
    // lesson the outbox card already learned when it was hidden behind
    // `length > 0` and simply vanished from the page.
    render(<OpsHealthPanel authFetch={makeFetch({ ok: true })} />)
    await waitFor(() =>
      expect(screen.getByText(/Inbox is empty/i)).toBeInTheDocument())
  })

  it('lists a held row with why it is waiting', async () => {
    render(<OpsHealthPanel authFetch={makeFetch({ inbox: { items: [heldRow()] } })} />)
    await waitFor(() =>
      expect(screen.getByText(/invoice_line_items/)).toBeInTheDocument())
    expect(screen.getByText(/Waiting for its parent record to arrive/i)).toBeInTheDocument()
  })

  it('distinguishes a rejected row and shows its error', async () => {
    const row = heldRow({ reason: 'rejected', last_error: 'UNIQUE constraint failed' })
    render(<OpsHealthPanel authFetch={makeFetch({ inbox: { items: [row] } })} />)
    await waitFor(() =>
      expect(screen.getByText(/UNIQUE constraint failed/)).toBeInTheDocument())
  })

  it('calls the retry endpoint for a held row', async () => {
    const authFetch = makeFetch({ inbox: { items: [heldRow()] } })
    render(<OpsHealthPanel authFetch={authFetch} />)
    await waitFor(() => expect(screen.getAllByText('Retry Item').length).toBeGreaterThan(0))

    fireEvent.click(screen.getAllByText('Retry Item')[0])
    await waitFor(() =>
      expect(authFetch).toHaveBeenCalledWith('/api/sync/inbox/5/retry', { method: 'POST' }))
  })

  it('does NOT claim all systems healthy while rows are stuck', async () => {
    // health.ok is computed server-side from the OUTBOX and knows nothing about
    // the inbox. Trusting it alone would have the banner assert the exact thing
    // that was untrue for months.
    const row = heldRow({ stuck: true, reason: 'rejected', attempts: 7 })
    render(<OpsHealthPanel authFetch={makeFetch({
      ok: true, inbox: { items: [row], stats: { pending_count: 1, stuck_count: 1,
                                                deferred_count: 0, rejected_count: 1 } },
    })} />)
    await waitFor(() =>
      expect(screen.getByText(/could not be applied/i)).toBeInTheDocument())
    expect(screen.queryByText('All systems healthy')).toBeNull()
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// LIVE REFRESH
//
// The panel used to load exactly once. Its queues drain on BACKEND timers — a
// 15 s sync tick, per-row inbox backoff — none of which the frontend hears, so
// the numbers froze at whatever was true when Settings was opened. A console
// whose whole job is live queue depth cannot be a snapshot.
// ─────────────────────────────────────────────────────────────────────────────
describe('OpsHealthPanel — live refresh', () => {
  beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }) })
  afterEach(() => { vi.useRealTimers() })

  const countCalls = (f, path) => f.mock.calls.filter(c => c[0] === path).length

  it('refreshes when a sync event fires', async () => {
    const authFetch = makeFetch({ ok: true })
    render(<OpsHealthPanel authFetch={authFetch} />)
    await waitFor(() => expect(countCalls(authFetch, '/api/sync/inbox/details')).toBe(1))

    act(() => { window.dispatchEvent(new CustomEvent('sync-event', { detail: { entity: 'invoice' } })) })
    await act(async () => { await vi.advanceTimersByTimeAsync(1200) })          // past EVENT_DEBOUNCE_MS
    await waitFor(() =>
      expect(countCalls(authFetch, '/api/sync/inbox/details')).toBeGreaterThan(1))
  })

  it('coalesces a burst of sync events into ONE refresh', async () => {
    // A single invoice with eight line items emits one event per entity. Without
    // debouncing, opening Settings during a sync would hammer the backend — on a
    // hybrid setup, the owner's own machine.
    const authFetch = makeFetch({ ok: true })
    render(<OpsHealthPanel authFetch={authFetch} />)
    await waitFor(() => expect(countCalls(authFetch, '/api/sync/inbox/details')).toBe(1))

    for (let i = 0; i < 8; i++) {
      act(() => { window.dispatchEvent(new CustomEvent('sync-event', { detail: { entity: 'invoice' } })) })
    }
    await act(async () => { await vi.advanceTimersByTimeAsync(1200) })
    await waitFor(() => expect(countCalls(authFetch, '/api/sync/inbox/details')).toBe(2))
  })

  it('polls on an interval while the panel is on screen', async () => {
    const authFetch = makeFetch({ ok: true })
    render(<OpsHealthPanel authFetch={authFetch} />)
    await waitFor(() => expect(countCalls(authFetch, '/api/sync/inbox/details')).toBe(1))

    await act(async () => { await vi.advanceTimersByTimeAsync(11000) })         // past POLL_MS
    await waitFor(() =>
      expect(countCalls(authFetch, '/api/sync/inbox/details')).toBeGreaterThan(1))
  })

  it('stops polling once paused', async () => {
    // Rows that keep being replaced cannot be read — which matters most when the
    // owner is trying to copy an error message out of one.
    const authFetch = makeFetch({ ok: true })
    render(<OpsHealthPanel authFetch={authFetch} />)
    await waitFor(() => expect(screen.getByText('Pause')).toBeInTheDocument())

    act(() => { fireEvent.click(screen.getByText('Pause')) })
    const before = countCalls(authFetch, '/api/sync/inbox/details')
    await act(async () => { await vi.advanceTimersByTimeAsync(30000) })
    expect(countCalls(authFetch, '/api/sync/inbox/details')).toBe(before)
    expect(screen.getByText(/Paused/)).toBeInTheDocument()
  })

  it('a paused panel also ignores sync events', async () => {
    const authFetch = makeFetch({ ok: true })
    render(<OpsHealthPanel authFetch={authFetch} />)
    await waitFor(() => expect(screen.getByText('Pause')).toBeInTheDocument())
    act(() => { fireEvent.click(screen.getByText('Pause')) })

    const before = countCalls(authFetch, '/api/sync/inbox/details')
    act(() => { window.dispatchEvent(new CustomEvent('sync-event', { detail: { entity: 'invoice' } })) })
    await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
    expect(countCalls(authFetch, '/api/sync/inbox/details')).toBe(before)
  })

  it('does not blank the panel while refreshing in the background', async () => {
    // A silent refresh must not flip `loading`, or the console would flash its
    // loading placeholder every 10 seconds and be unreadable.
    //
    // This asserted `queryByText(/Checking data health/i)).toBeNull()`. That
    // text placeholder was replaced by <SkeletonTable> on 2026-07-31, so the
    // assertion started passing because the string no longer exists ANYWHERE —
    // it would have gone green even if the panel really were blanking. Same
    // hollow-assertion trap as the `_PULL_CURSOR` string check in
    // test_pull_partial.py. Query the placeholder that actually renders.
    const authFetch = makeFetch({ inbox: { items: [heldRow()] } })
    render(<OpsHealthPanel authFetch={authFetch} />)
    await waitFor(() => expect(screen.getByText(/invoice_line_items/)).toBeInTheDocument())

    await act(async () => { await vi.advanceTimersByTimeAsync(11000) })
    expect(screen.queryByTestId('ops-health-loading')).toBeNull()
    expect(screen.getByText(/invoice_line_items/)).toBeInTheDocument()
  })

  it('shows a skeleton on the FIRST load — so the placeholder is real', async () => {
    // Pins the other half: if the skeleton never rendered, the assertion above
    // would be vacuous again for a different reason.
    let release
    const gate = new Promise(r => { release = r })
    const inner = makeFetch({ ok: true })
    const authFetch = vi.fn(async (...a) => { await gate; return inner(...a) })

    render(<OpsHealthPanel authFetch={authFetch} />)
    expect(screen.getByTestId('ops-health-loading')).toBeInTheDocument()

    release()
    await waitFor(() => expect(screen.queryByTestId('ops-health-loading')).toBeNull())
  })

  it('renders the shared EmptyState for an empty outbox and inbox', async () => {
    // EmptyState and Skeleton shipped tested and styled but nothing rendered
    // them — every card had its own ad-hoc "no data" div. Adopted 2026-07-31.
    render(<OpsHealthPanel authFetch={makeFetch({ ok: true })} />)
    await waitFor(() => expect(screen.getByTestId('outbox-empty')).toBeInTheDocument())
    expect(screen.getByTestId('inbox-empty')).toBeInTheDocument()
    // The wording the owner reads must survive the swap.
    expect(screen.getByText(/Outbox is empty/i)).toBeInTheDocument()
    expect(screen.getByText(/Every row the cloud sent has been applied here/i)).toBeInTheDocument()
  })

  it('reports how old the data is', async () => {
    render(<OpsHealthPanel authFetch={makeFetch({ ok: true })} />)
    // A number on screen is only meaningful if the reader can tell its age.
    await waitFor(() => expect(screen.getByText(/Live · /)).toBeInTheDocument())
  })
})
