// ============================================================================
// OverflowActions — a toolbar action row that shows as many buttons as FIT.
// ----------------------------------------------------------------------------
// Not a breakpoint. `useOverflowFit` measures each button once and then only
// needs the row's own width, so the fold responds to the things a media query
// cannot see: the sidebar collapsing to its rail, the user's App Display Size
// zoom, and labels that change width ("Export" -> "Exporting…").
//
// Whatever does not fit goes into the same `ContextMenu` the grids use, so the
// action is never unreachable — only relocated.
//
//   <OverflowActions items={[
//     { label: 'Show Summary', icon: <SummaryIcon size={12} />, action: fn },
//     { label: 'Record Payment', icon: <PlusIcon size={13} />, action: fn, primary: true },
//   ]} />
//
// Items are ordered by importance: the FIRST to be hidden is the last in the
// array, so put the primary action first if it must survive a narrow bar.
// ============================================================================
import React, { useRef, useState } from 'react'
import ContextMenu from './ContextMenu'
import { useOverflowFit } from '../../hooks/useOverflowFit'

export default function OverflowActions({ items = [], className = '' }) {
  const ref = useRef(null)
  const [menu, setMenu] = useState(null)
  const fit = useOverflowFit(ref, items.length)
  const hidden = items.slice(fit)

  return (
    <div ref={ref} className={`ovf-actions ${className}`}>
      {items.slice(0, fit).map((it, i) => (
        <button
          key={it.label}
          data-fit-item
          className={it.variant || (it.primary ? 'btn btn-primary btn-sm' : 'btn btn-secondary btn-sm')}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}
          onClick={it.action}
          disabled={it.disabled}
        >
          {it.icon} {it.label}
        </button>
      ))}

      {/* Measuring pass: while widths are unknown the hook needs every item in
          the DOM. They are rendered off-screen rather than skipped, because a
          button that was never laid out has no width to cache. */}
      {fit < items.length && hidden.map(it => (
        <button key={`m-${it.label}`} data-fit-item aria-hidden="true" tabIndex={-1}
          className={it.variant || (it.primary ? 'btn btn-primary btn-sm' : 'btn btn-secondary btn-sm')}
          style={{ position: 'absolute', visibility: 'hidden', pointerEvents: 'none', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
          {it.icon} {it.label}
        </button>
      ))}

      {hidden.length > 0 && (
        <button
          className="btn btn-secondary btn-sm ovf-more"
          title="More actions"
          aria-label="More actions"
          onClick={e => {
            const r = e.currentTarget.getBoundingClientRect()
            setMenu({
              x: r.right - 210, y: r.bottom,
              items: hidden.filter(i => !i.disabled),
            })
          }}
        >
          &#8943;
        </button>
      )}

      <ContextMenu menu={menu} onClose={() => setMenu(null)} />
    </div>
  )
}
