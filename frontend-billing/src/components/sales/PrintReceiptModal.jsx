import React, { useEffect, useId, useRef } from 'react'
import { createPortal } from 'react-dom'
import { DownloadIcon, PrinterIcon } from '../Icons'
import './printReceiptModal.css'
import { RECEIPT_PRINT_START, RECEIPT_PRINT_END } from '../../utils/receiptPrintEvents'

export default function PrintReceiptModal({ job, onPrint, onPreparePdf, onDone }) {
  const dialogRef = useRef(null)
  const printRef = useRef(null)
  const callbacks = useRef({ onPrint, onDone })
  callbacks.current = { onPrint, onDone }
  const headingId = useId()
  const descriptionId = useId()
  const printDisabled = job?.format === 'pdf' && job?.status === 'preparing'
  const disabledRef = useRef(printDisabled)
  const printEscapeGuard = useRef(0)
  disabledRef.current = printDisabled

  useEffect(() => {
    if (!job) return undefined
    const previousFocus = document.activeElement
    const focusPrint = () => {
      const target = printRef.current?.disabled ? dialogRef.current : printRef.current
      target?.focus()
    }
    const onKey = event => {
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopImmediatePropagation()
        // Some hosts forward the Escape used to cancel native print preview
        // back to the page. Keep the saved receipt available for retry.
        if (Date.now() < printEscapeGuard.current) return
        callbacks.current.onDone?.()
      } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'p') {
        // Capture this before the counter's Ctrl+P save shortcut: this invoice
        // is already saved, so the shortcut must only print this document.
        event.preventDefault()
        event.stopImmediatePropagation()
        if (!disabledRef.current) callbacks.current.onPrint?.()
      } else if (event.key === 'Enter') {
        // Preserve the focused button's native action, including Done.
        event.stopPropagation()
      } else if (event.key === 'Tab') {
        const dialog = dialogRef.current
        const controls = dialog?.querySelectorAll('button:not([disabled]), a[href], [tabindex="0"]') || []
        const first = controls[0]
        const last = controls[controls.length - 1]
        const active = document.activeElement
        const outside = !dialog?.contains(active) || active === dialog
        if (!first) {
          event.preventDefault()
          dialog?.focus()
        } else if (event.shiftKey && (active === first || outside)) {
          event.preventDefault()
          last.focus()
        } else if (!event.shiftKey && (active === last || outside)) {
          event.preventDefault()
          first.focus()
        }
        event.stopPropagation()
      }
    }
    const keepFocus = event => {
      // A prepared PDF's print frame needs focus when native printing opens.
      if (event.target?.matches?.('iframe[data-invoice-print]')) return
      if (dialogRef.current && !dialogRef.current.contains(event.target)) focusPrint()
    }
    window.addEventListener('keydown', onKey, true)
    const beforePrint = () => { printEscapeGuard.current = Infinity }
    const afterPrint = () => { printEscapeGuard.current = Date.now() + 500 }
    window.addEventListener('beforeprint', beforePrint)
    window.addEventListener('afterprint', afterPrint)
    window.addEventListener(RECEIPT_PRINT_START, beforePrint)
    window.addEventListener(RECEIPT_PRINT_END, afterPrint)
    document.addEventListener('focusin', keepFocus, true)
    focusPrint()
    return () => {
      window.removeEventListener('keydown', onKey, true)
      window.removeEventListener('beforeprint', beforePrint)
      window.removeEventListener('afterprint', afterPrint)
      window.removeEventListener(RECEIPT_PRINT_START, beforePrint)
      window.removeEventListener(RECEIPT_PRINT_END, afterPrint)
      document.removeEventListener('focusin', keepFocus, true)
      if (previousFocus?.isConnected) previousFocus.focus?.()
    }
  }, [Boolean(job), job?.invoiceNo, job?.format])

  if (!job) return null

  return createPortal(
    <div className="pos-receipt-print-overlay no-print">
      <section className="pos-receipt-print-dialog" role="dialog" aria-modal="true"
        aria-labelledby={headingId} aria-describedby={descriptionId} tabIndex={-1} ref={dialogRef}>
        <div className="pos-receipt-print-heading">
          <span className="pos-receipt-print-icon"><PrinterIcon size={23} /></span>
          <div>
            <span className="pos-receipt-print-saved">{job.offline ? 'Saved on this device' : 'Invoice saved'}</span>
            <h2 id={headingId}>Invoice saved — print receipt</h2>
          </div>
        </div>
        <div className="pos-receipt-print-document">
          <div><span>Invoice number</span><strong>{job.invoiceNo}</strong></div>
          <span className="badge">{job.format === 'thermal' ? 'Thermal receipt' : 'PDF invoice'}</span>
        </div>
        <p id={descriptionId} className="pos-receipt-print-help">
          Your invoice is already saved. Print or download it below; these actions only use the saved receipt.
        </p>
        <p className="pos-receipt-print-status" role="status" aria-live="polite">
          {job.status === 'preparing' ? 'Preparing your receipt…' : 'Your receipt is ready to print.'}
        </p>
        {job.error && <p className="pos-receipt-print-error" role="alert">{job.error}</p>}
        <div className="pos-receipt-print-actions">
          <button type="button" className="btn btn-primary" ref={printRef}
            onClick={onPrint} disabled={printDisabled}>
            <PrinterIcon size={18} /> Print receipt
          </button>
          {job.pdfUrl ? <>
            <a className="btn btn-secondary" href={job.pdfUrl} target="_blank" rel="noopener noreferrer">Open PDF</a>
            <a className="btn btn-secondary" href={job.pdfUrl} download={`${job.invoiceNo}.pdf`}>
              <DownloadIcon size={17} /> Download PDF
            </a>
          </> : !job.offline && (
            <button type="button" className="btn btn-secondary" onClick={onPreparePdf}
              disabled={job.pdfLoading} aria-busy={job.pdfLoading}>
              {job.pdfLoading ? 'Preparing PDF…' : 'Prepare PDF'}
            </button>
          )}
        </div>
        <p className="pos-receipt-print-help">
          If a print dialog does not open, use Open PDF or Download PDF, then print from your browser or PDF app.
        </p>
        {job.offline && <p className="pos-receipt-print-offline">PDF download needs a connection. The saved bill will sync when you are back online.</p>}
        <div className="pos-receipt-print-footer">
          <button type="button" className="btn btn-secondary" onClick={onDone}>Done</button>
        </div>
      </section>
    </div>,
    document.body,
  )
}
