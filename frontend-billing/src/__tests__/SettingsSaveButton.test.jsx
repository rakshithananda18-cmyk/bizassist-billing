import React from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import SettingsSaveButton from '../components/settings/SettingsSaveButton'

afterEach(cleanup)

describe('Settings save control', () => {
  it.each([
    ['saved', 'Saved', false],
    ['saving', 'Saving…', true],
    ['unsaved', 'Save Changes', false],
    ['error', 'Retry Save', false],
  ])('integrates %s status into its single save button', (saveStatus, label, disabled) => {
    const save = vi.fn()
    render(<SettingsSaveButton saveStatus={saveStatus} saving={false} onSave={save} />)
    const button = screen.getByRole('button', { name: label })
    expect(screen.getAllByRole('button')).toHaveLength(1)
    expect(button.disabled).toBe(disabled)
    expect(button).toHaveAttribute('aria-busy', String(disabled))
    fireEvent.click(button)
    expect(save).toHaveBeenCalledTimes(disabled ? 0 : 1)
  })

  it('keeps retry disabled while an explicit save is starting', () => {
    render(<SettingsSaveButton saveStatus="error" saving onSave={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Saving…' })).toBeDisabled()
  })
})
