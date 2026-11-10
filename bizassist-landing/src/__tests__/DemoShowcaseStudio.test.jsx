import React from 'react'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import DemoShowcaseStudio from '../DemoShowcaseStudio'

const APP_ORIGIN = 'https://app.example.test'
let intersections

beforeEach(() => {
  intersections = []
  vi.stubEnv('VITE_BILLING_APP_URL', `${APP_ORIGIN}/?demo=1`)
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false })))
  vi.stubGlobal('IntersectionObserver', class {
    constructor(callback) { this.callback = callback; intersections.push(this) }
    observe(target) { this.target = target }
    disconnect() {}
  })
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback) { this.callback = callback }
    observe(target) { this.callback([{ target, contentRect: { width: 1100 } }]) }
    disconnect() {}
  })
})

afterEach(() => {
  cleanup()
  document.body.style.overflow = ''
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

function mountReadyTour() {
  const view = render(<DemoShowcaseStudio />)
  const frame = view.container.querySelector('iframe')
  const post = vi.spyOn(frame.contentWindow, 'postMessage').mockImplementation(() => {})
  const receive = (data, origin = APP_ORIGIN, source = frame.contentWindow) => act(() => {
    window.dispatchEvent(new MessageEvent('message', { data, origin, source }))
  })
  act(() => intersections[0].callback([{ target: intersections[0].target, isIntersecting: true }]))
  receive({ type: 'stater-tour:ready' })
  return { ...view, frame, post, receive }
}

describe('public app tour entry points', () => {
  it('links directly to clean registration and sign-in routes without collecting details', () => {
    const { frame, container, post } = mountReadyTour()
    const register = screen.getByRole('link', { name: /Create your account/ })
    const login = screen.getByRole('link', { name: /Already use STATER Bill/ })
    const video = screen.getByRole('link', { name: /Create your STATER Bill account to explore/ })
    expect(register.getAttribute('href')).toBe(`${APP_ORIGIN}/register`)
    expect(login.getAttribute('href')).toBe(`${APP_ORIGIN}/login`)
    expect(video.getAttribute('href')).toBe(register.getAttribute('href'))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(container.querySelector('form, input')).toBeNull()
    expect(frame.getAttribute('tabindex')).toBe('-1')
    expect(frame.hasAttribute('inert')).toBe(true)
    expect(new URL(frame.src).searchParams.get('tour')).toBe('1')
    expect(post.mock.calls.some(([data]) => data.command === 'sandbox')).toBe(false)
  })

  it('does not unlock controls in response to an untrusted frame message', () => {
    const view = render(<DemoShowcaseStudio />)
    const frame = view.container.querySelector('iframe')
    act(() => window.dispatchEvent(new MessageEvent('message', {
      data: { type: 'stater-tour:ready' }, origin: 'https://other.example.test', source: frame.contentWindow,
    })))
    expect(screen.getByRole('button', { name: 'Pause guided tour' }).disabled).toBe(true)
    expect(screen.queryByRole('link', { name: /Create your STATER Bill account to explore/ })).toBeNull()
  })
})

describe('paused preview page scrolling', () => {
  it('returns expanded playback inline on pause and restores the prior overflow value', () => {
    document.body.style.overflow = 'scroll'
    const { container, post, frame } = mountReadyTour()
    fireEvent.click(screen.getByRole('button', { name: 'Expand app preview' }))
    expect(container.querySelector('.demo-studio-expanded')).not.toBeNull()
    expect(document.body.style.overflow).toBe('hidden')

    fireEvent.click(screen.getByRole('button', { name: 'Pause guided tour' }))
    expect(container.querySelector('.demo-studio-expanded')).toBeNull()
    expect(document.body.style.overflow).toBe('scroll')
    expect(post.mock.calls.at(-1)[0].command).toBe('pause')
    expect(frame.hasAttribute('inert')).toBe(true)

    fireEvent.click(screen.getByRole('button', { name: 'Play guided tour' }))
    expect(container.querySelector('.demo-studio-expanded')).toBeNull()
    expect(document.body.style.overflow).toBe('scroll')
    expect(post.mock.calls.at(-1)[0].command).toBe('play')
  })

  it('releases expansion on Escape and restores its prior overflow on unmount', () => {
    document.body.style.overflow = 'auto'
    const { container, unmount } = mountReadyTour()
    fireEvent.click(screen.getByRole('button', { name: 'Expand app preview' }))
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(container.querySelector('.demo-studio-expanded')).toBeNull()
    expect(document.body.style.overflow).toBe('auto')

    fireEvent.click(screen.getByRole('button', { name: 'Expand app preview' }))
    expect(document.body.style.overflow).toBe('hidden')
    unmount()
    expect(document.body.style.overflow).toBe('auto')
  })

  it('only reopens expansion from a paused tour through an explicitly labelled resume action', () => {
    const { container, post } = mountReadyTour()
    fireEvent.click(screen.getByRole('button', { name: 'Pause guided tour' }))
    expect(document.body.style.overflow).toBe('')

    fireEvent.click(screen.getByRole('button', { name: 'Resume and expand app preview' }))
    expect(screen.getByRole('button', { name: 'Pause guided tour' })).not.toBeNull()
    expect(container.querySelector('.demo-studio-expanded')).not.toBeNull()
    expect(post.mock.calls.at(-1)[0].command).toBe('play')

    fireEvent.click(screen.getByRole('button', { name: 'Pause guided tour' }))
    expect(container.querySelector('.demo-studio-expanded')).toBeNull()
    expect(document.body.style.overflow).toBe('')
  })

  it.each([{ complete: true }, { error: 'A sample page could not load' }])('releases the expanded page when playback stops: %j', stopped => {
    document.body.style.overflow = 'scroll'
    const { container, receive } = mountReadyTour()
    fireEvent.click(screen.getByRole('button', { name: 'Expand app preview' }))
    receive({ type: 'stater-tour:state', chapter: 'home', progress: 1, ...stopped })
    expect(container.querySelector('.demo-studio-expanded')).toBeNull()
    expect(document.body.style.overflow).toBe('scroll')
  })
})
