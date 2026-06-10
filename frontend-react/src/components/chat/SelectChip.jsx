/**
 * components/chat/SelectChip.jsx
 * ================================
 * Expands as a fixed-position panel when clicked (escapes overflow:hidden parents).
 * User picks targets, clicks "Send" — fires the action with selected params.
 */
import { useState, useRef, useEffect } from 'react'
import { Icon } from '../icons'

export default function SelectChip({ chip, onConfirm }) {
  const [expanded, setExpanded]   = useState(false)
  const [panelPos, setPanelPos]   = useState({ top: 0, left: 0 })
  const [selected, setSelected]   = useState(
    () => (chip.options || []).map(o => o.value)  // all pre-selected by default
  )
  const btnRef = useRef(null)

  function toggle(value) {
    setSelected(prev =>
      prev.includes(value) ? prev.filter(v => v !== value) : [...prev, value]
    )
  }

  function open() {
    if (btnRef.current) {
      const rect = btnRef.current.getBoundingClientRect()
      // Position panel above the button, left-aligned
      setPanelPos({ top: rect.top - 8, left: rect.left })
    }
    setExpanded(true)
  }

  // Close on outside click
  useEffect(() => {
    if (!expanded) return
    function onOutside(e) {
      if (!e.target.closest('.select-chip-panel') && !e.target.closest('.chip-select')) {
        setExpanded(false)
      }
    }
    document.addEventListener('mousedown', onOutside)
    return () => document.removeEventListener('mousedown', onOutside)
  }, [expanded])

  return (
    <>
      <button
        ref={btnRef}
        className="chip chip-sm chip-select"
        onClick={open}
        title={chip.label}
      >
        <span className="chip-icon"><Icon name={chip.icon || 'bell'} /></span>
        <span className="chip-label">{chip.label}</span>
        <span className="chip-expand-arrow">▾</span>
      </button>

      {expanded && (
        <div
          className="select-chip-panel"
          style={{ top: panelPos.top, left: panelPos.left }}
        >
          <div className="select-chip-header">
            <span>{chip.label}</span>
            <button className="select-chip-close" onClick={() => setExpanded(false)}>✕</button>
          </div>
          <div className="select-chip-options">
            {(chip.options || []).map(opt => (
              <label key={opt.value} className="select-chip-option">
                <input
                  type="checkbox"
                  checked={selected.includes(opt.value)}
                  onChange={() => toggle(opt.value)}
                />
                <span>{opt.label}</span>
              </label>
            ))}
          </div>
          <button
            className="select-chip-confirm"
            disabled={selected.length === 0}
            onClick={() => {
              setExpanded(false)
              onConfirm(chip.action, chip.label, { customers: selected })
            }}
          >
            Send to {selected.length} selected
          </button>
        </div>
      )}
    </>
  )
}
