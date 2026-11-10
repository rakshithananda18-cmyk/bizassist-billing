import React from 'react'
import { act, cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import GuidedTour from '../demo/GuidedTour'
import ContactsPayments from '../pages/ContactsPayments'
import { useAuth } from '../contexts/AuthContext'

vi.mock('../contexts/AuthContext', async () => {
  const { DEMO_USER, DEMO_SETTINGS, handleDemoRequest } = await import('../demo/demoEngine')
  const authFetch = vi.fn(async (path, options) => handleDemoRequest(path, options))
  return {
    useAuth: () => ({ user: DEMO_USER, settings: DEMO_SETTINGS, authFetch, isDemoMode: true, networkMode: 'cloud' }),
    useBusinessConfig: () => ({ config: {}, attributesSchema: [] }),
  }
})
vi.mock('../contexts/ConfirmContext', () => ({ useConfirm: () => vi.fn().mockResolvedValue(true) }))
vi.mock('../layouts/AppLayout', () => ({ default: ({ children }) => <main>{children}</main> }))
vi.mock('../demo/guidedTourRuntime', async importOriginal => ({ ...await importOriginal(), isEmbeddedGuidedTour: () => true }))
vi.mock('../demo/guidedTourSteps', async importOriginal => {
  const { guidedTourSteps } = await importOriginal()
  return { guidedTourSteps: guidedTourSteps.filter(chapter => chapter.id === 'contacts').map(chapter => ({
    ...chapter, steps: chapter.steps.map(step => ({ ...step, hold: 20 })),
  })) }
})

afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); localStorage.clear() })

it('runs the real Contacts chapter from customer search through the populated credit ledger', async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'performance'] })
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({ left: 20, top: 20, right: 120, bottom: 70, width: 100, height: 50 })
  const post = vi.spyOn(window, 'postMessage').mockImplementation(() => {})
  render(<MemoryRouter initialEntries={['/parties/contacts?demo=1&embed=1&tour=1']}>
    <Routes><Route path="/parties/:tab" element={<ContactsPayments />} /></Routes>
    <GuidedTour />
  </MemoryRouter>)
  await act(async () => {})
  act(() => window.dispatchEvent(new MessageEvent('message', {
    data: { type: 'stater-tour:command', command: 'play' },
    origin: 'http://localhost:5173', source: window,
  })))
  for (let count = 0; count < 80; count++) await act(async () => { await vi.advanceTimersByTimeAsync(250) })
  expect(screen.getByPlaceholderText('Search customers…')).toHaveValue('Ramesh')
  expect(screen.getByText('Chronological Credit & Transaction Ledger')).toBeInTheDocument()
  expect(screen.queryByText('No credit transactions found in this period.')).not.toBeInTheDocument()
  expect(useAuth().authFetch.mock.calls.some(([path]) => path.startsWith('/reports/party-ledger?party_type=customer&party_id=1'))).toBe(true)
  const states = post.mock.calls.map(([data]) => data).filter(data => data.type === 'stater-tour:state')
  expect(states.at(-1)).toMatchObject({ chapter: 'contacts', complete: true, playing: false, error: null })
})
