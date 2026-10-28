// src/components/layout/GlobalShortcutsModal.jsx
// Global Keyboard Shortcuts Cheat-Sheet modal accessible anywhere via '?'
import React, { useEffect, useState } from 'react'
import Modal from '../Modal'
import { KeyboardIcon } from '../Icons'

const SHORTCUT_GROUPS = [
  {
    title: 'Global Navigation & Shell',
    shortcuts: [
      { combo: ['Ctrl', 'Space'], desc: 'Universal Search & AI Assistant' },
      { combo: ['Ctrl', 'K'], desc: 'Quick Search / Command Palette' },
      { combo: ['?'], desc: 'Keyboard Shortcuts Reference' },
      { combo: ['Ctrl', 'L'], desc: 'Lock POS Terminal / Screen' },
      { combo: ['Esc'], desc: 'Close open dialogs or popovers' },
    ]
  },
  {
    title: 'POS Billing Counter',
    shortcuts: [
      { combo: ['F1'], desc: 'Focus barcode scanner / product search' },
      { combo: ['F2'], desc: 'Jump to customer selection' },
      { combo: ['Enter'], desc: 'Proceed to payment (on blank search)' },
      { combo: ['Ctrl', 'P'], desc: 'Save & Print thermal receipt' },
      { combo: ['Ctrl', 'T'], desc: 'Open new customer billing tab' },
      { combo: ['Ctrl', 'W'], desc: 'Close active billing tab' },
    ]
  },
  {
    title: 'Inventory & Credit Statement',
    shortcuts: [
      { combo: ['Ctrl', 'I'], desc: 'Quick Stock Intake' },
      { combo: ['Ctrl', 'Enter'], desc: 'Run active accounting report' },
      { combo: ['Ctrl', 'B'], desc: 'Barcode Label Designer' },
    ]
  }
]

export default function GlobalShortcutsModal({ open: controlledOpen, onClose: controlledClose }) {
  const [internalOpen, setInternalOpen] = useState(false)
  const isControlled = controlledOpen !== undefined
  const isOpen = isControlled ? controlledOpen : internalOpen
  const handleClose = isControlled ? controlledClose : () => setInternalOpen(false)

  useEffect(() => {
    const handleKeyDown = (e) => {
      const tag = document.activeElement?.tagName
      const isInput = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || document.activeElement?.isContentEditable
      if (e.key === '?' && !isInput && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault()
        if (isControlled) {
          if (isOpen) controlledClose?.()
          else controlledClose?.() // Or trigger open if controlled
        } else {
          setInternalOpen(prev => !prev)
        }
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, isControlled, controlledClose])

  return (
    <Modal
      open={isOpen}
      onClose={handleClose}
      title="Keyboard Shortcuts"
      size="md"
    >
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 16, padding: '6px 0' }}>
        {SHORTCUT_GROUPS.map(group => (
          <div key={group.title} style={{ background: 'var(--bg-3)', padding: 14, borderRadius: 'var(--radius-md)', border: '1px solid var(--border)' }}>
            <div style={{ fontSize: '0.74rem', fontWeight: 700, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
              <KeyboardIcon size={14} /> {group.title}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {group.shortcuts.map(sc => (
                <div key={sc.desc} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.8rem' }}>
                  <span style={{ color: 'var(--text-secondary)' }}>{sc.desc}</span>
                  <div style={{ display: 'flex', gap: 4 }}>
                    {sc.combo.map(k => (
                      <kbd key={k} style={{
                        background: 'var(--bg-1)',
                        border: '1px solid var(--border)',
                        borderRadius: 4,
                        padding: '2px 6px',
                        fontSize: '0.72rem',
                        fontWeight: 700,
                        fontFamily: 'monospace',
                        color: 'var(--text-primary)',
                        boxShadow: '0 1px 2px rgba(0,0,0,0.06)'
                      }}>{k}</kbd>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </Modal>
  )
}
