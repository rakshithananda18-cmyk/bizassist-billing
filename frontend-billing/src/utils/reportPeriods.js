import { getTodayDateStr } from './format'

// Build calendar dates in UTC from the business's IST date. Serializing local
// midnight with toISOString otherwise moves an Indian month boundary back a day.
export function reportPeriod(period, today = getTodayDateStr()) {
  const [year, month] = today.split('-').map(Number)
  const date = (y, m, day) => new Date(Date.UTC(y, m, day)).toISOString().slice(0, 10)
  const fiscalYear = month >= 4 ? year : year - 1
  switch (period) {
    case 'today': return { from: today, to: today }
    case 'month': return { from: date(year, month - 1, 1), to: date(year, month, 0) }
    case 'lastMonth': return { from: date(year, month - 2, 1), to: date(year, month - 1, 0) }
    case 'quarter': {
      const start = Math.floor((month - 1) / 3) * 3
      return { from: date(year, start, 1), to: date(year, start + 3, 0) }
    }
    case 'financialYear': return { from: `${fiscalYear}-04-01`, to: `${fiscalYear + 1}-03-31` }
    case 'previousFinancialYear': return { from: `${fiscalYear - 1}-04-01`, to: `${fiscalYear}-03-31` }
    default: throw new Error('Unknown report period')
  }
}
