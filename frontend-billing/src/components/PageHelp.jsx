// components/PageHelp.jsx — the per-page ⓘ help button and visual guide.
// ==============================================================================
// Mounted in AppLayout; reads the current route and mounts the orange ⓘ badge
// next to the page title (.page-title / .page-title-placeholder).
// Clicking opens SmartHelpCenterModal with the contextual per-page guide,
// motion checkout simulation, keyboard shortcuts, and FAQs.
import React, { useState, useEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { useLocation } from 'react-router-dom'
import { HELP_CONTENT, HELP_EXCLUDED_ROUTES } from '../config/helpContent'
import SmartHelpCenterModal from './help/SmartHelpCenterModal'

function InfoIcon({ size = 13 }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
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
  useEffect(() => {
    setOpen(false)
  }, [pathname])

  // Look for target element to mount help icon next to title
  useEffect(() => {
    const timer = setTimeout(() => {
      const el = document.querySelector('.page-title') || document.querySelector('.page-title-placeholder')
      setTargetEl(el)
    }, 100)
    return () => clearTimeout(timer)
  }, [pathname])

  const onKey = useCallback((e) => {
    if (e.key === 'Escape') setOpen(false)
  }, [])

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
      type="button"
      onClick={(e) => {
        e.preventDefault()
        e.stopPropagation()
        setOpen(true)
      }}
      aria-label={`Help: ${help.title}`}
      title={`How ${help.title} works`}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 22,
        height: 22,
        borderRadius: '50%',
        background: 'rgba(194, 113, 79, 0.12)',
        border: '1.5px solid var(--accent, #c2714f)',
        color: 'var(--accent, #c2714f)',
        cursor: 'pointer',
        transition: 'all 0.15s ease',
        verticalAlign: 'middle',
        marginLeft: 8,
        flexShrink: 0
      }}
      onMouseEnter={e => {
        e.currentTarget.style.background = 'rgba(194, 113, 79, 0.24)'
        e.currentTarget.style.transform = 'scale(1.08)'
      }}
      onMouseLeave={e => {
        e.currentTarget.style.background = 'rgba(194, 113, 79, 0.12)'
        e.currentTarget.style.transform = 'scale(1)'
      }}
    >
      <InfoIcon size={12} />
    </button>
  )

  return (
    <>
      {targetEl ? createPortal(helpButton, targetEl) : null}

      <SmartHelpCenterModal
        isOpen={open}
        onClose={() => setOpen(false)}
        initialTab="page"
        currentRoute={pathname}
        routeHelp={help}
      />
    </>
  )
}
