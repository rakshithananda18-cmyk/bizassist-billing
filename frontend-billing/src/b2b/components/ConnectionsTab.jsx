// ============================================================================
// b2b/components/ConnectionsTab.jsx — the "Connections" tab.
// ----------------------------------------------------------------------------
// Three sub-views over one connection graph:
//
//   Approved  — live links, split into My Customers / My Suppliers
//   Pending   — requests waiting on ME to approve or decline   ← the inbox
//   Sent      — requests I raised, waiting on THEM (withdrawable)
//
// The Pending inbox is the security fix made visible: a BizID request no longer
// grants anyone access to your catalogue, pricing or stock — it lands here and
// waits for you. It's also the growth loop: "3 businesses want to connect" is a
// far better prompt than an empty supplier list.
// ============================================================================
import React, { useEffect, useState } from 'react'
import {
  AlertIcon, BillsIcon, CartIcon, CheckIcon, CloseIcon, ConnectionIcon,
  HandshakeIcon, SettingsIcon, ShieldIcon,
} from '../../components/Icons'
import CustomSelect from '../../components/common/CustomSelect'

const fmt = (n) =>
  n != null ? `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '—'

const since = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}

// ── Request card (used by both Pending and Sent) ─────────────────────────────
function RequestCard({ conn, mine, busy, onApprove, onReject, onCancel }) {
  // `mine` = I raised this request, so I can only withdraw it.
  const role = conn.my_role === 'seller' ? 'as your customer' : 'as your supplier'
  return (
    <div className="b2b-request">
      <div className="b2b-request-body">
        <div className="b2b-request-name">
          {conn.counterparty_name || 'Unknown business'}
          <span className="td-mono b2b-request-bizid">{conn.counterparty_bizid}</span>
        </div>
        <div className="b2b-request-role">
          {mine
            ? <>You asked to connect with them {role.replace('as your', 'as their').replace('customer', 'supplier').replace('supplier', 'customer')} · sent {since(conn.created_at)}</>
            : <>Wants to connect {role} · requested {since(conn.created_at)}</>}
        </div>
        {conn.request_message && (
          <div className="b2b-request-msg">“{conn.request_message}”</div>
        )}
      </div>
      <div className="b2b-request-actions">
        {mine ? (
          <button className="btn btn-ghost btn-sm" style={{ color: 'var(--danger)' }} disabled={busy} onClick={() => onCancel(conn)}>
            Withdraw
          </button>
        ) : (
          <>
            <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => onApprove(conn)}>
              <CheckIcon size={13} /> Approve
            </button>
            <button className="btn btn-ghost btn-sm" style={{ color: 'var(--danger)' }} disabled={busy} onClick={() => onReject(conn)}>
              Decline
            </button>
          </>
        )}
      </div>
    </div>
  )
}

// ── Policy modal (seller-side pricing / visibility controls) ─────────────────
function PolicyModal({ conn, onClose, onSave, saving }) {
  const [form, setForm] = useState({
    price_tier: conn.price_tier || 'standard',
    discount_pct: conn.discount_pct || 0,
    credit_limit: conn.credit_limit || 0,
    stock_visibility: conn.stock_visibility || 'exact',
    catalog_category: conn.catalog_category || '',
  })

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <span className="modal-title">Policy · {conn.counterparty_name || conn.buyer_name}</span>
          <button className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close"><CloseIcon size={16} /></button>
        </div>
        <form onSubmit={e => { e.preventDefault(); onSave(conn, form) }}>
          <div className="modal-body">
            <div className="form-group mb-3">
              <label className="form-label">Price tier</label>
              <CustomSelect className="form-select" value={form.price_tier} onChange={e => setForm({ ...form, price_tier: e.target.value })}>
                <option value="standard">Standard retail price</option>
                <option value="wholesale">Wholesale price</option>
                <option value="distributor">Distributor price</option>
              </CustomSelect>
              <small style={{ color: 'var(--text-muted)', fontSize: '0.75rem', display: 'block', marginTop: 4 }}>
                Which catalogue price tier this customer sees.
              </small>
            </div>

            <div className="grid grid-2 gap-3 mb-3">
              <div className="form-group">
                <label className="form-label">Discount override (%)</label>
                <input type="number" className="form-input" min="0" max="100" step="0.01"
                  value={form.discount_pct} onChange={e => setForm({ ...form, discount_pct: e.target.value })} />
              </div>
              <div className="form-group">
                <label className="form-label">Credit limit (₹)</label>
                <input type="number" className="form-input" min="0" step="any"
                  value={form.credit_limit} onChange={e => setForm({ ...form, credit_limit: e.target.value })} />
              </div>
            </div>

            <div className="form-group mb-3">
              <label className="form-label">Stock visibility</label>
              <CustomSelect className="form-select" value={form.stock_visibility} onChange={e => setForm({ ...form, stock_visibility: e.target.value })}>
                <option value="exact">Exact — show real counts (e.g. “43 units”)</option>
                <option value="band">Band — In / Low / Out of stock only</option>
                <option value="hidden">Hidden — no stock information</option>
              </CustomSelect>
              <small style={{ color: 'var(--text-muted)', fontSize: '0.75rem', display: 'block', marginTop: 4 }}>
                Exact counts reveal how much inventory you hold. Use Band for customers who are also competitors.
              </small>
            </div>

            <div className="form-group">
              <label className="form-label">Category restriction</label>
              <input className="form-input" placeholder="e.g. Medicines (blank = whole catalogue)"
                value={form.catalog_category} onChange={e => setForm({ ...form, catalog_category: e.target.value })} />
            </div>
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? 'Saving…' : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><CheckIcon size={14} /> Save policy</span>}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Revoke confirmation ──────────────────────────────────────────────────────
function RevokeModal({ conn, onClose, onConfirm, busy }) {
  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header" style={{ borderBottomColor: 'rgba(239, 68, 68, 0.2)' }}>
          <span className="modal-title" style={{ color: 'var(--danger)' }}>
            <AlertIcon size={16} style={{ color: 'var(--danger)', marginRight: 6, verticalAlign: 'middle' }} />
            Revoke this connection?
          </span>
          <button className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close"><CloseIcon size={16} /></button>
        </div>
        <div className="modal-body">
          <p style={{ marginBottom: 12 }}>
            Disconnect from <strong>{conn.counterparty_name}</strong>?
          </p>
          <div style={{
            background: 'var(--danger-dim)', border: '1px solid rgba(239, 68, 68, 0.2)',
            padding: '10px 12px', borderRadius: 'var(--radius-md)',
            color: 'var(--text-primary)', fontSize: '0.82rem', lineHeight: 1.45,
          }}>
            <strong>What happens next</strong>
            <ul style={{ marginLeft: 16, marginTop: 4 }}>
              <li>Catalogue, pricing and stock visibility are cut off immediately.</li>
              <li>No new orders can be placed in either direction.</li>
              <li>Existing orders and history stay intact and visible.</li>
              <li>They cannot reconnect on their own — a new request comes back to you for approval.</li>
            </ul>
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" style={{ backgroundColor: 'var(--danger)', borderColor: 'var(--danger)' }}
            disabled={busy} onClick={() => onConfirm(conn)}>
            {busy ? 'Disconnecting…' : 'Yes, disconnect'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main tab ─────────────────────────────────────────────────────────────────
export default function ConnectionsTab({ myBizId, connections, onCopyBizId, copied }) {
  const {
    as_seller: customers, as_buyer: suppliers,
    incoming_requests: incoming, outgoing_requests: outgoing,
    loading, busyId,
    sendRequest, approve, reject, cancel, revoke, savePolicy, probe,
  } = connections

  const [activeTab, setActiveTab] = useState('suppliers')  // suppliers | customers | requests
  const [subStatus, setSubStatus] = useState('approved')  // approved | pending | sent

  const [bizid, setBizid] = useState('')
  const [connectAs, setConnectAs] = useState('buyer')
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)
  const [target, setTarget] = useState(undefined)
  const [probing, setProbing] = useState(false)
  const [policyFor, setPolicyFor] = useState(null)
  const [revokeFor, setRevokeFor] = useState(null)

  // Categorize requests by role
  const incomingSuppliers = incoming.filter(c => c.my_role !== 'seller')
  const incomingCustomers = incoming.filter(c => c.my_role === 'seller')
  const outgoingSuppliers = outgoing.filter(c => c.my_role !== 'seller')
  const outgoingCustomers = outgoing.filter(c => c.my_role === 'seller')

  // Check the BizID as soon as the user stops typing a plausible one.
  useEffect(() => {
    const code = bizid.trim()
    if (code.length < 6) { setTarget(undefined); return }
    let cancelled = false
    setProbing(true)
    const t = setTimeout(async () => {
      const found = await probe(code)
      if (!cancelled) { setTarget(found); setProbing(false) }
    }, 400)
    return () => { cancelled = true; clearTimeout(t); setProbing(false) }
  }, [bizid, probe])

  const submitRequest = async (e) => {
    e.preventDefault()
    if (!bizid.trim()) return
    setSending(true)
    const ok = await sendRequest({ bizid, role: connectAs, message })
    setSending(false)
    if (ok) { setBizid(''); setMessage(''); setTarget(undefined); setActiveTab(connectAs === 'buyer' ? 'suppliers' : 'customers'); setSubStatus('sent') }
  }

  return (
    <div className="b2b-connections">
      {/* ── Identity + Request Form: Single Unified Header Card ─────────── */}
      <div className="card b2b-header-card mb-4">
        {/* Left Column: My Network Address */}
        <div className="b2b-header-col">
          <div>
            <div className="b2b-card-eyebrow">
              <ConnectionIcon size={14} style={{ color: 'var(--accent)', marginRight: 6, verticalAlign: 'middle' }} />
              My network address
            </div>
            <div className="b2b-card-sub">
              Share your BizID so other businesses can request a connection. Requests require your explicit approval.
            </div>
          </div>
          <div className="b2b-bizid-box" style={{ marginTop: 12 }}>
            <span className="td-mono b2b-bizid">{myBizId || 'Loading…'}</span>
            {myBizId && (
              <button type="button" className="btn btn-secondary btn-sm" onClick={onCopyBizId} style={{ minWidth: 64, height: 32 }}>
                {copied ? 'Copied' : 'Copy'}
              </button>
            )}
          </div>
          <div className="b2b-card-hint" style={{ marginTop: 8 }}>
            <ShieldIcon size={12} style={{ marginRight: 4, verticalAlign: 'middle', color: 'var(--success)' }} />
            Safe to share — gives zero access until you approve.
          </div>
        </div>

        {/* Vertical Divider */}
        <div className="b2b-header-divider" />

        {/* Right Column: Request a Connection */}
        <div className="b2b-header-col">
          <div>
            <div className="b2b-card-eyebrow">
              <HandshakeIcon size={14} style={{ color: 'var(--accent)', marginRight: 6, verticalAlign: 'middle' }} />
              Request a connection
            </div>
            <div className="b2b-card-sub">
              Enter their BizID and select your relationship. They will receive a request to approve.
            </div>
          </div>
          <form onSubmit={submitRequest} style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 12 }}>
            <div style={{ display: 'flex', gap: 8 }}>
              <input
                className="form-input td-mono"
                style={{ textTransform: 'uppercase', letterSpacing: '0.5px', flex: 1, height: 34 }}
                placeholder="E.G. BA-ABC123"
                value={bizid}
                onChange={e => setBizid(e.target.value)}
                required
              />
              <CustomSelect className="form-select" value={connectAs} onChange={e => setConnectAs(e.target.value)} style={{ width: 170, height: 34 }}>
                <option value="buyer">They're my supplier</option>
                <option value="seller">They're my customer</option>
              </CustomSelect>
            </div>

            {/* Pre-flight verdict on the typed BizID */}
            {probing && bizid.trim().length >= 6 && (
              <div className="b2b-probe is-checking">Checking {bizid.trim().toUpperCase()}…</div>
            )}
            {!probing && target === null && (
              <div className="b2b-probe is-bad">
                No business found with BizID <b>{bizid.trim().toUpperCase()}</b>. Double-check the code.
              </div>
            )}
            {!probing && target && target.reachable === false && (
              <div className="b2b-probe is-warn">
                <b>{target.business_name}</b> is running in offline mode. Request will deliver when they sync.
              </div>
            )}
            {!probing && target && target.reachable !== false && (
              <div className="b2b-probe is-good">
                Found <b>{target.business_name}</b> — ready to receive your request.
              </div>
            )}

            <div style={{ display: 'flex', gap: 8 }}>
              <input
                className="form-input"
                style={{ fontSize: '0.82rem', flex: 1, height: 34 }}
                placeholder="Optional note — e.g. “We buy paint monthly”"
                maxLength={500}
                value={message}
                onChange={e => setMessage(e.target.value)}
              />
              <button type="submit" className="btn btn-primary btn-sm" style={{ height: 34, flexShrink: 0, padding: '0 14px' }} disabled={sending || !bizid.trim()}>
                {sending ? 'Sending…' : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><ConnectionIcon size={14} /> Send request</span>}
              </button>
            </div>
          </form>
        </div>
      </div>

      {/* ── Main Party Tabs: My Suppliers · My Customers ──── */}
      <div className="tabs page-subbar mb-3">
        <button
          className={`tab${activeTab === 'suppliers' ? ' active' : ''}`}
          onClick={() => { setActiveTab('suppliers'); setSubStatus('approved') }}
        >
          <CartIcon size={14} style={{ marginRight: 6, verticalAlign: 'middle' }} />
          My Suppliers <span className="b2b-tab-count">{suppliers.length}</span>
          {incomingSuppliers.length > 0 && (
            <span className="b2b-tab-count is-alert" style={{ marginLeft: 6 }}>
              {incomingSuppliers.length} pending
            </span>
          )}
        </button>

        <button
          className={`tab${activeTab === 'customers' ? ' active' : ''}`}
          onClick={() => { setActiveTab('customers'); setSubStatus('approved') }}
        >
          <ShieldIcon size={14} style={{ marginRight: 6, verticalAlign: 'middle' }} />
          My Customers <span className="b2b-tab-count">{customers.length}</span>
          {incomingCustomers.length > 0 && (
            <span className="b2b-tab-count is-alert" style={{ marginLeft: 6 }}>
              {incomingCustomers.length} pending
            </span>
          )}
        </button>
      </div>

      {loading ? (
        <div className="page-loader"><span className="spinner" /> Loading your network…</div>
      ) : (
        /* ── Integrated Table / Request Card Container ────────────────────────── */
        <div className="card b2b-table-card" style={{ padding: 0, overflow: 'hidden' }}>
          {/* Integrated Header Bar with Status Filter Pills */}
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '10px 16px', borderBottom: '1px solid var(--border)', background: 'var(--bg-3)'
          }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <button
                type="button"
                className={`btn btn-sm ${subStatus === 'approved' ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => setSubStatus('approved')}
                style={{ height: 32 }}
              >
                <CheckIcon size={13} style={{ marginRight: 4 }} />
                Connected {activeTab === 'suppliers' ? `(${suppliers.length})` : `(${customers.length})`}
              </button>

              <button
                type="button"
                className={`btn btn-sm ${subStatus === 'pending' ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => setSubStatus('pending')}
                style={{ height: 32 }}
              >
                <AlertIcon size={13} style={{ marginRight: 4 }} />
                Requests Received
                {activeTab === 'suppliers'
                  ? (incomingSuppliers.length > 0 && <span className="b2b-tab-count is-alert" style={{ marginLeft: 4 }}>{incomingSuppliers.length}</span>)
                  : (incomingCustomers.length > 0 && <span className="b2b-tab-count is-alert" style={{ marginLeft: 4 }}>{incomingCustomers.length}</span>)}
              </button>

              <button
                type="button"
                className={`btn btn-sm ${subStatus === 'sent' ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => setSubStatus('sent')}
                style={{ height: 32 }}
              >
                Requests Sent
                {activeTab === 'suppliers'
                  ? (outgoingSuppliers.length > 0 && <span className="b2b-tab-count" style={{ marginLeft: 4 }}>{outgoingSuppliers.length}</span>)
                  : (outgoingCustomers.length > 0 && <span className="b2b-tab-count" style={{ marginLeft: 4 }}>{outgoingCustomers.length}</span>)}
              </button>
            </div>
          </div>

          {/* Body Content */}
          {activeTab === 'suppliers' ? (
            /* ── MY SUPPLIERS TAB ──────────────────────────────────────────────── */
            subStatus === 'pending' ? (
              <div style={{ padding: '16px' }}>
                {incomingSuppliers.length === 0 ? (
                  <div className="empty-state">
                    <div className="empty-icon"><CheckIcon size={22} /></div>
                    <h3>No pending supplier requests</h3>
                    <p>When a supplier requests to connect with you, their request appears here.</p>
                  </div>
                ) : (
                  <div className="b2b-request-list">
                    {incomingSuppliers.map(c => (
                      <RequestCard key={c.id} conn={c} mine={false} busy={busyId === c.id}
                        onApprove={approve} onReject={reject} onCancel={cancel} />
                    ))}
                  </div>
                )}
              </div>
            ) : subStatus === 'sent' ? (
              <div style={{ padding: '16px' }}>
                {outgoingSuppliers.length === 0 ? (
                  <div className="empty-state">
                    <div className="empty-icon"><ConnectionIcon size={22} /></div>
                    <h3>No sent requests to suppliers</h3>
                    <p>Requests you send to suppliers will appear here until they approve.</p>
                  </div>
                ) : (
                  <div className="b2b-request-list">
                    {outgoingSuppliers.map(c => (
                      <RequestCard key={c.id} conn={c} mine busy={busyId === c.id}
                        onApprove={approve} onReject={reject} onCancel={cancel} />
                    ))}
                  </div>
                )}
              </div>
            ) : (
              /* Approved / Connected Suppliers Table */
              suppliers.length === 0 ? (
                <div style={{ padding: '16px' }}>
                  <div className="empty-state">
                    <div className="empty-icon"><CartIcon size={24} /></div>
                    <h3>No connected suppliers yet</h3>
                    <p>Use "Request a connection" above to connect with your suppliers and order from their catalogue.</p>
                  </div>
                </div>
              ) : (
                <div className="data-table-wrap" style={{ border: 'none' }}>
                  <table className="data-table">
                    <thead><tr>
                      <th>Supplier</th><th>BizID</th><th>My price tier</th><th>My discount</th>
                      <th>Credit limit</th><th>Outstanding</th><th style={{ width: 110 }}>Actions</th>
                    </tr></thead>
                    <tbody>
                      {suppliers.map(c => (
                        <tr key={c.id}>
                          <td>
                            <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{c.counterparty_name || c.seller_name}</div>
                            <div style={{ fontSize: '0.73rem', color: 'var(--text-muted)' }}>Connected {since(c.responded_at || c.created_at)}</div>
                          </td>
                          <td className="td-mono">{c.counterparty_bizid || c.seller_bizid}</td>
                          <td><span className="badge badge-info" style={{ textTransform: 'capitalize' }}>{c.price_tier}</span></td>
                          <td>{c.discount_pct > 0 ? `${c.discount_pct}%` : 'None'}</td>
                          <td>{c.credit_limit > 0 ? fmt(c.credit_limit) : 'Unlimited'}</td>
                          <td style={{ fontWeight: 600 }}>
                            {c.outstanding_balance > 0
                              ? <span className="badge badge-danger">{fmt(c.outstanding_balance)}</span>
                              : <span className="badge badge-success">Nil</span>}
                          </td>
                          <td>
                            <button className="btn btn-ghost btn-sm" style={{ color: 'var(--danger)' }} onClick={() => setRevokeFor(c)}>
                              Revoke
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            )
          ) : (
            /* ── MY CUSTOMERS TAB ──────────────────────────────────────────────── */
            subStatus === 'pending' ? (
              <div style={{ padding: '16px' }}>
                {incomingCustomers.length === 0 ? (
                  <div className="empty-state">
                    <div className="empty-icon"><CheckIcon size={22} /></div>
                    <h3>No pending customer requests</h3>
                    <p>When a business requests to connect as your customer, their request appears here.</p>
                  </div>
                ) : (
                  <div className="b2b-request-list">
                    {incomingCustomers.map(c => (
                      <RequestCard key={c.id} conn={c} mine={false} busy={busyId === c.id}
                        onApprove={approve} onReject={reject} onCancel={cancel} />
                    ))}
                  </div>
                )}
              </div>
            ) : subStatus === 'sent' ? (
              <div style={{ padding: '16px' }}>
                {outgoingCustomers.length === 0 ? (
                  <div className="empty-state">
                    <div className="empty-icon"><ConnectionIcon size={22} /></div>
                    <h3>No sent requests to customers</h3>
                    <p>Requests you send to customers will appear here until they approve.</p>
                  </div>
                ) : (
                  <div className="b2b-request-list">
                    {outgoingCustomers.map(c => (
                      <RequestCard key={c.id} conn={c} mine busy={busyId === c.id}
                        onApprove={approve} onReject={reject} onCancel={cancel} />
                      ))}
                  </div>
                )}
              </div>
            ) : (
              /* Approved / Connected Customers Table */
              customers.length === 0 ? (
                <div style={{ padding: '16px' }}>
                  <div className="empty-state">
                    <div className="empty-icon"><ShieldIcon size={24} /></div>
                    <h3>No connected customers yet</h3>
                    <p>Share your BizID above so your buyers can connect with you and order from your catalogue.</p>
                  </div>
                </div>
              ) : (
                <div className="data-table-wrap" style={{ border: 'none' }}>
                  <table className="data-table">
                    <thead><tr>
                      <th>Customer</th><th>BizID</th><th>Price tier</th><th>Discount</th>
                      <th>Credit limit</th><th>Stock visibility</th><th>Categories</th><th style={{ width: 150 }}>Actions</th>
                    </tr></thead>
                    <tbody>
                      {customers.map(c => (
                        <tr key={c.id}>
                          <td>
                            <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{c.counterparty_name || c.buyer_name}</div>
                            <div style={{ fontSize: '0.73rem', color: 'var(--text-muted)' }}>Connected {since(c.responded_at || c.created_at)}</div>
                          </td>
                          <td className="td-mono">{c.counterparty_bizid || c.buyer_bizid}</td>
                          <td><span className="badge badge-info" style={{ textTransform: 'capitalize' }}>{c.price_tier}</span></td>
                          <td>{c.discount_pct > 0 ? `${c.discount_pct}%` : 'None'}</td>
                          <td>{c.credit_limit > 0 ? fmt(c.credit_limit) : 'Unlimited'}</td>
                          <td>
                            <span className={`badge ${c.stock_visibility === 'exact' ? 'badge-success' : c.stock_visibility === 'band' ? 'badge-warning' : 'badge-danger'}`} style={{ textTransform: 'capitalize' }}>
                              {c.stock_visibility}
                            </span>
                          </td>
                          <td style={{ color: c.catalog_category ? 'var(--text-primary)' : 'var(--text-muted)' }}>
                            {c.catalog_category || 'All'}
                          </td>
                          <td>
                            <div className="flex gap-1" style={{ justifyContent: 'center' }}>
                              <button className="btn btn-secondary btn-sm" onClick={() => setPolicyFor(c)} title="Configure pricing and visibility">
                                <SettingsIcon size={12} /> Policy
                              </button>
                              <button className="btn btn-ghost btn-sm" style={{ color: 'var(--danger)' }} onClick={() => setRevokeFor(c)}>
                                Revoke
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            )
          )}
        </div>
      )}

      {policyFor && (
        <PolicyModal
          conn={policyFor}
          saving={busyId === policyFor.id}
          onClose={() => setPolicyFor(null)}
          onSave={async (conn, form) => { await savePolicy(conn, form); setPolicyFor(null) }}
        />
      )}
      {revokeFor && (
        <RevokeModal
          conn={revokeFor}
          busy={busyId === revokeFor.id}
          onClose={() => setRevokeFor(null)}
          onConfirm={async (conn) => { await revoke(conn); setRevokeFor(null) }}
        />
      )}
    </div>
  )
}
