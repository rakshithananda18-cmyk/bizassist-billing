// ============================================================================
// FilterDropdown — reusable filter popover with a funnel icon button.
//
// Supported filter types:
//   'chips'       — pill button group  { value: string, onChange, options: [{value,label}] }
//   'select'      — list with checkmark { same }
//   'daterange'   — from/to date pickers { value: {from,to}, onChange({from,to}) }
//   'amountrange' — min/max number inputs { value: {min,max}, onChange({min,max}) }
//
// Shows a badge with the count of active (non-empty) filters.
// Portal-rendered dropdown avoids overflow clipping.
// ============================================================================
import React, { useState, useRef, useEffect, useId } from 'react'
import { createPortal } from 'react-dom'
import { FilterIcon } from '../Icons'

function isActive(f) {
  if (f.type === 'daterange')   return !!(f.value?.from || f.value?.to)
  if (f.type === 'amountrange') return (f.value?.min !== '' && f.value?.min != null) || (f.value?.max !== '' && f.value?.max != null)
  return f.value !== '' && f.value != null
}

export default function FilterDropdown({ filters = [], className = '', style = {} }) {
  const uid = useId()
  const [isOpen, setIsOpen] = useState(false)
  const buttonRef = useRef(null)
  const [panelStyle, setPanelStyle] = useState({})

  const activeCount = filters.filter(isActive).length

  const getPosition = () => {
    if (!buttonRef.current) return {}
    const rect = buttonRef.current.getBoundingClientRect()
    const spaceBelow = window.innerHeight - rect.bottom - 12
    const estimatedHeight = Math.min(filters.length * 110 + 60, 440)
    const openUpward = spaceBelow < estimatedHeight && rect.top > estimatedHeight
    return {
      top: openUpward
        ? rect.top + window.scrollY - estimatedHeight - 4
        : rect.bottom + window.scrollY + 4,
      right: window.innerWidth - rect.right - window.scrollX,
      minWidth: Math.max(rect.width, 260),
    }
  }

  const handleToggle = (e) => {
    e.preventDefault()
    if (isOpen) { setIsOpen(false); return }
    setPanelStyle(getPosition())
    setIsOpen(true)
  }

  useEffect(() => {
    if (!isOpen) return
    const handleClickOutside = (e) => {
      const panelEl = document.getElementById(`filter-panel-${uid}`)
      if (
        (buttonRef.current && buttonRef.current.contains(e.target)) ||
        (panelEl && panelEl.contains(e.target))
      ) return
      setIsOpen(false)
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [isOpen, uid])

  useEffect(() => {
    if (!isOpen) return
    const update = () => setPanelStyle(getPosition())
    window.addEventListener('scroll', update, true)
    window.addEventListener('resize', update)
    return () => {
      window.removeEventListener('scroll', update, true)
      window.removeEventListener('resize', update)
    }
  }, [isOpen])

  const handleClearAll = () => {
    filters.forEach(f => {
      if (f.type === 'daterange')        f.onChange({ from: '', to: '' })
      else if (f.type === 'amountrange') f.onChange({ min: '', max: '' })
      else                               f.onChange('')
    })
  }

  const inputStyle = {
    flex: 1, boxSizing: 'border-box', height: 32,
    padding: '0 8px', borderRadius: 6,
    border: '1px solid var(--border)',
    background: 'var(--bg-3)', color: 'var(--text-primary)',
    fontSize: '0.8rem', outline: 'none',
  }

  const btnStyle = {
    display: 'inline-flex', alignItems: 'center', gap: 6, height: 34,
    padding: '0 12px',
    background: isOpen || activeCount > 0 ? 'var(--accent-subtle, rgba(var(--accent-rgb,249,115,22),0.10))' : 'var(--bg-2)',
    border: isOpen || activeCount > 0 ? '1px solid var(--accent, #f97316)' : '1px solid var(--border)',
    borderRadius: 'var(--radius-md, 8px)',
    color: isOpen || activeCount > 0 ? 'var(--accent, #f97316)' : 'var(--text-secondary)',
    fontSize: '0.82rem', fontWeight: 600, cursor: 'pointer',
    transition: 'all 0.15s ease', flexShrink: 0, ...style,
  }

  return (
    <>
      <button ref={buttonRef} type="button" className={`filter-dropdown-btn ${className}`}
        onClick={handleToggle} title="Filters" style={btnStyle}>
        <FilterIcon size={14} />
        <span>Filters</span>
        {activeCount > 0 && (
          <span style={{
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            width: 18, height: 18, borderRadius: '50%',
            background: 'var(--accent, #f97316)', color: '#fff',
            fontSize: '0.65rem', fontWeight: 800, lineHeight: 1,
          }}>{activeCount}</span>
        )}
      </button>

      {isOpen && createPortal(
        <div id={`filter-panel-${uid}`} style={{
          position: 'absolute', top: panelStyle.top, right: panelStyle.right,
          minWidth: panelStyle.minWidth,
          background: 'var(--bg-2, #fff)', border: '1px solid var(--border)',
          borderRadius: 12, boxShadow: '0 8px 32px rgba(0,0,0,0.18)',
          zIndex: 99999, padding: '12px 14px 14px',
          display: 'flex', flexDirection: 'column', gap: 14,
        }}>
          {/* Header */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 2 }}>
            <span style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
              Filters
            </span>
            {activeCount > 0 && (
              <button type="button" onClick={handleClearAll} style={{
                background: 'none', border: 'none', cursor: 'pointer',
                fontSize: '0.75rem', color: 'var(--accent)', fontWeight: 600, padding: 0,
              }}>Clear all</button>
            )}
          </div>

          {/* Filter groups */}
          {filters.map(f => (
            <div key={f.key}>
              <div style={{ fontSize: '0.73rem', fontWeight: 700, color: 'var(--text-muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                {f.label}
              </div>

              {f.type === 'daterange' ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)', width: 28, flexShrink: 0 }}>From</label>
                    <input type="date" value={f.value?.from || ''} style={inputStyle}
                      onChange={e => f.onChange({ ...f.value, from: e.target.value })} />
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)', width: 28, flexShrink: 0 }}>To</label>
                    <input type="date" value={f.value?.to || ''} style={inputStyle}
                      onChange={e => f.onChange({ ...f.value, to: e.target.value })} />
                  </div>
                </div>

              ) : f.type === 'amountrange' ? (
                <div style={{ display: 'flex', gap: 8 }}>
                  <input type="number" placeholder="Min ₹" value={f.value?.min ?? ''} min={0}
                    style={{ ...inputStyle, flex: 1 }}
                    onChange={e => f.onChange({ ...f.value, min: e.target.value })} />
                  <input type="number" placeholder="Max ₹" value={f.value?.max ?? ''} min={0}
                    style={{ ...inputStyle, flex: 1 }}
                    onChange={e => f.onChange({ ...f.value, max: e.target.value })} />
                </div>

              ) : f.type === 'chips' ? (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {f.options.map(opt => {
                    const sel = String(f.value) === String(opt.value)
                    return (
                      <button key={opt.value} type="button" onClick={() => f.onChange(opt.value)} style={{
                        padding: '4px 12px', borderRadius: 20,
                        border: sel ? '1px solid var(--accent)' : '1px solid var(--border)',
                        background: sel ? 'var(--accent-subtle, rgba(249,115,22,0.10))' : 'var(--bg-3)',
                        color: sel ? 'var(--accent)' : 'var(--text-secondary)',
                        fontSize: '0.78rem', fontWeight: sel ? 700 : 500,
                        cursor: 'pointer', transition: 'all 0.12s ease',
                      }}>{opt.label}</button>
                    )
                  })}
                </div>

              ) : (
                // 'select' — list with checkmark
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {f.options.map(opt => {
                    const sel = String(f.value) === String(opt.value)
                    return (
                      <button key={opt.value} type="button" onClick={() => f.onChange(opt.value)} style={{
                        padding: '6px 10px', borderRadius: 6, border: 'none',
                        background: sel ? 'var(--accent-subtle, rgba(249,115,22,0.10))' : 'transparent',
                        color: sel ? 'var(--accent)' : 'var(--text-primary)',
                        fontSize: '0.82rem', fontWeight: sel ? 700 : 500,
                        cursor: 'pointer', textAlign: 'left',
                        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                        width: '100%', transition: 'background 0.1s ease',
                      }}
                        onMouseEnter={e => { if (!sel) e.currentTarget.style.background = 'var(--bg-3)' }}
                        onMouseLeave={e => { if (!sel) e.currentTarget.style.background = 'transparent' }}
                      >
                        <span>{opt.label}</span>
                        {sel && <span style={{ fontSize: '0.7rem', opacity: 0.8 }}>✓</span>}
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          ))}
        </div>,
        document.body
      )}
    </>
  )
}
