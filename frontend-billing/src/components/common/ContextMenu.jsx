// ============================================================================
// ContextMenu.jsx
// Shared right-click context menu rendered via portal to document.body.
// Escapes all overflow:hidden containers. Auto-clamps to viewport edges.
//
// Usage:
//   const [ctxMenu, setCtxMenu] = useState(null) // { x, y, items }
//
//   <tr onContextMenu={e => {
//     e.preventDefault()
//     setCtxMenu({ x: e.clientX, y: e.clientY, items: [...] })
//   }}>
//
//   <ContextMenu menu={ctxMenu} onClose={() => setCtxMenu(null)} />
//
// Item shape:
//   { label, icon?, action, danger?, divider? }
//   divider: true → renders a separator line (other fields ignored)
// ============================================================================

import React, { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

const MENU_WIDTH  = 210
const MENU_OFFSET = 4   // gap from cursor

export default function ContextMenu({ menu, onClose }) {
  const ref = useRef(null)

  useEffect(() => {
    if (!menu) return

    // Clamp position to viewport
    if (ref.current) {
      const { width: w, height: h } = ref.current.getBoundingClientRect()
      const vw = window.innerWidth
      const vh = window.innerHeight
      if (menu.x + w + MENU_OFFSET > vw) ref.current.style.left = `${Math.max(0, menu.x - w - MENU_OFFSET)}px`
      if (menu.y + h + MENU_OFFSET > vh) ref.current.style.top  = `${Math.max(0, menu.y - h)}px`
    }

    function onMouseDown(e) {
      if (ref.current && !ref.current.contains(e.target)) onClose()
    }
    function onKeyDown(e) {
      if (e.key === 'Escape') onClose()
    }
    function onScroll() { onClose() }

    document.addEventListener('mousedown', onMouseDown)
    document.addEventListener('keydown', onKeyDown)
    window.addEventListener('scroll', onScroll, true)
    return () => {
      document.removeEventListener('mousedown', onMouseDown)
      document.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('scroll', onScroll, true)
    }
  }, [menu, onClose])

  if (!menu) return null

  return createPortal(
    <div
      ref={ref}
      className="ctx-menu"
      style={{
        position: 'fixed',
        top:  menu.y + MENU_OFFSET,
        left: menu.x + MENU_OFFSET,
        width: MENU_WIDTH,
        zIndex: 99990,
      }}
    >
      {menu.items.map((item, i) => {
        if (item.divider) {
          return <div key={i} className="ctx-menu-divider" />
        }
        return (
          <button
            key={i}
            className={`ctx-menu-item${item.danger ? ' ctx-menu-item--danger' : ''}`}
            onClick={() => { onClose(); item.action() }}
          >
            {item.icon && (
              <span className="ctx-menu-item-icon">{item.icon}</span>
            )}
            <span>{item.label}</span>
          </button>
        )
      })}
    </div>,
    document.body
  )
}
