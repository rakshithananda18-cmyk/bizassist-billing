import React from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import FileBackupCard from '../components/hosting/FileBackupCard'

const confirmRestore = vi.hoisted(() => vi.fn())
vi.mock('../config', () => ({ API_BASE: 'http://backup.test' }))
vi.mock('../contexts/ConfirmContext', () => ({ useConfirm: () => confirmRestore }))
vi.mock('../utils/logger', () => ({ logger: { error: vi.fn() } }))

const LAST_BACKUP_KEY = 'bizassist_last_file_backup'
const PREVIOUS_BACKUP = '2026-10-20T08:30:00.000Z'
const validBackup = {
  exported_at: '2026-10-19T10:00:00.000Z',
  business_id: 42,
  tables: { products: [{ id: 7, name: 'Soap' }], invoices: [] },
}

function backupFile(contents = JSON.stringify(validBackup)) {
  const file = new File([contents], 'business-backup.json', { type: 'application/json' })
  // jsdom File does not implement Blob.text(). Keep the real file-selection
  // event, and supply only that missing browser method.
  Object.defineProperty(file, 'text', { value: vi.fn().mockResolvedValue(contents) })
  return file
}

function selectBackup(container, file) {
  fireEvent.change(container.querySelector('input[type="file"]'), { target: { files: [file] } })
}

beforeEach(() => {
  confirmRestore.mockReset().mockResolvedValue(true)
  // Every request is isolated; an unexpected fetch can never reach a backend.
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Unexpected backup request')))
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('FileBackupCard', () => {
  it('reports a partially committed restore without claiming completion', async () => {
    fetch.mockResolvedValue({ ok: true, json: async () => ({ total: 2, complete: false,
      b2b_skipped: [{ reason: 'missing party' }] }) })
    const { container } = render(<FileBackupCard token="test-token" />)
    selectBackup(container, backupFile())
    await waitFor(() => expect(screen.getByText(/Import incomplete:/i)).toBeInTheDocument())
    expect(screen.queryByText(/Restore complete/i)).not.toBeInTheDocument()
  })
  it('keeps file recovery available without rendering an unusable reminder toggle', () => {
    render(<FileBackupCard token="test-token" />)

    expect(screen.getByRole('button', { name: 'Download backup file' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Restore from file' })).toBeEnabled()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })

  it('also hides the toggle when only a saved reminder value is supplied', () => {
    render(<FileBackupCard token="test-token" autoBackup />)

    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })

  it('passes the updated reminder preference to its supplied callback', () => {
    const onAutoBackupChange = vi.fn()
    render(<FileBackupCard token="test-token" autoBackup={false} onAutoBackupChange={onAutoBackupChange} />)

    fireEvent.click(screen.getByRole('checkbox'))
    expect(onAutoBackupChange).toHaveBeenCalledTimes(1)
    expect(onAutoBackupChange).toHaveBeenCalledWith(true)
  })

  it.each([
    ['invalid JSON', '{broken'],
    ['null', 'null'],
    ['an unrelated object', '{"settings":{}}'],
    ['an array of tables', '{"tables":[]}'],
    ['a table that is not a row list', '{"tables":{"products":{}}}'],
    ['a row that is not an object', '{"tables":{"products":[null]}}'],
  ])('rejects %s before requesting an import', async (_label, contents) => {
    const { container } = render(<FileBackupCard token="test-token" />)
    selectBackup(container, backupFile(contents))

    expect(await screen.findByText(/not a valid BizAssist backup/)).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Restore from file' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: 'Reload restored data' })).not.toBeInTheDocument()
    expect(localStorage.getItem(LAST_BACKUP_KEY)).toBeNull()
  })

  it('does not read or import the file when the owner cancels', async () => {
    confirmRestore.mockResolvedValue(false)
    const file = backupFile()
    const { container } = render(<FileBackupCard token="test-token" />)
    selectBackup(container, file)

    await waitFor(() => expect(confirmRestore).toHaveBeenCalledWith(expect.objectContaining({
      title: 'Restore backup?', entity: file.name, confirmText: 'Restore',
    })))
    expect(file.text).not.toHaveBeenCalled()
    expect(fetch).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Restore from file' })).toBeEnabled()
  })

  it('imports the selected backup and offers a reload without overwriting the export timestamp', async () => {
    localStorage.setItem(LAST_BACKUP_KEY, PREVIOUS_BACKUP)
    let finishImport
    fetch.mockImplementationOnce(() => new Promise(resolve => { finishImport = resolve }))
    const { container } = render(<FileBackupCard token="test-token" />)
    selectBackup(container, backupFile())

    await waitFor(() => expect(screen.getByRole('button', { name: 'Restoring…' })).toBeDisabled())
    expect(screen.getByRole('button', { name: 'Download backup file' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Reload restored data' })).not.toBeInTheDocument()
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(fetch).toHaveBeenCalledWith(
      'http://backup.test/api/data-transfer/import?remap_ids=true',
      {
        method: 'POST',
        headers: { Authorization: 'Bearer test-token', 'Content-Type': 'application/json' },
        body: JSON.stringify(validBackup),
      },
    )

    await act(async () => finishImport({ ok: true, json: async () => ({ message: '3 records restored.' }) }))
    expect(await screen.findByText(/3 records restored\./)).toBeInTheDocument()
    expect(localStorage.getItem(LAST_BACKUP_KEY)).toBe(PREVIOUS_BACKUP)
    expect(screen.getByRole('button', { name: 'Restore from file' })).toBeEnabled()

    const reload = vi.fn()
    // jsdom cannot navigate. Replace only the location read used by the click
    // handler, while forwarding the rest of the window to the actual DOM.
    vi.stubGlobal('window', new Proxy(window, {
      get: (target, key) => key === 'location' ? { reload } : Reflect.get(target, key),
    }))
    fireEvent.click(screen.getByRole('button', { name: 'Reload restored data' }))
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it.each([
    ['legacy tables-only export', { tables: { products: [{ id: 7 }] } }],
    ['empty-business export', { tables: {} }],
  ])('accepts a %s without requiring newer export metadata', async (_label, payload) => {
    fetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) })
    const { container } = render(<FileBackupCard token="test-token" />)
    selectBackup(container, backupFile(JSON.stringify(payload)))

    expect(await screen.findByText(/Restore complete/)).toBeInTheDocument()
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual(payload)
    expect(screen.getByRole('button', { name: 'Reload restored data' })).toBeEnabled()
    expect(localStorage.getItem(LAST_BACKUP_KEY)).toBeNull()
  })

  it('keeps a failed restore visible and allows retrying the same file', async () => {
    localStorage.setItem(LAST_BACKUP_KEY, PREVIOUS_BACKUP)
    fetch
      .mockResolvedValueOnce({ ok: false, status: 409, json: async () => ({ detail: 'Restore blocked: invoice conflict.' }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ message: 'Retry restored the backup.' }) })
    const file = backupFile()
    const { container } = render(<FileBackupCard token="test-token" />)
    selectBackup(container, file)

    expect(await screen.findByText('Restore blocked: invoice conflict.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Restore from file' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Download backup file' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: 'Reload restored data' })).not.toBeInTheDocument()
    expect(localStorage.getItem(LAST_BACKUP_KEY)).toBe(PREVIOUS_BACKUP)

    selectBackup(container, file)
    expect(await screen.findByText(/Retry restored the backup\./)).toBeInTheDocument()
    expect(screen.queryByText('Restore blocked: invoice conflict.')).not.toBeInTheDocument()
    expect(file.text).toHaveBeenCalledTimes(2)
    expect(fetch).toHaveBeenCalledTimes(2)
    expect(confirmRestore).toHaveBeenCalledTimes(2)
    expect(localStorage.getItem(LAST_BACKUP_KEY)).toBe(PREVIOUS_BACKUP)
  })

  it('records the backup time only after a successful file export', async () => {
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    fetch.mockResolvedValueOnce({ ok: true, json: async () => validBackup })
    const before = Date.now()
    render(<FileBackupCard token="test-token" bizId="BA-DEMO" />)
    fireEvent.click(screen.getByRole('button', { name: 'Download backup file' }))

    expect(await screen.findByText(/Backup saved as bizassist-backup-ba-demo-/)).toBeInTheDocument()
    const stamp = localStorage.getItem(LAST_BACKUP_KEY)
    expect(Date.parse(stamp)).toBeGreaterThanOrEqual(before)
    expect(Date.parse(stamp)).toBeLessThanOrEqual(Date.now())
    expect(screen.getByText(/Last file backup:/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reload restored data' })).not.toBeInTheDocument()
  })

  it('does not replace the last successful backup timestamp when an export fails', async () => {
    localStorage.setItem(LAST_BACKUP_KEY, PREVIOUS_BACKUP)
    fetch.mockResolvedValueOnce({ ok: false, status: 503 })
    render(<FileBackupCard token="test-token" />)
    fireEvent.click(screen.getByRole('button', { name: 'Download backup file' }))

    expect(await screen.findByText('Export failed: HTTP 503')).toBeInTheDocument()
    expect(localStorage.getItem(LAST_BACKUP_KEY)).toBe(PREVIOUS_BACKUP)
    expect(screen.getByRole('button', { name: 'Download backup file' })).toBeEnabled()
  })

  it('does not display an unreadable stored backup timestamp as a valid backup', () => {
    localStorage.setItem(LAST_BACKUP_KEY, 'not-a-date')
    render(<FileBackupCard token="test-token" />)

    expect(screen.queryByText(/Last file backup:/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Invalid Date/)).not.toBeInTheDocument()
  })
})
