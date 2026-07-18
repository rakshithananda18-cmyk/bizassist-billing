// ============================================================================
// lib/posInvoiceNumbers.js — per-counter invoice numbering (split from Sales.jsx)
// ----------------------------------------------------------------------------
// Pure helpers. Each counter has its own series (prefix), and numbering must
// NOT mix series — deriving the next number from the global max scrambles
// multi-counter numbering.
// ============================================================================

/** Highest numeric suffix among invoices whose number starts with `prefix`. */
export function maxNumInSeries(existingInvoices, prefix) {
  let maxNum = 0
  existingInvoices.forEach(inv => {
    const invNo = inv.invoice_number || inv.invoice_no || ''
    if (invNo && invNo.startsWith(prefix)) {
      const m = invNo.slice(prefix.length).match(/(\d+)/)
      if (m) { const num = parseInt(m[1]); if (num > maxNum) maxNum = num }
    }
  })
  return maxNum
}

/** Next invoice number in this counter's series, zero-padded to 4 digits. */
export function nextInvoiceNo(existingInvoices, prefix) {
  const nextVal = maxNumInSeries(existingInvoices, prefix) + 1
  return `${prefix}${String(nextVal).padStart(4, '0')}`
}

/**
 * Re-number open POS tabs against the DB's committed invoices: tabs holding a
 * cart with a real (non-placeholder) name keep it; everything else gets the
 * next free number in this counter's series, skipping numbers already used.
 */
export function syncTabNames(currentTabs, existingInvoices, prefix) {
  const nextDbVal = maxNumInSeries(existingInvoices, prefix) + 1

  const usedNumbers = new Set(existingInvoices.map(inv => inv.invoice_number || inv.invoice_no || ''))

  let currentNum = nextDbVal
  return currentTabs.map(tab => {
    const hasItems = tab.form?.items?.length > 0
    const currentTabName = tab.name

    if (hasItems && !usedNumbers.has(currentTabName) && currentTabName !== 'Invoice #1001' && !currentTabName.startsWith('Invoice #')) {
      usedNumbers.add(currentTabName)
      return tab
    } else {
      let candidate = `${prefix}${String(currentNum).padStart(4, '0')}`
      while (usedNumbers.has(candidate)) {
        currentNum++
        candidate = `${prefix}${String(currentNum).padStart(4, '0')}`
      }
      usedNumbers.add(candidate)
      currentNum++
      return { ...tab, name: candidate }
    }
  })
}
