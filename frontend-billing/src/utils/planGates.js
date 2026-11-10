/** Unknown plans never start timers or show upgrade prompts. Older APIs keep their legacy gate. */
export function planGate(subscription, name) {
  if (typeof subscription?.plan !== 'string') return false
  return subscription.gates?.[name] ?? subscription.plan !== 'pro'
}

export function previewTimerKey(user) {
  return `bizassist_preview_start:${user?.public_id || ''}:${user?.user_id || user?.id || ''}`
}
