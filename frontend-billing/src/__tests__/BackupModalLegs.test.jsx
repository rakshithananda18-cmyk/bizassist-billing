// The two-leg sync: what it runs, in what order, and what it says when the
// second leg dies half way.
//
// The partial-failure case is the whole reason this is a render test and not a
// data test. One press now performs two independent, separately-committed
// operations, and the failure a user actually hits — download fine, upload
// refused because the 24h cloud token expired — used to render as a flat "Sync
// failed", which reads as "nothing happened". It did happen. Saying otherwise
// sends the owner looking for data that arrived perfectly well.
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import BackupModal from '../components/hosting/BackupModal'
import { CLOUD_URL, LOCAL_URL } from '../config'

const exportBody = (n) => ({ tables: { customers: Array.from({ length: n }, (_, i) => ({ id: i })) } })
const ok = (body) => ({ ok: true, status: 200, json: async () => body })

/** Record every call so leg ORDER is asserted, not assumed. */
function mockFetch(handlers) {
  const calls = []
  global.fetch = vi.fn(async (url, opts) => {
    calls.push(String(url))
    const res = handlers(String(url), opts, calls.length)
    if (res) return res
    return ok({})            // /health probe
  })
  return calls
}

beforeEach(() => { vi.restoreAllMocks() })
afterEach(() => { delete global.fetch })

describe('two-leg sync', () => {
  it('pulls before it pushes', async () => {
    // Order is deliberate: if the upload dies, the device is already whole. The
    // reverse leaves the owner billing against a device still missing rows.
    const calls = mockFetch((url) => {
      if (url.includes('/export')) return ok(exportBody(3))
      if (url.includes('/import')) return ok({ imported: { customers: 3 }, total: 3 })
      return null
    })

    render(<BackupModal token="t" direction="both" />)
    await waitFor(() => expect(screen.getByText(/Sync complete/i)).toBeTruthy())

    const legs = calls.filter(c => c.includes('/data-transfer/'))
    expect(legs).toHaveLength(4)          // export, import, export, import
    expect(CLOUD_URL).not.toBe(LOCAL_URL) // otherwise the rest proves nothing
    expect(legs[0].startsWith(CLOUD_URL)).toBe(true)   // read cloud
    expect(legs[1].startsWith(LOCAL_URL)).toBe(true)   // write local
    expect(legs[2].startsWith(LOCAL_URL)).toBe(true)   // read local
    expect(legs[3].startsWith(CLOUD_URL)).toBe(true)   // write cloud
  })

  it('re-reads the source for the second leg', async () => {
    // Leg 1 mutates the local DB. If leg 2 uploaded a snapshot taken before
    // that, everything just downloaded would be missing from what it sends.
    let exports = 0
    mockFetch((url) => {
      if (url.includes('/export')) { exports += 1; return ok(exportBody(1)) }
      if (url.includes('/import')) return ok({ imported: {}, total: 0 })
      return null
    })

    render(<BackupModal token="t" direction="both" />)
    await waitFor(() => expect(screen.getByText(/Sync complete/i)).toBeTruthy())
    expect(exports).toBe(2)
  })

  it('keeps the first leg when the second fails', async () => {
    mockFetch((url, _opts, n) => {
      if (url.includes('/export')) return ok(exportBody(4))
      if (url.includes('/import')) {
        // n=2 is leg 1's import (succeeds); n=4 is leg 2's (refused).
        if (n === 2) return ok({ imported: { customers: 4 }, total: 4 })
        return { ok: false, status: 401, json: async () => ({}) }
      }
      return null
    })

    render(<BackupModal token="t" direction="both" />)
    await waitFor(() => expect(screen.getByText(/Sync stopped/i)).toBeTruthy())

    // The download landed and the copy has to say so.
    expect(screen.getByText(/brought down 4 records/i)).toBeTruthy()
    expect(screen.getByText(/that part is saved/i)).toBeTruthy()
  })

  it('runs one leg when a caller asks for one', async () => {
    // The mode-switch and nudge callers pass an explicit direction; collapsing
    // the Settings buttons must not force both legs on them.
    const calls = mockFetch((url) => {
      if (url.includes('/export')) return ok(exportBody(2))
      if (url.includes('/import')) return ok({ imported: {}, total: 0 })
      return null
    })

    render(<BackupModal token="t" direction="cloud-to-local" />)
    await waitFor(() => expect(screen.getByText(/Sync complete/i)).toBeTruthy())
    expect(calls.filter(c => c.includes('/data-transfer/'))).toHaveLength(2)
  })

  it('never asks for the retired merge mode', async () => {
    // `?merge=true` is read by nobody (the LWW branch needs remap_ids=false,
    // which 422s). Sending it advertised a behaviour that never ran.
    const calls = mockFetch((url) => {
      if (url.includes('/export')) return ok(exportBody(1))
      if (url.includes('/import')) return ok({ imported: {}, total: 0 })
      return null
    })

    render(<BackupModal token="t" direction="both" />)
    await waitFor(() => expect(screen.getByText(/Sync complete/i)).toBeTruthy())
    for (const c of calls.filter(c => c.includes('/import'))) {
      expect(c).not.toMatch(/merge=/)
      expect(c).toMatch(/remap_ids=true/)
    }
  })

  it('does not re-upload what leg 1 just brought down', async () => {
    // Leg 2 writes into the database leg 1 read, so leg 1's rows are already
    // there and the far end would only skip them. Sending them anyway cost a
    // second full tenant — 32.6 MB on the load-test business.
    const cloudRows = [{ uid: 'a' }, { uid: 'b' }, { uid: 'c' }]
    const bodies = []
    mockFetch((url, opts) => {
      if (url.includes('/export')) {
        // Leg 2 reads the local DB *after* leg 1 landed: the cloud's three rows
        // plus one that only ever existed on this device.
        return ok(url.startsWith(CLOUD_URL)
          ? { tables: { customers: cloudRows } }
          : { tables: { customers: [...cloudRows, { uid: 'local-only' }] } })
      }
      if (url.includes('/import')) {
        bodies.push(JSON.parse(opts.body))
        return ok({ imported: {}, total: 0 })
      }
      return null
    })

    render(<BackupModal token="t" direction="both" />)
    await waitFor(() => expect(screen.getByText(/Sync complete/i)).toBeTruthy())

    expect(bodies[0].tables.customers).toHaveLength(3)              // leg 1: unfiltered
    expect(bodies[1].tables.customers.map(r => r.uid)).toEqual(['local-only'])
  })

  it('still uploads an old row the cloud never got', async () => {
    // The self-healing property a `since` filter would have destroyed: this row
    // predates every sync stamp, and it is exactly the row that must travel.
    const bodies = []
    mockFetch((url, opts) => {
      if (url.includes('/export')) {
        return ok(url.startsWith(CLOUD_URL)
          ? { tables: { customers: [{ uid: 'shared' }] } }
          : { tables: { customers: [{ uid: 'shared' }, { uid: 'stranded-2019' }] } })
      }
      if (url.includes('/import')) {
        bodies.push(JSON.parse(opts.body))
        return ok({ imported: { customers: 1 }, total: 1 })
      }
      return null
    })

    render(<BackupModal token="t" direction="both" />)
    await waitFor(() => expect(screen.getByText(/Sync complete/i)).toBeTruthy())
    expect(bodies[1].tables.customers.map(r => r.uid)).toContain('stranded-2019')
  })

  it('keeps rows that carry no uid', async () => {
    // `users` has no uid — it identifies by public_id. With no key that is safe
    // to match on, the only correct move is to send the row.
    const bodies = []
    mockFetch((url, opts) => {
      if (url.includes('/export')) return ok({ tables: { users: [{ id: 1, username: 'owner' }] } })
      if (url.includes('/import')) {
        bodies.push(JSON.parse(opts.body))
        return ok({ imported: {}, total: 0 })
      }
      return null
    })

    render(<BackupModal token="t" direction="both" />)
    await waitFor(() => expect(screen.getByText(/Sync complete/i)).toBeTruthy())
    expect(bodies[1].tables.users).toHaveLength(1)
  })

  it('says nothing was missing rather than claiming work', async () => {
    mockFetch((url) => {
      if (url.includes('/export')) return ok(exportBody(9))
      if (url.includes('/import')) return ok({ imported: {}, total: 0 })
      return null
    })

    render(<BackupModal token="t" direction="both" />)
    await waitFor(() => expect(screen.getByText(/Sync complete/i)).toBeTruthy())
    expect(screen.getByText(/nothing to add/i)).toBeTruthy()
  })
})
