import React, { useState, useRef, useEffect, useId, forwardRef, useImperativeHandle } from 'react'
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
  const optionRefs = useRef([])
  const [dropdownStyle, setDropdownStyle] = useState({})
  const generatedId = useId().replace(/:/g, '')
  const listboxId = `${id || `custom-select-${generatedId}`}-listbox`

  useImperativeHandle(ref, () => buttonRef.current)

  // Extract options from children (native <option> elements)
  const options = React.Children.toArray(children).map(child => {
    if (child && child.type === 'option') {
      return {
        value: child.props.value !== undefined ? child.props.value : child.props.children,
        label: child.props.children,
        disabled: child.props.disabled
      }
    }
    return null
  }).filter(Boolean)

  const selectedIndex = options.findIndex(o => String(o.value) === String(value))
  const selectedOption = options[selectedIndex]
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

  const enabledOptionIndexes = options
    .map((option, index) => (!option.disabled ? index : null))
    .filter(index => index !== null)

  const focusOption = (index) => {
    const fallback = enabledOptionIndexes.find(optionIndex => optionIndex >= index) ?? enabledOptionIndexes[0]
    if (fallback !== undefined) optionRefs.current[fallback]?.focus()
  }

  const openMenu = (preferredIndex = selectedIndex) => {
    if (disabled) return
    setDropdownStyle(getDropdownPosition())
    setIsOpen(true)
    const schedule = window.requestAnimationFrame || ((callback) => window.setTimeout(callback, 0))
    schedule(() => focusOption(preferredIndex))
  }

  const closeMenu = ({ restoreFocus = false } = {}) => {
    setIsOpen(false)
    if (restoreFocus) {
      buttonRef.current?.focus()
    }
  }

  // Close on outside click
  useEffect(() => {
    function handleClickOutside(e) {
      // If clicking outside both the button and the dropdown list
      const dropdownEl = document.getElementById(listboxId)
      if (
        (buttonRef.current && buttonRef.current.contains(e.target)) ||
        (dropdownEl && dropdownEl.contains(e.target))
      ) {
        return
      }
      closeMenu()
    }
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [isOpen, listboxId])

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
    closeMenu({ restoreFocus: true })
  }

  const moveFocus = (currentIndex, direction) => {
    if (!enabledOptionIndexes.length) return
    const currentPosition = enabledOptionIndexes.indexOf(currentIndex)
    const nextPosition = currentPosition < 0
      ? 0
      : (currentPosition + direction + enabledOptionIndexes.length) % enabledOptionIndexes.length
    focusOption(enabledOptionIndexes[nextPosition])
  }

  const handleTriggerKeyDown = (event) => {
    onKeyDown?.(event)
    if (event.defaultPrevented || disabled) return
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const first = enabledOptionIndexes[0]
      const last = enabledOptionIndexes.at(-1)
      openMenu(selectedIndex >= 0 ? selectedIndex : (event.key === 'ArrowDown' ? first : last))
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      isOpen ? closeMenu() : openMenu()
    } else if (event.key === 'Escape' && isOpen) {
      event.preventDefault()
      closeMenu()
    }
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
        onClick={() => (isOpen ? closeMenu() : openMenu())}
        onKeyDown={handleTriggerKeyDown}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-controls={isOpen ? listboxId : undefined}
        style={buttonStyle}
      >
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {displayLabel}
        </span>
        <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginLeft: 8, opacity: 0.6, flexShrink: 0 }}>
          <polyline points="6 9 12 15 18 9"></polyline>
        </svg>
      </button>

      {isOpen && !disabled && createPortal(
        <div
          id={listboxId}
          role="listbox"
          aria-labelledby={id || undefined}
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
                key={`${String(opt.value)}-${idx}`}
                ref={node => { optionRefs.current[idx] = node }}
                type="button"
                role="option"
                aria-selected={isCurrent}
                disabled={opt.disabled}
                onClick={() => handleSelect(opt.value)}
                onKeyDown={(event) => {
                  if (event.key === 'ArrowDown') { event.preventDefault(); moveFocus(idx, 1) }
                  else if (event.key === 'ArrowUp') { event.preventDefault(); moveFocus(idx, -1) }
                  else if (event.key === 'Home') { event.preventDefault(); focusOption(enabledOptionIndexes[0]) }
                  else if (event.key === 'End') { event.preventDefault(); focusOption(enabledOptionIndexes.at(-1)) }
                  else if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); handleSelect(opt.value) }
                  else if (event.key === 'Escape') { event.preventDefault(); closeMenu({ restoreFocus: true }) }
                  else if (event.key === 'Tab') closeMenu()
                }}
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
              >
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{opt.label}</span>
                {isCurrent && <span aria-hidden="true" style={{ fontSize: '0.75rem', flexShrink: 0, marginLeft: 8 }}>✓</span>}
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

