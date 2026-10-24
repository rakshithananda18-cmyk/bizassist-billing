// @vitest-environment jsdom
// ^ Uses window.open. vite.config.js sends *.test.js to the `node`
//   environment unless the file asks for a DOM like this.
//
// fieldTeam.js — the sidebar's "Field Team" link. Hidden until configured on
// the web, the production Field Team on the desktop; the sign-in hand-off must
// survive pop-up blockers and a failed ticket, and on the desktop come from
// the cloud, whose secret the cloud Field Team checks.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const { post, cfg } = vi.hoisted(() => ({ post: vi.fn(), cfg: { IS_LOCAL_APP: false } }))
vi.mock('../api/client', () => ({ default: { post } }))
// jsdom runs on localhost, which config.js would call the desktop app; each
// test says which one it is.
vi.mock('../config', async (importOriginal) => ({
  ...(await importOriginal()),
  get IS_LOCAL_APP() { return cfg.IS_LOCAL_APP },
  CLOUD_URL: 'https://cloud.example.app',
}))

import { FIELD_TEAM_CLOUD_URL, fieldTeamNeedsCloudData, getFieldTeamUrl, openFieldTeam } from '../config/fieldTeam'

const URL_ = 'https://field.example.app'
const fakeTab = () => ({ location: { href: '' }, focus: vi.fn() })

describe('Field Team link', () => {
  beforeEach(() => { post.mockReset(); cfg.IS_LOCAL_APP = false; localStorage.clear() })
  afterEach(() => { vi.unstubAllEnvs(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

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

  it('on the desktop, which is built without the URL, opens the production Field Team', () => {
    cfg.IS_LOCAL_APP = true
    vi.stubEnv('VITE_FIELD_TEAM_URL', '')
    expect(getFieldTeamUrl()).toBe(FIELD_TEAM_CLOUD_URL)
  })

  it('on the desktop, gets the ticket from the cloud with the cloud token, not from its own backend', async () => {
    cfg.IS_LOCAL_APP = true
    vi.stubEnv('VITE_FIELD_TEAM_URL', '')
    localStorage.setItem('bizassist_cloud_token', 'cloud-tok')
    const tab = fakeTab()
    vi.spyOn(window, 'open').mockReturnValue(tab)
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ticket: 'cloud.ticket.1' }) })
    vi.stubGlobal('fetch', fetchMock)

    await openFieldTeam()
    expect(post).not.toHaveBeenCalled()
    expect(fetchMock).toHaveBeenCalledWith('https://cloud.example.app/handoff-ticket',
      expect.objectContaining({ method: 'POST', headers: { Authorization: 'Bearer cloud-tok' } }))
    expect(tab.location.href).toBe(`${FIELD_TEAM_CLOUD_URL}/?sso=cloud.ticket.1`)
  })

  it('on the desktop without a cloud token, opens the sign-in page', async () => {
    cfg.IS_LOCAL_APP = true
    vi.stubEnv('VITE_FIELD_TEAM_URL', '')
    const tab = fakeTab()
    vi.spyOn(window, 'open').mockReturnValue(tab)
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    await openFieldTeam()
    expect(fetchMock).not.toHaveBeenCalled()
    expect(tab.location.href).toBe(`${FIELD_TEAM_CLOUD_URL}/`)
  })

  it('a local Field Team (start_dev) takes the local ticket', async () => {
    cfg.IS_LOCAL_APP = true
    vi.stubEnv('VITE_FIELD_TEAM_URL', 'http://localhost:5176')
    const tab = fakeTab()
    vi.spyOn(window, 'open').mockReturnValue(tab)
    post.mockResolvedValue({ ticket: 'local.ticket' })
    await openFieldTeam()
    expect(post).toHaveBeenCalledWith('/handoff-ticket')
    expect(tab.location.href).toBe('http://localhost:5176/?sso=local.ticket')
  })
})

describe('Field Team on a Local only desktop', () => {
  const cloud = FIELD_TEAM_CLOUD_URL
  it('asks to switch only on the desktop, on Local only, for the cloud Field Team', () => {
    expect(fieldTeamNeedsCloudData({ isLocalApp: true, effectiveMode: 'local', url: cloud })).toBe(true)
    expect(fieldTeamNeedsCloudData({ isLocalApp: true, effectiveMode: 'hybrid', url: cloud })).toBe(false)
    expect(fieldTeamNeedsCloudData({ isLocalApp: false, effectiveMode: 'cloud', url: cloud })).toBe(false)
    expect(fieldTeamNeedsCloudData({ isLocalApp: true, effectiveMode: 'local', url: 'http://localhost:5176' })).toBe(false)
    expect(fieldTeamNeedsCloudData({ isLocalApp: true, effectiveMode: 'local', url: null })).toBe(false)
  })
})
