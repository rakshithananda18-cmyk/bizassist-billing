import React, { useEffect, useState, useCallback } from 'react'
import AppLayout from '../layouts/AppLayout'
import { useAuth, useBusinessConfig } from '../contexts/AuthContext'
import { InventoryIcon, AlertIcon, SyncIcon, PlusIcon } from '../components/Icons'

const fmt = (n) =>
  n != null ? `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '—'

const defaultProduct = {
  name: '', sku: '', barcode: '', category: '', unit: 'pcs',
  min_stock: '', selling_price: '', wholesale_price: '', distributor_price: '', cost_price: '', opening_stock: '',
  attributes: {},
}

const defaultAdjust = {
  product_id: '',
  movement_type: 'stock_in',
  quantity: '',
  reason: '',
  reference: '',
}

const defaultTransfer = {
  from_godown_id: '',
  to_godown_id: '',
  product_id: '',
  quantity: '',
  notes: '',
}

function getStatus(product) {
  const qty = parseFloat(product.stock_qty ?? product.quantity ?? 0)
  const min = parseFloat(product.min_stock ?? 0)
  if (qty <= 0) return 'Out'
  if (qty <= min) return 'Low'
  return 'In Stock'
}

export default function Stock() {
  const { authFetch } = useAuth()
  const { attributesSchema } = useBusinessConfig()

  const [products, setProducts]             = useState([])
  const [godowns, setGodowns]               = useState([])
  const [transfers, setTransfers]           = useState([])
  const [loading, setLoading]               = useState(true)
  const [search, setSearch]                 = useState('')
  const [catFilter, setCatFilter]           = useState('')
  const [activeTab, setActiveTab]           = useState('catalogue') // 'catalogue' | 'godowns'
  const [showAddModal, setShowAddModal]     = useState(false)
  const [showAdjustModal, setShowAdjustModal] = useState(false)
  const [showTransferModal, setShowTransferModal] = useState(false)
  const [form, setForm]                     = useState(defaultProduct)
  const [adjustForm, setAdjustForm]         = useState(defaultAdjust)
  const [transferForm, setTransferForm]     = useState(defaultTransfer)
  
  const [newGodownName, setNewGodownName]   = useState('')
  const [newGodownAddress, setNewGodownAddress] = useState('')
  
  const [submitting, setSubmitting]         = useState(false)
  const [alert, setAlert]                   = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([
      authFetch('/billing/products').then(r => r.ok ? r.json() : []).catch(() => []),
      authFetch('/billing/godowns').then(r => r.ok ? r.json() : []).catch(() => []),
      authFetch('/billing/stock-transfers').then(r => r.ok ? r.json() : []).catch(() => []),
    ]).then(([prodData, godData, transData]) => {
      const items = Array.isArray(prodData) ? prodData : (prodData && Array.isArray(prodData.items) ? prodData.items : [])
      setProducts(items)
      setGodowns(godData)
      setTransfers(transData)
    }).finally(() => setLoading(false))
  }, [authFetch])

  useEffect(() => { load() }, [load])

  const categories = [...new Set(products.map(p => p.category).filter(Boolean))]

  const filtered = products.filter(p => {
    if (catFilter && p.category !== catFilter) return false
    const q = search.toLowerCase()
    return !q || p.name?.toLowerCase().includes(q) || p.sku?.toLowerCase().includes(q)
  })

  const totalProducts = products.length
  const lowStock  = products.filter(p => getStatus(p) === 'Low').length
  const outStock  = products.filter(p => getStatus(p) === 'Out').length

  const setField = (k, v) => setForm(f => ({ ...f, [k]: v }))
  const setAttributeField = (attr, v) => setForm(f => ({
    ...f,
    attributes: {
      ...(f.attributes || {}),
      [attr]: v
    }
  }))
  const setAdjField = (k, v) => setAdjustForm(f => ({ ...f, [k]: v }))
  const setTrsfField = (k, v) => setTransferForm(f => ({ ...f, [k]: v }))

  const handleAddProduct = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    try {
      const res = await authFetch('/billing/products', {
        method: 'POST',
        body: JSON.stringify({
          ...form,
          min_stock: parseFloat(form.min_stock) || 0,
          selling_price: parseFloat(form.selling_price) || 0,
          wholesale_price: parseFloat(form.wholesale_price) || 0,
          distributor_price: parseFloat(form.distributor_price) || 0,
          cost_price: parseFloat(form.cost_price) || 0,
          opening_stock: parseFloat(form.opening_stock) || 0,
          attributes: form.attributes || {},
        }),
      })
      if (res.ok) {
        setAlert({ type: 'success', msg: 'Product added successfully!' })
        setShowAddModal(false)
        setForm(defaultProduct)
        load()
      } else {
        const err = await res.json().catch(() => ({}))
        setAlert({ type: 'danger', msg: err.detail || 'Failed to add product.' })
      }
    } catch {
      setAlert({ type: 'danger', msg: 'Network error.' })
    } finally {
      setSubmitting(false)
    }
  }

  const handleAdjust = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    try {
      const res = await authFetch('/billing/stock/adjust', {
        method: 'POST',
        body: JSON.stringify({ ...adjustForm, quantity: parseFloat(adjustForm.quantity) || 0 }),
      })
      if (res.ok) {
        setAlert({ type: 'success', msg: 'Stock adjusted successfully!' })
        setShowAdjustModal(false)
        setAdjustForm(defaultAdjust)
        load()
      } else {
        setAlert({ type: 'danger', msg: 'Failed to adjust stock.' })
      }
    } catch {
      setAlert({ type: 'danger', msg: 'Network error.' })
    } finally {
      setSubmitting(false)
    }
  }

  const handleAddGodown = async (e) => {
    e.preventDefault()
    if (!newGodownName.trim()) return
    setSubmitting(true)
    try {
      const res = await authFetch('/billing/godowns', {
        method: 'POST',
        body: JSON.stringify({ name: newGodownName.trim(), address: newGodownAddress.trim() }),
      })
      if (res.ok) {
        setNewGodownName('')
        setNewGodownAddress('')
        setAlert({ type: 'success', msg: 'Godown added successfully!' })
        load()
      } else {
        const err = await res.json().catch(() => ({}))
        setAlert({ type: 'danger', msg: err.detail || 'Failed to add godown.' })
      }
    } catch {
      setAlert({ type: 'danger', msg: 'Network error.' })
    } finally {
      setSubmitting(false)
    }
  }

  const handleTransferStock = async (e) => {
    e.preventDefault()
    if (!transferForm.from_godown_id || !transferForm.to_godown_id || !transferForm.product_id || !transferForm.quantity) {
      setAlert({ type: 'danger', msg: 'Please fill out all required transfer fields.' })
      return
    }
    setSubmitting(true)
    try {
      const res = await authFetch('/billing/stock-transfers', {
        method: 'POST',
        body: JSON.stringify({
          transfer_date: new Date().toISOString().split('T')[0],
          from_godown_id: parseInt(transferForm.from_godown_id),
          to_godown_id: parseInt(transferForm.to_godown_id),
          notes: transferForm.notes || null,
          items: [
            {
              product_id: parseInt(transferForm.product_id),
              product_name: products.find(p => p.id === parseInt(transferForm.product_id))?.name || '',
              quantity: parseFloat(transferForm.quantity)
            }
          ]
        }),
      })
      if (res.ok) {
        setAlert({ type: 'success', msg: 'Stock transferred successfully!' })
        setShowTransferModal(false)
        setTransferForm(defaultTransfer)
        load()
      } else {
        const err = await res.json().catch(() => ({}))
        setAlert({ type: 'danger', msg: err.detail || 'Failed to transfer stock.' })
      }
    } catch {
      setAlert({ type: 'danger', msg: 'Network error.' })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AppLayout title="Stock & Inventory">
      <div className="slide-up">

        {alert && (
          <div className={`alert alert-${alert.type} mb-4`}>
            {alert.type === 'success' ? '✅' : '❌'} {alert.msg}
            <button onClick={() => setAlert(null)} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'inherit', cursor: 'pointer' }}>✕</button>
          </div>
        )}

        {/* Header */}
        <div className="page-header">
          <div className="page-header-left">
            <h1 className="page-title">Stock & Inventory</h1>
            <p className="page-subtitle">Manage your product catalogue, pricing tiers, and warehouse locations</p>
          </div>
          <div className="page-actions">
            {activeTab === 'catalogue' ? (
              <>
                <button className="btn btn-secondary" onClick={() => { setAdjustForm(defaultAdjust); setShowAdjustModal(true) }}>
                  ↕ Adjust Stock
                </button>
                <button className="btn btn-primary" onClick={() => { setForm(defaultProduct); setShowAddModal(true) }}>
                  ＋ Add Product
                </button>
              </>
            ) : (
              <button className="btn btn-primary" onClick={() => { setTransferForm(defaultTransfer); setShowTransferModal(true) }}>
                ＋ Transfer Stock
              </button>
            )}
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="page-subbar" style={{ display: 'flex', gap: 16, borderBottom: '1px solid var(--border)' }}>
          <button
            onClick={() => setActiveTab('catalogue')}
            style={{
              padding: '10px 16px',
              fontWeight: 600,
              fontSize: '0.95rem',
              color: activeTab === 'catalogue' ? 'var(--text-primary)' : 'var(--text-muted)',
              borderBottom: activeTab === 'catalogue' ? '2px solid var(--accent)' : '2px solid transparent',
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              marginBottom: -1
            }}
          >
            Product Catalogue
          </button>
          <button
            onClick={() => setActiveTab('godowns')}
            style={{
              padding: '10px 16px',
              fontWeight: 600,
              fontSize: '0.95rem',
              color: activeTab === 'godowns' ? 'var(--text-primary)' : 'var(--text-muted)',
              borderBottom: activeTab === 'godowns' ? '2px solid var(--accent)' : '2px solid transparent',
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              marginBottom: -1
            }}
          >
            Godowns & Transfers
          </button>
        </div>

        {/* Stat cards */}
        <div className="vsummary-strip-three mb-6">
          <div className="vsummary-card" style={{ borderLeftColor: 'var(--accent)' }}>
            <div className="vsummary-label">Total Products</div>
            <div className="vsummary-value">{totalProducts}</div>
            <div className="vsummary-sub">active catalogue items</div>
          </div>
          <div className="vsummary-card" style={{ borderLeftColor: '#c97c22' }}>
            <div className="vsummary-label">Low Stock</div>
            <div className="vsummary-value">{lowStock}</div>
            <div className="vsummary-sub">below minimum threshold</div>
          </div>
          <div className="vsummary-card" style={{ borderLeftColor: '#c02a2a' }}>
            <div className="vsummary-label">Out of Stock</div>
            <div className="vsummary-value" style={{ color: '#c02a2a' }}>{outStock}</div>
            <div className="vsummary-sub">needs immediate restock</div>
          </div>
        </div>

        {activeTab === 'catalogue' ? (
          <>
            {/* Filters */}
            <div className="flex items-center gap-3 mb-4" style={{ flexWrap: 'wrap' }}>
              <div className="search-bar">
                <span style={{ color: 'var(--text-muted)' }}>🔍</span>
                <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search products…" />
              </div>
              <select
                className="form-select"
                style={{ width: 'auto', minWidth: 160 }}
                value={catFilter}
                onChange={e => setCatFilter(e.target.value)}
              >
                <option value="">All Categories</option>
                {categories.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>

            {/* Table */}
            {loading ? (
              <div className="page-loader"><span className="spinner" /> Loading products…</div>
            ) : (
              <div className="data-table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Product</th>
                      <th>SKU / Barcode</th>
                      <th>Category</th>
                      <th>Stock Qty</th>
                      <th>Unit</th>
                      <th>Min Stock</th>
                      <th>Selling Price</th>
                      <th>Wholesale Price</th>
                      <th>Distributor Price</th>
                      <th>Cost Price</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.length === 0 ? (
                      <tr><td colSpan={11}>
                        <div className="empty-state">
                          <div className="empty-icon"><InventoryIcon size={24} /></div>
                          <h3>No products found</h3>
                          <p>{search ? 'Try a different search.' : 'Add your first product using the button above.'}</p>
                        </div>
                      </td></tr>
                    ) : filtered.map(p => {
                      const status = getStatus(p)
                      const isLow = status === 'Low' || status === 'Out'
                      return (
                        <tr key={p.id} style={isLow ? { background: 'rgba(239,68,68,0.03)' } : {}}>
                          <td className="td-primary">{p.name}</td>
                          <td className="td-mono" style={{ fontSize: '0.78rem' }}>
                            <div>{p.sku || '—'}</div>
                            {p.barcode && <div style={{ color: 'var(--text-muted)', fontSize: '0.72rem' }}>{p.barcode}</div>}
                          </td>
                          <td>
                            {p.category
                              ? <span className="badge badge-muted">{p.category}</span>
                              : <span style={{ color: 'var(--text-muted)' }}>—</span>}
                          </td>
                          <td style={{ fontWeight: 700, color: isLow ? 'var(--danger)' : 'var(--text-primary)' }}>
                            {p.stock_qty ?? p.quantity ?? 0}
                          </td>
                          <td style={{ color: 'var(--text-muted)' }}>{p.unit || 'pcs'}</td>
                          <td style={{ color: 'var(--text-muted)' }}>{p.min_stock ?? 0}</td>
                          <td>{fmt(p.selling_price)}</td>
                          <td>{fmt(p.wholesale_price)}</td>
                          <td>{fmt(p.distributor_price)}</td>
                          <td>{fmt(p.cost_price)}</td>
                          <td>
                            <span className={`badge ${status === 'In Stock' ? 'badge-success' : status === 'Low' ? 'badge-warning' : 'badge-danger'}`}>
                              {status}
                            </span>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </>
        ) : (
          /* Godowns & Stock Transfers View */
          <div className="grid grid-2 gap-4">
            {/* Left side: Godowns listing & Add Godown form */}
            <div>
              <h3 style={{ color: 'var(--text-primary)', fontWeight: 600, marginBottom: 12 }}>Godown Locations</h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 20 }}>
                {godowns.length === 0 ? (
                  <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>No godown locations registered. List is auto-seeded when billing counter starts.</p>
                ) : (
                  godowns.map(g => (
                    <div key={g.id} style={{ background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: '8px', padding: '14px', boxShadow: 'var(--shadow-sm)' }}>
                      <div style={{ display: 'flex', justifycontent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: '0.92rem' }}>{g.name}</span>
                        <span className="badge badge-success" style={{ fontSize: '0.68rem' }}>Active</span>
                      </div>
                      {g.address && <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginTop: 4, marginBottom: 0 }}>{g.address}</p>}
                    </div>
                  ))
                )}
              </div>

              {/* Add Godown Form */}
              <div style={{ background: 'var(--bg-3)', border: '1px solid var(--border)', borderRadius: '8px', padding: '16px' }}>
                <h4 style={{ color: 'var(--text-primary)', fontWeight: 600, fontSize: '0.85rem', marginBottom: 10 }}>Register New Godown Location</h4>
                <form onSubmit={handleAddGodown} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <div className="form-group">
                    <label className="form-label" style={{ fontSize: '0.72rem' }}>Godown Name *</label>
                    <input className="form-input" style={{ height: 35, fontSize: '0.82rem' }} placeholder="e.g. Outlet Store, Cold Storage" value={newGodownName} onChange={e => setNewGodownName(e.target.value)} required />
                  </div>
                  <div className="form-group">
                    <label className="form-label" style={{ fontSize: '0.72rem' }}>Address / Location</label>
                    <input className="form-input" style={{ height: 35, fontSize: '0.82rem' }} placeholder="e.g. Ground Floor, Sector 4" value={newGodownAddress} onChange={e => setNewGodownAddress(e.target.value)} />
                  </div>
                  <button type="submit" className="btn btn-primary btn-sm" disabled={submitting} style={{ alignSelf: 'flex-start' }}>
                    {submitting ? 'Registering…' : '✓ Register Godown'}
                  </button>
                </form>
              </div>
            </div>

            {/* Right side: Stock Transfer History */}
            <div>
              <h3 style={{ color: '#0f172a', fontWeight: 800, marginBottom: 12 }}>⚡ Stock Transfer Log</h3>
              <div className="data-table-wrap" style={{ maxHeight: '420px', overflowY: 'auto' }}>
                <table className="data-table" style={{ fontSize: '0.8rem' }}>
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>From Godown</th>
                      <th>To Godown</th>
                      <th>Item</th>
                      <th>Qty</th>
                    </tr>
                  </thead>
                  <tbody>
                    {transfers.length === 0 ? (
                      <tr>
                        <td colSpan={5} style={{ textAlign: 'center', color: '#64748b', padding: '20px 0' }}>
                          No stock transfers recorded yet.
                        </td>
                      </tr>
                    ) : (
                      transfers.map(t => (
                        <tr key={t.id}>
                          <td>{t.transfer_date}</td>
                          <td style={{ fontWeight: 600, color: '#b91c1c' }}>{t.from_godown_name}</td>
                          <td style={{ fontWeight: 600, color: '#15803d' }}>{t.to_godown_name}</td>
                          <td>
                            {t.items && t.items.map(it => (
                              <div key={it.id}>{it.product_name}</div>
                            ))}
                          </td>
                          <td style={{ fontWeight: 700 }}>
                            {t.items && t.items.map(it => (
                              <div key={it.id}>{it.quantity} {it.unit || 'pcs'}</div>
                            ))}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Add Product Modal */}
      {showAddModal && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowAddModal(false)}>
          <div className="modal modal-lg">
            <div className="modal-header">
              <span className="modal-title" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <InventoryIcon size={16} />
                <span>Add Product</span>
              </span>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowAddModal(false)}>✕</button>
            </div>
            <form onSubmit={handleAddProduct}>
              <div className="modal-body">
                <div className="grid grid-2 gap-3 mb-4">
                  <div className="form-group">
                    <label className="form-label">Product Name *</label>
                    <input className="form-input" placeholder="e.g. Basmati Rice 1kg" value={form.name} onChange={e => setField('name', e.target.value)} required />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Category</label>
                    <input className="form-input" placeholder="e.g. Groceries, Electronics…" value={form.category} onChange={e => setField('category', e.target.value)} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">SKU</label>
                    <input className="form-input" placeholder="e.g. RICE-1KG-001" value={form.sku} onChange={e => setField('sku', e.target.value)} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Barcode</label>
                    <input className="form-input" placeholder="e.g. 8901234567890" value={form.barcode} onChange={e => setField('barcode', e.target.value)} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Unit</label>
                    <select className="form-select" value={form.unit} onChange={e => setField('unit', e.target.value)}>
                      <option value="pcs">Pieces</option>
                      <option value="kg">Kilograms</option>
                      <option value="g">Grams</option>
                      <option value="L">Litres</option>
                      <option value="mL">mL</option>
                      <option value="box">Box</option>
                      <option value="set">Set</option>
                      <option value="pair">Pair</option>
                    </select>
                  </div>
                  <div className="form-group">
                    <label className="form-label">Minimum Stock Level</label>
                    <input type="number" className="form-input" placeholder="0" min="0" value={form.min_stock} onChange={e => setField('min_stock', e.target.value)} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Selling Price (₹)</label>
                    <input type="number" className="form-input" placeholder="0.00" min="0" step="any" value={form.selling_price} onChange={e => setField('selling_price', e.target.value)} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Cost Price (₹)</label>
                    <input type="number" className="form-input" placeholder="0.00" min="0" step="any" value={form.cost_price} onChange={e => setField('cost_price', e.target.value)} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Opening Stock Qty</label>
                    <input type="number" className="form-input" placeholder="0" min="0" value={form.opening_stock} onChange={e => setField('opening_stock', e.target.value)} />
                  </div>
                  {attributesSchema && attributesSchema.map(field => (
                    <div className="form-group" key={field.attr}>
                      <label className="form-label">{field.label}{field.required ? ' *' : ''}</label>
                      {field.type === 'enum' ? (
                        <select
                          className="form-select"
                          value={form.attributes?.[field.attr] || ''}
                          onChange={e => setAttributeField(field.attr, e.target.value)}
                          required={field.required}
                        >
                          {field.options && field.options.map(opt => (
                            <option key={opt} value={opt}>{opt || 'Select Option'}</option>
                          ))}
                        </select>
                      ) : (
                        <input
                          type={field.type === 'number' ? 'number' : 'text'}
                          className="form-input"
                          placeholder={`Enter ${field.label.toLowerCase()}`}
                          value={form.attributes?.[field.attr] || ''}
                          onChange={e => setAttributeField(field.attr, e.target.value)}
                          required={field.required}
                        />
                      )}
                    </div>
                  ))}
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setShowAddModal(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={submitting}>
                  {submitting ? <><span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /> Saving…</> : '✓ Add Product'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Adjust Stock Modal */}
      {showAdjustModal && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowAdjustModal(false)}>
          <div className="modal">
            <div className="modal-header">
              <span className="modal-title">↕ Adjust Stock</span>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowAdjustModal(false)}>✕</button>
            </div>
            <form onSubmit={handleAdjust}>
              <div className="modal-body">
                <div className="form-group mb-4">
                  <label className="form-label">Select Product *</label>
                  <select className="form-select" value={adjustForm.product_id} onChange={e => setAdjField('product_id', e.target.value)} required>
                    <option value="">Choose a product…</option>
                    {products.map(p => (
                      <option key={p.id} value={p.id}>{p.name} (Stock: {p.stock_qty ?? p.quantity ?? 0} {p.unit || ''})</option>
                    ))}
                  </select>
                </div>
                <div className="grid grid-2 gap-3 mb-4">
                  <div className="form-group">
                    <label className="form-label">Movement Type</label>
                    <select className="form-select" value={adjustForm.movement_type} onChange={e => setAdjField('movement_type', e.target.value)}>
                      <option value="stock_in">📥 Stock In</option>
                      <option value="stock_out">📤 Stock Out</option>
                      <option value="adjustment">✏️ Adjustment</option>
                    </select>
                  </div>
                  <div className="form-group">
                    <label className="form-label">Quantity</label>
                    <input type="number" className="form-input" placeholder="0" min="0" step="any" value={adjustForm.quantity} onChange={e => setAdjField('quantity', e.target.value)} required />
                  </div>
                </div>
                <div className="form-group mb-4">
                  <label className="form-label">Reason</label>
                  <input className="form-input" placeholder="e.g. Damaged goods, Physical count correction…" value={adjustForm.reason} onChange={e => setAdjField('reason', e.target.value)} />
                </div>
                <div className="form-group">
                  <label className="form-label">Reference</label>
                  <input className="form-input" placeholder="PO number, GRN number…" value={adjustForm.reference} onChange={e => setAdjField('reference', e.target.value)} />
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setShowAdjustModal(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={submitting}>
                  {submitting ? <><span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /> Adjusting…</> : '✓ Apply Adjustment'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Transfer Stock Modal */}
      {showTransferModal && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowTransferModal(false)}>
          <div className="modal">
            <div className="modal-header">
              <span className="modal-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <SyncIcon size={16} />
                <span>Transfer Stock</span>
              </span>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowTransferModal(false)}>✕</button>
            </div>
            <form onSubmit={handleTransferStock}>
              <div className="modal-body">
                <div className="form-group mb-4">
                  <label className="form-label">Select Product *</label>
                  <select className="form-select" value={transferForm.product_id} onChange={e => setTrsfField('product_id', e.target.value)} required>
                    <option value="">Choose a product…</option>
                    {products.map(p => (
                      <option key={p.id} value={p.id}>{p.name} (Total Stock: {p.stock_qty ?? p.quantity ?? 0} {p.unit || ''})</option>
                    ))}
                  </select>
                </div>
                <div className="grid grid-2 gap-3 mb-4">
                  <div className="form-group">
                    <label className="form-label">From Godown *</label>
                    <select className="form-select" value={transferForm.from_godown_id} onChange={e => setTrsfField('from_godown_id', e.target.value)} required>
                      <option value="">Select source…</option>
                      {godowns.map(g => (
                        <option key={g.id} value={g.id}>{g.name}</option>
                      ))}
                    </select>
                  </div>
                  <div className="form-group">
                    <label className="form-label">To Godown *</label>
                    <select className="form-select" value={transferForm.to_godown_id} onChange={e => setTrsfField('to_godown_id', e.target.value)} required>
                      <option value="">Select destination…</option>
                      {godowns.map(g => (
                        <option key={g.id} value={g.id}>{g.name}</option>
                      ))}
                    </select>
                  </div>
                </div>
                <div className="form-group mb-4">
                  <label className="form-label">Quantity *</label>
                  <input type="number" className="form-input" placeholder="0" min="0.001" step="any" value={transferForm.quantity} onChange={e => setTrsfField('quantity', e.target.value)} required />
                </div>
                <div className="form-group">
                  <label className="form-label">Notes / Remarks</label>
                  <input className="form-input" placeholder="Reason for transfer, vehicle details etc." value={transferForm.notes} onChange={e => setTrsfField('notes', e.target.value)} />
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setShowTransferModal(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={submitting}>
                  {submitting ? <><span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /> Transferring…</> : '✓ Transfer Stock'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </AppLayout>
  )
}
