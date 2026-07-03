// components/sales/ThermalReceipt.jsx
// ===================================
// The printable thermal receipt, rendered into document.body via a portal so it
// sits outside the app layout for printing. Extracted VERBATIM from Sales.jsx
// (R5 decomposition, step 1) — purely presentational, owns no state, changes no
// money math. Every figure is passed in already-computed from the POS counter.
//
// Header lines (logo / name / address / contact / GSTIN) honour the owner's
// drag-to-reorder + per-line alignment saved at settings.print.header_layout,
// applied identically to the Settings live preview.
import { createPortal } from 'react-dom'
import { getTodayDateStr, numberToWords } from '../../utils/format'
import { lineTotal, gstSlabBreakdown } from '../../utils/invoiceMath'
import { getHeaderLayout } from '../../utils/printLayout'

export default function ThermalReceipt({
  settings,
  profile,
  activeTab,
  form,
  customers,
  user,
  isIntrastate,
  subtotal,
  billDiscountAmt,
  cgstAmt,
  sgstAmt,
  igstAmt,
  cashDiscountAmt,
  roundOff,
  grandTotal,
  payable,
  changeToReturn,
  colFooter,
}) {
  if (!activeTab) return null

  const renderReceiptHeaderLine = (key, align) => {
    const p = settings?.print || {}
    const textAlign = align || 'center'
    switch (key) {
      case 'logo':
        if (!p.print_logo || !profile?.logo) return null
        return <div key="logo" style={{ textAlign, marginBottom: 2 }}><img src={profile.logo} alt="logo" style={{ maxHeight: 26, maxWidth: 96, objectFit: 'contain' }} /></div>
      case 'company_name':
        if (p.print_company_name === false) return null
        return <h3 key="company_name" style={{ textAlign }}>{(profile?.business_name || 'BIZASSIST POS').toUpperCase()}</h3>
      case 'company_address':
        if (p.print_company_address === false || !profile?.address) return null
        return <p key="company_address" style={{ textAlign }}>{profile.address}</p>
      case 'company_contact': {
        const showPhone = p.print_company_phone !== false && profile?.phone
        const showEmail = p.print_company_email !== false && profile?.email
        if (!showPhone && !showEmail) return null
        return <p key="company_contact" style={{ textAlign }}>{showPhone ? `Phone: ${profile.phone}` : ''}{showPhone && showEmail ? '  ·  ' : ''}{showEmail ? `Email: ${profile.email}` : ''}</p>
      }
      case 'gstin':
        if (p.print_gstin === false || !profile?.gstin) return null
        return <p key="gstin" style={{ textAlign }}>GSTIN: {profile.gstin}</p>
      default:
        return null
    }
  }

  return createPortal(
    <div
      id="thermal-receipt"
      className={`size-${settings?.print?.thermal_page_size || '3inch'} text-size-${settings?.print?.text_size || 'medium'} theme-${settings?.print?.thermal_theme || 'theme_standard'}`}
    >
      <div className="receipt-header">
        {getHeaderLayout(settings?.print).map(line => renderReceiptHeaderLine(line.key, line.align))}
        <div className="dashed" />
      </div>

      <div className="receipt-info" style={{ marginBottom: '6px', display: 'flex', flexDirection: 'column', gap: '1px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span><b>Bill No:</b> {activeTab.name}</span>
          <span><b>Counter:</b> {settings?.print?.counter_id || 'POS'}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span><b>Date:</b> {getTodayDateStr()}</span>
          <span><b>Time:</b> {new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}</span>
        </div>
        {(() => {
          const c = customers.find(x => String(x.id) === String(form.customer_id))
          if (c && c.name !== 'Cash Sale') {
            return (
              <div>
                <b>Customer:</b> {c.name}{c.phone ? ` (${c.phone})` : ''}
              </div>
            )
          }
          return <div><b>Cashier:</b> {user?.username || 'POS'}</div>
        })()}
        <div className="dashed" style={{ marginTop: '4px' }} />
      </div>

      <table className="receipt-table">
        <thead>
          {settings?.print?.thermal_theme === 'theme_compact' ? (
            <tr>
              <th colSpan={settings?.print?.print_item_hsn ? 3 : 2}>Description</th>
              <th className="text-right">Amt</th>
            </tr>
          ) : (
            <tr>
              {settings?.print?.print_item_sno !== false && <th style={{ width: '25px' }}>#</th>}
              <th>Item</th>
              {settings?.print?.print_item_hsn && <th>HSN</th>}
              <th className="text-right">MRP</th>
              <th className="text-right">Rate</th>
              <th className="text-right">Qty</th>
              {settings?.print?.print_item_tax !== false && <th className="text-right">GST</th>}
              <th className="text-right">Amt</th>
            </tr>
          )}
        </thead>
        <tbody>
          {form.items.map((it, idx) => {
            const cgstRate = parseFloat(it.cgst_rate) || 0
            const sgstRate = parseFloat(it.sgst_rate) || 0
            const igstRate = it.igst_rate ? parseFloat(it.igst_rate) : (cgstRate + sgstRate)
            const totalRate = isIntrastate ? (cgstRate + sgstRate) : igstRate
            const lineUnitPrice = parseFloat(it.price) || 0

            if (settings?.print?.thermal_theme === 'theme_compact') {
              return (
                <tr key={idx} style={{ borderBottom: '1px dotted #ccc' }}>
                  <td colSpan={settings?.print?.print_item_hsn ? 2 : 1}>
                    <div style={{ fontWeight: 'bold', fontSize: '10px' }}>{it.product}</div>
                    <div style={{ fontSize: '9px', color: '#555' }}>
                      {it.qty} {it.unit || 'Nos'} · MRP ₹{lineUnitPrice.toFixed(2)} → ₹{((parseFloat(it.qty) || 1) ? lineTotal(it) / (parseFloat(it.qty) || 1) : lineUnitPrice).toFixed(2)}
                      {settings?.print?.print_item_hsn && it.hsn_sac && ` (HSN: ${it.hsn_sac})`}
                      {settings?.print?.print_item_tax !== false && totalRate > 0 && ` (Tax: ${totalRate}%)`}
                    </div>
                  </td>
                  <td className="text-right" style={{ verticalAlign: 'bottom', fontSize: '10px' }}>
                    ₹{lineTotal(it).toFixed(2)}
                  </td>
                </tr>
              )
            } else {
              const qn = parseFloat(it.qty) || 1
              const rate = qn ? lineTotal(it) / qn : lineUnitPrice   // chosen selling price per unit
              return (
                <tr key={idx}>
                  {settings?.print?.print_item_sno !== false && <td>{idx + 1}</td>}
                  <td>{it.product}</td>
                  {settings?.print?.print_item_hsn && <td>{it.hsn_sac || '—'}</td>}
                  <td className="text-right">₹{lineUnitPrice.toFixed(2)}</td>
                  <td className="text-right">₹{rate.toFixed(2)}</td>
                  <td className="text-right">{it.qty}</td>
                  {settings?.print?.print_item_tax !== false && <td className="text-right">{totalRate}%</td>}
                  <td className="text-right">₹{lineTotal(it).toFixed(2)}</td>
                </tr>
              )
            }
          })}
        </tbody>
      </table>

      <div className="dashed" />

      <div className="receipt-totals">
        <div className="receipt-row">
          <span>Subtotal:</span>
          <span>₹{subtotal.toFixed(2)}</span>
        </div>
        {billDiscountAmt > 0 && (
          <div className="receipt-row">
            <span>Discount:</span>
            <span>− ₹{billDiscountAmt.toFixed(2)}</span>
          </div>
        )}
        {settings?.print?.print_tax_breakdown !== false && (
          <>
            {cgstAmt > 0 && (
              <div className="receipt-row">
                <span>CGST:</span>
                <span>₹{cgstAmt.toFixed(2)}</span>
              </div>
            )}
            {sgstAmt > 0 && (
              <div className="receipt-row">
                <span>SGST:</span>
                <span>₹{sgstAmt.toFixed(2)}</span>
              </div>
            )}
            {igstAmt > 0 && (
              <div className="receipt-row">
                <span>IGST:</span>
                <span>₹{igstAmt.toFixed(2)}</span>
              </div>
            )}
          </>
        )}
        {(cashDiscountAmt > 0 || Math.abs(roundOff || 0) >= 0.005) ? (
          <>
            <div className="receipt-row">
              <span>Total:</span>
              <span>₹{grandTotal.toFixed(2)}</span>
            </div>
            {cashDiscountAmt > 0 && (
              <div className="receipt-row">
                <span>(−) Cash Discount:</span>
                <span>₹{cashDiscountAmt.toFixed(2)}</span>
              </div>
            )}
            {Math.abs(roundOff || 0) >= 0.005 && (
              <div className="receipt-row">
                <span>Round Off:</span>
                <span>{(roundOff || 0) > 0 ? '+' : '−'} ₹{Math.abs(roundOff || 0).toFixed(2)}</span>
              </div>
            )}
            <div className="receipt-row grand-total">
              <span>PAYABLE:</span>
              <span>₹{payable.toFixed(2)}</span>
            </div>
          </>
        ) : (
          <div className="receipt-row grand-total">
            <span>GRAND TOTAL:</span>
            <span>₹{grandTotal.toFixed(2)}</span>
          </div>
        )}
        {settings?.print?.print_amount_in_words && (
          <div className="receipt-row" style={{ fontSize: '9px', fontStyle: 'italic', textTransform: 'capitalize', marginTop: '2px' }}>
            <span>In Words: {numberToWords(payable)}</span>
          </div>
        )}
        <div className="receipt-row" style={{ marginTop: 4 }}>
          <span>Payment Mode:</span>
          <span>{form.payment_mode ? form.payment_mode.toUpperCase() : 'CASH'}</span>
        </div>
        <div className="receipt-row">
          <span>Amount Received:</span>
          <span>₹{parseFloat(form.amount_received || 0).toFixed(2)}</span>
        </div>
        {changeToReturn > 0 && (
          <div className="receipt-row">
            <span>Change Return:</span>
            <span>₹{changeToReturn.toFixed(2)}</span>
          </div>
        )}
        <div className="receipt-row" style={{ marginTop: 4 }}>
          <span>Qty: {colFooter.qty}</span>
          <span>Items: {form.items.length}</span>
        </div>
        {(colFooter.discount + billDiscountAmt + cashDiscountAmt) > 0.005 && (
          <div className="receipt-row" style={{ fontWeight: 700 }}>
            <span>You have Saved:</span>
            <span>₹{(colFooter.discount + billDiscountAmt + cashDiscountAmt).toFixed(2)}</span>
          </div>
        )}
      </div>

      {/* Per-slab GST tax table (Tax% · Taxable · CGST/SGST), like the kirana receipt */}
      {settings?.print?.print_tax_breakdown !== false && form.items.length > 0 && (() => {
        const slabs = gstSlabBreakdown(form.items, { isIntrastate })
        if (!slabs.length) return null
        return (
          <>
            <div className="dashed" />
            <table className="receipt-table" style={{ fontSize: '9px' }}>
              <thead>
                <tr>
                  <th>Tax%</th>
                  <th className="text-right">Taxable</th>
                  {isIntrastate
                    ? (<><th className="text-right">CGST</th><th className="text-right">SGST</th></>)
                    : (<th className="text-right">IGST</th>)}
                </tr>
              </thead>
              <tbody>
                {slabs.map((s, i) => (
                  <tr key={i}>
                    <td>{s.rate}%</td>
                    <td className="text-right">₹{s.taxable.toFixed(2)}</td>
                    {isIntrastate
                      ? (<><td className="text-right">₹{s.cgst.toFixed(2)}</td><td className="text-right">₹{s.sgst.toFixed(2)}</td></>)
                      : (<td className="text-right">₹{s.igst.toFixed(2)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )
      })()}

      {(settings?.print?.fssai_no || settings?.print?.prices_incl_gst) && (
        <div style={{ fontSize: '9px', textAlign: 'center', marginTop: 4 }}>
          {settings?.print?.prices_incl_gst && <div>E. &amp; O.E. · Prices Incl. GST</div>}
          {settings?.print?.fssai_no && <div>FSSAI: {settings.print.fssai_no}</div>}
        </div>
      )}

      {form.notes && (
        <>
          <div className="dashed" />
          <div className="receipt-notes">
            <p><strong>Notes:</strong> {form.notes}</p>
          </div>
        </>
      )}

      {settings?.print?.print_terms_conditions && settings?.print?.terms_conditions_text && (
        <>
          <div className="dashed" />
          <div className="receipt-terms" style={{ fontSize: '9px', textAlign: 'center' }}>
            <p><strong>Terms & Conditions:</strong></p>
            <p style={{ whiteSpace: 'pre-wrap' }}>{settings.print.terms_conditions_text}</p>
          </div>
        </>
      )}

      {/* Signature lines */}
      {(settings?.print?.customer_signature || settings?.print?.print_signature) && (
        <div style={{ marginTop: '24px', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', fontSize: '9px' }}>
          {settings?.print?.customer_signature ? (
            <div style={{ borderTop: '1px dashed #64748b', width: '110px', textAlign: 'center', paddingTop: '2px' }}>
              {settings.print.customer_signature_label || 'Customer Signature'}
            </div>
          ) : <div />}
          
          {settings?.print?.print_signature ? (
            <div style={{ borderTop: '1px dashed #64748b', width: '110px', textAlign: 'center', paddingTop: '2px' }}>
              {settings.print.signature_label || 'Authorised Signatory'}
            </div>
          ) : <div />}
        </div>
      )}

      {/* Computer generated note — always shown */}
      <div style={{ textAlign: 'center', fontSize: '9px', color: '#94a3b8', marginTop: '10px', paddingTop: '4px', borderTop: '1px dotted #e2e8f0' }}>
        Computer generated invoice. No signature required.
      </div>

      {settings?.print?.print_invoice_qr && (
        <div style={{ textAlign: 'center', marginTop: '12px' }}>
          <div style={{ width: 90, height: 90, border: '1px dashed #ccc', margin: '0 auto', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#999', fontSize: '10px' }}>
            QR Code
          </div>
          <div style={{ fontSize: '9px', color: '#64748b', marginTop: '4px' }}>
            Scan to view invoice online
          </div>
        </div>
      )}

      <div className="dashed" />
      <div className="receipt-footer">
        <p>Thank you for shopping with us!</p>
        <p>Powered by BizAssist</p>
      </div>
    </div>,
    document.body
  )
}
