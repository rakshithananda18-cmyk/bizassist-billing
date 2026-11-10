import { useEffect, useState } from 'react'

const CHANGE_EVENT = 'admin:preference-change'
const OPTIONS = {
  admin_time_format: ['IST', 'UTC'],
  admin_poll_interval: ['5', '10', '30'],
}
const DEFAULTS = { admin_time_format: 'IST', admin_poll_interval: '10' }

export function readAdminPreference(key) {
  try {
    const value = localStorage.getItem(key)
    return OPTIONS[key]?.includes(value) ? value : DEFAULTS[key]
  } catch { return DEFAULTS[key] }
}

export function writeAdminPreference(key, value) {
  if (!OPTIONS[key]?.includes(value)) return
  try { localStorage.setItem(key, value) } catch { /* Session UI stays usable without storage. */ }
  window.dispatchEvent(new CustomEvent(CHANGE_EVENT, { detail: { key, value } }))
}

export function useAdminPreference(key) {
  const [value, setValue] = useState(() => readAdminPreference(key))
  useEffect(() => {
    const update = event => {
      if (event.type === 'storage') setValue(readAdminPreference(key))
      else if (event.detail?.key === key) setValue(event.detail.value)
    }
    window.addEventListener(CHANGE_EVENT, update)
    window.addEventListener('storage', update)
    return () => {
      window.removeEventListener(CHANGE_EVENT, update)
      window.removeEventListener('storage', update)
    }
  }, [key])
  return [value, next => writeAdminPreference(key, next)]
}

export function useAdminTheme() {
  const [isDark, setIsDark] = useState(() => document.documentElement.classList.contains('dark-mode'))
  useEffect(() => {
    const observer = new MutationObserver(() => setIsDark(document.documentElement.classList.contains('dark-mode')))
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    return () => observer.disconnect()
  }, [])
  const setTheme = dark => {
    document.documentElement.classList.toggle('dark-mode', dark)
    setIsDark(dark)
    try {
      localStorage.setItem('theme', dark ? 'dark' : 'light')
      localStorage.setItem('billing_theme', dark ? 'dark' : 'light')
    } catch { /* Theme still applies when browser storage is disabled. */ }
  }
  return [isDark, setTheme]
}

export function formatAdminTime(value, standard = readAdminPreference('admin_time_format')) {
  if (!value) return '—'
  const raw = String(value)
  // API timestamps are UTC; Python can serialize them without a timezone suffix.
  const iso = /^\d{4}-\d\d-\d\dT/.test(raw) && !/(?:Z|[+-]\d\d:\d\d)$/i.test(raw) ? `${raw}Z` : raw
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return raw
  return date.toLocaleString('en-IN', { timeZone: standard === 'UTC' ? 'UTC' : 'Asia/Kolkata', timeZoneName: 'short' })
}
