// components/stock/IntakeConfirmSheet.jsx
// ============================================================================
// The review step between building a stock intake and committing it.
//
// Deliberately BEFORE the write, not after. Confirming performs the save; Edit
// returns to the sheet with every row intact. A review shown after the rows had
// already been posted would offer an "Edit" that reopens committed stock, and a
// second Save All would post it twice — on the one screen where a duplicate is
// real inventory that never arrived.
//
// The totals row mirrors the POS cart footer (COLUMN TOTALS) because it answers
// the same question in the same place: what does everything in this table add
// up to, before I commit it.
import React from 'react'
import { CheckIcon, CloseIcon } from '../Icons'
import { intakeTotals } from '../../utils/intakeTotals'

const money = (n) =>
  `₹${(Number(n) || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

const qtyFmt = (n) => (Number(n) || 0).toLocaleString('en-IN', { maximumFractionDigits: 3 })

const near = (a, b) => Math.abs((Number(a) || 0) - (Number(b) || 0)) < 0.005

/**
 * What confirming this row will actually DO, in the owner's words.
 *
 * The table showed money but not consequences, so "will this create a product?
 * will it overwrite my selling price? is this a new batch?" were unanswerable
 * on the screen whose only job is to answer them. Each effect is derived from
 * the same fields saveAll branches on, so the list cannot claim something the
 * save will not do.
 */
export function rowEffects(r) {
  const out = []
  const qty = (Number(r.qty) || 0) + (Number(r.free) || 0)

  if (r._type === 'new') {
    out.push({ kind: 'new', text: 'Creates this product' })
  }
  out.push({ kind: 'stock', text: `Adds ${qtyFmt(qty)} to stock` })

  if (r._type === 'existing') {
    if (r._price_mode === 'update') {
      const costChanged = r.current_cost != null && !near(r.current_cost, r.cost_price)
      const sellChanged = r.current_sell != null && !near(r.current_sell, r.selling_price)
      if (costChanged) out.push({ kind: 'price', text: `Cost ₹${r.current_cost} → ₹${r.cost_price}` })
      if (sellChanged) out.push({ kind: 'price', text: `Sell ₹${r.current_sell} → ₹${r.selling_price}` })
      if (!costChanged && !sellChanged) out.push({ kind: 'muted', text: 'Price unchanged' })
    } else {
      // 'new_batch' — the product's price is deliberately left alone.
      out.push({ kind: 'muted', text: 'Keeps the current price' })
    }
  }

  if (r.batch) {
    out.push({ kind: 'batch', text: `Batch ${r.batch}${r.expiry ? ` · exp ${r.expiry}` : ''}` })
  }
  return out
}

const EFFECT_STYLE = {
  new:   { color: 'var(--accent)', fontWeight: 700 },
  price: { color: 'var(--warning, #b45309)', fontWeight: 600 },
  batch: { color: '#818cf8', fontWeight: 600 },
  stock: { color: 'var(--text-primary)' },
  muted: { color: 'var(--text-muted)' },
}

export default function IntakeConfirmSheet({
  open,
  rows = [],
  adjustments = {},
  distributor = {},
  onEdit,
  onConfirm,
  saving = false,
}) {
  if (!open) return null

  const t = intakeTotals(rows, adjustments)

  return (
    <div className="table-fullscreen-overlay" role="dialog" aria-modal="true"
         aria-label="Confirm stock intake">
      <div className="table-fullscreen-panel">

        <div className="table-fullscreen-header">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span style={{ fontWeight: 800, fontSize: '0.95rem', color: 'var(--text-primary)' }}>
              Confirm stock intake
            </span>
            <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
              {rows.length} item{rows.length !== 1 ? 's' : ''}
              {distributor?.name ? ` from ${distributor.name}` : ''}
              {distributor?.invoice_no ? ` · bill ${distributor.invoice_no}` : ''}
              {' · nothing is recorded until you confirm'}
            </span>
          </div>
          <button type="button" className="table-fullscreen-btn" onClick={onEdit} disabled={saving}>
            <CloseIcon size={14} /> Close
          </button>
        </div>

        <div className="data-table-wrap" style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ width: 44, textAlign: 'right' }}>#</th>
                <th>Product</th>
                <th style={{ textAlign: 'right' }}>Qty</th>
                <th style={{ textAlign: 'right' }}>Free</th>
                <th style={{ textAlign: 'right' }}>Cost</th>
                <th style={{ textAlign: 'right' }}>Tax %</th>
                <th style={{ textAlign: 'right' }}>Taxable</th>
                <th style={{ textAlign: 'right' }}>Tax</th>
                <th style={{ textAlign: 'right' }}>Net</th>
                <th style={{ minWidth: 200 }}>What happens</th>
              </tr>
            </thead>
            <tbody>
              {t.lines.map((l, i) => (
                <tr key={l.row._key ?? i}>
                  <td className="td-mono" style={{ textAlign: 'right', color: 'var(--text-muted)' }}>{i + 1}</td>
                  <td className="td-primary">
                    {l.row.name || '—'}
                    {l.row._type === 'new' && (
                      <span className="badge badge-info" style={{ marginLeft: 6, fontSize: '0.62rem' }}>NEW</span>
                    )}
                    {l.row.batch && (
                      <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                        batch {l.row.batch}{l.row.expiry ? ` · exp ${l.row.expiry}` : ''}
                      </div>
                    )}
                  </td>
                  <td style={{ textAlign: 'right' }}>{qtyFmt(l.qty)}</td>
                  <td style={{ textAlign: 'right', color: l.free ? 'var(--success)' : 'var(--text-muted)' }}>
                    {qtyFmt(l.free)}
                  </td>
                  <td style={{ textAlign: 'right' }}>{money(l.cost)}</td>
                  <td style={{ textAlign: 'right', color: 'var(--text-muted)' }}>{l.rate}%</td>
                  <td style={{ textAlign: 'right' }}>{money(l.taxable)}</td>
                  <td style={{ textAlign: 'right' }}>{money(l.tax)}</td>
                  <td style={{ textAlign: 'right', fontWeight: 700 }}>{money(l.net)}</td>
                  <td>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 1, fontSize: '0.72rem' }}>
                      {rowEffects(l.row).map((e, k) => (
                        <span key={k} style={EFFECT_STYLE[e.kind]}>{e.text}</span>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>

            {/* Column totals — same role as the POS cart footer. */}
            <tfoot>
              <tr className="pos-cart-foot">
                <td className="pos-sticky-footer"></td>
                <td className="pos-footer-totals-label pos-sticky-footer">Column totals</td>
                <td className="pos-sticky-footer" style={{ textAlign: 'right', fontWeight: 700 }}>{qtyFmt(t.qty)}</td>
                <td className="pos-sticky-footer" style={{ textAlign: 'right', fontWeight: 700 }}>{qtyFmt(t.free)}</td>
                <td className="pos-sticky-footer"></td>
                <td className="pos-sticky-footer"></td>
                <td className="pos-sticky-footer" style={{ textAlign: 'right', fontWeight: 700 }}>{money(t.gross)}</td>
                <td className="pos-sticky-footer" style={{ textAlign: 'right', fontWeight: 700 }}>{money(t.taxTotal)}</td>
                <td className="pos-sticky-footer" style={{ textAlign: 'right', fontWeight: 800 }}>{money(t.gross + t.taxTotal)}</td>
                <td className="pos-sticky-footer"></td>
              </tr>
            </tfoot>
          </table>
        </div>

        {/* Payable strip + the decision. Mirrors the intake side panel so the
            two never disagree — both read utils/intakeTotals. */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          gap: 16, flexWrap: 'wrap',
          padding: '12px 16px', borderTop: '1px solid var(--border)',
          background: 'var(--bg-3)', flexShrink: 0,
        }}>
          <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', fontSize: '0.8rem' }}>
            <span style={{ color: 'var(--text-muted)' }}>Gross <b style={{ color: 'var(--text-primary)' }}>{money(t.gross)}</b></span>
            {t.itemDisc > 0 && <span style={{ color: 'var(--text-muted)' }}>Item disc <b style={{ color: 'var(--text-primary)' }}>−{money(t.itemDisc)}</b></span>}
            <span style={{ color: 'var(--text-muted)' }}>Tax <b style={{ color: 'var(--text-primary)' }}>{money(t.taxTotal)}</b></span>
            {t.cess > 0 && <span style={{ color: 'var(--text-muted)' }}>Cess <b style={{ color: 'var(--text-primary)' }}>{money(t.cess)}</b></span>}
            {t.cashDisc > 0 && <span style={{ color: 'var(--text-muted)' }}>Cash disc <b style={{ color: 'var(--text-primary)' }}>−{money(t.cashDisc)}</b></span>}
            <span style={{ fontWeight: 800, color: 'var(--text-primary)' }}>Payable {money(t.payable)}</span>
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            <button type="button" className="btn btn-secondary btn-sm" onClick={onEdit} disabled={saving}>
              Edit
            </button>
            <button type="button" className="btn btn-primary btn-sm" onClick={onConfirm}
                    disabled={saving || rows.length === 0}>
              {saving
                ? 'Recording…'
                : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                    <CheckIcon size={14} /> Confirm &amp; record
                  </span>}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
