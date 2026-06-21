// src/utils/printLayout.js
// =========================
// Shared model for the customisable receipt HEADER: the order of the header
// lines and each line's horizontal alignment. Used by BOTH the Settings live
// preview (drag to reorder, click L/C/R to align) and the real thermal receipt,
// so what you arrange is what prints. Persisted at settings.print.header_layout.

// Each entry: { key, align: 'left'|'center'|'right' }.
export const DEFAULT_HEADER_LAYOUT = [
  { key: 'logo', align: 'center' },
  { key: 'company_name', align: 'center' },
  { key: 'company_address', align: 'center' },
  { key: 'company_contact', align: 'center' },
  { key: 'gstin', align: 'center' },
]

export const HEADER_LINE_LABEL = {
  logo: 'Logo',
  company_name: 'Company name',
  company_address: 'Address',
  company_contact: 'Phone / Email',
  gstin: 'GSTIN',
}

const VALID_KEYS = DEFAULT_HEADER_LAYOUT.map(l => l.key)

/** Saved layout if present, otherwise the default — and always backfills any
 *  missing/renamed keys so the editor can't lose a line. */
export function getHeaderLayout(pr) {
  const saved = pr && Array.isArray(pr.header_layout) ? pr.header_layout : null
  if (!saved || !saved.length) return DEFAULT_HEADER_LAYOUT.map(l => ({ ...l }))
  const clean = saved.filter(l => l && VALID_KEYS.includes(l.key))
                     .map(l => ({ key: l.key, align: ['left', 'center', 'right'].includes(l.align) ? l.align : 'center' }))
  const present = new Set(clean.map(l => l.key))
  DEFAULT_HEADER_LAYOUT.forEach(d => { if (!present.has(d.key)) clean.push({ ...d }) })
  return clean
}

/** Whether a header line should render, based on the existing print toggles. */
export function isHeaderLineEnabled(key, pr) {
  if (!pr) return false
  switch (key) {
    case 'logo':            return !!pr.print_logo
    case 'company_name':    return pr.print_company_name !== false
    case 'company_address': return pr.print_company_address !== false
    case 'company_contact': return (pr.print_company_phone !== false) || (pr.print_company_email !== false)
    case 'gstin':           return pr.print_gstin !== false
    default:                return true
  }
}

/** Pure array move helper (immutable). */
export function moveItem(arr, from, to) {
  const next = arr.slice()
  if (from < 0 || from >= next.length || to < 0 || to >= next.length) return next
  const [moved] = next.splice(from, 1)
  next.splice(to, 0, moved)
  return next
}
