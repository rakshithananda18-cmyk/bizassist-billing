import React from 'react'
import { act, cleanup, render } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import GuidedTour from '../demo/GuidedTour'

vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 999999, is_demo: true }, isDemoMode: true }) }))
vi.mock('../demo/demoEngine', () => ({ resetDemoData: vi.fn() }))
vi.mock('../demo/guidedTourRuntime', async importOriginal => ({ ...await importOriginal(), isEmbeddedGuidedTour: () => true }))
vi.mock('../demo/guidedTourSteps', () => ({ guidedTourSteps: [
  { id: 'home', route: '/', steps: [{ target: '[data-testid="home"]', caption: 'Home', click: true, hold: 100 }] },
  { id: 'dashboard', route: '/dashboard', steps: [{ target: '[data-testid="dashboard"]', caption: 'Dashboard', hold: 100 }] },
] }))

afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks() })

it('keeps the playback session running as the actual router navigates between chapters', async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'performance'] })
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({ left: 20, top: 20, right: 120, bottom: 70, width: 100, height: 50 })
  const post = vi.spyOn(window, 'postMessage').mockImplementation(() => {})
  render(<MemoryRouter initialEntries={['/?demo=1&embed=1&tour=1']}>
    <Routes>
      <Route path="/" element={<div data-testid="home">Home</div>} />
      <Route path="/dashboard" element={<div data-testid="dashboard">Dashboard</div>} />
    </Routes>
    <GuidedTour />
  </MemoryRouter>)
  act(() => window.dispatchEvent(new MessageEvent('message', {
    data: { type: 'stater-tour:command', command: 'play' },
    origin: 'http://localhost:5173', source: window,
  })))
  for (let count = 0; count < 30; count++) {
    await act(async () => { await vi.advanceTimersByTimeAsync(250) })
  }
  const states = post.mock.calls.map(([data]) => data).filter(data => data.type === 'stater-tour:state')
  expect(states.some(state => state.chapter === 'home' && state.playing)).toBe(true)
  expect(states.at(-1)).toMatchObject({ chapter: 'dashboard', complete: true, playing: false, progress: 1 })
})

it('waits for a covering register dialog to close before clicking a pending target', async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'performance'] })
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({ left: 20, top: 20, right: 120, bottom: 70, width: 100, height: 50 })
  vi.spyOn(window, 'postMessage').mockImplementation(() => {})
  const click = vi.fn()
  const blocker = document.createElement('div')
  blocker.className = 'modal-overlay'
  blocker.textContent = 'Open Register Shift'
  document.body.appendChild(blocker)
  try {
    render(<MemoryRouter initialEntries={['/?demo=1&embed=1&tour=1']}>
      <Routes>
        <Route path="/" element={<button data-testid="home" onClick={click}>Billing</button>} />
        <Route path="/dashboard" element={<div data-testid="dashboard">Dashboard</div>} />
      </Routes>
      <GuidedTour />
    </MemoryRouter>)
    act(() => window.dispatchEvent(new MessageEvent('message', {
      data: { type: 'stater-tour:command', command: 'play' },
      origin: 'http://localhost:5173', source: window,
    })))
    for (let count = 0; count < 20; count++) await act(async () => { await vi.advanceTimersByTimeAsync(250) })
    expect(click).not.toHaveBeenCalled()
    blocker.remove()
    for (let count = 0; count < 20; count++) await act(async () => { await vi.advanceTimersByTimeAsync(250) })
    expect(click).toHaveBeenCalledOnce()
  } finally { blocker.remove() }
})

it('freezes the single cursor mid-movement when playback pauses', async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'performance'] })
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({ left: 300, top: 200, right: 400, bottom: 250, width: 100, height: 50 })
  vi.spyOn(window, 'postMessage').mockImplementation(() => {})
  render(<MemoryRouter initialEntries={['/?demo=1&embed=1&tour=1']}>
    <Routes>
      <Route path="/" element={<button data-testid="home">Home</button>} />
      <Route path="/dashboard" element={<div data-testid="dashboard">Dashboard</div>} />
    </Routes>
    <GuidedTour />
  </MemoryRouter>)
  const command = value => act(() => window.dispatchEvent(new MessageEvent('message', {
    data: { type: 'stater-tour:command', command: value }, origin: 'http://localhost:5173', source: window,
  })))
  command('play')
  await act(async () => { await vi.advanceTimersByTimeAsync(1300) })
  const cursor = document.querySelector('.guided-tour-cursor')
  expect(cursor).not.toBeNull()
  const stoppedAt = cursor.style.transform
  command('pause')
  await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
  expect(document.querySelectorAll('.guided-tour-cursor')).toHaveLength(1)
  expect(cursor.style.transform).toBe(stoppedAt)
  command('play')
  await act(async () => { await vi.advanceTimersByTimeAsync(400) })
  expect(cursor.style.transform).not.toBe(stoppedAt)
})
