// ============================================================================
// useInvoiceActions — ONE home for every invoice action, so Print / Share /
// Return / View / Record-Payment behave identically wherever an invoice appears
// (party drill-down, Invoices view, …). Lifted verbatim from the logic that
// lived inline in Parties.jsx.
//
//   const inv = useInvoiceActions(authFetch, { onChanged })
//   <InvoiceActions invoice={row} actions={inv} />   // buttons
//   {inv.modals}                                      // render once per page
//
// `onChanged` fires after a return/payment succeeds so the caller can refresh.
// ============================================================================
import React, { useCallback, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { logger } from '../utils/logger'
import { buildUpiUri, buildWhatsAppShareUrl } from '../utils/share'
import InvoiceViewerModal from '../components/invoice/InvoiceViewerModal'
import SaleReturnModal from '../components/parties/SaleReturnModal'
import RecordPaymentModal from '../components/payments/RecordPaymentModal'

const toast = (type, msg) => window.dispatchEvent(new CustomEvent('show_toast', { detail: { type, msg } }))
const emptyPay = () => ({ type: 'received', invoice_ref: '', amount: '', method: 'UPI', reference: '', date: new Date().toISOString().slice(0, 10) })

export default function useInvoiceActions(authFetch, { onChanged } = {}) {
  const { user } = useAuth()

  // Viewer
  const [viewingInvoiceNo, setViewingInvoiceNo] = useState(null)
  // Return (credit note)
  const [returningInvoice, setReturningInvoice] = useState(null)
  const [returnLines, setReturnLines] = useState([])
  const [returnNote, setReturnNote] = useState('')
  const [savingReturn, setSavingReturn] = useState(false)
  const [showReturnModal, setShowReturnModal] = useState(false)
  // Payment
  const [payForm, setPayForm] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const view = useCallback((invoiceNo) => setViewingInvoiceNo(invoiceNo), [])

  const print = useCallback(async (invoiceNo) => {
    if (!invoiceNo) return
    try {
      const res = await authFetch(`/sales/${invoiceNo}/pdf`)
      if (!res.ok) { toast('error', 'Failed to load PDF for printing.'); return }
      const blob = await res.blob()
      const url = window.URL.createObjectURL(blob)
      const iframe = document.createElement('iframe')
      iframe.style.display = 'none'
      iframe.src = url
      document.body.appendChild(iframe)
      iframe.onload = () => iframe.contentWindow.print()
    } catch (err) {
      logger.error('[INVOICE] print failed', err)
      toast('error', 'Error printing invoice.')
    }
  }, [authFetch])

  const share = useCallback((invoice, customer = null) => {
    const invoiceNo = invoice.invoice_number || invoice.invoice_no
    const total = parseFloat(invoice.total_amount || 0)
    const paid = parseFloat(invoice.paid_amount || 0)
    const balance = Math.max(total - paid, 0)
    let phone = customer?.phone || invoice.customer_phone || ''
    if (!phone) {
      const input = window.prompt("Enter Customer's WhatsApp Number (10 digits):")
      if (!input) return
      phone = input
    }
    const upiVpa = localStorage.getItem('pos_upi_vpa') || 'bizassist@upi'
    const businessName = (user?.business_name || 'BizAssist Merchant').toUpperCase()
    let message = `Hi ${customer?.name || 'Customer'},\n\nHere is your Invoice ${invoiceNo} from ${businessName}:\nDate: ${invoice.date || invoice.invoice_date}\nTotal Amount: ₹${total.toLocaleString('en-IN')}\n`
    if (balance > 0) {
      const upiLink = buildUpiUri({ vpa: upiVpa, payeeName: businessName, amount: balance, note: `INV-${invoiceNo}` })
      message += `Balance Due: ₹${balance.toLocaleString('en-IN')}.\nYou can pay online using this UPI link: ${upiLink}\n`
    }
    message += `\nThank you for your business!`
    window.open(buildWhatsAppShareUrl(phone, message), '_blank')
  }, [user])

  const openReturn = useCallback(async (invoice) => {
    const invoiceNo = invoice.invoice_number || invoice.invoice_no
    try {
      const res = await authFetch(`/sales/${invoiceNo}`)
      if (!res.ok) { toast('error', 'Failed to fetch invoice details.'); return }
      const detail = await res.json()
      setReturningInvoice(detail)
      setReturnLines((detail.lines || []).map(li => ({
        product_id: li.product_id, product_name: li.product_name, quantity: 0,
        max_quantity: li.quantity, unit_price: li.unit_price,
        cgst_rate: li.cgst_rate || 0, sgst_rate: li.sgst_rate || 0,
        igst_rate: li.igst_rate || 0, cess_rate: li.cess_rate || 0,
        unit: li.unit || 'Nos', hsn_sac: li.hsn_sac || '',
      })))
      setReturnNote('')
      setShowReturnModal(true)
    } catch (e) {
      logger.error('[INVOICE] open return failed', e)
      toast('error', 'Network error fetching invoice details.')
    }
  }, [authFetch])

  const saveReturn = useCallback(async () => {
    const activeLines = returnLines.filter(l => l.quantity > 0)
    if (activeLines.length === 0) { toast('error', 'Enter a return quantity greater than zero for at least one item.'); return }
    const invalid = activeLines.find(l => l.quantity > l.max_quantity)
    if (invalid) { toast('error', `Return quantity for ${invalid.product_name} cannot exceed original (${invalid.max_quantity}).`); return }
    setSavingReturn(true)
    try {
      const res = await authFetch('/credit-notes', {
        method: 'POST',
        body: JSON.stringify({
          invoice_id: returningInvoice.id,
          lines: activeLines.map(l => ({
            product_id: l.product_id, product_name: l.product_name,
            quantity: parseFloat(l.quantity), unit_price: parseFloat(l.unit_price),
            cgst_rate: parseFloat(l.cgst_rate), sgst_rate: parseFloat(l.sgst_rate),
            igst_rate: parseFloat(l.igst_rate), hsn_sac: l.hsn_sac, unit: l.unit,
          })),
          note: returnNote,
        }),
      })
      if (res.ok) {
        toast('success', 'Sales return (Credit Note) recorded — stock & balance updated.')
        setShowReturnModal(false); setReturningInvoice(null); setReturnLines([]); setReturnNote('')
        onChanged && onChanged()
      } else {
        const err = await res.json().catch(() => ({}))
        toast('error', err.detail || 'Failed to record sales return.')
      }
    } catch (e) {
      logger.error('[INVOICE] save return failed', e)
      toast('error', 'Network error recording the return.')
    } finally {
      setSavingReturn(false)
    }
  }, [authFetch, returnLines, returnNote, returningInvoice, onChanged])

  const recordPayment = useCallback((invoice) => {
    const invoiceNo = invoice.invoice_number || invoice.invoice_no
    const outstanding = invoice.outstanding != null
      ? invoice.outstanding
      : Math.max((parseFloat(invoice.total_amount || 0)) - (parseFloat(invoice.paid_amount || 0)), 0)
    setPayForm({ ...emptyPay(), invoice_ref: invoiceNo, amount: String(outstanding || '') })
  }, [])

  const submitPayment = useCallback(async (e) => {
    e.preventDefault(); setSubmitting(true)
    try {
      const nowIso = new Date().toISOString()
      const res = await authFetch('/billing/payments', {
        method: 'POST',
        body: JSON.stringify({
          ...payForm,
          amount: parseFloat(payForm.amount),
          created_at: nowIso,
          payment_date: nowIso,
        })
      })
      if (res.ok) { toast('success', 'Payment recorded.'); setPayForm(null); onChanged && onChanged() }
      else { const err = await res.json().catch(() => ({})); toast('error', err.detail || 'Could not record payment.') }
    } catch (err) { logger.error('[INVOICE] payment failed', err); toast('error', 'Network error recording payment.') }
    finally { setSubmitting(false) }
  }, [authFetch, payForm, onChanged])

  const modals = (
    <>
      <InvoiceViewerModal invoiceNo={viewingInvoiceNo} onClose={() => setViewingInvoiceNo(null)} />
      {showReturnModal && returningInvoice && (
        <SaleReturnModal
          returningInvoice={returningInvoice} setReturningInvoice={setReturningInvoice}
          returnLines={returnLines} setReturnLines={setReturnLines}
          returnNote={returnNote} setReturnNote={setReturnNote}
          handleSaveReturn={saveReturn} savingReturn={savingReturn}
          setShowReturnModal={setShowReturnModal} form={null}
        />
      )}
      {payForm && (
        <RecordPaymentModal
          form={payForm} setField={(k, v) => setPayForm(f => ({ ...f, [k]: v }))}
          onSubmit={submitPayment} submitting={submitting} onClose={() => setPayForm(null)}
        />
      )}
    </>
  )

  return { view, print, share, openReturn, recordPayment, modals }
}
