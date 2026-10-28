// @vitest-environment jsdom
// ^ Uses window.open. vite.config.js sends *.test.js to the `node`
//   environment unless the file asks for a DOM like this.
//
// fieldTeam.js — the sidebar's "Field Team" link. Hidden until configured on
// the web, the production Field Team on the desktop; the sign-in hand-off must
// survive pop-up blockers and a failed ticket, and on the desktop come from
// the cloud, whose secret the cloud Field Team checks.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const { post, cfg } = vi.hoisted(() => ({ post: vi.fn(), cfg: { IS_LOCAL_APP: false, base: 'http://localhost:8001' } }))
vi.mock('../api/client', () => ({ default: { post } }))
// jsdom runs on localhost, which config.js would call the desktop app; each
// test says which one it is.
vi.mock('../config', async (importOriginal) => ({
  ...(await importOriginal()),
  get IS_LOCAL_APP() { return cfg.IS_LOCAL_APP },
  CLOUD_URL: 'https://cloud.example.app',
  getApiBase: () => cfg.base,
}))

import { FIELD_TEAM_CLOUD_URL, fieldTeamNeedsCloudData, getFieldTeamUrl, openFieldTeam } from '../config/fieldTeam'

const URL_ = 'https://field.example.app'
const fakeTab = () => ({ location: { href: '' }, focus: vi.fn(), postMessage: vi.fn() })

describe('Field Team link', () => {
  beforeEach(() => { post.mockReset(); cfg.IS_LOCAL_APP = false; cfg.base = 'http://localhost:8001'; localStorage.clear() })
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
    expect(tab.location.href).toContain(`${URL_}/?from_billing=1`); expect(tab.location.href).toContain("sso=1761140000.eyJpZCI6MX0.ab12")
    expect(tab.focus).toHaveBeenCalled()
  })

  it('still opens Field Team, at its sign-in page, when no ticket can be had', async () => {
    vi.stubEnv('VITE_FIELD_TEAM_URL', URL_)
    const tab = fakeTab()
    vi.spyOn(window, 'open').mockReturnValue(tab)
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    post.mockRejectedValue(new Error('offline'))

    await openFieldTeam()
    expect(tab.location.href).toContain(`${URL_}/?from_billing=1`)
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
    expect(tab.location.href).toContain(`${FIELD_TEAM_CLOUD_URL}/?from_billing=1`); expect(tab.location.href).toContain("sso=cloud.ticket.1")
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
    expect(tab.location.href).toContain(`${FIELD_TEAM_CLOUD_URL}/?from_billing=1`)
  })

  it('a local Field Team (start_dev) takes the local ticket', async () => {
    cfg.IS_LOCAL_APP = true
    vi.stubEnv('VITE_FIELD_TEAM_URL', 'http://localhost:5176'); vi.stubEnv('VITE_FIELD_TEAM_LOCAL_TEST', '1')
    const tab = fakeTab()
    vi.spyOn(window, 'open').mockReturnValue(tab)
    post.mockResolvedValue({ ticket: 'local.ticket' })
    await openFieldTeam()
    expect(post).toHaveBeenCalledWith('/handoff-ticket')
    expect(tab.location.href).toContain('http://localhost:5176/?from_billing=1'); expect(tab.location.href).toContain('sso=local.ticket')
  })

  it('keeps normal Field Team cloud-only even if a stale dev URL is configured', () => {
    cfg.IS_LOCAL_APP = true
    vi.stubEnv('VITE_FIELD_TEAM_URL', 'http://localhost:5176')
    expect(getFieldTeamUrl()).toBe(FIELD_TEAM_CLOUD_URL)
  })

  it('uses the active cloud Billing session instead of an older cloud-sync token', async () => {
    cfg.IS_LOCAL_APP = true
    cfg.base = 'https://cloud.example.app'
    vi.stubEnv('VITE_FIELD_TEAM_URL', FIELD_TEAM_CLOUD_URL)
    localStorage.setItem('bizassist_cloud_token', 'old-business-sync-token')
    vi.spyOn(window, 'open').mockReturnValue(fakeTab())
    post.mockResolvedValue({ ticket: 'current-business-ticket' })
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    await openFieldTeam({ user: { public_id: 'BA-ONE', user_id: 1 } })
    expect(post).toHaveBeenCalledWith('/handoff-ticket')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('shares both palette modes only with the matching business and opened window', async () => {
    vi.stubEnv('VITE_FIELD_TEAM_URL', URL_)
    const tab = fakeTab()
    vi.spyOn(window, 'open').mockReturnValue(tab)
    post.mockResolvedValue({ ticket: 'one-use' })
    await openFieldTeam({ user: { public_id: 'BA-ONE', user_id: 1 } })
    const launch = new URL(tab.location.href).searchParams.get('billing_launch')
    const ready = (source, businessId, origin = URL_) => window.dispatchEvent(Object.assign(new Event('message'), {
      source, origin, data: { type: 'BIZASSIST_FIELD_READY', launchId: launch, businessId },
    }))
    ready({}, 'BA-ONE')
    ready(tab, 'BA-TWO')
    ready(tab, 'BA-ONE', 'https://other.test')
    expect(tab.postMessage).not.toHaveBeenCalled()
    ready(tab, 'BA-ONE')
    const [{ appearance }, origin] = tab.postMessage.mock.calls[0]
    expect(origin).toBe(URL_)
    expect(appearance.businessId).toBe('BA-ONE')
    expect(appearance.lightTokens['--bg']).not.toBe(appearance.darkTokens['--bg'])
    expect(tab.location.href).not.toContain('--accent')
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
