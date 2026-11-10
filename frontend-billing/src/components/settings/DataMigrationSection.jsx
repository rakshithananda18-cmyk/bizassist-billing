// ============================================================================
// DataMigrationSection.jsx
// Description: Bulk data manager embedded in Settings. Handles uploading CSV
//              templates for products, customers, and vendors, and exporting
//              billing ledgers.
// ============================================================================
import React, { useRef, useState } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import ImportReviewModal from '../ImportReviewModal'
import { SectionHeader } from './SettingsPrimitives'
import {
  ImportIcon,
  DownloadIcon,
  InventoryIcon,
  ContactsIcon,
  BillsIcon,
  CounterIcon,
  CashIcon,
  SummaryIcon,
  AlertIcon,
} from '../Icons'

/* ── helpers ───────────────────────────────────── */
function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  try { a.click() } finally { a.remove() }
  // Give the browser time to consume the download before releasing its blob.
  setTimeout(() => URL.revokeObjectURL(url), 60000)
}

/* ── DragDropCard ───────────────────────────────── */
function DragDropCard({ icon, title, description, templateHref, endpoint, onSuccess, onError, authFetch, reviewFlow = false, onPreviewReady }) {
  const fileRef = useRef()
  const [dragOver, setDragOver] = useState(false)
  const [file, setFile] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [result, setResult] = useState(null) // {type:'success'|'danger', msg}

  const pickFile = (f) => {
    setResult(null)
    if (!f) return
    setFile(null)
    if (!/\.csv$/i.test(f.name)) {
      setResult({ type: 'danger', msg: 'Choose a CSV file using the downloaded template.' })
      return
    }
    if (f.size > 10 * 1024 * 1024) {
      setResult({ type: 'danger', msg: 'CSV files must be 10 MB or smaller.' })
      return
    }
    setFile(f)
  }

  const handleUpload = async () => {
    if (!file) return
    setUploading(true)
    setResult(null)
    const fd = new FormData()
    fd.append('file', file)
    try {
      // Approval flow: with reviewFlow the file is only PARSED (?preview=1) —
      // the parent shows the editable review table and commits separately.
      const url = reviewFlow ? `${endpoint}?preview=1` : endpoint
      const res = await authFetch(url, { method: 'POST', headers: {}, body: fd })
      if (res.ok) {
        const data = await res.json().catch(() => ({}))
        if (reviewFlow) {
          if (data.preview !== true || !Array.isArray(data.items)) {
            setResult({ type: 'danger', msg: 'The server did not return an import review. Check your records before retrying.' })
            return
          }
          setResult({ type: 'success', msg: `${data.count} row(s) parsed — review before anything is saved.` })
          setFile(null)
          onPreviewReady?.(data.items || [])
        } else {
          const count = data.count ?? data.imported ?? data.rows ?? '?'
          setResult({ type: 'success', msg: `Imported ${count} records successfully!` })
          setFile(null)
          if (onSuccess) onSuccess(data)
        }
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
        role="button"
        tabIndex={uploading ? -1 : 0}
        aria-label={`Choose ${title} CSV`}
        onKeyDown={e => {
          if (!uploading && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault()
            fileRef.current?.click()
          }
        }}
        onDragOver={e => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={e => { e.preventDefault(); setDragOver(false); pickFile(e.dataTransfer?.files?.[0]) }}
        onClick={() => !uploading && fileRef.current?.click()}
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
        aria-label={`${title} CSV file`}
        accept=".csv"
        disabled={uploading}
        style={{ display: 'none' }}
        onChange={e => { pickFile(e.target.files?.[0]); e.target.value = '' }}
      />

      <div className="flex items-center gap-2">
        {templateHref && (
          <a
            href={templateHref}
            download={`${title.toLowerCase()}_template.csv`}
            className="btn btn-secondary btn-sm"
            style={{ flex: 1, justifyContent: 'center' }}
            onClick={e => e.stopPropagation()}
          >
            <span>Download Template</span>
          </a>
        )}
        <button
          type="button"
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

      <button type="button" className="btn btn-secondary btn-sm w-full" disabled={exporting} onClick={handleExport} style={{ justifyContent: 'center' }}>
        {exporting
          ? <><span className="spinner" style={{ width: 13, height: 13, borderWidth: 2 }} /> Exporting…</>
          : 'Export CSV'}
      </button>
    </div>
  )
}

/* ── DataMigrationSection ───────────────────────── */
export default function DataMigrationSection() {
  const { authFetch } = useAuth()

  // Approval flow: parse-only preview → editable review table → explicit approve → commit.
  const [reviewItems, setReviewItems] = useState(null)   // rows awaiting approval
  const [reviewCtx, setReviewCtx] = useState(null)       // {endpoint, columns, label}
  const [committing, setCommitting] = useState(false)
  const [commitResult, setCommitResult] = useState(null)
  const commitInFlight = useRef(false)

  const commitApproved = async (approvedRows) => {
    if (commitInFlight.current || !reviewCtx || !approvedRows?.length) return
    const ctx = reviewCtx
    commitInFlight.current = true
    setCommitting(true)
    try {
      const res = await authFetch(ctx.endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items: approvedRows }),
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok) {
        const errs = data.errors?.length ? ` (${data.errors.length} row(s) skipped: ${data.errors.slice(0, 3).join('; ')}${data.errors.length > 3 ? '…' : ''})` : ''
        setCommitResult({ type: 'success', msg: `Imported ${data.created ?? data.count ?? approvedRows.length} ${ctx.label}(s).${errs}` })
        setReviewItems(null)
      } else {
        setCommitResult({ type: 'danger', msg: data.detail || 'Import failed. Check your records before retrying.' })
      }
    } catch {
      setCommitResult({ type: 'danger', msg: 'The import result could not be confirmed. Check your records before retrying.' })
    } finally {
      commitInFlight.current = false
      setCommitting(false)
    }
  }

  const openReview = (endpoint, columns, label) => (items) => {
    setCommitResult(null)
    setReviewCtx({ endpoint, columns, label })
    setReviewItems(items)
  }

  const CUSTOMER_COLUMNS = [
    { field: 'name', label: 'Name *' }, { field: 'phone', label: 'Phone' },
    { field: 'email', label: 'Email' }, { field: 'address', label: 'Address' },
    { field: 'gstin', label: 'GSTIN' }, { field: 'state_code', label: 'State' },
    { field: 'pan', label: 'PAN' },
    { field: 'credit_limit', label: 'Credit ₹', num: true },
    { field: 'credit_days', label: 'Cr. days', num: true },
    { field: 'opening_dues', label: 'Op. dues ₹', num: true },
  ]
  const VENDOR_COLUMNS = [
    { field: 'name', label: 'Name *' }, { field: 'phone', label: 'Phone' },
    { field: 'email', label: 'Email' }, { field: 'address', label: 'Address' },
    { field: 'gstin', label: 'GSTIN' }, { field: 'state_code', label: 'State' },
    { field: 'pan', label: 'PAN' },
    { field: 'payment_terms_days', label: 'Pay terms (d)', num: true },
  ]

  const IMPORT_CONFIGS = [
    {
      icon: <InventoryIcon size={18} />,
      title: 'Products',
      description: 'Import product catalogue with SKU, price, and stock levels. Every file goes through an editable review table — nothing is saved without your approval.',
      endpoint: '/billing/import/products',
      templateHref: 'data:text/csv;charset=utf-8,name,sku,barcode,hsn_sac,unit,description,brand,manufacturer,category,selling_price,wholesale_price,distributor_price,cost_price,mrp,cgst_rate,sgst_rate,igst_rate,opening_stock',
      reviewFlow: true,
      onPreviewReady: openReview('/billing/import/products', undefined, 'product'),
    },
    {
      icon: <ContactsIcon size={18} />,
      title: 'Customers',
      description: 'Import customer list with contact info and GSTIN. Reviewed before anything is saved — duplicates flagged.',
      endpoint: '/billing/import/customers',
      templateHref: 'data:text/csv;charset=utf-8,name,phone,email,address,gstin,state_code,pan,credit_limit,credit_days,opening_dues',
      reviewFlow: true,
      onPreviewReady: openReview('/billing/import/customers', CUSTOMER_COLUMNS, 'customer'),
    },
    {
      icon: <BillsIcon size={18} />,
      title: 'Vendors',
      description: 'Import supplier / vendor list with payment terms. Reviewed before anything is saved — duplicates flagged.',
      endpoint: '/billing/import/vendors',
      templateHref: 'data:text/csv;charset=utf-8,name,phone,email,address,gstin,state_code,pan,payment_terms_days',
      reviewFlow: true,
      onPreviewReady: openReview('/billing/import/vendors', VENDOR_COLUMNS, 'vendor'),
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
    <>
      <SectionHeader
        title="Data Migration & Backup"
        description="Bulk import data from CSV templates or export system ledgers for external reporting, analysis and offline backups."
      />

      {commitResult && (
        <div className={`alert alert-${commitResult.type} mb-4`}>{commitResult.msg}</div>
      )}

      {/* Approval table — shown after a preview parse (products/customers/vendors) */}
      <ImportReviewModal
        open={reviewItems != null}
        items={reviewItems || []}
        columns={reviewCtx?.columns}
        entityLabel={reviewCtx?.label || 'row'}
        committing={committing}
        onCancel={() => setReviewItems(null)}
        onCommit={commitApproved}
      />

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
              • Review duplicate and validation warnings before approving rows.<br />
              • Maximum file size: 10 MB per import.
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
