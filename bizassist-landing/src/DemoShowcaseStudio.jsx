import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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

export default function DemoShowcaseStudio() {
  const appBase = useMemo(getAppBase, [])
  const registerUrl = useMemo(() => new URL('/register', appBase).href, [appBase])
  const loginUrl = useMemo(() => new URL('/login', appBase).href, [appBase])
  const iframeUrl = useMemo(() => {
    const url = new URL(appBase)
    url.search = 'demo=1&embed=1&tour=1'
    return url.href
  }, [appBase])
  const frameRef = useRef(null)
  const viewportRef = useRef(null)
  const [ready, setReady] = useState(false)
  const [loadError, setLoadError] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [visible, setVisible] = useState(false)
  const [pageVisible, setPageVisible] = useState(!document.hidden)
  const [wantsPlay, setWantsPlay] = useState(() => !window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  const [tour, setTour] = useState({ chapter: 'home', caption: 'A guided look around your sample store.', progress: 0, playing: false })
  const [frameWidth, setFrameWidth] = useState(1120)
  const [frameKey, setFrameKey] = useState(0)
  const playing = wantsPlay && visible && pageVisible
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
        if (data.error || data.complete) {
          setWantsPlay(false)
          setExpanded(false)
        }
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
    if (ready) send(playing ? 'play' : 'pause')
  }, [ready, playing, send])

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

  const pause = () => {
    // Return to the document flow before releasing the body's scroll lock.
    // A fixed expanded panel would keep catching the wheel even if unlocked.
    send('pause')
    setWantsPlay(false)
    setExpanded(false)
  }
  const replay = () => {
    setWantsPlay(true)
    send('restart')
    send(visible && pageVisible ? 'play' : 'pause')
  }
  const togglePlayback = () => {
    if (tour.complete) replay()
    else if (wantsPlay) pause()
    else setWantsPlay(true)
  }
  const toggleExpanded = () => {
    if (expanded) { setExpanded(false); return }
    // An explicitly paused preview must never reopen a fixed scroll trap.
    // Make resuming part of this action, with the button labelled accordingly.
    if (!wantsPlay) {
      if (tour.complete) replay()
      else setWantsPlay(true)
    }
    setExpanded(true)
  }
  const chooseChapter = id => {
    if (!ready) return
    setTour(previous => ({ ...previous, chapter: id, progress: 0, complete: false, error: null }))
    setWantsPlay(true)
    send('chapter', { chapter: id })
    send(visible && pageVisible ? 'play' : 'pause')
  }
  const scale = Math.min(1, frameWidth / 1280)

  return <section className={`demo-studio ${expanded ? 'demo-studio-expanded' : ''}`} aria-label="STATER Bill app tour">
    <div className="demo-studio-heading">
      <div className="demo-studio-heading-copy"><span className="demo-eyebrow"><span className="demo-live-dot" /> THE ACTUAL APP. A PROTECTED PREVIEW.</span>
        <h2>See how a working day flows.</h2>
        <p>Six short chapters. Real screens. Selected advanced workflows are hidden in this preview.</p>
      </div>
      <div className="demo-auth-actions">
        <a className="demo-primary-button" href={registerUrl}>Create your account <span>↗</span></a>
        <a className="demo-text-button" href={loginUrl}>Already use STATER Bill? Sign in →</a>
      </div>
    </div>
    <div className="demo-player">
      <div className="demo-window-bar">
        <div className="demo-window-dots" aria-hidden="true"><i /><i /><i /></div>
        <span className="demo-window-title">STATER Bill <span>/ Guided app tour</span></span>
        <div className="demo-window-actions">
          <span className="demo-sample-label">PROTECTED PREVIEW</span>
          <button className="demo-icon-button" aria-label={expanded ? 'Collapse app preview' : wantsPlay ? 'Expand app preview' : tour.complete ? 'Replay and expand app preview' : 'Resume and expand app preview'} onClick={toggleExpanded}>{expanded ? '↙' : '⛶'}</button>
        </div>
      </div>
      <div ref={viewportRef} className="demo-app-viewport" style={{ height: `${820 * scale}px` }}>
        <iframe key={frameKey} ref={frameRef} src={iframeUrl} title="STATER Bill protected app tour with sample data" className="demo-app-frame" style={{ width: 1280, height: 820, transform: `scale(${scale})` }}
          loading="eager" tabIndex={-1} inert=""
          onLoad={() => { setLoadError(false); send(playing ? 'play' : 'pause') }} />
        {ready && <a className="demo-takeover-surface" href={registerUrl} aria-label="Create your STATER Bill account to explore the full app" />}
        {!ready && <div className="demo-loading" role="status">
          <span className="demo-loading-mark">S<span>•</span></span>
          <strong>{loadError ? 'The app preview is taking a little longer.' : 'Opening your sample store…'}</strong>
          <p>{loadError ? 'Reload the preview to reconnect to the demo app.' : 'Loading the same STATER Bill app your business will use.'}</p>
          {loadError && <button className="demo-primary-button" onClick={() => { setReady(false); setLoadError(false); setFrameKey(key => key + 1) }}>Reload preview ↻</button>}
        </div>}
      </div>
      <div className="demo-playback-bar">
        <div className="demo-playback-controls">
          <button className="demo-play-button" disabled={!ready} onClick={togglePlayback} aria-label={tour.complete ? 'Replay guided tour' : wantsPlay ? 'Pause guided tour' : 'Play guided tour'}>{tour.complete || !wantsPlay ? '▶' : 'Ⅱ'}</button>
          <button className="demo-icon-button" disabled={!ready} onClick={replay} aria-label="Restart tour from Home">↺</button>
          <span className="demo-chapter-count">{String(chapterIndex + 1).padStart(2, '0')} / 06</span>
        </div>
        <div className="demo-caption" aria-live="polite" aria-atomic="true"><strong>{chapter.title}</strong><span>{tour.error ? 'This step could not load. Replay the chapter to try again.' : tour.complete ? 'Tour complete. Create an account or sign in to explore the full app.' : tour.caption}</span></div>
        <div className="demo-playback-auth"><a className="demo-text-button" href={registerUrl}>Get started →</a><a className="demo-text-button" href={loginUrl}>Sign in</a></div>
      </div>
      <div className="demo-progress-track" role="progressbar" aria-label={`${chapter.title} chapter progress`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(tour.progress * 100)}><div style={{ width: `${tour.progress * 100}%` }} /></div>
    </div>
    <div className="demo-chapter-grid" aria-label="Choose a tour chapter">
      {CHAPTERS.map((item, index) => <button key={item.id} disabled={!ready} aria-current={chapter.id === item.id ? 'step' : undefined} onClick={() => chooseChapter(item.id)} className={`demo-chapter-card ${chapter.id === item.id ? 'is-active' : ''}`}>
        <span className="demo-chapter-number">{String(index + 1).padStart(2, '0')}<span aria-hidden="true">↗</span></span>
        <strong>{item.title}</strong><span>{item.detail}</span>
      </button>)}
    </div>
    <div className="demo-chapter-description"><p>{chapter.description}</p><span>Advanced pricing, analytics and inventory calculations are hidden. App Settings, B2B &amp; POS Live remain locked.</span></div>
  </section>
}
