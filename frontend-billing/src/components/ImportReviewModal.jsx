// components/ImportReviewModal.jsx — the products-import approval table.
// ======================================================================
// Owner requirement (2026-07): nothing from a file lands in the product table
// without a human looking at it. The backend parses the CSV with ?preview=1
// (zero writes), this modal shows every row EDITABLE with problems flagged,
// and only the ticked rows are committed on "Approve & Import".
import React, { useState, useMemo } from 'react'

const NUM_FIELDS = ['selling_price', 'cost_price', 'mrp', 'cgst_rate', 'sgst_rate', 'opening_stock']

export default function ImportReviewModal({ open, items, onCancel, onCommit, committing }) {
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
        for (const f of NUM_FIELDS) {
          if (out[f] === '' || out[f] == null) { out[f] = f === 'mrp' ? null : 0 }
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
                  <th style={cell}>Name *</th>
                  <th style={cell}>SKU</th>
                  <th style={cell}>Barcode</th>
                  <th style={cell}>Unit</th>
                  <th style={cell}>Category</th>
                  <th style={cell}>Sell ₹</th>
                  <th style={cell}>Cost ₹</th>
                  <th style={cell}>MRP</th>
                  <th style={cell}>CGST%</th>
                  <th style={cell}>SGST%</th>
                  <th style={cell}>Open. stock</th>
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
                        <td style={cell}><input style={inputStyle} value={r.name || ''} onChange={e => setField(i, 'name', e.target.value)} /></td>
                        <td style={cell}><input style={inputStyle} value={r.sku || ''} onChange={e => setField(i, 'sku', e.target.value)} /></td>
                        <td style={cell}><input style={inputStyle} value={r.barcode || ''} onChange={e => setField(i, 'barcode', e.target.value)} /></td>
                        <td style={cell}><input style={{ ...inputStyle, minWidth: 50 }} value={r.unit || ''} onChange={e => setField(i, 'unit', e.target.value)} /></td>
                        <td style={cell}><input style={inputStyle} value={r.category || ''} onChange={e => setField(i, 'category', e.target.value)} /></td>
                        {NUM_FIELDS.map(f => (
                          <td key={f} style={cell}>
                            <input style={{ ...inputStyle, minWidth: 56, textAlign: 'right' }} inputMode="decimal"
                              value={r[f] ?? ''} onChange={e => setField(i, f, e.target.value)} />
                          </td>
                        ))}
                      </tr>
                      {hasProblem && (
                        <tr>
                          <td style={{ ...cell, border: 'none' }}></td>
                          <td colSpan={11} style={{ ...cell, paddingTop: 0, color: '#ef4444', fontSize: '0.72rem', border: 'none' }}>
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
              <b>{approvedCount}</b> of {rows.length} row{rows.length === 1 ? '' : 's'} will be imported.
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
