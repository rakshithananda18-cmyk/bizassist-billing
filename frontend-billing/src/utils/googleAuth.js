/**
 * utils/googleAuth.js
 * Google Identity Services (GSI) loader and button renderer.
 */
import { GOOGLE_CLIENT_ID } from '../config'

let scriptLoadingPromise = null
let isGoogleInitialized = false
let activeCredentialCallback = null

export function loadGoogleScript() {
  if (typeof window === 'undefined') return Promise.reject(new Error('Window not available'))
  if (window.google?.accounts?.id) return Promise.resolve(window.google)

  if (!scriptLoadingPromise) {
    scriptLoadingPromise = new Promise((resolve, reject) => {
      const script = document.createElement('script')
      script.src = 'https://accounts.google.com/gsi/client'
      script.async = true
      script.defer = true
      script.onload = () => {
        if (window.google?.accounts?.id) {
          resolve(window.google)
        } else {
          reject(new Error('Google Identity Services script loaded but accounts.id unavailable'))
        }
      }
      script.onerror = () => reject(new Error('Failed to load Google Identity Services SDK'))
      document.head.appendChild(script)
    })
  }
  return scriptLoadingPromise
}

export async function renderGoogleButton(container, { onCredential, text = 'continue_with', width = 340 } = {}) {
  try {
    const google = await loadGoogleScript()
    if (!google?.accounts?.id || !container) return false

    activeCredentialCallback = onCredential

    if (!isGoogleInitialized) {
      google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: (res) => {
          if (res?.credential && activeCredentialCallback) {
            activeCredentialCallback(res.credential)
          }
        },
      })
      isGoogleInitialized = true
    }

    container.innerHTML = ''
    google.accounts.id.renderButton(container, {
      theme: 'outline',
      size: 'large',
      text,
      shape: 'rectangular',
      logo_alignment: 'left',
      width: Math.min(width, container.offsetWidth || 340),
    })
    return true
  } catch (err) {
    console.warn('[GOOGLE_AUTH] Could not render Google Sign-In button:', err?.message)
    return false
  }
}
