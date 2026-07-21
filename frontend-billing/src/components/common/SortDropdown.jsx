// ============================================================================
// SortDropdown — reusable sort + group-by control for any table.
//
// Usage:
//   <SortDropdown
//     fields={[
//       { value: 'date',       label: 'Date' },
//       { value: 'party_name', label: 'Customer' },
//       { value: 'amount',     label: 'Amount' },
//     ]}
//     sortConfig={{ key: 'date', direction: 'desc' }}   // '' key = unsorted
//     onSortChange={cfg => setSortConfig(cfg)}
//
//     // Optional group-by
//     groupFields={[
//       { value: '',           label: 'None' },
//       { value: 'party_name', label: 'Customer' },
//       { value: 'date',       label: 'Date' },
//     ]}
//     groupBy={''}
//     onGroupChange={field => setGroupBy(field)}
//   />
//
// The button shows the active sort field label + direction arrow, and
// highlights when any sort or group-by is active.
// ============================================================================
import React, { useState, useRef, useEffect, useId } from 'react'
import { createPortal } from 'react-dom'

const SORT_ICON = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M3 6h18M7 12h10M11 18h2" />
  </svg>
)
const ASC_ICON  = '↑'
const DESC_ICON = '↓'

export default function SortDropdown({
  fields = [],
  sortConfig = { key: '', direction: 'asc' },
  onSortChange = () => {},
  groupFields = [],
  groupBy = '',
  onGroupChange = () => {},
}) {
  const uid = useId()
  const [isOpen, setIsOpen] = useState(false)
  const buttonRef = useRef(null)
  const [panelStyle, setPanelStyle] = useState({})

  const isActive = sortConfig.key !== '' || groupBy !== ''
  const activeField = fields.find(f => f.value === sortConfig.key)

  const getPosition = () => {
    if (!buttonRef.current) return {}
    const rect = buttonRef.current.getBoundingClientRect()
    const panelH = (fields.length + groupFields.length) * 36 + 90
    const spaceBelow = window.innerHeight - rect.bottom - 12
    const openUpward = spaceBelow < panelH && rect.top > panelH
    return {
      top: openUpward
        ? rect.top + window.scrollY - panelH - 4
        : rect.bottom + window.scrollY + 4,
      right: window.innerWidth - rect.right - window.scrollX,
      minWidth: Math.max(rect.width, 200),
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
    const close = (e) => {
      const panel = document.getElementById(`sort-panel-${uid}`)
      if (
        (buttonRef.current && buttonRef.current.contains(e.target)) ||
        (panel && panel.contains(e.target))
      ) return
      setIsOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
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

  const handleFieldClick = (fieldValue) => {
    if (sortConfig.key === fieldValue) {
      // Same field → toggle direction
      onSortChange({ key: fieldValue, direction: sortConfig.direction === 'asc' ? 'desc' : 'asc' })
    } else {
      // New field → default direction
      const numericFields = ['amount', 'total', 'balance', 'outstanding', 'credit']
      const defaultDir = numericFields.some(n => fieldValue.includes(n)) ? 'desc' : 'asc'
      onSortChange({ key: fieldValue, direction: defaultDir })
    }
  }

  const handleClear = () => {
    onSortChange({ key: '', direction: 'asc' })
    if (groupFields.length) onGroupChange('')
  }

  const sectionLabel = {
    fontSize: '0.7rem', fontWeight: 700, color: 'var(--text-muted)',
    textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 4,
  }
  const rowBtn = (isSelected) => ({
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    width: '100%', padding: '6px 10px', borderRadius: 6, border: 'none',
    background: isSelected ? 'var(--accent-subtle, rgba(249,115,22,0.10))' : 'transparent',
    color: isSelected ? 'var(--accent, #f97316)' : 'var(--text-primary)',
    fontSize: '0.82rem', fontWeight: isSelected ? 700 : 500,
    cursor: 'pointer', textAlign: 'left', transition: 'background 0.1s',
  })

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={handleToggle}
        title="Sort & Group"
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 5, height: 34,
          padding: '0 12px',
          background: isActive ? 'var(--accent-subtle, rgba(249,115,22,0.10))' : 'var(--bg-2)',
          border: isActive ? '1px solid var(--accent, #f97316)' : '1px solid var(--border)',
          borderRadius: 'var(--radius-md, 8px)',
          color: isActive ? 'var(--accent, #f97316)' : 'var(--text-secondary)',
          fontSize: '0.82rem', fontWeight: 600, cursor: 'pointer',
          transition: 'all 0.15s', flexShrink: 0,
        }}
      >
        {SORT_ICON}
        <span>
          {activeField
            ? `${activeField.label} ${sortConfig.direction === 'asc' ? ASC_ICON : DESC_ICON}`
            : 'Sort'}
        </span>
      </button>

      {isOpen && createPortal(
        <div
          id={`sort-panel-${uid}`}
          style={{
            position: 'absolute', top: panelStyle.top, right: panelStyle.right,
            minWidth: panelStyle.minWidth,
            background: 'var(--bg-2, #fff)', border: '1px solid var(--border)',
            borderRadius: 12, boxShadow: '0 8px 32px rgba(0,0,0,0.18)',
            zIndex: 99999, padding: '12px 14px 14px',
          }}
        >
          {/* Header */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
            <span style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
              Sort & Group
            </span>
            {isActive && (
              <button type="button" onClick={handleClear} style={{
                background: 'none', border: 'none', cursor: 'pointer',
                fontSize: '0.75rem', color: 'var(--accent)', fontWeight: 600, padding: 0,
              }}>Clear</button>
            )}
          </div>

          {/* Sort by */}
          {fields.length > 0 && (
            <div style={{ marginBottom: groupFields.length ? 12 : 0 }}>
              <div style={sectionLabel}>Sort by</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                {fields.map(f => {
                  const sel = sortConfig.key === f.value
                  return (
                    <button key={f.value} type="button"
                      style={rowBtn(sel)}
                      onClick={() => handleFieldClick(f.value)}
                      onMouseEnter={e => { if (!sel) e.currentTarget.style.background = 'var(--bg-3)' }}
                      onMouseLeave={e => { if (!sel) e.currentTarget.style.background = 'transparent' }}
                    >
                      <span>{f.label}</span>
                      {sel && (
                        <span style={{ fontSize: '0.8rem' }}>
                          {sortConfig.direction === 'asc' ? '↑ A→Z' : '↓ Z→A'}
                        </span>
                      )}
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {/* Group by */}
          {groupFields.length > 0 && (
            <div>
              <div style={{ ...sectionLabel, borderTop: '1px solid var(--border)', paddingTop: 10, marginTop: 4 }}>
                Group by
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {groupFields.map(f => {
                  const sel = groupBy === f.value
                  return (
                    <button key={f.value} type="button"
                      onClick={() => onGroupChange(f.value)}
                      style={{
                        padding: '4px 12px', borderRadius: 20, cursor: 'pointer',
                        border: sel ? '1px solid var(--accent)' : '1px solid var(--border)',
                        background: sel ? 'var(--accent-subtle, rgba(249,115,22,0.10))' : 'var(--bg-3)',
                        color: sel ? 'var(--accent)' : 'var(--text-secondary)',
                        fontSize: '0.78rem', fontWeight: sel ? 700 : 500,
                        transition: 'all 0.12s',
                      }}
                    >{f.label}</button>
                  )
                })}
              </div>
            </div>
          )}
        </div>,
        document.body
      )}
    </>
  )
}
