// ============================================================================
// PurchaseReturnModal — extracted verbatim from pages/Purchases.jsx (repo restructure).
// All state and handlers stay with the page and arrive as same-named props,
// so the JSX body is byte-identical to the original.
// ============================================================================
import React from 'react'
import CustomSelect from '../common/CustomSelect'
import { CheckIcon, ChevronLeftIcon, ChevronRightIcon, CloseIcon, SyncIcon } from '../Icons'

const fmt = (n) =>
  n != null ? `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '—'

export default function PurchaseReturnModal({ setShowReturnModal, returnStep, setReturnStep, returnSupplier, setReturnSupplier, returnBillId, setReturnBillId, bills, debitNoteNoInput, setDebitNoteNoInput, returnLines, setReturnLines, returnNote, setReturnNote, handleSelectBillNext, confirming, handleSaveReturn }) {
  return (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowReturnModal(false)}>
          <div className="modal" style={{ maxWidth: returnStep === 'enter_items' ? '850px' : '480px', width: '95%' }}>
            <div className="modal-header">
              <span className="modal-title"><SyncIcon size={16} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Record Purchase Return (Debit Note)</span>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowReturnModal(false)} aria-label="Close"><CloseIcon size={16} /></button>
            </div>

            <div className="modal-body">
              {returnStep === 'select_bill' ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                  <div className="form-group">
                    <label className="form-label" style={{ fontWeight: 600 }}>1. Select Supplier</label>
                    <CustomSelect
                      className="form-input"
                      value={returnSupplier}
                      onChange={e => {
                        setReturnSupplier(e.target.value)
                        setReturnBillId('')
                      }}
                    >
                      <option value="">-- Choose Supplier --</option>
                      {Array.from(new Set(bills.filter(b => b.status === 'confirmed').map(b => b.supplier_name))).map(sup => (
                        <option key={sup} value={sup}>{sup}</option>
                      ))}
                    </CustomSelect>
                  </div>

                  {returnSupplier && (
                    <div className="form-group">
                      <label className="form-label" style={{ fontWeight: 600 }}>2. Select Confirmed Bill</label>
                      <CustomSelect
                        className="form-input"
                        value={returnBillId}
                        onChange={e => setReturnBillId(e.target.value)}
                      >
                        <option value="">-- Choose Purchase Invoice --</option>
                        {bills
                          .filter(b => b.status === 'confirmed' && b.supplier_name === returnSupplier)
                          .map(b => (
                            <option key={b.id} value={b.id}>
                              {b.invoice_number || b.bill_number || `#${b.id}`} ({new Date(b.date || b.invoice_date).toLocaleDateString('en-IN')}) - Total: {fmt(b.total_amount)}
                            </option>
                          ))}
                      </CustomSelect>
                    </div>
                  )}
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', borderBottom: '1px solid var(--border)', paddingBottom: 10 }}>
                    <div><strong>Supplier:</strong> {returnSupplier}</div>
                    <div><strong>Original Bill:</strong> {bills.find(b => String(b.id) === String(returnBillId))?.invoice_number || bills.find(b => String(b.id) === String(returnBillId))?.bill_number || `#${returnBillId}`}</div>
                  </div>

                  <div className="form-group">
                    <label className="form-label" style={{ fontWeight: 600 }}>Debit Note Number (Optional)</label>
                    <input
                      type="text"
                      className="form-input"
                      value={debitNoteNoInput}
                      onChange={e => setDebitNoteNoInput(e.target.value)}
                      placeholder="e.g. DN-0001 (Leave blank to auto-generate)"
                    />
                  </div>

                  <div className="data-table-wrap" style={{ maxHeight: '250px', overflowY: 'auto' }}>
                    <table className="data-table" style={{ fontSize: '0.82rem' }}>
                      <thead>
                        <tr>
                          <th>Item Name</th>
                          <th style={{ width: 80, textAlign: 'center' }}>Original Qty</th>
                          <th style={{ width: 100, textAlign: 'center' }}>Return Qty</th>
                          <th>Return Reason</th>
                          <th style={{ width: 90, textAlign: 'right' }}>Price</th>
                        </tr>
                      </thead>
                      <tbody>
                        {returnLines.map((line, idx) => (
                          <tr key={idx}>
                            <td className="td-primary">{line.product_name}</td>
                            <td style={{ textAlign: 'center' }}>{line.max_quantity}</td>
                            <td style={{ textAlign: 'center' }}>
                              <input
                                type="number"
                                className="form-input"
                                style={{ padding: '4px 6px', fontSize: '0.8rem', width: '80px', textAlign: 'center' }}
                                min="0"
                                max={line.max_quantity}
                                step="any"
                                value={line.quantity || ''}
                                onChange={e => {
                                  const val = parseFloat(e.target.value) || 0
                                  setReturnLines(prev => {
                                    const updated = [...prev]
                                    updated[idx].quantity = val
                                    return updated
                                  })
                                }}
                                placeholder="0"
                              />
                            </td>
                            <td>
                              <CustomSelect
                                className="form-input"
                                style={{ padding: '4px 6px', fontSize: '0.8rem' }}
                                value={line.reason}
                                onChange={e => {
                                  const val = e.target.value
                                  setReturnLines(prev => {
                                    const updated = [...prev]
                                    updated[idx].reason = val
                                    return updated
                                  })
                                }}
                              >
                                <option value="Damaged">Damaged</option>
                                <option value="Defective">Defective</option>
                                <option value="Incorrect Item">Incorrect Item</option>
                                <option value="Shortage">Shortage</option>
                                <option value="Expired">Expired</option>
                              </CustomSelect>
                            </td>
                            <td style={{ textAlign: 'right', fontWeight: 600 }}>{fmt(line.unit_price)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {/* Return Summary */}
                  {(() => {
                    let sub = 0, tax = 0
                    returnLines.forEach(l => {
                      const qty = parseFloat(l.quantity) || 0
                      const p = parseFloat(l.unit_price) || 0
                      const taxable = qty * p
                      sub += taxable
                      tax += taxable * (((parseFloat(l.cgst_rate) || 0) + (parseFloat(l.sgst_rate) || 0) + (parseFloat(l.igst_rate) || 0)) / 100)
                    })
                    const total = sub + tax
                    return (
                      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 20, fontSize: '0.85rem', fontWeight: 600, borderTop: '1px solid var(--border)', paddingTop: 10 }}>
                        <div>Return Subtotal: <span style={{ color: 'var(--text-secondary)' }}>{fmt(sub)}</span></div>
                        <div>Return Tax: <span style={{ color: 'var(--text-secondary)' }}>{fmt(tax)}</span></div>
                        <div>Grand Total: <span style={{ color: 'var(--accent)', fontWeight: 700 }}>{fmt(total)}</span></div>
                      </div>
                    )
                  })()}

                  <div className="form-group">
                    <label className="form-label" style={{ fontWeight: 600 }}>Remarks / Reason for Return</label>
                    <textarea
                      className="form-input"
                      rows={2}
                      value={returnNote}
                      onChange={e => setReturnNote(e.target.value)}
                      placeholder="Add any internal remarks here..."
                    />
                  </div>
                </div>
              )}
            </div>

            <div className="modal-footer">
              {returnStep === 'select_bill' ? (
                <>
                  <button className="btn btn-secondary" onClick={() => setShowReturnModal(false)}>Cancel</button>
                  <button
                    className="btn btn-primary"
                    disabled={!returnBillId}
                    onClick={handleSelectBillNext}
                  >
                    Next Step <ChevronRightIcon size={14} style={{ marginLeft: 6, display: 'inline-block', verticalAlign: 'middle' }} />
                  </button>
                </>
              ) : (
                <>
                  <button className="btn btn-secondary" onClick={() => setReturnStep('select_bill')}><ChevronLeftIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Back</button>
                  <button className="btn btn-primary" disabled={confirming} onClick={handleSaveReturn}>
                    {confirming ? 'Recording Return…' : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><CheckIcon size={14} /> Confirm & Save Return</span>}
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
  )
}
