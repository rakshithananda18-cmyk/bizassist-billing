import React, { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import RoadmapTown from './RoadmapTown'
import './AuthRoadmap.css'

// A gently widening ribbon makes the journey from a small counter to a growing business visible.
const ROAD_SEGMENTS = [
  [[-100, 820], [180, 880], [330, 780], [300, 650]],
  [[300, 650], [270, 520], [100, 510], [180, 350]],
  [[180, 350], [260, 190], [450, 300], [650, 420]],
  [[650, 420], [850, 540], [1130, 560], [1180, 420]],
  [[1180, 420], [1230, 280], [1110, 200], [1250, 140]],
  [[1250, 140], [1390, 80], [1500, 170], [1700, 70]],
]

function roadRibbon(inset = 0) {
  const points = ROAD_SEGMENTS.flatMap(([a, b, c, d], segment) => Array.from({ length: 33 }, (_, step) => {
    const t = step / 32
    const u = 1 - t
    const x = u ** 3 * a[0] + 3 * u ** 2 * t * b[0] + 3 * u * t ** 2 * c[0] + t ** 3 * d[0]
    const y = u ** 3 * a[1] + 3 * u ** 2 * t * b[1] + 3 * u * t ** 2 * c[1] + t ** 3 * d[1]
    const dx = 3 * u ** 2 * (b[0] - a[0]) + 6 * u * t * (c[0] - b[0]) + 3 * t ** 2 * (d[0] - c[0])
    const dy = 3 * u ** 2 * (b[1] - a[1]) + 6 * u * t * (c[1] - b[1]) + 3 * t ** 2 * (d[1] - c[1])
    const length = Math.hypot(dx, dy)
    const halfWidth = 23 + 24 * (segment + t) / ROAD_SEGMENTS.length - inset
    return { x, y, nx: -dy / length * halfWidth, ny: dx / length * halfWidth }
  }))
  const edge = (point, side) => `${(point.x + point.nx * side).toFixed(1)},${(point.y + point.ny * side).toFixed(1)}`
  return `M${points.map(point => edge(point, 1)).join('L')}L${points.reverse().map(point => edge(point, -1)).join('L')}Z`
}

const ROAD_EDGE = roadRibbon()
const ROAD_SURFACE = roadRibbon(5)

const CHECKPOINTS = [
  { id: 'prices', label: 'Pricing', name: 'Explore flexible selling prices', title: 'One catalogue. Three ways to sell.', copy: 'Keep retail, wholesale and distributor prices on the same item, with one shared view of stock.', x: 11.25, y: 35, side: 'left' },
  { id: 'offline', label: 'Billing', name: 'Explore offline desktop billing', title: 'Keep the counter moving.', copy: 'Scan, bill and print on your desktop using local store data, even when the internet drops.', x: 18.75, y: 65, side: 'left' },
  { id: 'stock', label: 'Stock', name: 'Explore connected stock and purchases', title: 'Know what came in. And what is left.', copy: 'Bring supplier purchases, quantities, batches and expiry dates together in your stock workspace.', x: 73.75, y: 42, side: 'right' },
  { id: 'dues', label: 'Payments', name: 'Explore customer and supplier dues', title: 'Every balance, in view.', copy: 'Follow customer and supplier dues beside their invoices, receipts and part payments.', x: 78.125, y: 14, side: 'right' },
]

function CheckpointIcon({ id }) {
  return <svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {id === 'prices' && <><path d="M4 5v14m4-14v14m3-14v14m5-14v14m4-14v14M2 3h5M2 3v4m20-4h-5m5 0v4M2 21h5m-5 0v-4m20 4h-5m5 0v-4" /></>}
    {id === 'offline' && <><path d="M6 3h12v18l-3-2-3 2-3-2-3 2V3Zm3 5h6m-6 4h6m-6 4h3" /></>}
    {id === 'stock' && <><path d="m12 3 9 5-9 5-9-5 9-5Zm-9 5v9l9 5 9-5V8m-9 5v9M7.5 5.5l9 5" /></>}
    {id === 'dues' && <><circle cx="12" cy="12" r="9" /><path d="M8 7h8M8 10h8M8 7c7 0 7 7 0 7l7 4" /></>}
  </svg>
}

/** A backdrop only: the existing login card and authentication flow stay intact. */
export default function AuthRoadmap({ interactive = true }) {
  const [active, setActive] = useState(null)
  const [pinned, setPinned] = useState(false)
  const [position, setPosition] = useState(null)
  const region = useRef(null)
  const detail = useRef(null)
  const buttons = useRef({})
  const detailId = `roadmap-${useId().replace(/:/g, '')}`
  const feature = CHECKPOINTS.find(point => point.id === active)

  useLayoutEffect(() => {
    if (!feature) return
    function place(scrollOnMobile = false) {
      if (!detail.current || !buttons.current[feature.id]) return
      if (window.innerWidth <= 1100) {
        if (scrollOnMobile) {
          const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
          detail.current.scrollIntoView?.({ block: 'nearest', behavior: reducedMotion ? 'auto' : 'smooth' })
        }
        return
      }
      const box = detail.current.getBoundingClientRect()
      const card = region.current?.closest('.login-container')?.querySelector('.login-card')?.getBoundingClientRect()
      // Dock copy in the illustration's empty sky, away from the road and its checkpoints.
      const side = window.innerHeight < 700 ? 'right' : feature.side
      let left = window.innerWidth * (side === 'left' ? .045 : .805)
      if (card) left = side === 'left' ? Math.min(left, card.left - box.width - 16) : Math.max(left, card.right + 16)
      left = Math.max(16, Math.min(left, window.innerWidth - box.width - 16))
      const top = Math.min(window.innerHeight * (side === 'left' ? .045 : .4), window.innerHeight - box.height - 24)
      setPosition({ left, top: Math.max(16, top) })
    }
    place(true)
    const onResize = () => place()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [feature])

  function close() { setActive(null); setPinned(false) }
  // Docked copy stays readable while the pointer crosses the space between a pin and its story.
  function preview(id) { if (!pinned) setActive(id) }

  useEffect(() => {
    function outside(event) { if (!region.current?.contains(event.target)) close() }
    function escape(event) { if (event.key === 'Escape') close() }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('pointerdown', outside)
      document.removeEventListener('keydown', escape)
    }
  }, [])

  return <>
    <div className="roadmap-scene" aria-hidden="true">
      <svg className="roadmap-scene-art" viewBox="0 0 1600 1000" preserveAspectRatio="none" fill="none">
        <defs>
          <radialGradient id={`${detailId}-glow`}><stop stopColor="#dc9373" stopOpacity=".09" /><stop offset="1" stopColor="var(--auth-canvas, #090a0d)" stopOpacity="0" /></radialGradient>
          <path id={`${detailId}-road`} d="M-100 820C180 880 330 780 300 650S100 510 180 350 450 300 650 420 1130 560 1180 420 1110 200 1250 140 1500 170 1700 70" />
        </defs>
        <ellipse cx="800" cy="500" rx="900" ry="650" fill={`url(#${detailId}-glow)`} />
        <path d={ROAD_EDGE} fill="#000" opacity=".3" transform="translate(0 10)" />
        <path d={ROAD_EDGE} fill="var(--roadmap-edge, #363b45)" opacity=".68" />
        <path d={ROAD_SURFACE} fill="var(--roadmap-surface, #1d222b)" opacity=".9" />
        <use href={`#${detailId}-road`} stroke="var(--roadmap-line, #cbd3df)" strokeWidth="2" strokeDasharray="13 18" opacity=".3" />
        <g stroke="var(--roadmap-line, #c4ccd9)" strokeWidth="1" opacity=".065"><path d="M0 180h1600M0 420h1600M0 660h1600M0 900h1600M180 0v1000M420 0v1000M660 0v1000M900 0v1000M1140 0v1000M1380 0v1000" /></g>
        <RoadmapTown />
      </svg>
      <div className="roadmap-scene-veil" />
      <div className="roadmap-scene-caption"><span>EVERY BIG BUSINESS STARTS SMALL</span><p>From your first sale.<br />To your next chapter.</p><small>Explore the checkpoints along the way.</small></div>
    </div>

    {interactive && <div className="roadmap-checkpoints" ref={region} role="group" aria-label="Explore STATER Bill benefits" onBlur={event => { if (event.relatedTarget && !event.currentTarget.contains(event.relatedTarget)) close() }}>
      <p className="roadmap-mobile-heading">Explore what your business can do.</p>
      <div className="roadmap-pins">
        {CHECKPOINTS.map(point => <div className={`roadmap-pin ${active === point.id ? 'is-active' : ''}`} key={point.id} style={{ '--point-x': `${point.x}%`, '--point-y': `${point.y}%` }} onPointerEnter={event => { if (event.pointerType !== 'touch') preview(point.id) }}>
          <button ref={element => { buttons.current[point.id] = element }} type="button" aria-label={point.name} aria-expanded={active === point.id} aria-controls={active === point.id ? detailId : undefined} aria-describedby={active === point.id ? detailId : undefined} onFocus={() => { setActive(point.id); setPinned(false) }} onClick={() => { if (pinned && active === point.id) close(); else { setActive(point.id); setPinned(true) } }}><CheckpointIcon id={point.id} /></button>
          <span className="roadmap-pin-stem" /><span className="roadmap-pin-dot" /><span className="roadmap-pin-label">{point.label}</span>
        </div>)}
      </div>
      {feature && <div ref={detail} id={detailId} role="tooltip" className={`roadmap-feature roadmap-feature--${feature.side}`} style={position ? { '--measured-left': `${position.left}px`, '--measured-top': `${position.top}px` } : undefined}>
        <span className="roadmap-feature-kicker">BUILT FOR YOUR WORKING DAY</span><h2>{feature.title}</h2><p>{feature.copy}</p>
      </div>}
    </div>}
  </>
}
