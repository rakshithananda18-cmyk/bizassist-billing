import { afterEach, describe, expect, it, vi } from 'vitest'
import { isAllowedTourOrigin, isEmbeddedGuidedTour, isTourCommand, TourClock } from '../demo/guidedTourRuntime'

afterEach(() => vi.useRealTimers())

describe('embedded app tour boundary', () => {
  it('requires a frame and every explicit demo playback flag', () => {
    const location = { search: '?demo=1&embed=1&tour=1' }
    expect(isEmbeddedGuidedTour(location, true)).toBe(true)
    expect(isEmbeddedGuidedTour(location, false)).toBe(false)
    for (const search of ['?demo=1', '?embed=1&tour=1', '?demo=1&tour=1', '?demo=1&embed=1']) {
      expect(isEmbeddedGuidedTour({ search }, true)).toBe(false)
    }
  })

  it('accepts only trusted landing origins and exact configured preview origins', () => {
    expect(isAllowedTourOrigin('https://staterbill.com')).toBe(true)
    expect(isAllowedTourOrigin('https://www.staterbill.com')).toBe(true)
    expect(isAllowedTourOrigin('http://localhost:5173')).toBe(true)
    expect(isAllowedTourOrigin('https://preview.example.com', 'https://preview.example.com/landing')).toBe(true)
    for (const origin of ['null', 'https://staterbill.com.evil.test', 'https://evil.test', 'http://staterbill.com', 'https://staterbill.com/path']) {
      expect(isAllowedTourOrigin(origin)).toBe(false)
    }
  })

  it('does not accept arbitrary commands or page routes from postMessage', () => {
    expect(isTourCommand({ type: 'stater-tour:command', command: 'chapter', chapter: 'purchases' })).toBe(true)
    expect(isTourCommand({ type: 'stater-tour:command', command: 'chapter', chapter: '/settings' })).toBe(false)
    expect(isTourCommand({ type: 'stater-tour:command', command: 'click', selector: 'button' })).toBe(false)
  })
})

describe('tour playback clock', () => {
  it('preserves the remaining dwell while paused and prevents a pending action', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'performance'] })
    let playing = true
    const action = vi.fn()
    const clock = new TourClock({ active: () => playing, cancelled: () => false })
    const pending = clock.wait(1000).then(action)
    await vi.advanceTimersByTimeAsync(400)
    playing = false
    await vi.advanceTimersByTimeAsync(6000)
    expect(action).not.toHaveBeenCalled()
    playing = true
    await vi.advanceTimersByTimeAsync(550)
    expect(action).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(150)
    await pending
    expect(action).toHaveBeenCalledOnce()
  })

  it('cancels paused work when changing chapter or handing over to sandbox', async () => {
    vi.useFakeTimers()
    let cancelled = false
    const action = vi.fn()
    const clock = new TourClock({ active: () => false, cancelled: () => cancelled })
    const pending = clock.gate().then(action).catch(error => error.message)
    cancelled = true
    await vi.advanceTimersByTimeAsync(60)
    expect(await pending).toBe('tour-cancelled')
    expect(action).not.toHaveBeenCalled()
  })
})
