export function trustedHandoff(event, { billingUrl, opener = window.opener } = {}) {
  if (!event.source || !opener || event.source !== opener) return false
  const origins = [window.location.origin, 'https://staterbill.com', 'https://www.staterbill.com', 'https://bizassist-billing.vercel.app', ...(billingUrl || '').split(',')]
  if (['localhost', '127.0.0.1'].includes(window.location.hostname) || /^192\.168\.|^10\.|^172\.(1[6-9]|2\d|3[01])\./.test(window.location.hostname)) {
    origins.push(`http://${window.location.hostname}:5174`, `http://${window.location.hostname}:8450`)
  }
  return origins.some(url => { try { const parsed = new URL(url.trim()); return ['http:', 'https:'].includes(parsed.protocol) && !parsed.username && !parsed.password && parsed.origin === event.origin } catch { return false } })
}
