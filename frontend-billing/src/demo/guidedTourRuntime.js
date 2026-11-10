export const TOUR_CHAPTERS = ['home', 'dashboard', 'pos', 'stock', 'purchases', 'contacts']

export function isEmbeddedGuidedTour(location = window.location, framed = window.parent !== window) {
  const params = new URLSearchParams(location.search)
  return framed && ['1', 'true'].includes(params.get('demo')) && params.get('embed') === '1' && params.get('tour') === '1'
}

export function isAllowedTourOrigin(origin, configuredUrl) {
  try {
    const url = new URL(origin)
    if (url.origin !== origin) return false
    if (['localhost', '127.0.0.1'].includes(url.hostname) && ['http:', 'https:'].includes(url.protocol)) return true
    if (['https://staterbill.com', 'https://www.staterbill.com'].includes(origin)) return true
    return Boolean(configuredUrl && new URL(configuredUrl).origin === origin)
  } catch { return false }
}

export function isTourCommand(data) {
  return data?.type === 'stater-tour:command' && ['play', 'pause', 'chapter', 'sandbox', 'restart'].includes(data.command) &&
    (data.command !== 'chapter' || TOUR_CHAPTERS.includes(data.chapter))
}

// Time advances only while playing. The same gate is used immediately before
// DOM actions, so a paused tour cannot keep typing or click a pending target.
export class TourClock {
  constructor({ active, cancelled, tick = 50 }) {
    this.active = active
    this.cancelled = cancelled
    this.tick = tick
  }

  async wait(milliseconds, onTick) {
    let elapsed = 0
    let previous = performance.now()
    let wasActive = this.active()
    while (elapsed < milliseconds || !this.active()) {
      if (this.cancelled()) throw new Error('tour-cancelled')
      await new Promise(resolve => setTimeout(resolve, this.tick))
      if (this.cancelled()) throw new Error('tour-cancelled')
      const now = performance.now()
      const active = this.active()
      if (active && wasActive) elapsed += Math.min(now - previous, this.tick * 2)
      previous = now
      wasActive = active
      onTick?.(Math.min(1, elapsed / milliseconds))
    }
    if (this.cancelled()) throw new Error('tour-cancelled')
  }

  async gate() { await this.wait(0) }
}
