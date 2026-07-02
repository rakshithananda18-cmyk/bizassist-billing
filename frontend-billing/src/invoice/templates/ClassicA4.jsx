// src/invoice/templates/ClassicA4.jsx — the Standard Printed Invoice (plan Part 1).
// =================================================================================
// PURE renderer of the InvoicePrintPayload: monochrome, table-ruled, dense — the
// market-standard layout every distributor/CA recognises. No fetching, no state,
// no money math; column set and blocks come from payload.visibility.
import { inr, n2, qty, pct, has } from '../formatters'

const S = {
  page: {
    background: '#fff', color: '#000', width: '100%', maxWidth: '210mm',
    margin: '0 auto', padding: '10mm 9mm', boxSizing: 'border-box',
    fontFamily: "'DM Sans', Arial, sans-serif", fontSize: 12, lineHeight: 1.45,
    fontVariantNumeric: 'tabular-nums',
  },
  hairline: { borderBottom: '1px solid #000' },
  box: { border: '1px solid #000' },
  th: {
    border: '1px solid #000', padding: '4px 6px', fontWeight: 700,
    fontSize: 11, textAlign: 'left', background: '#f2f2f2',
  },
  td: { border: '1px solid #000', padding: '4px 6px', verticalAlign: 'top' },
  right: { textAlign: 'right' },
  label: { fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 700 },
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
      <div style={{ ...S.box, padding: '8px 10px', display: 'flex', gap: 12, alignItems: 'center' }}>
        {seller.logo_url ? (
          <img src={seller.logo_url} alt="logo" style={{ maxHeight: 52, maxWidth: 110, objectFit: 'contain' }} />
        ) : null}
        <div style={{ flex: 1, textAlign: 'center' }}>
          <div style={{ fontSize: 20, fontWeight: 800, letterSpacing: '0.02em' }}>{seller.name}</div>
          {seller.address ? <div>{seller.address}</div> : null}
          <div>
            {seller.phone ? <span>Ph: {seller.phone}</span> : null}
            {seller.phone && seller.email ? ' · ' : ''}
            {seller.email ? <span>{seller.email}</span> : null}
          </div>
          {gst ? (
            <div style={{ fontWeight: 700 }}>
              GSTIN: {seller.gstin}
              {seller.state ? <span style={{ fontWeight: 400 }}> · State: {seller.state} ({seller.state_code})</span> : null}
            </div>
          ) : null}
        </div>
      </div>

      {/* title strip */}
      <div style={{ ...S.box, borderTop: 'none', padding: '3px 10px', textAlign: 'center', fontWeight: 800, fontSize: 13, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
        {invoice.title}
      </div>

      {/* ── meta + B. buyer ── */}
      <div style={{ display: 'flex', borderLeft: '1px solid #000', borderRight: '1px solid #000' }}>
        <div style={{ flex: 1.2, padding: '6px 10px', borderRight: '1px solid #000' }}>
          <div style={S.label}>Billed To</div>
          <div style={{ fontWeight: 700 }}>{buyer.name}</div>
          {buyer.billing_address ? <div>{buyer.billing_address}</div> : null}
          {buyer.phone ? <div>Ph: {buyer.phone}</div> : null}
          {gst && buyer.gstin ? <div>GSTIN: {buyer.gstin}</div> : null}
          {gst && buyer.state ? <div>State: {buyer.state} ({buyer.state_code})</div> : null}
        </div>
        <div style={{ flex: 1, padding: '6px 10px', fontSize: 12 }}>
          <table style={{ borderCollapse: 'collapse', width: '100%' }}><tbody>
            <tr><td style={{ paddingRight: 8 }}>Invoice No.</td><td style={{ fontWeight: 700 }}>{invoice.number}</td></tr>
            <tr><td>Date</td><td style={{ fontWeight: 700 }}>{invoice.date}{invoice.time ? ` · ${invoice.time}` : ''}</td></tr>
            {invoice.due_date ? <tr><td>Due Date</td><td>{invoice.due_date}</td></tr> : null}
            {gst && invoice.place_of_supply ? <tr><td>Place of Supply</td><td>{invoice.place_of_supply}</td></tr> : null}
            {gst && invoice.reverse_charge ? <tr><td>Reverse Charge</td><td>Yes</td></tr> : null}
          </tbody></table>
        </div>
      </div>

      {/* ── C. Item table ── */}
      <table style={{ borderCollapse: 'collapse', width: '100%' }}>
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
                {l.name}
                {l.description ? <div style={{ fontSize: 10, color: '#333' }}>{l.description}</div> : null}
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
      <div style={{ display: 'flex', border: '1px solid #000', borderTop: 'none' }}>
        <div style={{ flex: 1.3, padding: '6px 10px', borderRight: '1px solid #000' }}>
          <div style={S.label}>Amount in Words</div>
          <div style={{ fontStyle: 'italic' }}>{totals.amount_in_words}</div>

          {payments.length > 0 ? (
            <div style={{ marginTop: 8 }}>
              <div style={S.label}>Payments</div>
              {payments.map((p, i) => (
                <div key={i}>
                  {p.mode}: {inr(p.amount)}{p.reference ? ` (${p.reference})` : ''}
                </div>
              ))}
            </div>
          ) : null}

          {gst && tax_summary.length > 0 ? (
            <div style={{ marginTop: 8 }}>
              <div style={S.label}>Tax Summary (HSN-wise)</div>
              <table style={{ borderCollapse: 'collapse', marginTop: 2 }}>
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

        <div style={{ flex: 1, padding: '6px 10px' }}>
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
            <Row k="Amount Paid" v={inr(totals.amount_paid)} />
            {totals.balance_due ? <Row k="Balance Due" v={inr(totals.balance_due)} big /> : null}
          </tbody></table>
        </div>
      </div>

      {/* ── F. Footer ── */}
      <div style={{ display: 'flex', gap: 16, marginTop: 10 }}>
        <div style={{ flex: 1.4 }}>
          {footer.terms ? (
            <>
              <div style={S.label}>Terms &amp; Conditions</div>
              <div style={{ fontSize: 10, whiteSpace: 'pre-wrap' }}>{footer.terms}</div>
            </>
          ) : null}
          {footer.return_policy ? (
            <div style={{ fontSize: 10, marginTop: 4 }}>{footer.return_policy}</div>
          ) : null}
        </div>
        <div style={{ flex: 1, textAlign: 'center', alignSelf: 'flex-end' }}>
          <div style={{ borderBottom: '1px solid #000', height: 36, marginBottom: 4 }} />
          <div style={{ fontSize: 10 }}>{footer.customer_signature_label}</div>
        </div>
        <div style={{ flex: 1, textAlign: 'center', alignSelf: 'flex-end' }}>
          <div style={{ borderBottom: '1px solid #000', height: 36, marginBottom: 4 }} />
          <div style={{ fontSize: 10, fontWeight: 700 }}>For {seller.name}<br />{footer.signature_label}</div>
        </div>
      </div>

      <div style={{ textAlign: 'center', fontSize: 9, color: '#444', marginTop: 10 }}>
        {footer.thank_you ? <span>{footer.thank_you} · </span> : null}
        This is a computer generated invoice.
        {seller.biz_id ? <span> · BizID: {seller.biz_id}</span> : null}
      </div>
    </div>
  )
}

function Row({ k, v, big }) {
  return (
    <tr>
      <td style={{ padding: '2px 4px', ...(big ? { fontWeight: 800, fontSize: 13, borderTop: '1px solid #000' } : null) }}>{k}</td>
      <td style={{ padding: '2px 4px', textAlign: 'right', ...(big ? { fontWeight: 800, fontSize: 13, borderTop: '1px solid #000' } : null) }}>{v}</td>
    </tr>
  )
}
