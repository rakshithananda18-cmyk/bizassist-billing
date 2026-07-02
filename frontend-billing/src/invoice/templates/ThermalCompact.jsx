// src/invoice/templates/ThermalCompact.jsx — compact receipt renderer (Phase 2).
// ==============================================================================
// PURE renderer of the InvoicePrintPayload for the 80mm-roll look — the viewer's
// third template. NOTE: the live POS print path (components/sales/ThermalReceipt)
// is untouched; this renders SAVED invoices from the same normalized payload as
// Classic/Modern. Monospace, dashed rules, centered 76mm column (prints centered
// on A4 too; thermal drivers take the roll width).
import { inr, n2, qty } from '../formatters'

const S = {
  page: {
    width: '76mm', margin: '0 auto', padding: '4mm 0', background: '#fff',
    color: '#000', fontFamily: "'Geist Mono', 'Courier New', monospace",
    fontSize: 11, lineHeight: 1.35,
  },
  center: { textAlign: 'center' },
  dashed: { borderTop: '1px dashed #000', margin: '4px 0' },
  row: { display: 'flex', justifyContent: 'space-between', gap: 6 },
  big: { fontWeight: 700, fontSize: 13 },
}

export default function ThermalCompact({ payload }) {
  if (!payload) return null
  const { invoice, seller, buyer, lines, totals, payments, footer, visibility } = payload
  const gst = visibility.gst_mode

  return (
    <div style={S.page} data-testid="invoice-thermal">
      <div style={S.center}>
        <div style={{ ...S.big, textTransform: 'uppercase' }}>{seller.name}</div>
        {seller.address ? <div>{seller.address}</div> : null}
        {seller.phone ? <div>Ph: {seller.phone}</div> : null}
        {gst ? <div>GSTIN: {seller.gstin}</div> : null}
        <div style={{ marginTop: 2, fontWeight: 700 }}>{invoice.title}</div>
      </div>
      <div style={S.dashed} />
      <div style={S.row}><span>Bill: {invoice.number}</span><span>{invoice.date}{invoice.time ? ` ${invoice.time}` : ''}</span></div>
      {buyer.name && buyer.name !== 'Cash Sale' ? (
        <div>Customer: {buyer.name}{buyer.phone ? ` (${buyer.phone})` : ''}</div>
      ) : null}
      <div style={S.dashed} />

      {/* items */}
      <div style={{ ...S.row, fontWeight: 700 }}>
        <span style={{ flex: 2.2 }}>ITEM</span>
        <span style={{ flex: 0.8, textAlign: 'right' }}>QTY</span>
        <span style={{ flex: 1, textAlign: 'right' }}>RATE</span>
        <span style={{ flex: 1.1, textAlign: 'right' }}>AMT</span>
      </div>
      {lines.map((l) => (
        <div key={l.sno}>
          <div style={S.row}>
            <span style={{ flex: 2.2, overflow: 'hidden' }}>{l.name}</span>
            <span style={{ flex: 0.8, textAlign: 'right' }}>{qty(l.qty)}</span>
            <span style={{ flex: 1, textAlign: 'right' }}>{n2(l.rate)}</span>
            <span style={{ flex: 1.1, textAlign: 'right' }}>{n2(l.line_total)}</span>
          </div>
          {(l.batch_no || l.expiry) ? (
            <div style={{ fontSize: 9.5 }}>
              {l.batch_no ? `B:${l.batch_no}` : ''}{l.batch_no && l.expiry ? ' ' : ''}{l.expiry ? `E:${l.expiry}` : ''}
            </div>
          ) : null}
        </div>
      ))}
      <div style={S.dashed} />

      {/* totals */}
      <div style={S.row}><span>Subtotal</span><span>{inr(totals.taxable_amount)}</span></div>
      {totals.total_discount ? <div style={S.row}><span>Discount</span><span>-{inr(totals.total_discount)}</span></div> : null}
      {gst && !visibility.igst_mode ? (
        <>
          <div style={S.row}><span>CGST</span><span>{inr(totals.cgst_total)}</span></div>
          <div style={S.row}><span>SGST</span><span>{inr(totals.sgst_total)}</span></div>
        </>
      ) : null}
      {gst && visibility.igst_mode ? <div style={S.row}><span>IGST</span><span>{inr(totals.igst_total)}</span></div> : null}
      {totals.round_off ? <div style={S.row}><span>Round Off</span><span>{inr(totals.round_off)}</span></div> : null}
      {totals.cash_discount ? <div style={S.row}><span>Cash Disc.</span><span>-{inr(totals.cash_discount)}</span></div> : null}
      <div style={{ ...S.row, ...S.big, borderTop: '1px solid #000', marginTop: 2, paddingTop: 2 }}>
        <span>TOTAL</span><span>{inr(totals.grand_total)}</span>
      </div>
      {payments.map((p, i) => (
        <div key={i} style={S.row}><span>{p.mode}</span><span>{inr(p.amount)}</span></div>
      ))}
      {totals.balance_due ? (
        <div style={{ ...S.row, fontWeight: 700 }}><span>BALANCE DUE</span><span>{inr(totals.balance_due)}</span></div>
      ) : null}
      <div style={S.dashed} />

      <div style={S.center}>
        {footer.thank_you ? <div>{footer.thank_you}</div> : null}
        <div style={{ fontSize: 9 }}>Computer generated invoice{seller.biz_id ? ` · ${seller.biz_id}` : ''}</div>
      </div>
    </div>
  )
}
