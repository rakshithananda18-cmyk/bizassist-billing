export const APPEARANCE_EVENT = 'billing-appearance-change'
export const CUSTOM_PALETTES_EVENT = 'billing-custom-palettes-change'
export const THEME_COLOR_KEYS = Object.freeze(['sidebar', 'surface', 'accent', 'selection'])
const CUSTOM_PALETTES_KEY = 'billing_custom_palettes_v1'
const CUSTOM_PALETTES_OWNER_KEY = 'billing_custom_palettes_legacy_owner'
export const CUSTOM_THEME_DEFAULTS = Object.freeze({ sidebar: '#f4efeb', surface: '#ffffff', accent: '#c15f3c', selection: '#c15f3c' })
export const DEFAULT_APPEARANCE = Object.freeze({
  theme: 'system', accent: 'terracotta', customColors: CUSTOM_THEME_DEFAULTS,
  windowGradient: false, darkerSidebar: false,
})
const LEGACY_OWNER_KEY = 'billing_appearance_legacy_owner'

// Text accents brighten in dark mode. Filled actions have a separate shade so
// their white labels remain readable in either mode. Each definition also owns
// its navigation colours: previews and applied colours share this one registry.
export const APPEARANCE_PALETTES = [
  { id: 'terracotta', name: 'Terracotta', description: 'Warm and familiar',
    themeName: 'Classic', colors: { ...CUSTOM_THEME_DEFAULTS },
    light: { accent: '#c15f3c', solid: '#c15f3c', hover: '#a84e2e', canvas: '#fdfdfc', soft: '#f4efeb', card: '#ffffff', raised: '#f4f4f1', border: '#c8c5be' },
    dark: { accent: '#d4714a', solid: '#c15f3c', hover: '#e08660', canvas: '#121212', soft: '#181818', card: '#1e1e1e', raised: '#262626', border: '#333333' } },
  { id: 'ocean', name: 'Ocean', description: 'Clear and focused',
    themeName: 'Lagoon', colors: { sidebar: '#356676', surface: '#245765', accent: '#245765', selection: '#edc46e' },
    light: { accent: '#245eac', solid: '#245eac', hover: '#194980', canvas: '#f8fafc', soft: '#edf3fa', card: '#ffffff', raised: '#e1eaf5', border: '#bdcbdc' },
    dark: { accent: '#8fbafa', solid: '#245eac', hover: '#194980', canvas: '#11161d', soft: '#171e28', card: '#1d2733', raised: '#293648', border: '#3f526b' } },
  { id: 'forest', name: 'Forest', description: 'Calm and grounded',
    themeName: 'Mint', colors: { sidebar: '#d4f5e6', surface: '#6ec498', accent: '#a65471', selection: '#a65471' },
    light: { accent: '#186b4b', solid: '#186b4b', hover: '#105238', canvas: '#f8fbf9', soft: '#edf5f0', card: '#ffffff', raised: '#dfede4', border: '#bbcebf' },
    dark: { accent: '#8fcfae', solid: '#186b4b', hover: '#105238', canvas: '#111813', soft: '#171f1a', card: '#1d2921', raised: '#2a392e', border: '#3f5646' } },
  { id: 'orchid', name: 'Orchid', description: 'Rich and creative',
    themeName: 'Sundown', colors: { sidebar: '#fbead1', surface: '#edb770', accent: '#32775c', selection: '#32775c' },
    light: { accent: '#77489e', solid: '#77489e', hover: '#5f347e', canvas: '#fbf9fd', soft: '#f2edf7', card: '#ffffff', raised: '#e9dff1', border: '#ccbdd8' },
    dark: { accent: '#c9a5ed', solid: '#77489e', hover: '#5f347e', canvas: '#17121c', soft: '#201927', card: '#292131', raised: '#392d44', border: '#594367' } },
  { id: 'rose', name: 'Rose', description: 'Soft and expressive',
    themeName: 'Cherry', colors: { sidebar: '#b83b55', surface: '#b22f44', accent: '#9b263d', selection: '#a7d581' },
    light: { accent: '#a73a64', solid: '#a73a64', hover: '#87284d', canvas: '#fdf9fb', soft: '#f8edf2', card: '#ffffff', raised: '#f0dfe7', border: '#d8bec9' },
    dark: { accent: '#eca3c0', solid: '#a73a64', hover: '#87284d', canvas: '#1b1317', soft: '#251b20', card: '#2e2228', raised: '#402d36', border: '#664451' } },
  { id: 'graphite', name: 'Graphite', description: 'Quiet and minimal',
    themeName: 'Graphite', colors: { sidebar: '#30343b', surface: '#24272d', accent: '#526072', selection: '#dce5ef' },
    light: { accent: '#526072', solid: '#526072', hover: '#3f4a59', canvas: '#f8f9fa', soft: '#eef0f3', card: '#ffffff', raised: '#e2e6eb', border: '#c0c7d0' },
    dark: { accent: '#b7c5d8', solid: '#526072', hover: '#3f4a59', canvas: '#13161a', soft: '#1a1e24', card: '#222830', raised: '#303844', border: '#495563' } },
  { id: 'heritage', name: 'Heritage', description: 'Parchment, forest & midnight',
    themeName: 'Heritage', colors: { sidebar: '#0e192b', surface: '#132237', accent: '#e4d6bc', selection: '#243a2e' },
    light: { accent: '#243a2e', solid: '#243a2e', hover: '#192920', canvas: '#f8f5ee', soft: '#dad4c6', card: '#ffffff', raised: '#ede6d5', border: '#cfc7b7' },
    dark: { accent: '#e4d6bc', solid: '#203348', hover: '#2c4460', canvas: '#081020', soft: '#0e192b', card: '#132237', raised: '#1a2c44', border: '#243a56' } },
]

// Compatibility export; no second copy of the colour values can drift.
export const THEME_PRESETS = APPEARANCE_PALETTES.map(({ id, themeName, colors }) => ({ id, name: themeName, colors }))

function browserStorage() {
  try { return globalThis.localStorage } catch { return null }
}

export function customPalettesStorageKey(user) {
  return `billing_custom_palettes_v2:${encodeURIComponent(appearanceScope(user))}`
}

function readPaletteList(raw) {
  if (!raw) return []
  const parsed = JSON.parse(raw)
  if (!Array.isArray(parsed)) return []
  return parsed.filter(palette => palette && typeof palette.id === 'string'
    && palette.id.startsWith('custom_') && typeof palette.name === 'string'
    && THEME_COLOR_KEYS.every(key => normalizeHexColor(palette.colors?.[key]))
    && ['light', 'dark'].every(mode => palette[mode]
      && ['accent', 'solid', 'hover', 'canvas', 'soft', 'card', 'raised', 'border']
        .every(key => normalizeHexColor(palette[mode][key]))))
}

export function getCustomPalettes(user, storage = browserStorage()) {
  try {
    const key = customPalettesStorageKey(user)
    const scoped = storage?.getItem(key)
    if (scoped !== null && scoped !== undefined) return readPaletteList(scoped)

    // The old library carried no ownership. An authenticated account can claim
    // it once. Other accounts retain only a palette they had already selected;
    // they cannot browse, edit, or delete the first account's library.
    if (appearanceScope(user) === 'guest') return []
    const legacy = readPaletteList(storage?.getItem(CUSTOM_PALETTES_KEY))
    if (!legacy.length) return []
    const owner = storage?.getItem(CUSTOM_PALETTES_OWNER_KEY) || storage?.getItem(LEGACY_OWNER_KEY)
    const scope = appearanceScope(user)
    let migrated = legacy
    if (owner && owner !== scope) {
      let selected = null
      try { selected = JSON.parse(storage?.getItem(appearanceStorageKey(user)) || 'null')?.accent } catch { /* invalid preference */ }
      migrated = legacy.filter(palette => palette.id === selected)
    } else {
      storage?.setItem(CUSTOM_PALETTES_OWNER_KEY, scope)
    }
    storage?.setItem(key, JSON.stringify(migrated))
    return migrated
  } catch {
    return []
  }
}

function notifyPaletteChange(user) {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(CUSTOM_PALETTES_EVENT, { detail: { key: customPalettesStorageKey(user) } }))
  }
}

export function saveCustomPalette(user, palette, storage = browserStorage()) {
  try {
    if (!readPaletteList(JSON.stringify([palette])).length) return getCustomPalettes(user, storage)
    const current = getCustomPalettes(user, storage)
    const filtered = current.filter(p => p.id !== palette.id)
    filtered.push(palette)
    storage?.setItem(customPalettesStorageKey(user), JSON.stringify(filtered))
    notifyPaletteChange(user)
    return filtered
  } catch {
    return []
  }
}

export function deleteCustomPalette(user, paletteId, storage = browserStorage()) {
  try {
    const current = getCustomPalettes(user, storage)
    const filtered = current.filter(p => p.id !== paletteId)
    storage?.setItem(customPalettesStorageKey(user), JSON.stringify(filtered))
    notifyPaletteChange(user)
    return filtered
  } catch {
    return []
  }
}

export function buildCustomPalette(name, rawColors = {}) {
  const id = `custom_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`
  const accent = normalizeHexColor(rawColors.accent) || '#c15f3c'
  const sidebar = normalizeHexColor(rawColors.sidebar) || '#f4efeb'
  const surface = normalizeHexColor(rawColors.surface) || '#ffffff'
  const selection = normalizeHexColor(rawColors.selection) || accent
  const colors = { sidebar, surface, accent, selection }

  const light = {
    accent,
    solid: accent,
    hover: blend(accent, '#000000', 0.14),
    canvas: '#fdfdfc',
    soft: blend(surface, '#000000', 0.04),
    card: surface,
    raised: blend(surface, '#000000', 0.06),
    border: blend(accent, '#d9dadd', 0.3),
  }

  const dark = {
    accent: blend(accent, '#ffffff', 0.25),
    solid: accent,
    hover: blend(accent, '#ffffff', 0.14),
    canvas: '#121212',
    soft: '#181818',
    card: '#1e1e1e',
    raised: '#262626',
    border: '#333333',
  }

  return {
    id,
    name: name?.trim() || 'Custom Palette',
    description: 'Custom user palette',
    isCustom: true,
    colors,
    light,
    dark,
  }
}

export function normalizeAppearance(value, user, storage = browserStorage()) {
  const custom = getCustomPalettes(user, storage)
  const isValidAccent = value?.accent === 'custom'
    || APPEARANCE_PALETTES.some(palette => palette.id === value?.accent)
    || custom.some(palette => palette.id === value?.accent)

  return {
    theme: ['light', 'dark', 'system'].includes(value?.theme) ? value.theme : DEFAULT_APPEARANCE.theme,
    accent: isValidAccent ? value?.accent : DEFAULT_APPEARANCE.accent,
    customColors: Object.fromEntries(THEME_COLOR_KEYS.map(key => [key, normalizeHexColor(value?.customColors?.[key]) || CUSTOM_THEME_DEFAULTS[key]])),
    windowGradient: value?.windowGradient === true,
    darkerSidebar: value?.darkerSidebar === true,
  }
}

export function normalizeHexColor(value) {
  if (typeof value !== 'string') return null
  const hex = value.trim().toLowerCase()
  if (/^#[0-9a-f]{6}$/.test(hex)) return hex
  if (/^#[0-9a-f]{3}$/.test(hex)) return `#${hex.slice(1).split('').map(channel => channel + channel).join('')}`
  return null
}

const channels = hex => hex.slice(1).match(/../g).map(channel => parseInt(channel, 16))
const blend = (from, to, amount) => `#${channels(from).map((channel, index) =>
  Math.round(channel + (channels(to)[index] - channel) * amount).toString(16).padStart(2, '0')).join('')}`
const luminance = hex => channels(hex).map(channel => channel / 255)
  .map(channel => channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4)
  .reduce((sum, channel, index) => sum + channel * [.2126, .7152, .0722][index], 0)

export const contrastRatio = (a, b) => (Math.max(luminance(a), luminance(b)) + .05) / (Math.min(luminance(a), luminance(b)) + .05)
export const themeForeground = background => contrastRatio('#ffffff', background) >= contrastRatio('#17191d', background) ? '#ffffff' : '#17191d'

function readableColour(colour, background, target) {
  if (contrastRatio(colour, background) >= 4.5) return colour
  for (let step = 1; step <= 100; step++) {
    const result = blend(colour, target, step / 100)
    if (contrastRatio(result, background) >= 4.5) return result
  }
  return target
}

function readableOnSurfaces(colour, backgrounds, target) {
  if (backgrounds.every(background => contrastRatio(colour, background) >= 4.5)) return colour
  for (let step = 1; step <= 100; step++) {
    const result = blend(colour, target, step / 100)
    if (backgrounds.every(background => contrastRatio(result, background) >= 4.5)) return result
  }
  return target
}

const strongestForeground = background => contrastRatio('#ffffff', background) >= contrastRatio('#000000', background) ? '#ffffff' : '#000000'

function softNavigationSelection(selection, surface) {
  // The navigation selection can intentionally differ from action buttons
  // (gold navigation with blue actions, for example). Tint a neutral surface
  // so a coloured sidebar cannot turn the selected hue into another colour.
  const base = strongestForeground(surface) === '#ffffff' ? '#17191d' : '#ffffff'
  const background = blend(base, selection, .2)
  const foreground = readableColour(selection, background, strongestForeground(background))
  return { background, foreground, border: blend(background, foreground, .3) }
}

export function appearanceThemeColors(preference, user, storage = browserStorage()) {
  const appearance = normalizeAppearance(preference, user, storage)
  if (appearance.accent === 'custom') return { ...appearance.customColors }
  const custom = getCustomPalettes(user, storage).find(p => p.id === appearance.accent)
  if (custom) return { ...custom.colors }
  const preset = APPEARANCE_PALETTES.find(item => item.id === appearance.accent)
  return { ...(preset ? preset.colors : CUSTOM_THEME_DEFAULTS) }
}

export function appearanceScope(user) {
  if (!user) return 'guest'
  const identity = user.user_id ?? user.id ?? user.username
  return identity == null ? 'guest' : `${user.public_id || 'local'}:${identity}`
}

export function appearanceStorageKey(user) {
  return `billing_appearance_v1:${encodeURIComponent(appearanceScope(user))}`
}

export function readAppearance(user, storage = browserStorage()) {
  try {
    const key = appearanceStorageKey(user)
    const saved = storage?.getItem(key)
    if (saved) return normalizeAppearance(JSON.parse(saved), user, storage)

    const scope = appearanceScope(user)
    const legacyOwner = storage?.getItem(LEGACY_OWNER_KEY)
    // Only the first account may claim the former device-wide preference.
    // Another user on this till starts with their own defaults.
    if (scope === 'guest' || !legacyOwner || legacyOwner === scope) {
      const legacy = normalizeAppearance({ theme: storage?.getItem('billing_theme'), accent: storage?.getItem('billing_accent') }, user, storage)
      if (scope !== 'guest') {
        storage?.setItem(LEGACY_OWNER_KEY, scope)
        storage?.setItem(key, JSON.stringify(legacy))
      }
      return legacy
    }
  } catch { /* A corrupt preference or private storage must not block billing. */ }
  return normalizeAppearance(DEFAULT_APPEARANCE, user, storage)
}

export function saveAppearance(user, preference, storage = browserStorage()) {
  const appearance = normalizeAppearance(preference, user, storage)
  try {
    storage?.setItem(appearanceStorageKey(user), JSON.stringify(appearance))
    // Auth restoration briefly renders the guest appearance first. Leave the
    // legacy mirrors intact until an account can claim its existing palette.
    if (appearanceScope(user) !== 'guest') {
      storage?.setItem('billing_theme', appearance.theme)
      storage?.setItem('billing_accent', appearance.accent)
    }
  } catch { /* The current session still changes when persistence is unavailable. */ }
  return appearance
}

export function appearanceTokens(preference, systemDark = false, user, storage = browserStorage()) {
  const appearance = normalizeAppearance(preference, user, storage)
  const mode = appearance.theme === 'system' ? (systemDark ? 'dark' : 'light') : appearance.theme
  const dark = mode === 'dark'
  const picked = appearanceThemeColors(appearance, user, storage)
  // The working canvas and navigation use the same canonical palette that
  // supplies the settings preview.
  const custom = getCustomPalettes(user, storage).find(p => p.id === appearance.accent)
  const palette = APPEARANCE_PALETTES.find(p => p.id === appearance.accent) || custom
  const colors = palette
    ? { ...(palette[mode] || palette.light || {}) }
    : dark
      ? { canvas: '#121212', soft: '#181818', card: '#1e1e1e', raised: '#262626', border: '#333333',
          accent: '#d4714a', solid: '#c15f3c', hover: '#e08660' }
      : { canvas: '#fdfdfc', soft: '#f4efeb', card: '#ffffff', raised: '#f4f4f1', border: '#c8c5be',
          accent: '#c15f3c', solid: '#c15f3c', hover: '#a84e2e' }
  if (!colors.hover) colors.hover = blend(colors.solid || colors.accent || '#c15f3c', '#000000', .14)
  let textPrimary = dark ? '#f5f5f4' : '#17191d'
  let textSecondary = dark ? '#d0d3d8' : '#343a43'
  let textMuted = dark ? '#aeb6c1' : '#5a6370'
  let actionForeground = '#ffffff'
  if (custom || !palette) {
    // Keep the chosen brand colour on filled actions. Their labels and the
    // accent used for text can adapt independently to the selected surfaces.
    colors.solid = picked.accent
    if (!palette) {
      colors.card = picked.surface
      colors.soft = blend(picked.surface, '#000000', .04)
      colors.raised = blend(picked.surface, '#000000', .06)
    }
    const foreground = strongestForeground(colors.card)
    const backgroundTarget = foreground === '#ffffff' ? '#000000' : '#ffffff'
    // A dark custom card in Light mode cannot share text with a white canvas.
    // Adjust only derived surfaces that conflict; the chosen card stays exact.
    for (const key of ['canvas', 'soft', 'raised']) {
      if (contrastRatio(colors[key], foreground) < 4.5) {
        colors[key] = blend(colors.card, backgroundTarget, key === 'canvas' ? .04 : .06)
      }
    }
    const backgrounds = ['canvas', 'soft', 'card', 'raised'].map(key => colors[key])
    if (!backgrounds.every(background => contrastRatio(textPrimary, background) >= 4.5)) {
      textPrimary = readableOnSurfaces(themeForeground(colors.card), backgrounds, foreground)
    }
    textSecondary = readableOnSurfaces(textSecondary, backgrounds, foreground)
    textMuted = readableOnSurfaces(textMuted, backgrounds, foreground)
    colors.accent = readableOnSurfaces(palette ? colors.accent : picked.accent, backgrounds, foreground)
    actionForeground = readableColour(themeForeground(colors.solid), colors.solid, strongestForeground(colors.solid))
    colors.hover = readableColour(colors.hover, actionForeground, strongestForeground(actionForeground))
  }
  const defaultSidebar = picked.sidebar.toLowerCase() === '#f4efeb'
  const sidebar = dark
    ? (defaultSidebar ? (appearance.darkerSidebar ? '#121212' : '#181818') : (appearance.darkerSidebar ? blend(picked.sidebar, '#000000', .18) : picked.sidebar))
    : (appearance.darkerSidebar ? blend(picked.sidebar, '#000000', .18) : picked.sidebar)
  const sidebarText = themeForeground(sidebar)
  const sidebarMuted = readableColour(blend(sidebarText, sidebar, .16), sidebar, sidebarText)
  const sidebarSubSelection = softNavigationSelection(picked.selection, sidebar)
  const pageSelection = softNavigationSelection(picked.selection, colors.card)
  const sidebarHover = blend(sidebar, sidebarText, .1)
  const sidebarHoverText = readableColour(colors.accent, sidebarHover, strongestForeground(sidebarHover))
  const headerText = themeForeground(picked.surface)
  const sidebarEnd = blend(sidebar, picked.surface, .35)
  const surfaceEnd = blend(picked.surface, picked.accent, .2)
  const safeSidebarEnd = contrastRatio(sidebarText, sidebarEnd) >= 4.5 ? sidebarEnd : sidebar
  const safeSurfaceEnd = contrastRatio(headerText, surfaceEnd) >= 4.5 ? surfaceEnd : picked.surface
  return {
    mode,
    tokens: {
      '--accent': colors.accent,
      '--accent-light': colors.accent,
      '--accent-hover': colors.hover,
      '--accent-solid': colors.solid,
      '--accent-solid-hover': colors.hover,
      '--accent-contrast': actionForeground,
      '--accent-foreground': actionForeground,
      '--accent-dim': appearance.accent === 'terracotta'
        ? (dark ? 'rgba(212, 113, 74, 0.15)' : 'rgba(193, 95, 60, 0.10)')
        : `color-mix(in srgb, ${colors.accent} ${dark ? 16 : 10}%, transparent)`,
      '--accent-glow': appearance.accent === 'terracotta'
        ? (dark ? 'rgba(212, 113, 74, 0.08)' : 'rgba(193, 95, 60, 0.05)')
        : `color-mix(in srgb, ${colors.accent} ${dark ? 9 : 5}%, transparent)`,
      '--accent-muted': `color-mix(in srgb, ${colors.accent} ${dark ? 18 : 12}%, transparent)`,
      '--accent-soft': `color-mix(in srgb, ${colors.accent} ${dark ? 16 : 10}%, transparent)`,
      '--accent-subtle': `color-mix(in srgb, ${colors.accent} ${dark ? 16 : 10}%, transparent)`,
      '--accent-rgb': appearance.accent === 'terracotta'
        ? (dark ? '212, 113, 74' : '193, 95, 60')
        : (colors.accent ? colors.accent.slice(1).match(/../g).map(value => parseInt(value, 16)).join(', ') : '193, 95, 60'),
      '--accent-softer': `color-mix(in srgb, ${colors.accent} 5%, transparent)`,
      '--border-subtle': `color-mix(in srgb, ${colors.accent} 16%, transparent)`,
      '--shadow-accent': `0 0 0 1px color-mix(in srgb, ${colors.accent} 14%, transparent)`,
      '--bg': colors.canvas,
      '--bg-1': colors.soft,
      '--bg-2': colors.card,
      '--bg-3': dark ? colors.raised : colors.soft,
      '--bg-4': colors.raised,
      '--surface': colors.card,
      '--surface-hover': dark ? colors.raised : colors.soft,
      '--border': colors.border,
      '--border-strong': colors.border,
      '--border-focus': colors.accent,
      '--glass-bg': colors.card,
      '--glass-bg-hover': dark ? colors.raised : colors.soft,
      '--glass-border': colors.border,
      '--text-primary': textPrimary,
      '--text-secondary': textSecondary,
      '--text-muted': textMuted,
      '--text-inverse': custom || !palette ? themeForeground(textPrimary) : (dark ? '#17191d' : '#ffffff'),
      '--sidebar-bg': appearance.windowGradient ? `linear-gradient(160deg, ${sidebar}, ${safeSidebarEnd})` : sidebar,
      '--sidebar-surface': sidebar,
      '--sidebar-text': sidebarText,
      '--sidebar-muted': sidebarMuted,
      '--sidebar-hover': sidebarHover,
      '--sidebar-hover-text': sidebarHoverText,
      '--sidebar-border': blend(sidebar, sidebarText, .2),
      '--sidebar-active-bg-sub': sidebarSubSelection.background,
      '--sidebar-active-text-sub': sidebarSubSelection.foreground,
      '--page-selection-bg': pageSelection.background,
      '--page-selection-text': pageSelection.foreground,
      '--page-selection-border': pageSelection.border,
      '--sidebar-active-bg': picked.selection,
      '--sidebar-active-text': themeForeground(picked.selection),
      '--theme-surface': picked.surface,
      '--theme-chrome': appearance.windowGradient ? `linear-gradient(110deg, ${picked.surface}, ${safeSurfaceEnd})` : picked.surface,
      '--theme-chrome-text': headerText,
      '--theme-chrome-muted': readableColour(blend(headerText, picked.surface, .16), picked.surface, headerText),
    },
  }
}

export function applyAppearance(preference, systemDark = false, root = globalThis.document?.documentElement, user, storage = browserStorage()) {
  if (!root) return
  const appearance = normalizeAppearance(preference, user, storage)
  const { mode, tokens } = appearanceTokens(appearance, systemDark, user, storage)
  root.classList.toggle('dark-mode', mode === 'dark')
  root.dataset.appearance = mode
  root.dataset.accent = appearance.accent
  root.dataset.windowGradient = String(appearance.windowGradient)
  root.dataset.darkerSidebar = String(appearance.darkerSidebar)
  root.style.colorScheme = mode
  Object.entries(tokens).forEach(([name, value]) => root.style.setProperty(name, value))
}
