const STORAGE_KEY = 'stater_storage_consent'
export const STORAGE_CONSENT_CHANGED = 'stater-storage-consent-changed'
export const OPEN_STORAGE_PREFERENCES = 'stater-open-storage-preferences'
export const STORAGE_CONSENT_KEY = STORAGE_KEY
let volatileConsent = null
let sessionOverride = false

export function readStorageConsent() {
  if (sessionOverride) return volatileConsent
  let raw
  try { raw = localStorage.getItem(STORAGE_KEY) } catch { return volatileConsent }
  try {
    const value = JSON.parse(raw || 'null')
    volatileConsent = value?.version === 1 && value.essential === true && typeof value.diagnostics === 'boolean'
      ? value : null
    return volatileConsent
  } catch {
    volatileConsent = null
    return null
  }
}

export function diagnosticsAllowed() {
  return readStorageConsent()?.diagnostics === true
}

export function saveStorageConsent(diagnostics) {
  const value = { version: 1, essential: true, diagnostics: diagnostics === true, savedAt: new Date().toISOString() }
  volatileConsent = value
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(value))
    sessionOverride = false
  } catch {
    // Reads may still work when writes fail (for example at storage quota).
    // Honor this session's latest choice instead of restoring an older opt-in.
    sessionOverride = true
    if (!value.diagnostics) {
      // Removing a stale opt-in can still succeed when storage is full. A
      // reload then defaults diagnostics off and asks for a fresh choice.
      try { localStorage.removeItem(STORAGE_KEY) } catch { /* Keep the in-memory refusal. */ }
    }
  }
  if (!value.diagnostics) {
    try { localStorage.removeItem('web_device_id') } catch { /* Browser storage can be unavailable. */ }
  }
  window.dispatchEvent(new CustomEvent(STORAGE_CONSENT_CHANGED, { detail: value }))
  return value
}

export function openStoragePreferences() {
  window.dispatchEvent(new CustomEvent(OPEN_STORAGE_PREFERENCES))
}
