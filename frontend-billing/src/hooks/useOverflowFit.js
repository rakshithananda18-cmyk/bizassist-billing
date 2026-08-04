// ============================================================================
// useOverflowFit — show as many toolbar items as actually fit, overflow the rest.
// ----------------------------------------------------------------------------
// WHY NOT A BREAKPOINT
// The first version of the Stock toolbar folded its buttons at a fixed width
// (`@media (max-width: 1400px)`, later `@container (max-width: 1000px)`). A
// breakpoint answers "is the window small" when the question is "do these
// specific buttons fit", and the two come apart constantly:
//
//   · the sidebar toggles between a ~56px rail and ~240px expanded, so one
//     viewport width means two very different toolbars;
//   · `html` carries a user-set `zoom`, so CSS pixels and rendered pixels differ
//     by a factor the stylesheet cannot see;
//   · the items themselves change width — "Export" becomes "Exporting…", a
//     count appears in a tab label, a role hides one button entirely.
//
// Measured on /parties/payments 2026-08-04: the bar had 979px available and its
// content needed 673px. A breakpoint tuned for the other workspace would have
// folded it anyway.
//
// HOW
// Each item's natural width is measured ONCE, while all of them are rendered.
// After that the hook only needs the container's width — it sums cached widths
// until they stop fitting, reserving room for the ⋯ trigger whenever anything
// is hidden. Re-measures when `count` changes (labels/roles changed the set).
//
// Returns `fitCount`: how many leading items to render. The caller renders
// items[0..fitCount) inline and items[fitCount..] in a menu.
// ============================================================================
import { useState, useRef, useLayoutEffect, useCallback } from 'react'

// Width reserved for the ⋯ trigger when at least one item overflows.
const TRIGGER_W = 34

export function useOverflowFit(containerRef, count, { gap = 6, reserve = 0 } = {}) {
  const [fitCount, setFitCount] = useState(count)
  const widths = useRef([])
  const measured = useRef(false)

  // Invalidate the cache when the item set changes.
  useLayoutEffect(() => { measured.current = false }, [count])

  const recompute = useCallback(() => {
    const el = containerRef.current
    if (!el) return

    if (!measured.current) {
      // Only valid while every item is rendered, which is true on the pass
      // right after `count` changed because fitCount was reset to `count`.
      const kids = [...el.querySelectorAll('[data-fit-item]')]
      if (kids.length < count) return          // not all present yet; try later
      widths.current = kids.map(k => k.getBoundingClientRect().width)
      measured.current = true
    }

    const avail = el.getBoundingClientRect().width - reserve
    let used = 0
    let n = 0
    for (let i = 0; i < widths.current.length; i++) {
      const next = used + widths.current[i] + (i ? gap : 0)
      // Everything after this one would need the trigger, so budget for it
      // unless this is the last item.
      const needsTrigger = i < widths.current.length - 1
      if (next + (needsTrigger ? TRIGGER_W + gap : 0) > avail) break
      used = next
      n++
    }
    setFitCount(n)
  }, [containerRef, count, gap, reserve])

  useLayoutEffect(() => {
    const el = containerRef.current
    if (!el) return
    recompute()
    // ResizeObserver rather than a window listener: the bar's width changes
    // when the SIDEBAR toggles, which fires no window resize at all.
    const ro = new ResizeObserver(recompute)
    ro.observe(el)
    return () => ro.disconnect()
  }, [containerRef, recompute])

  return fitCount
}

export default useOverflowFit
