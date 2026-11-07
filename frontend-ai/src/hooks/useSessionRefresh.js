import { useCallback, useEffect, useRef, useState } from 'react'
import { API_BASE } from '../config'
import { boundedFetch, isSessionRejection, responseError } from '../utils/httpErrors'

function expiry(token) {
  try { return JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))).exp * 1000 }
  catch { return null }
}

export function useSessionRefresh(session, accept, reject) {
  const current = useRef(session)
  current.current = session
  const pending = useRef(null)
  const attempted = useRef(0)
  const [warning, setWarning] = useState(null)
  const refreshSession = useCallback(async (force = false) => {
    const active = current.current
    const expires = expiry(active?.token || '')
    if (!active?.token || (!force && (!expires || expires - Date.now() > 6 * 3600000))) return null
    if (pending.current) return pending.current
    if (!force && Date.now() - attempted.current < 60000) return null
    attempted.current = Date.now()
    pending.current = (async () => {
      try {
        const res = await boundedFetch(`${API_BASE}/auth/refresh`, { method: 'POST', headers: { Authorization: `Bearer ${active.token}` } })
        if (current.current?.token !== active.token) return null
        if (isSessionRejection(res)) { reject(); return null }
        if (!res.ok) throw await responseError(res)
        const data = await res.json()
        if (!data.token || current.current?.token !== active.token) return null
        const next = { ...active, ...data }
        accept(next)
        setWarning(null)
        return next
      } catch {
        if (expires && expires - Date.now() <= 10 * 60000) setWarning('Your session could not be renewed. Please sign in again before it expires.')
        return null
      } finally { pending.current = null }
    })()
    return pending.current
  }, [accept, reject])
  useEffect(() => {
    attempted.current = 0
    setWarning(null)
    refreshSession()
    const tick = () => { if (!document.hidden) refreshSession() }
    const timer = setInterval(tick, 60000)
    window.addEventListener('focus', tick)
    window.addEventListener('online', tick)
    return () => { clearInterval(timer); window.removeEventListener('focus', tick); window.removeEventListener('online', tick) }
  }, [session?.token, refreshSession])
  return { warning, refreshSession }
}

