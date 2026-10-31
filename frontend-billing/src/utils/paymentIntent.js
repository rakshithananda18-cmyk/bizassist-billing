import { newClientRequestId } from '../sync/uuid'
import { getApiBase } from '../config'

// Keep ambiguous money submissions retryable across a tab reload. A confirmed
// response clears the key; a new acknowledged intent receives a fresh key.
export function paymentIntent(path, payload) {
  let owner = {}
  try { owner = JSON.parse(localStorage.getItem('billing_user') || '{}') } catch { /* no stored session */ }
  const identity = owner.public_id || owner.username || owner.id || 'session'
  const storageKey = `bizassist_payment_intent:${getApiBase?.() || ''}:${identity}:${path}:${JSON.stringify(payload)}`
  let key = sessionStorage.getItem(storageKey)
  if (!key) { key = newClientRequestId(); sessionStorage.setItem(storageKey, key) }
  return { key, clear: () => sessionStorage.removeItem(storageKey) }
}
