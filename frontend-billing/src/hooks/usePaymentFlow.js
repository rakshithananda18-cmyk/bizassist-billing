import { useState, useCallback, useRef } from 'react'
import { logger } from '../utils/logger'
import { buildInvoicePayload } from '../utils/invoiceMath'
import { newClientRequestId } from '../sync/uuid'

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
    if (form.items.length === 0 || form.items.some(it => !it.product || !it.price)) {
      setAlert({ type: 'danger', msg: 'Please add items and complete all fields.' })
      return false
    }
    
    const pay = (payable ?? grandTotal)
    const isCredit = form.payment_mode === 'credit'
    // Credit → record only what was actually received now (may be 0 / partial).
    // Any other mode → "Paid": the full payable is settled at the counter.
    const paidNow = isCredit ? (parseFloat(form.amount_received) || 0) : pay

    if (!skipConfirm) {
      if (isCredit) {
        const confirmCredit = window.confirm(`Save on CREDIT — ₹${(pay - paidNow).toFixed(2)} will be due. Proceed?`)
        if (!confirmCredit) return false
      } else {
        const confirmPaid = window.confirm(`Mark PAID ₹${pay.toFixed(2)} (${(form.payment_mode || 'cash').toUpperCase()}) and print?`)
        if (!confirmPaid) return false
      }
    }

    setSubmitting(true)
    logger.info('[SALES] saving invoice', activeTab.name, '· items', form.items.length, '· payable', pay, '· paid', paidNow, isCredit ? '(credit)' : '(paid)')
    const reqKey = activeTab.name
    const clientRequestId = reqIdFor(reqKey)
    const payload = buildInvoicePayload({ invoiceNo: activeTab.name, form, gstEnabled: gstAmt > 0, billDiscount: billDiscountAmt, cashDiscount: cashDiscountAmt, paidAmount: paidNow, markPaid: !isCredit })

    // Local reset for the offline path — close the tab + refocus WITHOUT a server
    // refetch (which would fail offline). The next bill's number is still kept
    // unique because Sales feeds the queued (pending) invoice numbers back into
    // the number allocator.
    const offlineReset = () => {
      closeTab(activeTabId, null, true)
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
      reqIdRef.current.delete(reqKey) // safely persisted in the outbox now
      logger.info('[SALES] invoice queued offline', activeTab.name)
      const isThermal = settings?.print?.thermal_printer_mode === true
      if (printAfterSave && isThermal) {
        setAlert({ type: 'warning', msg: 'Saved offline — printing locally; will sync when back online.' })
        setTimeout(() => { window.print(); offlineReset() }, 500)
      } else {
        setAlert({ type: 'warning', msg: printAfterSave
          ? 'Saved offline — PDF printing needs a connection; the bill will sync automatically.'
          : 'Saved offline — will sync automatically when you’re back online.' })
        offlineReset()
      }
      return true
    }

    try {
      // Known-offline → don't even try the network; queue straight away.
      if (typeof navigator !== 'undefined' && navigator.onLine === false) {
        return await doQueueOffline()
      }

      const res = await authFetch('/billing/invoices', {
        method: 'POST',
        headers: { 'X-Client-Request-Id': clientRequestId },
        body: JSON.stringify(payload),
      })
      if (res.ok) {
        reqIdRef.current.delete(reqKey)  // settled — next save is a fresh intent
        logger.info('[SALES] invoice saved', activeTab.name, printAfterSave ? '(print)' : '')
        setAlert({ type: 'success', msg: printAfterSave ? 'Invoice created and print triggered!' : 'Invoice created successfully!' })
        
        const finishReset = () => {
          authFetch('/billing/invoices').then(r => r.ok ? r.json() : []).then(invs => {
            setDbInvoices(invs)
            setTabs(prev => syncTabNames(prev, invs))
            closeTab(activeTabId, null, true)
          }).catch(() => closeTab(activeTabId, null, true))
          setTimeout(() => barcodeRef.current?.focus(), 100)
        }

        if (printAfterSave) {
          const invoiceNo = activeTab.name
          const isThermal = settings?.print?.thermal_printer_mode === true
          if (isThermal) {
            setTimeout(() => {
              window.print()
              finishReset()
            }, 500)
          } else {
            setTimeout(async () => {
              try {
                const pdfRes = await authFetch(`/sales/${invoiceNo}/pdf`)
                if (!pdfRes.ok) throw new Error('Failed to fetch invoice PDF')
                const blob = await pdfRes.blob()
                const url = URL.createObjectURL(blob)

                let iframe = document.getElementById('print-iframe')
                if (!iframe) {
                  iframe = document.createElement('iframe')
                  iframe.id = 'print-iframe'
                  iframe.style.position = 'absolute'
                  iframe.style.width = '0px'
                  iframe.style.height = '0px'
                  iframe.style.border = 'none'
                  document.body.appendChild(iframe)
                }
                iframe.src = url
                iframe.onload = () => {
                  iframe.contentWindow.focus()
                  iframe.contentWindow.print()
                }
                finishReset()
              } catch (err) {
                logger.error('[SALES] PDF print failed, falling back to window.print()', err)
                window.print()
                finishReset()
              }
            }, 300)
          }
        } else {
          finishReset()
        }
        return true
      } else {
        // Definitive server rejection (validation etc.) — won't fix itself on
        // retry, so drop the id; a corrected re-save is a new intent.
        reqIdRef.current.delete(reqKey)
        const err = await res.json().catch(() => ({}))
        logger.error('[SALES] invoice save rejected — status', res.status, err.detail || '')
        setAlert({ type: 'danger', msg: err.detail || 'Failed to create invoice.' })
        return false
      }
    } catch (e) {
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
      setSubmitting(false)
    }
  }, [form, authFetch, activeTab.name, activeTabId, closeTab, gstAmt, settings, grandTotal, payable, cashDiscountAmt, changeToReturn, billDiscountAmt, setAlert, setSubmitting, setDbInvoices, setTabs, syncTabNames, barcodeRef, enqueueOffline])

  const openPaymentFlow = useCallback((focusTarget = 'amountReceived') => {
    if (form.items.length === 0) return
    const pay = (payable ?? grandTotal)
    setForm(f => ({
      ...f,
      amount_received: f.payment_mode === 'credit' ? '0' : (f.amount_received || pay.toFixed(2))
    }))
    setPaymentFocusTarget(focusTarget)
    setShowPaymentPopup(true)
  }, [form.items.length, grandTotal, payable, setForm])

  const executeSaveInvoice = useCallback(async (print) => {
    const success = await handleSaveInvoice(print, true)
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
