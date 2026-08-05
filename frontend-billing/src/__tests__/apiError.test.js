// formatApiError — the one place a FastAPI error body becomes a readable line.
// Replaced four near-copies that disagreed on the `loc` format; the array case
// is the one that mattered, because unhandled it renders "[object Object]".
import { describe, it, expect } from 'vitest'
import { formatApiError } from '../utils/apiError'

describe('formatApiError', () => {
  it('names the field from a 422 validation array', () => {
    const body = { detail: [{ loc: ['body', 'connect_as'], msg: 'Field required', type: 'missing' }] }
    expect(formatApiError(body)).toBe('connect_as: Field required')
  })

  it('joins several validation errors', () => {
    const body = {
      detail: [
        { loc: ['body', 'name'], msg: 'Field required' },
        { loc: ['body', 'qty'], msg: 'Input should be a valid number' },
      ],
    }
    expect(formatApiError(body)).toBe('name: Field required; qty: Input should be a valid number')
  })

  it('passes a raised string detail through untouched', () => {
    // The products 409 names its blockers and tells the owner what to do
    // instead. That message IS the feature — it must not be reworded.
    const msg = "'Sugar 50kg' is used by 10 sales invoices and cannot be deleted."
    expect(formatApiError({ detail: msg }, 'nope')).toBe(msg)
  })

  it('falls back when there is nothing usable', () => {
    expect(formatApiError({}, 'Failed to add party.')).toBe('Failed to add party.')
    expect(formatApiError(null, 'Failed to add party.')).toBe('Failed to add party.')
    expect(formatApiError({ detail: [] }, 'Failed to add party.')).toBe('Failed to add party.')
  })

  it('never returns [object Object]', () => {
    for (const body of [
      { detail: [{ loc: ['body', 'x'], msg: 'bad' }] },
      { detail: { nested: 'thing' } },
      { detail: [{}] },
    ]) {
      expect(String(formatApiError(body))).not.toContain('[object Object]')
    }
  })
})
