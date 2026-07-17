import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import React from 'react'
import ReadinessPanel from '../components/hosting/ReadinessPanel'
import PreflightModal from '../components/hosting/PreflightModal'
import ConsequenceModal from '../components/hosting/ConsequenceModal'
import MigrationModal from '../components/hosting/MigrationModal'

afterEach(cleanup)

describe('ReadinessPanel', () => {
  it('renders all probe statuses and allows manual recheck', () => {
    const onRecheck = vi.fn()
    render(
      <ReadinessPanel
        localProbe={{ status: 'online', ms: 15, error: null }}
        cloudProbe={{ status: 'online', ms: 120, error: null }}
        internetProbe={{ status: 'online', ms: 85, error: null }}
        onRecheck={onRecheck}
      />
    )

    expect(screen.getByText('Local Backend')).toBeInTheDocument()
    expect(screen.getByText('Cloud Backend')).toBeInTheDocument()
    expect(screen.getByText('Internet')).toBeInTheDocument()

    // Online labels with ms should be displayed
    expect(screen.getByText('Online (15ms)')).toBeInTheDocument()
    expect(screen.getByText('Online (120ms)')).toBeInTheDocument()
    expect(screen.getByText('Online (85ms)')).toBeInTheDocument()

    // Clicking recheck calls onRecheck
    const recheckBtn = screen.getByText(/Recheck/i)
    fireEvent.click(recheckBtn)
    expect(onRecheck).toHaveBeenCalledTimes(1)
  })

  it('renders offline/checking/cors states correctly', () => {
    render(
      <ReadinessPanel
        localProbe={{ status: 'checking', ms: null, error: null }}
        cloudProbe={{ status: 'offline', ms: null, error: 'Timeout' }}
        internetProbe={{ status: 'cors', ms: null, error: 'CORS Blocked' }}
        onRecheck={() => {}}
      />
    )
    expect(screen.getByText('Checking…')).toBeInTheDocument()
    expect(screen.getByText('Offline')).toBeInTheDocument()
    expect(screen.getByText('Blocked (CORS)')).toBeInTheDocument()
  })
})

describe('PreflightModal', () => {
  it('renders required probes for target mode and handles cancel/proceed', () => {
    const onClose = vi.fn()
    const onProceed = vi.fn()
    
    // Test for Hybrid target mode (which needs local, cloud, internet)
    render(
      <PreflightModal
        targetMode="hybrid"
        localProbe={{ status: 'online', ms: 10, error: null }}
        cloudProbe={{ status: 'online', ms: 100, error: null }}
        internetProbe={{ status: 'online', ms: 50, error: null }}
        onClose={onClose}
        onProceed={onProceed}
      />
    )

    expect(screen.getByText(/Switch to Local \+ Cloud/i)).toBeInTheDocument()
    expect(screen.getByText('Local Backend (P1)')).toBeInTheDocument()
    expect(screen.getByText('Cloud Backend (P2)')).toBeInTheDocument()
    expect(screen.getByText('Internet Access (P3)')).toBeInTheDocument()

    // Since all are online, the proceed button should be active and say "Continue →"
    const proceedBtn = screen.getByRole('button', { name: /Continue →/i })
    expect(proceedBtn).toBeEnabled()
    fireEvent.click(proceedBtn)
    expect(onProceed).toHaveBeenCalledTimes(1)

    // Backdrop click when not checking calls onClose
    const backdrop = screen.getByText(/Switch to Local \+ Cloud/i).closest('.pf-backdrop')
    fireEvent.mouseDown(backdrop)
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})

describe('ConsequenceModal', () => {
  it('renders transition warnings and buttons', () => {
    const onCancel = vi.fn()
    const onConfirm = vi.fn()

    render(
      <ConsequenceModal
        fromMode="local"
        toMode="cloud"
        onCancel={onCancel}
        onConfirm={onConfirm}
      />
    )

    expect(screen.getByText(/Move to Cloud Mode/i)).toBeInTheDocument()
    expect(screen.getByText(/Internet connection will be required/i)).toBeInTheDocument()
    expect(screen.getByText(/Upload all local data/i)).toBeInTheDocument()

    const confirmBtn = screen.getByRole('button', { name: /Move to Cloud/i })
    fireEvent.click(confirmBtn)
    expect(onConfirm).toHaveBeenCalledTimes(1)

    const cancelBtn = screen.getByRole('button', { name: /Cancel/i })
    fireEvent.click(cancelBtn)
    expect(onCancel).toHaveBeenCalledTimes(1)
  })
})

describe('MigrationModal', () => {
  beforeEach(() => {
    // Cloud legs authenticate with a CLOUD-issued token (local JWTs 401 on the
    // cloud); the modal fails fast in step 0 if it's absent.
    localStorage.setItem('bizassist_cloud_token', 'cloud-test-token')
  })
  afterEach(() => {
    localStorage.removeItem('bizassist_cloud_token')
    vi.unstubAllGlobals()
  })

  it('runs through the migration steps successfully', async () => {
    const mockFetch = vi.fn().mockImplementation(async (url) => {
      if (url.endsWith('/api/data-transfer/count')) {
        return {
          ok: true,
          json: async () => ({ users: 1, customers: 3 })
        }
      }
      if (url.endsWith('/api/data-transfer/export')) {
        return {
          ok: true,
          json: async () => ({
            tables: { users: [{ id: 1 }], customers: [{ id: 1 }, { id: 2 }] },
            backup_path: '/backups/backup.db'
          })
        }
      }
      // import is now called with ?remap_ids=true (collision-safe mode)
      if (url.includes('/api/data-transfer/import')) {
        return {
          ok: true,
          json: async () => ({
            imported: { users: 1, customers: 2 },
            total: 3
          })
        }
      }
      if (url.endsWith('/settings')) {
        return { ok: true, json: async () => ({}) }
      }
      return { ok: false, status: 404 }
    })

    vi.stubGlobal('fetch', mockFetch)

    const onComplete = vi.fn()
    const onError = vi.fn()

    render(
      <MigrationModal
        fromMode="local"
        toMode="cloud"
        token="test-token"
        onComplete={onComplete}
        onError={onError}
      />
    )

    // Wait for step 0 (Verify) and step 1 (Count) to run
    await waitFor(() => {
      expect(screen.getByText('Verifying credentials & permissions')).toBeInTheDocument()
    })

    // Success no longer auto-fires onComplete — the user reads the summary and
    // explicitly continues (the mode switch signs them out, so it must be a choice).
    await waitFor(() => {
      expect(screen.getByText(/Sign out & continue/i)).toBeInTheDocument()
    }, { timeout: 4500 })
    expect(onComplete).not.toHaveBeenCalled()

    fireEvent.click(screen.getByText(/Sign out & continue/i))
    expect(onComplete).toHaveBeenCalled()
    expect(onError).not.toHaveBeenCalled()
  })

  it('handles export failure gracefully and calls onError', async () => {
    const mockFetch = vi.fn().mockImplementation(async (url) => {
      if (url.endsWith('/api/data-transfer/count')) {
        return { ok: true, json: async () => ({}) }
      }
      if (url.endsWith('/api/data-transfer/export')) {
        return { ok: false, status: 500 }
      }
      return { ok: false, status: 404 }
    })
    
    vi.stubGlobal('fetch', mockFetch)

    const onComplete = vi.fn()
    const onError = vi.fn()

    render(
      <MigrationModal
        fromMode="local"
        toMode="cloud"
        token="test-token"
        onComplete={onComplete}
        onError={onError}
      />
    )

    // Wait for the migration to fail — the modal STAYS OPEN showing the error
    // (unmounting on failure made the switch look like a silent no-op).
    await waitFor(() => {
      expect(screen.getByText(/Migration Failed/i)).toBeInTheDocument()
    }, { timeout: 4500 })

    expect(screen.getByText(/Export failed: HTTP 500/i)).toBeInTheDocument()
    expect(onComplete).not.toHaveBeenCalled()
    expect(onError).not.toHaveBeenCalled()   // parent must not unmount the error screen

    // Explicit close is what hands control back to the parent.
    fireEvent.click(screen.getByRole('button', { name: /Cancel/i }))
    expect(onError).toHaveBeenCalled()
  })

  it('fails fast with a fix when the cloud leg has no cloud session token', async () => {
    localStorage.removeItem('bizassist_cloud_token')
    vi.stubGlobal('fetch', vi.fn())   // must not be reached

    render(
      <MigrationModal
        fromMode="local"
        toMode="cloud"
        token="test-token"
        onComplete={vi.fn()}
        onError={vi.fn()}
      />
    )

    await waitFor(() => {
      expect(screen.getByText(/Migration Failed/i)).toBeInTheDocument()
    }, { timeout: 4500 })
    expect(screen.getByText(/No cloud session found/i)).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })
})
