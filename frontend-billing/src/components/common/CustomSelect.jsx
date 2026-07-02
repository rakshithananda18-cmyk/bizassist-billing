import React, { useState, useRef, useEffect, forwardRef, useImperativeHandle } from 'react'
import { createPortal } from 'react-dom'

const CustomSelect = forwardRef(function CustomSelect({
  value,
  onChange,
  onKeyDown,
  children,
  className = '',
  style = {},
  disabled = false,
  id = ''
}, ref) {
  const [isOpen, setIsOpen] = useState(false)
  const buttonRef = useRef(null)
  const [dropdownStyle, setDropdownStyle] = useState({})

  useImperativeHandle(ref, () => buttonRef.current)

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

  // Calculate position of the dropdown menu dynamically to handle viewport boundaries and screen height
  const getDropdownPosition = () => {
    if (!buttonRef.current) return {}
    const rect = buttonRef.current.getBoundingClientRect()
    const defaultMaxHeight = 250
    const spaceBelow = window.innerHeight - rect.bottom - 20
    const spaceAbove = rect.top - 20

    let top = rect.bottom + window.scrollY + 4
    let maxHeight = defaultMaxHeight
    if (spaceBelow < defaultMaxHeight && spaceAbove > spaceBelow) {
      // Not enough space below: open upward and clamp height to available space above
      maxHeight = Math.min(defaultMaxHeight, Math.max(80, spaceAbove))
      top = rect.top + window.scrollY - maxHeight - 4
    } else {
      // Open downward and clamp height to available space below
      maxHeight = Math.min(defaultMaxHeight, Math.max(80, spaceBelow))
    }

    return {
      top,
      left: rect.left + window.scrollX,
      width: rect.width,
      maxHeight,
    }
  }

  // Open/close handler
  const handleToggle = (e) => {
    e.preventDefault()
    if (isOpen) {
      setIsOpen(false)
      return
    }
    setDropdownStyle(getDropdownPosition())
    setIsOpen(true)
  }

  // Close on outside click
  useEffect(() => {
    function handleClickOutside(e) {
      // If clicking outside both the button and the dropdown list
      const dropdownEl = document.getElementById(`custom-dropdown-${id || 'generic'}`)
      if (
        (buttonRef.current && buttonRef.current.contains(e.target)) ||
        (dropdownEl && dropdownEl.contains(e.target))
      ) {
        return
      }
      setIsOpen(false)
    }
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [isOpen, id])

  // Update position on scroll/resize when open
  useEffect(() => {
    function updatePosition() {
      if (isOpen && buttonRef.current) {
        setDropdownStyle(getDropdownPosition())
      }
    }
    if (isOpen) {
      window.addEventListener('scroll', updatePosition, true)
      window.addEventListener('resize', updatePosition)
    }
    return () => {
      window.removeEventListener('scroll', updatePosition, true)
      window.removeEventListener('resize', updatePosition)
    }
  }, [isOpen])

  const handleSelect = (val) => {
    if (onChange) {
      // Simulate native event object for compatibility
      onChange({ target: { value: val } })
    }
    setIsOpen(false)
  }

  // Base style for the button to ensure it looks good if no styles are provided,
  // but allows overriding via className and style.
  const buttonStyle = {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.6 : 1,
    outline: 'none',
    width: '100%',
    backgroundImage: 'none',
    ...style
  }

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        id={id}
        className={`custom-select-btn ${className}`}
        disabled={disabled}
        onClick={handleToggle}
        onKeyDown={onKeyDown}
        style={buttonStyle}
      >
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {displayLabel}
        </span>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginLeft: 8, opacity: 0.6, flexShrink: 0 }}>
          <polyline points="6 9 12 15 18 9"></polyline>
        </svg>
      </button>

      {isOpen && !disabled && createPortal(
        <div
          id={`custom-dropdown-${id || 'generic'}`}
          style={{
            position: 'absolute',
            top: dropdownStyle.top,
            left: dropdownStyle.left,
            width: dropdownStyle.width,
            background: 'var(--bg-2, #ffffff)',
            border: '1px solid var(--border, #e5e7eb)',
            borderRadius: 8,
            boxShadow: '0 4px 14px rgba(0, 0, 0, 0.25)',
            zIndex: 99999,
            maxHeight: dropdownStyle.maxHeight || 250,
            overflowY: 'auto',
            padding: '6px 0',
            display: 'flex',
            flexDirection: 'column'
          }}
        >
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
        </div>,
        document.body
      )}
    </>
  )
})

export default CustomSelect

