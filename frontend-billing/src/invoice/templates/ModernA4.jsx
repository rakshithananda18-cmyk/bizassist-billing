// src/invoice/templates/ModernA4.jsx — the Modern BizAssist Invoice (plan Part 2).
// ================================================================================
// PURE renderer of the InvoicePrintPayload. Premium and calm: single accent band,
// generous whitespace, light row separators, elegant totals panel, status chip.
// Prints cleanly on A4 in B/W. No fetching, no state, no money math.
import { inr, n2, qty, pct, has, statusChip } from '../formatters'

const ACCENT = '#c15f3c'      // BizAssist terracotta (matches app --accent)
const INK = '#1a1714'
const MUTED = '#6b665f'
const HAIR = '#e4e1db'

const S = {
  page: {
    background: '#fff', color: INK, width: '100%', maxWidth: '210mm',
    margin: '0 auto', padding: '0 0 10mm', boxSizing: 'border-box',
    fontFamily: "'DM Sans', 'Segoe UI', Arial, sans-serif", fontSize: 12.5,
    lineHeight: 1.5, fontVariantNumeric: 'tabular-nums',
  },
  band: {
    background: ACCENT, color: '#fff', padding: '14px 12mm',
    display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16,
  },
  section: { padding: '0 12mm' },
  label: {
    fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.08em',
    color: MUTED, fontWeight: 600, marginBottom: 2,
  },
  th: {
    padding: '7px 8px', fontSize: 10.5, textTransform: 'uppercase',
    letterSpacing: '0.05em', color: MUTED, fontWeight: 600,
    borderBottom: `2px solid ${INK}`, textAlign: 'left',
  },
  td: { padding: '7px 8px', borderBottom: `1px solid ${HAIR}`, verticalAlign: 'top' },
  right: { textAlign: 'right' },
}

const CHIP_TONES = {
  success: { background: '#eaf3ed', color: '#1f6b3a' },
  warning: { background: '#f7efe2', color: '#8a4e00' },
  danger: { background: '#f9e9e9', color: '#9b1c1c' },
}

function Th({ children, right }) {
  return <th style={{ ...S.th, ...(right ? S.right : null) }}>{children}</th>
}
function Td({ children, right, bold }) {
  return <td style={{ ...S.td, ...(right ? S.right : null), ...(bold ? { fontWeight: 600 } : null) }}>{children}</td>
}

export default function ModernA4({ payload }) {
  if (!payload) return null
  const { invoice, seller, buyer, lines, totals, payments, tax_summary, footer, visibility } = payload
  const gst = visibility.gst_mode
  const igst = visibility.igst_mode
  const chip = statusChip(totals)
  const tone = CHIP_TONES[chip.tone]

  return (
    <div style={S.page} data-testid="invoice-modern">
      {/* ── Accent band: identity left, invoice meta right ── */}
      <div style={S.band}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {seller.logo_url ? (
            <img src={seller.logo_url} alt="logo"
                 style={{ maxHeight: 44, maxWidth: 100, objectFit: 'contain', background: '#fff', borderRadius: 6, padding: 3 }} />
          ) : null}
          <div>
            <div style={{ fontSize: 19, fontWeight: 700, letterSpacing: '0.01em' }}>{seller.name}</div>
            <div style={{ fontSize: 10.5, opacity: 0.9 }}>
              {[seller.phone, seller.email].filter(Boolean).join(' · ')}
            </div>
            {gst ? <div style={{ fontSize: 10.5, opacity: 0.9 }}>GSTIN {seller.gstin}</div> : null}
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 11, letterSpacing: '0.12em', textTransform: 'uppercase', opacity: 0.85 }}>
            {invoice.title}
          </div>
          <div style={{ fontSize: 17, fontWeight: 700 }}>{invoice.number}</div>
          <div style={{ fontSize: 11, opacity: 0.9 }}>{invoice.date}{invoice.time ? ` · ${invoice.time}` : ''}</div>
        </div>
      </div>

      {/* ── Buyer + meta + status ── */}
      <div style={{ ...S.section, display: 'flex', gap: 24, padding: '16px 12mm 12px' }}>
        <div style={{ flex: 1.4 }}>
          <div style={S.label}>Billed To</div>
          <div style={{ fontWeight: 700, fontSize: 14 }}>{buyer.name}</div>
          {buyer.billing_address ? <div style={{ color: MUTED }}>{buyer.billing_address}</div> : null}
          {buyer.phone ? <div style={{ color: MUTED }}>{buyer.phone}</div> : null}
          {gst && buyer.gstin ? <div style={{ color: MUTED }}>GSTIN {buyer.gstin}</div> : null}
        </div>
        <div style={{ flex: 1 }}>
          {seller.address ? (<><div style={S.label}>From</div><div style={{ color: MUTED }}>{seller.address}</div></>) : null}
          {gst && invoice.place_of_supply ? (
            <div style={{ marginTop: 6 }}>
              <div style={S.label}>Place of Supply</div>
              <div>{invoice.place_of_supply}</div>
            </div>
          ) : null}
          {invoice.due_date ? (
            <div style={{ marginTop: 6 }}>
              <div style={S.label}>Due Date</div>
              <div>{invoice.due_date}</div>
            </div>
          ) : null}
        </div>
        <div>
          <span data-testid="status-chip" style={{
            ...tone, borderRadius: 6, padding: '4px 10px', fontSize: 11,
            fontWeight: 700, letterSpacing: '0.06em', whiteSpace: 'nowrap',
          }}>{chip.label}</span>
        </div>
      </div>

      {/* ── Items ── */}
      <div style={S.section}>
        <table style={{ borderCollapse: 'collapse', width: '100%' }}>
          <thead>
            <tr>
              <Th>#</Th>
              <Th>Item</Th>
              {has(payload, 'hsn') ? <Th>HSN</Th> : null}
              {has(payload, 'batch') ? <Th>Batch</Th> : null}
              {has(payload, 'expiry') ? <Th>Expiry</Th> : null}
              {has(payload, 'serial') ? <Th>Serial</Th> : null}
              <Th right>Qty</Th>
              <Th right>Rate</Th>
              {has(payload, 'mrp') ? <Th right>MRP</Th> : null}
              {gst ? <Th right>GST</Th> : null}
              <Th right>Amount</Th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l) => (
              <tr key={l.sno}>
                <Td>{l.sno}</Td>
                <Td bold>
                  {l.name}
                  {l.description ? <div style={{ fontWeight: 400, fontSize: 11, color: MUTED }}>{l.description}</div> : null}
                  {l.discount ? <div style={{ fontWeight: 400, fontSize: 11, color: MUTED }}>Discount {inr(l.discount)}</div> : null}
                </Td>
                {has(payload, 'hsn') ? <Td>{l.hsn_sac || '—'}</Td> : null}
                {has(payload, 'batch') ? <Td>{l.batch_no || '—'}</Td> : null}
                {has(payload, 'expiry') ? <Td>{l.expiry || '—'}</Td> : null}
                {has(payload, 'serial') ? <Td>{l.serial_no || '—'}</Td> : null}
                <Td right>{qty(l.qty)} {l.unit}</Td>
                <Td right>{n2(l.rate)}</Td>
                {has(payload, 'mrp') ? <Td right>{l.mrp != null ? n2(l.mrp) : '—'}</Td> : null}
                {gst ? <Td right>{pct(l.gst_rate)}</Td> : null}
                <Td right bold>{n2(l.line_total)}</Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ── Totals panel + payment block ── */}
      <div style={{ ...S.section, display: 'flex', gap: 24, marginTop: 14 }}>
        <div style={{ flex: 1.3 }}>
          <div style={S.label}>Amount in Words</div>
          <div style={{ fontStyle: 'italic', color: MUTED }}>{totals.amount_in_words}</div>

          {payments.length > 0 ? (
            <div style={{ marginTop: 10 }}>
              <div style={S.label}>Payments Received</div>
              {payments.map((p, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', maxWidth: 220, borderBottom: `1px solid ${HAIR}`, padding: '3px 0' }}>
                  <span>{p.mode}{p.reference ? ` · ${p.reference}` : ''}</span>
                  <span>{inr(p.amount)}</span>
                </div>
              ))}
            </div>
          ) : null}

          {seller.upi?.vpa ? (
            <div style={{ marginTop: 10 }}>
              <div style={S.label}>Pay via UPI</div>
              <div>{seller.upi.vpa}</div>
            </div>
          ) : null}

          {gst && tax_summary.length > 0 ? (
            <div style={{ marginTop: 10, fontSize: 11 }}>
              <div style={S.label}>Tax Breakup</div>
              {tax_summary.map((g, i) => (
                <div key={i} style={{ color: MUTED }}>
                  HSN {g.hsn} · {pct(g.rate)} on {inr(g.taxable)} →{' '}
                  {igst ? `IGST ${inr(g.igst)}` : `CGST ${inr(g.cgst)} + SGST ${inr(g.sgst)}`}
                </div>
              ))}
            </div>
          ) : null}
        </div>

        <div style={{ width: 250 }}>
          <TotalRow k="Taxable Amount" v={inr(totals.taxable_amount)} />
          {totals.total_discount ? <TotalRow k="Discount" v={`− ${inr(totals.total_discount)}`} /> : null}
          {gst && !igst ? <TotalRow k="CGST" v={inr(totals.cgst_total)} /> : null}
          {gst && !igst ? <TotalRow k="SGST" v={inr(totals.sgst_total)} /> : null}
          {gst && igst ? <TotalRow k="IGST" v={inr(totals.igst_total)} /> : null}
          {totals.round_off ? <TotalRow k="Round Off" v={inr(totals.round_off)} /> : null}
          {totals.cash_discount ? <TotalRow k="Cash Discount" v={`− ${inr(totals.cash_discount)}`} /> : null}
          <div style={{
            display: 'flex', justifyContent: 'space-between', padding: '8px 10px',
            background: '#faf6f3', borderTop: `2px solid ${INK}`, marginTop: 4,
            fontWeight: 800, fontSize: 15, borderRadius: '0 0 6px 6px',
          }}>
            <span>Total</span><span>{inr(totals.grand_total)}</span>
          </div>
          <TotalRow k="Paid" v={inr(totals.amount_paid)} />
          {totals.balance_due ? (
            <div style={{ display: 'flex', justifyContent: 'space-between', padding: '5px 10px', fontWeight: 700, color: '#9b1c1c' }}>
              <span>Balance Due</span><span>{inr(totals.balance_due)}</span>
            </div>
          ) : null}
        </div>
      </div>

      {/* ── Footer ── */}
      <div style={{ ...S.section, marginTop: 22, display: 'flex', gap: 24, alignItems: 'flex-end' }}>
        <div style={{ flex: 1, fontSize: 10.5, color: MUTED }}>
          {footer.terms ? (<><div style={S.label}>Terms</div><div style={{ whiteSpace: 'pre-wrap' }}>{footer.terms}</div></>) : null}
        </div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ borderBottom: `1px solid ${INK}`, width: 170, height: 34, marginBottom: 4 }} />
          <div style={{ fontSize: 10.5, color: MUTED }}>For {seller.name} · {footer.signature_label}</div>
        </div>
      </div>

      <div style={{ ...S.section, textAlign: 'center', fontSize: 9.5, color: MUTED, marginTop: 14 }}>
        {footer.thank_you ? <span>{footer.thank_you} · </span> : null}
        Computer generated invoice
        {seller.biz_id ? <span> · BizID {seller.biz_id}</span> : null}
        <span> · Powered by BizAssist</span>
      </div>
    </div>
  )
}

function TotalRow({ k, v }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '5px 10px', borderBottom: `1px solid ${HAIR}` }}>
      <span style={{ color: MUTED }}>{k}</span><span>{v}</span>
    </div>
  )
}
