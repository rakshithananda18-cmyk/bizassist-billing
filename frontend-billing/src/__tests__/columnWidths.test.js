// Unit tests for lib/columnWidths — the pure half of the resizable-column
// feature (storage keying, clamping, sanitising, drag maths, auto-fit).
import { describe, it, expect, beforeEach } from 'vitest'
import {
  MIN_COLUMN_WIDTH, MAX_COLUMN_WIDTH, AUTOFIT_PADDING,
  storageKey, clampWidth, sanitizeWidths,
  loadWidths, saveWidths, clearWidths, nextWidth, autoFitWidth,
} from '../lib/columnWidths'

beforeEach(() => { localStorage.clear() })

describe('storageKey', () => {
  it('namespaces by user AND table so two users on one counter PC never collide', () => {
    expect(storageKey('stock.catalogue', 7)).not.toBe(storageKey('stock.catalogue', 8))
    expect(storageKey('stock.catalogue', 7)).not.toBe(storageKey('pos.cart', 7))
  })

  it('falls back to "anon" rather than throwing when there is no user', () => {
    expect(storageKey('t', null)).toContain('.anon.')
    expect(storageKey('t', undefined)).toContain('.anon.')
  })

  it('treats user id 0 as a real id, not as missing', () => {
    expect(storageKey('t', 0)).toContain('.0.')
  })
})

describe('clampWidth', () => {
  it('holds the floor and ceiling', () => {
    expect(clampWidth(1)).toBe(MIN_COLUMN_WIDTH)
    expect(clampWidth(99999)).toBe(MAX_COLUMN_WIDTH)
  })
  it('rounds to whole pixels', () => {
    expect(clampWidth(120.6)).toBe(121)
  })
  it('returns null for junk (meaning "leave on auto")', () => {
    expect(clampWidth(NaN)).toBeNull()
    expect(clampWidth('abc')).toBeNull()
    expect(clampWidth(undefined)).toBeNull()
  })
})

describe('sanitizeWidths', () => {
  it('drops columns that no longer exist in this app version', () => {
    expect(sanitizeWidths({ name: 200, ancient: 120 }, ['name', 'qty'])).toEqual({ name: 200 })
  })
  it('drops unusable values instead of persisting NaN', () => {
    expect(sanitizeWidths({ name: 'wide', qty: 80 })).toEqual({ qty: 80 })
  })
  it('survives a hand-mangled entry', () => {
    expect(sanitizeWidths(null)).toEqual({})
    expect(sanitizeWidths([1, 2, 3])).toEqual({})
    expect(sanitizeWidths('nope')).toEqual({})
  })
})

describe('load / save / clear', () => {
  it('round-trips', () => {
    saveWidths('t', 1, { name: 240 })
    expect(loadWidths('t', 1)).toEqual({ name: 240 })
  })

  it('removes the entry entirely when the map is empty (clean reset)', () => {
    saveWidths('t', 1, { name: 240 })
    saveWidths('t', 1, {})
    expect(localStorage.getItem(storageKey('t', 1))).toBeNull()
  })

  it('treats corrupt JSON as "no overrides" rather than throwing', () => {
    localStorage.setItem(storageKey('t', 1), '{not json')
    expect(loadWidths('t', 1)).toEqual({})
  })

  it('clearWidths wipes only that user+table', () => {
    saveWidths('t', 1, { name: 100 })
    saveWidths('t', 2, { name: 300 })
    clearWidths('t', 1)
    expect(loadWidths('t', 1)).toEqual({})
    expect(loadWidths('t', 2)).toEqual({ name: 300 })
  })
})

describe('nextWidth (drag maths)', () => {
  it('adds the pointer delta to the width the drag started from', () => {
    expect(nextWidth(200, 500, 560)).toBe(260)
    expect(nextWidth(200, 500, 440)).toBe(140)
  })
  it('never drags a column below the floor', () => {
    expect(nextWidth(100, 500, 0)).toBe(MIN_COLUMN_WIDTH)
  })
})

describe('autoFitWidth', () => {
  it('fits the widest measured cell plus padding', () => {
    expect(autoFitWidth([80, 150, 120])).toBe(150 + AUTOFIT_PADDING)
  })
  it('ignores non-numeric measurements', () => {
    expect(autoFitWidth([80, null, undefined, NaN])).toBe(80 + AUTOFIT_PADDING)
  })
  it('returns null when nothing could be measured', () => {
    expect(autoFitWidth([])).toBeNull()
    expect(autoFitWidth(null)).toBeNull()
  })
  it('still respects the ceiling for absurdly long content', () => {
    expect(autoFitWidth([99999])).toBe(MAX_COLUMN_WIDTH)
  })
})
