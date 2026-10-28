// lib/theme.js — billing's theme rule: 'system' by default, explicit light/dark wins.
const KEY = 'task_theme'
const BILLING_KEY = 'billing_theme'

export function applyTheme(choice) {
  const dark = choice === 'dark' || (choice === 'system' && typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches)
  if (typeof document !== 'undefined') {
    document.documentElement.classList.toggle('dark-mode', Boolean(dark))
  }
}

export function getTheme() {
  try {
    return localStorage.getItem(KEY) || localStorage.getItem(BILLING_KEY) || 'system'
  } catch {
    return 'system'
  }
}

export function setTheme(choice) {
  try {
    localStorage.setItem(KEY, choice)
  } catch { /* ignore */ }
  applyTheme(choice)
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('task-theme-change', { detail: choice }))
  }
}

export function cycleTheme() {
  const order = ['system', 'light', 'dark']
  const current = getTheme()
  const idx = order.indexOf(current)
  const next = order[(idx >= 0 ? idx + 1 : 0) % order.length]
  setTheme(next)
  return next
}

// Auto-sync with system preference changes if in 'system' mode
if (typeof window !== 'undefined') {
  try {
    const media = window.matchMedia?.('(prefers-color-scheme: dark)')
    media?.addEventListener?.('change', () => {
      if (getTheme() === 'system') applyTheme('system')
    })
    window.addEventListener?.('storage', (e) => {
      if (e.key === KEY || e.key === BILLING_KEY) {
        applyTheme(getTheme())
      }
    })
  } catch { /* ignore */ }
}
