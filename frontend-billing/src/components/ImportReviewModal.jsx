// components/ImportReviewModal.jsx — the import approval table (column-driven).
// ======================================================================
// Owner requirement (2026-07): nothing from a file lands in the DB without a
// human looking at it. The backend parses the CSV with ?preview=1 (zero
// writes), this modal shows every row EDITABLE with problems flagged, and only
// the ticked rows are committed on "Approve & Import".
//
// Column-driven so the SAME modal serves products, customers and vendors — the
// caller passes a `columns` schema. Falls back to the product columns for
// backward compatibility if none is supplied.
import React, { useState, useMemo } from 'react'

// field: row key · label: header · num: numeric input (right-aligned) ·
// nullable: empty numeric commits as null instead of 0
const PRODUCT_COLUMNS = [
  { field: 'name', label: 'Name *' },
  { field: 'sku', label: 'SKU' },
  { field: 'barcode', label: 'Barcode' },
  { field: 'unit', label: 'Unit' },
  { field: 'category', label: 'Category' },
  { field: 'selling_price', label: 'Sell ₹', num: true },
  { field: 'cost_price', label: 'Cost ₹', num: true },
  { field: 'mrp', label: 'MRP', num: true, nullable: true },
  { field: 'cgst_rate', label: 'CGST%', num: true },
  { field: 'sgst_rate', label: 'SGST%', num: true },
  { field: 'opening_stock', label: 'Open. stock', num: true },
]

export default function ImportReviewModal({
  open, items, onCancel, onCommit, committing,
  columns = PRODUCT_COLUMNS, entityLabel = 'row',
}) {
  // rows: editable copies; include: per-row approval (problem rows start unticked)
  const [rows, setRows] = useState([])
  const [include, setInclude] = useState({})

  // Re-seed whenever a new preview arrives.
  React.useEffect(() => {
    if (!open) return
    setRows((items || []).map(it => ({ ...it })))
    const inc = {}
    ;(items || []).forEach((it, i) => { inc[i] = (it.problems || []).length === 0 })
    setInclude(inc)
  }, [open, items])

  const numFields = useMemo(() => columns.filter(c => c.num), [columns])
  const nullableFields = useMemo(
    () => new Set(columns.filter(c => c.num && c.nullable).map(c => c.field)),
    [columns],
  )
  const approvedCount = useMemo(() => Object.values(include).filter(Boolean).length, [include])

  if (!open) return null

  const setField = (idx, field, value) => {
    setRows(prev => prev.map((r, i) => (i === idx ? { ...r, [field]: value } : r)))
  }

  const commit = () => {
    const approved = rows
      .filter((_, i) => include[i])
      .map(r => {
        const out = { ...r }
        delete out.problems
        delete out.row
        for (const c of numFields) {
          if (out[c.field] === '' || out[c.field] == null) {
            out[c.field] = nullableFields.has(c.field) ? null : 0
          }
        }
        return out
      })
      .filter(r => (r.name || '').trim())
    onCommit?.(approved)
  }

  const cell = { padding: '4px 6px', borderBottom: '1px solid var(--border)' }
  const inputStyle = {
    width: '100%', minWidth: 70, height: 28, padding: '2px 6px', fontSize: '0.76rem',
    border: '1px solid var(--border)', borderRadius: 4,
    background: 'var(--bg-3)', color: 'var(--text-primary)',
  }

  return (
    <div className="modal-overlay" style={{ zIndex: 3000 }} onClick={e => e.target === e.currentTarget && !committing && onCancel?.()}>
      <div className="modal" style={{ maxWidth: 1100, width: '96%', maxHeight: '90vh', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '18px 22px', display: 'flex', flexDirection: 'column', gap: 12, minHeight: 0 }}>
          <div>
            <h3 style={{ margin: 0, fontSize: '1.05rem' }}>Review before import — nothing is saved yet</h3>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.78rem', margin: '4px 0 0' }}>
              {rows.length} row{rows.length === 1 ? '' : 's'} found in the file. Edit anything inline, untick rows you
              don't want. Rows with problems start unticked — fix the issue or leave them out.
            </p>
          </div>

          <div style={{ overflow: 'auto', border: '1px solid var(--border)', borderRadius: 8, flex: 1, minHeight: 0 }}>
            <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: '0.78rem' }}>
              <thead>
                <tr style={{ position: 'sticky', top: 0, background: 'var(--bg-2)', zIndex: 2 }}>
                  <th style={{ ...cell, width: 34 }}>✓</th>
                  {columns.map(c => <th key={c.field} style={cell}>{c.label}</th>)}
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => {
                  const hasProblem = (r.problems || []).length > 0
                  return (
                    <React.Fragment key={i}>
                      <tr style={{ opacity: include[i] ? 1 : 0.5 }}>
                        <td style={{ ...cell, textAlign: 'center' }}>
                          <input type="checkbox" checked={!!include[i]}
                            onChange={e => setInclude(prev => ({ ...prev, [i]: e.target.checked }))} />
                        </td>
                        {columns.map(c => (
                          <td key={c.field} style={cell}>
                            <input
                              style={c.num
                                ? { ...inputStyle, minWidth: 56, textAlign: 'right' }
                                : inputStyle}
                              inputMode={c.num ? 'decimal' : undefined}
                              value={r[c.field] ?? ''}
                              onChange={e => setField(i, c.field, e.target.value)}
                            />
                          </td>
                        ))}
                      </tr>
                      {hasProblem && (
                        <tr>
                          <td style={{ ...cell, border: 'none' }}></td>
                          <td colSpan={columns.length} style={{ ...cell, paddingTop: 0, color: '#ef4444', fontSize: '0.72rem', border: 'none' }}>
                            ⚠ Row {r.row}: {r.problems.join('; ')}
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>

          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', flex: 1 }}>
              <b>{approvedCount}</b> of {rows.length} {entityLabel}{rows.length === 1 ? '' : 's'} will be imported.
            </span>
            <button className="btn btn-secondary" disabled={committing} onClick={onCancel}>Cancel — import nothing</button>
            <button className="btn btn-primary" style={{ fontWeight: 700 }} disabled={committing || approvedCount === 0} onClick={commit}>
              {committing ? 'Importing…' : `Approve & Import ${approvedCount}`}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
