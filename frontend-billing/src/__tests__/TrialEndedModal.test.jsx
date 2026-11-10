// The web screen for a lapsed signup trial. Its whole job is that a web-only
// owner can still take their data out — so the backup download has to work,
// hit the export endpoint (never plan-gated), and the desktop link has to be
// the real download page.
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'

vi.mock('../config', async (importOriginal) => ({ ...(await importOriginal()), API_BASE: 'https://cloud.test' }))

import TrialEndedModal from '../components/layout/TrialEndedModal'
import { DESKTOP_DOWNLOAD_URL } from '../config/downloadApp'

const props = (over = {}) => ({
  isOwner: true, token: 'tok', bizId: 'BA-123456',
  onSignOut: vi.fn(), onCheckPlan: vi.fn(), onDismiss: vi.fn(), ...over,
})

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ tables: {} }) })))
  URL.createObjectURL = vi.fn(() => 'blob:backup')
  URL.revokeObjectURL = vi.fn()
  HTMLAnchorElement.prototype.click = vi.fn()   // jsdom cannot navigate to a blob
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('TrialEndedModal', () => {
  it('lets the owner download a backup file from the export endpoint', async () => {
    render(<TrialEndedModal {...props()} />)
    fireEvent.click(screen.getByRole('button', { name: /download backup file/i }))
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/Saved as bizassist-backup-ba-123456-/))
    expect(fetch).toHaveBeenCalledWith('https://cloud.test/api/data-transfer/export',
      { headers: { Authorization: 'Bearer tok' } })
  })

  it('says so when the backup fails, instead of pretending', async () => {
    fetch.mockImplementation(async () => ({ ok: false, status: 500 }))
    render(<TrialEndedModal {...props()} />)
    fireEvent.click(screen.getByRole('button', { name: /download backup file/i }))
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/HTTP 500/))
  })

  it('links to the real desktop download page', () => {
    render(<TrialEndedModal {...props()} />)
    expect(screen.getByRole('link', { name: /download the desktop app/i }).getAttribute('href'))
      .toBe(DESKTOP_DOWNLOAD_URL)
  })

  it('sends staff to the owner, without a download they cannot make', () => {
    render(<TrialEndedModal {...props({ isOwner: false })} />)
    expect(screen.queryByRole('button', { name: /download backup file/i })).toBeNull()
    expect(screen.getByText(/Ask the business owner/)).toBeTruthy()
  })

  it('offers "look around" only while the preview lasts', () => {
    const p = props()
    const { rerender } = render(<TrialEndedModal {...p} />)
    fireEvent.click(screen.getByRole('button', { name: /look around first/i }))
    expect(p.onDismiss).toHaveBeenCalled()

    rerender(<TrialEndedModal {...p} onDismiss={null} />)
    expect(screen.queryByRole('button', { name: /look around first/i })).toBeNull()
  })

  it('re-checks the plan on request', () => {
    const p = props()
    render(<TrialEndedModal {...p} />)
    fireEvent.click(screen.getByRole('button', { name: /check my plan again/i }))
    expect(p.onCheckPlan).toHaveBeenCalled()
  })
})
