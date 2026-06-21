import React, { useRef, useState } from 'react'
import AppLayout from '../layouts/AppLayout'
import { useAuth } from '../contexts/AuthContext'
import {
  ImportIcon,
  DownloadIcon,
  InventoryIcon,
  ContactsIcon,
  BillsIcon,
  CounterIcon,
  CashIcon,
  TaxIcon,
  SummaryIcon,
  AlertIcon
} from '../components/Icons'

/* ── helpers ───────────────────────────────────── */
function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

/* ── DragDropCard ───────────────────────────────── */
function DragDropCard({ icon, title, description, templateHref, endpoint, onSuccess, onError, authFetch }) {
  const fileRef = useRef()
  const [dragOver, setDragOver] = useState(false)
  const [file, setFile] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [result, setResult] = useState(null) // {type:'success'|'danger', msg}

  const pickFile = (f) => { if (f) setFile(f); setResult(null) }

  const handleUpload = async () => {
    if (!file) return
    setUploading(true)
    setResult(null)
    const fd = new FormData()
    fd.append('file', file)
    try {
      const res = await authFetch(endpoint, { method: 'POST', headers: {}, body: fd })
      if (res.ok) {
        const data = await res.json().catch(() => ({}))
        const count = data.count ?? data.imported ?? data.rows ?? '?'
        setResult({ type: 'success', msg: `Imported ${count} records successfully!` })
        setFile(null)
        if (onSuccess) onSuccess(data)
      } else {
        const err = await res.json().catch(() => ({}))
        setResult({ type: 'danger', msg: `${err.detail || 'Import failed.'}` })
        if (onError) onError(err)
      }
    } catch {
      setResult({ type: 'danger', msg: 'Network error during upload.' })
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div className="flex items-center gap-3">
        <span style={{ display: 'flex', color: 'var(--text-muted)' }}>{icon}</span>
        <div>
          <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{title}</div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: 2 }}>{description}</div>
        </div>
      </div>

      {result && (
        <div className={`alert alert-${result.type}`} style={{ marginBottom: 0 }}>
          {result.msg}
        </div>
      )}

      {/* Drop zone */}
      <div
        onDragOver={e => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={e => { e.preventDefault(); setDragOver(false); pickFile(e.dataTransfer?.files?.[0]) }}
        onClick={() => fileRef.current?.click()}
        style={{
          border: `2px dashed ${dragOver ? 'var(--accent)' : 'var(--border)'}`,
          borderRadius: 'var(--radius-md)',
          padding: '20px 12px',
          textAlign: 'center',
          cursor: 'pointer',
          background: dragOver ? 'var(--accent-dim)' : 'var(--bg-3)',
          transition: 'all 180ms ease',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 6, color: 'var(--text-muted)' }}>
          {dragOver ? <DownloadIcon size={20} /> : <ImportIcon size={20} />}
        </div>
        <div style={{ fontSize: '0.8rem', color: file ? 'var(--text-primary)' : 'var(--text-muted)' }}>
          {file ? file.name : 'Click or drag CSV here'}
        </div>
        {file && (
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 3 }}>
            {(file.size / 1024).toFixed(1)} KB
          </div>
        )}
      </div>
      <input
        ref={fileRef}
        type="file"
        accept=".csv"
        style={{ display: 'none' }}
        onChange={e => pickFile(e.target.files?.[0])}
      />

      <div className="flex items-center gap-2">
        {templateHref && (
          <a
            href={templateHref}
            download
            className="btn btn-secondary btn-sm"
            style={{ flex: 1, justifyContent: 'center' }}
            onClick={e => e.stopPropagation()}
          >
            <span>Download Template</span>
          </a>
        )}
        <button
          className="btn btn-primary btn-sm"
          style={{ flex: 2, justifyContent: 'center' }}
          disabled={!file || uploading}
          onClick={handleUpload}
        >
          {uploading
            ? <><span className="spinner" style={{ width: 13, height: 13, borderWidth: 2 }} /> Uploading…</>
            : 'Import'}
        </button>
      </div>
    </div>
  )
}

/* ── ExportCard ─────────────────────────────────── */
function ExportCard({ icon, title, description, endpoint, filename, authFetch }) {
  const [exporting, setExporting] = useState(false)
  const [result, setResult] = useState(null)

  const handleExport = async () => {
    setExporting(true)
    setResult(null)
    try {
      const res = await authFetch(endpoint)
      if (res.ok) {
        const blob = await res.blob()
        const ext = filename.endsWith('.csv') ? '' : '.csv'
        triggerDownload(blob, filename + ext)
        setResult({ type: 'success', msg: 'Download started!' })
      } else if (res.status === 404) {
        setResult({ type: 'warning', msg: 'Export not available yet.' })
      } else {
        setResult({ type: 'danger', msg: 'Export failed.' })
      }
    } catch {
      setResult({ type: 'danger', msg: 'Network error.' })
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div className="flex items-center gap-3">
        <span style={{ display: 'flex', color: 'var(--text-muted)' }}>{icon}</span>
        <div>
          <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{title}</div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: 2 }}>{description}</div>
        </div>
      </div>

      {result && (
        <div className={`alert alert-${result.type}`} style={{ marginBottom: 0 }}>
          {result.msg}
        </div>
      )}

      <button className="btn btn-secondary btn-sm w-full" disabled={exporting} onClick={handleExport} style={{ justifyContent: 'center' }}>
        {exporting
          ? <><span className="spinner" style={{ width: 13, height: 13, borderWidth: 2 }} /> Exporting…</>
          : 'Export CSV'}
      </button>
    </div>
  )
}

/* ── Main page ──────────────────────────────────── */
export default function Import() {
  const { authFetch } = useAuth()

  const IMPORT_CONFIGS = [
    {
      icon: <InventoryIcon size={18} />,
      title: 'Products',
      description: 'Import product catalogue with SKU, price, and stock levels.',
      endpoint: '/billing/import/products',
      templateHref: '#',
    },
    {
      icon: <ContactsIcon size={18} />,
      title: 'Customers',
      description: 'Import customer list with contact info and GSTIN.',
      endpoint: '/billing/import/customers',
      templateHref: '#',
    },
    {
      icon: <BillsIcon size={18} />,
      title: 'Vendors',
      description: 'Import supplier / vendor list with payment terms.',
      endpoint: '/billing/import/vendors',
      templateHref: '#',
    },
  ]

  const EXPORT_CONFIGS = [
    {
      icon: <InventoryIcon size={18} />,
      title: 'Products',
      description: 'Export full product catalogue with pricing and stock.',
      endpoint: '/billing/export/products',
      filename: 'products_export.csv',
    },
    {
      icon: <CounterIcon size={18} />,
      title: 'Invoices',
      description: 'Export all sales invoices with line items and status.',
      endpoint: '/billing/export/invoices',
      filename: 'invoices_export.csv',
    },
    {
      icon: <CashIcon size={18} />,
      title: 'Payments',
      description: 'Export payment history with methods and references.',
      endpoint: '/billing/export/payments',
      filename: 'payments_export.csv',
    },
    {
      icon: <SummaryIcon size={18} />,
      title: 'Stock Ledger',
      description: 'Export complete stock movement history.',
      endpoint: '/billing/export/stock-ledger',
      filename: 'stock_ledger_export.csv',
    },
  ]

  return (
    <AppLayout title="Data Migration">
      <div className="slide-up">

        {/* Header */}
        <div className="page-header">
          <div className="page-header-left">
            <h1 className="page-title">Data Migration</h1>
            <p className="page-subtitle">Bulk import data from CSV or export records for backup and analysis</p>
          </div>
        </div>

        <div className="grid grid-2 gap-4">
          {/* ── Import section ── */}
          <div>
            <div className="flex items-center gap-2 mb-4">
              <span style={{ display: 'flex', color: 'var(--text-muted)' }}><ImportIcon size={16} /></span>
              <h2 style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--text-primary)' }}>Import Data</h2>
              <span className="badge badge-accent">CSV</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {IMPORT_CONFIGS.map(cfg => (
                <DragDropCard key={cfg.endpoint} {...cfg} authFetch={authFetch} />
              ))}
            </div>
          </div>

          {/* ── Export section ── */}
          <div>
            <div className="flex items-center gap-2 mb-4">
              <span style={{ display: 'flex', color: 'var(--text-muted)' }}><DownloadIcon size={16} /></span>
              <h2 style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--text-primary)' }}>Export Data</h2>
              <span className="badge badge-muted">CSV</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {EXPORT_CONFIGS.map(cfg => (
                <ExportCard key={cfg.endpoint} {...cfg} authFetch={authFetch} />
              ))}
            </div>
          </div>
        </div>

        {/* Info card */}
        <div className="card mt-6">
          <div className="flex items-center gap-3">
            <span style={{ display: 'flex', color: 'var(--text-muted)' }}><AlertIcon size={20} /></span>
            <div>
              <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>Import Guidelines</div>
              <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', lineHeight: 1.7 }}>
                • Download the template CSV to see required column headers and format.<br />
                • Dates should be in <span style={{ fontFamily: 'monospace', color: 'var(--text-secondary)' }}>YYYY-MM-DD</span> format.<br />
                • Prices should be in INR without currency symbols.<br />
                • Duplicate SKUs / phone numbers will be updated, not duplicated.<br />
                • Maximum file size: 10 MB per import.
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppLayout>
  )
}
