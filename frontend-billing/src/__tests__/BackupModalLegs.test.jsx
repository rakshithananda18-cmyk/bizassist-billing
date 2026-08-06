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
