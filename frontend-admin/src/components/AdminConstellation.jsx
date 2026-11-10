import { useEffect, useId, useRef, useState } from 'react'

const POINTS = [
  { id: 'businesses', label: 'Businesses', title: 'A whole network. A personal view.', copy: 'Find business accounts, review plans and access, and open the records you need to support each store.', x: 14, y: 27, side: 'left' },
  { id: 'adoption', label: 'Adoption', title: 'See the bigger picture.', copy: 'Follow activation, plan mix and business activity to understand where the platform is growing.', x: 17, y: 74, side: 'left' },
  { id: 'health', label: 'Service health', title: 'Keep the foundations in view.', copy: 'Review service health, infrastructure and audit results from your operations workspace.', x: 85, y: 27, side: 'right' },
  { id: 'telemetry', label: 'Diagnostics', title: 'Follow the signal to the source.', copy: 'Explore business and device telemetry, then use events and logs to take a closer look at an issue.', x: 83, y: 74, side: 'right' },
]

function OrbitIcon({ id }) {
  return <svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {id === 'businesses' && <><path d="M3 21h18M5 21V9h6v12m2 0V3h6v18M7 12h2m-2 4h2m6-9h2m-2 4h2m-2 4h2" /></>}
    {id === 'adoption' && <><path d="M4 19V5m0 14h16M7 15l4-5 4 2 5-7m-5 0h5v5" /></>}
    {id === 'health' && <><path d="M3 12h4l3-7 4 14 3-7h4" /><circle cx="12" cy="12" r="10" /></>}
    {id === 'telemetry' && <><circle cx="10" cy="10" r="6" /><path d="m15 15 6 6M6 10h2l1-2 2 4 1-2h2" /></>}
  </svg>
}

/** The operations portal has its own quiet atlas, rather than the billing app's town. */
export default function AdminConstellation() {
  const [active, setActive] = useState(null)
  const [pinned, setPinned] = useState(false)
  const region = useRef(null)
  const detail = useRef(null)
  const id = `admin-orbit-${useId().replace(/:/g, '')}`
  const feature = POINTS.find(point => point.id === active)

  function close() { setActive(null); setPinned(false) }

  useEffect(() => {
    const onPointerDown = event => { if (!region.current?.contains(event.target)) close() }
    const onKeyDown = event => { if (event.key === 'Escape') close() }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [])

  useEffect(() => {
    if (feature && window.innerWidth <= 1050) {
      const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
      detail.current?.scrollIntoView?.({ block: 'nearest', behavior: reduced ? 'auto' : 'smooth' })
    }
  }, [feature])

  return <>
    <div className="admin-observatory" aria-hidden="true">
      <svg className="admin-observatory-art" viewBox="0 0 1600 1000" fill="none" preserveAspectRatio="xMidYMid slice" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
        <g opacity=".13">
          <ellipse cx="800" cy="500" rx="646" ry="346" transform="rotate(-14 800 500)" />
          <ellipse cx="800" cy="500" rx="690" ry="390" transform="rotate(16 800 500)" strokeDasharray="2 11" />
          <path d="M210 235c120 50 150 181 292 220m816-235c-120 50-170 170-237 206M272 760c109-34 119-119 235-166m812 145c-110-25-154-103-241-140" />
          <path d="M70 500h1460M800 65v870" strokeDasharray="2 15" opacity=".4" />
        </g>

        {/* A small network of businesses, drawn as an architectural study. */}
        <g transform="translate(128 92)" opacity=".32">
          <path d="m0 71 56-26 61 25-56 28Zm0 0v68l61 29 56-28V70M61 98v70" />
          <path d="m61 98 56-28M0 71l12-17 61 27-12 17m-48-34 9-6 61 27m-48-20 8-6 61 27" stroke="var(--entry-clay)" />
          <path d="m15 95 26 12v37l-26-12Zm57 17 31-15v24l-31 16ZM15 116l26 12m44-22v25" />
          <path d="m130 63 44-20 51 21-45 23Zm0 0v72l50 24 45-22V64m-45 23v72m-37-78 22 10v25l-22-10Zm48 13 21-10v29l-21 10Z" />
          <path d="m174 43 1-23 50 21v23M175 20l-45 19v24m55-27 11 5m-11 7 11 5" opacity=".7" />
          <path d="m-16 156 70 33 183-45m-253 20 70 33 183-45" opacity=".45" />
          <path d="M40 32V11m-8 0h16M29 27l11 5 11-5" stroke="var(--entry-clay)" opacity=".8" />
        </g>

        {/* An instrument rack and radio signal for the platform's foundations. */}
        <g transform="translate(1283 92)" opacity=".3">
          <path d="m0 25 27-16h115l-27 16ZM0 25h115v133H0Zm115 0 27-16v132l-27 17" />
          <path d="M13 42h89v29H13Zm0 40h89v29H13Zm0 40h89v23H13Z" />
          <path d="M26 56h38m-38 40h38m-38 38h38" opacity=".55" />
          <circle cx="87" cy="56" r="2" stroke="var(--entry-clay)" /><circle cx="87" cy="96" r="2" stroke="var(--entry-clay)" /><circle cx="87" cy="134" r="2" stroke="var(--entry-clay)" />
          <path d="M169 146V74m-11 0h22m-11 0 10-9m-10 9-10-9m10 0V48m-15 8c-13-13-13-31 0-44m30 44c13-13 13-31 0-44m-22 36c-8-8-8-18 0-26m14 26c8-8 8-18 0-26" />
          <path d="m-14 171 140 2 73-28m-210 34 138 2 72-28" opacity=".4" />
        </g>

        {/* An open notebook carries the adoption story, without invented figures. */}
        <g transform="translate(117 776) rotate(-9)" opacity=".3">
          <path d="M0 0c37-8 68-5 104 10 36-15 67-18 104-10v99c-37-8-68-5-104 10-36-15-67-18-104-10V0Zm104 10v99M9 109c33-5 62-1 95 11 33-12 62-16 95-11" />
          <path d="M21 22h53M21 33h41M21 46h53M21 57h31m67 30V35m0 52h66m-53-16 12-16 13 5 21-27m-10 0h10v10" stroke="var(--entry-clay)" />
          <path d="m231 25 6-6 24 27-6 6Zm24 27 10 5-4-11m-29-22-3-4 7-6 4 4" />
          <circle cx="-27" cy="63" r="13" /><path d="M-40 63h26m-13-13v26" opacity=".45" />
        </g>

        {/* A magnifier and connected traces make diagnostics a different visual story. */}
        <g transform="translate(1274 755)" opacity=".3">
          <circle cx="79" cy="43" r="47" /><circle cx="79" cy="43" r="37" opacity=".55" />
          <path d="m111 77 49 49m-39-58 50 49-11 9m-106-73h12l9-19 13 29 9-15h8" stroke="var(--entry-clay)" />
          <path d="M-34 15h46m-46 18H0m-34 18h44m-44 18h33m-23 34h68m-68 14h40m66-120v-23h48v23m-48-12h48" opacity=".65" />
          <circle cx="-43" cy="15" r="2" /><circle cx="-43" cy="33" r="2" /><circle cx="-43" cy="51" r="2" /><circle cx="-43" cy="69" r="2" />
          <path d="M174-7h15m-7-7v14M-25 133h22m-11-11v22" opacity=".55" />
        </g>
        <g stroke="var(--entry-clay)" opacity=".32">
          <path d="m381 608 3 8 8 3-8 3-3 8-3-8-8-3 8-3Zm806-205 3 8 8 3-8 3-3 8-3-8-8-3 8-3Z" />
          <circle cx="422" cy="205" r="3" /><circle cx="1162" cy="798" r="3" /><circle cx="1450" cy="504" r="2" /><circle cx="98" cy="579" r="2" />
        </g>
      </svg>
      <div className="admin-observatory-caption"><span>THE OPERATIONS OBSERVATORY</span><p>Every business.<br />A clearer perspective.</p></div>
    </div>
    <div className="admin-orbit-controls" ref={region} role="group" aria-label="Explore the admin workspace" onBlur={event => { if (event.relatedTarget && !event.currentTarget.contains(event.relatedTarget)) close() }}>
      <p className="admin-orbit-mobile-heading">One connected operations workspace.</p>
      <div className="admin-orbit-points">
        {POINTS.map(point => <div key={point.id} className={`admin-orbit-point ${active === point.id ? 'is-active' : ''}`} style={{ '--orbit-x': `${point.x}%`, '--orbit-y': `${point.y}%` }} onPointerEnter={event => { if (event.pointerType !== 'touch' && !pinned) setActive(point.id) }}>
          <button type="button" aria-label={`Explore ${point.label.toLowerCase()}`} aria-expanded={active === point.id} aria-describedby={active === point.id ? id : undefined} onFocus={() => { setActive(point.id); setPinned(false) }} onClick={() => { if (pinned && active === point.id) close(); else { setActive(point.id); setPinned(true) } }}><OrbitIcon id={point.id} /></button><span>{point.label}</span>
        </div>)}
      </div>
      {feature && <div ref={detail} id={id} role="tooltip" className={`admin-orbit-detail admin-orbit-detail--${feature.side}`}><span>CONNECTED OPERATIONS</span><h2>{feature.title}</h2><p>{feature.copy}</p></div>}
    </div>
  </>
}
