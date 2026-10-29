import { useState, useCallback, useRef, useEffect } from 'react'
import { logger } from '../utils/logger'
import { buildInvoicePayload } from '../utils/invoiceMath'
import { newClientRequestId } from '../sync/uuid'
import { IS_LOCAL_APP } from '../config'
import { getFromDateStr } from '../utils/format'
import { useConfirm } from '../contexts/ConfirmContext'
import { playSuccessChime } from '../utils/posAudio'
import { printInvoicePdf } from '../utils/printInvoicePdf'
import { requestReceiptPrint } from '../utils/receiptPrintEvents'

// Module-level save lock — shared across ALL instances of this hook.
// Prevents duplicate POSTs when React StrictMode mounts two instances
// simultaneously, or when the user double-clicks the Pay button.
// Key = invoice number, Value = true while in flight.
const _saveLock = new Map()

export default function usePaymentFlow({
  form,
  setForm,
  grandTotal,
  payable,
  cashDiscountAmt,
  gstAmt,
  billDiscountAmt,
  changeToReturn,
  activeTab,
  activeTabId,
  closeTab,
  setTabs,
  syncTabNames,
  setDbInvoices,
  settings,
  authFetch,
  setAlert,
  setSubmitting,
  barcodeRef,
  enqueueOffline,
  onReceiptReady,
  onReceiptClosed,
}) {
  const confirm = useConfirm()
  const [showPaymentPopup, setShowPaymentPopup] = useState(false)
  const [paymentFocusTarget, setPaymentFocusTarget] = useState('amountReceived')
  const [printJob, setPrintJob] = useState(null)
  const printWorkRef = useRef(null)
  const mountedRef = useRef(true)

  const disposePrintWork = useCallback(work => {
    if (!work) return
    clearTimeout(work.autoTimer)
    work.pendingAbort?.abort()
    work.pdfController?.dispose?.()
    if (work.info.pdfUrl) URL.revokeObjectURL(work.info.pdfUrl)
    work.releaseLock()
  }, [])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      const work = printWorkRef.current
      printWorkRef.current = null
      disposePrintWork(work)
    }
  }, [disposePrintWork])

  const updatePrintJob = useCallback((work, patch) => {
    if (printWorkRef.current !== work) return
    work.info = { ...work.info, ...patch }
    setPrintJob(work.info)
  }, [])

  const prepareSavedPdf = useCallback(async (work = printWorkRef.current) => {
    if (!work || work.info.offline || work.info.pdfLoading || work.info.pdfUrl) return
    updatePrintJob(work, { pdfLoading: true, error: null })
    const pending = new AbortController()
    work.pendingAbort = pending
    const timeout = setTimeout(() => pending.abort(), 20000)
    try {
      const response = await authFetch(`/sales/${encodeURIComponent(work.info.invoiceNo)}/pdf`, { signal: pending.signal })
      if (!response.ok) throw new Error('PDF request failed')
      const blob = await response.blob()
      clearTimeout(timeout)
      if (printWorkRef.current !== work) return
      if (pending.signal.aborted) throw new DOMException('PDF preparation cancelled', 'AbortError')
      // The server can return an HTML fallback with HTTP 200 when PDF rendering
      // is unavailable. Never expose that as a PDF download or active blob page.
      const mime = (blob.type || response.headers?.get?.('content-type') || '').split(';')[0].trim().toLowerCase()
      if (!blob.size || (mime && mime !== 'application/pdf')) throw new Error('PDF_UNAVAILABLE')
      const pdfUrl = URL.createObjectURL(blob)
      updatePrintJob(work, { pdfUrl, pdfLoading: false })
      if (work.info.format === 'pdf') {
        const controller = await printInvoicePdf(blob, { signal: pending.signal, retainUntilDisposed: true })
        if (printWorkRef.current !== work) { controller?.dispose?.(); return }
        work.pdfController = controller
      }
      updatePrintJob(work, { status: 'ready' })
    } catch (error) {
      if (printWorkRef.current === work) {
        logger.warn('[SALES] saved invoice PDF could not open', error)
        updatePrintJob(work, { pdfLoading: false, status: 'ready', error: error.message === 'PDF_UNAVAILABLE'
          ? 'The invoice is saved, but PDF generation is unavailable. Use Print receipt now, or retry Prepare PDF later.'
          : 'The invoice is saved. The PDF print window could not open. Retry Print, or open/download the PDF if available.' })
      }
    } finally { clearTimeout(timeout) }
  }, [authFetch, updatePrintJob])

  const printSavedInvoice = useCallback(() => {
    const work = printWorkRef.current
    if (!work) return
    clearTimeout(work.autoTimer)
    try {
      // Keep this call synchronous with the explicit Print click. A delayed
      // post-save print request can be ignored by browser/embedded policies.
      if (work.info.format === 'pdf' && work.pdfController) work.pdfController.print()
      else if (work.info.format === 'pdf' && work.info.pdfUrl) window.open(work.info.pdfUrl, '_blank', 'noopener')
      else requestReceiptPrint(() => window.print())
      updatePrintJob(work, { error: null })
    } catch (error) {
      updatePrintJob(work, { error: 'No print window opened. Open or download the PDF and print it from your browser.' })
    }
  }, [updatePrintJob])

  const closePrintJob = useCallback(() => {
    const work = printWorkRef.current
    printWorkRef.current = null
    disposePrintWork(work)
    setPrintJob(null)
    onReceiptClosed?.()
  }, [disposePrintWork, onReceiptClosed])

  const beginPrintJob = useCallback(({ invoiceNo, receiptForm, offline, releaseLock }) => {
    if (!mountedRef.current) return false
    disposePrintWork(printWorkRef.current)
    onReceiptReady?.({ invoiceNo, form: receiptForm })
    const format = offline || settings?.print?.thermal_printer_mode === true ? 'thermal' : 'pdf'
    const work = { releaseLock, info: { invoiceNo, format, offline, status: format === 'pdf' ? 'preparing' : 'ready', pdfLoading: false, pdfUrl: null, error: null } }
    printWorkRef.current = work
    setPrintJob(work.info)
    if (format === 'pdf') void prepareSavedPdf(work)
    else work.autoTimer = setTimeout(() => {
      if (printWorkRef.current !== work) return
      try { requestReceiptPrint(() => window.print()) } catch { updatePrintJob(work, { error: 'Automatic printing did not open. Use Print or open/download the PDF.' }) }
    }, 800)
    return true
  }, [disposePrintWork, onReceiptReady, prepareSavedPdf, settings, updatePrintJob])

  // Exactly-once save (R7b): one stable X-Client-Request-Id per bill (keyed by the
  // tab's invoice number). A retry after an ambiguous NETWORK failure reuses the
  // same id, so the backend replay wall collapses it to one invoice; a clean
  // success or a definitive (4xx) rejection clears the id so the next save is a
  // fresh intent. Persists across renders via a ref.
  const reqIdRef = useRef(new Map())
  const reqIdFor = (key) => {
    let id = reqIdRef.current.get(key)
    if (!id) { id = newClientRequestId(); reqIdRef.current.set(key, id) }
    return id
  }

  const handleSaveInvoice = useCallback(async (printAfterSave = false, skipConfirm = false) => {
    if (form.items.length === 0 || form.items.some(it => !it.product
      || !Number.isFinite(parseFloat(it.price)) || parseFloat(it.price) < 0
      || !Number.isFinite(parseFloat(it.qty)) || parseFloat(it.qty) <= 0)) {
      setAlert({ type: 'danger', msg: 'Please add items and complete all fields.' })
      return false
    }

    // Module-level lock: prevent duplicate saves from concurrent hook instances
    // (React StrictMode double-mount or rapid double-click on Pay button).
    const lockKey = activeTab.name
    if (_saveLock.has(lockKey)) {
      logger.warn('[SALES] duplicate save blocked for', lockKey)
      return false
    }
    _saveLock.set(lockKey, 'saving')
    
    const pay = (payable ?? grandTotal)
    const creditMode = form.payment_mode === 'credit'
    const tendered = form.amount_received !== '' && form.amount_received != null
      ? Number(form.amount_received) : (creditMode ? 0 : pay)
    if (!Number.isFinite(tendered) || tendered < 0 || !Number.isFinite(pay) || pay < 0) {
      _saveLock.delete(lockKey)
      setAlert({ type: 'danger', msg: 'Enter a valid amount received before saving.' })
      return false
    }
    // Preserve the actual partial tender and its cash/card/UPI method. Only
    // the amount applied to this bill is capped; the summary shows full cash
    // tender so change remains correct.
    let paidNow = Math.min(Math.round((tendered + Number.EPSILON) * 100) / 100, pay)
    let isCredit = creditMode || paidNow < pay
    // The form values that actually get saved. setForm is async, so when the
    // cashier flips to credit below we can't rely on the state update landing
    // before we build the payload — carry the override explicitly.
    let formForSave = form

    const releaseLock = () => { _saveLock.delete(lockKey) }

    if (!skipConfirm) {
      // Wrap in try/finally: if confirm() throws (e.g. the ConfirmProvider is
      // unmounted mid-flight) the lock must still be released so the POS isn't
      // left blocking the next save attempt.
      try {
        if (creditMode) {
          // Already on credit — just confirm the amount going on the books.
          const ok = await confirm({
            mode: 'update',
            title: 'Save on credit?',
            message: `Save on CREDIT — ₹${(pay - paidNow).toFixed(2)} will be due.`,
            confirmText: printAfterSave ? 'Save & print on credit' : 'Save on credit',
            cancelText: 'Go back & edit',
            paymentSummary: {
              amountReceived: tendered,
              payable: pay,
              isCredit: true,
              paymentMode: form.payment_mode,
            },
          })
          if (!ok) { releaseLock(); return false }
        } else {
          // Three-way check: did we actually collect the money, is it going on
          // credit instead, or does the cashier want to keep editing?
          const choice = await confirm({
            mode: 'update',
            title: paidNow < pay ? 'Confirm partial payment' : 'Confirm payment',
            message: paidNow < pay
              ? `Record ₹${paidNow.toFixed(2)} received and ₹${(pay - paidNow).toFixed(2)} still due on this customer's account.`
              : `Confirm the amount received via ${(form.payment_mode || 'cash').toUpperCase()} and return any change shown below.`,
            confirmText: paidNow < pay
              ? (printAfterSave ? 'Save partial payment & print' : 'Save partial payment')
              : (printAfterSave ? 'Received · Print invoice' : 'Received · Save invoice'),
            confirmValue: 'paid',
            tertiaryText: 'No payment · Add to credit',
            tertiaryValue: 'credit',
            cancelText: 'Go back & edit',
            cancelValue: 'cancel',
            paymentSummary: {
              amountReceived: tendered,
              payable: pay,
              isCredit: paidNow < pay,
              paymentMode: form.payment_mode,
            },
          })
          if (choice === 'cancel' || !choice) { releaseLock(); return false }
          if (choice === 'credit') {
            // Not collected — record the full payable as due and switch the tab
            // to credit so the receipt/ledger/shift tallies reflect it.
            isCredit = true
            paidNow = 0
            formForSave = { ...form, payment_mode: 'credit', amount_received: '0' }
            setForm(f => ({ ...f, payment_mode: 'credit', amount_received: '0' }))
          }
        }
      } catch (confirmErr) {
        // confirm() itself threw — release the lock and surface a generic error.
        logger.error('[SALES] confirm dialog threw unexpectedly', confirmErr)
        releaseLock()
        return false
      }
    }

    if (paidNow < pay && !String(formForSave.customer_id || '').trim()) {
      releaseLock()
      setAlert({ type: 'danger', msg: 'Select a customer before saving a balance on credit.' })
      return false
    }
    if (formForSave.amount_received === '' || formForSave.amount_received == null) {
      // Quick-save shortcuts confirm a full payment without opening checkout.
      // Paint that confirmed amount into the receipt before printing it.
      formForSave = { ...formForSave, amount_received: tendered.toFixed(2) }
      setForm(current => ({ ...current, amount_received: tendered.toFixed(2) }))
    }

    setSubmitting(true)
    logger.info('[SALES] saving invoice', activeTab.name, '· items', form.items.length, '· payable', pay, '· paid', paidNow, isCredit ? '(credit)' : '(paid)')
    const reqKey = activeTab.name
    const clientRequestId = reqIdFor(reqKey)
    let payload
    try {
      payload = buildInvoicePayload({ invoiceNo: activeTab.name, form: formForSave, gstEnabled: gstAmt > 0, billDiscount: billDiscountAmt, cashDiscount: cashDiscountAmt, paidAmount: paidNow, markPaid: !isCredit })
    } catch (error) {
      releaseLock()
      setSubmitting(false)
      setAlert({ type: 'danger', msg: 'Please check the bill details before saving.' })
      return false
    }

    // Local reset for the offline path — close the tab + refocus WITHOUT a server
    // refetch (which would fail offline). The next bill's number is still kept
    // unique because Sales feeds the queued (pending) invoice numbers back into
    // the number allocator.
    const offlineReset = (keepPrintLock = false) => {
      try { closeTab(activeTabId, null, true) } finally { if (!keepPrintLock) releaseLock() }
      setTimeout(() => barcodeRef.current?.focus(), 100)
    }

    // Persist the bill to the durable outbox and treat it as saved. It carries
    // its stable id + invoice_no, so on reconnect syncManager flushes it exactly
    // once. Thermal receipts print from local state (offline-capable); PDF print
    // needs the server, so it's skipped with a notice.
    const doQueueOffline = async () => {
      if (!enqueueOffline) {
        setAlert({ type: 'danger', msg: 'Offline save is unavailable. Please check your connection.' })
        return false
      }
      await enqueueOffline({ method: 'POST', path: '/invoices', body: payload, clientRequestId })
      _saveLock.set(lockKey, 'saved')
      reqIdRef.current.delete(reqKey) // safely persisted in the outbox now
      logger.info('[SALES] invoice queued offline', activeTab.name)
      setAlert({ type: 'warning', msg: 'Saved offline — will sync automatically when you’re back online.' })
      const keepPrintLock = printAfterSave && beginPrintJob({ invoiceNo: activeTab.name, receiptForm: formForSave, offline: true, releaseLock })
      offlineReset(keepPrintLock)
      return true
    }

    let serverAccepted = false
    try {
      // Known-offline (only on the WEB/cloud app — the desktop app's backend is on localhost, so it is always online relative to the frontend)
      const isOfflineForBackend = !IS_LOCAL_APP && typeof navigator !== 'undefined' && navigator.onLine === false
      if (isOfflineForBackend) {
        return await doQueueOffline()
      }

      const res = await authFetch('/billing/invoices', {
        method: 'POST',
        headers: { 'X-Client-Request-Id': clientRequestId },
        body: JSON.stringify(payload),
      })
      if (res.ok) {
        serverAccepted = true
        _saveLock.set(lockKey, 'saved')
        reqIdRef.current.delete(reqKey)  // settled — next save is a fresh intent
        // The server may RE-NUMBER on a concurrent collision (§9.3b: a different
        // sale grabbed this number first). Always trust the number it returns for
        // the receipt/print — not the locally-computed tab name.
        const saved = await res.json().catch(() => null)
        const serverInvoiceNo = saved?.invoice_no || saved?.invoice_number || activeTab.name
        if (serverInvoiceNo !== activeTab.name) {
          logger.warn('[SALES] server reassigned invoice number', activeTab.name, '→', serverInvoiceNo)
          setTabs(prev => prev.map(t => t.id === activeTabId ? { ...t, name: serverInvoiceNo } : t))
        }
        logger.info('[SALES] invoice saved', serverInvoiceNo, printAfterSave ? '(print)' : '')
        try { playSuccessChime() } catch (error) { logger.warn('[SALES] success sound unavailable', error) }
        setAlert({ type: 'success', msg: printAfterSave ? 'Invoice saved. Preparing print…' : 'Invoice created successfully!' })
        
        const finishReset = (keepPrintLock = false) => {
          // Retire the committed cart immediately. A slow cloud list refresh must
          // not leave it editable after Done releases the saved-receipt lock.
          try { closeTab(activeTabId, null, true) } finally { if (!keepPrintLock) releaseLock() }
          if (!IS_LOCAL_APP) {
            // Refresh list/numbering in the background without closing another
            // tab later, when the cashier may already be working on a new sale.
            const fromDate = getFromDateStr(7)
            authFetch(`/billing/invoices?from_date=${fromDate}&per_page=500&sort=desc`)
              .then(r => r.ok ? r.json() : [])
              .then(invs => {
                setDbInvoices(invs)
                setTabs(prev => syncTabNames(prev, invs))
              }).catch(error => logger.warn('[SALES] invoice list refresh failed after save', error))
          }
          setTimeout(() => barcodeRef.current?.focus(), 100)
        }


        // The saved receipt owns a stable snapshot independent of the next
        // cart. Keep its print/retry screen until Done, even if print() silently
        // returns without opening a native dialog.
        const keepPrintLock = printAfterSave && beginPrintJob({ invoiceNo: serverInvoiceNo, receiptForm: formForSave, offline: false, releaseLock })
        finishReset(keepPrintLock)
        return true
      } else {
        // Definitive server rejection (validation etc.) — won't fix itself on
        // retry, so drop the id; a corrected re-save is a new intent.
        if (res.status >= 400 && res.status < 500) reqIdRef.current.delete(reqKey)
        const err = await res.json().catch(() => ({}))
        logger.error('[SALES] invoice save rejected — status', res.status, err.detail || '')
        setAlert({ type: 'danger', msg: err.detail || 'Failed to create invoice.' })
        return false
      }
    } catch (e) {
      if (serverAccepted) {
        // The sale is already committed. A UI, audio or print problem must
        // never turn it into another queued POST with a new request id.
        logger.error('[SALES] invoice saved but follow-up failed', e)
        setAlert({ type: 'warning', msg: 'Invoice saved. Reopen it from Invoices if you need to print; do not save it again.' })
        try { closeTab(activeTabId, null, true) } finally { releaseLock() }
        return true
      }
      if (e?.message === 'Session expired') {
        // authFetch already logged the user out — don't queue, surface it.
        setAlert({ type: 'danger', msg: 'Session expired. Please log in again.' })
        return false
      }
      // Network/CORS/ambiguous failure — don't lose the bill: queue it offline
      // under the SAME stable id, so a flush on reconnect is exactly-once.
      logger.warn('[SALES] save network failure — queuing offline', e?.message || e)
      try {
        return await doQueueOffline()
      } catch (qerr) {
        logger.error('[SALES] offline queue failed', qerr?.message || qerr)
        setAlert({ type: 'danger', msg: 'Could not save the bill. Please try again.' })
        return false
      }
    } finally {
      if (_saveLock.get(lockKey) === 'saving') releaseLock()
      setSubmitting(false)
    }
  }, [form, authFetch, activeTab.name, activeTabId, closeTab, gstAmt, settings, grandTotal, payable, cashDiscountAmt, billDiscountAmt, setAlert, setSubmitting, setDbInvoices, setTabs, syncTabNames, barcodeRef, enqueueOffline, confirm, beginPrintJob])

  const openPaymentFlow = useCallback((focusTarget = 'amountReceived') => {
    if (form.items.length === 0) return
    const pay = (payable ?? grandTotal)
    setForm(f => ({
      ...f,
      amount_received: f.payment_mode === 'credit' ? '0' : pay.toFixed(2)
    }))
    setPaymentFocusTarget(focusTarget)
    setShowPaymentPopup(true)
  }, [form.items.length, grandTotal, payable, setForm])

  const executeSaveInvoice = useCallback(async (print) => {
    // skipConfirm=false → show the "Payment received? / Add to credit / Go back"
    // check after the cashier clicks Pay in the checkout popup.
    const success = await handleSaveInvoice(print, false)
    if (success) {
      setShowPaymentPopup(false)
    }
  }, [handleSaveInvoice])

  return {
    printJob,
    printSavedInvoice,
    prepareSavedPdf: () => prepareSavedPdf(),
    closePrintJob,
    showPaymentPopup,
    setShowPaymentPopup,
    paymentFocusTarget,
    setPaymentFocusTarget,
    openPaymentFlow,
    executeSaveInvoice,
    handleSaveInvoice,
  }
}
