// The index is hand-written, so this is what stops it rotting.
//
// A curated list was the honest choice — runtime scraping needs Settings mounted
// and authenticated, and build-time AST extraction is a codegen step plus a
// dependency that still cannot infer which tab a row sits in without tracking
// the enclosing `activeTab === '...'` conditional. The cost of writing it down
// is that Settings.jsx moves on without it. So this reads the real file.
//
// The third assertion is the one that matters most: a row that MOVES between
// tabs produces a deep link that silently lands on the wrong tab and scrolls to
// nothing — no error, no clue.
import fs from 'fs'
import path from 'path'
import { describe, it, expect } from 'vitest'
import { PAGE_INDEX, SETTINGS_INDEX, matchPages, matchSettings, settingsRoute } from '../config/searchIndex'

const read = (p) => fs.readFileSync(path.resolve(__dirname, p), 'utf-8')
const settingsSrc = read('../pages/Settings.jsx')
const appSrc = read('../App.jsx')

/** Every `id="set-*"` in Settings.jsx, with the tab whose block encloses it. */
function scrapeSettingRows() {
  const lines = settingsSrc.split('\n')
  const found = []
  let tab = null
  for (const line of lines) {
    const t = line.match(/activeTab === '([a-z]+)'/)
    if (t) tab = t[1]
    const id = line.match(/id="set-([A-Za-z0-9_]+)"/)
    if (id) found.push({ tab, key: id[1] })
  }
  return found
}

describe('settings search index', () => {
  const scraped = scrapeSettingRows()

  it('indexes only fields that still exist', () => {
    // Catches a renamed or deleted SettingRow — the link would 404 into nothing.
    const live = new Set(scraped.map(r => r.key))
    for (const entry of SETTINGS_INDEX) {
      expect(live.has(entry.key), `indexed "${entry.key}" no longer exists in Settings.jsx`).toBe(true)
    }
  })

  it('indexes every deep-linkable field', () => {
    // The half that stops rot: a new SettingRow with an id must be added here,
    // or it is invisible to search forever and nobody finds out.
    const indexed = new Set(SETTINGS_INDEX.map(e => e.key))
    for (const row of scraped) {
      expect(indexed.has(row.key),
        `Settings.jsx has id="set-${row.key}" but searchIndex.js does not list it`).toBe(true)
    }
  })

  it('records the tab each field actually lives in', () => {
    // A row moved between tabs still deep-links — to the WRONG tab, where
    // jumpToSetting finds no element and does nothing. Silent, so it needs a test.
    const actual = Object.fromEntries(scraped.map(r => [r.key, r.tab]))
    for (const entry of SETTINGS_INDEX) {
      expect(entry.tab, `"${entry.key}" is on the "${actual[entry.key]}" tab, indexed as "${entry.tab}"`)
        .toBe(actual[entry.key])
    }
  })

  it('builds the deep link Settings.jsx knows how to read', () => {
    expect(settingsRoute({ tab: 'print', key: 'print_logo' }))
      .toBe('/settings?tab=print&field=print_logo')
  })
})

describe('page index', () => {
  it('points only at routes the app declares', () => {
    // A typo here is a result that navigates to the catch-all redirect.
    for (const page of PAGE_INDEX) {
      const base = page.route.split('?')[0]
      const top = '/' + (base.split('/')[1] || '')
      const declared = appSrc.includes(`path="${base}"`) ||
                       appSrc.includes(`path="${top}"`) ||
                       appSrc.includes(`path="${top}/:`) ||
                       base === '/'
      expect(declared, `no route in App.jsx matches "${page.route}"`).toBe(true)
    }
  })
})

describe('matching', () => {
  it('finds a page by a word that is not in its title', () => {
    // "gst" must reach Reports; a shop owner does not know the page is called
    // "GST & Tax Reports" before they find it.
    const labels = matchPages('gst').map(p => p.label)
    expect(labels).toContain('GST Summary')
  })

  it('finds a settings field by name', () => {
    expect(matchSettings('logo').map(s => s.key)).toContain('print_logo')
  })

  it('offers a cashier nothing they cannot open', () => {
    // An owner-only result is a dead end for a cashier — the page refuses them.
    expect(matchPages('gst', { isCashier: true })).toEqual([])
    expect(matchSettings('logo', { isCashier: true })).toEqual([])
  })

  it('returns nothing for an empty query', () => {
    for (const q of ['', '   ', null, undefined]) {
      expect(matchPages(q)).toEqual([])
      expect(matchSettings(q)).toEqual([])
    }
  })
})
