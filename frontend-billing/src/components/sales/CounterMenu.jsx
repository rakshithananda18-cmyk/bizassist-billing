// components/sales/CounterMenu.jsx
// ================================
// Counter selection dropdown in the POS top bar (multi-terminal POS).
// For owners: allows switching counter prefixes on the fly to review/bill under
// cashiers' series, and has an "+ Add Counter" option that redirects to Staff settings.
// For staff/cashiers: displays a static, read-only counter badge.
import React, { useState, useEffect, useRef } from 'react'

export default function CounterMenu({
  prefix,
  isOwner = false,
  availableCounters = [],
  onSelectCounter,
  onAddCounter
}) {
  const [isOpen, setIsOpen] = useState(false)
  const menuRef = useRef(null)
  const label = (prefix || '').trim() || '—'

  useEffect(() => {
    function handleClickOutside(event) {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
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

  const handleToggle = () => {
    if (isOwner) {
      setIsOpen(!isOpen)
    }
  }

  const handleSelect = (val) => {
    if (typeof onSelectCounter === 'function') {
      onSelectCounter(val)
    }
    setIsOpen(false)
  }

  const handleAdd = (e) => {
    e.stopPropagation()
    if (typeof onAddCounter === 'function') {
      onAddCounter()
    }
    setIsOpen(false)
  }

  return (
    <div ref={menuRef} style={{ position: 'relative', display: 'inline-block' }}>
      <span
        className="pos-counter-badge"
        onClick={handleToggle}
        title={isOwner
          ? 'Click to switch counter or manage staff assignments'
          : 'Your billing counter — assigned by the owner in Staff management'}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 6,
          fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-secondary)',
          padding: '3px 10px', border: '1px solid var(--border)', borderRadius: 6,
          background: 'var(--bg-3)', whiteSpace: 'nowrap',
          cursor: isOwner ? 'pointer' : 'default',
          userSelect: 'none'
        }}
      >
        <span style={{ color: 'var(--text-muted)' }}>Counter:</span> {label}
        {isOwner && <span style={{ fontSize: '0.55rem', opacity: 0.7, marginLeft: 2 }}>▼</span>}
      </span>

      {isOpen && (
        <div style={{
          position: 'absolute',
          top: '100%',
          right: 0,
          marginTop: 6,
          background: 'var(--bg-surface, #ffffff)',
          border: '1px solid var(--border, #e5e7eb)',
          borderRadius: 8,
          boxShadow: '0 4px 14px rgba(0, 0, 0, 0.16)',
          zIndex: 1000,
          minWidth: 160,
          padding: '6px 0',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'stretch'
        }}>
          {availableCounters.map((c, idx) => {
            const isCurrent = c.label === label
            return (
              <button
                key={idx}
                onClick={() => handleSelect(c.value)}
                style={{
                  background: isCurrent ? 'var(--bg-3, rgba(0,0,0,0.04))' : 'transparent',
                  border: 'none',
                  color: isCurrent ? 'var(--accent, #3b82f6)' : 'var(--text-primary, #374151)',
                  padding: '8px 12px',
                  fontSize: '0.78rem',
                  fontWeight: isCurrent ? 600 : 500,
                  textAlign: 'left',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  outline: 'none',
                  width: '100%'
                }}
                onMouseEnter={(e) => {
                  if (!isCurrent) e.currentTarget.style.background = 'var(--bg-2, rgba(0,0,0,0.02))'
                }}
                onMouseLeave={(e) => {
                  if (!isCurrent) e.currentTarget.style.background = 'transparent'
                }}
              >
                <span>{c.label}</span>
                {isCurrent && <span style={{ fontSize: '0.7rem' }}>✓</span>}
              </button>
            )
          })}
          
          <div style={{ height: 1, background: 'var(--border, #e5e7eb)', margin: '4px 0' }} />
          
          <button
            onClick={handleAdd}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--accent, #3b82f6)',
              padding: '8px 12px',
              fontSize: '0.78rem',
              fontWeight: 600,
              textAlign: 'left',
              cursor: 'pointer',
              outline: 'none',
              width: '100%'
            }}
            onMouseEnter={(e) => e.currentTarget.style.background = 'var(--bg-2, rgba(0,0,0,0.02))'}
            onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
          >
            + Add Counter
          </button>
        </div>
      )}
    </div>
  )
}
