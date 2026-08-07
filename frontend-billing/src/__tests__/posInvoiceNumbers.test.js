// The number the counter SEES before a bill is saved.
//
// These helpers scan the invoice list the POS holds in memory, and that list is
// fetched with a SEVEN-DAY window (pages/Sales.jsx). A counter that had not
// billed in a week therefore saw an empty series and displayed `<SERIES>-0001` —
// which is how a draft tab read `LCL-OW-0001` while `LCL-OW-0001..0003` had
// existed since 2026-07-03. The `floor` argument is the server's authoritative
// last-issued number (GET /sales/next-number) and closes that hole.
import { describe, it, expect } from 'vitest'
import { maxNumInSeries, nextInvoiceNo, syncTabNames } from '../lib/posInvoiceNumbers'

const inv = (n) => ({ invoice_number: n })

describe('POS invoice numbering', () => {
  it('continues from the server floor when the window hides the series', () => {
    // Exactly the reported case: nothing in the last 7 days, 3 bills in July.
    expect(nextInvoiceNo([], 'LCL-OW-', 3)).toBe('LCL-OW-0004')
  })

  it('restarts at 0001 without the floor — the bug this guards', () => {
    expect(nextInvoiceNo([], 'LCL-OW-')).toBe('LCL-OW-0001')
  })

  it('prefers the in-memory list when it is AHEAD of the floor', () => {
    // A bill committed this session, after the floor was fetched. The scan has
    // to still win, or two tabs would be handed the same number.
    expect(nextInvoiceNo([inv('LCL-OW-0009')], 'LCL-OW-', 3)).toBe('LCL-OW-0010')
  })

  it('keeps series apart — a floor for one must not move another', () => {
    // `LCL-OW` and `OW` are deliberately separate series.
    expect(maxNumInSeries([inv('OW-0007')], 'LCL-OW-', 0)).toBe(0)
    expect(nextInvoiceNo([inv('OW-0007')], 'OW-', 0)).toBe('OW-0008')
  })

  it('ignores a missing or junk floor rather than numbering from NaN', () => {
    expect(nextInvoiceNo([], 'OW-', undefined)).toBe('OW-0001')
    expect(nextInvoiceNo([], 'OW-', null)).toBe('OW-0001')
    expect(nextInvoiceNo([], 'OW-', 'abc')).toBe('OW-0001')
  })

  it('names fresh tabs above the floor', () => {
    const tabs = [{ name: 'Invoice #1001', form: { items: [] } }]
    const named = syncTabNames(tabs, [], 'LCL-OW-', 3)
    expect(named[0].name).toBe('LCL-OW-0004')
  })
})
