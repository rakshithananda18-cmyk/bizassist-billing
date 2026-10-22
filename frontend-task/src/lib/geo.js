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
