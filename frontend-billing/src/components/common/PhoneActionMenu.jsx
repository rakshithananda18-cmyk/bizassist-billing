import { useEffect, useRef, useState } from 'react'
import './phoneActionMenu.css'

/** Secondary phone actions share existing callbacks; no duplicate edit state. */
export default function PhoneActionMenu({ label = 'More actions', actions = [] }) {
  const [open, setOpen] = useState(false)
  const root = useRef(null)
  const trigger = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    const dismiss = event => {
      if (!root.current?.contains(event.target)) setOpen(false)
    }
    const escape = event => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); setOpen(false); trigger.current?.focus() }
    }
    document.addEventListener('pointerdown', dismiss)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('pointerdown', dismiss)
      document.removeEventListener('keydown', escape)
    }
  }, [open])
  return (
    <div className="phone-action-menu" ref={root}>
      <button ref={trigger} type="button" className="phone-action-trigger" aria-label={label} aria-expanded={open} onClick={() => setOpen(value => !value)}>
        <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></svg>
      </button>
      {open && <div className="phone-action-popover" aria-label={label}>
        {actions.map((action, index) => <button key={action.id || index} type="button" disabled={action.disabled} onClick={() => { setOpen(false); action.action?.() }}>
          {action.icon}<span>{action.label}</span>{action.badge && <small>{action.badge}</small>}
        </button>)}
      </div>}
    </div>
  )
}
