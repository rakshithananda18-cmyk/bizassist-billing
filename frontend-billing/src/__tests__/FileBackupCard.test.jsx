import React from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import FileBackupCard from '../components/hosting/FileBackupCard'

afterEach(cleanup)

describe('FileBackupCard', () => {
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
})
