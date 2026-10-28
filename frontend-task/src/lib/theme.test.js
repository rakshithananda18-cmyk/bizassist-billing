import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

let styles
let dark
let media
let theme
const tokens = (accent = '#c15f3c', background = '#ffffff') => ({
  '--bg': background, '--bg-2': background, '--accent': accent,
  '--accent-solid': accent, '--accent-foreground': '#ffffff',
  '--text-primary': '#111111', '--sidebar-surface': '#f4efeb',
})
const payload = (overrides = {}) => ({
  businessId: 'BA-ONE', mode: 'light', lightTokens: tokens(),
  darkTokens: tokens('#8fbafa', '#121212'), billingUrl: 'http://localhost:5174', ...overrides,
})

beforeEach(async () => {
  vi.resetModules()
  const storage = new Map()
  styles = new Map()
  dark = false
  media = { matches: false, addEventListener: vi.fn() }
  vi.stubGlobal('localStorage', {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
  })
  vi.stubGlobal('document', { documentElement: {
    classList: { toggle: (_className, value) => { dark = value } }, dataset: {},
    style: { setProperty: (key, value) => styles.set(key, value), removeProperty: key => styles.delete(key) },
  } })
  vi.stubGlobal('window', {
    location: { hostname: 'localhost', protocol: 'http:' },
    matchMedia: () => media, dispatchEvent: vi.fn(), addEventListener: vi.fn(),
  })
  vi.stubGlobal('CustomEvent', class { constructor(type, options) { this.type = type; this.detail = options?.detail } })
  theme = await import('./theme')
})
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs() })

describe('Billing appearance continuity', () => {
  it('uses the verified Billing palette in both modes and preserves it when mode changes', () => {
    theme.setThemeBusiness('BA-ONE')
    expect(theme.acceptBillingAppearance(payload())).toBe(true)
    expect(styles.get('--accent')).toBe('#c15f3c')
    theme.setTheme('dark')
    expect(dark).toBe(true)
    expect(styles.get('--accent')).toBe('#8fbafa')
    expect(styles.get('--bg')).toBe('#121212')
    expect(theme.getTheme()).toBe('dark')
  })

  it('keeps system mode responsive to the current device preference', () => {
    theme.setThemeBusiness('BA-ONE')
    theme.acceptBillingAppearance(payload({ mode: 'system' }))
    expect(dark).toBe(false)
    media.matches = true
    theme.applyTheme(theme.getTheme())
    expect(dark).toBe(true)
    expect(styles.get('--bg')).toBe('#121212')
  })

  it('isolates business preferences and removes the previous palette on logout or switch', () => {
    theme.setThemeBusiness('BA-ONE')
    theme.acceptBillingAppearance(payload({ mode: 'dark' }))
    theme.setThemeBusiness('BA-TWO')
    expect(styles.has('--accent')).toBe(false)
    expect(theme.getTheme()).toBe('system')
    expect(theme.acceptBillingAppearance(payload())).toBe(false)
    theme.setThemeBusiness('BA-ONE')
    expect(styles.get('--accent')).toBe('#8fbafa')
    theme.setThemeBusiness(null)
    expect(styles.size).toBe(0)
  })

  it('migrates a legacy mode to only the first business that claims it', () => {
    localStorage.setItem('task_theme', 'dark')
    theme.setThemeBusiness('BA-ONE')
    expect(theme.getTheme()).toBe('dark')
    theme.setThemeBusiness('BA-TWO')
    expect(theme.getTheme()).toBe('system')
  })

  it('rejects unsafe required tokens and ignores unknown properties', () => {
    theme.setThemeBusiness('BA-ONE')
    expect(theme.acceptBillingAppearance(payload({ lightTokens: { ...tokens(), '--bg': 'url(secret)' } }))).toBe(false)
    expect(theme.acceptBillingAppearance(payload({ lightTokens: { ...tokens(), '--other': '#ff0000', '--sidebar-bg': 'url(secret)' } }))).toBe(true)
    expect(styles.has('--other')).toBe(false)
    expect(styles.has('--sidebar-bg')).toBe(false)
  })

  it('allows Billing colour mixes and gradients without allowing arbitrary functions', () => {
    theme.setThemeBusiness('BA-ONE')
    const extra = { '--accent-dim': 'color-mix(in srgb, #245eac 10%, transparent)', '--sidebar-bg': 'linear-gradient(160deg, #123456, #ffffff)' }
    theme.acceptBillingAppearance(payload({ lightTokens: { ...tokens(), ...extra } }))
    expect(styles.get('--sidebar-bg')).toBe(extra['--sidebar-bg'])
    expect(styles.get('--accent-dim')).toBe(extra['--accent-dim'])
  })
})

describe('Return to Billing', () => {
  it('uses the account launch origin, without preserving query strings or credentials', () => {
    theme.setThemeBusiness('BA-ONE')
    theme.acceptBillingAppearance(payload({ billingUrl: 'http://192.168.1.20:8450/?sso=discarded' }))
    expect(theme.getBillingUrl('/settings?tab=profile')).toBe('http://192.168.1.20:8450/settings?tab=profile&field_business=BA-ONE')
    expect(theme.sanitizeBillingUrl('https://user:password@bizassist-billing.vercel.app')).toBe(null)
    expect(theme.sanitizeBillingUrl('javascript:alert(1)')).toBe(null)
    expect(theme.sanitizeBillingUrl('https://unrelated.example')).toBe(null)
    expect(theme.sanitizeBillingUrl('http://192.168.attacker.example:5174')).toBe(null)
    expect(theme.sanitizeBillingUrl('http://10.attacker.example:8450')).toBe(null)
  })

  it('uses local and configured fallbacks and prevents protocol-relative paths', () => {
    expect(theme.getBillingUrl()).toBe('http://localhost:5174/')
    vi.stubEnv('VITE_BILLING_URL', 'https://billing.staging.example')
    expect(theme.getBillingUrl('/parties')).toBe('https://billing.staging.example/parties')
    expect(theme.getBillingUrl('//unrelated.example')).toBe('https://billing.staging.example/')
    expect(theme.getBillingUrl('/\\unrelated.example')).toBe('https://billing.staging.example/')
  })
})
