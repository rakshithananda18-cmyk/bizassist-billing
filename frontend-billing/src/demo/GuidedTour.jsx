import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { resetDemoData } from './demoEngine'
import { guidedTourSteps } from './guidedTourSteps'
import { isAllowedTourOrigin, isEmbeddedGuidedTour, isTourCommand, TourClock } from './guidedTourRuntime'
import './guidedTour.css'

function setInputValue(element, value) {
  const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  Object.getOwnPropertyDescriptor(prototype, 'value').set.call(element, value)
  element.dispatchEvent(new Event('input', { bubbles: true }))
  element.dispatchEvent(new Event('change', { bubbles: true }))
}

function isRendered(element) {
  const rect = element.getBoundingClientRect()
  const style = getComputedStyle(element)
  return element.isConnected && rect.width > 0 && rect.height > 0 && !element.disabled && style.visibility !== 'hidden' && style.visibility !== 'collapse' && style.display !== 'none'
}

function visibleTarget(selector) {
  return [...document.querySelectorAll(selector)].find(element => {
    return isRendered(element)
  })
}

function isUncovered(element) {
  if (!isRendered(element)) return false
  // A programmatic click bypasses browser hit testing. Respect real blocking
  // dialogs before looking for a visible point on the target beneath them.
  const dialogs = document.querySelectorAll('[role="dialog"][aria-modal="true"], .modal-overlay, .drawer-overlay')
  if ([...dialogs].some(dialog => isRendered(dialog) && !dialog.contains(element))) return false
  const rect = element.getBoundingClientRect()
  const left = Math.max(0, rect.left), top = Math.max(0, rect.top)
  const right = Math.min(window.innerWidth, rect.right), bottom = Math.min(window.innerHeight, rect.bottom)
  if (right <= left || bottom <= top) return false
  // DOM-only environments have no hit-testing API. Browser playback always
  // uses it so sticky headers, popovers and other overlays also block input.
  if (typeof document.elementFromPoint !== 'function') return true
  const hit = document.elementFromPoint((left + right) / 2, (top + bottom) / 2)
  return Boolean(hit && (element === hit || element.contains(hit)))
}

export default function GuidedTour() {
  const navigate = useNavigate()
  // BrowserRouter can replace navigate when pathname changes. Keep the tour
  // session alive across its own chapter navigation.
  const navigateRef = useRef(navigate)
  navigateRef.current = navigate
  const { user, isDemoMode } = useAuth()
  const eligible = useRef(isEmbeddedGuidedTour())
  const [pointer, setPointer] = useState(null)
  const playing = useRef(false)
  const generation = useRef(0)
  const enabled = eligible.current && Boolean(user?.is_demo || isDemoMode)

  useEffect(() => {
    if (!enabled) return
    let parentOrigin = null
    let mounted = true
    let tourActive = true
    let running = false
    let handshakeComplete = false
    let chapterIndex = 0
    let cursorPosition = { x: 42, y: 44 }
    let report = { chapter: 'home', step: 0, caption: 'Start at Home and explore the real STATER Bill app.', progress: 0, playing: false }
    const allowed = origin => isAllowedTourOrigin(origin, import.meta.env.VITE_LANDING_URL)
    try {
      const referrerOrigin = new URL(document.referrer).origin
      if (allowed(referrerOrigin)) parentOrigin = referrerOrigin
    } catch { /* A trusted command may establish the parent when Referrer-Policy omits it. */ }

    const post = data => {
      if (parentOrigin && mounted) window.parent.postMessage(data, parentOrigin)
    }
    const update = next => {
      report = { ...report, ...next, playing: playing.current }
      post({ type: 'stater-tour:state', ...report })
    }
    const playbackMode = active => window.dispatchEvent(new CustomEvent('stater-tour:playback', { detail: { active } }))

    async function run(startChapter, reset = false) {
      const runGeneration = ++generation.current
      running = true
      if (reset) resetDemoData()
      const clockOptions = { active: () => playing.current, cancelled: () => !mounted || runGeneration !== generation.current }
      const clock = new TourClock(clockOptions)
      const motionClock = new TourClock({ ...clockOptions, tick: 16 })
      const target = async selector => {
        let attempts = 0
        while (attempts < 140) {
          await clock.gate()
          const element = visibleTarget(selector)
          if (element) {
            element.scrollIntoView?.({ behavior: 'instant', block: 'nearest', inline: 'nearest' })
            await clock.wait(100)
            if (isUncovered(element)) return element
          }
          await clock.wait(100)
          attempts++
        }
        throw new Error('This page is taking longer to load. Choose a chapter to try again.')
      }
      try {
        for (let index = startChapter; index < guidedTourSteps.length; index++) {
          chapterIndex = index
          const chapter = guidedTourSteps[index]
          if (chapter.id === 'pos' && user?.is_demo) {
            // Only the sample user's persisted cart is reset. Store owners'
            // per-terminal drafts have separate user keys and are untouched.
            try {
              const uid = user.user_id || user.id
              localStorage.removeItem(`pos_minimized_tabs_${uid}`)
              localStorage.removeItem(`pos_minimized_active_id_${uid}`)
            } catch { /* Playback also works when browser storage is unavailable. */ }
          }
          // Remount the real route to clear old dialogs, searches and the sample
          // cart. The controller is a sibling and keeps its playback state.
          window.dispatchEvent(new Event('stater-tour:reset-page'))
          navigateRef.current(`${chapter.route}?demo=1&embed=1&tour=1`, { replace: true })
          setPointer(current => current && { ...current, hideFocus: true, clicking: false })
          update({ chapter: chapter.id, step: 0, caption: chapter.steps[0].caption, progress: 0, complete: false, error: null })
          await clock.wait(850)
          for (let stepIndex = 0; stepIndex < chapter.steps.length; stepIndex++) {
            const step = chapter.steps[stepIndex]
            update({ step: stepIndex, caption: step.caption, progress: stepIndex / chapter.steps.length })
            let element = await target(step.target)
            await clock.gate()
            element.scrollIntoView?.({ behavior: 'instant', block: 'nearest', inline: 'nearest' })
            const rect = element.getBoundingClientRect()
            const width = Math.min(rect.width, window.innerWidth - Math.max(0, rect.left) - 5)
            const height = Math.min(rect.height, window.innerHeight - Math.max(0, rect.top) - 5)
            const destination = { x: Math.min(window.innerWidth - 28, rect.left + Math.min(rect.width * .6, 220)), y: Math.min(window.innerHeight - 32, rect.top + Math.min(rect.height * .5, 90)) }
            const start = { ...cursorPosition }
            setPointer({ left: Math.max(3, rect.left - 3), top: Math.max(3, rect.top - 3), width: Math.max(12, width + 6), height: Math.max(12, height + 6), ...start, clicking: false, hideFocus: true })
            if (!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
              let lastFraction = -1
              await motionClock.wait(1200, fraction => {
                if (fraction === lastFraction) return
                lastFraction = fraction
                // Smooth start and stop with no overshoot. The playback clock
                // freezes motion as well as actions when the video is paused.
                const eased = fraction * fraction * (3 - 2 * fraction)
                cursorPosition = { x: start.x + (destination.x - start.x) * eased, y: start.y + (destination.y - start.y) * eased }
                setPointer(current => current && { ...current, ...cursorPosition })
              })
            }
            cursorPosition = destination
            setPointer(current => current && { ...current, ...destination, hideFocus: false })
            await clock.gate()
            if (step.click || step.input !== undefined) {
              element = await target(step.target)
              await clock.gate()
              setPointer(current => current && { ...current, clicking: true })
              if (step.click) element.click()
              else {
                element.focus({ preventScroll: true })
                if (element.type === 'number') setInputValue(element, step.input)
                else {
                  setInputValue(element, '')
                  for (let count = 1; count <= step.input.length; count++) {
                    await clock.wait(150)
                    await clock.gate()
                    element = await target(step.target)
                    await clock.gate()
                    setInputValue(element, step.input.slice(0, count))
                  }
                }
              }
              await clock.wait(500)
              setPointer(current => current && { ...current, clicking: false, hideFocus: !isRendered(element) })
            }
            let lastReport = 0
            await clock.wait(step.hold, fraction => {
              const now = performance.now()
              if (now - lastReport > 200) {
                update({ progress: (stepIndex + fraction) / chapter.steps.length })
                lastReport = now
              }
            })
          }
        }
        await clock.gate()
        playing.current = false
        running = false
        setPointer(null)
        update({ progress: 1, complete: true, caption: 'Tour complete. Create an account or sign in to explore the full app.' })
      } catch (error) {
        if (runGeneration !== generation.current || !mounted) return
        playing.current = false
        running = false
        setPointer(null)
        update({ error: error.message, caption: error.message })
      }
    }

    const onMessage = event => {
      if (event.source !== window.parent || !allowed(event.origin) || !isTourCommand(event.data)) return
      if (parentOrigin && event.origin !== parentOrigin) return
      parentOrigin = event.origin
      const { command, chapter } = event.data
      if (!handshakeComplete) {
        handshakeComplete = true
        post({ type: 'stater-tour:ready' })
      }
      if (command === 'sandbox') {
        generation.current++
        playing.current = false
        tourActive = false
        running = false
        setPointer(null)
        playbackMode(false)
        update({})
        return
      }
      if (command === 'pause') {
        playing.current = false
        update({})
        return
      }
      if (!tourActive) {
        tourActive = true
        playbackMode(true)
      }
      if (command === 'chapter') {
        chapterIndex = guidedTourSteps.findIndex(item => item.id === chapter)
        run(chapterIndex)
      } else if (command === 'restart') {
        playing.current = true
        run(0, true)
      } else if (command === 'play') {
        playing.current = true
        if (!running) run(report.complete ? 0 : chapterIndex, report.complete || chapterIndex === 0)
      }
      update({})
    }

    window.addEventListener('message', onMessage)
    post({ type: 'stater-tour:ready' })
    update({})
    return () => {
      mounted = false
      generation.current++
      playing.current = false
      window.removeEventListener('message', onMessage)
    }
  }, [enabled])

  if (!enabled || !pointer) return null
  return createPortal(<div aria-hidden="true">
    {!pointer.hideFocus && <div className="guided-tour-focus" style={{ left: pointer.left, top: pointer.top, width: pointer.width, height: pointer.height }} />}
    <div className={`guided-tour-cursor${pointer.clicking ? ' is-clicking' : ''}`} style={{ transform: `translate3d(${pointer.x}px, ${pointer.y}px, 0)` }}>
      <svg viewBox="0 0 24 28" fill="none"><path d="M3 2v20l5-5 4 9 4-2-4-9h9L3 2Z" fill="#fff" stroke="#25211e" strokeWidth="1.7" strokeLinejoin="round" /></svg>
    </div>
  </div>, document.body)
}
