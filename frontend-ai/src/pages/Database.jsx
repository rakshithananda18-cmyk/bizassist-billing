import { useState, useEffect, useRef, useCallback } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { API_BASE } from '../config'
import { useDialog } from '../contexts/DialogContext'
import { Spinner, PageHeader, Section } from '../components/ui'
import { Icon } from '../components/icons'

const LIMIT = 7

function fmtAmount(n) {
  if (!n && n !== 0) return '—'
  if (n >= 100000) return '₹' + (n / 100000).toFixed(1) + 'L'
  if (n >= 1000)   return '₹' + Math.round(n / 1000) + 'k'
  return '₹' + Math.round(n)
}

function Pagination({ total, page, limit, onPage }) {
  const pages = Math.ceil(total / limit)
  if (pages <= 1) return null
  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 12, padding: '12px 0' }}>
      <button
        className="chip"
        style={{ fontSize: 11, padding: '3px 10px' }}
        onClick={() => onPage(page - 1)}
        disabled={page === 1}
      >
        ← Previous
      </button>
      <span style={{ fontSize: '11.5px', color: 'var(--secondary-text)', fontWeight: 600 }}>
        Page {page} / {pages}
      </span>
      <button
        className="chip"
        style={{ fontSize: 11, padding: '3px 10px' }}
        onClick={() => onPage(page + 1)}
        disabled={page >= pages}
      >
        Next →
      </button>
    </div>
  )
}

export default function Database() {
  const { authFetch } = useAuth()
  const { showAlert, showConfirm, showError } = useDialog()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')

  // Multi-step delete database modal states
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [deleteStep, setDeleteStep] = useState(0)
  const [deleteInput, setDeleteInput] = useState('')

  // Explorer collapse/expand all
  const explorerRef = useRef(null)
  const [allExpanded, setAllExpanded] = useState(false)

  const toggleAllSections = useCallback(() => {
    const next = !allExpanded
    setAllExpanded(next)
    if (explorerRef.current) {
      explorerRef.current.querySelectorAll('details.tree-node').forEach(d => {
        if (next) d.setAttribute('open', '') 
        else d.removeAttribute('open')
      })
    }
  }, [allExpanded])

  // Pagination states
  const [uploadsPage, setUploadsPage] = useState(1)
  const [folderUploadsPage, setFolderUploadsPage] = useState(1)
  const [invoicesPage, setInvoicesPage] = useState(1)
  const [inventoryPage, setInventoryPage] = useState(1)
  const [paymentsPage, setPaymentsPage] = useState(1)
  const [chatPage, setChatPage] = useState(1)

  // File preview modal
  const [preview, setPreview] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewPage, setPreviewPage] = useState(1)
  const PREVIEW_LIMIT = 10

  useEffect(() => {
    loadDatabase()
    function handleDataUpdated() { loadDatabase(false) }
    window.addEventListener('data-updated', handleDataUpdated)
    return () => window.removeEventListener('data-updated', handleDataUpdated)
  }, [])

  async function loadDatabase(showSkeleton = true) {
    if (showSkeleton) setLoading(true)
    try {
      const res = await authFetch(`${API_BASE}/database`)
      if (!res.ok) throw new Error('Failed to fetch database data')
      const json = await res.json()
      setData(json)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleFileUpload(e) {
    const file = e.target.files[0]
    if (!file) return
    setUploading(true)
    const formData = new FormData()
    formData.append('file', file)
    try {
      const res = await authFetch(`${API_BASE}/upload`, { method: 'POST', body: formData })
      const resp = await res.json()
      if (!res.ok || resp.error) {
        throw new Error(resp.error || resp.detail || resp.message || res.statusText || `Upload failed (${res.status})`)
      }
      await showAlert(`File type: ${resp.file_type}\nRows processed: ${resp.rows}`)
      loadDatabase()
    } catch (err) {
      await showError(err, 'Upload failed')
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  async function fetchFileData(file) {
    setPreviewLoading(true)
    setPreviewPage(1)
    const fileType = file.type || file.file_type || 'Unknown'
    setPreview({ filename: file.filename, file_type: fileType, columns: [], rows: [], total_rows: 0, loading: true })
    try {
      const res = await authFetch(`${API_BASE}/upload/${file.id}/data`)
      if (!res.ok) throw new Error('Failed to load file data')
      const data = await res.json()
      setPreview(data)
    } catch (err) {
      setPreview({ filename: file.filename, file_type: fileType, columns: [], rows: [], total_rows: 0, error: err.message })
    } finally {
      setPreviewLoading(false)
    }
  }

  function closePreview() {
    setPreview(null)
    setPreviewPage(1)
  }

  async function handleDeleteUpload(id) {
    const confirmed = await showConfirm('Are you sure you want to delete this file? This action cannot be undone.')
    if (!confirmed) return
    try {
      const res = await authFetch(`${API_BASE}/upload/${id}`, { method: 'DELETE' })
      const resp = await res.json()
      if (!res.ok || resp.error) throw new Error(resp.error || 'Delete failed')
      await showAlert('File deleted successfully')
      loadDatabase()
    } catch (err) {
      await showError(err, 'Failed to delete file')
    }
  }

  async function executeWipeDatabase() {
    setDeleteStep(2)
    try {
      const res = await authFetch(`${API_BASE}/database/delete`, { method: 'DELETE' })
      if (res.ok) setDeleteStep(3)
      else throw new Error('Wipe operation failed')
    } catch (err) {
      await showError(err)
      setShowDeleteModal(false)
    }
  }

  if (loading) {
    return (
      <>
        <PageHeader title="Business Database" subtitle="View and manage uploaded files and records" />
        <div className="widget">
          <div className="vskel" style={{ width: '40%' }}></div>
          <div className="vskel" style={{ height: 90 }}></div>
        </div>
        <div className="widget" style={{ marginTop: 16 }}>
          <div className="vskel" style={{ width: '30%' }}></div>
          <div className="vskel"></div>
          <div className="vskel"></div>
        </div>
      </>
    )
  }

  if (error || !data) {
    return (
      <div className="vempty">
        <div className="vempty-icon"><Icon name="database" size={36} /></div>
        <div className="vempty-title">Database is empty</div>
        <div className="vempty-sub">{error || 'Upload CSV/XLSX billing files to populate the database.'}</div>
        <button
          className="chip"
          style={{ marginTop: 14, fontWeight: 600, cursor: 'pointer' }}
          disabled={uploading}
          onClick={() => !uploading && document.getElementById('file-upload-db').click()}
        >
          {uploading ? <Spinner /> : '+ Upload data'}
        </button>
        <input type="file" id="file-upload-db" accept=".csv,.xlsx,.pdf" onChange={handleFileUpload} hidden />
      </div>
    )
  }

  // Parse chat history sessions
  const chatHistoryList = data.chat_history || []
  const sessions = {}
  chatHistoryList.forEach(m => {
    const sid = m.session_id || 'default'
    if (!sessions[sid]) sessions[sid] = { title: m.session_title || 'Previous Chat Session', messages: [] }
    sessions[sid].messages.push(m)
  })
  const sessionKeys = Object.keys(sessions)

  // Paginated slices
  const uploadsList = data.uploads || []
  const slicedUploads = uploadsList.slice((uploadsPage - 1) * LIMIT, uploadsPage * LIMIT)
  const slicedFolderUploads = uploadsList.slice((folderUploadsPage - 1) * LIMIT, folderUploadsPage * LIMIT)
  const invoicesList = data.invoices || []
  const slicedInvoices = invoicesList.slice((invoicesPage - 1) * LIMIT, invoicesPage * LIMIT)
  const inventoryList = data.inventory || []
  const slicedInventory = inventoryList.slice((inventoryPage - 1) * LIMIT, inventoryPage * LIMIT)
  const paymentsList = data.payments || []
  const slicedPayments = paymentsList.slice((paymentsPage - 1) * LIMIT, paymentsPage * LIMIT)
  const slicedSessionKeys = sessionKeys.slice((chatPage - 1) * LIMIT, chatPage * LIMIT)

  return (
    <>
      <PageHeader title="Business Database" subtitle="View and manage uploaded files and records" />

      {/* OVERVIEW CARDS */}
      <div className="widget">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div className="widget-title" style={{ margin: 0 }}>Database Overview</div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button
              onClick={() => !uploading && document.getElementById('file-upload-db').click()}
              className="chip"
              style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 12px', fontSize: 12, fontWeight: 600 }}
              disabled={uploading}
            >
              {uploading ? <Spinner /> : <><Icon name="file" size={13} /> Upload Data</>}
            </button>
            <input type="file" id="file-upload-db" accept=".csv,.xlsx,.pdf" onChange={handleFileUpload} hidden />

            <button
              onClick={loadDatabase}
              className="chip"
              style={{ padding: '6px 12px', fontSize: 12, fontWeight: 600 }}
            >
              ↻ Refresh
            </button>

            <button
              onClick={() => { setDeleteStep(0); setDeleteInput(''); setShowDeleteModal(true) }}
              className="chip"
              style={{ padding: '6px 12px', fontSize: 12, fontWeight: 600, background: 'rgba(155,28,28,0.10)', color: '#9b1c1c', border: '1px solid rgba(155,28,28,0.20)' }}
              title="Delete entire database (cannot be undone)"
            >
              <Icon name="trash" size={13} /> Delete All
            </button>
          </div>
        </div>

        <div className="vsummary-strip-three">
          <div className="vsummary-card" style={{ borderLeftColor: 'var(--accent-color)', cursor: 'default' }}>
            <div className="vsummary-label">Invoices</div>
            <div className="vsummary-value">{data.invoice_count}</div>
            <div className="vsummary-sub">records tracked</div>
          </div>
          <div className="vsummary-card" style={{ borderLeftColor: '#1f6b3a', cursor: 'default' }}>
            <div className="vsummary-label">Inventory</div>
            <div className="vsummary-value">{data.inventory_count}</div>
            <div className="vsummary-sub">items in stock</div>
          </div>
          <div className="vsummary-card" style={{ borderLeftColor: '#7a4200', cursor: 'default' }}>
            <div className="vsummary-label">Uploads</div>
            <div className="vsummary-value">{data.upload_count}</div>
            <div className="vsummary-sub">datasets uploaded</div>
          </div>
        </div>
      </div>

      {/* UPLOADED FILES */}
      <Section
        title="Uploaded Files"
        count={uploadsList.length}
        icon={<Icon name="file" size={16} />}
        collapsible
        noPad
        style={{ marginTop: 12 }}
      >
        <div className="vtable-wrap">
          <table>
            <thead>
              <tr>
                <th>Filename</th>
                <th>Type</th>
                <th>Rows</th>
                <th>Uploaded</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {slicedUploads.length === 0 ? (
                <tr>
                  <td colSpan="5" style={{ textAlign: 'center', color: 'var(--secondary-text)', padding: '20px' }}>
                    No uploaded files yet.
                  </td>
                </tr>
              ) : (
                slicedUploads.map((file, i) => (
                  <tr key={i} style={{ cursor: 'pointer' }} onClick={() => fetchFileData(file)}>
                    <td style={{ color: 'var(--accent-color)', fontWeight: 600, textDecoration: 'underline dotted' }} title="Click to preview">
                      {file.filename}
                    </td>
                    <td><span className="tag">{file.type || file.file_type || '—'}</span></td>
                    <td>{file.rows || file.rows_count || '0'}</td>
                    <td style={{ color: 'var(--secondary-text)', fontSize: 12 }}>{file.uploaded || file.upload_time || '—'}</td>
                    <td>
                      <button
                        className="delete-btn-small"
                        onClick={e => { e.stopPropagation(); handleDeleteUpload(file.id) }}
                        title="Delete file"
                      >
                        <Icon name="trash" size={12} /> Delete
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
          <Pagination total={uploadsList.length} page={uploadsPage} limit={LIMIT} onPage={setUploadsPage} />
        </div>
      </Section>

      {/* DATABASE EXPLORER TREE */}
      <Section
        title="Database Explorer"
        icon={<Icon name="database" size={18} />}
        collapsible
        style={{ marginTop: 12 }}
        actions={
          <button
            onClick={toggleAllSections}
            className="chip"
            style={{ fontSize: 11, padding: '4px 10px', display: 'flex', alignItems: 'center', gap: 5 }}
            title={allExpanded ? 'Collapse all sections' : 'Expand all sections'}
          >
            <span style={{
              display: 'inline-block',
              transition: 'transform 0.22s ease',
              transform: allExpanded ? 'rotate(90deg)' : 'rotate(0deg)',
              fontSize: 14, lineHeight: 1, color: 'var(--secondary-text)'
            }}>›</span>
            {allExpanded ? 'Collapse All' : 'Expand All'}
          </button>
        }
      >
        <div ref={explorerRef} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>

          {/* Datasets */}
          <details className="tree-node">
            <summary className="tree-summary">
              <Icon name="file" size={14} /> Uploaded Datasets ({uploadsList.length})
            </summary>
            <div className="tree-content">
              {uploadsList.length === 0 ? (
                <div style={{ color: 'var(--secondary-text)', padding: '10px 0' }}>No datasets uploaded.</div>
              ) : (
                <>
                  <div className="vtable-wrap">
                    <table>
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
                        {slicedFolderUploads.map((u, i) => (
                          <tr key={i} style={{ cursor: 'pointer' }} onClick={() => fetchFileData(u)}>
                            <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{u.id}</td>
                            <td style={{ fontWeight: 600, color: 'var(--accent-color)', textDecoration: 'underline dotted' }}>{u.filename}</td>
                            <td><span className="tag">{u.file_type || u.type}</span></td>
                            <td>{u.rows_count || u.rows} rows</td>
                            <td style={{ color: 'var(--secondary-text)', fontSize: 12 }}>{u.upload_time || u.uploaded}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <Pagination total={uploadsList.length} page={folderUploadsPage} limit={LIMIT} onPage={setFolderUploadsPage} />
                </>
              )}
            </div>
          </details>

          {/* Invoices */}
          <details className="tree-node">
            <summary className="tree-summary">
              <Icon name="card" size={14} /> Invoices &amp; Sales ({invoicesList.length})
            </summary>
            <div className="tree-content">
              {invoicesList.length === 0 ? (
                <div style={{ color: 'var(--secondary-text)', padding: '10px 0' }}>No invoices present.</div>
              ) : (
                <>
                  <div className="vtable-wrap">
                    <table>
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
                        {slicedInvoices.map((inv, i) => (
                          <tr key={i}>
                            <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{inv.invoice_id || 'N/A'}</td>
                            <td style={{ fontWeight: 500 }}>{inv.customer}</td>
                            <td>{inv.product || 'N/A'}</td>
                            <td style={{ fontWeight: 600 }}>₹{(inv.amount || 0).toLocaleString('en-IN')}</td>
                            <td>
                              <span className="vpill" style={{
                                background: inv.status === 'Paid' ? 'rgba(31,107,58,0.12)' : 'rgba(193,95,60,0.12)',
                                color: inv.status === 'Paid' ? '#1a5c32' : 'var(--accent-color)',
                              }}>
                                {inv.status}
                              </span>
                            </td>
                            <td style={{ color: 'var(--secondary-text)', fontSize: 12 }}>{inv.due_date || 'N/A'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <Pagination total={invoicesList.length} page={invoicesPage} limit={LIMIT} onPage={setInvoicesPage} />
                </>
              )}
            </div>
          </details>

          {/* Inventory */}
          <details className="tree-node">
            <summary className="tree-summary">
              <Icon name="package" size={14} /> Inventory Stock ({inventoryList.length} items)
            </summary>
            <div className="tree-content">
              {inventoryList.length === 0 ? (
                <div style={{ color: 'var(--secondary-text)', padding: '10px 0' }}>No inventory records.</div>
              ) : (
                <>
                  <div className="vtable-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Product Name</th>
                          <th>Stock</th>
                          <th>Expiry Date</th>
                          <th>Supplier</th>
                        </tr>
                      </thead>
                      <tbody>
                        {slicedInventory.map((item, i) => (
                          <tr key={i}>
                            <td style={{ fontWeight: 600, color: 'var(--accent-color)' }}>
                              {item.product_name || item.product}
                            </td>
                            <td>{item.stock} items</td>
                            <td style={{ color: 'var(--secondary-text)', fontSize: 12 }}>{item.expiry_date || item.expiry || 'N/A'}</td>
                            <td style={{ color: 'var(--secondary-text)' }}>{item.supplier || 'N/A'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <Pagination total={inventoryList.length} page={inventoryPage} limit={LIMIT} onPage={setInventoryPage} />
                </>
              )}
            </div>
          </details>

          {/* Payments */}
          <details className="tree-node">
            <summary className="tree-summary">
              <Icon name="wallet" size={14} /> Logged Payments &amp; Dues ({paymentsList.length})
            </summary>
            <div className="tree-content">
              {paymentsList.length === 0 ? (
                <div style={{ color: 'var(--secondary-text)', padding: '10px 0' }}>No payment entries.</div>
              ) : (
                <>
                  <div className="vtable-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Customer</th>
                          <th>Amount</th>
                          <th>Due Date</th>
                          <th>Paid Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {slicedPayments.map((p, i) => (
                          <tr key={i}>
                            <td style={{ fontWeight: 500 }}>{p.customer}</td>
                            <td style={{ fontWeight: 600 }}>₹{(p.amount || 0).toLocaleString('en-IN')}</td>
                            <td style={{ color: 'var(--secondary-text)', fontSize: 12 }}>{p.due_date || 'N/A'}</td>
                            <td>
                              <span className="vpill" style={{
                                background: p.paid === 'Yes' ? 'rgba(31,107,58,0.12)' : 'rgba(193,95,60,0.12)',
                                color: p.paid === 'Yes' ? '#1a5c32' : 'var(--accent-color)',
                              }}>
                                {p.paid === 'Yes' ? 'Paid' : 'Unpaid'}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <Pagination total={paymentsList.length} page={paymentsPage} limit={LIMIT} onPage={setPaymentsPage} />
                </>
              )}
            </div>
          </details>

          {/* Chat threads */}
          <details className="tree-node">
            <summary className="tree-summary">
              <Icon name="chat" size={14} /> Chat Thread History ({sessionKeys.length} sessions)
            </summary>
            <div className="tree-content" style={{ paddingTop: 14, maxHeight: 450, overflowY: 'auto' }}>
              {sessionKeys.length === 0 ? (
                <div style={{ color: 'var(--secondary-text)', padding: '10px 0' }}>No chat history threads found.</div>
              ) : (
                <>
                  {slicedSessionKeys.map(sid => {
                    const s = sessions[sid]
                    const sortedMsgs = [...s.messages].reverse()
                    return (
                      <details
                        key={sid}
                        style={{
                          marginBottom: 12,
                          border: '1px solid var(--border-color)',
                          borderRadius: 8,
                          padding: '6px 12px',
                          background: 'var(--hover-bg)',
                        }}
                      >
                        <summary style={{ fontWeight: 600, fontSize: 13, padding: '6px 0', cursor: 'pointer', color: 'var(--text-color)' }}>
                          {s.title}
                        </summary>
                        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
                          {sortedMsgs.map((msg, idx) => (
                            <div key={idx} className={`chat-tree-bubble ${msg.role}`}>
                              <span style={{
                                fontWeight: 600, fontSize: 10, textTransform: 'uppercase',
                                color: msg.role === 'user' ? 'var(--accent-color)' : '#1a5c32',
                                display: 'block', marginBottom: 2,
                              }}>
                                {msg.role}
                              </span>
                              <span>{msg.content}</span>
                            </div>
                          ))}
                        </div>
                      </details>
                    )
                  })}
                  <Pagination total={sessionKeys.length} page={chatPage} limit={LIMIT} onPage={setChatPage} />
                </>
              )}
            </div>
          </details>
        </div>
      </Section>

      {/* MULTI-STEP DELETE DATABASE MODAL */}
      {showDeleteModal && (
        <div className="custom-modal-overlay">
          {deleteStep === 0 && (
            <div style={{
              background: 'var(--card-color)', borderRadius: 12, padding: 32,
              maxWidth: 450, width: '90%', boxShadow: '0 16px 48px rgba(0,0,0,0.3)',
              border: '2px solid rgba(155,28,28,0.3)',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                <Icon name="trash" size={22} style={{ color: '#9b1c1c' }} />
                <div style={{ fontSize: 20, fontWeight: 700, color: '#9b1c1c' }}>Delete Entire Database?</div>
              </div>
              <div style={{ fontSize: 14, lineHeight: 1.6, marginBottom: 24, color: 'var(--secondary-text)' }}>
                This will <strong>permanently delete</strong> all data:<br />
                • All invoices<br />• All inventory records<br />• All payment history<br />• All uploads
                <br /><br />
                <span style={{ color: '#9b1c1c', fontWeight: 600 }}>This action CANNOT be undone.</span>
              </div>
              <div style={{ display: 'flex', gap: 12 }}>
                <button onClick={() => setShowDeleteModal(false)} className="chip" style={{ flex: 1, padding: 12, justifyContent: 'center' }}>Cancel</button>
                <button onClick={() => setDeleteStep(1)} style={{ flex: 1, padding: 12, borderRadius: 8, border: 'none', background: '#9b1c1c', color: 'white', cursor: 'pointer', fontWeight: 600 }}>
                  I Understand, Delete
                </button>
              </div>
            </div>
          )}

          {deleteStep === 1 && (
            <div style={{
              background: 'var(--card-color)', borderRadius: 12, padding: 32,
              maxWidth: 450, width: '90%', boxShadow: '0 16px 48px rgba(0,0,0,0.3)',
              border: '2px solid rgba(155,28,28,0.3)',
            }}>
              <div style={{ fontSize: 20, fontWeight: 700, marginBottom: 16, color: '#9b1c1c' }}>Final Confirmation Required</div>
              <div style={{ fontSize: 13, lineHeight: 1.6, marginBottom: 20, color: 'var(--secondary-text)' }}>
                Type the word <strong style={{ color: '#9b1c1c' }}>DELETE</strong> below to confirm permanent deletion.
              </div>
              <input
                id="deleteConfirmInput"
                type="text"
                value={deleteInput}
                onChange={e => setDeleteInput(e.target.value)}
                placeholder="Type DELETE..."
                style={{
                  width: '100%', padding: 12, borderRadius: 8,
                  border: '1px solid var(--border-color)',
                  background: 'var(--input-bg)', color: 'var(--text-color)',
                  fontSize: 14, marginBottom: 20, boxSizing: 'border-box',
                }}
                autoFocus
              />
              <div style={{ display: 'flex', gap: 12 }}>
                <button onClick={() => setShowDeleteModal(false)} className="chip" style={{ flex: 1, padding: 12, justifyContent: 'center' }}>Cancel</button>
                <button
                  disabled={deleteInput.toUpperCase() !== 'DELETE'}
                  onClick={executeWipeDatabase}
                  style={{
                    flex: 1, padding: 12, borderRadius: 8, border: 'none',
                    background: '#9b1c1c', color: 'white',
                    cursor: deleteInput.toUpperCase() === 'DELETE' ? 'pointer' : 'not-allowed',
                    fontWeight: 600, opacity: deleteInput.toUpperCase() === 'DELETE' ? 1 : 0.5,
                  }}
                >
                  Delete Permanently
                </button>
              </div>
            </div>
          )}

          {deleteStep === 2 && (
            <div style={{
              background: 'var(--card-color)', borderRadius: 12, padding: 32,
              maxWidth: 450, width: '90%', boxShadow: '0 16px 48px rgba(0,0,0,0.3)', textAlign: 'center',
            }}>
              <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>Deleting database...</div>
              <div style={{
                width: 40, height: 40, borderRadius: '50%',
                border: '4px solid var(--border-color)', borderTopColor: '#9b1c1c',
                animation: 'spin 1s linear infinite', margin: '0 auto',
              }} />
            </div>
          )}

          {deleteStep === 3 && (
            <div style={{
              background: 'var(--card-color)', borderRadius: 12, padding: 32,
              maxWidth: 450, width: '90%', boxShadow: '0 16px 48px rgba(0,0,0,0.3)',
              textAlign: 'center', border: '2px solid rgba(31,107,58,0.3)',
            }}>
              <Icon name="trophy" size={32} style={{ color: '#1a5c32', marginBottom: 12 }} />
              <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 8, color: '#1a5c32' }}>Database Deleted</div>
              <div style={{ fontSize: 13, color: 'var(--secondary-text)', marginBottom: 24 }}>All data has been permanently removed.</div>
              <button
                onClick={() => { setShowDeleteModal(false); loadDatabase() }}
                style={{ width: '100%', padding: 12, borderRadius: 8, border: 'none', background: '#1a5c32', color: 'white', cursor: 'pointer', fontWeight: 600 }}
              >
                Done
              </button>
            </div>
          )}
        </div>
      )}

      {/* FILE DATA PREVIEW MODAL */}
      {preview && (
        <div
          style={{
            position: 'fixed', inset: 0, zIndex: 9000,
            background: 'rgba(0,0,0,0.55)', backdropFilter: 'blur(10px)',
            WebkitBackdropFilter: 'blur(10px)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            padding: 24, animation: 'fadeIn 0.2s ease',
          }}
          onClick={closePreview}
        >
          <div
            style={{
              background: 'var(--card-color)', border: '1.5px solid var(--glass-border)',
              borderRadius: 16, boxShadow: 'var(--shadow-lg)',
              width: '100%', maxWidth: 860, maxHeight: '85vh',
              display: 'flex', flexDirection: 'column', overflow: 'hidden',
              animation: 'slideUp 0.25s cubic-bezier(0.16,1,0.3,1)',
            }}
            onClick={e => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div style={{
              padding: '16px 20px', borderBottom: '1px solid var(--border-color)',
              display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0,
            }}>
              <div>
                <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--text-color)', display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Icon name="file" size={16} /> {preview.filename}
                </div>
                <div style={{ fontSize: 12, color: 'var(--secondary-text)', marginTop: 3 }}>
                  {preview.file_type} · {preview.total_rows} rows
                </div>
              </div>
              <button
                onClick={closePreview}
                style={{ border: 'none', background: 'transparent', fontSize: 22, cursor: 'pointer', color: 'var(--secondary-text)', lineHeight: 1, padding: '4px 8px', borderRadius: 6 }}
              >✕</button>
            </div>

            {/* Modal Body */}
            <div style={{ flex: 1, overflowY: 'auto', padding: '0 0 16px' }}>
              {previewLoading || preview.loading ? (
                <div style={{ textAlign: 'center', padding: 40, color: 'var(--secondary-text)' }}>
                  <div style={{
                    width: 32, height: 32, border: '3px solid var(--border-color)',
                    borderTopColor: 'var(--accent-color)', borderRadius: '50%',
                    animation: 'spin 0.8s linear infinite', margin: '0 auto 12px',
                  }} />
                  Loading file data...
                </div>
              ) : preview.error ? (
                <div style={{ textAlign: 'center', padding: 32, color: '#9b1c1c' }}>
                  <Icon name="alert" size={20} style={{ marginBottom: 8 }} /> {preview.error}
                </div>
              ) : preview.rows.length === 0 ? (
                <div style={{ textAlign: 'center', padding: 32, color: 'var(--secondary-text)' }}>
                  No records found for this file.
                </div>
              ) : (
                <>
                  <div className="vtable-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th style={{ width: 36, textAlign: 'center' }}>#</th>
                          {preview.columns.map(col => (
                            <th key={col}>{col.replace(/_/g, ' ')}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {preview.rows
                          .slice((previewPage - 1) * PREVIEW_LIMIT, previewPage * PREVIEW_LIMIT)
                          .map((row, i) => (
                            <tr key={i}>
                              <td style={{ textAlign: 'center', color: 'var(--secondary-text)', fontSize: 11 }}>
                                {(previewPage - 1) * PREVIEW_LIMIT + i + 1}
                              </td>
                              {preview.columns.map(col => {
                                const val = row[col]
                                if (col === 'status' || col === 'paid') {
                                  const isPositive = val === 'Paid' || val === 'Yes'
                                  return (
                                    <td key={col}>
                                      <span className="vpill" style={{
                                        background: isPositive ? 'rgba(31,107,58,0.12)' : 'rgba(193,95,60,0.12)',
                                        color: isPositive ? '#1a5c32' : 'var(--accent-color)',
                                      }}>
                                        {isPositive ? (col === 'paid' ? 'Paid' : val) : (col === 'paid' ? 'Unpaid' : val)}
                                      </span>
                                    </td>
                                  )
                                }
                                if (col === 'amount') return <td key={col} style={{ fontWeight: 600 }}>₹{Number(val).toLocaleString('en-IN')}</td>
                                return <td key={col}>{val || '—'}</td>
                              })}
                            </tr>
                          ))
                        }
                      </tbody>
                    </table>
                  </div>
                  <Pagination total={preview.rows.length} page={previewPage} limit={PREVIEW_LIMIT} onPage={setPreviewPage} />
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  )
}
