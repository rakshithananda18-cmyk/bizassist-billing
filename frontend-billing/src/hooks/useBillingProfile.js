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

const MODE_STORAGE_KEY = 'pos.counter_mode'
const MODE_EVENT = 'bizassist:counter-mode'

const _cache = new Map()          // cacheKey ('' = primary) → profile
const _inflight = new Map()       // cacheKey → Promise

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
  const [override, setOverride] = useState(getCounterMode)
  const effective = mode ?? override ?? ''    // '' = business primary
  const [profile, setProfile] = useState(() => _cache.get(effective) ?? null)
  const [loading, setLoading] = useState(!_cache.has(effective))

  // Follow device-level mode switches when no explicit mode was requested.
  useEffect(() => {
    if (mode !== null) return undefined
    const onSwitch = (e) => setOverride(e?.detail ?? getCounterMode())
    window.addEventListener(MODE_EVENT, onSwitch)
    return () => window.removeEventListener(MODE_EVENT, onSwitch)
  }, [mode])

  useEffect(() => {
    let alive = true
    async function load() {
      if (_cache.has(effective)) {
        setProfile(_cache.get(effective))
        setLoading(false)
        return
      }
      setLoading(true)
      try {
        if (!_inflight.has(effective)) {
          _inflight.set(effective,
            api.get('/business/billing-profile', effective ? { mode: effective } : undefined))
        }
        const data = await _inflight.get(effective)
        _cache.set(effective, data?.profile || null)
        if (alive) setProfile(_cache.get(effective))
      } catch (e) {
        logger.warn('billing-profile fetch failed — counter runs unrestricted', e)
        _inflight.delete(effective)
        if (alive) setProfile(null)
      } finally {
        if (alive) setLoading(false)
      }
    }
    load()
    return () => { alive = false }
  }, [effective])

  return { profile, loading, mode: effective || null }
}

/** Reset the session cache (logout / business switch / tests). */
export function clearBillingProfileCache() {
  _cache.clear()
  _inflight.clear()
}
