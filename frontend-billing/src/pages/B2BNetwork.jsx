// ============================================================================
// Page: Connections.jsx
// Description: B2B vendor/buyer connection requests, rules, policy setups,
//              and connection codes. Enables merchants to request, establish,
//              and revoke secure sync pipes between businesses.
// ============================================================================
import React, { useEffect, useState, useCallback } from 'react'
import AppLayout from '../layouts/AppLayout'
import { useAuth } from '../contexts/AuthContext'
import { logger } from '../utils/logger'
import { AlertIcon, BillsIcon, CartIcon, CheckIcon, CloseIcon, ConnectionIcon, SettingsIcon, ShieldIcon, SparkleIcon } from '../components/Icons'
import CustomSelect from '../components/common/CustomSelect'

const fmt = (n) =>
  n != null ? `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '—'

export default function B2BNetwork() {
  const { authFetch } = useAuth()

  // State
  const [myBizId, setMyBizId] = useState('')
  const [connections, setConnections] = useState({ as_seller: [], as_buyer: [] })
  const [activeTab, setActiveTab] = useState('Customers') // 'Customers' | 'Suppliers'
  const [loading, setLoading] = useState(true)
  const [alert, setAlert] = useState(null)
  
  // Connection states
  const [connectBizId, setConnectBizId] = useState('')
  const [connectAs, setConnectAs] = useState('buyer') // 'buyer' | 'seller'
  const [connecting, setConnecting] = useState(false)
  
  // Policy Modal state
  const [showPolicyModal, setShowPolicyModal] = useState(false)
  const [selectedConnection, setSelectedConnection] = useState(null)
  const [policyForm, setPolicyForm] = useState({
    price_tier: 'standard',
    discount_pct: 0,
    credit_limit: 0,
    stock_visibility: 'exact',
    catalog_category: ''
  })
  const [policySubmitting, setPolicySubmitting] = useState(false)
  
  // Revoke state
  const [showRevokeModal, setShowRevokeModal] = useState(false)
  const [connectionToRevoke, setConnectionToRevoke] = useState(null)
  const [revoking, setRevoking] = useState(false)

  // Copy feedbacks
  const [copiedId, setCopiedId] = useState(false)

  // Load connections and own BizID
  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const [bizidRes, connRes] = await Promise.all([
        authFetch('/bizid').then(r => r.ok ? r.json() : null),
        authFetch('/connections/connections').then(r => r.ok ? r.json() : { as_seller: [], as_buyer: [] })
      ])
      
      if (bizidRes) {
        setMyBizId(bizidRes.public_id)
      }
      if (connRes) {
        setConnections(connRes)
      }
    } catch (err) {
      logger.error('Error loading connections:', err)
      setAlert({ type: 'danger', msg: 'Failed to load connections data.' })
    } finally {
      setLoading(false)
    }
  }, [authFetch])

  useEffect(() => {
    loadData()
  }, [loadData])

  // Copy to clipboard helper
  const handleCopy = (text, setCopied) => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  // Connect via BizID
  const handleConnect = async (e) => {
    e.preventDefault()
    const cleanedId = connectBizId.trim().toUpperCase()
    if (!cleanedId) return
    setConnecting(true)
    try {
      const res = await authFetch('/connections/connections/connect', {
        method: 'POST',
        body: JSON.stringify({ bizid: cleanedId, connect_as: connectAs })
      })
      if (res.ok) {
        setAlert({ type: 'success', msg: `Successfully connected with business ${cleanedId}!` })
        setConnectBizId('')
        loadData()
        setActiveTab(connectAs === 'buyer' ? 'Suppliers' : 'Customers')
      } else {
        const err = await res.json().catch(() => ({}))
        setAlert({ type: 'danger', msg: err.detail || 'Failed to establish connection.' })
      }
    } catch {
      setAlert({ type: 'danger', msg: 'Network error establishing connection.' })
    } finally {
      setConnecting(false)
    }
  }

  // Open edit policy modal
  const openPolicyModal = (conn) => {
    setSelectedConnection(conn)
    setPolicyForm({
      price_tier: conn.price_tier || 'standard',
      discount_pct: conn.discount_pct || 0,
      credit_limit: conn.credit_limit || 0,
      stock_visibility: conn.stock_visibility || 'exact',
      catalog_category: conn.catalog_category || ''
    })
    setShowPolicyModal(true)
  }

  // Save policy updates
  const handleSavePolicy = async (e) => {
    e.preventDefault()
    if (!selectedConnection) return
    setPolicySubmitting(true)
    try {
      const res = await authFetch(`/connections/connections/${selectedConnection.id}/policy`, {
        method: 'POST',
        body: JSON.stringify({
          price_tier: policyForm.price_tier,
          discount_pct: parseFloat(policyForm.discount_pct) || 0,
          credit_limit: parseFloat(policyForm.credit_limit) || 0,
          stock_visibility: policyForm.stock_visibility,
          catalog_category: policyForm.catalog_category.trim() || null
        })
      })
      if (res.ok) {
        setAlert({ type: 'success', msg: 'Connection policy updated!' })
        setShowPolicyModal(false)
        loadData()
      } else {
        const err = await res.json().catch(() => ({}))
        setAlert({ type: 'danger', msg: err.detail || 'Failed to update connection policy.' })
      }
    } catch {
      setAlert({ type: 'danger', msg: 'Network error updating policy.' })
    } finally {
      setPolicySubmitting(false)
    }
  }

  // Trigger connection revoke
  const confirmRevoke = (conn) => {
    setConnectionToRevoke(conn)
    setShowRevokeModal(true)
  }

  const handleRevoke = async () => {
    if (!connectionToRevoke) return
    setRevoking(true)
    try {
      const res = await authFetch(`/connections/connections/${connectionToRevoke.id}/revoke`, {
        method: 'POST'
      })
      if (res.ok) {
        setAlert({ type: 'success', msg: 'Partnership revoked successfully.' })
        setShowRevokeModal(false)
        setConnectionToRevoke(null)
        loadData()
      } else {
        const err = await res.json().catch(() => ({}))
        setAlert({ type: 'danger', msg: err.detail || 'Failed to revoke partnership.' })
      }
    } catch {
      setAlert({ type: 'danger', msg: 'Network error revoking partnership.' })
    } finally {
      setRevoking(false)
    }
  }

  return (
    <AppLayout title="B2B Network">
      <div className="slide-up">

        {alert && (
          <div className={`alert alert-${alert.type} mb-4`}>
            {alert.type === 'success' ? '✅' : '❌'} {alert.msg}
            <button onClick={() => setAlert(null)} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'inherit', cursor: 'pointer' }} aria-label="Close"><CloseIcon size={16} /></button>
          </div>
        )}

        {/* Header */}
        <div className="page-header">
          <div className="page-header-left">
            <h1 className="page-title">B2B Network</h1>
            <p className="page-subtitle">Link with customers and suppliers to synchronize order flows and visibility policies</p>
          </div>
        </div>

        {/* Top Cards Section: My ID + Operations */}
        <div className="grid grid-2 gap-4 mb-5">
          {/* My BizID Display */}
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-4)', padding: 'var(--sp-5)' }}>
            <div>
              <div className="flex items-center gap-2 mb-1">
                <span style={{ fontSize: '0.75rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text)' }}>
                  My Network Address
                </span>
              </div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                Share your unique BizID so other businesses can establish connection channels with you.
              </div>
            </div>
            
            <div className="flex items-center justify-between mt-auto" style={{
              background: 'var(--bg-3)',
              padding: '8px 12px',
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--border-strong)'
            }}>
              <span className="td-mono" style={{ fontSize: '1.1rem', fontWeight: 600, color: 'var(--accent)', letterSpacing: '1px' }}>
                {myBizId || 'Loading...'}
              </span>
              {myBizId && (
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => handleCopy(myBizId, setCopiedId)}
                  style={{ minWidth: 64, height: 32 }}
                >
                  {copiedId ? 'Copied' : 'Copy'}
                </button>
              )}
            </div>
          </div>

          {/* Connect to Another Business */}
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-4)', padding: 'var(--sp-5)' }}>
            <div>
              <div className="flex items-center gap-2 mb-1">
                <ConnectionIcon size={16} style={{ color: 'var(--accent)' }} />
                <span style={{ fontSize: '0.75rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text)' }}>
                  Connect Business Channel
                </span>
              </div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                Enter the BizID of the supplier you restock from or customer you sell to.
              </div>
            </div>
            
            <form onSubmit={handleConnect} className="mt-auto flex" style={{ gap: 'var(--sp-3)' }}>
              <input
                className="form-input td-mono"
                style={{ textTransform: 'uppercase', letterSpacing: '0.5px', flex: 1 }}
                placeholder="E.G. BA-ABC123"
                value={connectBizId}
                onChange={e => setConnectBizId(e.target.value)}
                required
              />
              <CustomSelect
                className="form-select"
                value={connectAs}
                onChange={e => setConnectAs(e.target.value)}
                style={{ width: 140 }}
              >
                <option value="buyer">As Buyer</option>
                <option value="seller">As Seller</option>
              </CustomSelect>
              <button type="submit" className="btn btn-primary" disabled={connecting} style={{ height: 38 }}>
                {connecting ? '...' : <span style={{ display: 'inline-flex', alignItems: 'center' }}><ConnectionIcon size={16} /></span>}
              </button>
            </form>
          </div>
        </div>

        {/* Tab Controls & Connections List */}
        <div className="tabs page-subbar">
          <button className={`tab${activeTab === 'Customers' ? ' active' : ''}`} onClick={() => setActiveTab('Customers')}>
            <ShieldIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> My Customers <span style={{ marginLeft: 4, fontSize: '0.7rem', opacity: 0.7 }}>({connections.as_seller.length})</span>
          </button>
          <button className={`tab${activeTab === 'Suppliers' ? ' active' : ''}`} onClick={() => setActiveTab('Suppliers')}>
            <CartIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> My Suppliers <span style={{ marginLeft: 4, fontSize: '0.7rem', opacity: 0.7 }}>({connections.as_buyer.length})</span>
          </button>
        </div>

        {loading ? (
          <div className="page-loader"><span className="spinner" /> Loading network details…</div>
        ) : (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead>
                {activeTab === 'Customers' ? (
                  <tr>
                    <th>Business / Customer</th>
                    <th>BizID</th>
                    <th>Price Policy</th>
                    <th>Discount</th>
                    <th>Credit Limit</th>
                    <th>Stock Visibility</th>
                    <th>Category Filter</th>
                    <th>Status</th>
                    <th style={{ width: 140 }}>Actions</th>
                  </tr>
                ) : (
                  <tr>
                    <th>Supplier</th>
                    <th>Supplier BizID</th>
                    <th>My Price Tier</th>
                    <th>My Discount</th>
                    <th>Credit Limit</th>
                    <th>Stock Visibility</th>
                    <th>Outstanding Balance</th>
                    <th>Status</th>
                    <th style={{ width: 100 }}>Actions</th>
                  </tr>
                )}
              </thead>
              <tbody>
                {activeTab === 'Customers' ? (
                  connections.as_seller.length === 0 ? (
                    <tr>
                      <td colSpan={9}>
                        <div className="empty-state">
                          <div className="empty-icon"><ConnectionIcon size={24} /></div>
                          <h3>No Customers Connected Yet</h3>
                          <p>Use the connection box above to connect directly using your customer's BizID.</p>
                        </div>
                      </td>
                    </tr>
                  ) : (
                    connections.as_seller.map(conn => (
                      <tr key={conn.id}>
                        <td>
                          <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{conn.buyer_name}</div>
                          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Linked on {new Date(conn.created_at).toLocaleDateString('en-IN')}</div>
                        </td>
                        <td className="td-mono">{conn.buyer_bizid}</td>
                        <td>
                          <span className="badge badge-info" style={{ textTransform: 'capitalize' }}>
                            {conn.price_tier}
                          </span>
                        </td>
                        <td>{conn.discount_pct > 0 ? `${conn.discount_pct}%` : 'None'}</td>
                        <td>{conn.credit_limit > 0 ? fmt(conn.credit_limit) : 'Unlimited'}</td>
                        <td>
                          <span className={`badge ${conn.stock_visibility === 'exact' ? 'badge-success' : conn.stock_visibility === 'band' ? 'badge-warning' : 'badge-danger'}`} style={{ textTransform: 'capitalize' }}>
                            {conn.stock_visibility}
                          </span>
                        </td>
                        <td style={{ color: conn.catalog_category ? 'var(--text-primary)' : 'var(--text-muted)' }}>
                          {conn.catalog_category || 'All Categories'}
                        </td>
                        <td>
                          <span className={`badge ${conn.status === 'accepted' ? 'badge-success' : 'badge-danger'}`} style={{ textTransform: 'capitalize' }}>
                            {conn.status}
                          </span>
                        </td>
                        <td>
                          <div className="flex gap-1">
                            <button className="btn btn-secondary btn-sm" onClick={() => openPolicyModal(conn)} title="Configure policies" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                              <SettingsIcon size={12} />
                              <span>Policy</span>
                            </button>
                            <button className="btn btn-ghost btn-sm" style={{ color: 'var(--danger)' }} onClick={() => confirmRevoke(conn)} title="Revoke connection">
                              ✕ Revoke
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))
                  )
                ) : (
                  connections.as_buyer.length === 0 ? (
                    <tr>
                      <td colSpan={9}>
                        <div className="empty-state">
                          <div className="empty-icon"><BillsIcon size={24} /></div>
                          <h3>No Suppliers Connected Yet</h3>
                          <p>Use the connection box above to connect directly using your supplier's BizID.</p>
                        </div>
                      </td>
                    </tr>
                  ) : (
                    connections.as_buyer.map(conn => (
                      <tr key={conn.id}>
                        <td>
                          <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{conn.seller_name}</div>
                          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Linked on {new Date(conn.created_at).toLocaleDateString('en-IN')}</div>
                        </td>
                        <td className="td-mono">{conn.seller_bizid}</td>
                        <td>
                          <span className="badge badge-info" style={{ textTransform: 'capitalize' }}>
                            {conn.price_tier}
                          </span>
                        </td>
                        <td>{conn.discount_pct > 0 ? `${conn.discount_pct}%` : 'None'}</td>
                        <td>{conn.credit_limit > 0 ? fmt(conn.credit_limit) : 'Unlimited'}</td>
                        <td>
                          <span className="badge badge-secondary" style={{ textTransform: 'capitalize' }}>
                            {conn.stock_visibility}
                          </span>
                        </td>
                        <td style={{ fontWeight: 600 }}>
                          {conn.outstanding_balance > 0 ? (
                            <span className="badge badge-danger">{fmt(conn.outstanding_balance)}</span>
                          ) : (
                            <span className="badge badge-success">Nil</span>
                          )}
                        </td>
                        <td>
                          <span className={`badge ${conn.status === 'accepted' ? 'badge-success' : 'badge-danger'}`} style={{ textTransform: 'capitalize' }}>
                            {conn.status}
                          </span>
                        </td>
                        <td>
                          <button className="btn btn-ghost btn-sm" style={{ color: 'var(--danger)' }} onClick={() => confirmRevoke(conn)} title="Revoke connection">
                            ✕ Revoke
                          </button>
                        </td>
                      </tr>
                    ))
                  )
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* Configure Policy Modal */}
        {showPolicyModal && selectedConnection && (
          <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowPolicyModal(false)}>
            <div className="modal">
              <div className="modal-header">
                <span className="modal-title">⚙️ Policy: {selectedConnection.buyer_name}</span>
                <button className="btn btn-ghost btn-icon" onClick={() => setShowPolicyModal(false)} aria-label="Close"><CloseIcon size={16} /></button>
              </div>
              <form onSubmit={handleSavePolicy}>
                <div className="modal-body">
                  <div className="form-group mb-3">
                    <label className="form-label">Price Tier</label>
                    <CustomSelect
                      className="form-select"
                      value={policyForm.price_tier}
                      onChange={e => setPolicyForm({ ...policyForm, price_tier: e.target.value })}
                    >
                      <option value="standard">Standard Retail Price</option>
                      <option value="wholesale">Wholesale Price</option>
                      <option value="distributor">Distributor Price</option>
                    </CustomSelect>
                    <small style={{ color: 'var(--text-muted)', fontSize: '0.75rem', display: 'block', marginTop: 4 }}>
                      Select which catalog price tier applies to this customer.
                    </small>
                  </div>

                  <div className="grid grid-2 gap-3 mb-3">
                    <div className="form-group">
                      <label className="form-label">Discount Override (%)</label>
                      <input
                        type="number"
                        className="form-input"
                        min="0"
                        max="100"
                        step="0.01"
                        value={policyForm.discount_pct}
                        onChange={e => setPolicyForm({ ...policyForm, discount_pct: e.target.value })}
                      />
                    </div>
                    <div className="form-group">
                      <label className="form-label">Credit Limit (₹)</label>
                      <input
                        type="number"
                        className="form-input"
                        min="0"
                        step="any"
                        value={policyForm.credit_limit}
                        onChange={e => setPolicyForm({ ...policyForm, credit_limit: e.target.value })}
                      />
                    </div>
                  </div>

                  <div className="form-group mb-3">
                    <label className="form-label">Stock Count Visibility</label>
                    <CustomSelect
                      className="form-select"
                      value={policyForm.stock_visibility}
                      onChange={e => setPolicyForm({ ...policyForm, stock_visibility: e.target.value })}
                    >
                      <option value="exact">Exact (show exact stock, e.g., "43 units")</option>
                      <option value="band">Band (show "In Stock" / "Low Stock" / "Out of Stock")</option>
                      <option value="hidden">Hidden (completely hide stock counts)</option>
                    </CustomSelect>
                  </div>

                  <div className="form-group">
                    <label className="form-label">Allowed Category Filter</label>
                    <input
                      className="form-input"
                      placeholder="e.g. Medicines (leave blank for entire catalog)"
                      value={policyForm.catalog_category}
                      onChange={e => setPolicyForm({ ...policyForm, catalog_category: e.target.value })}
                    />
                    <small style={{ color: 'var(--text-muted)', fontSize: '0.75rem', display: 'block', marginTop: 4 }}>
                      Restrict this customer to viewing only products from a specific category.
                    </small>
                  </div>
                </div>
                <div className="modal-footer">
                  <button type="button" className="btn btn-secondary" onClick={() => setShowPolicyModal(false)}>Cancel</button>
                  <button type="submit" className="btn btn-primary" disabled={policySubmitting}>
                    {policySubmitting ? 'Saving...' : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><CheckIcon size={14} /> Save Policies</span>}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* Revoke Confirmation Modal */}
        {showRevokeModal && connectionToRevoke && (
          <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowRevokeModal(false)}>
            <div className="modal">
              <div className="modal-header" style={{ borderBottomColor: 'rgba(239, 68, 68, 0.2)' }}>
                <span className="modal-title" style={{ color: 'var(--danger)' }}><AlertIcon size={16} style={{ color: 'var(--danger)', marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Revoke Partnership?</span>
                <button className="btn btn-ghost btn-icon" onClick={() => setShowRevokeModal(false)} aria-label="Close"><CloseIcon size={16} /></button>
              </div>
              <div className="modal-body">
                <p style={{ marginBottom: 12 }}>
                  Are you sure you want to disconnect from <strong>
                    {activeTab === 'Customers' ? connectionToRevoke.buyer_name : connectionToRevoke.seller_name}
                  </strong>?
                </p>
                <div style={{
                  background: 'var(--danger-dim)',
                  border: '1px solid rgba(239, 68, 68, 0.2)',
                  padding: '10px 12px',
                  borderRadius: 'var(--radius-md)',
                  color: 'var(--text-primary)',
                  fontSize: '0.82rem',
                  lineHeight: '1.4'
                }}>
                  <strong>What happens next:</strong>
                  <ul style={{ marginLeft: 16, marginTop: 4 }}>
                    <li>All pricing agreements and discount overrides are immediately terminated.</li>
                    <li>Catalog access is revoked; no new orders can be placed.</li>
                    <li>Existing historical B2B orders will remain visible in the history logs.</li>
                  </ul>
                </div>
              </div>
              <div className="modal-footer">
                <button className="btn btn-secondary" onClick={() => setShowRevokeModal(false)}>Cancel</button>
                <button className="btn btn-primary" style={{ backgroundColor: 'var(--danger)', borderColor: 'var(--danger)' }} onClick={handleRevoke} disabled={revoking}>
                  {revoking ? 'Disconnecting...' : 'Yes, Disconnect'}
                </button>
              </div>
            </div>
          </div>
        )}

      </div>
    </AppLayout>
  )
}
