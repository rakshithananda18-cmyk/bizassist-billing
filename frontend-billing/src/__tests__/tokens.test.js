// Phase 4.1 token-system guard (plan §4.5).
// Reads index.css raw and asserts the design-token contract holds:
//   • the motion system (3 durations + one ease) exists and no legacy
//     hardcoded transition durations crept back in
//   • type scale, spacing grid, border weights, focus ring tokens exist
//   • reduced-motion kill-switch and :focus-visible ring are present
//   • print isolation blocks stay untouched
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

// vitest cwd = the frontend-billing project root
const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8')

describe('design tokens (Phase 4.1)', () => {
  it('defines the motion system', () => {
    expect(css).toMatch(/--dur-fast:\s*120ms/)
    expect(css).toMatch(/--dur:\s*180ms/)
    expect(css).toMatch(/--dur-slow:\s*240ms/)
    expect(css).toMatch(/--ease:\s*cubic-bezier/)
  })

  it('has NO hardcoded transition durations left (everything on the system)', () => {
    const transitions = css.match(/transition:[^;]+;/g) || []
    const offenders = transitions.filter(t =>
      /\d+(\.\d+)?m?s/.test(t) &&                    // contains a literal duration
      !t.includes('var(--dur') &&                    // not tokenised
      !t.includes('0.01ms') &&                       // reduced-motion kill-switch
      !t.includes('width 0.4s'))                     // sidebar width: intentional outlier
    expect(offenders).toEqual([])
  })

  it('defines the type scale and spacing grid', () => {
    for (const t of ['--fs-xs', '--fs-sm', '--fs-base', '--fs-md', '--fs-lg', '--fs-2xl',
                     '--sp-1', '--sp-2', '--sp-3', '--sp-4', '--sp-5', '--sp-6', '--sp-7', '--sp-8',
                     '--lh-body', '--lh-heading']) {
      expect(css, `missing token ${t}`).toContain(`${t}:`)
    }
  })

  it('defines border weights and the focus ring (light + dark mode)', () => {
    expect((css.match(/--border-hairline:/g) || []).length).toBeGreaterThanOrEqual(2)
    expect((css.match(/--border-strong:/g) || []).length).toBeGreaterThanOrEqual(2)
    expect(css).toContain('--focus-ring:')
    expect(css).toMatch(/:focus-visible/)
  })

  it('applies tabular numerals app-wide and the reduced-motion kill-switch', () => {
    expect(css).toContain('font-variant-numeric: tabular-nums')
    expect(css).toContain('prefers-reduced-motion: reduce')
  })

  it('print isolation blocks remain intact', () => {
    expect(css).toContain('#thermal-receipt')
    expect(css).toContain('#invoice-a4-root')
    expect(css).toMatch(/@page\s*\{\s*size:\s*A4/)
  })
})
