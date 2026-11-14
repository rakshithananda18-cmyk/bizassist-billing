import { runAsync } from '../utils/asyncAction'
// src/hooks/useBillingProfile.js — the billing-counter profile (plan Phase 2).
// ============================================================================
// Fetches GET /business/billing-profile (entry mode, customer gating, line
// fields, counter widgets, invoice default) resolved from the business's
// vertical template(s).
//
// COUNTER MODE (multi-type businesses): the device's selected mode is sticky in
// localStorage ('pos.counter_mode'). `useBillingProfile()` with no argument
// follows it live (a 'bizassist:counter-mode' event re-renders every consumer —
// PosTopBar switcher, CheckoutModal gating, etc.). An explicit `mode` argument
// always wins (used to preview a specific vertical).
//
// FAIL-OPEN: if the endpoint is unreachable (offline-first reality), profile is
// null and callers must apply NO restrictions — billing never blocks on config.
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { logger } from '../utils/logger'
import { getApiBase } from '../config'

const MODE_STORAGE_KEY = 'pos.counter_mode'
const MODE_EVENT = 'bizassist:counter-mode'

const _cache = new Map()          // `${tenantScope}:${effective}` → profile
const _inflight = new Map()       // `${tenantScope}:${effective}` → Promise
let generation = 0
const SESSION_EVENT = 'bizassist:session-changed'

function getTenantScope() {
  try {
    const raw = localStorage.getItem('billing_user')
    if (raw) {
      const u = JSON.parse(raw)
      return `${getApiBase?.() || ''}|${u.public_id || u.business_id || u.id || 'anon'}|${u.user_id || u.id || ''}`
    }
  } catch {
    // ignore
  }
  return 'anon'
}

export function getCounterMode() {
  try { return localStorage.getItem(MODE_STORAGE_KEY) || null } catch { return null }
}

/** Set (or clear with null) the device's sticky counter mode and notify every
 *  mounted consumer. Logs `counter_mode_switched` (server logs
 *  `billing_profile_applied` on the follow-up fetch). */
export function setCounterMode(modeKey) {
  try {
    if (modeKey) localStorage.setItem(MODE_STORAGE_KEY, modeKey)
    else localStorage.removeItem(MODE_STORAGE_KEY)
  } catch { /* storage unavailable — event still updates this session */ }
  logger.info('counter_mode_switched', { mode_key: modeKey || '(primary)' })
  try {
    window.dispatchEvent(new CustomEvent(MODE_EVENT, { detail: modeKey }))
  } catch { /* non-browser env */ }
}

export function useBillingProfile(mode = null) {
  const [session, setSession] = useState(generation)
  const [override, setOverride] = useState(getCounterMode)
  const effective = mode ?? override ?? ''    // '' = business primary
  const cacheKey = `${getTenantScope()}:${effective}`
  const [profile, setProfile] = useState(() => _cache.get(cacheKey) ?? null)
  const [loading, setLoading] = useState(!_cache.has(cacheKey))
  useEffect(() => {
    const changed = () => setSession(generation)
    window.addEventListener(SESSION_EVENT, changed)
    window.addEventListener('storage', changed)
    return () => { window.removeEventListener(SESSION_EVENT, changed); window.removeEventListener('storage', changed) }
  }, [])

  // Follow device-level mode switches when no explicit mode was requested.
  useEffect(() => {
    if (mode !== null) return undefined
    const onSwitch = (e) => setOverride(e?.detail ?? getCounterMode())
    window.addEventListener(MODE_EVENT, onSwitch)
    return () => window.removeEventListener(MODE_EVENT, onSwitch)
  }, [mode])

  useEffect(() => {
    let alive = true
    const requestGeneration = generation
    const currentKey = `${getTenantScope()}:${effective}`
    async function load() {
      if (_cache.has(currentKey)) {
        setProfile(_cache.get(currentKey))
        setLoading(false)
        return
      }
      setLoading(true)
      try {
        if (!_inflight.has(currentKey)) {
          _inflight.set(currentKey,
            api.get('/business/billing-profile', effective ? { mode: effective } : undefined))
        }
        const data = await _inflight.get(currentKey)
        if (generation !== requestGeneration || currentKey !== `${getTenantScope()}:${effective}`) return
        _cache.set(currentKey, data?.profile || null)
        if (alive) setProfile(_cache.get(currentKey))
      } catch (e) {
        logger.warn('billing-profile fetch failed — counter runs unrestricted', e)
        _inflight.delete(currentKey)
        if (alive) setProfile(null)
      } finally {
        if (alive) setLoading(false)
      }
    }
    runAsync(() => load())
    return () => { alive = false }
  }, [effective, cacheKey, session])

  return { profile, loading, mode: effective || null }
}

/** Reset the session cache (logout / business switch / tests). */
export function clearBillingProfileCache() {
  generation++
  _cache.clear()
  _inflight.clear()
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(SESSION_EVENT))
}
