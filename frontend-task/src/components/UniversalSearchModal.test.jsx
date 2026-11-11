// @vitest-environment jsdom
import React, { useState } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
const get = vi.hoisted(() => vi.fn())
vi.mock('../lib/api', () => ({ api: { get } }))
import UniversalSearchModal from './UniversalSearchModal'

function Harness() {
  const [open, setOpen] = useState(false)
  return <><button onClick={() => setOpen(true)}>Open search</button><UniversalSearchModal open={open} onClose={() => setOpen(false)} /></>
}
const view = () => render(<MemoryRouter><Routes><Route path="*" element={<Harness />} /></Routes></MemoryRouter>)
beforeEach(() => get.mockReset().mockResolvedValue([]))
afterEach(cleanup)

describe('Workspace search dialog', () => {
  it('traps focus and restores the opener when Escape is pressed from a result', async () => {
    view()
    const opener = screen.getByRole('button', { name: 'Open search' })
    opener.focus()
    fireEvent.click(opener)
    const dialog = screen.getByRole('dialog', { name: 'Search workspaces' })
    const input = within(dialog).getByRole('searchbox', { name: 'Search pages, shops, staff and routes' })
    await waitFor(() => expect(document.activeElement).toBe(input))
    fireEvent.keyDown(input, { key: 'Tab', shiftKey: true })
    const buttons = within(dialog).getAllByRole('button')
    expect(document.activeElement).toBe(buttons[buttons.length - 1])
    fireEvent.keyDown(document.activeElement, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.activeElement).toBe(opener)
  })

  it('discards results from a closed search rather than overwriting the next search', async () => {
    let resolveOld
    const oldShops = new Promise(resolve => { resolveOld = resolve })
    let shopRequests = 0
    get.mockImplementation(path => path === '/api/shops'
      ? (++shopRequests === 1 ? oldShops : Promise.resolve([{ name: 'Current shop' }]))
      : Promise.resolve([]))
    view()
    fireEvent.click(screen.getByRole('button', { name: 'Open search' }))
    fireEvent.click(screen.getByRole('button', { name: 'Close search' }))
    fireEvent.click(screen.getByRole('button', { name: 'Open search' }))
    const input = screen.getByRole('searchbox')
    fireEvent.change(input, { target: { value: 'Current shop' } })
    await screen.findByRole('button', { name: /Current shop/ })
    await act(async () => { resolveOld([{ name: 'Previous private shop' }]); await oldShops })
    expect(screen.getByRole('button', { name: /Current shop/ })).toBeTruthy()
    fireEvent.change(input, { target: { value: 'Previous private shop' } })
    expect(screen.queryByRole('button', { name: /Previous private shop/ })).toBeNull()
  })
})
