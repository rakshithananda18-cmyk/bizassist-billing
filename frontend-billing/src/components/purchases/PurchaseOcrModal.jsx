// ============================================================================
// PurchaseOcrModal — extracted verbatim from pages/Purchases.jsx (repo restructure).
// All state and handlers stay with the page and arrive as same-named props,
// so the JSX body is byte-identical to the original.
// ============================================================================
import React from 'react'
import CustomSelect from '../common/CustomSelect'
import { BillsIcon, CheckIcon, ChevronLeftIcon, CloseIcon, DownloadIcon, ImportIcon, InfoIcon, UploadIcon } from '../Icons'

const fmt = (n) =>
  n != null ? `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '—'

export default function PurchaseOcrModal({ setShowModal, step, setStep, dragOver, setDragOver, handleFileDrop, fileRef, file, setFile, extracted, handleHeaderChange, handleItemChange, handleRemoveItem, catalogProducts, uploading, handleUpload, confirming, handleConfirm }) {
  return (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowModal(false)}>
          <div className="modal" style={{ maxWidth: step === 'review' ? '1200px' : '520px', width: '95%' }}>
            <div className="modal-header">
              <span className="modal-title">
                {step === 'upload' ? <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><BillsIcon size={14} /> Upload Bill</span> : '🔍 Review Extracted Data'}
              </span>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowModal(false)} aria-label="Close"><CloseIcon size={16} /></button>
            </div>

            <div className="modal-body">
              {step === 'upload' ? (
                <>
                  {/* Drag-drop zone */}
                  <div
                    onDragOver={e => { e.preventDefault(); setDragOver(true) }}
                    onDragLeave={() => setDragOver(false)}
                    onDrop={handleFileDrop}
                    onClick={() => fileRef.current?.click()}
                    style={{
                      border: `2px dashed ${dragOver ? 'var(--accent)' : 'var(--border)'}`,
                      borderRadius: 'var(--radius-lg)',
                      padding: '40px 24px',
                      textAlign: 'center',
                      cursor: 'pointer',
                      background: dragOver ? 'var(--accent-dim)' : 'var(--bg-3)',
                      transition: 'all 180ms ease',
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      gap: 12,
                    }}
                  >
                    {dragOver ? <DownloadIcon size={32} style={{ color: 'var(--accent)' }} /> : <UploadIcon size={32} style={{ color: 'var(--accent)' }} />}
                    <div>
                      <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>
                        {file ? file.name : 'Drag & drop your bill here'}
                      </div>
                      <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                        {file ? `${(file.size / 1024).toFixed(1)} KB · ${file.type || 'file'}` : 'or click to browse · PDF, PNG, JPG supported'}
                      </div>
                    </div>
                    {file && (
                      <span className="badge badge-success">✓ File selected</span>
                    )}
                  </div>
                  <input
                    ref={fileRef}
                    type="file"
                    accept=".pdf,.png,.jpg,.jpeg"
                    style={{ display: 'none' }}
                    onChange={e => setFile(e.target.files?.[0] || null)}
                  />
                </>
              ) : (
                <>
                  {/* Extracted items review */}
                  <div className="alert alert-info mb-4" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <InfoIcon size={16} style={{ color: 'var(--info)', marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> <span>AI extracted the following details. Correct any fields and verify product mappings before confirming.</span>
                  </div>

                  {/* Header info editing */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16, marginBottom: 20 }}>
                    <div className="form-group">
                      <label className="form-label">Supplier Name</label>
                      <input
                        type="text"
                        className="form-input"
                        value={extracted?.supplier_name || ''}
                        onChange={e => handleHeaderChange('supplier_name', e.target.value)}
                      />
                    </div>
                    <div className="form-group">
                      <label className="form-label">Bill / Invoice Number</label>
                      <input
                        type="text"
                        className="form-input"
                        value={extracted?.invoice_number || ''}
                        onChange={e => handleHeaderChange('invoice_number', e.target.value)}
                      />
                    </div>
                    <div className="form-group">
                      <label className="form-label">Invoice Date</label>
                      <input
                        type="text"
                        className="form-input"
                        value={extracted?.invoice_date || ''}
                        onChange={e => handleHeaderChange('invoice_date', e.target.value)}
                        placeholder="YYYY-MM-DD"
                      />
                    </div>
                  </div>

                  {/* Table of items */}
                  <div style={{ marginBottom: 12 }}>
                    <div className="data-table-wrap" style={{ overflowX: 'auto' }}>
                      <table className="data-table" style={{ minWidth: 1000 }}>
                        <thead>
                          <tr>
                            <th>Extracted Info</th>
                            <th>Catalog Product</th>
                            <th>Product Name</th>
                            <th>Qty</th>
                            <th>Rate</th>
                            <th>Factor</th>
                            <th>P. Unit</th>
                            <th>Batch</th>
                            <th>Expiry</th>
                            <th>Barcode</th>
                            <th style={{ textAlign: 'right' }}>Total</th>
                            <th style={{ width: 36 }}></th>
                          </tr>
                        </thead>
                        <tbody>
                          {extracted?.items?.length ? extracted.items.map((item, index) => {
                            const isMatched = item.is_matched || item.product_id;
                            const confidence = item.confidence_score != null ? Math.round(item.confidence_score * 100) : 0;
                            return (
                              <tr key={index}>
                                <td>
                                  <div style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: '0.82rem', maxWidth: 180, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={item.product_name}>
                                    {item.product_name || '—'}
                                  </div>
                                  <div style={{ marginTop: 2 }}>
                                    {isMatched ? (
                                      <span className="badge badge-success" style={{ fontSize: '0.65rem', padding: '2px 6px' }}>Matched ({confidence}%)</span>
                                    ) : (
                                      <span className="badge badge-warning" style={{ fontSize: '0.65rem', padding: '2px 6px' }}>New Product</span>
                                    )}
                                  </div>
                                </td>
                                <td>
                                  <CustomSelect
                                    className="form-select"
                                    style={{ fontSize: '0.8rem', padding: '5px 8px', width: 150 }}
                                    value={item.product_id || 'new'}
                                    onChange={e => {
                                      const val = e.target.value;
                                      if (val === 'new') {
                                        handleItemChange(index, 'product_id', null);
                                        handleItemChange(index, 'is_matched', false);
                                      } else {
                                        const pid = parseInt(val);
                                        const matchedProd = catalogProducts.find(p => p.id === pid);
                                        handleItemChange(index, 'product_id', pid);
                                        handleItemChange(index, 'is_matched', true);
                                        if (matchedProd) {
                                          handleItemChange(index, 'product_name', matchedProd.name);
                                        }
                                      }
                                    }}
                                  >
                                    <option value="new">+ Create New Product</option>
                                    {catalogProducts.map(p => (
                                      <option key={p.id} value={p.id}>{p.name}</option>
                                    ))}
                                  </CustomSelect>
                                </td>
                                <td>
                                  <input
                                    type="text"
                                    className="form-input"
                                    style={{ fontSize: '0.8rem', padding: '5px 8px', width: 140 }}
                                    value={item.product_name || ''}
                                    onChange={e => handleItemChange(index, 'product_name', e.target.value)}
                                  />
                                </td>
                                <td>
                                  <input
                                    type="number"
                                    className="form-input"
                                    style={{ fontSize: '0.8rem', padding: '5px 8px', width: 65 }}
                                    value={item.quantity ?? 0}
                                    onChange={e => handleItemChange(index, 'quantity', parseFloat(e.target.value) || 0)}
                                  />
                                </td>
                                <td>
                                  <input
                                    type="number"
                                    className="form-input"
                                    style={{ fontSize: '0.8rem', padding: '5px 8px', width: 85 }}
                                    value={item.unit_price ?? 0}
                                    onChange={e => handleItemChange(index, 'unit_price', parseFloat(e.target.value) || 0)}
                                  />
                                </td>
                                <td>
                                  <input
                                    type="number"
                                    className="form-input"
                                    style={{ fontSize: '0.8rem', padding: '5px 8px', width: 60 }}
                                    value={item.conversion_factor ?? 1.0}
                                    onChange={e => handleItemChange(index, 'conversion_factor', parseFloat(e.target.value) || 1.0)}
                                  />
                                </td>
                                <td>
                                  <input
                                    type="text"
                                    className="form-input"
                                    style={{ fontSize: '0.8rem', padding: '5px 8px', width: 75 }}
                                    value={item.purchase_unit || ''}
                                    onChange={e => handleItemChange(index, 'purchase_unit', e.target.value)}
                                    placeholder="Box"
                                  />
                                </td>
                                <td>
                                  <input
                                    type="text"
                                    className="form-input"
                                    style={{ fontSize: '0.8rem', padding: '5px 8px', width: 85 }}
                                    value={item.batch || ''}
                                    onChange={e => handleItemChange(index, 'batch', e.target.value)}
                                    placeholder="Batch"
                                  />
                                </td>
                                <td>
                                  <input
                                    type="text"
                                    className="form-input"
                                    style={{ fontSize: '0.8rem', padding: '5px 8px', width: 90 }}
                                    value={item.expiry || ''}
                                    onChange={e => handleItemChange(index, 'expiry', e.target.value)}
                                    placeholder="Expiry"
                                  />
                                </td>
                                <td>
                                  <input
                                    type="text"
                                    className="form-input"
                                    style={{ fontSize: '0.8rem', padding: '5px 8px', width: 105 }}
                                    value={item.barcode || ''}
                                    onChange={e => handleItemChange(index, 'barcode', e.target.value)}
                                    placeholder="Barcode"
                                  />
                                </td>
                                <td style={{ fontWeight: 600, color: 'var(--text-primary)', textAlign: 'right', fontSize: '0.82rem' }}>
                                  {fmt(item.line_total)}
                                </td>
                                <td style={{ textAlign: 'center' }}>
                                  <button
                                    type="button"
                                    className="btn btn-ghost btn-icon"
                                    title="Remove this line — it will NOT be added"
                                    onClick={() => handleRemoveItem(index)}
                                    style={{ color: 'var(--danger, #ef4444)', padding: 4, fontSize: 16, lineHeight: 1 }}
                                  >
                                    ×
                                  </button>
                                </td>
                              </tr>
                            );
                          }) : (
                            <tr><td colSpan={12} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>No items extracted</td></tr>
                          )}
                        </tbody>
                      </table>
                    </div>

                    {/* Summary statistics */}
                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 24, marginTop: 16, fontSize: '0.85rem', fontWeight: 600 }}>
                      <div>Subtotal: <span style={{ color: 'var(--text-secondary)' }}>{fmt(extracted?.subtotal)}</span></div>
                      <div>Total Tax: <span style={{ color: 'var(--text-secondary)' }}>{fmt((extracted?.cgst_total || 0) + (extracted?.sgst_total || 0) + (extracted?.igst_total || 0))}</span></div>
                      <div>Grand Total: <span style={{ color: 'var(--success)', fontSize: '1.0rem', fontWeight: 700 }}>{fmt(extracted?.total_amount)}</span></div>
                    </div>
                  </div>
                </>
              )}
            </div>

            <div className="modal-footer">
              {step === 'upload' ? (
                <>
                  <button className="btn btn-secondary" onClick={() => setShowModal(false)}>Cancel</button>
                  <button
                    className="btn btn-primary"
                    disabled={!file || uploading}
                    onClick={handleUpload}
                  >
                    {uploading
                      ? <><span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /> Extracting…</>
                      : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><ImportIcon size={14} /> Upload & Extract</span>}
                  </button>
                </>
              ) : (
                <>
                  <button className="btn btn-secondary" onClick={() => setStep('upload')}><ChevronLeftIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Back</button>
                  <button className="btn btn-primary" disabled={confirming} onClick={handleConfirm}>
                    {confirming
                      ? <><span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /> Confirming…</>
                      : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><CheckIcon size={14} /> Confirm Bill</span>}
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
  )
}
