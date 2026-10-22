import { describe, expect, it } from 'vitest'
import { MAX_BUFFER, PingBuffer } from './tracker'

function memoryStorage() {
  const m = new Map()
  return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)) }
}

describe('PingBuffer', () => {
  it('keeps points in order and drops the oldest past the cap', () => {
    const b = new PingBuffer(memoryStorage())
    for (let i = 0; i < MAX_BUFFER + 5; i++) b.push({ i })
    const items = b.read()
    expect(items).toHaveLength(MAX_BUFFER)
    expect(items[0].i).toBe(5)
    expect(items.at(-1).i).toBe(MAX_BUFFER + 4)
  })

  it('take empties the buffer; putBack restores ahead of newer points', () => {
    const b = new PingBuffer(memoryStorage())
    b.push({ i: 1 }); b.push({ i: 2 })
    const taken = b.take()
    expect(b.size()).toBe(0)
    b.push({ i: 3 })
    b.putBack(taken)
    expect(b.read().map(x => x.i)).toEqual([1, 2, 3])
  })

  it('survives corrupt storage', () => {
    const s = memoryStorage()
    s.setItem('task_ping_buffer', '{not json')
    expect(new PingBuffer(s).read()).toEqual([])
  })
})
