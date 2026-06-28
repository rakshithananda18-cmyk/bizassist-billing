import React, { useState, useRef, useEffect } from 'react'

export default function CustomSelect({
  value,
  onChange,
  children,
  className = '',
  style = {},
  disabled = false,
  id = ''
}) {
  const [isOpen, setIsOpen] = useState(false)
  const containerRef = useRef(null)

  // Extract options from children (native <option> elements)
  const options = React.Children.map(children, child => {
    if (child && child.type === 'option') {
      return {
        value: child.props.value !== undefined ? child.props.value : child.props.children,
        label: child.props.children,
        disabled: child.props.disabled
      }
    }
    return null
  }).filter(Boolean)

  const selectedOption = options.find(o => String(o.value) === String(value))
  const displayLabel = selectedOption ? selectedOption.label : (options.length > 0 ? options[0].label : 'Select...')

  // Close on outside click
  useEffect(() => {
    function handleClickOutside(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setIsOpen(false)
      }
    }
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [isOpen])

  const handleSelect = (val) => {
    if (onChange) {
      // Simulate native event object for compatibility
      onChange({ target: { value: val } })
    }
    setIsOpen(false)
  }

  return (
    <div
      ref={containerRef}
      className={`custom-select-container ${className}`}
      style={{ position: 'relative', display: 'inline-block', width: '100%', ...style }}
      id={id}
    >
      <button
        type="button"
        disabled={disabled}
        onClick={(e) => { e.preventDefault(); setIsOpen(!isOpen); }}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: 'var(--bg-2, #ffffff)',
          border: '1px solid var(--border, #e5e7eb)',
          color: 'var(--text-primary, #1f2937)',
          padding: '8px 12px',
          borderRadius: 'var(--radius-md, 6px)',
          fontSize: '0.875rem',
          cursor: disabled ? 'not-allowed' : 'pointer',
          opacity: disabled ? 0.6 : 1,
          outline: 'none',
          boxShadow: 'var(--shadow-sm, 0 1px 2px rgba(0,0,0,0.05))',
          minHeight: 38
        }}
      >
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {displayLabel}
        </span>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginLeft: 8, opacity: 0.6, flexShrink: 0 }}>
          <polyline points="6 9 12 15 18 9"></polyline>
        </svg>
      </button>

      {isOpen && !disabled && (
        <div style={{
          position: 'absolute',
          top: '100%',
          left: 0,
          right: 0,
          marginTop: 4,
          background: 'var(--bg-2, #ffffff)',
          border: '1px solid var(--border, #e5e7eb)',
          borderRadius: 8,
          boxShadow: '0 4px 14px rgba(0, 0, 0, 0.25)',
          zIndex: 9999,
          maxHeight: 250,
          overflowY: 'auto',
          padding: '6px 0',
          display: 'flex',
          flexDirection: 'column'
        }}>
          {options.map((opt, idx) => {
            const isCurrent = String(opt.value) === String(value)
            return (
              <button
                key={idx}
                type="button"
                disabled={opt.disabled}
                onClick={(e) => { e.preventDefault(); handleSelect(opt.value); }}
                style={{
                  background: isCurrent ? 'var(--bg-4, rgba(0,0,0,0.06))' : 'transparent',
                  border: 'none',
                  color: opt.disabled ? 'var(--text-muted, #9ca3af)' : (isCurrent ? 'var(--accent, #f97316)' : 'var(--text-primary, #374151)'),
                  padding: '8px 12px',
                  fontSize: '0.85rem',
                  fontWeight: isCurrent ? 600 : 500,
                  textAlign: 'left',
                  cursor: opt.disabled ? 'not-allowed' : 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  outline: 'none',
                  width: '100%',
                  opacity: opt.disabled ? 0.6 : 1
                }}
                onMouseEnter={(e) => {
                  if (!isCurrent && !opt.disabled) e.currentTarget.style.background = 'var(--bg-3, rgba(0,0,0,0.03))'
                }}
                onMouseLeave={(e) => {
                  if (!isCurrent && !opt.disabled) e.currentTarget.style.background = 'transparent'
                }}
              >
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{opt.label}</span>
                {isCurrent && <span style={{ fontSize: '0.75rem', flexShrink: 0, marginLeft: 8 }}>✓</span>}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
