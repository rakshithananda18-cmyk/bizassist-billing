/**
 * components/PageLoader.jsx
 * ==========================
 * Full-screen brand splash shown while the app boots / auth resolves.
 * Animated skyline (SkylineLoader) + rotating taglines, exact port of
 * the frontend-ai PageLoader — adapted with billing-specific copy and
 * the billing palette token (--accent instead of --accent-color).
 */
import React, { useState, useEffect } from 'react'
import { SkylineLoader } from './Logo'

// Billing-specific taglines — keyword (accent-coloured) in the middle slot.
const TAGLINES = [
  ['The ', 'intelligence', ' behind your billing.'],
  ['', 'Clarity', ' for every rupee.'],
  ['Your business, in sharp ', 'focus', '.'],
  ['Where your ', 'numbers', ' start talking.'],
  ['Smart billing, ', 'effortlessly', ' done.'],
]

export default function PageLoader() {
  const [i, setI] = useState(0)

  useEffect(() => {
    const t = setInterval(() => setI(p => (p + 1) % TAGLINES.length), 2600)
    return () => clearInterval(t)
  }, [])

  const [pre, hl, post] = TAGLINES[i]

  return (
    <div
      role="status"
      aria-label="Loading BizAssist Billing"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 22,
        background: 'var(--bg)',
      }}
    >
      {/* Animated skyline — uses ba-rise + ba-rise-star from index.css */}
      <div style={{ color: 'var(--accent)' }}>
        <SkylineLoader size={92} />
      </div>

      {/* Rotating tagline */}
      <div
        key={i}
        style={{
          fontSize: 15,
          fontWeight: 500,
          color: 'var(--text-muted)',
          textAlign: 'center',
          animation: 'ba-fade-in 0.5s ease-out',
        }}
      >
        {pre}
        <span style={{ color: 'var(--accent)' }}>{hl}</span>
        {post}
      </div>
    </div>
  )
}
