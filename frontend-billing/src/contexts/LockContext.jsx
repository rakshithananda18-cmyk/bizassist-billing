// src/contexts/LockContext.jsx
// ============================================================
// Per-user session PIN lock.  All localStorage keys are
// namespaced by user.id so owner and each cashier have fully
// independent locks on the same device/browser.
//
// Storage keys (all keyed by user.id):
//   lock_hash_<id>     SHA-256 hex of (pin + salt)
//   lock_salt_<id>     random 16-byte hex salt
//   lock_active_<id>   '1' while the screen is locked
//
// Fresh server-login always clears the lock (see clearLock).
// ============================================================
import React, {
  createContext, useContext, useState, useEffect,
  useCallback, useRef,
} from 'react'
import { useAuth } from './AuthContext'
import { logger } from '../utils/logger'

const LockContext = createContext(null)

// ── Crypto helpers ────────────────────────────────────────────────────────────
async function sha256hex(str) {
  const buf = await crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(str),
  )
  return Array.from(new Uint8Array(buf))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('')
}

function randomHex(bytes = 16) {
  const arr = new Uint8Array(bytes)
  crypto.getRandomValues(arr)
  return Array.from(arr).map(b => b.toString(16).padStart(2, '0')).join('')
}

// ── Provider ──────────────────────────────────────────────────────────────────
export function LockProvider({ children }) {
  const { user, logout, token } = useAuth()
  const uid = user?.id ?? null

  // Keys namespaced by user.id — returns null when no user logged in
  const k = useCallback((suffix) => uid != null ? `lock_${suffix}_${uid}` : null, [uid])

  const [isLocked, setIsLocked]   = useState(false)
  const [hasLock,  setHasLock]    = useState(false)
  const inactivityRef = useRef(null)

  // ── Load lock state whenever user changes ──────────────────────────────────
  useEffect(() => {
    if (uid == null) {
      setIsLocked(false)
      setHasLock(false)
      return
    }
    const hashKey   = k('hash')
    const activeKey = k('active')
    const hash = localStorage.getItem(hashKey)
    const active = localStorage.getItem(activeKey)
    setHasLock(!!hash)
    setIsLocked(!!hash && active === '1')
    logger.debug(`[LOCK] Loaded state for user ${uid}: hasLock=${!!hash} isLocked=${!!hash && active === '1'}`)
  }, [uid, k])

  // ── Clear lock on fresh token (login resets PIN state) ────────────────────
  useEffect(() => {
    // When a new token arrives and there was a previous lock_active, clear it
    // so fresh login always bypasses the lock screen.
    if (uid == null) return
    const activeKey = k('active')
    if (localStorage.getItem(activeKey) === '1') {
      // Only auto-clear if there's a fresh valid token (i.e. just logged in)
      // We detect this by checking token is present but isLocked was set to
      // true — the re-login flow calls logout() first, clearing uid, then
      // sets a new token, so uid changes → this effect re-runs → we clear.
      localStorage.removeItem(activeKey)
      setIsLocked(false)
      logger.info('[LOCK] Fresh login detected — lock_active cleared')
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]) // only re-run when token changes (i.e. on login)

  // ── Inactivity timer ──────────────────────────────────────────────────────
  const resetInactivityTimer = useCallback((timeoutMs) => {
    if (inactivityRef.current) clearTimeout(inactivityRef.current)
    if (timeoutMs <= 0) return
    inactivityRef.current = setTimeout(() => {
      if (hasLock) {
        logger.info('[LOCK] Inactivity timeout — locking session')
        setIsLocked(true)
        if (uid != null) localStorage.setItem(k('active'), '1')
      }
    }, timeoutMs)
  }, [hasLock, uid, k])

  // ── Public API ────────────────────────────────────────────────────────────
  /** Manually lock the session */
  const lock = useCallback(() => {
    if (!hasLock) return
    logger.info('[LOCK] Manual lock triggered')
    setIsLocked(true)
    if (uid != null) localStorage.setItem(k('active'), '1')
  }, [hasLock, uid, k])

  /** Attempt to unlock. Returns true on success. */
  const unlock = useCallback(async (pin) => {
    if (uid == null) return false
    const storedHash = localStorage.getItem(k('hash'))
    const storedSalt = localStorage.getItem(k('salt'))
    if (!storedHash || !storedSalt) return false
    const attempt = await sha256hex(pin + storedSalt)
    if (attempt !== storedHash) {
      logger.warn('[LOCK] Incorrect PIN attempt for user', uid)
      return false
    }
    logger.info('[LOCK] Correct PIN — unlocking for user', uid)
    localStorage.removeItem(k('active'))
    setIsLocked(false)
    return true
  }, [uid, k])

  /** Set or change the PIN for the current user */
  const setupPasscode = useCallback(async (pin) => {
    if (uid == null) return
    const salt = randomHex(16)
    const hash = await sha256hex(pin + salt)
    localStorage.setItem(k('hash'), hash)
    localStorage.setItem(k('salt'), salt)
    localStorage.removeItem(k('active'))
    setHasLock(true)
    setIsLocked(false)
    logger.info('[LOCK] Passcode set for user', uid)
  }, [uid, k])

  /** Remove the PIN entirely for the current user */
  const clearPasscode = useCallback(() => {
    if (uid == null) return
    localStorage.removeItem(k('hash'))
    localStorage.removeItem(k('salt'))
    localStorage.removeItem(k('active'))
    setHasLock(false)
    setIsLocked(false)
    logger.info('[LOCK] Passcode cleared for user', uid)
  }, [uid, k])

  return (
    <LockContext.Provider value={{
      isLocked, hasLock,
      lock, unlock, setupPasscode, clearPasscode,
      resetInactivityTimer,
    }}>
      {children}
    </LockContext.Provider>
  )
}

export const useLock = () => useContext(LockContext)
