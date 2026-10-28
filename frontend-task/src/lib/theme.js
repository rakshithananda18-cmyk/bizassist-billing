// Billing owns the account palette. The verified launch bridge supplies its
// light/dark tokens, without putting preferences or credentials in a URL.
const KEY = 'task_theme'
const BUSINESS_MODE_PREFIX = 'task_theme_v2:'
const APPEARANCE_PREFIX = 'task_billing_appearance_v1:'
const LEGACY_OWNER_KEY = 'task_theme_legacy_owner'
const BILLING_CLOUD_URL = 'https://bizassist-billing.vercel.app'
const MODES = new Set(['system', 'light', 'dark'])
const TOKEN_NAMES = new Set([
  '--accent', '--accent-light', '--accent-hover', '--accent-solid', '--accent-solid-hover',
  '--accent-contrast', '--accent-foreground', '--accent-dim', '--accent-glow', '--accent-muted',
  '--accent-soft', '--accent-subtle', '--accent-rgb', '--accent-softer', '--border-subtle', '--shadow-accent',
  '--bg', '--bg-1', '--bg-2', '--bg-3', '--bg-4', '--surface', '--surface-hover',
  '--border', '--border-strong', '--border-focus', '--glass-bg', '--glass-bg-hover', '--glass-border',
  '--text-primary', '--text-secondary', '--text-muted', '--text-inverse', '--sidebar-bg',
  '--sidebar-surface', '--sidebar-text', '--sidebar-muted', '--sidebar-hover', '--sidebar-hover-text',
  '--sidebar-border', '--sidebar-active-bg', '--sidebar-active-text', '--theme-surface',
  '--theme-chrome', '--theme-chrome-text', '--theme-chrome-muted',
])
const REQUIRED_TOKENS = ['--bg', '--bg-2', '--accent', '--accent-solid', '--text-primary', '--sidebar-surface']
let businessId = null
let appliedTokens = new Set()

const getStored = key => { try { return localStorage.getItem(key) } catch { return null } }
const store = (key, value) => { try { localStorage.setItem(key, value) } catch { /* private mode */ } }
const validBusiness = value => typeof value === 'string' && /^[A-Za-z0-9_-]{1,100}$/.test(value)
const modeKey = () => businessId ? `${BUSINESS_MODE_PREFIX}${businessId}` : KEY
const appearanceKey = () => businessId ? `${APPEARANCE_PREFIX}${businessId}` : null
function localHost(host) {
  if (host === 'localhost' || host === '[::1]' || host.endsWith('.local')) return true
  const parts = host.split('.')
  if (parts.length !== 4 || parts.some(part => !/^\d{1,3}$/.test(part) || Number(part) > 255)) return false
  const [first, second] = parts.map(Number)
  return first === 127 || first === 10 || (first === 192 && second === 168)
    || (first === 172 && second >= 16 && second <= 31)
}

/** Return a trusted Billing origin only; never preserve query credentials. */
export function sanitizeBillingUrl(value) {
  try {
    const url = new URL(value)
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null
    const configured = import.meta.env.VITE_BILLING_URL
    let configuredOrigin = null
    try { configuredOrigin = configured ? new URL(configured).origin : null } catch { /* invalid config */ }
    if (url.origin === BILLING_CLOUD_URL || url.origin === configuredOrigin
      || (localHost(url.hostname) && ['5174', '8450'].includes(url.port))) return url.origin
  } catch { /* invalid URL */ }
  return null
}

function cleanTokens(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return null
  const tokens = {}
  for (const [name, value] of Object.entries(input)) {
    if (!TOKEN_NAMES.has(name) || typeof value !== 'string' || value.length > 600
      || !/^[#a-z\d\s.,()%+\-]+$/i.test(value)) continue
    // Only colour functions emitted by Billing are accepted. CSS cannot make
    // URL requests or inject declarations through this preference channel.
    const functions = [...value.matchAll(/([a-z-]+)\s*\(/gi)].map(match => match[1].toLowerCase())
    if (functions.some(name => !['rgb', 'rgba', 'color-mix', 'linear-gradient'].includes(name))) continue
    tokens[name] = value
  }
  return REQUIRED_TOKENS.every(name => tokens[name]) ? tokens : null
}

function readAppearance() {
  if (!businessId) return null
  try {
    const appearance = JSON.parse(getStored(appearanceKey()) || 'null')
    const lightTokens = cleanTokens(appearance?.lightTokens)
    const darkTokens = cleanTokens(appearance?.darkTokens)
    if (appearance?.businessId !== businessId || !lightTokens || !darkTokens) return null
    return { ...appearance, lightTokens, darkTokens, billingUrl: sanitizeBillingUrl(appearance.billingUrl) }
  } catch { return null }
}

function notifyTheme() {
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('task-theme-change', { detail: getTheme() }))
}

export function setThemeBusiness(value) {
  businessId = validBusiness(value) ? value : null
  applyTheme(getTheme())
  notifyTheme()
}

export function acceptBillingAppearance(appearance) {
  if (!businessId || appearance?.businessId !== businessId || !MODES.has(appearance.mode)) return false
  const lightTokens = cleanTokens(appearance.lightTokens)
  const darkTokens = cleanTokens(appearance.darkTokens)
  const billingUrl = sanitizeBillingUrl(appearance.billingUrl)
  if (!lightTokens || !darkTokens || !billingUrl) return false
  store(appearanceKey(), JSON.stringify({ businessId, mode: appearance.mode, lightTokens, darkTokens, billingUrl }))
  store(modeKey(), appearance.mode)
  applyTheme(appearance.mode)
  notifyTheme()
  return true
}

export function getBillingUrl(path = '/') {
  const inherited = readAppearance()?.billingUrl
  const configured = sanitizeBillingUrl(import.meta.env.VITE_BILLING_URL)
  const fallback = typeof window !== 'undefined' && localHost(window.location.hostname)
    ? `${window.location.protocol}//${window.location.hostname}:5174` : BILLING_CLOUD_URL
  const origin = inherited || configured || fallback
  const safePath = typeof path === 'string' && path.startsWith('/') && !path.startsWith('//') && !path.includes('\\') ? path : '/'
  const url = new URL(safePath, `${origin}/`)
  if (businessId) url.searchParams.set('field_business', businessId)
  return url.href
}

export function applyTheme(choice) {
  const mode = MODES.has(choice) ? choice : 'system'
  const dark = mode === 'dark' || (mode === 'system' && typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches)
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.classList.toggle('dark-mode', Boolean(dark))
  root.dataset.appearance = dark ? 'dark' : 'light'
  root.style.colorScheme = dark ? 'dark' : 'light'
  appliedTokens.forEach(name => root.style.removeProperty(name))
  const tokens = readAppearance()?.[dark ? 'darkTokens' : 'lightTokens'] || {}
  Object.entries(tokens).forEach(([name, value]) => root.style.setProperty(name, value))
  appliedTokens = new Set(Object.keys(tokens))
}

export function getTheme() {
  const scoped = getStored(modeKey())
  if (MODES.has(scoped)) return scoped
  if (businessId) {
    const inherited = readAppearance()?.mode
    if (MODES.has(inherited)) return inherited
    // Claim the old device preference once; a different account must not
    // inherit the previous business's mode after a switch.
    const owner = getStored(LEGACY_OWNER_KEY)
    const legacy = getStored(KEY)
    if ((!owner || owner === businessId) && MODES.has(legacy)) {
      store(LEGACY_OWNER_KEY, businessId)
      store(modeKey(), legacy)
      return legacy
    }
    return 'system'
  }
  const billing = getStored('billing_theme')
  return MODES.has(billing) ? billing : 'system'
}

export function setTheme(choice) {
  const mode = MODES.has(choice) ? choice : 'system'
  store(modeKey(), mode)
  applyTheme(mode)
  notifyTheme()
}

export function cycleTheme() {
  const order = ['system', 'light', 'dark']
  const next = order[(order.indexOf(getTheme()) + 1) % order.length]
  setTheme(next)
  return next
}

if (typeof window !== 'undefined') {
  try {
    window.matchMedia?.('(prefers-color-scheme: dark)')?.addEventListener?.('change', () => {
      if (getTheme() === 'system') applyTheme('system')
    })
    window.addEventListener?.('storage', event => {
      if ([modeKey(), appearanceKey(), 'billing_theme'].includes(event.key) || event.key === null) {
        applyTheme(getTheme())
        notifyTheme()
      }
    })
  } catch { /* unavailable browser preferences */ }
}
