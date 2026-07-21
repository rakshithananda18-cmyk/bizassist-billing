// src/invoice/templates/ClassicA4.jsx — the Standard Printed Invoice (plan Part 1).
// =================================================================================
// PURE renderer of the InvoicePrintPayload: monochrome, table-ruled, dense — the
// market-standard layout every distributor/CA recognises. No fetching, no state,
// no money math; column set and blocks come from payload.visibility.
//
// 2026-07 polish: same classic bones, cleaner ink. One strong outer frame, light
// grey inner rules (prints crisp, reads calmer), consistent cell padding, muted
// secondary text, and a properly weighted totals ladder. All content, column
// logic and test hooks are unchanged.
import { inr, n2, qty, pct, has } from '../formatters'

const INK = '#111'
const MUTED = '#555'
const RULE = '#bbb'
const FRAME = '#333'
const HEAD_BG = '#eee'

const S = {
  page: {
    background: '#fff', color: INK, width: '100%', maxWidth: '210mm',
    margin: '0 auto', padding: '10mm 9mm', boxSizing: 'border-box',
    fontFamily: "Arial, sans-serif", fontSize: 12, lineHeight: 1.5,
    fontVariantNumeric: 'tabular-nums',
  },
  box: { border: 'none' },
  th: {
    border: '1px solid #bbb',
    padding: '5px 7px', fontWeight: 700, fontSize: 11, textAlign: 'left',
    background: HEAD_BG, textTransform: 'uppercase', letterSpacing: '0.03em',
    whiteSpace: 'nowrap',
  },
  td: {
    border: '1px solid #bbb',
    padding: '5px 7px', verticalAlign: 'top', fontSize: 11,
  },
  right: { textAlign: 'right' },
  label: {
    fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em',
    fontWeight: 700, color: MUTED, marginBottom: 4, borderBottom: '1px solid #999', paddingBottom: 3
  },
}

function Th({ children, right }) {
  return <th style={{ ...S.th, ...(right ? S.right : null) }}>{children}</th>
}
function Td({ children, right, colSpan, bold }) {
  return (
    <td colSpan={colSpan} style={{ ...S.td, ...(right ? S.right : null), ...(bold ? { fontWeight: 700 } : null) }}>
      {children}
    </td>
  )
}

export default function ClassicA4({ payload }) {
  if (!payload) return null
  const { invoice, seller, buyer, lines, totals, payments, tax_summary, footer, visibility } = payload
  const gst = visibility.gst_mode
  const igst = visibility.igst_mode

  return (
    <div style={S.page} data-testid="invoice-classic">
      {/* ── A. Header ── */}
      <div style={{ display: 'flex', gap: 14, alignItems: 'center', marginBottom: 12, borderBottom: `2px solid ${FRAME}`, paddingBottom: 10 }}>
        {seller.logo_url ? (
          <img src={seller.logo_url} alt="logo" style={{ maxHeight: 54, maxWidth: 110, objectFit: 'contain' }} />
        ) : null}
        <div style={{ flex: 1, textAlign: 'center' }}>
          <div style={{ fontSize: 21, fontWeight: 800, letterSpacing: '0.01em', lineHeight: 1.2 }}>{seller.name}</div>
          {seller.address ? <div style={{ color: MUTED, fontSize: 11.5, marginTop: 2 }}>{seller.address}</div> : null}
          <div style={{ color: MUTED, fontSize: 11.5 }}>
            {seller.phone ? <span>Ph: {seller.phone}</span> : null}
            {seller.phone && seller.email ? <span style={{ margin: '0 5px', color: RULE }}>|</span> : ''}
            {seller.email ? <span>{seller.email}</span> : null}
          </div>
          {gst ? (
            <div style={{ fontWeight: 700, fontSize: 11.5, marginTop: 3 }}>
              GSTIN: {seller.gstin}
              {seller.state ? <span style={{ fontWeight: 400, color: MUTED }}> · State: {seller.state} ({seller.state_code})</span> : null}
            </div>
          ) : null}
        </div>
      </div>

      {/* title strip */}
      <div style={{
        padding: '4px 12px', textAlign: 'center',
        fontWeight: 800, fontSize: 14, letterSpacing: '0.14em',
        textTransform: 'uppercase', borderBottom: `1px solid ${RULE}`, marginBottom: 12
      }}>
        {invoice.title}
      </div>

      {/* ── meta + B. buyer ── */}
      <div style={{ display: 'flex', gap: 32, marginBottom: 12 }}>
        <div style={{ flex: 1.2, padding: '0' }}>
          <div style={S.label}>Billed To</div>
          <div style={{ fontWeight: 700, fontSize: 12.5 }}>{buyer.name}</div>
          {buyer.billing_address ? <div style={{ color: MUTED, fontSize: 11.5 }}>{buyer.billing_address}</div> : null}
          {buyer.phone ? <div style={{ fontSize: 11.5 }}>Ph: {buyer.phone}</div> : null}
          {gst && buyer.gstin ? <div style={{ fontSize: 11.5 }}>GSTIN: <b>{buyer.gstin}</b></div> : null}
          {gst && buyer.state ? <div style={{ fontSize: 11.5, color: MUTED }}>State: {buyer.state} ({buyer.state_code})</div> : null}
        </div>
        <div style={{ flex: 1, padding: '0' }}>
          <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 11.5 }}><tbody>
            <MetaRow k="Invoice No.">{invoice.number}</MetaRow>
            <MetaRow k="Date">{invoice.date}{invoice.time ? ` · ${invoice.time}` : ''}</MetaRow>
            {invoice.due_date ? <MetaRow k="Due Date" plain>{invoice.due_date}</MetaRow> : null}
            {gst && invoice.place_of_supply ? <MetaRow k="Place of Supply" plain>{invoice.place_of_supply}</MetaRow> : null}
            {gst && invoice.reverse_charge ? <MetaRow k="Reverse Charge" plain>Yes</MetaRow> : null}
          </tbody></table>
        </div>
      </div>

      {/* ── C. Item table ── */}
      <table style={{
        borderCollapse: 'collapse', width: '100%', marginTop: 6, marginBottom: 12
      }}>
        <thead>
          <tr>
            <Th>#</Th>
            <Th>Item</Th>
            {has(payload, 'hsn') ? <Th>HSN/SAC</Th> : null}
            {has(payload, 'batch') ? <Th>Batch</Th> : null}
            {has(payload, 'expiry') ? <Th>Exp.</Th> : null}
            {has(payload, 'serial') ? <Th>Serial/IMEI</Th> : null}
            {has(payload, 'mrp') ? <Th right>MRP</Th> : null}
            <Th right>Qty</Th>
            <Th>Unit</Th>
            <Th right>Rate</Th>
            <Th right>Disc.</Th>
            {gst ? <Th right>Taxable</Th> : null}
            {gst ? <Th right>GST%</Th> : null}
            {gst && !igst ? <Th right>CGST</Th> : null}
            {gst && !igst ? <Th right>SGST</Th> : null}
            {gst && igst ? <Th right>IGST</Th> : null}
            <Th right>Amount</Th>
          </tr>
        </thead>
        <tbody>
          {lines.map((l) => (
            <tr key={l.sno}>
              <Td>{l.sno}</Td>
              <Td>
                <span style={{ fontWeight: 600 }}>{l.name}</span>
                {l.description ? <div style={{ fontSize: 10, color: MUTED }}>{l.description}</div> : null}
              </Td>
              {has(payload, 'hsn') ? <Td>{l.hsn_sac || '—'}</Td> : null}
              {has(payload, 'batch') ? <Td>{l.batch_no || '—'}</Td> : null}
              {has(payload, 'expiry') ? <Td>{l.expiry || '—'}</Td> : null}
              {has(payload, 'serial') ? <Td>{l.serial_no || '—'}</Td> : null}
              {has(payload, 'mrp') ? <Td right>{l.mrp != null ? n2(l.mrp) : '—'}</Td> : null}
              <Td right>{qty(l.qty)}</Td>
              <Td>{l.unit}</Td>
              <Td right>{n2(l.rate)}</Td>
              <Td right>{l.discount ? n2(l.discount) : '—'}</Td>
              {gst ? <Td right>{n2(l.taxable_value)}</Td> : null}
              {gst ? <Td right>{pct(l.gst_rate)}</Td> : null}
              {gst && !igst ? <Td right>{n2(l.cgst)}</Td> : null}
              {gst && !igst ? <Td right>{n2(l.sgst)}</Td> : null}
              {gst && igst ? <Td right>{n2(l.igst)}</Td> : null}
              <Td right bold>{n2(l.line_total)}</Td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* ── D. Totals + words ── */}
      <div style={{ display: 'flex', gap: 32, marginTop: 12 }}>
        <div style={{ flex: 1.3, padding: '0' }}>
          <div style={S.label}>Amount in Words</div>
          <div style={{ fontStyle: 'italic', fontSize: 11.5 }}>{totals.amount_in_words}</div>

          {payments.length > 0 ? (
            <div style={{ marginTop: 10 }}>
              <div style={S.label}>Payments</div>
              {payments.map((p, i) => {
                const when = [p.date, p.time].filter(Boolean).join(' ')
                const meta = [p.reference, when].filter(Boolean).join(' · ')
                return (
                  <div key={i} style={{ fontSize: 11.5 }}>
                    {p.mode}: {inr(p.amount)}{meta ? <span style={{ color: MUTED }}> ({meta})</span> : ''}
                  </div>
                )
              })}
            </div>
          ) : null}

          {gst && tax_summary.length > 0 ? (
            <div style={{ marginTop: 10 }}>
              <div style={S.label}>Tax Summary (HSN-wise)</div>
              <table style={{ borderCollapse: 'collapse', width: '100%', marginTop: 6 }}>
                <thead>
                  <tr>
                    <Th>HSN</Th><Th right>Taxable</Th><Th right>Rate</Th>
                    {igst ? <Th right>IGST</Th> : <><Th right>CGST</Th><Th right>SGST</Th></>}
                  </tr>
                </thead>
                <tbody>
                  {tax_summary.map((g, i) => (
                    <tr key={i}>
                      <Td>{g.hsn}</Td><Td right>{n2(g.taxable)}</Td><Td right>{pct(g.rate)}</Td>
                      {igst ? <Td right>{n2(g.igst)}</Td> : <><Td right>{n2(g.cgst)}</Td><Td right>{n2(g.sgst)}</Td></>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>

        <div style={{ flex: 1, padding: '0' }}>
          <table style={{ borderCollapse: 'collapse', width: '100%' }}><tbody>
            <Row k="Sub Total (Taxable)" v={inr(totals.taxable_amount)} />
            {totals.total_discount ? <Row k="Discount" v={`− ${inr(totals.total_discount)}`} /> : null}
            {gst && !igst ? <Row k="CGST" v={inr(totals.cgst_total)} /> : null}
            {gst && !igst ? <Row k="SGST" v={inr(totals.sgst_total)} /> : null}
            {gst && igst ? <Row k="IGST" v={inr(totals.igst_total)} /> : null}
            {gst && totals.cess_total ? <Row k="Cess" v={inr(totals.cess_total)} /> : null}
            {totals.round_off ? <Row k="Round Off" v={inr(totals.round_off)} /> : null}
            {totals.cash_discount ? <Row k="Cash Discount" v={`− ${inr(totals.cash_discount)}`} /> : null}
            <Row k="GRAND TOTAL" v={inr(totals.grand_total)} big />
            <Row k="Amount Paid" v={inr(totals.amount_paid)} muted />
            {totals.balance_due ? <Row k="Balance Due" v={inr(totals.balance_due)} big /> : null}
          </tbody></table>
        </div>
      </div>

      {/* ── F. Footer ── */}
      <div style={{ display: 'flex', gap: 18, marginTop: 12 }}>
        <div style={{ flex: 1.4 }}>
          {footer.terms ? (
            <>
              <div style={S.label}>Terms &amp; Conditions</div>
              <div style={{ fontSize: 10, whiteSpace: 'pre-wrap', color: MUTED }}>{footer.terms}</div>
            </>
          ) : null}
          {footer.return_policy ? (
            <div style={{ fontSize: 10, marginTop: 4, color: MUTED }}>{footer.return_policy}</div>
          ) : null}
        </div>
        {/* Signature blocks — IDENTICAL structure (top label → ruled space →
            caption) so both signature lines sit at exactly the same height.
            The company block carries "For <business>" ABOVE its line (the
            standard letterhead convention); the customer block reserves the
            same label row so nothing shifts. */}
        <div style={{ flex: 1, textAlign: 'center', alignSelf: 'flex-end' }}>
          <div style={{ fontSize: 10, fontWeight: 700, height: 14, marginBottom: 2 }}>{' '}</div>
          <div style={{ borderBottom: `1px solid ${INK}`, height: 34, marginBottom: 5 }} />
          <div style={{ fontSize: 10, color: MUTED }}>{footer.customer_signature_label}</div>
        </div>
        <div style={{ flex: 1, textAlign: 'center', alignSelf: 'flex-end' }}>
          <div style={{ fontSize: 10, fontWeight: 700, height: 14, marginBottom: 2 }}>For {seller.name}</div>
          <div style={{ borderBottom: `1px solid ${INK}`, height: 34, marginBottom: 5 }} />
          <div style={{ fontSize: 10, color: MUTED }}>{footer.signature_label}</div>
        </div>
      </div>

      <div style={{ textAlign: 'center', fontSize: 9.5, color: MUTED, marginTop: 12, borderTop: `1px solid ${RULE}`, paddingTop: 6 }}>
        {footer.thank_you ? <span>{footer.thank_you} · </span> : null}
        <span style={{ fontWeight: 600 }}>This is a computer generated invoice.</span>
        {seller.biz_id ? <span> · BizID: {seller.biz_id}</span> : null}
      </div>
    </div>
  )
}

function MetaRow({ k, children, plain }) {
  return (
    <tr>
      <td style={{ paddingRight: 10, padding: '1.5px 10px 1.5px 0', color: MUTED, whiteSpace: 'nowrap' }}>{k}</td>
      <td style={{ padding: '1.5px 0', fontWeight: plain ? 400 : 700 }}>{children}</td>
    </tr>
  )
}

function Row({ k, v, big, muted }) {
  const base = { padding: '3px 4px', fontSize: 11.5 }
  const emph = big ? { fontWeight: 800, fontSize: 13, borderTop: `1.5px solid ${FRAME}`, paddingTop: 5 } : null
  const dim = muted ? { color: MUTED } : null
  return (
    <tr>
      <td style={{ ...base, ...emph, ...dim }}>{k}</td>
      <td style={{ ...base, textAlign: 'right', fontVariantNumeric: 'tabular-nums', ...emph, ...dim }}>{v}</td>
    </tr>
  )
}
