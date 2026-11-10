import React from 'react'
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import StorageConsentNotice from '../components/StorageConsentNotice'
import { diagnosticsAllowed, openStoragePreferences, readStorageConsent, STORAGE_CONSENT_KEY } from '../utils/storageConsent'

const renderNotice = () => render(<MemoryRouter><StorageConsentNotice /></MemoryRouter>)
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('browser storage choices', () => {
  it('describes real storage and keeps optional diagnostics off until chosen', () => {
    renderNotice()
    expect(screen.getByRole('region', { name: /cookies & browser storage/i })).toBeInTheDocument()
    expect(screen.getByText(/we don’t use advertising or tracking cookies/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /privacy & storage details/i })).toHaveAttribute('href', '/privacy')
    expect(diagnosticsAllowed()).toBe(false)
  })

  it('remembers essential-only acceptance without disabling essential storage', () => {
    localStorage.setItem('web_device_id', 'old-diagnostic-id')
    renderNotice()
    fireEvent.click(screen.getByRole('button', { name: 'Essential only' }))
    expect(readStorageConsent()).toMatchObject({ essential: true, diagnostics: false, version: 1 })
    expect(localStorage.getItem('web_device_id')).toBeNull()
    expect(screen.queryByRole('region')).not.toBeInTheDocument()
    cleanup(); renderNotice()
    expect(screen.queryByRole('region')).not.toBeInTheDocument()
  })

  it('allows optional diagnostics and lets the user change that choice later', () => {
    renderNotice()
    fireEvent.click(screen.getByRole('button', { name: 'Accept all' }))
    expect(diagnosticsAllowed()).toBe(true)
    act(() => openStoragePreferences())
    fireEvent.click(screen.getByRole('button', { name: 'Essential only' }))
    expect(diagnosticsAllowed()).toBe(false)
  })

  it('asks again if the stored choice is invalid', () => {
    localStorage.setItem(STORAGE_CONSENT_KEY, '{broken')
    renderNotice()
    expect(screen.getByRole('button', { name: 'Accept all' })).toBeInTheDocument()
  })

  it('remains usable when browser storage is blocked', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
    renderNotice()
    fireEvent.click(screen.getByRole('button', { name: 'Essential only' }))
    expect(screen.queryByRole('region')).not.toBeInTheDocument()
    expect(diagnosticsAllowed()).toBe(false)
  })
})
