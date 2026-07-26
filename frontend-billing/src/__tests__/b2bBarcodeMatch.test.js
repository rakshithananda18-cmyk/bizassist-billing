// Unit tests for findByCode — the scan-to-order resolver on the B2B order desk.
// A wrong match here silently orders the wrong product from a supplier, so the
// precedence rules get pinned down explicitly.
import { describe, it, expect } from 'vitest'
import { findByCode } from '../b2b/components/OrderDeskTab'

const CATALOG = [
  {
    product_id: 1, name: 'Apex Ultima 10L', sku: 'AP-ULT-10',
    barcode: '8901030812345', barcodes: ['8901030812345', '8901030899999'],
  },
  {
    product_id: 2, name: 'Tractor Emulsion 20L', sku: 'TR-EM-20',
    barcode: '8901030855555', barcodes: ['8901030855555'],
  },
  // Legacy row: no packaging-revision list, only the primary code.
  { product_id: 3, name: 'Putty 5kg', sku: 'PT-05', barcode: '8901030877777' },
  // Row with no codes at all.
  { product_id: 4, name: 'Loose Thinner', sku: null, barcode: null },
]

describe('findByCode — barcode', () => {
  it('matches the primary barcode', () => {
    expect(findByCode(CATALOG, '8901030855555').product_id).toBe(2)
  })

  it('matches a secondary packaging-revision barcode', () => {
    expect(findByCode(CATALOG, '8901030899999').product_id).toBe(1)
  })

  it('matches a product that only carries the legacy primary code', () => {
    expect(findByCode(CATALOG, '8901030877777').product_id).toBe(3)
  })

  it('is exact — a partial barcode must never match', () => {
    expect(findByCode(CATALOG, '890103085')).toBeNull()
    expect(findByCode(CATALOG, '89010308555550')).toBeNull()
  })

  it('tolerates the whitespace a scanner appends', () => {
    expect(findByCode(CATALOG, '  8901030855555 ').product_id).toBe(2)
  })
})

describe('findByCode — fallbacks', () => {
  it('falls back to SKU, case-insensitively', () => {
    expect(findByCode(CATALOG, 'tr-em-20').product_id).toBe(2)
    expect(findByCode(CATALOG, 'AP-ULT-10').product_id).toBe(1)
  })

  it('falls back to an exact product name', () => {
    expect(findByCode(CATALOG, 'Loose Thinner').product_id).toBe(4)
    expect(findByCode(CATALOG, 'putty 5kg').product_id).toBe(3)
  })

  it('does NOT match a partial name — that is what the search box is for', () => {
    expect(findByCode(CATALOG, 'Putty')).toBeNull()
  })

  it('prefers a barcode over a SKU when both could match', () => {
    const overlapping = [
      { product_id: 10, name: 'A', sku: '8901030855555', barcodes: [] },
      { product_id: 11, name: 'B', sku: 'B-1', barcodes: ['8901030855555'] },
    ]
    expect(findByCode(overlapping, '8901030855555').product_id).toBe(11)
  })
})

describe('findByCode — bad input', () => {
  it('returns null rather than throwing', () => {
    expect(findByCode(CATALOG, '')).toBeNull()
    expect(findByCode(CATALOG, null)).toBeNull()
    expect(findByCode(CATALOG, undefined)).toBeNull()
    expect(findByCode(CATALOG, '   ')).toBeNull()
    expect(findByCode([], '8901030855555')).toBeNull()
  })

  it('does not match a product whose codes are all null', () => {
    expect(findByCode(CATALOG, 'null')).toBeNull()
  })
})
