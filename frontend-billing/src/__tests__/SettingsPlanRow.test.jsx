// The plan had no display anywhere in the app — it only gated features — and
// the one control that could force a re-check ("Refresh Plan Status") rendered
// only when sync was ON and the plan was free. A local install therefore had no
// way to ask, so a Pro grant made on the admin portal simply never turned up.
//
// `force` is the point of this test: without ?force=true the backend's
// 30-minute cooldown skips the cloud call entirely.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Settings from '../pages/Settings'

let settings
let fetchSettings

vi.mock('../layouts/AppLayout', () => ({
  default: ({ children }) => <div>{children}</div>,
}))
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({
    authFetch: vi.fn(async () => ({ ok: true, status: 200, json: async () => settings })),
    user: { id: 1, role: 'owner' },
    token: 'tok',
    fetchSettings,
    switchMode: vi.fn(),
    setHostingMode: vi.fn(),
    networkMode: 'local',
  }),
  useBusinessConfig: () => ({ config: {}, refreshConfig: vi.fn() }),
}))
vi.mock('../contexts/ConfirmContext', () => ({ useConfirm: () => async () => true }))
vi.mock('../contexts/LockContext', () => ({
  useLock: () => ({ hasLock: false, setupPasscode: vi.fn(), clearPasscode: vi.fn() }),
}))

beforeEach(() => {
  fetchSettings = vi.fn(async () => {})
  settings = { general: {}, subscription: { plan: 'free', status: 'none' } }
  localStorage.clear()
})

const renderSettings = () => render(<MemoryRouter><Settings /></MemoryRouter>)

describe('Settings subscription row', () => {
  it('shows the current plan', async () => {
    expect((await renderSettings(), await screen.findByText(/Current plan: Free/))).toBeInTheDocument()
  })

  it('shows Pro when the plan is pro', async () => {
    settings = { general: {}, subscription: { plan: 'pro', status: 'active' } }
    renderSettings()
    expect(await screen.findByText(/Current plan: Pro/)).toBeInTheDocument()
  })

  it('forces the cloud re-check, bypassing the cooldown', async () => {
    renderSettings()
    fireEvent.click(await screen.findByRole('button', { name: /check for updates/i }))
    await waitFor(() => expect(fetchSettings).toHaveBeenCalledWith(true))
  })
})
