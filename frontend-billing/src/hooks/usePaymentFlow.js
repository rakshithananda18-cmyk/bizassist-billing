import { useState, useCallback } from 'react'
import { logger } from '../utils/logger'
import { buildInvoicePayload } from '../utils/invoiceMath'

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
}) {
  const [showPaymentPopup, setShowPaymentPopup] = useState(false)
  const [paymentFocusTarget, setPaymentFocusTarget] = useState('amountReceived')

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
    try {
      const res = await authFetch('/billing/invoices', {
        method: 'POST',
        body: JSON.stringify(
          buildInvoicePayload({ invoiceNo: activeTab.name, form, gstEnabled: gstAmt > 0, billDiscount: billDiscountAmt, cashDiscount: cashDiscountAmt, paidAmount: paidNow, markPaid: !isCredit })
        ),
      })
      if (res.ok) {
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
        const err = await res.json().catch(() => ({}))
        logger.error('[SALES] invoice save rejected — status', res.status, err.detail || '')
        setAlert({ type: 'danger', msg: err.detail || 'Failed to create invoice.' })
        return false
      }
    } catch (e) {
      logger.error('[SALES] invoice save network error', e?.message || e)
      setAlert({ type: 'danger', msg: 'Network error. Please try again.' })
      return false
    } finally {
      setSubmitting(false)
    }
  }, [form, authFetch, activeTab.name, activeTabId, closeTab, gstAmt, settings, grandTotal, payable, cashDiscountAmt, changeToReturn, billDiscountAmt, setAlert, setSubmitting, setDbInvoices, setTabs, syncTabNames, barcodeRef])

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
