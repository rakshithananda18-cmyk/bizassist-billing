import { describe, expect, it } from 'vitest'
import { planBanner } from './plan'

describe('planBanner', () => {
  it('stays hidden unless the server says to warn', () => {
    expect(planBanner(null)).toBeNull()
    expect(planBanner({ warn: false, ends_at: '2026-10-28T00:00:00Z' })).toBeNull()
  })
  it('names the last day of the plan before it ends', () => {
    expect(planBanner({ warn: true, in_grace: false, ends_at: '2026-10-28T00:00:00Z' })).toContain('ends after 27 Oct')
  })
  it('names the last working day during the grace period', () => {
    const text = planBanner({ warn: true, in_grace: true, ends_at: '2026-10-21T00:00:00Z', grace_until: '2026-10-28T00:00:00Z' })
    expect(text).toContain('has ended')
    expect(text).toContain('through 27 Oct')
  })
})
