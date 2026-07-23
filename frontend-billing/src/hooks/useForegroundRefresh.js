// ============================================================================
// useForegroundRefresh.js
// Refresh a page's data when the user returns to it — but only if they were
// actually away long enough for the data to be worth re-fetching. A quick
// glance at another tab/app and straight back must NOT reload.
//
// Leaving (tab hidden OR window blur) and returning (tab visible OR window
// focus) are tracked as ONE "away" session; onResume runs at most once on
// return, and only when the away duration >= staleMs.
//
// Router-free by design, so it can be used in any component (including ones
// rendered outside a <Router> in tests). usePageLifecycle builds on top of
// this and adds the react-router navigation blocker.
//
//   const { isRefreshing } = useForegroundRefresh({ onResume: () => load() })
// ============================================================================
import { useEffect, useRef, useState } from 'react'

export function useForegroundRefresh({ onResume, onPause, staleMs = 30000 } = {}) {
  const [isRefreshing, setIsRefreshing] = useState(false)
  const onResumeRef = useRef(onResume)
  const onPauseRef  = useRef(onPause)
  useEffect(() => { onResumeRef.current = onResume })
  useEffect(() => { onPauseRef.current  = onPause })

  // Timestamp when the page went to the background, or null while foreground.
  const awaySinceRef = useRef(null)

  useEffect(() => {
    let running = false

    const markAway = () => {
      if (awaySinceRef.current != null) return   // already away — keep the first timestamp
      awaySinceRef.current = Date.now()
      if (onPauseRef.current) {
        try { onPauseRef.current() } catch { /* best-effort */ }
      }
    }

    const markBack = () => {
      // Ignore focus while the tab is still hidden, and any stray focus that
      // wasn't preceded by a real "away" (nothing to refresh for).
      if (document.visibilityState === 'hidden') return
      const awaySince = awaySinceRef.current
      awaySinceRef.current = null
      if (awaySince == null) return
      if (Date.now() - awaySince < staleMs) return   // only briefly away → still fresh
      if (running || !onResumeRef.current) return
      running = true
      setIsRefreshing(true)
      Promise.resolve()
        .then(() => onResumeRef.current && onResumeRef.current())
        .catch(() => { /* best-effort */ })
        .finally(() => { running = false; setIsRefreshing(false) })
    }

    const onVisibility = () => {
      if (document.visibilityState === 'hidden') markAway()
      else markBack()
    }

    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('blur', markAway)
    window.addEventListener('focus', markBack)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('blur', markAway)
      window.removeEventListener('focus', markBack)
    }
  }, [staleMs])

  return { isRefreshing }
}
