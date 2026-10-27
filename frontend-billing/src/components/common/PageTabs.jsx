// ============================================================================
// common/PageTabs.jsx — shared segmented navigation for workspace pages.
// ----------------------------------------------------------------------------
// tabs: [{ id, label, icon? }] · active: id · onChange(id)
// inline: render compactly inside a page's own toolbar row (no full-width
//         strip/border) — used by the merged workspaces so the workspace tabs
//         sit where the page's stale title used to be, on ONE header row.
// ============================================================================

import React, { useLayoutEffect, useRef } from 'react'
import './pageTabs.css'

export default function PageTabs({ tabs, active, onChange, inline = false, label = 'Workspace pages' }) {
  const containerRef = useRef(null)
  useLayoutEffect(() => {
    const list = containerRef.current
    const selected = list?.querySelector('[aria-selected="true"]')
    if (!selected) return
    const bounds = list.getBoundingClientRect()
    const item = selected.getBoundingClientRect()
    // Reveal a deep-linked section without moving the page's vertical scroll.
    if (item.left < bounds.left) list.scrollLeft += item.left - bounds.left - 5
    else if (item.right > bounds.right) list.scrollLeft += item.right - bounds.right + 5
  }, [active, tabs.length])
  const moveFocus = (event, index) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1
      : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length
    containerRef.current?.querySelectorAll('[role="tab"]')[next]?.focus()
    onChange(tabs[next].id)
  }
  return (
    <div ref={containerRef} className={`page-tabs${inline ? ' page-tabs--inline' : ''}`} role="tablist" aria-label={label}>
      {tabs.map((tab, index) => (
        <button
          type="button"
          role="tab"
          key={tab.id}
          className={`page-tab${active === tab.id ? ' is-active' : ''}`}
          aria-selected={active === tab.id}
          tabIndex={active === tab.id ? 0 : -1}
          onClick={() => onChange(tab.id)}
          onKeyDown={event => moveFocus(event, index)}
        >
          {tab.icon}
          <span>{tab.label}</span>
          {tab.badge > 0 && <span className="page-tab-count">{tab.badge}</span>}
        </button>
      ))}
    </div>
  )
}
