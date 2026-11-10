import React, { useEffect, useId, useRef, useState } from 'react'
import './TaskLoginScene.css'

const BENEFITS = [
  { id: 'plan', label: 'Plan the day', x: '14%', y: '35%', side: 'left', title: 'A clear plan before the first stop.', copy: 'Bring routes, shops and daily assignments together, so your team knows where to go next.' },
  { id: 'tasks', label: 'Keep work moving', x: '19%', y: '70%', side: 'left', title: 'Every task has a next step.', copy: 'Assign work, follow its progress and keep shop requests connected to the people handling them.' },
  { id: 'visits', label: 'See the field', x: '79%', y: '26%', side: 'right', title: 'Stay connected beyond the office.', copy: 'See the live map and shop visits alongside your team’s day plan.' },
  { id: 'team', label: 'Bring it together', x: '81%', y: '68%', side: 'right', title: 'Make the day’s work visible.', copy: 'Review attendance and team scorecards in the same workspace as your field operations.' },
]

function Symbol({ kind }) {
  return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {kind === 'plan' && <><rect x="4" y="5" width="16" height="16" rx="3" /><path d="M8 3v4m8-4v4M4 10h16M8 14h3m2 3h3" /></>}
    {kind === 'tasks' && <><path d="m3 6 2 2 3-4m3 2h10M3 13l2 2 3-4m3 2h10M3 20l2 2 3-4m3 2h10" /></>}
    {kind === 'visits' && <><path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 0 1 14 0Z" /><circle cx="12" cy="10" r="2.5" /></>}
    {kind === 'team' && <><circle cx="9" cy="8" r="3" /><path d="M3 21v-3a6 6 0 0 1 12 0v3m0-16a3 3 0 0 1 0 6m3 3a5 5 0 0 1 3 4v3" /></>}
  </svg>
}

function FieldDoodles() {
  return <svg className="task-field-art" viewBox="0 0 1600 1000" fill="none" aria-hidden="true" preserveAspectRatio="none">
    <g stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
      <g opacity=".1" strokeWidth="1"><path d="M80 0v1000m200-1000v1000m200-1000v1000m640-1000v1000m200-1000v1000m200-1000v1000M0 100h1600M0 300h1600M0 500h1600M0 700h1600M0 900h1600" strokeDasharray="1 12" /></g>
      <path className="task-field-route" d="M-60 845c180 65 391-20 385-143s-180-127-161-268 223-275 309-173M1130 650c230 116 395-29 320-151s-255 17-267-107 102-240 285-230 186-52 186-52" strokeWidth="2" strokeDasharray="5 10" opacity=".32" />
      <g transform="translate(332 210) rotate(-10)" opacity=".34" strokeWidth="1.5">
        <rect x="0" y="0" width="124" height="154" rx="9" fill="var(--task-doodle-fill)" />
        <path d="M23 0v154M-5 24h15m-15 26h15m-15 26h15m-15 26h15m-15 26h15M39 28h62" />
        <path d="m39 55 4 4 7-9m9 6h40m-60 24 4 4 7-9m9 6h29m-49 24 4 4 7-9m9 6h34" stroke="var(--task-scene-accent)" />
        <path d="m145 18 8 3-28 91-9 9-1-13Z" /><path d="m145 18 3-9 8 3-3 9m-37 100 9-9" />
      </g>
      <g transform="translate(65 575) rotate(9)" opacity=".3" strokeWidth="1.5">
        <path d="M0 0 66 13 122-8 180 6v124l-58-14-56 20L0 121Z" fill="var(--task-doodle-fill)" />
        <path d="M66 13v123m56-144v124M12 79l40-32 28 15 26-25 28 17 30-22" strokeDasharray="3 6" />
        <path d="M104 9c0 20-18 39-18 39S68 29 68 9a18 18 0 1 1 36 0Z" stroke="var(--task-scene-accent)" fill="var(--task-doodle-fill)" /><circle cx="86" cy="9" r="6" stroke="var(--task-scene-accent)" />
      </g>
      <g transform="translate(1305 135)" opacity=".34" strokeWidth="1.5">
        <path d="M0 35h162v91H0Z" fill="var(--task-doodle-fill)" /><path d="m-8 35 10-26h158l10 26Zm15 0v-9m20 9v-9m20 9v-9m20 9v-9m20 9v-9m20 9v-9m20 9v-9m20 9v-9" stroke="var(--task-scene-accent)" />
        <path d="M18 67h47v59H18Zm68 0h57v35H86Zm-38 34h7M20-1h119v10H20Z" /><path d="M94 82h40" />
        <path d="M-13 132h190m-172 7h155" opacity=".5" />
      </g>
      <g transform="translate(1315 695) rotate(11)" opacity=".3" strokeWidth="1.5">
        <rect width="92" height="169" rx="14" fill="var(--task-doodle-fill)" /><path d="M29 8h34m-23 151h13M10 24h72v116H10Z" />
        <circle cx="46" cy="72" r="24" stroke="var(--task-scene-accent)" /><path d="m34 72 8 8 17-19M24 113h45m-35 10h25" stroke="var(--task-scene-accent)" />
      </g>
      <g transform="translate(1457 441) rotate(-16)" opacity=".28" strokeWidth="1.5"><path d="m0 0 76-34-23 69-14-25Z" fill="var(--task-doodle-fill)" /><path d="m39 10 37-44-27 51m-26 9-19 11m17 1L4 48" /></g>
      <g opacity=".26" strokeWidth="1.5"><circle cx="415" cy="800" r="29" /><path d="m401 800 10 10 19-23M1300 412h24m-12-12v24M86 249h20m-10-10v20M1463 902h22m-11-11v22" stroke="var(--task-scene-accent)" /><circle cx="343" cy="135" r="4" /><circle cx="1492" cy="356" r="5" /><path d="m109 784 19 7-12 13m-2-12-24 2m1168-623 18 9-15 10m-1-11-23-1" /></g>
    </g>
  </svg>
}

export default function TaskLoginScene() {
  const [active, setActive] = useState(null)
  const region = useRef(null)
  const details = useRef(null)
  const id = `field-story-${useId().replace(/:/g, '')}`
  const benefit = BENEFITS.find(item => item.id === active)

  useEffect(() => {
    const dismiss = event => { if (!region.current?.contains(event.target)) setActive(null) }
    const escape = event => { if (event.key === 'Escape') setActive(null) }
    document.addEventListener('pointerdown', dismiss)
    document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('pointerdown', dismiss); document.removeEventListener('keydown', escape) }
  }, [])

  useEffect(() => {
    if (active && window.innerWidth <= 1100) details.current?.scrollIntoView?.({ block: 'nearest', behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
  }, [active])

  return <>
    <div className="task-field-scene" aria-hidden="true"><FieldDoodles /><div className="task-field-caption"><p>A good day,<br />out in the field.</p><span>Small plans. Shared progress. Better days.</span></div></div>
    <section className="task-field-checkpoints" ref={region} aria-label="Explore Field Team benefits" onBlur={event => { if (event.relatedTarget && !event.currentTarget.contains(event.relatedTarget)) setActive(null) }}>
      <p className="task-field-mobile-title">A more connected working day.</p>
      <div className="task-field-pins">{BENEFITS.map(item => <button key={item.id} type="button" className={`task-field-pin ${active === item.id ? 'is-active' : ''}`} style={{ '--field-x': item.x, '--field-y': item.y }} aria-label={item.label} aria-expanded={active === item.id} aria-controls={active === item.id ? id : undefined} onPointerEnter={event => { if (event.pointerType !== 'touch') setActive(item.id) }} onFocus={() => setActive(item.id)} onClick={() => setActive(item.id)}><Symbol kind={item.id} /><span>{item.label}</span></button>)}</div>
      {benefit && <div className={`task-field-story task-field-story--${benefit.side}`} id={id} ref={details} role="tooltip"><span className="task-field-eyebrow">YOUR TEAM, IN SYNC</span><h2>{benefit.title}</h2><p>{benefit.copy}</p></div>}
    </section>
  </>
}
