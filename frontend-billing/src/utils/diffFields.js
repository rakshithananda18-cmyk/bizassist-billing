// ============================================================================
// diffFields — turn a before/after pair into a human-readable change list for
// the confirmation dialog. Shared by every "double-check before save" flow.
//
//   const changes = diffFields(original, next, [
//     { key: 'name',          label: 'Name' },
//     { key: 'selling_price', label: 'Retail price', money: true },
//     { key: 'cgst_rate',     label: 'CGST %',       suffix: '%' },
//   ])
//   // → [{ label:'Retail price', from:'₹100', to:'₹120' }, ...]
//
// Only fields whose value actually changed are returned, so the dialog shows
// exactly what the save will alter — nothing more.
// ============================================================================

const isBlank = (v) => v === '' || v === null || v === undefined

// Loose equality that treats '5' / 5 / 5.0 and ''/null/undefined as equal, so
// we never surface a "change" that is only a string-vs-number formatting quirk.
function sameValue(a, b) {
  if (isBlank(a) && isBlank(b)) return true
  const na = typeof a === 'number' ? a : (a !== '' && !isNaN(Number(a)) ? Number(a) : null)
  const nb = typeof b === 'number' ? b : (b !== '' && !isNaN(Number(b)) ? Number(b) : null)
  if (na !== null && nb !== null) return na === nb
  return String(a ?? '').trim() === String(b ?? '').trim()
}

export function formatValue(v, field = {}) {
  if (isBlank(v)) return '—'
  if (field.money) {
    const n = Number(v)
    return isNaN(n) ? String(v) : `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
  }
  if (field.map && field.map[v] != null) return field.map[v]
  let s = String(v)
  if (field.suffix) s += field.suffix
  return s
}

// before → after diff. `fields` describes which keys to compare and how to
// label/format them. Returns [{ key, label, from, to }] for changed keys only.
export function diffFields(before = {}, after = {}, fields = []) {
  const out = []
  for (const f of fields) {
    const a = before?.[f.key]
    const b = after?.[f.key]
    if (!sameValue(a, b)) {
      out.push({ key: f.key, label: f.label, from: formatValue(a, f), to: formatValue(b, f) })
    }
  }
  return out
}

// For "add" flows: a flat summary of the non-empty fields being created.
// Returns [{ key, label, value }].
export function summariseFields(values = {}, fields = []) {
  const out = []
  for (const f of fields) {
    const v = values?.[f.key]
    if (!isBlank(v)) out.push({ key: f.key, label: f.label, value: formatValue(v, f) })
  }
  return out
}

// True when `after` differs from `before` on any of the listed fields — used to
// decide whether a "discard changes?" prompt is warranted.
export function isDirty(before = {}, after = {}, fields = []) {
  return diffFields(before, after, fields).length > 0
}
