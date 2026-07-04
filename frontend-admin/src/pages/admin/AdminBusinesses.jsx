import { useState, useEffect } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { useDialog } from '../../contexts/DialogContext'
import { API_BASE } from '../../config'
import { Section } from '../../components/ui'
import { Icon } from '../../components/icons'

export default function AdminBusinesses() {
  const { authFetch, adminUser } = useAuth()
  const { showAlert, showConfirm, showError } = useDialog()
  const [businesses, setBusinesses] = useState([])
  const [loading, setLoading] = useState(true)

  // Modals visibility
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showEditModal, setShowEditModal] = useState(false)
  const [showLimitsModal, setShowLimitsModal] = useState(false)
  const [showInspectModal, setShowInspectModal] = useState(false)

  // Create form states
  const [createForm, setCreateForm] = useState({ business_name: '', username: '', password: '' })
  const [createError, setCreateError] = useState('')

  // Edit form states
  const [editForm, setEditForm] = useState({ id: null, business_name: '', username: '', password: '' })
  const [editError, setEditError] = useState('')

  // Rate limits form states
  const [limitsForm, setLimitsForm] = useState({ id: null, businessName: '', rpm: 10, rpd: 500, tokens: 50000, complex: 20, active: true })
  const [limitsError, setLimitsError] = useState('')

  // Inspector details states
  const [inspectDetails, setInspectDetails] = useState(null)
  const [inspectLoading, setInspectLoading] = useState(false)

  // Subscription modal states (Phase B.5)
  const [showPlanModal, setShowPlanModal] = useState(false)
  const [planForm, setPlanForm] = useState({ id: null, businessName: '', plan: 'free', status: 'active', expires_at: '', note: '' })
  const [planError, setPlanError] = useState('')

  // Type-the-name wipe confirmation (danger guard)
  const [wipeTarget, setWipeTarget] = useState(null)   // { id, name }
  const [wipeTyped, setWipeTyped] = useState('')

  useEffect(() => {
    loadBusinesses()
  }, [])

  async function loadBusinesses() {
    setLoading(true)
    try {
      const res = await authFetch(`${API_BASE}/admin/businesses`)
      if (!res.ok) throw new Error('Failed to load merchant directory')
      const data = await res.json()
      setBusinesses(data)
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  // --- WIPE USER DATA (type-the-name confirmation) ---
  function handleWipeUser(id, name) {
    setWipeTyped('')
    setWipeTarget({ id, name })
  }

  async function confirmWipe() {
    if (!wipeTarget || wipeTyped !== wipeTarget.name) return
    const { id, name } = wipeTarget
    setWipeTarget(null)
    try {
      const res = await authFetch(`${API_BASE}/admin/wipe-user-data/${id}`, { method: 'DELETE' })
      const data = await res.json()
      await showAlert(data.message || `Wiped all data for ${name} successfully.`)
      loadBusinesses()
    } catch (err) {
      await showError(err)
    }
  }

  // --- SUBSCRIPTION (Phase B.5) ---
  async function openPlanModal(b) {
    setPlanError('')
    setPlanForm({ id: b.id, businessName: b.business_name, plan: b.plan || 'free', status: b.plan_status || 'active', expires_at: b.plan_expires_at ? b.plan_expires_at.slice(0, 10) : '', note: '' })
    setShowPlanModal(true)
    try {
      const res = await authFetch(`${API_BASE}/admin/subscription/${b.id}`)
      if (res.ok) {
        const s = await res.json()
        setPlanForm(f => ({ ...f, plan: s.plan || 'free', status: s.status === 'none' ? 'active' : s.status, expires_at: s.expires_at ? String(s.expires_at).slice(0, 10) : '', note: s.note || '' }))
      }
    } catch (err) { console.error(err) }
  }

  async function handlePlanSubmit(e) {
    e.preventDefault()
    setPlanError('')
    const body = { plan: planForm.plan }
    if (planForm.plan !== 'free') {
      body.status = planForm.status || 'active'
      if (planForm.expires_at) body.expires_at = `${planForm.expires_at}T23:59:59`
      if (planForm.note) body.note = planForm.note
    }
    try {
      const res = await authFetch(`${API_BASE}/admin/subscription/${planForm.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })
      if (!res.ok) {
        const errData = await res.json()
        throw new Error(errData.detail || 'Failed to save subscription')
      }
      setShowPlanModal(false)
      loadBusinesses()
    } catch (err) {
      setPlanError(err.message)
    }
  }

  // --- FLUSH MERCH CACHE ---
  async function handleFlushCache(id, name) {
    if (!(await showConfirm(`Flush cached context and response lookups for ${name}?`))) return
    try {
      const res = await authFetch(`${API_BASE}/admin/flush-cache/${id}`, { method: 'POST' })
      const data = await res.json()
      await showAlert(data.message || `Flushed cache for ${name} successfully.`)
    } catch (err) {
      await showError(err)
    }
  }

  // --- CREATE MERCHANT ---
  async function handleCreateSubmit(e) {
    e.preventDefault()
    setCreateError('')
    try {
      const res = await authFetch(`${API_BASE}/admin/create-user`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(createForm)
      })
      if (!res.ok) {
        const errData = await res.json()
        throw new Error(errData.detail || 'Failed to create merchant user')
      }
      setShowCreateModal(false)
      setCreateForm({ business_name: '', username: '', password: '' })
      loadBusinesses()
    } catch (err) {
      setCreateError(err.message)
    }
  }

  // --- EDIT MERCHANT ---
  function openEditModal(b) {
    setEditForm({ id: b.id, business_name: b.business_name, username: b.username, password: '' })
    setEditError('')
    setShowEditModal(true)
  }

  async function handleEditSubmit(e) {
    e.preventDefault()
    setEditError('')
    const body = { username: editForm.username, business_name: editForm.business_name }
    if (editForm.password) body.password = editForm.password

    try {
      const res = await authFetch(`${API_BASE}/admin/update-user/${editForm.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })
      if (!res.ok) {
        const errData = await res.json()
        throw new Error(errData.detail || 'Failed to update merchant user')
      }
      setShowEditModal(false)
      loadBusinesses()
    } catch (err) {
      setEditError(err.message)
    }
  }

  // --- RATE LIMITS ---
  async function openLimitsModal(b) {
    setLimitsError('')
    setLimitsForm({
      id: b.id,
      businessName: b.business_name,
      rpm: 10,
      rpd: 500,
      tokens: 50000,
      complex: 20,
      active: true
    })
    setShowLimitsModal(true)

    try {
      const res = await authFetch(`${API_BASE}/admin/rate-limits/${b.id}`)
      if (res.ok) {
        const data = await res.json()
        const cfg = data.configured ? data : data.defaults
        setLimitsForm({
          id: b.id,
          businessName: b.business_name,
          rpm: cfg.requests_per_minute,
          rpd: cfg.requests_per_day,
          tokens: cfg.max_tokens_per_day,
          complex: cfg.complex_per_day,
          active: cfg.active !== false
        })
      }
    } catch (err) {
      console.error(err)
    }
  }

  async function handleLimitsSubmit(e) {
    e.preventDefault()
    setLimitsError('')
    const body = {
      requests_per_minute: parseInt(limitsForm.rpm),
      requests_per_day: parseInt(limitsForm.rpd),
      max_tokens_per_day: parseInt(limitsForm.tokens),
      complex_per_day: parseInt(limitsForm.complex),
      active: limitsForm.active
    }
    try {
      const res = await authFetch(`${API_BASE}/admin/rate-limits/${limitsForm.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })
      if (!res.ok) {
        const errData = await res.json()
        throw new Error(errData.detail || 'Failed to save rate limits')
      }
      setShowLimitsModal(false)
    } catch (err) {
      setLimitsError(err.message)
    }
  }

  // --- INSPECTOR ---
  async function openInspectModal(b) {
    setInspectDetails(null)
    setInspectLoading(true)
    setShowInspectModal(true)
    try {
      const res = await authFetch(`${API_BASE}/admin/business-details/${b.id}`)
      if (!res.ok) throw new Error('Could not inspect business explorer data')
      const data = await res.json()
      setInspectDetails(data)
    } catch (err) {
      await showError(err)
      setShowInspectModal(false)
    } finally {
      setInspectLoading(false)
    }
  }

  return (
    <div className="admin-main" style={{ margin: 0, padding: 0 }}>
      {/* Header */}
      <div className="admin-header-row" style={{ borderBottom: '1.5px solid var(--border-color)', paddingBottom: 20 }}>
        <div className="admin-title-group">
          <h1>✦ REGISTERED ENTERPRISES</h1>
          <p>Manage sandbox accounts, directory credentials, data wipe, and rate limits</p>
        </div>
        <button className="btn-flush" onClick={() => setShowCreateModal(true)} style={{ padding: '10px 16px', fontSize: 13 }}>
          + Add New Merchant
        </button>
      </div>

      {/* Directory Table */}
      <Section
        title="Enterprise Business Directory"
        icon={<Icon name="database" size={16} />}
        collapsible
        noPad
        style={{ marginTop: 24 }}
      >
        {loading ? (
          <div className="vskel" style={{ padding: 20 }}></div>
        ) : (
          <div className="admin-table-wrap" style={{ overflowX: 'auto', width: '100%' }}>
            <table className="admin-table" style={{ width: '100%', marginTop: 12 }}>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>BizID</th>
                  <th>Business Name</th>
                  <th>Username</th>
                  <th>Mode</th>
                  <th>Sync</th>
                  <th>Plan</th>
                  <th>Total Invoices</th>
                  <th>Tracked Revenue</th>
                  <th>Inventory Stock Count</th>
                  <th>Upload History</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {businesses.length === 0 ? (
                  <tr>
                    <td colSpan="12" style={{ textAlign: 'center', color: 'var(--secondary-text)', padding: 30 }}>
                      No enterprise businesses registered yet.
                    </td>
                  </tr>
                ) : (
                  businesses.map(b => (
                    <tr key={b.id}>
                      <td style={{ fontFamily: "'Geist Mono',monospace", opacity: 0.75 }}>{b.id}</td>
                      <td style={{ fontFamily: "'Geist Mono',monospace", fontSize: 11, opacity: 0.85 }} title="Stable identity across cloud & local databases">{b.bizid || '—'}</td>
                      <td style={{ fontWeight: 600, color: 'var(--accent-color)' }}>{b.business_name}</td>
                      <td>{b.username}</td>
                      <td><span className="tag">{b.hosting_mode || 'local'}</span></td>
                      <td>
                        <span title={b.last_sync_at ? `Last sync ${b.last_sync_at}${b.sync_queue_depth ? ` · ${b.sync_queue_depth} queued` : ''}` : 'Never synced'} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12 }}>
                          <span style={{ width: 8, height: 8, borderRadius: '50%', background: b.online_last_24h ? '#3a9a5c' : 'var(--border-color)', display: 'inline-block' }}></span>
                          {b.online_last_24h ? '24h' : (b.last_sync_at ? 'stale' : '—')}
                          {b.sync_queue_depth > 0 && <span style={{ color: 'var(--accent-color)', fontWeight: 600 }}>+{b.sync_queue_depth}</span>}
                        </span>
                      </td>
                      <td>
                        <span className="tag" style={{
                          background: b.plan === 'pro' ? 'rgba(58,154,92,0.12)' : 'var(--accent-soft)',
                          color: b.plan === 'pro' ? '#3a9a5c' : 'var(--secondary-text)',
                          fontWeight: 700, textTransform: 'uppercase', fontSize: 10
                        }}>{b.plan || 'free'}</span>
                      </td>
                      <td>{b.invoice_count}</td>
                      <td style={{ fontFamily: "'Crimson Pro',serif", fontSize: 16, fontWeight: 600 }}>
                        ₹{b.total_revenue.toLocaleString('en-IN')}
                      </td>
                      <td>{b.inventory_count} items</td>
                      <td>{b.upload_count} datasets</td>
                      <td>
                        <div style={{ display: 'flex', gap: 6 }}>
                          <button className="btn-flush" onClick={() => openInspectModal(b)}>Inspect</button>
                          <button className="btn-flush" onClick={() => openEditModal(b)}>Edit</button>
                          <button className="btn-flush" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }} onClick={() => openLimitsModal(b)}><Icon name="settings" size={12} /> Limits</button>
                          <button className="btn-flush" onClick={() => openPlanModal(b)}>Plan</button>
                          <button className="btn-flush" onClick={() => handleFlushCache(b.id, b.business_name)}>Flush Cache</button>
                          <button className="btn-wipe-row" onClick={() => handleWipeUser(b.id, b.business_name)}>Wipe Data</button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {/* CREATE MERCHANT MODAL */}
      {showCreateModal && (
        <div className="custom-modal-overlay">
          <div className="custom-modal-card admin-modal-card" style={{ maxWidth: 450 }}>
            <div className="custom-modal-title">Register New Merchant Sandbox</div>
            <form onSubmit={handleCreateSubmit} className="auth-form" style={{ marginTop: 16 }}>
              <div className="form-group">
                <label>Business Name</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Medicare Pharmacy"
                  value={createForm.business_name}
                  onChange={e => setCreateForm(f => ({ ...f, business_name: e.target.value }))}
                />
              </div>
              <div className="form-group">
                <label>Username</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. medicare"
                  value={createForm.username}
                  onChange={e => setCreateForm(f => ({ ...f, username: e.target.value }))}
                />
              </div>
              <div className="form-group">
                <label>Password</label>
                <input
                  type="password"
                  required
                  placeholder="••••••••"
                  value={createForm.password}
                  onChange={e => setCreateForm(f => ({ ...f, password: e.target.value }))}
                />
              </div>
              {createError && <div className="auth-error">{createError}</div>}
              <div className="custom-modal-actions" style={{ marginTop: 24 }}>
                <button type="button" className="custom-modal-btn cancel-btn" onClick={() => setShowCreateModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="custom-modal-btn confirm-btn" style={{ background: 'var(--accent-color)' }}>
                  Create Merchant
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* EDIT MERCHANT MODAL */}
      {showEditModal && (
        <div className="custom-modal-overlay">
          <div className="custom-modal-card admin-modal-card" style={{ maxWidth: 450 }}>
            <div className="custom-modal-title">Edit Merchant Credentials</div>
            <form onSubmit={handleEditSubmit} className="auth-form" style={{ marginTop: 16 }}>
              <div className="form-group">
                <label>Business Name</label>
                <input
                  type="text"
                  required
                  value={editForm.business_name}
                  onChange={e => setEditForm(f => ({ ...f, business_name: e.target.value }))}
                />
              </div>
              <div className="form-group">
                <label>Username</label>
                <input
                  type="text"
                  required
                  value={editForm.username}
                  onChange={e => setEditForm(f => ({ ...f, username: e.target.value }))}
                />
              </div>
              <div className="form-group">
                <label>New Password (leave blank to keep current)</label>
                <input
                  type="password"
                  placeholder="••••••••"
                  value={editForm.password}
                  onChange={e => setEditForm(f => ({ ...f, password: e.target.value }))}
                />
              </div>
              {editError && <div className="auth-error">{editError}</div>}
              <div className="custom-modal-actions" style={{ marginTop: 24 }}>
                <button type="button" className="custom-modal-btn cancel-btn" onClick={() => setShowEditModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="custom-modal-btn confirm-btn" style={{ background: 'var(--accent-color)' }}>
                  Save Credentials
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* RATE LIMITS CONFIG MODAL */}
      {showLimitsModal && (
        <div className="custom-modal-overlay">
          <div className="custom-modal-card admin-modal-card" style={{ maxWidth: 480 }}>
            <div className="custom-modal-title">Rate Limits: {limitsForm.businessName}</div>
            <form onSubmit={handleLimitsSubmit} className="auth-form" style={{ marginTop: 16 }}>
              <div className="admin-form-grid">
                <div className="form-group">
                  <label>Requests Per Minute (RPM)</label>
                  <input
                    type="number"
                    min="1"
                    value={limitsForm.rpm}
                    onChange={e => setLimitsForm(f => ({ ...f, rpm: e.target.value }))}
                  />
                </div>
                <div className="form-group">
                  <label>Requests Per Day (RPD)</label>
                  <input
                    type="number"
                    min="1"
                    value={limitsForm.rpd}
                    onChange={e => setLimitsForm(f => ({ ...f, rpd: e.target.value }))}
                  />
                </div>
              </div>
              <div className="admin-form-grid" style={{ marginTop: 8 }}>
                <div className="form-group">
                  <label>Max Tokens Per Day</label>
                  <input
                    type="number"
                    min="1000"
                    value={limitsForm.tokens}
                    onChange={e => setLimitsForm(f => ({ ...f, tokens: e.target.value }))}
                  />
                </div>
                <div className="form-group">
                  <label>AI_COMPLEX Runs Per Day</label>
                  <input
                    type="number"
                    min="1"
                    value={limitsForm.complex}
                    onChange={e => setLimitsForm(f => ({ ...f, complex: e.target.value }))}
                  />
                </div>
              </div>
              <div className="form-group" style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
                <input
                  id="limits-active"
                  type="checkbox"
                  checked={limitsForm.active}
                  onChange={e => setLimitsForm(f => ({ ...f, active: e.target.checked }))}
                  style={{ width: 'auto' }}
                />
                <label htmlFor="limits-active" style={{ textTransform: 'none', margin: 0, cursor: 'pointer' }}>
                  Enable Rate Limiting for this merchant
                </label>
              </div>
              {limitsError && <div className="auth-error">{limitsError}</div>}
              <div className="custom-modal-actions" style={{ marginTop: 24 }}>
                <button type="button" className="custom-modal-btn cancel-btn" onClick={() => setShowLimitsModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="custom-modal-btn confirm-btn" style={{ background: 'var(--accent-color)' }}>
                  Save Limits
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* SUBSCRIPTION / PLAN MODAL (Phase B.5) */}
      {showPlanModal && (
        <div className="custom-modal-overlay">
          <div className="custom-modal-card admin-modal-card" style={{ maxWidth: 460 }}>
            <div className="custom-modal-title">Subscription: {planForm.businessName}</div>
            <form onSubmit={handlePlanSubmit} className="auth-form" style={{ marginTop: 16 }}>
              <div className="admin-form-grid">
                <div className="form-group">
                  <label>Plan</label>
                  <select value={planForm.plan} onChange={e => setPlanForm(f => ({ ...f, plan: e.target.value }))}>
                    <option value="free">Free (revoke)</option>
                    <option value="pro">Pro</option>
                  </select>
                </div>
                <div className="form-group">
                  <label>Status</label>
                  <select value={planForm.status} disabled={planForm.plan === 'free'} onChange={e => setPlanForm(f => ({ ...f, status: e.target.value }))}>
                    <option value="active">Active</option>
                    <option value="trial">Trial</option>
                    <option value="suspended">Suspended</option>
                  </select>
                </div>
              </div>
              <div className="form-group" style={{ marginTop: 8 }}>
                <label>Expires On (blank = no expiry)</label>
                <input type="date" value={planForm.expires_at} disabled={planForm.plan === 'free'}
                       onChange={e => setPlanForm(f => ({ ...f, expires_at: e.target.value }))} />
              </div>
              <div className="form-group" style={{ marginTop: 8 }}>
                <label>Note (internal)</label>
                <input type="text" placeholder="e.g. field-testing grant" value={planForm.note} disabled={planForm.plan === 'free'}
                       onChange={e => setPlanForm(f => ({ ...f, note: e.target.value }))} />
              </div>
              {planError && <div className="auth-error">{planError}</div>}
              <div className="custom-modal-actions" style={{ marginTop: 24 }}>
                <button type="button" className="custom-modal-btn cancel-btn" onClick={() => setShowPlanModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="custom-modal-btn confirm-btn" style={{ background: 'var(--accent-color)' }}>
                  {planForm.plan === 'free' ? 'Revoke Plan' : 'Save Plan'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* WIPE CONFIRMATION MODAL (type-the-name guard) */}
      {wipeTarget && (
        <div className="custom-modal-overlay">
          <div className="custom-modal-card admin-modal-card" style={{ maxWidth: 460 }}>
            <div className="custom-modal-title" style={{ color: 'var(--accent-color)' }}>⚠ Permanently wipe {wipeTarget.name}?</div>
            <p style={{ fontSize: 13, color: 'var(--secondary-text)', marginTop: 12, lineHeight: 1.5 }}>
              This deletes the account and ALL its business data — invoices, inventory,
              payments, uploads, embeddings and chat history. This cannot be undone.
              Type the business name <strong style={{ color: 'var(--text-color)' }}>{wipeTarget.name}</strong> to confirm.
            </p>
            <div className="form-group" style={{ marginTop: 12 }}>
              <input
                type="text"
                autoFocus
                placeholder="Type the business name exactly"
                value={wipeTyped}
                onChange={e => setWipeTyped(e.target.value)}
              />
            </div>
            <div className="custom-modal-actions" style={{ marginTop: 20 }}>
              <button type="button" className="custom-modal-btn cancel-btn" onClick={() => setWipeTarget(null)}>
                Cancel
              </button>
              <button
                type="button"
                className="custom-modal-btn confirm-btn"
                disabled={wipeTyped !== wipeTarget.name}
                onClick={confirmWipe}
                style={{ background: wipeTyped === wipeTarget.name ? '#c0392b' : 'var(--border-color)', cursor: wipeTyped === wipeTarget.name ? 'pointer' : 'not-allowed' }}
              >
                Wipe Everything
              </button>
            </div>
          </div>
        </div>
      )}

      {/* INSPECTOR DETAILS MODAL */}
      {showInspectModal && (
        <div className="custom-modal-overlay">
          <div className="custom-modal-card admin-inspect-modal" style={{ maxWidth: 800, width: '90%', overflowY: 'auto' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <div className="custom-modal-title" style={{ fontSize: 22, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  <Icon name="search" size={20} /> Inspect: {inspectDetails?.business_name || 'Loading...'}
                </div>
                <div style={{ fontSize: 12, color: 'var(--secondary-text)', marginTop: 4 }}>
                  User ID: {inspectDetails?.id} | Username: {inspectDetails?.username}
                </div>
              </div>
              <button
                onClick={() => setShowInspectModal(false)}
                style={{ background: 'transparent', border: 'none', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', color: 'var(--secondary-text)' }}
                aria-label="Close"
              >
                <Icon name="x" size={20} />
              </button>
            </div>

            {inspectLoading || !inspectDetails ? (
              <div className="vskel" style={{ marginTop: 24 }}></div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16, marginTop: 24 }}>
                {/* Uploaded datasets */}
                <details className="tree-node">
                  <summary className="tree-summary" style={{ display: 'flex', alignItems: 'center', gap: 6 }}><Icon name="package" size={14} /> Uploaded Datasets ({inspectDetails.uploads.length})</summary>
                  <div className="tree-content">
                    {inspectDetails.uploads.length === 0 ? (
                      <div style={{ color: 'var(--secondary-text)', padding: '10px 0' }}>No datasets uploaded.</div>
                    ) : (
                      <table className="tree-table">
                        <thead>
                          <tr>
                            <th>ID</th>
                            <th>Filename</th>
                            <th>Type</th>
                            <th>Row Count</th>
                            <th>Uploaded Time</th>
                          </tr>
                        </thead>
                        <tbody>
                          {inspectDetails.uploads.map((u, i) => (
                            <tr key={i}>
                              <td style={{ fontFamily: 'monospace' }}>{u.id}</td>
                              <td style={{ fontWeight: 600, color: 'var(--accent-color)' }}>{u.filename}</td>
                              <td><span className="tag">{u.file_type}</span></td>
                              <td>{u.rows_count} rows</td>
                              <td>{u.upload_time}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                </details>

                {/* Invoices */}
                <details className="tree-node">
                  <summary className="tree-summary" style={{ display: 'flex', alignItems: 'center', gap: 6 }}><Icon name="file" size={14} /> Invoices & Sales ({inspectDetails.invoices.length})</summary>
                  <div className="tree-content">
                    {inspectDetails.invoices.length === 0 ? (
                      <div style={{ color: 'var(--secondary-text)', padding: '10px 0' }}>No invoices present.</div>
                    ) : (
                      <table className="tree-table">
                        <thead>
                          <tr>
                            <th>Invoice ID</th>
                            <th>Customer</th>
                            <th>Product</th>
                            <th>Amount</th>
                            <th>Status</th>
                            <th>Due Date</th>
                          </tr>
                        </thead>
                        <tbody>
                          {inspectDetails.invoices.slice(0, 50).map((inv, i) => (
                            <tr key={i}>
                              <td style={{ fontFamily: 'monospace' }}>{inv.invoice_id || 'N/A'}</td>
                              <td style={{ fontWeight: 500 }}>{inv.customer}</td>
                              <td>{inv.product}</td>
                              <td style={{ fontWeight: 600 }}>₹{inv.amount.toLocaleString('en-IN')}</td>
                              <td>
                                <span className="tag" style={{
                                  background: inv.status === 'Paid' ? 'rgba(58,154,92,0.12)' : 'rgba(201,100,66,0.12)',
                                  color: inv.status === 'Paid' ? '#3a9a5c' : 'var(--accent-color)'
                                }}>
                                  {inv.status}
                                </span>
                              </td>
                              <td>{inv.due_date || 'N/A'}</td>
                            </tr>
                          ))}
                          {inspectDetails.invoices.length > 50 && (
                            <tr>
                              <td colSpan="6" style={{ textAlign: 'center', color: 'var(--secondary-text)', padding: 8 }}>
                                Showing first 50 of {inspectDetails.invoices.length} invoices.
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    )}
                  </div>
                </details>

                {/* Inventory */}
                <details className="tree-node">
                  <summary className="tree-summary" style={{ display: 'flex', alignItems: 'center', gap: 6 }}><Icon name="package" size={14} /> Inventory Stock ({inspectDetails.inventory.length} items)</summary>
                  <div className="tree-content">
                    {inspectDetails.inventory.length === 0 ? (
                      <div style={{ color: 'var(--secondary-text)', padding: '10px 0' }}>No inventory records.</div>
                    ) : (
                      <table className="tree-table">
                        <thead>
                          <tr>
                            <th>Product Name</th>
                            <th>Stock</th>
                            <th>Expiry Date</th>
                            <th>Supplier</th>
                          </tr>
                        </thead>
                        <tbody>
                          {inspectDetails.inventory.slice(0, 50).map((item, i) => (
                            <tr key={i}>
                              <td style={{ fontWeight: 600, color: 'var(--accent-color)' }}>{item.product_name}</td>
                              <td>{item.stock} items</td>
                              <td>{item.expiry_date || 'N/A'}</td>
                              <td>{item.supplier || 'N/A'}</td>
                            </tr>
                          ))}
                          {inspectDetails.inventory.length > 50 && (
                            <tr>
                              <td colSpan="4" style={{ textAlign: 'center', color: 'var(--secondary-text)', padding: 8 }}>
                                Showing first 50 of {inspectDetails.inventory.length} products.
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    )}
                  </div>
                </details>

                {/* Payments */}
                <details className="tree-node">
                  <summary className="tree-summary" style={{ display: 'flex', alignItems: 'center', gap: 6 }}><Icon name="card" size={14} /> Logged Payments & Dues ({inspectDetails.payments.length})</summary>
                  <div className="tree-content">
                    {inspectDetails.payments.length === 0 ? (
                      <div style={{ color: 'var(--secondary-text)', padding: '10px 0' }}>No payment entries.</div>
                    ) : (
                      <table className="tree-table">
                        <thead>
                          <tr>
                            <th>Customer</th>
                            <th>Amount</th>
                            <th>Due Date</th>
                            <th>Paid Status</th>
                          </tr>
                        </thead>
                        <tbody>
                          {inspectDetails.payments.slice(0, 50).map((p, i) => (
                            <tr key={i}>
                              <td style={{ fontWeight: 500 }}>{p.customer}</td>
                              <td style={{ fontWeight: 600 }}>₹{p.amount.toLocaleString('en-IN')}</td>
                              <td>{p.due_date || 'N/A'}</td>
                              <td>
                                <span className="tag" style={{
                                  background: p.paid === 'Yes' ? 'rgba(58,154,92,0.12)' : 'rgba(201,100,66,0.12)',
                                  color: p.paid === 'Yes' ? '#3a9a5c' : 'var(--accent-color)'
                                }}>
                                  {p.paid === 'Yes' ? 'Paid' : 'Unpaid'}
                                </span>
                              </td>
                            </tr>
                          ))}
                          {inspectDetails.payments.length > 50 && (
                            <tr>
                              <td colSpan="4" style={{ textAlign: 'center', color: 'var(--secondary-text)', padding: 8 }}>
                                Showing first 50 of {inspectDetails.payments.length} payments.
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    )}
                  </div>
                </details>

                {/* Chat History */}
                <details className="tree-node">
                  <summary className="tree-summary" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <Icon name="chat" size={14} /> Chat Threads History ({Object.keys(inspectDetails.chat_history.reduce((acc, m) => {
                      const sid = m.session_id || 'default'
                      acc[sid] = true
                      return acc
                    }, {})).length} sessions)
                  </summary>
                  <div className="tree-content" style={{ paddingTop: 14, maxHeight: 450, overflowY: 'auto' }}>
                    {(() => {
                      const insSessions = {}
                      inspectDetails.chat_history.forEach(m => {
                        const sid = m.session_id || 'default'
                        if (!insSessions[sid]) {
                          insSessions[sid] = {
                            title: m.session_title || 'Previous Chat Session',
                            messages: []
                          }
                        }
                        insSessions[sid].messages.push(m)
                      })
                      const insSessionKeys = Object.keys(insSessions)

                      if (insSessionKeys.length === 0) {
                        return <div style={{ color: 'var(--secondary-text)', padding: '10px 0' }}>No chat history threads found.</div>
                      }

                      return insSessionKeys.map(sid => {
                        const s = insSessions[sid]
                        const sortedMsgs = [...s.messages].reverse()
                        return (
                          <details key={sid} style={{ marginBottom: 12, border: '1px dashed var(--border-color)', borderRadius: 8, padding: '6px 12px', background: 'rgba(255,255,255,0.2)' }}>
                            <summary style={{ fontWeight: 600, fontSize: 13, padding: '6px 0', cursor: 'pointer', color: 'var(--text-color)' }}>
                              {s.title}
                            </summary>
                            <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
                              {sortedMsgs.map((msg, idx) => (
                                <div key={idx} className={`chat-tree-bubble ${msg.role}`}>
                                  <span style={{
                                    fontWeight: 600,
                                    fontSize: 10,
                                    textTransform: 'uppercase',
                                    color: msg.role === 'user' ? 'var(--accent-color)' : '#3a9a5c',
                                    display: 'block',
                                    marginBottom: 2
                                  }}>{msg.role}</span>
                                  <span>{msg.content}</span>
                                </div>
                              ))}
                            </div>
                          </details>
                        )
                      })
                    })()}
                  </div>
                </details>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
