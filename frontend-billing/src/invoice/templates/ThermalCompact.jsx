// src/invoice/templates/ThermalCompact.jsx — dynamic thermal receipt renderer (Phase 2).
import { inr, n2, qty } from '../formatters'
import { QRCodeSVG } from 'qrcode.react'

export default function ThermalCompact({ payload }) {
  if (!payload) return null
  const { invoice, seller, buyer, lines, totals, payments, footer, visibility, settings } = payload
  if (!settings) return null
  const gst = visibility.gst_mode
  const s = settings

  // Helper to get font size scale
  const getFontSize = () => {
    if (s.text_size === 'small') return '0.68em'
    if (s.text_size === 'large') return '0.85em'
    return '0.75em'
  }

  const containerStyle = {
    background: '#ffffff',
    color: '#1e293b',
    fontFamily: 'monospace',
    fontSize: getFontSize(),
    lineHeight: 1.4,
    width: s.thermal_page_size === '2inch' ? '58mm' : '80mm',
    margin: '0 auto',
    padding: '8px 0', // Usually printed edge-to-edge
  }

  return (
    <div style={containerStyle} data-testid="invoice-thermal">
      {/* Header */}
      <div style={{ borderBottom: '1px dashed #94a3b8', paddingBottom: '4px', marginBottom: '6px' }}>
        {s.header_layout && s.header_layout.map((row) => {
          if (row.key === 'logo' && s.print_logo && seller.logo_url) {
            return (
              <div key={row.key} style={{ textAlign: row.align, marginBottom: '4px' }}>
                <img src={seller.logo_url} alt="Logo" style={{ maxWidth: '60px', maxHeight: '60px' }} />
              </div>
            )
          }
          if (row.key === 'company_name' && s.print_company_name) {
            return (
              <div key={row.key} style={{ textAlign: row.align, fontWeight: 'bold', fontSize: '1.1em' }}>
                {seller.name}
              </div>
            )
          }
          if (row.key === 'company_address' && s.print_company_address && seller.address) {
            return (
              <div key={row.key} style={{ textAlign: row.align }}>
                {seller.address.replace(/\n/g, ', ')}
              </div>
            )
          }
          if (row.key === 'company_contact') {
            if ((s.print_company_phone && seller.phone) || (s.print_company_email && seller.email)) {
              return (
                <div key={row.key} style={{ textAlign: row.align }}>
                  {s.print_company_phone && seller.phone ? `Ph: ${seller.phone}` : ''}
                  {s.print_company_phone && seller.phone && s.print_company_email && seller.email ? ' · ' : ''}
                  {s.print_company_email && seller.email ? seller.email : ''}
                </div>
              )
            }
            return null
          }
          if (row.key === 'gstin' && s.print_gstin && seller.gstin) {
            return (
              <div key={row.key} style={{ textAlign: row.align }}>
                GSTIN: {seller.gstin}
              </div>
            )
          }
          return null
        })}
      </div>

      {/* Meta block */}
      <div style={{ marginBottom: '6px', fontSize: '0.85em', display: 'flex', flexDirection: 'column', gap: '1px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span><b>Bill No:</b> {invoice.number}</span>
          <span><b>Counter:</b> {s.counter_id || 'POS'}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span><b>Date:</b> {invoice.date}</span>
          {invoice.time ? <span><b>Time:</b> {invoice.time}</span> : null}
        </div>
        {buyer.name && buyer.name !== 'Cash Sale' ? (
          <div>
            <b>Customer:</b> {buyer.name}{buyer.phone ? ` (${buyer.phone})` : ''}
          </div>
        ) : (
          <div><b>Cashier:</b> {s.cashier_name || 'POS'}</div>
        )}
      </div>

      {/* Items table */}
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85em', marginBottom: '8px' }}>
        <thead>
          <tr style={{ borderBottom: '1px dashed #94a3b8' }}>
            {s.print_item_sno && <th style={{ textAlign: 'left', padding: '2px 0' }}>#</th>}
            <th style={{ textAlign: 'left', padding: '2px 0' }}>Item</th>
            <th style={{ textAlign: 'right', padding: '2px 0' }}>MRP</th>
            <th style={{ textAlign: 'right', padding: '2px 0' }}>Rate</th>
            <th style={{ textAlign: 'center', padding: '2px 0' }}>Qty</th>
            <th style={{ textAlign: 'right', padding: '2px 0' }}>Amt</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((l, i) => (
            <tr key={i} style={i === lines.length - 1 ? { borderBottom: '1px dashed #94a3b8' } : {}}>
              {s.print_item_sno && <td style={{ padding: '2px 0' }}>{i + 1}</td>}
              <td style={{ padding: '2px 0' }}>
                {l.name}
                {s.print_item_hsn && l.hsn_sac && (
                  <span style={{ fontSize: '0.85em', color: '#64748b', marginLeft: '4px' }}>({l.hsn_sac})</span>
                )}
              </td>
              <td style={{ textAlign: 'right', padding: '2px 0' }}>{l.mrp || l.rate}</td>
              <td style={{ textAlign: 'right', padding: '2px 0' }}>{l.rate}</td>
              <td style={{ textAlign: 'center', padding: '2px 0' }}>{parseFloat(l.qty)}</td>
              <td style={{ textAlign: 'right', padding: '2px 0' }}>{l.line_total}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Totals */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', alignItems: 'flex-end', borderBottom: '1px dashed #94a3b8', paddingBottom: '6px', marginBottom: '6px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', width: '120px', fontSize: '0.9em' }}>
          <span>Subtotal:</span>
          <span>₹{totals.subtotal}</span>
        </div>
        {s.print_item_tax && parseFloat(totals.cgst_total || 0) > 0 && (
          <div style={{ display: 'flex', justifyContent: 'space-between', width: '120px', fontSize: '0.9em' }}>
            <span>CGST:</span>
            <span>₹{totals.cgst_total}</span>
          </div>
        )}
        {s.print_item_tax && parseFloat(totals.sgst_total || 0) > 0 && (
          <div style={{ display: 'flex', justifyContent: 'space-between', width: '120px', fontSize: '0.9em' }}>
            <span>SGST:</span>
            <span>₹{totals.sgst_total}</span>
          </div>
        )}
        {s.print_item_tax && parseFloat(totals.igst_total || 0) > 0 && (
          <div style={{ display: 'flex', justifyContent: 'space-between', width: '120px', fontSize: '0.9em' }}>
            <span>IGST:</span>
            <span>₹{totals.igst_total}</span>
          </div>
        )}
        {totals.cash_discount > 0 && (
          <div style={{ display: 'flex', justifyContent: 'space-between', width: '120px', fontSize: '0.9em' }}>
            <span>Discount:</span>
            <span>-₹{totals.cash_discount}</span>
          </div>
        )}
        {parseFloat(totals.round_off || 0) !== 0 && (
          <div style={{ display: 'flex', justifyContent: 'space-between', width: '120px', fontSize: '0.9em' }}>
            <span>Round Off:</span>
            <span>₹{totals.round_off}</span>
          </div>
        )}
        <div style={{ display: 'flex', justifyContent: 'space-between', width: '120px', fontSize: '1.05em', fontWeight: 'bold' }}>
          <span>Grand Total:</span>
          <span>₹{totals.grand_total}</span>
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85em', marginBottom: '4px' }}>
        <span>Qty: {lines.reduce((a, b) => a + parseFloat(b.qty || 0), 0)}</span>
        <span>Items: {lines.length}</span>
      </div>
      {parseFloat(totals.total_discount || 0) > 0 && (
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.95em', fontWeight: 'bold', color: '#16a34a', marginBottom: '8px' }}>
          <span>You have Saved:</span>
          <span>₹{totals.total_discount}</span>
        </div>
      )}

      {s.print_tax_breakdown !== false && payload.tax_summary && payload.tax_summary.length > 0 && (
        <div style={{ fontSize: '0.75em', color: '#475569', marginBottom: '8px' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px dotted #94a3b8' }}>
                <th style={{ textAlign: 'left' }}>Tax%</th>
                <th style={{ textAlign: 'right' }}>Taxable</th>
                <th style={{ textAlign: 'right' }}>CGST</th>
                <th style={{ textAlign: 'right' }}>SGST</th>
                {visibility.igst_mode && <th style={{ textAlign: 'right' }}>IGST</th>}
              </tr>
            </thead>
            <tbody>
              {payload.tax_summary.map((t, i) => (
                <tr key={i}>
                  <td>{t.rate}%</td>
                  <td style={{ textAlign: 'right' }}>{t.taxable}</td>
                  <td style={{ textAlign: 'right' }}>{t.cgst}</td>
                  <td style={{ textAlign: 'right' }}>{t.sgst}</td>
                  {visibility.igst_mode && <td style={{ textAlign: 'right' }}>{t.igst}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(s.fssai_no || s.prices_incl_gst) && (
        <div style={{ fontSize: '0.75em', color: '#64748b', textAlign: 'center', marginBottom: '8px' }}>
          {s.prices_incl_gst && <div>E. &amp; O.E. · Prices Incl. GST</div>}
          {s.fssai_no && <div>FSSAI: {s.fssai_no}</div>}
        </div>
      )}

      {s.print_amount_in_words && totals.amount_in_words && (
        <div style={{ fontSize: '0.8em', color: '#64748b', fontStyle: 'italic', marginBottom: '8px', textAlign: 'center' }}>
          {totals.amount_in_words}
        </div>
      )}

      {footer.terms && (
        <div style={{ fontSize: '0.8em', color: '#64748b', textAlign: 'center', borderTop: '1px dashed #94a3b8', paddingTop: '4px', marginTop: '4px' }}>
          <b>Terms:</b> {footer.terms}
        </div>
      )}

      {(s.print_signature || s.customer_signature) && (
        <div style={{ marginTop: '24px', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
          {s.customer_signature ? (
            <div style={{ borderTop: '1px dashed #64748b', width: '110px', textAlign: 'center', paddingTop: '2px', fontSize: '0.75em' }}>
              {footer.customer_signature_label || 'Customer Signature'}
            </div>
          ) : <div />}
          
          {s.print_signature ? (
            <div style={{ borderTop: '1px dashed #64748b', width: '110px', textAlign: 'center', paddingTop: '2px', fontSize: '0.75em' }}>
              {footer.signature_label || 'Authorised Signatory'}
            </div>
          ) : <div />}
        </div>
      )}

      {/* Computer generated note — always shown */}
      <div style={{ textAlign: 'center', fontSize: '0.7em', color: '#94a3b8', marginTop: '10px', paddingTop: '4px', borderTop: '1px dotted #e2e8f0' }}>
        Computer generated invoice. No signature required.
      </div>

      {s.print_invoice_qr && invoice.public_url && (
        <div style={{ textAlign: 'center', marginTop: '12px' }}>
          <QRCodeSVG value={invoice.public_url} size={90} />
          <div style={{ fontSize: '0.7em', color: '#64748b', marginTop: '4px' }}>
            Scan to view invoice online
          </div>
        </div>
      )}
    </div>
  )
}
