import { useState, useCallback, useRef } from 'react'
import { logger } from '../utils/logger'
import { buildInvoicePayload } from '../utils/invoiceMath'
import { newClientRequestId } from '../sync/uuid'
import { IS_LOCAL_APP } from '../config'
import { getFromDateStr } from '../utils/format'
import { useConfirm } from '../contexts/ConfirmContext'
import { playSuccessChime } from '../utils/posAudio'
import { printInvoicePdf } from '../utils/printInvoicePdf'

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
}) {
  const confirm = useConfirm()
  const [showPaymentPopup, setShowPaymentPopup] = useState(false)
  const [paymentFocusTarget, setPaymentFocusTarget] = useState('amountReceived')

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
    const offlineReset = () => {
      try { closeTab(activeTabId, null, true) } finally { releaseLock() }
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
      const isThermal = settings?.print?.thermal_printer_mode === true
      if (printAfterSave && isThermal) {
        setAlert({ type: 'warning', msg: 'Saved offline — printing locally; will sync when back online.' })
        setTimeout(() => {
          try { window.print() } catch (error) { logger.warn('[SALES] offline print failed', error) }
          finally { offlineReset() }
        }, 500)
      } else {
        setAlert({ type: 'warning', msg: printAfterSave
          ? 'Saved offline — PDF printing needs a connection; the bill will sync automatically.'
          : 'Saved offline — will sync automatically when you’re back online.' })
        offlineReset()
      }
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
        
        const finishReset = () => {
          if (IS_LOCAL_APP) {
            // Local app: skip the full invoice list re-fetch after every save.
            // The list is stale by at most one entry and refreshes naturally when
            // the user navigates to /payments. Removing this round-trip makes POS
            // feel noticeably snappier (saves 100-400ms per bill on the hybrid path).
            try { closeTab(activeTabId, null, true) } finally { releaseLock() }
          } else {
            // Cloud mode: refresh the 7-day invoice window only (not all invoices ever).
            const fromDate = getFromDateStr(7)
            authFetch(`/billing/invoices?from_date=${fromDate}&per_page=500&sort=desc`)
              .then(r => r.ok ? r.json() : [])
              .then(invs => {
                setDbInvoices(invs)
                setTabs(prev => syncTabNames(prev, invs))
                closeTab(activeTabId, null, true)
              }).catch(() => closeTab(activeTabId, null, true)).finally(releaseLock)
          }
          setTimeout(() => barcodeRef.current?.focus(), 100)
        }


        if (printAfterSave) {
          const invoiceNo = serverInvoiceNo
          const isThermal = settings?.print?.thermal_printer_mode === true
          if (isThermal) {
            // 800ms delay: ensures the ThermalReceipt Portal is fully painted in the
            // DOM before window.print() fires. 500ms was occasionally too short on
            // slower machines / hybrid mode (more state updates before render).
            setTimeout(() => {
              try { window.print() } catch (error) { logger.warn('[SALES] print failed after saving', error) }
              finally { finishReset() }
            }, 800)
          } else {
            (async () => {
              try {
                const pdfRes = await authFetch(`/sales/${invoiceNo}/pdf`)
                if (!pdfRes.ok) throw new Error('Failed to fetch invoice PDF')
                const blob = await pdfRes.blob()
                await printInvoicePdf(blob)
              } catch (err) {
                logger.error('[SALES] PDF print failed, falling back to window.print()', err)
                setAlert({ type: 'warning', msg: 'Invoice saved. PDF print could not open; trying the receipt view. You can reprint from Invoices.' })
                try { window.print() } catch (printError) { logger.warn('[SALES] print unavailable', printError) }
              } finally {
                finishReset()
              }
            })()
          }
        } else {
          finishReset()
        }
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
  }, [form, authFetch, activeTab.name, activeTabId, closeTab, gstAmt, settings, grandTotal, payable, cashDiscountAmt, billDiscountAmt, setAlert, setSubmitting, setDbInvoices, setTabs, syncTabNames, barcodeRef, enqueueOffline, confirm])

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
    showPaymentPopup,
    setShowPaymentPopup,
    paymentFocusTarget,
    setPaymentFocusTarget,
    openPaymentFlow,
    executeSaveInvoice,
    handleSaveInvoice,
  }
}
