import { afterEach, beforeEach, expect, it, vi } from 'vitest'

let contexts
class CashierAudioContext {
  constructor() {
    this.currentTime = 10
    this.destination = { output: 'cashier-speaker' }
    this.state = 'running'
    this.voices = []
    this.gains = []
    this.resume = vi.fn().mockResolvedValue(undefined)
    contexts.push(this)
  }
  createOscillator() {
    const voice = { frequency: { setValueAtTime: vi.fn() }, connect: vi.fn(), start: vi.fn(), stop: vi.fn() }
    this.voices.push(voice)
    return voice
  }
  createGain() {
    const gain = { gain: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() }, connect: vi.fn() }
    this.gains.push(gain)
    return gain
  }
}

beforeEach(() => {
  vi.resetModules()
  contexts = []
  vi.stubGlobal('window', { AudioContext: CashierAudioContext })
})
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('reuses one audio context and schedules short, quiet scan feedback with a definite stop', async () => {
  const audio = await import('../utils/posAudio')
  audio.playScanBeep()
  audio.playScanBeep()
  expect(contexts).toHaveLength(1)
  const ctx = contexts[0]
  expect(ctx.voices).toHaveLength(2)
  ctx.voices.forEach((voice, index) => {
    expect(voice.type).toBe('sine')
    expect(voice.frequency.setValueAtTime.mock.calls[0][0]).toBeGreaterThan(1000)
    expect(voice.connect).toHaveBeenCalledWith(ctx.gains[index])
    expect(ctx.gains[index].connect).toHaveBeenCalledWith(ctx.destination)
    expect(ctx.gains[index].gain.setValueAtTime.mock.calls[0][0]).toBeLessThan(0.2)
    expect(ctx.gains[index].gain.exponentialRampToValueAtTime.mock.calls[0][0]).toBeLessThan(0.01)
    expect(voice.start).toHaveBeenCalledOnce()
    expect(voice.stop.mock.calls[0][0]).toBeGreaterThan(ctx.currentTime)
    expect(voice.stop.mock.calls[0][0]).toBeLessThan(ctx.currentTime + 0.1)
  })
})

it('distinguishes a failed action from a successful bill with a low buzz and a rising finite chime', async () => {
  const audio = await import('../utils/posAudio')
  audio.playErrorTone()
  audio.playSuccessChime()
  const ctx = contexts[0]
  expect(ctx.voices).toHaveLength(4)
  const [error, ...success] = ctx.voices
  expect(error.type).toBe('sawtooth')
  const errorFrequency = error.frequency.setValueAtTime.mock.calls[0][0]
  const notes = success.map(voice => voice.frequency.setValueAtTime.mock.calls[0][0])
  expect(notes.every(frequency => frequency > errorFrequency)).toBe(true)
  expect(notes).toEqual([...notes].sort((a, b) => a - b))
  const starts = success.map(voice => voice.start.mock.calls[0][0])
  expect(starts[1]).toBeGreaterThan(starts[0])
  expect(starts[2]).toBeGreaterThan(starts[1])
  success.forEach((voice, index) => {
    expect(voice.type).toBe('sine')
    expect(voice.stop.mock.calls[0][0]).toBeGreaterThan(starts[index])
    expect(voice.stop.mock.calls[0][0]).toBeLessThan(ctx.currentTime + 1)
  })
})

it.each([undefined, {}])('keeps billing actions usable when Web Audio is unavailable', async browser => {
  vi.stubGlobal('window', browser)
  const audio = await import('../utils/posAudio')
  expect(() => { audio.playScanBeep(); audio.playErrorTone(); audio.playSuccessChime() }).not.toThrow()
  expect(contexts).toHaveLength(0)
})

it('supports the WebKit audio API and tolerates a rejected autoplay resume', async () => {
  vi.stubGlobal('window', { webkitAudioContext: CashierAudioContext })
  const audio = await import('../utils/posAudio')
  audio.playScanBeep()
  const ctx = contexts[0]
  ctx.state = 'suspended'
  ctx.resume.mockRejectedValue(new Error('user gesture required'))
  expect(() => audio.playErrorTone()).not.toThrow()
  await Promise.resolve()
  expect(ctx.resume).toHaveBeenCalledOnce()
  expect(contexts).toHaveLength(1)
})

it('allows the next cashier gesture to retry after audio-context construction was blocked', async () => {
  let attempts = 0
  vi.stubGlobal('window', { AudioContext: class extends CashierAudioContext {
    constructor() {
      if (++attempts === 1) throw new Error('autoplay blocked')
      super()
    }
  } })
  const audio = await import('../utils/posAudio')
  expect(() => audio.playScanBeep()).not.toThrow()
  expect(contexts).toHaveLength(0)
  audio.playScanBeep()
  expect(contexts).toHaveLength(1)
  expect(attempts).toBe(2)
})

it('never lets an unavailable audio graph block scan, error or successful-checkout handling', async () => {
  const audio = await import('../utils/posAudio')
  audio.playScanBeep()
  contexts[0].createOscillator = () => { throw new Error('audio device disconnected') }
  expect(() => audio.playScanBeep()).not.toThrow()
  expect(() => audio.playErrorTone()).not.toThrow()
  expect(() => audio.playSuccessChime()).not.toThrow()
})
