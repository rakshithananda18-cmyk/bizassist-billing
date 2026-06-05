import { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { API_BASE } from '../config'

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
    <div className="db-pagination" style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 12, marginTop: 12, marginBottom: 12 }}>
      <button
        className="matte-glass"
        style={{ padding: '4px 10px', cursor: 'pointer', borderRadius: 6, fontSize: 11, border: '1px solid var(--border-color)', background: 'var(--card-color)', color: 'var(--text-color)' }}
        onClick={() => onPage(page - 1)}
        disabled={page === 1}
      >
        ← Previous
      </button>
      <span style={{ fontSize: '11.5px', color: 'var(--secondary-text)', fontWeight: 600 }}>
        Page {page} / {pages}
      </span>
      <button
        className="matte-glass"
        style={{ padding: '4px 10px', cursor: 'pointer', borderRadius: 6, fontSize: 11, border: '1px solid var(--border-color)', background: 'var(--card-color)', color: 'var(--text-color)' }}
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
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')

  // Multi-step delete database modal states
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [deleteStep, setDeleteStep] = useState(0) // 0: initial warning, 1: text confirmation, 2: executing, 3: done
  const [deleteInput, setDeleteInput] = useState('')

  // Pagination states
  const [uploadsPage, setUploadsPage] = useState(1)
  const [folderUploadsPage, setFolderUploadsPage] = useState(1)
  const [invoicesPage, setInvoicesPage] = useState(1)
  const [inventoryPage, setInventoryPage] = useState(1)
  const [paymentsPage, setPaymentsPage] = useState(1)
  const [chatPage, setChatPage] = useState(1)

  // File preview modal
  const [preview, setPreview] = useState(null)  // { filename, file_type, columns, rows, total_rows }
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewPage, setPreviewPage] = useState(1)
  const PREVIEW_LIMIT = 10

  useEffect(() => {
    loadDatabase()
    // Re-fetch when data changes elsewhere (e.g. an upload from the chat panel)
    function handleDataUpdated() {
      loadDatabase(false)
    }
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
      const res = await authFetch(`${API_BASE}/upload`, {
        method: 'POST',
        body: formData,
      })
      const resp = await res.json()
      if (!res.ok || resp.error) {
        throw new Error(resp.error || 'Upload failed')
      }
      alert(`File type: ${resp.file_type}\nRows processed: ${resp.rows}`)
      loadDatabase()
    } catch (err) {
      alert('Upload failed: ' + err.message)
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
    if (!window.confirm('Are you sure you want to delete this file? This action cannot be undone.')) return

    try {
      const res = await authFetch(`${API_BASE}/upload/${id}`, { method: 'DELETE' })
      const resp = await res.json()
      if (!res.ok || resp.error) {
        throw new Error(resp.error || 'Delete failed')
      }
      alert('File deleted successfully')
      loadDatabase()
    } catch (err) {
      alert('Failed to delete file: ' + err.message)
    }
  }

  async function executeWipeDatabase() {
    setDeleteStep(2)
    try {
      const res = await authFetch(`${API_BASE}/database/delete`, { method: 'DELETE' })
      if (res.ok) {
        setDeleteStep(3)
      } else {
        throw new Error('Wipe operation failed')
      }
    } catch (err) {
      alert(err.message)
      setShowDeleteModal(false)
    }
  }

  if (loading) {
    return (
      <>
        <div className="vheader" style={{ marginBottom: 16 }}>
          <div>
            <div className="vheader-title">Business Database</div>
            <div className="vheader-sub">View and manage uploaded files and records</div>
          </div>
        </div>
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
        <div className="vempty-icon">🗄</div>
        <div className="vempty-title">Database is empty</div>
        <div className="vempty-sub">{error || 'Upload CSV/XLSX billing files to populate the database.'}</div>
        <button
          className="chip"
          style={{
            marginTop: 14,
            border: '1px solid var(--border-color)',
            background: 'var(--card-color)',
            color: 'var(--text-color)',
            fontWeight: 600,
            cursor: 'pointer'
          }}
          onClick={() => document.getElementById('file-upload-db').click()}
        >
          {uploading ? 'Uploading...' : '+ Upload data'}
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
    if (!sessions[sid]) {
      sessions[sid] = {
        title: m.session_title || 'Previous Chat Session',
        messages: [],
      }
    }
    sessions[sid].messages.push(m)
  })
  const sessionKeys = Object.keys(sessions)

  // Paginated Slices
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
      <div className="vheader" style={{ marginBottom: 16 }}>
        <div>
          <div className="vheader-title">Business Database</div>
          <div className="vheader-sub">View and manage uploaded files and records</div>
        </div>
      </div>

      {/* OVERVIEW CARDS */}
      <div className="widget">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div className="widget-title" style={{ margin: 0 }}>
            Database Overview
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button
              onClick={() => document.getElementById('file-upload-db').click()}
              style={{
                padding: '8px 12px',
                border: '1px solid var(--border-color)',
                borderRadius: '8px',
                background: 'var(--card-color)',
                color: 'var(--text-color)',
                cursor: 'pointer',
                fontSize: '12px',
                fontWeight: 600,
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
              }}
              disabled={uploading}
            >
              <span style={{ fontSize: '13px', fontWeight: 'bold' }}>↑</span>
              {uploading ? 'Uploading...' : 'Upload Data'}
            </button>
            <input type="file" id="file-upload-db" accept=".csv,.xlsx,.pdf" onChange={handleFileUpload} hidden />

            <button
              onClick={loadDatabase}
              style={{
                padding: '8px 12px',
                border: '1px solid var(--border-color)',
                borderRadius: '8px',
                background: 'var(--card-color)',
                color: 'var(--text-color)',
                cursor: 'pointer',
                fontSize: '12px',
                fontWeight: 600,
              }}
            >
              ↻ Refresh
            </button>

            <button
              onClick={() => {
                setDeleteStep(0)
                setDeleteInput('')
                setShowDeleteModal(true)
              }}
              style={{
                padding: '8px 12px',
                border: 'none',
                borderRadius: '8px',
                background: 'rgba(201,66,66,0.15)',
                color: '#c94242',
                cursor: 'pointer',
                fontSize: '12px',
                fontWeight: 600,
              }}
              title="Delete entire database (cannot be undone)"
            >
              🗑 Delete All
            </button>
          </div>
        </div>

        <div className="admin-summary-strip">
          <div className="vsummary-card" style={{ borderLeftColor: 'var(--accent-color)', cursor: 'default' }}>
            <div className="vsummary-label">Invoices</div>
            <div className="vsummary-value">{data.invoice_count}</div>
            <div className="vsummary-sub">records tracked</div>
          </div>
          <div className="vsummary-card" style={{ borderLeftColor: '#3a9a5c', cursor: 'default' }}>
            <div className="vsummary-label">Inventory</div>
            <div className="vsummary-value">{data.inventory_count}</div>
            <div className="vsummary-sub">items in stock</div>
          </div>
          <div className="vsummary-card" style={{ borderLeftColor: '#c97c22', cursor: 'default' }}>
            <div className="vsummary-label">Uploads</div>
            <div className="vsummary-value">{data.upload_count}</div>
            <div className="vsummary-sub">datasets uploaded</div>
          </div>
        </div>
      </div>

      {/* UPLOADED FILES */}
      <div className="widget" style={{ marginTop: 12 }}>
        <div className="widget-title">Uploaded Files</div>
        <div className="database-table" style={{ marginTop: 12 }}>
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
                  <td colSpan="5" style={{ textAlign: 'center', color: 'var(--secondary-text)', padding: '16px' }}>
                    No uploaded files yet.
                  </td>
                </tr>
              ) : (
                slicedUploads.map((file, i) => (
                  <tr key={i} style={{ cursor: 'pointer' }} className="upload-file-row" onClick={() => fetchFileData(file)}>
                    <td
                      style={{ color: 'var(--accent-color)', fontWeight: 600, cursor: 'pointer', textDecoration: 'underline dotted' }}
                      title="Click to preview file data"
                    >
                      {file.filename}
                    </td>
                    <td>{file.type || file.file_type || '—'}</td>
                    <td>{file.rows || file.rows_count || '0'}</td>
                    <td>{file.uploaded || file.upload_time || '—'}</td>
                    <td>
                      <button
                        className="delete-btn-small"
                        onClick={e => { e.stopPropagation(); handleDeleteUpload(file.id) }}
                        title="Delete file"
                      >
                        ✕ Delete
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
          <Pagination total={uploadsList.length} page={uploadsPage} limit={LIMIT} onPage={setUploadsPage} />
        </div>
      </div>

      {/* DATABASE EXPLORER TREE */}
      <div className="widget" style={{ marginTop: 12 }}>
        <div className="widget-title" style={{ marginBttom: 16 }}>
          Database Explorer
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, marginTop: 12 }}>
          {/* Datasets */}
          <details className="tree-node">
            <summary className="tree-summary">📦 Uploaded Datasets ({uploadsList.length})</summary>
            <div className="tree-content">
              {uploadsList.length === 0 ? (
                <div style={{ color: 'var(--secondary-text)', padding: '10px 0' }}>No datasets uploaded.</div>
              ) : (
                <>
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
                      {slicedFolderUploads.map((u, i) => (
                        <tr key={i} style={{ cursor: 'pointer' }} onClick={() => fetchFileData(u)}>
                          <td style={{ fontFamily: 'monospace' }}>{u.id}</td>
                          <td style={{ fontWeight: 600, color: 'var(--accent-color)', textDecoration: 'underline dotted' }}>{u.filename}</td>
                          <td>
                            <span className="tag">{u.file_type || u.type}</span>
                          </td>
                          <td>{u.rows_count || u.rows} rows</td>
                          <td>{u.upload_time || u.uploaded}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <Pagination total={uploadsList.length} page={folderUploadsPage} limit={LIMIT} onPage={setFolderUploadsPage} />
                </>
              )}
            </div>
          </details>

          {/* Invoices */}
          <details className="tree-node">
            <summary className="tree-summary">📄 Invoices & Sales ({invoicesList.length})</summary>
            <div className="tree-content">
              {invoicesList.length === 0 ? (
                <div style={{ color: 'var(--secondary-text)', padding: '10px 0' }}>No invoices present.</div>
              ) : (
                <>
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
                      {slicedInvoices.map((inv, i) => (
                        <tr key={i}>
                          <td style={{ fontFamily: 'monospace' }}>{inv.invoice_id || 'N/A'}</td>
                          <td style={{ fontWeight: 500 }}>{inv.customer}</td>
                          <td>{inv.product || 'N/A'}</td>
                          <td style={{ fontWeight: 600 }}>₹{(inv.amount || 0).toLocaleString('en-IN')}</td>
                          <td>
                            <span
                              className="tag"
                              style={{
                                background: inv.status === 'Paid' ? 'rgba(58,154,92,0.12)' : 'rgba(201,100,66,0.12)',
                                color: inv.status === 'Paid' ? '#3a9a5c' : 'var(--accent-color)',
                              }}
                            >
                              {inv.status}
                            </span>
                          </td>
                          <td>{inv.due_date || 'N/A'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <Pagination total={invoicesList.length} page={invoicesPage} limit={LIMIT} onPage={setInvoicesPage} />
                </>
              )}
            </div>
          </details>

          {/* Inventory */}
          <details className="tree-node">
            <summary className="tree-summary">📦 Inventory Stock ({inventoryList.length} items)</summary>
            <div className="tree-content">
              {inventoryList.length === 0 ? (
                <div style={{ color: 'var(--secondary-text)', padding: '10px 0' }}>No inventory records.</div>
              ) : (
                <>
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
                      {slicedInventory.map((item, i) => (
                        <tr key={i}>
                          <td style={{ fontWeight: 600, color: 'var(--accent-color)' }}>
                            {item.product_name || item.product}
                          </td>
                          <td>{item.stock} items</td>
                          <td>{item.expiry_date || item.expiry || 'N/A'}</td>
                          <td>{item.supplier || 'N/A'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <Pagination total={inventoryList.length} page={inventoryPage} limit={LIMIT} onPage={setInventoryPage} />
                </>
              )}
            </div>
          </details>

          {/* Payments */}
          <details className="tree-node">
            <summary className="tree-summary">💳 Logged Payments & Dues ({paymentsList.length})</summary>
            <div className="tree-content">
              {paymentsList.length === 0 ? (
                <div style={{ color: 'var(--secondary-text)', padding: '10px 0' }}>No payment entries.</div>
              ) : (
                <>
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
                      {slicedPayments.map((p, i) => (
                        <tr key={i}>
                          <td style={{ fontWeight: 500 }}>{p.customer}</td>
                          <td style={{ fontWeight: 600 }}>₹{(p.amount || 0).toLocaleString('en-IN')}</td>
                          <td>{p.due_date || 'N/A'}</td>
                          <td>
                            <span
                              className="tag"
                              style={{
                                background: p.paid === 'Yes' ? 'rgba(58,154,92,0.12)' : 'rgba(201,100,66,0.12)',
                                color: p.paid === 'Yes' ? '#3a9a5c' : 'var(--accent-color)',
                              }}
                            >
                              {p.paid === 'Yes' ? 'Paid' : 'Unpaid'}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <Pagination total={paymentsList.length} page={paymentsPage} limit={LIMIT} onPage={setPaymentsPage} />
                </>
              )}
            </div>
          </details>

          {/* Chat threads */}
          <details className="tree-node">
            <summary className="tree-summary">💬 Chat Threads History ({sessionKeys.length} sessions)</summary>
            <div className="tree-content" style={{ paddingTop: '14px', maxHeight: '450px', overflowY: 'auto' }}>
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
                          marginBottom: '12px',
                          border: '1px dashed var(--border-color)',
                          borderRadius: '8px',
                          padding: '6px 12px',
                          background: 'var(--input-bg)',
                        }}
                      >
                        <summary style={{ fontWeight: 600, fontSize: '13px', padding: '6px 0', cursor: 'pointer', color: 'var(--text-color)' }}>
                          {s.title}
                        </summary>
                        <div style={{ marginTop: '8px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                          {sortedMsgs.map((msg, idx) => (
                            <div key={idx} className={`chat-tree-bubble ${msg.role}`}>
                              <span
                                style={{
                                  fontWeight: 600,
                                  fontSize: '10px',
                                  textTransform: 'uppercase',
                                  color: msg.role === 'user' ? 'var(--accent-color)' : '#3a9a5c',
                                  display: 'block',
                                  marginBottom: '2px',
                                }}
                              >
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
      </div>

      {/* MULTI-STEP DELETE DATABASE MODAL */}
      {showDeleteModal && (
        <div className="custom-modal-overlay">
          {deleteStep === 0 && (
            <div
              style={{
                background: 'var(--card-color)',
                borderRadius: '12px',
                padding: '32px',
                maxWidth: '450px',
                width: '90%',
                boxShadow: '0 16px 48px rgba(0,0,0,0.3)',
                border: '2px solid rgba(201,66,66,0.3)',
              }}
            >
              <div style={{ fontSize: '24px', fontWeight: 700, marginBottom: '12px', color: '#c94242' }}>
                ⚠ Delete Entire Database?
              </div>
              <div style={{ fontSize: '14px', lineHeight: 1.6, marginBottom: '24px', color: 'var(--secondary-text)' }}>
                This will <strong>permanently delete</strong> all data:
                <br />• All invoices
                <br />• All inventory records
                <br />• All payment history
                <br />• All uploads
                <br />
                <br />
                <span style={{ color: '#c94242', fontWeight: 600 }}>This action CANNOT be undone.</span>
              </div>
              <div style={{ display: 'flex', gap: '12px' }}>
                <button
                  onClick={() => setShowDeleteModal(false)}
                  style={{
                    flex: 1,
                    padding: '12px',
                    borderRadius: '8px',
                    border: '1px solid var(--border-color)',
                    background: 'transparent',
                    color: 'var(--text-color)',
                    cursor: 'pointer',
                    fontWeight: 600,
                  }}
                >
                  Cancel
                </button>
                <button
                  onClick={() => setDeleteStep(1)}
                  style={{
                    flex: 1,
                    padding: '12px',
                    borderRadius: '8px',
                    border: 'none',
                    background: '#c94242',
                    color: 'white',
                    cursor: 'pointer',
                    fontWeight: 600,
                  }}
                >
                  I Understand, Delete
                </button>
              </div>
            </div>
          )}

          {deleteStep === 1 && (
            <div
              style={{
                background: 'var(--card-color)',
                borderRadius: '12px',
                padding: '32px',
                maxWidth: '450px',
                width: '90%',
                boxShadow: '0 16px 48px rgba(0,0,0,0.3)',
                border: '2px solid rgba(201,66,66,0.3)',
              }}
            >
              <div style={{ fontSize: '20px', fontWeight: 700, marginBottom: '16px', color: '#c94242' }}>
                Final Confirmation Required
              </div>
              <div style={{ fontSize: '13px', lineHeight: 1.6, marginBottom: '20px', color: 'var(--secondary-text)' }}>
                Type the word <strong style={{ color: '#c94242' }}>DELETE</strong> below to confirm permanent deletion.
              </div>
              <input
                id="deleteConfirmInput"
                type="text"
                value={deleteInput}
                onChange={e => setDeleteInput(e.target.value)}
                placeholder="Type DELETE..."
                style={{
                  width: '100%',
                  padding: '12px',
                  borderRadius: '8px',
                  border: '1px solid var(--border-color)',
                  background: 'var(--input-bg)',
                  color: 'var(--text-color)',
                  fontSpace: '14px',
                  marginBottom: '20px',
                  boxSizing: 'border-box',
                }}
                autoFocus
              />
              <div style={{ display: 'flex', gap: '12px' }}>
                <button
                  onClick={() => setShowDeleteModal(false)}
                  style={{
                    flex: 1,
                    padding: '12px',
                    borderRadius: '8px',
                    border: '1px solid var(--border-color)',
                    background: 'transparent',
                    color: 'var(--text-color)',
                    cursor: 'pointer',
                    fontWeight: 600,
                  }}
                >
                  Cancel
                </button>
                <button
                  disabled={deleteInput.toUpperCase() !== 'DELETE'}
                  onClick={executeWipeDatabase}
                  style={{
                    flex: 1,
                    padding: '12px',
                    borderRadius: '8px',
                    border: 'none',
                    background: '#c94242',
                    color: 'white',
                    cursor: deleteInput.toUpperCase() === 'DELETE' ? 'pointer' : 'not-allowed',
                    fontWeight: 600,
                    opacity: deleteInput.toUpperCase() === 'DELETE' ? 1 : 0.5,
                  }}
                >
                  Delete Permanently
                </button>
              </div>
            </div>
          )}

          {deleteStep === 2 && (
            <div
              style={{
                background: 'var(--card-color)',
                borderRadius: '12px',
                padding: '32px',
                maxWidth: '450px',
                width: '90%',
                boxShadow: '0 16px 48px rgba(0,0,0,0.3)',
                textAlign: 'center',
              }}
            >
              <div style={{ fontSize: '16px', fontWeight: 600, marginBottom: '16px' }}>Deleting database...</div>
              <div
                style={{
                  width: '40px',
                  height: '40px',
                  borderRadius: '50%',
                  border: '4px solid var(--border-color)',
                  borderTopColor: '#c94242',
                  animation: 'spin 1s linear infinite',
                  margin: '0 auto',
                }}
              ></div>
            </div>
          )}

          {deleteStep === 3 && (
            <div
              style={{
                background: 'var(--card-color)',
                borderRadius: '12px',
                padding: '32px',
                maxWidth: '450px',
                width: '90%',
                boxShadow: '0 16px 48px rgba(0,0,0,0.3)',
                textAlign: 'center',
                border: '2px solid rgba(76,175,80,0.3)',
              }}
            >
              <div style={{ fontSize: '24px', marginBottom: '16px' }}>✓</div>
              <div style={{ fontSize: '18px', fontWeight: 700, marginBottom: '8px', color: '#4caf50' }}>
                Database Deleted
              </div>
              <div style={{ fontSize: '13px', color: 'var(--secondary-text)', marginBottom: '24px' }}>
                All data has been permanently removed.
              </div>
              <button
                onClick={() => {
                  setShowDeleteModal(false)
                  loadDatabase()
                }}
                style={{
                  width: '100%',
                  padding: '12px',
                  borderRadius: '8px',
                  border: 'none',
                  background: '#4caf50',
                  color: 'white',
                  cursor: 'pointer',
                  fontWeight: 600,
                }}
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
            background: 'rgba(0,0,0,0.55)',
            backdropFilter: 'blur(10px)',
            WebkitBackdropFilter: 'blur(10px)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            padding: '24px',
            animation: 'fadeIn 0.2s ease'
          }}
          onClick={closePreview}
        >
          <div
            style={{
              background: 'var(--card-color)',
              border: '1.5px solid var(--glass-border)',
              borderRadius: '16px',
              boxShadow: 'var(--shadow-lg)',
              width: '100%', maxWidth: '860px',
              maxHeight: '85vh',
              display: 'flex', flexDirection: 'column',
              overflow: 'hidden',
              animation: 'slideUp 0.25s cubic-bezier(0.16,1,0.3,1)'
            }}
            onClick={e => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div style={{
              padding: '16px 20px',
              borderBottom: '1px solid var(--border-color)',
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              flexShrink: 0
            }}>
              <div>
                <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--text-color)' }}>
                  📄 {preview.filename}
                </div>
                <div style={{ fontSize: 12, color: 'var(--secondary-text)', marginTop: 3 }}>
                  {preview.file_type} · {preview.total_rows} rows
                </div>
              </div>
              <button
                onClick={closePreview}
                style={{
                  border: 'none', background: 'transparent',
                  fontSize: 22, cursor: 'pointer',
                  color: 'var(--secondary-text)', lineHeight: 1,
                  padding: '4px 8px', borderRadius: 6
                }}
              >✕</button>
            </div>

            {/* Modal Body */}
            <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px' }}>
              {previewLoading || preview.loading ? (
                <div style={{ textAlign: 'center', padding: '40px', color: 'var(--secondary-text)' }}>
                  <div style={{
                    width: 32, height: 32, border: '3px solid var(--border-color)',
                    borderTopColor: 'var(--accent-color)', borderRadius: '50%',
                    animation: 'spin 0.8s linear infinite', margin: '0 auto 12px'
                  }} />
                  Loading file data...
                </div>
              ) : preview.error ? (
                <div style={{ textAlign: 'center', padding: 32, color: '#c94242' }}>
                  ⚠ {preview.error}
                </div>
              ) : preview.rows.length === 0 ? (
                <div style={{ textAlign: 'center', padding: 32, color: 'var(--secondary-text)' }}>
                  No records found for this file.
                </div>
              ) : (
                <>
                  <div className="database-table">
                    <table>
                      <thead>
                        <tr>
                          <th style={{ width: 36, textAlign: 'center', color: 'var(--secondary-text)', fontWeight: 500 }}>#</th>
                          {preview.columns.map(col => (
                            <th key={col} style={{ textTransform: 'uppercase', fontSize: 10.5, letterSpacing: '0.05em' }}>
                              {col.replace(/_/g, ' ')}
                            </th>
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
                                  const isPosive = val === 'Paid' || val === 'Yes'
                                  return (
                                    <td key={col}>
                                      <span className="tag" style={{
                                        background: isPosive ? 'rgba(58,154,92,0.12)' : 'rgba(201,100,66,0.12)',
                                        color: isPosive ? '#3a9a5c' : 'var(--accent-color)'
                                      }}>
                                        {isPosive ? (col === 'paid' ? 'Paid' : val) : (col === 'paid' ? 'Unpaid' : val)}
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

                  {/* Pagination */}
                  <Pagination
                    total={preview.rows.length}
                    page={previewPage}
                    limit={PREVIEW_LIMIT}
                    onPage={setPreviewPage}
                  />
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  )
}
