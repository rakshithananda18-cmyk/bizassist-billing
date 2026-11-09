import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import './demoShowcase.css'

const CHAPTERS = [
  { id: 'home', title: 'Home', detail: 'Start your working day', description: 'Your daily overview, quick actions and open shift, together in the real Home workspace.' },
  { id: 'dashboard', title: 'Dashboard', detail: 'Understand your business', description: 'Read sales, payment trends and stock insights using a populated sample business.' },
  { id: 'pos', title: 'Billing Counter', detail: 'Build a bill, step by step', description: 'Find a sample product, add it to the counter and see quantities and totals update.' },
  { id: 'stock', title: 'Stock & Items', detail: 'Find and inspect your stock', description: 'Explore the Stock & Purchases workspace with sample items, prices and available quantities.' },
  { id: 'purchases', title: 'Purchases', detail: 'Follow your supplier bills', description: 'See purchase records and supplier details in the same workspace used by your store.' },
  { id: 'contacts', title: 'Contacts', detail: 'Know your customers and dues', description: 'Search sample contacts and explore their balances without sending any messages.' },
]

function getAppBase() {
  const configured = import.meta.env.VITE_BILLING_APP_URL
  const local = ['localhost', '127.0.0.1'].includes(window.location.hostname)
  return new URL(configured || (local ? `${window.location.protocol}//${window.location.hostname}:5174` : 'https://app.staterbill.com'))
}

function LeadModal({ onClose, onUnlock }) {
  const formRef = useRef(null)
  const [error, setError] = useState('')
  useEffect(() => {
    const previousFocus = document.activeElement
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    formRef.current?.querySelector('input')?.focus()
    const keydown = event => {
      if (event.key === 'Escape') onClose()
      if (event.key !== 'Tab') return
      const controls = [...formRef.current.querySelectorAll('button, input')]
      const first = controls[0]
      const last = controls[controls.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', keydown)
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', keydown)
      previousFocus?.focus()
    }
  }, [onClose])

  const submit = event => {
    event.preventDefault()
    const values = new FormData(event.currentTarget)
    const name = values.get('name').trim()
    const phone = values.get('phone').trim()
    if (!name || !/^\+?[0-9]{7,15}$/.test(phone.replace(/[\s()-]/g, ''))) {
      setError('Enter your name and a valid phone number to continue.')
      return
    }
    try { localStorage.setItem('stater_demo_lead', JSON.stringify({ name, phone, business: values.get('business').trim(), ts: Date.now() })) } catch {}
    onUnlock()
  }

  return createPortal(<div className="demo-studio demo-lead-backdrop" onClick={event => { if (event.target === event.currentTarget) onClose() }}>
    <form ref={formRef} className="demo-lead-dialog" role="dialog" aria-modal="true" aria-labelledby="demo-lead-title" aria-describedby="demo-lead-description" onSubmit={submit}>
      <button type="button" className="demo-icon-button demo-lead-close" aria-label="Close details form" onClick={onClose}>×</button>
      <span className="demo-eyebrow">YOUR TURN AT THE COUNTER</span>
      <h3 id="demo-lead-title">Try the app yourself.</h3>
      <p id="demo-lead-description">Add your details to explore STATER Bill with sample data. No account needed.</p>
      <label htmlFor="demo-lead-name">Your name <span>*</span></label>
      <input id="demo-lead-name" name="name" autoComplete="name" placeholder="Your name" required maxLength={100} />
      <label htmlFor="demo-lead-phone">Phone number <span>*</span></label>
      <input id="demo-lead-phone" name="phone" type="tel" autoComplete="tel" placeholder="+91 98765 43210" required maxLength={24} />
      <label htmlFor="demo-lead-business">Business name <small>Optional</small></label>
      <input id="demo-lead-business" name="business" autoComplete="organization" placeholder="Your shop or company" maxLength={150} />
      {error && <p className="demo-form-error" role="alert">{error}</p>}
      <button type="submit" className="demo-primary-button demo-lead-submit">Explore the demo app <span>→</span></button>
      <p className="demo-lead-note">Your details are remembered in this browser. All activity in the demo uses sample data.</p>
    </form>
  </div>, document.body)
}

export default function DemoShowcaseStudio() {
  const appBase = useMemo(getAppBase, [])
  const iframeUrl = useMemo(() => {
    const url = new URL(appBase)
    url.search = 'demo=1&embed=1&tour=1'
    return url.href
  }, [appBase])
  const frameRef = useRef(null)
  const studioRef = useRef(null)
  const viewportRef = useRef(null)
  const pendingAction = useRef('sandbox')
  const pendingChapter = useRef(null)
  const modeRef = useRef('tour')
  const [mode, setMode] = useState('tour')
  const [ready, setReady] = useState(false)
  const [loadError, setLoadError] = useState(false)
  const [showLead, setShowLead] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [visible, setVisible] = useState(false)
  const [pageVisible, setPageVisible] = useState(!document.hidden)
  const [wantsPlay, setWantsPlay] = useState(() => !window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  const [tour, setTour] = useState({ chapter: 'home', caption: 'A guided look around your sample store.', progress: 0, playing: false })
  const [frameWidth, setFrameWidth] = useState(1120)
  const [frameKey, setFrameKey] = useState(0)
  const playing = wantsPlay && visible && pageVisible && !showLead && mode === 'tour'
  const chapterIndex = Math.max(0, CHAPTERS.findIndex(chapter => chapter.id === tour.chapter))
  const chapter = CHAPTERS[chapterIndex]

  const send = useCallback((command, extra = {}) => {
    frameRef.current?.contentWindow?.postMessage({ type: 'stater-tour:command', command, ...extra }, appBase.origin)
  }, [appBase])

  useEffect(() => {
    const receive = event => {
      if (event.source !== frameRef.current?.contentWindow || event.origin !== appBase.origin) return
      const data = event.data
      if (data?.type === 'stater-tour:ready') { setReady(true); setLoadError(false) }
      if (data?.type === 'stater-tour:state' && CHAPTERS.some(item => item.id === data.chapter)) {
        setReady(true)
        setTour({ ...data, progress: Math.max(0, Math.min(1, Number(data.progress) || 0)) })
        if (data.error) setWantsPlay(false)
        if (data.complete) setWantsPlay(false)
      }
    }
    window.addEventListener('message', receive)
    return () => window.removeEventListener('message', receive)
  }, [appBase])

  useEffect(() => {
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting), { threshold: 0.15 })
    observer.observe(viewportRef.current)
    const resize = new ResizeObserver(([entry]) => setFrameWidth(entry.contentRect.width))
    resize.observe(viewportRef.current)
    const visibility = () => setPageVisible(!document.hidden)
    document.addEventListener('visibilitychange', visibility)
    return () => { observer.disconnect(); resize.disconnect(); document.removeEventListener('visibilitychange', visibility) }
  }, [])

  useEffect(() => {
    if (!ready) return
    if (mode === 'tour' && pendingChapter.current) {
      send('chapter', { chapter: pendingChapter.current })
      pendingChapter.current = null
    }
    send(mode === 'sandbox' ? 'sandbox' : playing ? 'play' : 'pause')
  }, [ready, mode, playing, send])

  useEffect(() => {
    if (ready) return
    const timeout = setTimeout(() => setLoadError(true), 20000)
    return () => clearTimeout(timeout)
  }, [ready, frameKey])

  useEffect(() => {
    if (!expanded) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const escape = event => { if (event.key === 'Escape') setExpanded(false) }
    window.addEventListener('keydown', escape)
    return () => { document.body.style.overflow = previousOverflow; window.removeEventListener('keydown', escape) }
  }, [expanded])

  const unlock = useCallback(() => {
    setShowLead(false)
    if (pendingAction.current === 'open') {
      const url = new URL(appBase)
      url.search = 'demo=1'
      window.open(url.href, '_blank', 'noopener,noreferrer')
    } else {
      modeRef.current = 'sandbox'
      setMode('sandbox')
      send('sandbox')
    }
  }, [appBase, send])
  const closeLead = useCallback(() => setShowLead(false), [])
  const takeControl = (action = 'sandbox') => {
    pendingAction.current = action
    let lead
    try { lead = JSON.parse(localStorage.getItem('stater_demo_lead') || 'null') } catch {}
    if (lead?.name && lead?.phone) unlock()
    else { send('pause'); setShowLead(true) }
  }
  const replay = () => {
    const wasSandbox = modeRef.current === 'sandbox'
    modeRef.current = 'tour'
    setMode('tour')
    setWantsPlay(true)
    if (wasSandbox) {
      setReady(false)
      setTour({ chapter: 'home', caption: 'A guided look around your sample store.', progress: 0, playing: false })
      setFrameKey(key => key + 1)
      return
    }
    send('restart')
    send(visible && pageVisible ? 'play' : 'pause')
  }
  const chooseChapter = id => {
    if (!ready) return
    if (modeRef.current === 'sandbox') {
      pendingChapter.current = id
      replay()
      return
    }
    setTour(previous => ({ ...previous, chapter: id, progress: 0, complete: false, error: null }))
    setWantsPlay(true)
    send('chapter', { chapter: id })
    send(visible && pageVisible ? 'play' : 'pause')
  }
  const appWidth = mode === 'sandbox' ? frameWidth : 1280
  const appHeight = mode === 'sandbox' ? 760 : 820
  const scale = mode === 'sandbox' ? 1 : Math.min(1, frameWidth / appWidth)

  return <section ref={studioRef} className={`demo-studio ${expanded ? 'demo-studio-expanded' : ''}`} aria-label="STATER Bill app tour">
    {showLead && <LeadModal onClose={closeLead} onUnlock={unlock} />}
    <div className="demo-studio-heading">
      <div className="demo-studio-heading-copy"><span className="demo-eyebrow"><span className="demo-live-dot" /> THE ACTUAL APP. A SAMPLE STORE.</span>
        <h2>See how a working day flows.</h2>
        <p>Six short chapters. Real screens. Follow the cursor, then try it yourself.</p>
      </div>
      <button className="demo-primary-button" onClick={() => takeControl()}>Try it yourself <span>↗</span></button>
    </div>
    <div className="demo-player">
      <div className="demo-window-bar">
        <div className="demo-window-dots" aria-hidden="true"><i /><i /><i /></div>
        <span className="demo-window-title">STATER Bill <span>/ {mode === 'tour' ? 'Guided app tour' : 'Your demo workspace'}</span></span>
        <div className="demo-window-actions">
          <span className="demo-sample-label">SAMPLE DATA</span>
          <button className="demo-icon-button" aria-label={expanded ? 'Collapse app preview' : 'Expand app preview'} onClick={() => setExpanded(value => !value)}>{expanded ? '↙' : '⛶'}</button>
          {mode === 'sandbox' && <button className="demo-icon-button" aria-label="Open demo in a new tab" onClick={() => takeControl('open')}>↗</button>}
        </div>
      </div>
      <div ref={viewportRef} className="demo-app-viewport" style={{ height: `${appHeight * scale}px` }}>
        <iframe key={frameKey} ref={frameRef} src={iframeUrl} title="STATER Bill real app with sample data" className="demo-app-frame" style={{ width: appWidth, height: appHeight, transform: `scale(${scale})` }}
          loading="eager" tabIndex={mode === 'tour' ? -1 : 0} inert={mode === 'tour' ? '' : undefined}
          onLoad={() => { setLoadError(false); send(modeRef.current === 'sandbox' ? 'sandbox' : playing ? 'play' : 'pause') }} />
        {mode === 'tour' && ready && <button className="demo-takeover-surface" onClick={() => takeControl()} aria-label="Take control of the demo app; enter your details to continue" />}
        {!ready && <div className="demo-loading" role="status">
          <span className="demo-loading-mark">S<span>•</span></span>
          <strong>{loadError ? 'The app preview is taking a little longer.' : 'Opening your sample store…'}</strong>
          <p>{loadError ? 'Reload the preview to reconnect to the demo app.' : 'Loading the same STATER Bill app your business will use.'}</p>
          {loadError && <button className="demo-primary-button" onClick={() => { setReady(false); setLoadError(false); setFrameKey(key => key + 1) }}>Reload preview ↻</button>}
        </div>}
      </div>
      <div className="demo-playback-bar">
        <div className="demo-playback-controls">
          <button className="demo-play-button" disabled={!ready} onClick={() => mode === 'sandbox' || tour.complete ? replay() : setWantsPlay(value => !value)} aria-label={mode === 'sandbox' || tour.complete ? 'Replay guided tour' : wantsPlay ? 'Pause guided tour' : 'Play guided tour'}>{mode === 'sandbox' || tour.complete || !wantsPlay ? '▶' : 'Ⅱ'}</button>
          <button className="demo-icon-button" disabled={!ready} onClick={replay} aria-label="Restart tour from Home">↺</button>
          <span className="demo-chapter-count">{String(chapterIndex + 1).padStart(2, '0')} / 06</span>
        </div>
        <div className="demo-caption" aria-live="polite" aria-atomic="true"><strong>{mode === 'sandbox' ? 'You’re in control.' : chapter.title}</strong><span>{mode === 'sandbox' ? 'Explore the app with sample data. Return to the tour whenever you like.' : tour.error ? 'This step could not load. Replay the chapter to try again.' : tour.complete ? 'Tour complete. Replay a chapter or try the app yourself.' : tour.caption}</span></div>
        <button className="demo-text-button" onClick={() => mode === 'tour' ? takeControl() : replay()}>{mode === 'tour' ? 'Take control →' : 'Back to tour →'}</button>
      </div>
      <div className="demo-progress-track" role="progressbar" aria-label={`${chapter.title} chapter progress`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(tour.progress * 100)}><div style={{ width: `${tour.progress * 100}%` }} /></div>
    </div>
    <div className="demo-chapter-grid" aria-label="Choose a tour chapter">
      {CHAPTERS.map((item, index) => <button key={item.id} disabled={!ready} aria-current={chapter.id === item.id ? 'step' : undefined} onClick={() => chooseChapter(item.id)} className={`demo-chapter-card ${chapter.id === item.id && mode === 'tour' ? 'is-active' : ''}`}>
        <span className="demo-chapter-number">{String(index + 1).padStart(2, '0')}<span aria-hidden="true">↗</span></span>
        <strong>{item.title}</strong><span>{item.detail}</span>
      </button>)}
    </div>
    <div className="demo-chapter-description"><p>{chapter.description}</p><span>App Settings, B2B &amp; POS Live are locked in the demo.</span></div>
  </section>
}
