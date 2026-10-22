// lib/coords.js — pull "lat,lng" out of what an owner is likely to paste:
// plain coordinates, or a full Google Maps link. Short links (maps.app.goo.gl)
// cannot be expanded from the browser; open them and copy the coordinates.
const PATTERNS = [
  /!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)/,              // place data
  /@(-?\d+\.\d+),(-?\d+\.\d+)/,                    // map view
  /[?&](?:q|ll|query|destination)=(-?\d+\.\d+)(?:,|%2C)\s*(-?\d+\.\d+)/i,
  /^\s*(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)\s*$/, // "12.97, 77.59"
]

export function parseCoords(text) {
  if (!text) return null
  for (const re of PATTERNS) {
    const m = re.exec(text)
    if (m) {
      const lat = Number(m[1]), lng = Number(m[2])
      if (Math.abs(lat) <= 90 && Math.abs(lng) <= 180 && !(lat === 0 && lng === 0)) return { lat, lng }
    }
  }
  return null
}
