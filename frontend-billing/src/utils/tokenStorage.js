/**
 * src/utils/tokenStorage.js — OS-backed secure token storage adapter.
 * Uses OS-backed secure store (Electron safeStorage / DPAPI / Keychain) when available on desktop,
 * with graceful fallback to browser localStorage for web/LAN mode.
 */

export const tokenStorage = {
  getItem(key) {
    try {
      if (typeof window !== 'undefined' && window.bizassistDesktop?.secureStorage?.getItemSync) {
        const val = window.bizassistDesktop.secureStorage.getItemSync(key)
        if (val !== undefined && val !== null) return val
      }
      return localStorage.getItem(key)
    } catch {
      return null
    }
  },

  setItem(key, value) {
    try {
      if (typeof window !== 'undefined' && window.bizassistDesktop?.secureStorage?.setItemSync) {
        window.bizassistDesktop.secureStorage.setItemSync(key, value)
      }
      localStorage.setItem(key, value)
    } catch { /* fallback ignore */ }
  },

  removeItem(key) {
    try {
      if (typeof window !== 'undefined' && window.bizassistDesktop?.secureStorage?.removeItemSync) {
        window.bizassistDesktop.secureStorage.removeItemSync(key)
      }
      localStorage.removeItem(key)
    } catch { /* fallback ignore */ }
  }
}
