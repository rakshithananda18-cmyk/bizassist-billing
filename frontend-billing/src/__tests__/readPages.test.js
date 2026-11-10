import { describe, it, expect, vi } from 'vitest'
import { readAllPages } from '../utils/readPages'
describe('complete server page traversal', () => {
  it('reaches records beyond the former 500-row cap', async () => {
    const fetch = vi.fn(async path => {
      const page = Number(new URL(path, 'https://test.invalid').searchParams.get('page'))
      const start = (page - 1) * 500
      return { ok: true, json: async () => ({ items: Array.from({ length: page === 1 ? 500 : 1 }, (_, i) => ({ id: start + i + 1 })), total: 501 }) }
    })
    const rows = await readAllPages(fetch, '/customers')
    expect(rows).toHaveLength(501)
    expect(rows[500].id).toBe(501)
    expect(fetch.mock.calls[1][0]).toContain('page=2')
  })
  it('rejects a failed continuation and repeated pages rather than claiming complete data', async () => {
    const page = { items: [{ id: 1 }, { id: 2 }], total: 4 }
    const fetch = vi.fn(async () => ({ ok: true, json: async () => page }))
    await expect(readAllPages(fetch, '/products', { pageSize: 2 })).rejects.toThrow('repeated a page')
    fetch.mockResolvedValue({ ok: false, status: 503 })
    await expect(readAllPages(fetch, '/products')).rejects.toThrow('HTTP 503')
  })
})
