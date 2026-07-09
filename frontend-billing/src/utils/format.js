// src/utils/format.js — shared formatting helpers.
// =================================================
// Centralised here so money/date/words formatting is consistent everywhere and
// there's ONE place to fix a rounding or locale bug.

/** Indian-rupee money string, e.g. 1234.5 → "₹1,234.5". Null/undefined → "—". */
export const fmt = (n) =>
  n != null ? `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '—'

// ── Timezone helpers ────────────────────────────────────────────────────────
// All timestamps from the backend are UTC (or naive local on older records).
// formatIST / formatISTDate convert them to IST (Asia/Kolkata, UTC+5:30) for
// display. Applied to: invoice lists, sync logs, reports, sync health pill.

const IST_LOCALE = 'en-IN'
const IST_TZ     = 'Asia/Kolkata'

export const parseAsUTCDate = (ts) => {
  if (!ts) return new Date(NaN)
  if (ts instanceof Date) return ts
  if (typeof ts === 'string') {
    // If it's a naive ISO timestamp (e.g., "2026-07-08T19:14:12" or "2026-07-08 19:14:12")
    // without timezone suffix ('Z', '+00:00', etc.), append 'Z' to treat it as UTC.
    if (ts.includes('-') && !ts.endsWith('Z') && !/[+-]\d{2}:?\d{2}$/.test(ts)) {
      const formatted = ts.includes('T') ? ts : ts.replace(' ', 'T')
      return new Date(formatted + 'Z')
    }
  }
  return new Date(ts)
}

/**
 * Full IST datetime, e.g. "08/07/2026, 11:30:45 PM"
 * Pass any value parseable by `new Date()` — ISO string, Unix ms, or Date.
 * Returns "—" on invalid input.
 */
export const formatIST = (ts) => {
  if (!ts) return '—'
  try {
    const d = parseAsUTCDate(ts)
    if (isNaN(d.getTime())) return '—'
    return d.toLocaleString(IST_LOCALE, {
      timeZone: IST_TZ,
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      hour12: true,
    })
  } catch { return '—' }
}

/**
 * Short IST date only, e.g. "08/07/2026".
 */
export const formatISTDate = (ts) => {
  if (!ts) return '—'
  try {
    const d = parseAsUTCDate(ts)
    if (isNaN(d.getTime())) return '—'
    return d.toLocaleDateString(IST_LOCALE, {
      timeZone: IST_TZ,
      day: '2-digit', month: '2-digit', year: 'numeric',
    })
  } catch { return '—' }
}

/**
 * Short IST time only, e.g. "11:30 PM".
 */
export const formatISTTime = (ts) => {
  if (!ts) return '—'
  try {
    const d = parseAsUTCDate(ts)
    if (isNaN(d.getTime())) return '—'
    return d.toLocaleTimeString(IST_LOCALE, {
      timeZone: IST_TZ,
      hour: '2-digit', minute: '2-digit', hour12: true,
    })
  } catch { return '—' }
}

/** Today's date as IST "YYYY-MM-DD" string — for API query params. */
export const getTodayDateStr = () => {
  // Use Intl to get today in IST, not local machine timezone.
  const now = new Date()
  const ist = new Intl.DateTimeFormat('en-CA', { timeZone: IST_TZ,
    year: 'numeric', month: '2-digit', day: '2-digit' }).format(now)
  return ist // en-CA locale gives YYYY-MM-DD naturally
}

/**
 * "YYYY-MM-DD" for N days before today in IST — used for the rolling invoice window.
 * getFromDateStr(7) → last 7 days including today.
 */
export const getFromDateStr = (days = 7) => {
  const now = new Date()
  now.setDate(now.getDate() - days + 1)
  return new Intl.DateTimeFormat('en-CA', { timeZone: IST_TZ,
    year: 'numeric', month: '2-digit', day: '2-digit' }).format(now)
}



/**
 * Amount → Indian-numbering words for invoice footers, e.g.
 * 1234.50 → "One Thousand Two Hundred and Thirty Four Rupees and Fifty Paise Only".
 * Returns "" on bad input (never throws). Verbatim from the original Sales.jsx.
 */
export const numberToWords = (num) => {
  try {
    const rupees = Math.floor(num)
    const paise = Math.round((num - rupees) * 100)

    const ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
                 "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
    const tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    const wordsUnder100 = (n) => {
      if (n < 20) return ones[n]
      return tens[Math.floor(n / 10)] + (n % 10 !== 0 ? " " + ones[n % 10] : "")
    }

    const intToWords = (n) => {
      if (n === 0) return "Zero"
      const parts = []
      if (n >= 10000000) { // Crore
        const crore = Math.floor(n / 10000000)
        parts.push(wordsUnder100(crore) + " Crore")
        n %= 10000000
      }
      if (n >= 100000) { // Lakh
        const lakh = Math.floor(n / 100000)
        parts.push(wordsUnder100(lakh) + " Lakh")
        n %= 100000
      }
      if (n >= 1000) { // Thousand
        const thousand = Math.floor(n / 1000)
        parts.push(wordsUnder100(thousand) + " Thousand")
        n %= 1000
      }
      if (n >= 100) { // Hundred
        const hundred = Math.floor(n / 100)
        parts.push(wordsUnder100(hundred) + " Hundred")
        n %= 100
      }
      if (n > 0) {
        if (parts.length > 0) {
          parts.push("and " + wordsUnder100(n))
        } else {
          parts.push(wordsUnder100(n))
        }
      }
      return parts.join(" ")
    }

    let result = intToWords(rupees) + " Rupees"
    if (paise > 0) {
      result += " and " + wordsUnder100(paise) + " Paise"
    }
    return result + " Only"
  } catch (e) {
    return ""
  }
}
