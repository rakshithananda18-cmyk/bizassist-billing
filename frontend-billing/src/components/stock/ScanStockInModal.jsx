// components/stock/ScanStockInModal.jsx — barcode-scan direct stock-in.
// =====================================================================
// The stock team's fastest path (owner req 2026-07): scan a barcode →
// the product appears → type quantity → Enter → stock recorded. No product
// duplication: an existing barcode ALWAYS updates the existing product's
// stock (via the append-only adjustment ledger). An unknown barcode offers
// "add as new product" with the code prefilled — nothing is created silently.
// A reason note is required — every movement is attributed and auditable.
import React, { useState, useRef, useEffect } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { logger } from '../../utils/logger'
import { CloseIcon, ZapIcon } from '../Icons'

export default function ScanStockInModal({ open, onClose, onStocked, onAddNew, initialCode = '' }) {
  const { authFetch } = useAuth()
  const [code, setCode] = useState('')
  const [product, setProduct] = useState(null)     // resolved product
  const [notFound, setNotFound] = useState(null)   // code that didn't resolve
  const [qty, setQty] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(null)           // last success message
  const [error, setError] = useState(null)
  const codeRef = useRef(null)
  const qtyRef = useRef(null)
  const lookupRef = useRef(null)   // latest lookup closure, for the auto-run effect

  useEffect(() => {
    if (open) {
      setCode(initialCode || ''); setProduct(null); setNotFound(null); setQty(''); setNote('')
      setDone(null); setError(null)
      setTimeout(() => codeRef.current?.focus(), 50)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialCode])

  // Smart-search handoff: when the table's search box passed a code in,
  // resolve it immediately — one Enter from scan to qty field.
  useEffect(() => {
    if (open && initialCode) {
      const t = setTimeout(() => { lookupRef.current?.() }, 80)
      return () => clearTimeout(t)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialCode])

  if (!open) return null

  const lookup = async () => {
    const c = code.trim()
    if (!c) return
    setBusy(true); setError(null); setNotFound(null); setProduct(null); setDone(null)
    try {
      const res = await authFetch(`/billing/sales/barcode/${encodeURIComponent(c)}`)
      if (res.ok) {
        const data = await res.json()
        const p = data.product || data
        if (p && p.id) {
          setProduct(p)
          setTimeout(() => qtyRef.current?.focus(), 50)
          return
        }
      }
      setNotFound(c)
    } catch (err) {
      logger.warn('[STOCK] barcode lookup failed', err)
      setError('Lookup failed — check the connection and scan again.')
    } finally {
      setBusy(false)
    }
  }
  lookupRef.current = lookup

  const stockIn = async () => {
    const q = parseFloat(qty)
    if (!product || isNaN(q) || q <= 0) { setError('Enter a quantity greater than 0.'); return }
    if (!note.trim()) { setError('A reason/reference is required (e.g. "supplier delivery", bill no.).'); return }
    setBusy(true); setError(null)
    try {
      const res = await authFetch(`/billing/products/${product.id}/stock/adjustment`, {
        method: 'POST',
        body: JSON.stringify({ qty_delta: q, note: `stock-in via barcode: ${note.trim()}` }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || 'Could not record stock-in.')
      }
      setDone(`✓ +${q} ${product.unit || ''} added to "${product.name}"`)
      onStocked?.(product, q)
      // Ready for the next scan immediately — the scanner workflow.
      setCode(''); setProduct(null); setQty(''); setNote('')
      setTimeout(() => codeRef.current?.focus(), 50)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-overlay" style={{ zIndex: 3000 }} onClick={e => e.target === e.currentTarget && !busy && onClose()}>
      <div className="modal" style={{ maxWidth: 480, width: '95%' }}>
        <div className="modal-header">
          <span className="modal-title" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <ZapIcon size={16} /><span>Scan Stock-In</span>
          </span>
          <button className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close"><CloseIcon size={16} /></button>
        </div>
        <div style={{ padding: '14px 20px 18px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)' }}>
            Scan (or type) a barcode / SKU and press Enter. Known products get stock added directly — no duplicates, ever.
          </div>

          {done && <div className="alert alert-success" style={{ marginBottom: 0 }}>{done}</div>}

          <div style={{ display: 'flex', gap: 8 }}>
            <input
              ref={codeRef} className="form-input" style={{ flex: 1, fontFamily: "'Geist Mono',monospace" }}
              placeholder="Scan barcode…" value={code}
              onChange={e => setCode(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); lookup() } }}
            />
            <button className="btn btn-secondary" disabled={busy || !code.trim()} onClick={lookup}>Find</button>
          </div>

          {product && (
            <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: '10px 12px' }}>
              <div style={{ fontWeight: 700 }}>{product.name}</div>
              <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', marginBottom: 8 }}>
                Current stock: <b>{product.stock_qty ?? product.quantity ?? '—'}</b> {product.unit || ''}
                {product.sku ? <> · SKU {product.sku}</> : null}
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <input
                  ref={qtyRef} type="number" min="0" step="any" className="form-input"
                  style={{ width: 110 }} placeholder="Qty"
                  value={qty} onChange={e => setQty(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); stockIn() } }}
                />
                <input
                  className="form-input" style={{ flex: 1, minWidth: 160 }}
                  placeholder="Reason / bill no. (required)"
                  value={note} onChange={e => setNote(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); stockIn() } }}
                />
                <button className="btn btn-primary" style={{ fontWeight: 700 }} disabled={busy} onClick={stockIn}>
                  {busy ? 'Saving…' : 'Add stock'}
                </button>
              </div>
            </div>
          )}

          {notFound && (
            <div style={{ border: '1px dashed var(--border)', borderRadius: 8, padding: '10px 12px', fontSize: '0.8rem' }}>
              No product carries <code style={{ fontFamily: "'Geist Mono',monospace" }}>{notFound}</code>.
              <button
                className="btn btn-secondary btn-sm" style={{ marginLeft: 10 }}
                onClick={() => { onAddNew?.(notFound); onClose?.() }}
              >
                Add as new product
              </button>
            </div>
          )}

          {error && <div className="alert alert-danger" style={{ marginBottom: 0 }}>{error}</div>}
        </div>
      </div>
    </div>
  )
}
