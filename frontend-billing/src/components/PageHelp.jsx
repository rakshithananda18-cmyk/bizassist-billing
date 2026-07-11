// components/PageHelp.jsx — the ⓘ help button on every page.
// ===========================================================
// Mounted ONCE in AppLayout; reads the current route and shows the matching
// entry from config/helpContent.js as a modal (numbered flow + tips). Pages
// without an entry (or in HELP_EXCLUDED_ROUTES, e.g. the full-screen POS)
// render nothing. Esc / overlay-click / × all close.
import React, { useState, useEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { useLocation } from 'react-router-dom'
import { HELP_CONTENT, HELP_EXCLUDED_ROUTES } from '../config/helpContent'

function InfoIcon({ size = 15 }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="16" x2="12" y2="12" />
      <line x1="12" y1="8" x2="12.01" y2="8" />
    </svg>
  )
}

export default function PageHelp() {
  const { pathname } = useLocation()
  const [open, setOpen] = useState(false)
  const [targetEl, setTargetEl] = useState(null)

  // Close when navigating to another page.
  useEffect(() => { setOpen(false) }, [pathname])

  // Look for target element to mount help icon next to title
  useEffect(() => {
    const timer = setTimeout(() => {
      const el = document.querySelector('.page-title') || document.querySelector('.page-title-placeholder')
      setTargetEl(el)
    }, 100)
    return () => clearTimeout(timer)
  }, [pathname])

  const onKey = useCallback((e) => { if (e.key === 'Escape') setOpen(false) }, [])
  useEffect(() => {
    if (!open) return
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onKey])

  if (HELP_EXCLUDED_ROUTES.has(pathname)) return null
  const help = HELP_CONTENT[pathname]
  if (!help) return null

  const helpButton = (
    <button
      onClick={(e) => {
        e.preventDefault()
        e.stopPropagation()
        setOpen(true)
      }}
      aria-label={`Help: ${help.title}`}
      title={`How ${help.title} works`}
      style={{
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        width: 18, height: 18, borderRadius: '50%',
        background: 'var(--bg-3, rgba(255,255,255,0.06))',
        border: '1px solid var(--border, rgba(128,128,128,0.3))',
        color: 'var(--text-muted, #888)', cursor: 'pointer',
        transition: 'all 0.15s ease',
        verticalAlign: 'middle',
        flexShrink: 0
      }}
      onMouseEnter={e => { e.currentTarget.style.color = 'var(--accent)'; e.currentTarget.style.borderColor = 'var(--accent)' }}
      onMouseLeave={e => { e.currentTarget.style.color = 'var(--text-muted, #888)'; e.currentTarget.style.borderColor = 'var(--border, rgba(128,128,128,0.3))' }}
    >
      <InfoIcon size={12} />
    </button>
  )

  return (
    <>
      {targetEl ? createPortal(helpButton, targetEl) : null}

      {open && createPortal(
        <div
          onClick={e => e.target === e.currentTarget && setOpen(false)}
          style={{
            position: 'fixed', inset: 0, zIndex: 1200,
            background: 'rgba(0,0,0,0.45)', backdropFilter: 'blur(2px)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20,
          }}
        >
          <div
            role="dialog" aria-modal="true"
            style={{
              width: '100%', maxWidth: 560, maxHeight: '82vh', overflowY: 'auto',
              background: 'var(--bg-1, var(--card, #1c1c1e))',
              border: '1px solid var(--border, rgba(128,128,128,0.3))',
              borderRadius: 14, padding: '20px 24px',
              boxShadow: '0 18px 50px rgba(0,0,0,0.35)',
            }}
          >
            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
              <span style={{ color: 'var(--accent)', display: 'inline-flex' }}><InfoIcon size={18} /></span>
              <span style={{ fontSize: '1.02rem', fontWeight: 800 }}>How {help.title} works</span>
              <button
                onClick={() => setOpen(false)} aria-label="Close help"
                style={{
                  marginLeft: 'auto', background: 'transparent', border: 'none',
                  color: 'var(--text-muted, #888)', fontSize: 20, cursor: 'pointer', lineHeight: 1, padding: 4,
                }}
              >×</button>
            </div>
            {help.intro && (
              <div style={{ fontSize: '0.85rem', color: 'var(--text-muted, #999)', marginBottom: 16, lineHeight: 1.5 }}>
                {help.intro}
              </div>
            )}

            {/* Numbered flow */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {help.steps.map((s, i) => (
                <div key={i} style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                  <span style={{
                    flexShrink: 0, width: 22, height: 22, borderRadius: '50%', marginTop: 1,
                    background: 'var(--accent)', color: '#fff',
                    fontSize: '0.72rem', fontWeight: 800,
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  }}>{i + 1}</span>
                  <div>
                    <div style={{ fontSize: '0.86rem', fontWeight: 700, marginBottom: 2 }}>{s.t}</div>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-muted, #999)', lineHeight: 1.55 }}>{s.d}</div>
                  </div>
                </div>
              ))}
            </div>

            {/* Tips */}
            {help.tips?.length > 0 && (
              <div style={{
                marginTop: 18, padding: '10px 14px', borderRadius: 10,
                background: 'var(--bg-2, rgba(255,255,255,0.04))',
                border: '1px solid var(--border, rgba(128,128,128,0.25))',
              }}>
                <div style={{
                  fontSize: '0.68rem', fontWeight: 800, textTransform: 'uppercase',
                  letterSpacing: '0.07em', color: 'var(--text-muted, #999)', marginBottom: 6,
                }}>Good to know</div>
                {help.tips.map((t, i) => (
                  <div key={i} style={{ fontSize: '0.78rem', color: 'var(--text-muted, #aaa)', lineHeight: 1.55, marginBottom: 4 }}>
                    • {t}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>,
        document.body
      )}
    </>
  )
}
