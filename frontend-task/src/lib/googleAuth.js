/**
 * lib/googleAuth.js
 * Google Identity Services (GSI) loader and button renderer for Field Team / Task app.
 */
export const GOOGLE_CLIENT_ID = import.meta.env?.VITE_GOOGLE_CLIENT_ID || '1076771386585-lt9gotlje2s5nrq509rokjngpufukuf0.apps.googleusercontent.com'

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
    }).catch(error => {
      scriptLoadingPromise = null
      document.querySelector('script[src="https://accounts.google.com/gsi/client"]')?.remove()
      throw error
    })
  }
  return scriptLoadingPromise
}

export async function renderGoogleButton(container, { onCredential, text = 'continue_with', width = 340 } = {}) {
  try {
    const google = await loadGoogleScript()
    if (!google?.accounts?.id || !container?.isConnected) return false

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
      width: Math.min(width, container.offsetWidth || width),
    })
    return true
  } catch {
    return false
  }
}
