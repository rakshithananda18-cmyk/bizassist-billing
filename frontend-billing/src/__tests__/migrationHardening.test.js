// @vitest-environment jsdom
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
const { post } = vi.hoisted(() => ({ post: vi.fn() }))
vi.mock('../api/client', () => ({ default: { post } }))
import { fieldTeamLaunchUrl, getFieldTeamUrl, openFieldTeam } from '../config/fieldTeam'
import { openAiDashboard } from '../config/aiDashboard'

describe('production companion launches', () => {
  beforeEach(() => { post.mockReset(); vi.stubEnv('VITE_FIELD_TEAM_URL', ''); localStorage.clear(); sessionStorage.clear() })
  afterEach(() => { vi.unstubAllEnvs(); vi.restoreAllMocks(); sessionStorage.clear(); window.history.replaceState({}, '', '/') })
  it('has a working business-aware Field Team link without build variables', () => {
    expect(getFieldTeamUrl()).toBe('https://task.staterbill.com')
    const target = new URL(fieldTeamLaunchUrl({ public_id: 'BA-ONE' }))
    expect(target.searchParams.get('billing_business')).toBe('BA-ONE')
    expect(target.searchParams.get('from_billing')).toBe('1')
    expect(target.searchParams.has('sso')).toBe(false)
  })
  it('explains a blocked popup without requesting a ticket', async () => {
    vi.spyOn(window, 'open').mockReturnValue(null)
    const events = vi.fn(); window.addEventListener('show_toast', events)
    await openFieldTeam()
    expect(post).not.toHaveBeenCalled()
    expect(events.mock.calls.at(-1)?.[0].detail.msg).toMatch(/blocked/)
    window.removeEventListener('show_toast', events)
  })
  it('opens the dashboard before its ticket resolves and requests the correct audience', async () => {
    let resolve; post.mockReturnValue(new Promise(r => { resolve = r }))
    const tab = { location: { href: '' }, focus: vi.fn() }
    const open = vi.spyOn(window, 'open').mockReturnValue(tab)
    const done = openAiDashboard({ user: { public_id: 'BA-ONE' } })
    expect(open).toHaveBeenCalledWith('', 'ai_dashboard')
    expect(post).toHaveBeenCalledWith('/handoff-ticket', { purpose: 'ai_dashboard' }, expect.any(Object))
    resolve({ ticket: 'one-use' }); await done
    expect(tab.location.href).toContain('sso=one-use')
    expect(tab.location.href).toContain('billing_business=BA-ONE')
  })

  it.each(['user', 'session', 'url'])('keeps Stater AI closed for a demo identified by %s, including direct search launches', async source => {
    const user = source === 'user' ? { is_demo: true } : undefined
    if (source === 'session') sessionStorage.setItem('stater_demo_active', '1')
    if (source === 'url') window.history.replaceState({}, '', '/?demo=true')
    const open = vi.spyOn(window, 'open').mockReturnValue({ location: { href: '' }, focus: vi.fn() })

    expect(await openAiDashboard({ user })).toBe(false)
    expect(open).not.toHaveBeenCalled()
    expect(post).not.toHaveBeenCalled()
  })
})
