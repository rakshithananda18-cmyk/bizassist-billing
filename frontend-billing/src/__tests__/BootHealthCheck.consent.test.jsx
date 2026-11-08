import React from 'react'
import { fireEvent, render, screen, cleanup } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
vi.unmock('../utils/telemetry')
vi.mock('../config', () => ({ API_BASE: 'https://staterbill-api-1076771386585.asia-south1.run.app', CLOUD_URL: 'https://staterbill-api-1076771386585.asia-south1.run.app', IS_LOCAL_APP: false }))
import BootHealthCheck from '../components/BootHealthCheck'
import { diagnosticsAllowed, saveStorageConsent } from '../utils/storageConsent'

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('sends an explicitly requested system check without opting into automatic diagnostics', () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }))
  saveStorageConsent(false)
  render(<BootHealthCheck auto={false} />)
  fireEvent.click(screen.getByRole('button', { name: 'Send diagnostics' }))
  expect(fetch).toHaveBeenCalledOnce()
  const body = JSON.parse(fetch.mock.calls[0][1].body)
  expect(body.events[0].payload.reason).toBe('boot_health_check')
  expect(body.device_id).toMatch(/^web-oneoff-/)
  expect(localStorage.getItem('web_device_id')).toBeNull()
  expect(diagnosticsAllowed()).toBe(false)
  expect(screen.getByRole('button', { name: 'Diagnostics queued ✓' })).toBeDisabled()
})
