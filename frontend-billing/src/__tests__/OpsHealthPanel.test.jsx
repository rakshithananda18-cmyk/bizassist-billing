// OpsHealthPanel: owner-facing data-health view that surfaces the ops-health
// and sync-conflicts endpoints, and lets the owner clear a reviewed conflict.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, waitFor, fireEvent } from '@testing-library/react'
import React from 'react'

import OpsHealthPanel from '../components/settings/OpsHealthPanel'

function makeFetch({ ok = true, conflicts = [] } = {}) {
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
    return { ok: false, json: async () => ({}) }
  })
}

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
