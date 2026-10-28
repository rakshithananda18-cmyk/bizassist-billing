import { describe, expect, it, vi, afterEach } from 'vitest'
import { reportPeriod } from '../utils/reportPeriods'
afterEach(() => vi.useRealTimers())
describe('business report periods', () => {
  it.each([
    ['month', '2026-10-29', '2026-10-01', '2026-10-31'],
    ['lastMonth', '2026-01-02', '2025-12-01', '2025-12-31'],
    ['month', '2024-02-20', '2024-02-01', '2024-02-29'],
    ['quarter', '2026-10-29', '2026-10-01', '2026-12-31'],
    ['financialYear', '2026-03-31', '2025-04-01', '2026-03-31'],
    ['previousFinancialYear', '2026-04-01', '2025-04-01', '2026-03-31'],
  ])('%s starts and ends on the actual calendar boundary', (period, today, from, to) => {
    expect(reportPeriod(period, today)).toEqual({ from, to })
  })
  it('uses the Indian business date after midnight even while UTC is yesterday', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-28T19:00:00Z'))
    expect(reportPeriod('today')).toEqual({ from: '2026-10-29', to: '2026-10-29' })
  })
})
