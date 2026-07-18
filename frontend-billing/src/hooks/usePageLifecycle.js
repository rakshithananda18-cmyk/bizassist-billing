// ============================================================================
// usePageLifecycle.js
// Maps mobile-style lifecycle events to web equivalents:
//
//   onStart   → component mounts   (handled by each page's own useEffect)
//   onPause   → tab/window hidden  (visibilitychange → hidden)
//   onResume  → tab/window visible (visibilitychange → visible)
//   onStop    → component unmounts (useEffect cleanup — automatic)
//   onBack    → browser Back / – button blocked when isDirty
//   onUnload  → hard tab-close / refresh (beforeunload)
//
// Usage:
//   const { blocker, isRefreshing } = usePageLifecycle({
//     isDirty:      () => rows.length > 0,
//     dirtyMessage: 'You have unsaved rows. Leave anyway?',
//     onPause:      () => saveDraft(),
//     onResume:     () => load(),         // ← triggers isRefreshing indicator
//   })
//
//   Then render: <UnsavedChangesModal blocker={blocker} message={dirtyMessage} />
// ============================================================================

import { useEffect, useRef, useState, useCallback, useContext } from 'react'
import { UNSAFE_NavigationContext, useLocation } from 'react-router-dom'

/**
 * @param {object}   opts
 * @param {()=>bool} opts.isDirty       - Return true when page has unsaved state
 * @param {string}   [opts.dirtyMessage]- Message shown in UnsavedChangesModal
 * @param {()=>void} [opts.onPause]     - Called when page becomes hidden (tab switch)
 * @param {()=>Promise|void} [opts.onResume] - Called when page becomes visible again
 *                                             If it returns a Promise, isRefreshing is set
 */
export function usePageLifecycle({
  isDirty,
  dirtyMessage = 'You have unsaved changes. Are you sure you want to leave?',
  onPause,
  onResume,
} = {}) {
  const [isRefreshing, setIsRefreshing] = useState(false)
  const isDirtyRef  = useRef(isDirty)
  const onPauseRef  = useRef(onPause)
  const onResumeRef = useRef(onResume)

  // Keep refs current so effects don't go stale
  useEffect(() => { isDirtyRef.current  = isDirty  })
  useEffect(() => { onPauseRef.current  = onPause  })
  useEffect(() => { onResumeRef.current = onResume })

  // ── React Router navigation blocker (custom history-blocker) ────────────────
  const { navigator } = useContext(UNSAFE_NavigationContext)
  const location = useLocation()
  const [blocker, setBlocker] = useState({
    state: 'unblocked',
    reset() {},
    proceed() {},
  })

  const unblockRef = useRef(null)

  useEffect(() => {
    if (!navigator || !navigator.block) return

    const unblock = navigator.block((tx) => {
      if (isDirtyRef.current && isDirtyRef.current()) {
        setBlocker({
          state: 'blocked',
          reset() {
            setBlocker({ state: 'unblocked', reset() {}, proceed() {} })
          },
          proceed() {
            if (unblockRef.current) {
              unblockRef.current()
              unblockRef.current = null
            }
            tx.retry()
          }
        })
      } else {
        unblock()
        tx.retry()
      }
    })

    unblockRef.current = unblock
    return () => {
      if (unblockRef.current) {
        unblockRef.current()
        unblockRef.current = null
      }
    }
  }, [navigator, location.pathname, location.search])

  // ── Browser unload / hard refresh guard ────────────────────────────────────
  // Shows the native browser "Leave site?" dialog — cannot be styled
  useEffect(() => {
    function handleBeforeUnload(e) {
      if (isDirtyRef.current && isDirtyRef.current()) {
        e.preventDefault()
        e.returnValue = ''   // required for Chrome
      }
    }
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [])

  // ── Visibility / Page Lifecycle (onPause + onResume) ───────────────────────
  useEffect(() => {
    async function handleVisibilityChange() {
      if (document.visibilityState === 'hidden') {
        // onPause — page going to background
        if (onPauseRef.current) {
          try { onPauseRef.current() } catch { /* best-effort */ }
        }
      } else {
        // onResume — page coming back to foreground
        if (onResumeRef.current) {
          setIsRefreshing(true)
          try {
            const result = onResumeRef.current()
            if (result && typeof result.then === 'function') {
              await result
            }
          } catch { /* best-effort */ }
          finally { setIsRefreshing(false) }
        }
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [])

  return {
    /** Pass to <UnsavedChangesModal blocker={blocker} /> */
    blocker,
    /** True while onResume fetch is in-flight — show a spinner */
    isRefreshing,
    /** The configured dirty message for the modal */
    dirtyMessage,
  }
}
