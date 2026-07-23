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
import { useForegroundRefresh } from './useForegroundRefresh'

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
  // Don't re-fetch if the page was refreshed within this window. A quick glance
  // at another tab/app and back shouldn't trigger a full reload; only a return
  // after the data has plausibly gone stale should.
  staleMs = 30000,
} = {}) {
  const isDirtyRef  = useRef(isDirty)
  useEffect(() => { isDirtyRef.current  = isDirty  })

  // Foreground refresh (throttled focus/visibility resume) lives in its own
  // router-free hook so it can be reused anywhere; usePageLifecycle just adds
  // the react-router navigation blocker on top.
  const { isRefreshing } = useForegroundRefresh({ onResume, onPause, staleMs })

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

  return {
    /** Pass to <UnsavedChangesModal blocker={blocker} /> */
    blocker,
    /** True while onResume fetch is in-flight — show a spinner */
    isRefreshing,
    /** The configured dirty message for the modal */
    dirtyMessage,
  }
}
