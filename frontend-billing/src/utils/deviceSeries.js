const keyFor = (publicId, backend) => `billing_device_series:${encodeURIComponent(backend)}:${publicId}`
const valid = value => typeof value === 'string' && /^[0-9A-Z]{3}$/.test(value)

export function rememberDeviceSeries(publicId, backend, value) {
  if (!publicId || !valid(value)) return
  try { localStorage.setItem(keyFor(publicId, backend), value) } catch {}
}

export function readDeviceSeries(publicId, backend) {
  if (!publicId) return null
  try {
    const value = localStorage.getItem(keyFor(publicId, backend))
    return valid(value) ? value : null
  } catch { return null }
}
