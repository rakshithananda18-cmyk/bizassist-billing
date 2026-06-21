import { useState, useRef, useEffect, useCallback } from 'react'
import { Icon } from '../icons'

const PW = 300, PH = 260, GAP = 6, PAD = 10

/** Sparkle chip (left of feedback) → floating popover of the memories used. */
export default function MemoryChip({ facts = [] }) {
  const [open, setOpen] = useState(false)
  const [pos, setPos]   = useState(null)
  const rootRef = useRef(null)
  const btnRef  = useRef(null)

  const place = useCallback(() => {
    if (!btnRef.current) return
    const r = btnRef.current.getBoundingClientRect()
    const left = Math.min(Math.max(r.left, PAD), window.innerWidth - PW - PAD)
    const spaceBelow = window.innerHeight - r.bottom
    const top = spaceBelow >= PH + GAP ? r.bottom + GAP : Math.max(PAD, r.top - PH - GAP)
    setPos({ top, left })
  }, [])

  useEffect(() => {
    if (!open) return
    place()                                          // initial + re-flip on scroll/resize
    const onDoc = (e) => { if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false) }
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    window.addEventListener('scroll', place, true)   // follow the anchor, don't close
    window.addEventListener('resize', place)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', place, true)
      window.removeEventListener('resize', place)
    }
  }, [open, place])

  if (!facts || facts.length === 0) return null

  const btn = {
    background: 'transparent', border: 'none', cursor: 'pointer',
    opacity: open ? 1 : 0.5, padding: '2px 4px', lineHeight: 0,
    color: open ? 'var(--accent-color)' : 'inherit', display: 'inline-flex',
  }

  return (
    <span className="mem-chip" ref={rootRef} style={{ display: 'inline-flex' }}>
      <button ref={btnRef} type="button" style={btn}
        title={`${facts.length} business ${facts.length === 1 ? 'memory' : 'memories'} used`}
        aria-label="Business memories used" onClick={() => setOpen(o => !o)}>
        <Icon name="sparkle" size={15} />
      </button>

      {open && pos && (
        <div className="bz-popover" onClick={e => e.stopPropagation()}
          style={{ position: 'fixed', top: pos.top, left: pos.left, width: PW, maxHeight: PH, overflowY: 'auto', zIndex: 1000 }}>
          <div className="bz-popover-head">
            <span className="bz-popover-title"><Icon name="memory" size={14} style={{ color: 'var(--accent-color)' }} /> Business Memories</span>
            <button className="bz-popover-close" onClick={() => setOpen(false)} aria-label="Close"><Icon name="x" size={14} /></button>
          </div>
          <div className="bz-popover-sub">Used for this answer.</div>
          <div className="bz-popover-list">
            {facts.map((f, i) => (
              <div key={i} className="memory-fact">
                <span className="memory-fact-cat">{(f.category || 'other').replace(/_/g, ' ')}</span>
                {f.fact_text}
              </div>
            ))}
          </div>
        </div>
      )}
    </span>
  )
}
