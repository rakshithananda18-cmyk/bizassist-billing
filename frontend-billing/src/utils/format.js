// src/utils/format.js — shared formatting helpers.
// =================================================
// These were defined inline inside Sales.jsx (and copied around other pages).
// Centralised here so money/date/words formatting is consistent everywhere and
// there's ONE place to fix a rounding or locale bug. Logic is unchanged.

/** Indian-rupee money string, e.g. 1234.5 → "₹1,234.5". Null/undefined → "—". */
export const fmt = (n) =>
  n != null ? `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '—'

/** Today as local date string "YYYY-MM-DD". */
export const getTodayDateStr = () => {
  const d = new Date()
  const year = d.getFullYear()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
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
