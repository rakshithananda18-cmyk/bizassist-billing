import { useEffect } from 'react'
import { IS_LOCAL_APP } from '../config'
import { tokenStorage } from '../utils/tokenStorage'
import { refreshSession } from '../api/session'
import { readSessionClaims } from '../utils/sessionExpiry'

export function useSessionRefresh(token) {
  useEffect(() => {
    if (!token || IS_LOCAL_APP) return
    const check = () => {
      if (document.visibilityState === 'hidden') return
      try {
        const current = tokenStorage.getItem('billing_token')
        const exp = readSessionClaims(current)?.exp
        if (Number.isFinite(exp) && exp * 1000 - Date.now() < 6 * 3600000) void refreshSession()
      } catch { /* only the server validates credentials */ }
    }
    check()
    const timer = setInterval(check, 5 * 60000)
    window.addEventListener('focus', check)
    document.addEventListener('visibilitychange', check)
    return () => { clearInterval(timer); window.removeEventListener('focus', check); document.removeEventListener('visibilitychange', check) }
  }, [token])
}
