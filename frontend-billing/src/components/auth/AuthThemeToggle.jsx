import React from 'react'
import { useAppearance } from '../../hooks/useAppearance'

export default function AuthThemeToggle() {
  const { resolvedTheme, setTheme } = useAppearance()
  const dark = resolvedTheme === 'dark'
  return <button className="auth-theme-toggle" type="button" onClick={() => setTheme(dark ? 'light' : 'dark')} aria-label={`Switch to ${dark ? 'light' : 'dark'} mode`} title={`Switch to ${dark ? 'light' : 'dark'} mode`}>
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {dark ? <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" /></> : <path d="M20.6 13.3A8.6 8.6 0 0 1 10.7 3.4 8.6 8.6 0 1 0 20.6 13.3Z" />}
    </svg>
  </button>
}
