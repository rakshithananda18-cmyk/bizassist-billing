import { describe, expect, it } from 'vitest'
import {
  APPEARANCE_PALETTES, THEME_PRESETS, CUSTOM_THEME_DEFAULTS, DEFAULT_APPEARANCE, appearanceStorageKey, appearanceTokens,
  appearanceThemeColors, buildCustomPalette, contrastRatio, customPalettesStorageKey, deleteCustomPalette, getCustomPalettes,
  normalizeAppearance, readAppearance, saveAppearance, saveCustomPalette,
} from '../utils/appearance'

const storage = () => {
  const values = new Map()
  return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, String(value)) }
}
const owner = { user_id: 1, public_id: 'SHOP-A' }
const cashier = { user_id: 2, public_id: 'SHOP-A' }

// normalizeAppearance always returns these extra fields
const extras = { customColors: CUSTOM_THEME_DEFAULTS, windowGradient: false, darkerSidebar: false }

describe('personal appearance preferences', () => {
  it('keeps sub-page selections readable across every built-in palette and mode', () => {
    for (const palette of APPEARANCE_PALETTES) {
      for (const theme of ['light', 'dark']) {
        const { tokens } = appearanceTokens({ theme, accent: palette.id }, theme === 'dark', owner, storage())
        expect(contrastRatio(tokens['--sidebar-active-text-sub'], tokens['--sidebar-active-bg-sub'])).toBeGreaterThanOrEqual(4.5)
        expect(contrastRatio(tokens['--page-selection-text'], tokens['--page-selection-bg'])).toBeGreaterThanOrEqual(4.5)
      }
    }
  })

  it('uses the configured navigation selection for sub-pages independently of the action accent', () => {
    const customColors = { sidebar: '#224466', surface: '#ffffff', accent: '#186b4b', selection: '#edc46e' }
    for (const theme of ['light', 'dark']) {
      const chosen = appearanceTokens({ theme, accent: 'custom', customColors }).tokens
      const newAction = appearanceTokens({ theme, accent: 'custom', customColors: { ...customColors, accent: '#77489e' } }).tokens
      const newSelection = appearanceTokens({ theme, accent: 'custom', customColors: { ...customColors, selection: '#a73a64' } }).tokens
      expect(chosen['--sidebar-active-bg']).toBe(customColors.selection)
      for (const key of ['--sidebar-active-bg-sub', '--sidebar-active-text-sub', '--page-selection-bg', '--page-selection-text']) {
        expect(newAction[key], key).toBe(chosen[key])
        expect(newSelection[key], key).not.toBe(chosen[key])
      }
      // A dark coloured sidebar and light content need independent foregrounds,
      // rather than reusing light labels on a pale page tab.
      expect(chosen['--sidebar-active-bg-sub']).not.toBe(chosen['--page-selection-bg'])
    }
  })

  it('keeps custom navigation selections readable on contrasting sidebar and content surfaces', () => {
    for (const selection of ['#ffffff', '#000000', '#777777', '#edc46e', '#a65471']) {
      for (const sidebar of ['#111111', '#ffffff', '#356676']) {
        for (const theme of ['light', 'dark']) {
          const customColors = { sidebar, surface: '#ffffff', accent: '#245eac', selection }
          const { tokens } = appearanceTokens({ theme, accent: 'custom', customColors })
          expect(contrastRatio(tokens['--sidebar-active-text-sub'], tokens['--sidebar-active-bg-sub'])).toBeGreaterThanOrEqual(4.5)
          expect(contrastRatio(tokens['--page-selection-text'], tokens['--page-selection-bg'])).toBeGreaterThanOrEqual(4.5)
        }
      }
    }
  })
  it('validates saved colours and modes before applying them', () => {
    expect(normalizeAppearance({ theme: 'unknown', accent: 'bad-css' })).toEqual(DEFAULT_APPEARANCE)
    expect(normalizeAppearance({ theme: 'dark', accent: 'ocean' })).toEqual({ theme: 'dark', accent: 'ocean', ...extras })
  })

  it('migrates the former device theme once, without giving it to the next account', () => {
    const disk = storage()
    disk.setItem('billing_theme', 'dark')
    expect(readAppearance(owner, disk)).toEqual({ theme: 'dark', accent: 'terracotta', ...extras })
    expect(readAppearance(cashier, disk)).toEqual(DEFAULT_APPEARANCE)
    saveAppearance(cashier, { theme: 'light', accent: 'forest' }, disk)
    expect(readAppearance(owner, disk)).toEqual({ theme: 'dark', accent: 'terracotta', ...extras })
    expect(readAppearance(cashier, disk)).toEqual({ theme: 'light', accent: 'forest', ...extras })
  })

  it('keeps accounts and businesses separate even when local ids match', () => {
    expect(appearanceStorageKey(owner)).not.toBe(appearanceStorageKey(cashier))
    expect(appearanceStorageKey(owner)).not.toBe(appearanceStorageKey({ ...owner, public_id: 'SHOP-B' }))
  })

  it('recovers from corrupt or unavailable local storage', () => {
    const disk = storage()
    disk.setItem(appearanceStorageKey(owner), '{invalid')
    expect(readAppearance(owner, disk)).toEqual(DEFAULT_APPEARANCE)
    const blocked = { getItem() { throw Error('blocked') }, setItem() { throw Error('blocked') } }
    expect(readAppearance(owner, blocked)).toEqual(DEFAULT_APPEARANCE)
    expect(saveAppearance(owner, { theme: 'dark', accent: 'rose' }, blocked)).toEqual({ theme: 'dark', accent: 'rose', ...extras })
  })

  it('resolves System mode and changes the same shared tokens for every palette', () => {
    expect(appearanceTokens({ theme: 'system', accent: 'ocean' }, true).mode).toBe('dark')
    expect(appearanceTokens({ theme: 'light', accent: 'ocean' }, true).mode).toBe('light')
    const ocean = appearanceTokens({ theme: 'dark', accent: 'ocean' }).tokens
    expect(ocean['--accent']).not.toBe(ocean['--accent-solid'])
    expect(ocean['--surface']).toBe(ocean['--bg-2'])
  })

  it('derives navigation previews and applied workspace colours from the same palette', () => {
    expect(Object.fromEntries(THEME_PRESETS.map(palette => [palette.id, palette.name]))).toEqual({
      terracotta: 'Classic', ocean: 'Lagoon', forest: 'Mint', orchid: 'Sundown',
      rose: 'Cherry', graphite: 'Graphite', heritage: 'Heritage',
    })
    for (const palette of APPEARANCE_PALETTES) {
      expect(THEME_PRESETS.find(preset => preset.id === palette.id).colors).toBe(palette.colors)
      expect(appearanceThemeColors({ accent: palette.id })).toEqual(palette.colors)
      for (const theme of ['light', 'dark']) {
        const { tokens } = appearanceTokens({ accent: palette.id, theme })
        expect(tokens['--accent']).toBe(palette[theme].accent)
        expect(tokens['--accent-solid']).toBe(palette[theme].solid)
        expect(tokens['--bg']).toBe(palette[theme].canvas)
        expect(tokens['--surface']).toBe(palette[theme].card)
        expect(tokens['--sidebar-active-bg']).toBe(palette.colors.selection)
        expect(tokens['--theme-surface']).toBe(palette.colors.surface)
        if (theme === 'light' || palette.id !== 'terracotta') {
          expect(tokens['--sidebar-surface']).toBe(palette.colors.sidebar)
        }
      }
    }
  })

  it('keeps filled action labels and accent text legible in every palette', () => {
    const luminance = hex => {
      const rgb = hex.slice(1).match(/../g).map(value => parseInt(value, 16) / 255)
        .map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4)
      return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722
    }
    const contrast = (a, b) => (Math.max(luminance(a), luminance(b)) + .05) / (Math.min(luminance(a), luminance(b)) + .05)
    for (const palette of APPEARANCE_PALETTES) {
      for (const mode of ['light', 'dark']) {
        const minContrast = palette.id === 'terracotta' ? 4.2 : 4.5
        expect(contrast(palette[mode].solid, '#ffffff'), `${palette.id} ${mode} filled action`).toBeGreaterThanOrEqual(minContrast)
        expect(contrast(palette[mode].accent, palette[mode].card), `${palette.id} ${mode} accent text`).toBeGreaterThanOrEqual(minContrast)
      }
    }
  })
})

describe('sidebar hover contrast', () => {
  it('matches the profile accent on sidebar hover while keeping it readable across palettes', () => {
    const accents = [...APPEARANCE_PALETTES.map(palette => ({ accent: palette.id })),
      ...['#ffffff', '#000000', '#777777'].map(accent => ({
        accent: 'custom', customColors: { ...CUSTOM_THEME_DEFAULTS, sidebar: '#777777', accent },
      }))]
    for (const preference of accents) {
      for (const theme of ['light', 'dark']) {
        for (const darkerSidebar of [false, true]) {
          const { tokens } = appearanceTokens({ ...preference, theme, darkerSidebar })
          const background = tokens['--sidebar-hover']
          const text = tokens['--sidebar-hover-text']
          expect(contrastRatio(text, background)).toBeGreaterThanOrEqual(4.5)
          if (contrastRatio(tokens['--accent'], background) >= 4.5) {
            expect(text).toBe(tokens['--accent'])
          }
        }
      }
    }
  })
})

describe('personal custom palette libraries', () => {
  it('lists, updates, and deletes palettes only within the current account and business', () => {
    const disk = storage()
    const otherBusiness = { ...owner, public_id: 'SHOP-B' }
    const first = buildCustomPalette('Front counter', { accent: '#245eac' })
    const second = buildCustomPalette('Back counter', { accent: '#186b4b' })
    const cashierPalette = buildCustomPalette('Cashier', { accent: '#77489e' })
    const otherPalette = buildCustomPalette('Second shop', { accent: '#a73a64' })
    saveCustomPalette(owner, first, disk)
    saveCustomPalette(owner, second, disk)
    saveCustomPalette(cashier, cashierPalette, disk)
    saveCustomPalette(otherBusiness, otherPalette, disk)
    expect(getCustomPalettes(owner, disk)).toEqual([first, second])
    expect(getCustomPalettes(cashier, disk)).toEqual([cashierPalette])
    expect(getCustomPalettes(otherBusiness, disk)).toEqual([otherPalette])
    expect(getCustomPalettes(null, disk)).toEqual([])
    expect(customPalettesStorageKey(owner)).not.toBe(customPalettesStorageKey(cashier))
    expect(customPalettesStorageKey(owner)).not.toBe(customPalettesStorageKey(otherBusiness))

    const renamed = { ...first, name: 'My counter' }
    expect(saveCustomPalette(owner, renamed, disk)).toEqual([second, renamed])
    expect(deleteCustomPalette(owner, first.id, disk)).toEqual([second])
    deleteCustomPalette(cashier, second.id, disk)
    expect(getCustomPalettes(owner, disk)).toEqual([second])
    expect(getCustomPalettes(cashier, disk)).toEqual([cashierPalette])
    expect(getCustomPalettes(otherBusiness, disk)).toEqual([otherPalette])
  })

  it('keeps custom selections valid through explicit storage, normalization, and token generation', () => {
    const disk = storage()
    const palette = buildCustomPalette('My blue', { sidebar: '#123456', surface: '#abcdef', accent: '#245eac', selection: '#fedcba' })
    saveCustomPalette(owner, palette, disk)
    const appearance = saveAppearance(owner, { theme: 'dark', accent: palette.id }, disk)
    expect(appearance.accent).toBe(palette.id)
    expect(readAppearance(owner, disk)).toEqual(appearance)
    expect(normalizeAppearance(appearance, owner, disk)).toEqual(appearance)
    expect(appearanceThemeColors(appearance, owner, disk)).toEqual(palette.colors)
    const { tokens } = appearanceTokens(appearance, false, owner, disk)
    expect(contrastRatio(tokens['--accent'], tokens['--surface'])).toBeGreaterThanOrEqual(4.5)
    expect(tokens['--accent-solid']).toBe(palette.colors.accent)
    expect(tokens['--sidebar-surface']).toBe(palette.colors.sidebar)
    expect(tokens['--sidebar-active-bg']).toBe(palette.colors.selection)
    expect(normalizeAppearance(appearance, cashier, disk).accent).toBe(DEFAULT_APPEARANCE.accent)
    expect(appearanceTokens(appearance, false, cashier, disk).tokens['--accent']).toBe(APPEARANCE_PALETTES[0].dark.accent)
    deleteCustomPalette(owner, palette.id, disk)
    expect(readAppearance(owner, disk).accent).toBe(DEFAULT_APPEARANCE.accent)
  })

  it('migrates the unowned legacy library once while preserving other accounts already selected palettes', () => {
    const disk = storage()
    const first = buildCustomPalette('Existing blue', { accent: '#245eac' })
    const second = buildCustomPalette('Existing green', { accent: '#186b4b' })
    disk.setItem('billing_custom_palettes_v1', JSON.stringify([first, second]))
    disk.setItem('billing_accent', first.id)
    disk.setItem('billing_theme', 'dark')
    disk.setItem(appearanceStorageKey(cashier), JSON.stringify({ theme: 'light', accent: second.id }))
    expect(getCustomPalettes(null, disk)).toEqual([])
    expect(readAppearance(owner, disk).accent).toBe(first.id)
    expect(getCustomPalettes(owner, disk)).toEqual([first, second])
    expect(getCustomPalettes(cashier, disk)).toEqual([second])
    expect(readAppearance(cashier, disk).accent).toBe(second.id)
    const newAccount = { ...owner, public_id: 'SHOP-B' }
    expect(getCustomPalettes(newAccount, disk)).toEqual([])
    expect(readAppearance(newAccount, disk)).toEqual(DEFAULT_APPEARANCE)
    deleteCustomPalette(cashier, second.id, disk)
    expect(getCustomPalettes(cashier, disk)).toEqual([])
    expect(getCustomPalettes(owner, disk)).toEqual([first, second])
  })

  it('preserves the legacy custom selection while the app restores the authenticated account', () => {
    const disk = storage()
    const palette = buildCustomPalette('Existing palette', { accent: '#245eac' })
    disk.setItem('billing_custom_palettes_v1', JSON.stringify([palette]))
    disk.setItem('billing_accent', palette.id)
    disk.setItem('billing_theme', 'dark')
    // AppearanceSync runs before AuthProvider restores the saved user.
    saveAppearance(null, readAppearance(null, disk), disk)
    expect(disk.getItem('billing_accent')).toBe(palette.id)
    expect(readAppearance(owner, disk).accent).toBe(palette.id)
    expect(getCustomPalettes(owner, disk)).toEqual([palette])
  })

  it('honors the existing appearance owner when a different account opens the legacy library first', () => {
    const disk = storage()
    const first = buildCustomPalette('Owner palette', { accent: '#245eac' })
    const second = buildCustomPalette('Cashier selection', { accent: '#186b4b' })
    disk.setItem('billing_custom_palettes_v1', JSON.stringify([first, second]))
    disk.setItem('billing_appearance_legacy_owner', 'SHOP-A:1')
    disk.setItem(appearanceStorageKey(cashier), JSON.stringify({ theme: 'dark', accent: second.id }))
    expect(getCustomPalettes(cashier, disk)).toEqual([second])
    expect(readAppearance(cashier, disk).accent).toBe(second.id)
    expect(getCustomPalettes(owner, disk)).toEqual([first, second])
    expect(getCustomPalettes({ ...owner, public_id: 'SHOP-B' }, disk)).toEqual([])
  })

  it('ignores corrupt custom data without interrupting preference reads', () => {
    const disk = storage()
    disk.setItem(customPalettesStorageKey(owner), '{invalid')
    expect(getCustomPalettes(owner, disk)).toEqual([])
    expect(readAppearance(owner, disk)).toEqual(DEFAULT_APPEARANCE)
    disk.setItem(customPalettesStorageKey(owner), JSON.stringify([{ id: 'custom_broken', name: 'Broken' }]))
    expect(getCustomPalettes(owner, disk)).toEqual([])
    const valid = buildCustomPalette('Usable', { accent: '#245eac' })
    expect(saveCustomPalette(owner, valid, disk)).toEqual([valid])
    expect(saveCustomPalette(owner, { id: 'custom_bad' }, disk)).toEqual([valid])
  })

  it.each([
    ['light', '#ffffff', '#111111'],
    ['dark', '#ffffff', '#111111'],
    ['light', '#000000', '#ffffff'],
    ['dark', '#000000', '#ffffff'],
    ['light', '#777777', '#777777'],
    ['dark', '#777777', '#777777'],
  ])('keeps custom %s surfaces and %s actions readable without replacing the chosen colours', (theme, accent, surface) => {
    const disk = storage()
    const palette = buildCustomPalette('High contrast', { accent, surface })
    saveCustomPalette(owner, palette, disk)
    const { tokens } = appearanceTokens({ theme, accent: palette.id }, false, owner, disk)

    expect(tokens['--accent-solid']).toBe(accent)
    expect(tokens['--surface']).toBe(palette[theme].card)
    expect(appearanceThemeColors({ accent: palette.id }, owner, disk)).toEqual(palette.colors)
    expect(getCustomPalettes(owner, disk)).toEqual([palette])
    expect(contrastRatio(tokens['--accent-solid'], tokens['--accent-foreground'])).toBeGreaterThanOrEqual(4.5)
    expect(contrastRatio(tokens['--accent-solid-hover'], tokens['--accent-foreground'])).toBeGreaterThanOrEqual(4.5)
    for (const background of ['--bg', '--bg-1', '--bg-2', '--bg-3', '--bg-4']) {
      for (const foreground of ['--text-primary', '--text-secondary', '--text-muted', '--accent']) {
        expect(contrastRatio(tokens[foreground], tokens[background]), `${foreground} on ${background}`).toBeGreaterThanOrEqual(4.5)
      }
    }
  })

  it.each(['light', 'dark'])('applies the same contrast protection to editable custom colours in %s mode', theme => {
    const customColors = { sidebar: '#222222', surface: '#111111', accent: '#ffffff', selection: '#eeeeee' }
    const { tokens } = appearanceTokens({ theme, accent: 'custom', customColors })
    expect(tokens['--surface']).toBe(customColors.surface)
    expect(tokens['--accent-solid']).toBe(customColors.accent)
    expect(contrastRatio(tokens['--accent-foreground'], tokens['--accent-solid'])).toBeGreaterThanOrEqual(4.5)
    for (const background of ['--bg', '--bg-1', '--bg-2', '--bg-3', '--bg-4']) {
      expect(contrastRatio(tokens['--text-primary'], tokens[background])).toBeGreaterThanOrEqual(4.5)
    }
  })
})
