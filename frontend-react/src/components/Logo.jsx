/**
 * components/Logo.jsx
 * ===================
 * BizAssist brand mark + loaders, all from one SVG skyline:
 *   - BuildingMark   outlined towers + windows + doors + accent star (theme-adaptive)
 *   - Logo           mark + "BizAssist" wordmark
 *   - SkylineLoader  animated towers (page loader)
 *   - InlineLoader   small bars-only (chat "typing")
 * Outline/windows/doors use currentColor so they adapt to the theme; the star
 * uses the accent. Animation classes (ba-rise / ba-rise-star) live in styles/brand.css.
 */
import { useId } from 'react'

const STAR = 'M50 0 L51.5 4.5 L56 6 L51.5 7.5 L50 12 L48.5 7.5 L44 6 L48.5 4.5 Z'

const WINDOWS = [
  [10.6, 39], [15.1, 39],
  [28.5, 29], [33.2, 29], [28.5, 34], [33.2, 34],
  [46.5, 23], [51.2, 23], [46.5, 28], [51.2, 28], [46.5, 33], [51.2, 33],
]

export function BuildingMark({ size = 28, accent = 'var(--accent-color)', strokeWidth = 1.8, style }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none" aria-hidden="true"
         shapeRendering="geometricPrecision"
         style={{ display: 'block', flexShrink: 0, ...style }}>
      <g stroke="currentColor" strokeWidth={strokeWidth} strokeLinejoin="round">
        <rect x="8" y="36" width="12" height="18" rx="1" />
        <rect x="26" y="26" width="12" height="28" rx="1" />
        <rect x="44" y="16" width="12" height="38" rx="1" />
      </g>
      <g fill="currentColor">
        {WINDOWS.map(([x, y], i) => (
          <rect key={i} x={x} y={y} width="2.1" height="2.1" />
        ))}
      </g>
      <g stroke="currentColor" strokeWidth={strokeWidth} fill="none" strokeLinejoin="round">
        <rect x="11.4" y="46" width="5.2" height="8" />
        <rect x="29.4" y="43" width="5.2" height="11" />
        <rect x="47.4" y="40" width="5.2" height="14" />
      </g>
      <path d={STAR} fill={accent} />
    </svg>
  )
}

// Compact mark for the nav/toolbars — drawn on a 24-unit grid at stroke 2 so it
// matches the weight of the other (Feather/24-grid) nav icons exactly. The
// detailed BuildingMark (64-grid) is for larger sizes (login, splash, chat).
export function NavMark({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true"
         stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
         style={{ display: 'block', flexShrink: 0 }}>
      <rect x="2.5" y="13" width="3.4" height="8" rx="0.5" />
      <rect x="8.3" y="9" width="3.4" height="12" rx="0.5" />
      <rect x="14.1" y="6" width="3.4" height="15" rx="0.5" />
      <path d="M15.8 0.5 L16.6 2.4 L18.5 3 L16.6 3.6 L15.8 5.5 L15 3.6 L13.1 3 L15 2.4 Z"
            fill="var(--accent-color)" stroke="none" />
    </svg>
  )
}

export function Logo({ size = 24, wordmark = true, className = '' }) {
  return (
    <span className={`ba-logo ${className}`}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
      <BuildingMark size={size} />
      {wordmark && (
        <span className="ba-wordmark">Biz<span style={{ color: 'var(--accent-color)' }}>Assist</span></span>
      )}
    </span>
  )
}

// Full detailed mark with the towers RISING out of the ground (clip-reveal, so
// the outline / windows / door keep their proportions — no stroke distortion).
function Tower({ x, y, w, h, windows, door }) {
  return (
    <>
      <rect x={x} y={y} width={w} height={h} rx="1" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" fill="none" />
      <g fill="currentColor">
        {windows.map(([wx, wy], i) => <rect key={i} x={wx} y={wy} width="2.1" height="2.1" />)}
      </g>
      <rect x={door[0]} y={door[1]} width={door[2]} height={door[3]} stroke="currentColor" strokeWidth="1.8" fill="none" strokeLinejoin="round" />
    </>
  )
}

export function SkylineLoader({ size = 92 }) {
  // Unique clip ids so several loaders can render at once (splash + chat).
  const uid = useId().replace(/:/g, '')
  const c1 = `${uid}-1`, c2 = `${uid}-2`, c3 = `${uid}-3`
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none" aria-hidden="true">
      <defs>
        <clipPath id={c1}><rect x="8" y="36" width="12" height="18" rx="1" /></clipPath>
        <clipPath id={c2}><rect x="26" y="26" width="12" height="28" rx="1" /></clipPath>
        <clipPath id={c3}><rect x="44" y="16" width="12" height="38" rx="1" /></clipPath>
      </defs>
      <g clipPath={`url(#${c1})`}>
        <g className="ba-rise" style={{ '--d': '18px', animationDelay: '0s' }}>
          <Tower x="8" y="36" w="12" h="18" windows={[[10.6, 39], [15.1, 39]]} door={[11.4, 46, 5.2, 8]} />
        </g>
      </g>
      <g clipPath={`url(#${c2})`}>
        <g className="ba-rise" style={{ '--d': '28px', animationDelay: '.18s' }}>
          <Tower x="26" y="26" w="12" h="28" windows={[[28.5, 29], [33.2, 29], [28.5, 34], [33.2, 34]]} door={[29.4, 43, 5.2, 11]} />
        </g>
      </g>
      <g clipPath={`url(#${c3})`}>
        <g className="ba-rise" style={{ '--d': '38px', animationDelay: '.36s' }}>
          <Tower x="44" y="16" w="12" h="38" windows={[[46.5, 23], [51.2, 23], [46.5, 28], [51.2, 28], [46.5, 33], [51.2, 33]]} door={[47.4, 40, 5.2, 14]} />
        </g>
      </g>
      <path className="ba-rise-star" d={STAR} fill="var(--accent-color)" />
    </svg>
  )
}

// The chat "thinking" loader is the SAME rising-skyline animation, just small.
export function InlineLoader({ size = 34 }) {
  return <SkylineLoader size={size} />
}
