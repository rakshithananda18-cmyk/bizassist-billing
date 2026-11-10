// lib/geo.js — one GPS fix for a field action.
//
// The server refuses every staff action without a fix, and refuses fixes worse
// than the owner's accuracy limit, so this asks the phone for a FRESH, HIGH
// accuracy reading (at most 5 s old) and reports failures in words an agent can act on.

export function batteryPct() {
  if (!navigator.getBattery) return Promise.resolve(undefined)
  return navigator.getBattery().then(b => Math.round(b.level * 100)).catch(() => undefined)
}

export function toFix(pos, battery) {
  const c = pos.coords
  return {
    lat: c.latitude,
    lng: c.longitude,
    accuracy: Math.round(c.accuracy * 10) / 10,
    speed: c.speed ?? undefined,
    heading: c.heading ?? undefined,
    client_time: new Date(pos.timestamp || Date.now()).toISOString(),
    battery,
  }
}

const ERR = {
  1: 'Location permission is blocked. Allow location for this site in browser settings, then retry.',
  2: 'Location unavailable. Turn on GPS / Location and retry.',
  3: 'Getting location took too long. Move to open sky and retry.',
}

export function getFix({ timeout = 20000 } = {}) {
  return new Promise((resolve, reject) => {
    if (!('geolocation' in navigator)) {
      reject(new Error('This browser cannot share location. Use Chrome on Android or Safari on iPhone.'))
      return
    }
    if (!window.isSecureContext) {
      reject(new Error('Location needs a secure (https) connection.'))
      return
    }
    navigator.geolocation.getCurrentPosition(
      async (pos) => resolve(toFix(pos, await batteryPct())),
      (err) => reject(new Error(ERR[err.code] || err.message || 'Could not get location.')),
      { enableHighAccuracy: true, maximumAge: 5000, timeout },
    )
  })
}

export function mapsDirectionsUrl(shop) {
  // Google Maps URLs need no API key and cost nothing; they open the Maps app.
  const dest = shop.lat != null ? `${shop.lat},${shop.lng}` : [shop.name, shop.address].filter(Boolean).join(', ')
  return `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(dest)}&travelmode=driving`
}


export function distanceBetweenM(lat1, lon1, lat2, lon2) {
  if (lat1 == null || lon1 == null || lat2 == null || lon2 == null) return null
  if ([lat1, lon1, lat2, lon2].some(value => String(value).trim() === '')) return null
  const numLat1 = Number(lat1), numLon1 = Number(lon1)
  const numLat2 = Number(lat2), numLon2 = Number(lon2)
  if (!Number.isFinite(numLat1) || !Number.isFinite(numLon1) || !Number.isFinite(numLat2) || !Number.isFinite(numLon2)) return null
  if (Math.abs(numLat1) > 90 || Math.abs(numLat2) > 90 || Math.abs(numLon1) > 180 || Math.abs(numLon2) > 180) return null
  const R = 6371000 // meters
  const dLat = (numLat2 - numLat1) * Math.PI / 180
  const dLon = (numLon2 - numLon1) * Math.PI / 180
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(numLat1 * Math.PI / 180) * Math.cos(numLat2 * Math.PI / 180) *
    Math.sin(dLon / 2) * Math.sin(dLon / 2)
  const bounded = Math.min(1, Math.max(0, a))
  const c = 2 * Math.atan2(Math.sqrt(bounded), Math.sqrt(1 - bounded))
  return Math.round(R * c)
}

export function formatDistance(meters) {
  if (meters == null || !Number.isFinite(Number(meters)) || Number(meters) < 0) return null
  if (meters < 1000) return `${meters} m`
  return `${(meters / 1000).toFixed(1)} km`
}

export function whatsappHref(phone, message = '') {
  if (!phone) return null
  const clean = String(phone).replace(/\D/g, '')
  if (!clean) return null
  const intl = clean.length === 10 ? `91${clean}` : clean
  return `https://wa.me/${intl}${message ? `?text=${encodeURIComponent(message)}` : ''}`
}

export function buildUpiUri({ vpa, payeeName = 'Stater Merchant', amount = 0, note = '' } = {}) {
  const payee = String(vpa || '').trim()
  const value = Number(amount)
  if (!/^[a-zA-Z0-9._-]+@[a-zA-Z0-9.-]+$/.test(payee) || !Number.isFinite(value) || value <= 0) return null
  const amt = value.toFixed(2)
  let uri = `upi://pay?pa=${encodeURIComponent(payee).replace('%40', '@')}&pn=${encodeURIComponent(payeeName)}&am=${amt}&cu=INR`
  if (note) uri += `&tn=${encodeURIComponent(note)}`
  return uri
}
