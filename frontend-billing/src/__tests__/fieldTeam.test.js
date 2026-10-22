// fieldTeam.js — the sidebar's "Field Team" link. Hidden until configured; the
// sign-in hand-off must survive pop-up blockers and a failed ticket.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const { post } = vi.hoisted(() => ({ post: vi.fn() }))
vi.mock('../api/client', () => ({ default: { post } }))

import { getFieldTeamUrl, openFieldTeam } from '../config/fieldTeam'

const URL_ = 'https://field.example.app'
const fakeTab = () => ({ location: { href: '' }, focus: vi.fn() })

describe('Field Team link', () => {
  beforeEach(() => { post.mockReset() })
  afterEach(() => { vi.unstubAllEnvs(); vi.restoreAllMocks() })

  it('is hidden until VITE_FIELD_TEAM_URL is set, and ignores a trailing slash', () => {
    vi.stubEnv('VITE_FIELD_TEAM_URL', '')
    expect(getFieldTeamUrl()).toBeNull()
    vi.stubEnv('VITE_FIELD_TEAM_URL', `${URL_}/`)
    expect(getFieldTeamUrl()).toBe(URL_)
  })

  it('opens the tab inside the click, then signs in with the ticket as ?sso=', async () => {
    vi.stubEnv('VITE_FIELD_TEAM_URL', URL_)
    const tab = fakeTab()
    const open = vi.spyOn(window, 'open').mockReturnValue(tab)
    let deliver
    post.mockReturnValue(new Promise((resolve) => { deliver = resolve }))

    const done = openFieldTeam()
    // Before the ticket request settles — i.e. still inside the user's click.
    expect(open).toHaveBeenCalledWith('', 'field_team')
    expect(tab.location.href).toBe('')

    deliver({ ticket: '1761140000.eyJpZCI6MX0.ab12' })
    await done
    expect(post).toHaveBeenCalledWith('/handoff-ticket')
    expect(tab.location.href).toBe(`${URL_}/?sso=1761140000.eyJpZCI6MX0.ab12`)
    expect(tab.focus).toHaveBeenCalled()
  })

  it('still opens Field Team, at its sign-in page, when no ticket can be had', async () => {
    vi.stubEnv('VITE_FIELD_TEAM_URL', URL_)
    const tab = fakeTab()
    vi.spyOn(window, 'open').mockReturnValue(tab)
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    post.mockRejectedValue(new Error('offline'))

    await openFieldTeam()
    expect(tab.location.href).toBe(`${URL_}/`)
  })

  it('asks for no ticket when the pop-up was blocked or the link is not configured', async () => {
    vi.stubEnv('VITE_FIELD_TEAM_URL', URL_)
    vi.spyOn(window, 'open').mockReturnValue(null)
    await openFieldTeam()

    vi.stubEnv('VITE_FIELD_TEAM_URL', '')
    await openFieldTeam()
    expect(post).not.toHaveBeenCalled()
  })
})
