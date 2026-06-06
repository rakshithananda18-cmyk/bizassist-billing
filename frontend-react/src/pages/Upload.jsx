import { useState, useEffect, useRef } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { API_BASE } from '../config'
import { useDialog } from '../contexts/DialogContext'

const ACCEPTED = '.csv,.xlsx,.pdf'

export default function Upload() {
  const { authFetch } = useAuth()
  const { showAlert, showConfirm, showError } = useDialog()
  const [uploads,   setUploads]   = useState([])
  const [dragging,  setDragging]  = useState(false)
  const [uploading, setUploading] = useState(false)
  const [progress,  setProgress]  = useState('')
  const [result,    setResult]    = useState(null)  // { ok, message }
  const inputRef = useRef(null)

  useEffect(() => { loadUploads() }, [])

  async function loadUploads() {
    try {
      const res  = await authFetch(`${API_BASE}/uploads`)
      const data = await res.json()
      setUploads(Array.isArray(data) ? data : [])
    } catch {}
  }

  async function handleFile(file) {
    if (!file) return
    const ext = file.name.split('.').pop().toLowerCase()
    if (!['csv', 'xlsx', 'pdf'].includes(ext)) {
      setResult({ ok: false, message: 'Unsupported file type. Use CSV, XLSX, or PDF.' })
      return
    }

    setUploading(true)
    setResult(null)
    setProgress(`Uploading ${file.name}…`)

    const form = new FormData()
    form.append('file', file)

    try {
      const res  = await authFetch(`${API_BASE}/upload`, { method: 'POST', body: form })
      const data = await res.json()

      if (res.status === 409) {
        setResult({ ok: false, message: `Duplicate file: ${data.detail}` })
        return
      }
      if (!res.ok) {
        throw new Error(data.detail || `Upload failed (${res.status})`)
      }

      setResult({
        ok: true,
        message: `✅ Uploaded successfully — ${data.rows} rows · type: ${data.file_type}`
      })
      loadUploads()
      window.dispatchEvent(new CustomEvent('data-updated'))
    } catch (err) {
      setResult({ ok: false, message: `❌ ${err.message}` })
    } finally {
      setUploading(false)
      setProgress('')
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  async function deleteUpload(id, filename) {
    const confirmed = await showConfirm(`Delete "${filename}"? This cannot be undone.`)
    if (!confirmed) return
    try {
      await authFetch(`${API_BASE}/upload/${id}`, { method: 'DELETE' })
      loadUploads()
      window.dispatchEvent(new CustomEvent('data-updated'))
    } catch (err) {
      await showError(err, 'Delete failed')
    }
  }

  // Drag & drop
  const onDragOver  = e => { e.preventDefault(); setDragging(true) }
  const onDragLeave = () => setDragging(false)
  const onDrop      = e => {
    e.preventDefault()
    setDragging(false)
    handleFile(e.dataTransfer.files[0])
  }

  const typeColors = {
    invoice:   { bg: 'rgba(58,154,92,0.10)',  color: '#3a9a5c' },
    inventory: { bg: 'rgba(74,144,201,0.10)', color: '#4a90c9' },
    payment:   { bg: 'rgba(201,124,34,0.10)', color: '#c97c22' },
  }

  return (
    <>
      {/* PAGE HEADER */}
      <div className="vheader">
        <div>
          <div className="vheader-title">Upload Data</div>
          <div className="vheader-sub">CSV, Excel, or PDF invoice files</div>
        </div>
      </div>

      {/* DROP ZONE */}
      <div
        className={`drop-zone ${dragging ? 'dragging' : ''} ${uploading ? 'uploading' : ''}`}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        onClick={() => !uploading && inputRef.current?.click()}
        style={{ marginBottom: 16 }}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED}
          style={{ display: 'none' }}
          onChange={e => handleFile(e.target.files[0])}
        />
        {uploading ? (
          <>
            <svg className="control-btn-spinner" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10" stroke="rgba(128, 128, 128, 0.25)" strokeWidth="2.5" fill="none" />
              <path d="M12 2a10 10 0 0 1 10 10" />
            </svg>
            <div className="drop-label">{progress}</div>
          </>
        ) : (
          <>
            <div className="drop-icon">📁</div>
            <div className="drop-label">
              {dragging ? 'Drop to upload' : 'Drag & drop or click to select'}
            </div>
            <div className="drop-sub">CSV · XLSX · PDF</div>
          </>
        )}
      </div>

      {/* RESULT MESSAGE */}
      {result && (
        <div className={`upload-result ${result.ok ? 'success' : 'error'}`} style={{ marginBottom: 16 }}>
          {result.message}
        </div>
      )}

      {/* FORMAT GUIDE */}
      <div className="widget" style={{ marginBottom: 16 }}>
        <div className="widget-title">Supported Formats</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12, marginTop: 12 }}>
          {[
            { icon: '📄', name: 'Invoices CSV/XLSX', cols: 'invoice_id, customer, product, amount, status, due_date' },
            { icon: '📦', name: 'Inventory CSV/XLSX', cols: 'product_name, stock, expiry_date, supplier' },
            { icon: '💳', name: 'Payments CSV/XLSX', cols: 'customer, amount, due_date, paid' },
            { icon: '📋', name: 'PDF Invoice', cols: 'Any structured invoice PDF — AI extracts the data' },
          ].map(f => (
            <div key={f.name} style={{
              background: 'var(--accent-softer)',
              borderRadius: 10, padding: '12px 14px',
              border: '1px solid var(--border-subtle)'
            }}>
              <div style={{ fontSize: 22, marginBottom: 6 }}>{f.icon}</div>
              <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4 }}>{f.name}</div>
              <div style={{ fontSize: 11, color: 'var(--secondary-text)', fontFamily: "'DM Mono', monospace" }}>{f.cols}</div>
            </div>
          ))}
        </div>
      </div>

      {/* UPLOAD HISTORY */}
      <div className="widget">
        <div className="widget-title" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span>Upload History</span>
          <span style={{ fontSize: 12, color: 'var(--secondary-text)', fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}>
            {uploads.length} file{uploads.length !== 1 ? 's' : ''}
          </span>
        </div>

        {uploads.length === 0 ? (
          <div className="empty-upload">No uploaded files yet</div>
        ) : (
          <div style={{ marginTop: 8 }}>
            {uploads.map(f => {
              const type = f.type || f.file_type || 'invoice'
              const tc = typeColors[type] || { bg: 'var(--tag-bg)', color: 'var(--accent-color)' }
              return (
                <div key={f.id} className="upload-item">
                  <div className="upload-top">
                    <strong style={{ fontSize: 13.5, color: 'var(--text-color)' }}>{f.filename}</strong>
                    <span className="upload-badge" style={{ background: tc.bg, color: tc.color }}>
                      {type}
                    </span>
                    <button
                      className="delete-btn"
                      onClick={() => deleteUpload(f.id, f.filename)}
                      title="Delete file"
                    >✕</button>
                  </div>
                  <div className="upload-meta">
                    {f.rows ?? f.rows_count} rows • {f.uploaded ?? f.upload_time}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </>
  )
}
