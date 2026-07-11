// components/stock/ProductFormModal.jsx — the complete product form.
// ===================================================================
// Inventory revamp (owner req 2026-07): the old inline modal exposed a
// handful of fields and had NO edit at all — the backend accepts everything
// (PATCH /products/{id} + CreateProduct). This one form does both modes with
// every field the counter and invoices use, organised in sections:
//   Basics · Pricing (all 4 prices + MRP) · Tax (HSN, CGST/SGST) · Stock ·
//   Codes (SKU + barcodes — MULTIPLE barcodes per product in edit mode) — v3.
import React, { useState, useEffect } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { logger } from '../../utils/logger'
import { CloseIcon, InventoryIcon } from '../Icons'

export const EMPTY_PRODUCT = {
  name: '', description: '', brand: '', category: '', unit: 'pcs',
  sku: '', barcode: '', hsn_sac: '',
  selling_price: '', wholesale_price: '', distributor_price: '', cost_price: '', mrp: '',
  cgst_rate: '', sgst_rate: '',
  min_stock: '', opening_stock: '',
}

const num = (v) => (v === '' || v === null || v === undefined ? 0 : parseFloat(v) || 0)
const numOrNull = (v) => (v === '' || v === null || v === undefined ? null : parseFloat(v) || 0)

function Section({ title, children }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{
        fontSize: '0.68rem', fontWeight: 800, textTransform: 'uppercase',
        letterSpacing: '0.07em', color: 'var(--text-muted)', marginBottom: 8,
        borderBottom: '1px solid var(--border)', paddingBottom: 4,
      }}>{title}</div>
      {children}
    </div>
  )
}

function Field({ label, children, flex = 1 }) {
  return (
    <div style={{ flex, minWidth: 110 }}>
      <label style={{ display: 'block', fontSize: '0.72rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: 3 }}>{label}</label>
      {children}
    </div>
  )
}

const inputCls = 'form-input'
const rowStyle = { display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 8 }

export default function ProductFormModal({ open, product, onClose, onSaved, prefillBarcode = '', inline = false, onChange }) {
  const { authFetch } = useAuth()
  const isEdit = !!product?.id
  const [form, setForm] = useState(EMPTY_PRODUCT)
  const [barcodes, setBarcodes] = useState([])      // edit mode: existing barcodes
  const [newBarcode, setNewBarcode] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  const currentRowStyle = {
    display: 'flex',
    gap: inline ? 6 : 10,
    flexWrap: 'wrap',
    marginBottom: 8,
    flexDirection: inline ? 'column' : 'row'
  }

  useEffect(() => {
    if (!open && !inline) return
    setError(null)
    setNewBarcode('')
    if (isEdit) {
      setForm({
        ...EMPTY_PRODUCT,
        ...Object.fromEntries(Object.entries({
          name: product.name, description: product.description, brand: product.brand,
          category: product.category, unit: product.unit || 'pcs',
          sku: product.sku, hsn_sac: product.hsn_sac,
          selling_price: product.selling_price, wholesale_price: product.wholesale_price,
          distributor_price: product.distributor_price, cost_price: product.cost_price,
          mrp: product.mrp, cgst_rate: product.cgst_rate, sgst_rate: product.sgst_rate,
          min_stock: product.min_stock,
        }).map(([k, v]) => [k, v ?? ''])),
      })
      // Load the full record for the barcode list.
      authFetch(`/billing/products/${product.id}`)
        .then(r => (r.ok ? r.json() : null))
        .then(d => { if (d?.barcodes) setBarcodes(d.barcodes) })
        .catch(err => logger.debug('[STOCK] barcode load skipped', err))
    } else {
      // Add mode — an unknown scan from Scan Stock-In prefills its barcode.
      setForm({ ...EMPTY_PRODUCT, barcode: prefillBarcode || '' })
      setBarcodes([])
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, product?.id, prefillBarcode, inline])

  if (!open && !inline) return null
  const setF = (k, v) => {
    setForm(f => ({ ...f, [k]: v }))
    onChange?.(k, v)
  }

  const submit = async (e) => {
    e.preventDefault()
    if (!form.name.trim()) { setError('Product name is required.'); return }
    setSubmitting(true); setError(null)
    try {
      const payload = {
        name: form.name.trim(),
        description: form.description || null,
        brand: form.brand || null,
        category: form.category || null,
        unit: form.unit || 'pcs',
        sku: form.sku || null,
        hsn_sac: form.hsn_sac || null,
        selling_price: num(form.selling_price),
        wholesale_price: num(form.wholesale_price),
        distributor_price: num(form.distributor_price),
        cost_price: num(form.cost_price),
        mrp: numOrNull(form.mrp),
        cgst_rate: num(form.cgst_rate),
        sgst_rate: num(form.sgst_rate),
      }
      let res
      if (isEdit) {
        res = await authFetch(`/billing/products/${product.id}`, {
          method: 'PATCH', body: JSON.stringify(payload),
        })
      } else {
        res = await authFetch('/billing/products', {
          method: 'POST',
          body: JSON.stringify({
            ...payload,
            barcode: form.barcode || null,
            min_stock: num(form.min_stock),
            opening_stock: num(form.opening_stock),
            attributes: {},
          }),
        })
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || 'Save failed.')
      }
      const savedProd = await res.json().catch(() => ({}))
      onSaved?.(isEdit ? 'updated' : 'created', savedProd)
    } catch (err) {
      setError(err.message || 'Network error.')
    } finally {
      setSubmitting(false)
    }
  }

  const addBarcode = async () => {
    const code = newBarcode.trim()
    if (!code || !isEdit) return
    try {
      const res = await authFetch(`/billing/products/${product.id}/barcodes`, {
        method: 'POST', body: JSON.stringify({ barcode: code }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || 'Could not add barcode.')
      setBarcodes(prev => {
        const next = [...prev, data.barcode ? data : { barcode: code }]
        onChange?.('barcodes', next)
        return next
      })
      setNewBarcode('')
    } catch (err) {
      setError(err.message)
    }
  }

  const formJSX = (
    <form onSubmit={submit} style={{ padding: inline ? '12px 14px 16px' : '14px 20px 18px', flex: inline ? 1 : undefined, overflowY: inline ? 'auto' : undefined, display: inline ? 'flex' : 'block', flexDirection: inline ? 'column' : undefined, gap: inline ? 12 : undefined }}>
      <Section title="Basics">
        <div style={currentRowStyle}>
          <Field label="Product name *" flex={2}>
            <input className={inputCls} required value={form.name} onChange={e => setF('name', e.target.value)} placeholder="e.g. Sunflower Oil 15L" />
          </Field>
          <Field label="Brand">
            <input className={inputCls} value={form.brand} onChange={e => setF('brand', e.target.value)} />
          </Field>
        </div>
        <div style={currentRowStyle}>
          <Field label="Category">
            <input className={inputCls} value={form.category} onChange={e => setF('category', e.target.value)} placeholder="e.g. Oils" />
          </Field>
          <Field label="Unit">
            <input className={inputCls} value={form.unit} onChange={e => setF('unit', e.target.value)} placeholder="pcs / kg / L / box" />
          </Field>
          <Field label="Description" flex={2}>
            <input className={inputCls} value={form.description} onChange={e => setF('description', e.target.value)} />
          </Field>
        </div>
      </Section>

      <Section title="Pricing — one stock, many selling points">
        <div style={currentRowStyle}>
          <Field label="Retail price (₹) *">
            <input className={inputCls} type="number" min="0" step="any" value={form.selling_price} onChange={e => setF('selling_price', e.target.value)} />
          </Field>
          <Field label="Wholesale price (₹)">
            <input className={inputCls} type="number" min="0" step="any" value={form.wholesale_price} onChange={e => setF('wholesale_price', e.target.value)} />
          </Field>
          <Field label="Distributor price (₹)">
            <input className={inputCls} type="number" min="0" step="any" value={form.distributor_price} onChange={e => setF('distributor_price', e.target.value)} />
          </Field>
        </div>
        <div style={currentRowStyle}>
          <Field label="Cost price (₹)">
            <input className={inputCls} type="number" min="0" step="any" value={form.cost_price} onChange={e => setF('cost_price', e.target.value)} />
          </Field>
          <Field label="MRP (₹)">
            <input className={inputCls} type="number" min="0" step="any" value={form.mrp} onChange={e => setF('mrp', e.target.value)} placeholder="printed MRP" />
          </Field>
          {!inline && (
            <Field label=" ">
              <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', paddingTop: 6 }}>
                The counter picks retail/wholesale per line; B2B customers get their tier automatically.
              </div>
            </Field>
          )}
        </div>
        {inline && (
          <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: -2, marginBottom: 4 }}>
            The counter picks retail/wholesale per line; B2B customers get their tier automatically.
          </div>
        )}
      </Section>

      <Section title="Tax (GST)">
        <div style={currentRowStyle}>
          <Field label="HSN / SAC">
            <input className={inputCls} value={form.hsn_sac} onChange={e => setF('hsn_sac', e.target.value)} placeholder="e.g. 1512" />
          </Field>
          <Field label="CGST %">
            <input className={inputCls} type="number" min="0" step="any" value={form.cgst_rate} onChange={e => setF('cgst_rate', e.target.value)} />
          </Field>
          <Field label="SGST %">
            <input className={inputCls} type="number" min="0" step="any" value={form.sgst_rate} onChange={e => setF('sgst_rate', e.target.value)} />
          </Field>
        </div>
      </Section>

      {!isEdit && (
        <Section title="Stock">
          <div style={currentRowStyle}>
            <Field label="Opening stock">
              <input className={inputCls} type="number" min="0" step="any" value={form.opening_stock} onChange={e => setF('opening_stock', e.target.value)} />
            </Field>
            <Field label="Minimum stock (low-stock alert)">
              <input className={inputCls} type="number" min="0" step="any" value={form.min_stock} onChange={e => setF('min_stock', e.target.value)} />
            </Field>
          </div>
        </Section>
      )}

      <Section title="Codes">
        <div style={currentRowStyle}>
          <Field label="SKU / Item code">
            <input className={inputCls} value={form.sku} onChange={e => setF('sku', e.target.value)} placeholder="internal code" />
          </Field>
          {!isEdit && (
            <Field label="Barcode (scan or type)">
              <input className={inputCls} value={form.barcode} onChange={e => setF('barcode', e.target.value)} placeholder="e.g. 8901234567890" />
            </Field>
          )}
        </div>
        {isEdit && (
          <div>
            <div style={{ fontSize: '0.72rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: 4 }}>
              Barcodes on this product — a product can carry several (old pack, new pack, carton code)
            </div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
              {barcodes.length === 0
                ? <span style={{ fontSize: '0.76rem', color: 'var(--text-muted)' }}>No barcodes yet.</span>
                : barcodes.map((b, i) => (
                  <span key={i} className="badge badge-muted" style={{ fontFamily: "'Geist Mono',monospace", fontSize: '0.7rem' }}>
                    {b.barcode}{b.is_primary ? ' ★' : ''}
                  </span>
                ))}
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <input className={inputCls} style={{ flex: 1 }} value={newBarcode}
                onChange={e => setNewBarcode(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addBarcode() } }}
                placeholder="Scan or type another barcode…" />
              <button type="button" className="btn btn-secondary" onClick={addBarcode} disabled={!newBarcode.trim()}>
                Add barcode
              </button>
            </div>
          </div>
        )}
      </Section>

      {error && <div className="alert alert-danger" style={{ marginBottom: 10 }}>{error}</div>}
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 14 }}>
        <button type="button" className="btn btn-secondary" disabled={submitting} onClick={onClose}>
          {inline ? 'Close' : 'Cancel'}
        </button>
        <button type="submit" className="btn btn-primary" style={{ fontWeight: 700 }} disabled={submitting}>
          {submitting ? 'Saving…' : isEdit ? 'Save changes' : 'Add product'}
        </button>
      </div>
    </form>
  )

  if (inline) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10, padding: '12px 14px',
          borderBottom: '1px solid var(--border)', background: 'var(--bg-2)', flexShrink: 0
        }}>
          <span style={{ fontWeight: 700, fontSize: '0.85rem', flex: 1, textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>
            {isEdit ? `Edit Product — ${product.name}` : 'Add Product'}
          </span>
          <button className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close" style={{ width: 24, height: 24 }}><CloseIcon size={14} /></button>
        </div>
        {formJSX}
      </div>
    )
  }

  return (
    <div className="modal-overlay" style={{ zIndex: 3000 }} onClick={e => e.target === e.currentTarget && !submitting && onClose()}>
      <div className="modal modal-lg" style={{ maxWidth: 720, width: '95%', maxHeight: '90vh', overflowY: 'auto' }}>
        <div className="modal-header">
          <span className="modal-title" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <InventoryIcon size={16} />
            <span>{isEdit ? `Edit Product — ${product.name}` : 'Add Product'}</span>
          </span>
          <button className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close"><CloseIcon size={16} /></button>
        </div>
        {formJSX}
      </div>
    </div>
  )
}
