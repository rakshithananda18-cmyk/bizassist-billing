// lib/tracker.js — the on-duty GPS trail.
//
// While the agent is checked in and the app is OPEN, the phone's position is
// watched and one point per `intervalS` is sent to /api/track/pings. Points
// that cannot be sent (no network) are kept in localStorage and replayed in
// order when the connection returns.
//
// Hard limit of a web app: when the screen locks or the app goes to the
// background, the browser pauses GPS. The "keep screen on" switch (Screen Wake
// Lock API) keeps the trail alive while the phone sits in a holder; a pocketed
// phone leaves gaps, and each field action still carries its own fix.
import { api, tokenStore } from './api'
import { batteryPct, toFix } from './geo'

const BUFFER_KEY = 'task_ping_buffer'
export const MAX_BUFFER = 120

export class PingBuffer {
  constructor(storage = globalThis.localStorage, key = BUFFER_KEY) {
    this.storage = storage
    this.key = key
  }
  read() {
    try {
      const items = JSON.parse(this.storage?.getItem(this.key) || '[]')
      return Array.isArray(items) ? items : []
    } catch { return [] }
  }
  write(items) {
    try { this.storage?.setItem(this.key, JSON.stringify(items)) } catch { /* quota / private mode */ }
  }
  push(fix) {
    const items = this.read()
    items.push(fix)
    // Oldest points are dropped first when the phone was offline a long time.
    this.write(items.slice(-MAX_BUFFER))
  }
  take() {
    const items = this.read()
    this.write([])
    return items
  }
  putBack(items) {
    this.write([...items, ...this.read()].slice(-MAX_BUFFER))
  }
  size() { return this.read().length }
}

export class Tracker {
  constructor({ onStatus, scope } = {}) {
    // A device may serve several workers/businesses. Legacy unowned points
    // cannot safely be attributed to the next person signing in.
    this.buffer = new PingBuffer(undefined, `${BUFFER_KEY}:${encodeURIComponent(scope || 'unscoped')}`)
    this.sessionToken = tokenStore.get()
    this.watchId = null
    this.timer = null
    this.latest = null
    this.lastSentAt = 0
    this.onStatus = onStatus || (() => {})
    this.wakeLock = null
    this.wantWake = false
    this._onVisible = () => {
      if (document.visibilityState === 'visible') {
        this.flush()
        if (this.wantWake) this.keepAwake(true)
      }
    }
    this._onOnline = () => this.flush()
  }

  start(intervalS = 60) {
    this.stop()
    this.intervalMs = Math.max(15, intervalS) * 1000
    if (!('geolocation' in navigator)) { this.onStatus({ state: 'unsupported' }); return }
    this.watchId = navigator.geolocation.watchPosition(
      async (pos) => {
        this.latest = toFix(pos, await batteryPct())
        this.onStatus({ state: 'tracking', fix: this.latest, buffered: this.buffer.size() })
      },
      (err) => this.onStatus({ state: 'error', message: err.message, code: err.code }),
      { enableHighAccuracy: true, maximumAge: 10000, timeout: 30000 },
    )
    this.timer = setInterval(() => this.tick(), this.intervalMs)
    document.addEventListener('visibilitychange', this._onVisible)
    window.addEventListener('online', this._onOnline)
  }

  stop() {
    if (this.watchId != null) navigator.geolocation.clearWatch(this.watchId)
    if (this.timer) clearInterval(this.timer)
    this.watchId = null
    this.timer = null
    document.removeEventListener('visibilitychange', this._onVisible)
    window.removeEventListener('online', this._onOnline)
  }

  tick() {
    if (!this.latest) { this.flush(); return }
    const t = new Date(this.latest.client_time).getTime()
    if (t <= this.lastSentAt) { this.flush(); return } // retry queued points even with no new fix
    this.lastSentAt = t
    this.buffer.push(this.latest)
    this.flush()
  }

  async flush() {
    if (this.flushing || !navigator.onLine || tokenStore.get() !== this.sessionToken) return
    const items = this.buffer.take()
    if (!items.length) return
    this.flushing = true
    let sent = 0
    try {
      for (let i = 0; i < items.length; i += 100) {
        if (tokenStore.get() !== this.sessionToken) {
          this.buffer.putBack(items.slice(sent))
          return
        }
        await api.post('/api/track/pings', { pings: items.slice(i, i + 100) })
        sent = Math.min(items.length, i + 100)
      }
      this.onStatus({ state: 'tracking', fix: this.latest, buffered: 0, sentAt: Date.now() })
    } catch (e) {
      const retryable = e.status === 0 || e.status === 408 || e.status === 429 || e.status >= 500
      // Preserve unsent evidence in its ORIGINAL identity scope after an account
      // switch; that scope is never loaded by the newly signed-in person.
      if (retryable || tokenStore.get() !== this.sessionToken) this.buffer.putBack(items.slice(sent))
      this.onStatus({ state: 'tracking', fix: this.latest, buffered: this.buffer.size(), error: e.message })
    } finally {
      this.flushing = false
    }
  }

  async keepAwake(on) {
    this.wantWake = on
    try {
      if (on && 'wakeLock' in navigator) {
        this.wakeLock = await navigator.wakeLock.request('screen')
        return true
      }
      if (!on && this.wakeLock) { await this.wakeLock.release(); this.wakeLock = null }
    } catch { /* denied (battery saver) — nothing else to do */ }
    return false
  }
}
