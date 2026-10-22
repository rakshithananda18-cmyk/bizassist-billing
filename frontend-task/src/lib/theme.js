// lib/theme.js — billing's theme rule: 'system' by default, explicit light/dark wins.
const KEY = 'task_theme'

export function applyTheme(choice) {
  const dark = choice === 'dark' || (choice === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.classList.toggle('dark-mode', dark)
}

export function getTheme() {
  try { return localStorage.getItem(KEY) || 'system' } catch { return 'system' }
}

export function setTheme(choice) {
  try { localStorage.setItem(KEY, choice) } catch { /* ignore */ }
  applyTheme(choice)
}

export function cycleTheme() {
  const order = ['system', 'light', 'dark']
  const next = order[(order.indexOf(getTheme()) + 1) % order.length]
  setTheme(next)
  return next
}
