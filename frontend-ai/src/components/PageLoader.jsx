/**
 * components/PageLoader.jsx
 * =========================
 * Full-screen brand splash shown while the app boots / auth resolves.
 * Animated skyline + a rotating tagline (the keyword is accent-coloured).
 */
import { useState, useEffect } from 'react'
import { SkylineLoader } from './Logo'

// [before keyword, keyword (accent), after keyword] — kept grammatical.
const TAGLINES = [
  ['The ', 'intelligence', ' behind everything.'],
  ['', 'Clarity', ' for every rupee.'],
  ['Your business, in sharp ', 'focus', '.'],
  ['Where your ', 'numbers', ' start talking.'],
]

export default function PageLoader() {
  const [i, setI] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setI(p => (p + 1) % TAGLINES.length), 2600)
    return () => clearInterval(t)
  }, [])

  const [pre, hl, post] = TAGLINES[i]
  return (
    <div className="ba-pageloader" role="status" aria-label="Loading BizAssist">
      <div style={{ color: 'var(--accent-color)' }}><SkylineLoader size={92} /></div>
      <div className="ba-tagline" key={i}>
        {pre}<span className="hl">{hl}</span>{post}
      </div>
    </div>
  )
}
