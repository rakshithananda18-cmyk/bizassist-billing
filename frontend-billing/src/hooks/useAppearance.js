import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import {
  APPEARANCE_EVENT, CUSTOM_PALETTES_EVENT, applyAppearance, appearanceStorageKey, customPalettesStorageKey, normalizeAppearance,
  readAppearance, saveAppearance, appearanceThemeColors, normalizeHexColor, THEME_COLOR_KEYS,
} from '../utils/appearance'

const systemIsDark = () => typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches

// AppLayout and Settings share the same preference without introducing a
// second settings request or making personal colours part of store-wide data.
export function useAppearance() {
  const { user } = useAuth() || {}
  const preferenceKey = appearanceStorageKey(user)
  const paletteLibraryKey = customPalettesStorageKey(user)
  const [state, setState] = useState(() => ({ key: preferenceKey, value: readAppearance(user) }))
  const [libraryRevision, setLibraryRevision] = useState(0)
  const [systemDark, setSystemDark] = useState(systemIsDark)
  const preference = state.key === preferenceKey ? state.value : readAppearance(user)
  const signature = JSON.stringify(preference)
  const themeColors = useMemo(() => appearanceThemeColors(preference, user), [preferenceKey, signature, libraryRevision])

  useEffect(() => {
    setState({ key: preferenceKey, value: readAppearance(user) })
    const onChange = event => {
      if (event.detail?.key === preferenceKey) {
        setState({ key: preferenceKey, value: normalizeAppearance(event.detail.appearance, user) })
      }
    }
    const onLibraryChange = event => {
      if (event.detail?.key === paletteLibraryKey) {
        setLibraryRevision(revision => revision + 1)
        setState({ key: preferenceKey, value: readAppearance(user) })
      }
    }
    const onStorage = event => {
      if (event.key === preferenceKey || event.key === paletteLibraryKey || event.key === null) {
        setState({ key: preferenceKey, value: readAppearance(user) })
      }
      if (event.key === paletteLibraryKey || event.key === null) {
        setLibraryRevision(revision => revision + 1)
      }
    }
    window.addEventListener(APPEARANCE_EVENT, onChange)
    window.addEventListener(CUSTOM_PALETTES_EVENT, onLibraryChange)
    window.addEventListener('storage', onStorage)
    return () => {
      window.removeEventListener(APPEARANCE_EVENT, onChange)
      window.removeEventListener(CUSTOM_PALETTES_EVENT, onLibraryChange)
      window.removeEventListener('storage', onStorage)
    }
  }, [preferenceKey, paletteLibraryKey])

  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    setSystemDark(media.matches)
    const update = event => setSystemDark(event.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])

  useLayoutEffect(() => {
    applyAppearance(preference, systemDark, undefined, user)
    saveAppearance(user, preference)
  }, [preferenceKey, signature, systemDark, libraryRevision])

  const update = useCallback(patch => {
    const appearance = saveAppearance(user, { ...preference, ...patch })
    setState({ key: preferenceKey, value: appearance })
    window.dispatchEvent(new CustomEvent(APPEARANCE_EVENT, { detail: { key: preferenceKey, appearance } }))
  }, [preferenceKey, signature])

  const setTheme = useCallback(theme => update({ theme }), [update])
  const setAccent = useCallback(accent => update(accent === 'custom' && preference.accent !== 'custom'
    ? { accent, customColors: themeColors } : { accent }), [update, preference.accent, themeColors])
  const setCustomColor = useCallback((key, value) => {
    const hex = normalizeHexColor(value)
    if (!THEME_COLOR_KEYS.includes(key) || !hex) return false
    update({ accent: 'custom', customColors: { ...themeColors, [key]: hex } })
    return true
  }, [update, themeColors])
  const setWindowGradient = useCallback(value => update({ windowGradient: value === true }), [update])
  const setDarkerSidebar = useCallback(value => update({ darkerSidebar: value === true }), [update])
  return {
    ...preference, setTheme, setAccent, setCustomColor, setWindowGradient, setDarkerSidebar, themeColors, preferenceKey,
    user, paletteLibraryKey, libraryRevision,
    resolvedTheme: preference.theme === 'system' ? (systemDark ? 'dark' : 'light') : preference.theme,
  }
}
