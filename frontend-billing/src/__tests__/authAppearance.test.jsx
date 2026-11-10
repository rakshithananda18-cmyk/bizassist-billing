import { describe, expect, it } from 'vitest'
import { applyAppearance } from '../utils/appearance'

const storage = () => ({ getItem: () => null, setItem: () => {} })

describe('sign-in and registration appearance', () => {
  it.each([
    ['/login', 'dark', false, 'dark'],
    ['/register', 'dark', false, 'dark'],
    ['/login', 'light', true, 'light'],
    ['/register', 'system', true, 'dark'],
    ['/privacy', 'dark', true, 'light'],
  ])('honors %s appearance while keeping public reading pages light', (path, theme, systemDark, expected) => {
    const previousPath = window.location.href
    const root = document.createElement('div')
    try {
      window.history.replaceState({}, '', path)
      applyAppearance({ theme, accent: 'terracotta' }, systemDark, root, null, storage())
      expect(root.dataset.appearance).toBe(expected)
      expect(root.classList.contains('dark-mode')).toBe(expected === 'dark')
    } finally {
      window.history.replaceState({}, '', previousPath)
    }
  })
})

