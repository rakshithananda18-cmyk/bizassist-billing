// components/stock/IntakePurchasePanel.jsx
// ============================================================================
// The right-side panel for Stock Intake: collapsible, themed, vertically
// scrollable sections that summarise the current intake like a distributor
// purchase / GRN entry.
//
//   • Distributor  — vendor picker (search existing) + inline "new distributor",
//                    invoice no & date.  (UI + local state; persist later.)
//   • Tax Breakdown— GST slab-wise taxable + tax, computed from the rows.
//   • Purchase Summary (large) — Gross, Item Disc, Taxable, Tax, Cess, Freight,
//                    Cash Disc → Payable.  Item Disc / Cess / Freight / Cash
//                    Disc are editable so Payable is meaningful.
//   • Payment      — mode + due date.
//   • Print        — opens a clean Purchase / GRN summary sheet to print.
//
// Everything is computed live from the intake rows passed in; nothing here is
// persisted yet (distributor + payment are a later backend pass).
import React, { useState, useEffect } from 'react'

const money = (n) =>
  `₹${(Number(n) || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const gstOf = (r) =>
  (parseFloat(r.cgst_rate) || 0) + (parseFloat(r.sgst_rate) || 0) || (parseFloat(r.igst_rate) || 0)
const todayISO = () => new Date().toISOString().slice(0, 10)

// ── little themed primitives ────────────────────────────────────────────────

function Section({ title, open, onToggle, children, accent }) {
  return (
    <div style={{ borderBottom: '1px solid var(--border)' }}>
      <button
        type="button"
        onClick={onToggle}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          background: 'transparent', border: 'none', cursor: 'pointer',
          padding: '9px 12px', color: accent ? 'var(--accent)' : 'var(--text-secondary)',
        }}
      >
        <span style={{ fontSize: '0.62rem', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.07em' }}>
          {title}
        </span>
        <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', transform: open ? 'rotate(90deg)' : 'none', transition: 'transform .15s' }}>▶</span>
      </button>
      {open && <div style={{ padding: '0 12px 12px' }}>{children}</div>}
    </div>
  )
}

const field = {
  width: '100%', height: 30, padding: '4px 8px', fontSize: '0.78rem',
  border: '1px solid var(--border)', borderRadius: 5,
  background: 'var(--bg-2)', color: 'var(--text-primary)',
}
const label = { fontSize: '0.6rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', marginBottom: 3, display: 'block' }

function Row({ l, v, muted, strong, big }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
      padding: strong ? '8px 0 0' : '3px 0',
      borderTop: strong ? '1px solid var(--border)' : 'none', marginTop: strong ? 4 : 0,
      fontSize: big ? '1.05rem' : strong ? '0.92rem' : '0.78rem',
      fontWeight: strong ? 800 : 500,
      color: strong ? 'var(--text-primary)' : muted ? 'var(--text-muted)' : 'var(--text-secondary)',
    }}>
      <span>{l}</span>
      <span style={{ fontVariantNumeric: 'tabular-nums', color: strong ? 'var(--accent)' : 'inherit' }}>{v}</span>
    </div>
  )
}

// ── main panel ───────────────────────────────────────────────────────────────

export default function IntakePurchasePanel({ rows = [], authFetch, distributor: propDistributor, setDistributor: propSetDistributor }) {
  const [open, setOpen] = useState({ distributor: true, tax: false, summary: true, payment: false })
  const toggle = (k) => setOpen((o) => ({ ...o, [k]: !o[k] }))

  const [vendors, setVendors] = useState([])
  const [vendorQuery, setVendorQuery] = useState('')

  const [localDist, setLocalDist] = useState({ vendor_id: null, name: '', gstin: '', pan: '', fssai: '', phone: '', address: '', invoice_no: '', invoice_date: todayISO() })
  const dist = propDistributor || localDist
  const setDist = (val) => {
    const setter = propSetDistributor || setLocalDist
    if (typeof val === 'function') {
      setter(prev => val(prev))
    } else {
      setter(val)
    }
  }
  const [pay, setPay] = useState({ mode: 'Credit', due_date: '' })
  const [adj, setAdj] = useState({ item_disc: '', cess: '', cash_disc: '' })

  useEffect(() => {
    if (!authFetch) return
    authFetch('/billing/vendors')
      .then((r) => (r.ok ? r.json() : { items: [] }))
      .then((d) => setVendors(d.items || []))
      .catch(() => {})
  }, [authFetch])

  // ── live computation from the intake rows ──
  let gross = 0
  const slabs = {}
  let totalQty = 0
  rows.forEach((r) => {
    const q = parseFloat(r.qty) || 0
    const f = parseFloat(r.free) || 0
    const c = parseFloat(r.cost_price) || 0
    const g = gstOf(r)
    const base = q * c
    gross += base
    totalQty += q + f
    const k = g.toFixed(0)
    slabs[k] = slabs[k] || { rate: g, taxable: 0, tax: 0 }
    slabs[k].taxable += base
    slabs[k].tax += (base * g) / 100
  })
  const slabList = Object.values(slabs).filter((s) => s.taxable > 0).sort((a, b) => a.rate - b.rate)
  const taxTotal = slabList.reduce((s, x) => s + x.tax, 0)
  const itemDisc = parseFloat(adj.item_disc) || 0
  const cess = parseFloat(adj.cess) || 0
  const cashDisc = parseFloat(adj.cash_disc) || 0
  const taxable = gross - itemDisc
  const payable = taxable + taxTotal + cess - cashDisc

  const vfiltered = vendorQuery.trim()
    ? vendors.filter((v) => (v.name || '').toLowerCase().includes(vendorQuery.trim().toLowerCase()))
    : vendors.slice(0, 8)
  const exactMatch = vendors.some((v) => (v.name || '').toLowerCase() === vendorQuery.trim().toLowerCase())

  const pickVendor = (v) => {
    setDist((d) => ({
      ...d,
      vendor_id: v.id,
      name: v.name || '',
      gstin: v.gstin || '',
      pan: v.pan || '',
      fssai: v.fssai || '',
      phone: v.phone || '',
      address: v.address || '',
    }))
    setVendorQuery('')
  }
  const useAsNew = () => {
    setDist((d) => ({
      ...d,
      vendor_id: null,
      name: vendorQuery.trim(),
      gstin: '',
      pan: '',
      fssai: '',
      phone: '',
      address: '',
    }))
    setVendorQuery('')
  }

  const printGRN = () => {
    const w = window.open('', '_blank', 'width=800,height=900')
    if (!w) return
    const rowsHtml = rows.map((r, i) => {
      const q = parseFloat(r.qty) || 0, f = parseFloat(r.free) || 0
      const c = parseFloat(r.cost_price) || 0, g = gstOf(r)
      const amt = q * c, taxAmt = amt * g / 100
      return `<tr>
        <td>${i + 1}</td><td>${r.name || ''}</td><td style="text-align:right">${q}</td>
        <td style="text-align:right">${f}</td><td style="text-align:right">${c.toFixed(2)}</td>
        <td style="text-align:right">${g}%</td><td style="text-align:right">${taxAmt.toFixed(2)}</td>
        <td style="text-align:right">${(amt + taxAmt).toFixed(2)}</td></tr>`
    }).join('')
    const slabHtml = slabList.map((s) =>
      `<tr><td>GST ${s.rate}%</td><td style="text-align:right">${s.taxable.toFixed(2)}</td><td style="text-align:right">${s.tax.toFixed(2)}</td></tr>`).join('')
    w.document.write(`<!doctype html><html><head><title>Purchase / GRN Summary</title>
      <style>
        body{font-family:Arial,sans-serif;color:#111;padding:24px;font-size:12px}
        h1{font-size:18px;margin:0 0 4px} h2{font-size:13px;margin:18px 0 6px;border-bottom:1px solid #999;padding-bottom:3px}
        table{width:100%;border-collapse:collapse;margin-top:6px} th,td{border:1px solid #bbb;padding:5px 7px;font-size:11px}
        th{background:#eee;text-align:left} .tot{display:flex;justify-content:space-between;padding:3px 0}
        .tot.big{font-size:15px;font-weight:800;border-top:2px solid #333;margin-top:6px;padding-top:6px}
        .grid{display:flex;gap:32px} .grid>div{flex:1}
      </style></head><body>
      <h1>Purchase / GRN Summary</h1>
      <div style="color:#555">${new Date().toLocaleString('en-IN')}</div>
      <div class="grid">
        <div><h2>Distributor</h2>
          <div>${dist.name || '—'}</div>
          <div>GSTIN: ${dist.gstin || '—'}</div>
          <div>PAN: ${dist.pan || '—'}</div>
          <div>FSSAI: ${dist.fssai || '—'}</div>
          <div>Phone: ${dist.phone || '—'}</div>
          <div>Address: ${dist.address || '—'}</div>
        </div>
        <div><h2>Invoice / Payment</h2>
          <div>Invoice No: ${dist.invoice_no || '—'}</div><div>Invoice Date: ${dist.invoice_date || '—'}</div>
          <div>Payment: ${pay.mode}${pay.due_date ? ' · due ' + pay.due_date : ''}</div></div>
      </div>
      <h2>Items</h2>
      <table><thead><tr><th>#</th><th>Product</th><th style="text-align:right">Qty</th><th style="text-align:right">Free</th>
        <th style="text-align:right">Cost</th><th style="text-align:right">Tax%</th><th style="text-align:right">Tax</th><th style="text-align:right">Net</th></tr></thead>
        <tbody>${rowsHtml}</tbody></table>
      <h2>Tax Breakdown</h2>
      <table><thead><tr><th>Slab</th><th style="text-align:right">Taxable</th><th style="text-align:right">Tax</th></tr></thead><tbody>${slabHtml || '<tr><td colspan=3>—</td></tr>'}</tbody></table>
      <h2>Summary</h2>
      <div class="tot"><span>Gross Amount</span><span>${money(gross)}</span></div>
      <div class="tot"><span>Item Disc</span><span>${money(itemDisc)}</span></div>
      <div class="tot"><span>Taxable</span><span>${money(taxable)}</span></div>
      <div class="tot"><span>Tax</span><span>${money(taxTotal)}</span></div>
      <div class="tot"><span>Cess</span><span>${money(cess)}</span></div>
      <div class="tot"><span>Cash Disc</span><span>-${money(cashDisc)}</span></div>
      <div class="tot big"><span>Payable Amount</span><span>${money(payable)}</span></div>
      </body></html>`)
    w.document.close()
    w.focus()
    setTimeout(() => { w.print() }, 250)
  }

  const numField = (key, ph) => (
    <input type="number" min="0" step="any" placeholder={ph} value={adj[key]}
      onChange={(e) => setAdj((a) => ({ ...a, [key]: e.target.value }))}
      style={{ ...field, height: 26, width: 96, textAlign: 'right' }} />
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flexShrink: 0, borderTop: '1px solid var(--border)', background: 'var(--bg-2)', maxHeight: '62%', overflowY: 'auto' }}>
      {/* Distributor */}
      <Section title="Distributor" open={open.distributor} onToggle={() => toggle('distributor')}>
        <div style={{ position: 'relative', marginBottom: 8 }}>
          <label style={label}>Supplier</label>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <input
              style={{ ...field, flex: 1 }}
              placeholder="Search vendor or type distributor name…"
              value={dist.name || ''}
              onChange={(e) => {
                const val = e.target.value
                setDist((d) => ({ ...d, name: val, vendor_id: null }))
                setVendorQuery(val)
              }}
            />
            {dist.name && (
              <button
                type="button"
                onClick={() => {
                  setDist({
                    vendor_id: null,
                    name: '',
                    gstin: '',
                    pan: '',
                    fssai: '',
                    phone: '',
                    address: '',
                    invoice_no: dist.invoice_no,
                    invoice_date: dist.invoice_date,
                  })
                  setVendorQuery('')
                }}
                style={{
                  background: 'rgba(239, 68, 68, 0.1)', border: 'none', color: '#ef4444',
                  cursor: 'pointer', fontSize: '0.72rem', fontWeight: 800, height: 26, width: 26,
                  borderRadius: 4, display: 'flex', alignItems: 'center', justifyContent: 'center'
                }}
                title="Clear distributor"
              >
                ✕
              </button>
            )}
          </div>
          {vendorQuery.trim() && (
            <div style={{ position: 'absolute', zIndex: 20, left: 0, right: 0, background: 'var(--bg-3)', border: '1px solid var(--border)', borderRadius: 6, marginTop: 2, maxHeight: 160, overflowY: 'auto', boxShadow: 'var(--shadow-md)' }}>
              {vfiltered.map((v) => (
                <div key={v.id} onClick={() => pickVendor(v)}
                  style={{ padding: '6px 9px', cursor: 'pointer', fontSize: '0.78rem', borderBottom: '1px solid var(--border)' }}>
                  {v.name}{v.gstin ? <span style={{ color: 'var(--text-muted)', fontSize: '0.66rem' }}> · {v.gstin}</span> : ''}
                </div>
              ))}
            </div>
          )}
        </div>
        {dist.name && (
          <div style={{ display: 'flex', gap: 6, marginBottom: 8, alignItems: 'center' }}>
            <span style={{
              fontSize: '0.58rem', fontWeight: 800, padding: '2px 6px', borderRadius: 4,
              background: dist.vendor_id ? 'rgba(20,184,166,.15)' : 'rgba(249,115,22,.15)',
              color: dist.vendor_id ? '#14b8a6' : '#f97316', letterSpacing: '0.04em'
            }}>
              {dist.vendor_id ? 'SAVED DISTRIBUTOR' : 'NEW DISTRIBUTOR'}
            </span>
          </div>
        )}
        <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
          <div style={{ flex: 1 }}>
            <label style={label}>Invoice No</label>
            <input style={field} value={dist.invoice_no || ''} onChange={(e) => setDist((d) => ({ ...d, invoice_no: e.target.value }))} />
          </div>
          <div style={{ flex: 1 }}>
            <label style={label}>Invoice Date</label>
            <input type="date" style={field} value={dist.invoice_date || ''} onChange={(e) => setDist((d) => ({ ...d, invoice_date: e.target.value }))} />
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <div style={{ flex: 1 }}>
            <label style={label}>GSTIN</label>
            <input style={field} value={dist.gstin || ''} onChange={(e) => setDist((d) => ({ ...d, gstin: e.target.value }))} />
          </div>
          <div style={{ flex: 1 }}>
            <label style={label}>PAN</label>
            <input style={field} value={dist.pan || ''} onChange={(e) => setDist((d) => ({ ...d, pan: e.target.value }))} />
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <div style={{ flex: 1 }}>
            <label style={label}>FSSAI</label>
            <input style={field} value={dist.fssai || ''} onChange={(e) => setDist((d) => ({ ...d, fssai: e.target.value }))} />
          </div>
          <div style={{ flex: 1 }}>
            <label style={label}>Phone</label>
            <input style={field} value={dist.phone || ''} onChange={(e) => setDist((d) => ({ ...d, phone: e.target.value }))} />
          </div>
        </div>
        <div style={{ marginTop: 8 }}>
          <label style={label}>Address</label>
          <input style={field} value={dist.address || ''} onChange={(e) => setDist((d) => ({ ...d, address: e.target.value }))} />
        </div>
      </Section>

      {/* Tax breakdown */}
      <Section title="Tax Breakdown" open={open.tax} onToggle={() => toggle('tax')}>
        {slabList.length === 0 ? (
          <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)' }}>Enter quantities to see the GST split.</div>
        ) : (
          <>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.58rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 3 }}>
              <span>Slab</span><span>Taxable</span><span>Tax</span>
            </div>
            {slabList.map((s) => (
              <div key={s.rate} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.76rem', padding: '2px 0', fontVariantNumeric: 'tabular-nums' }}>
                <span>GST {s.rate}%</span>
                <span style={{ color: 'var(--text-muted)' }}>{money(s.taxable)}</span>
                <span>{money(s.tax)}</span>
              </div>
            ))}
          </>
        )}
      </Section>

      {/* Purchase summary (large) */}
      <Section title="Purchase Summary" open={open.summary} onToggle={() => toggle('summary')} accent>
        <Row l="Gross Amount" v={money(gross)} muted />
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '3px 0', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
          <span>Item Disc</span>{numField('item_disc', '0')}
        </div>
        <Row l="Taxable Amount" v={money(taxable)} muted />
        <Row l="Tax Amount" v={money(taxTotal)} muted />
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '3px 0', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
          <span>Cess</span>{numField('cess', '0')}
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '3px 0', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
          <span>Cash Disc</span>{numField('cash_disc', '0')}
        </div>
        <Row l="Payable Amount" v={money(payable)} strong big />
      </Section>

      {/* Payment */}
      <Section title="Payment" open={open.payment} onToggle={() => toggle('payment')}>
        <div style={{ display: 'flex', gap: 8 }}>
          <div style={{ flex: 1 }}>
            <label style={label}>Mode</label>
            <select style={field} value={pay.mode} onChange={(e) => setPay((p) => ({ ...p, mode: e.target.value }))}>
              <option>Credit</option><option>Cash</option><option>UPI</option><option>Bank</option>
            </select>
          </div>
          <div style={{ flex: 1 }}>
            <label style={label}>Due Date</label>
            <input type="date" style={field} value={pay.due_date} onChange={(e) => setPay((p) => ({ ...p, due_date: e.target.value }))} />
          </div>
        </div>
      </Section>

      {/* Print */}
      <div style={{ padding: '10px 12px' }}>
        <button type="button" onClick={printGRN} disabled={rows.length === 0}
          style={{ width: '100%', padding: '8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-3)', color: 'var(--text-primary)', fontWeight: 700, fontSize: '0.8rem', cursor: rows.length === 0 ? 'not-allowed' : 'pointer', opacity: rows.length === 0 ? 0.5 : 1 }}>
          🖨 Print Purchase / GRN Summary
        </button>
      </div>
    </div>
  )
}
