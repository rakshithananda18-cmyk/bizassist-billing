// src/invoice/InvoiceViewer.jsx — open any invoice, switch template, print/share.
// ===============================================================================
// The Phase-1 viewer (plan Part 3). Fetches the normalized InvoicePrintPayload
// ONCE and freezes it: switching templates re-renders only — the payload object
// is never refetched or mutated (the core no-mutation guarantee). Unknown or
// crashing templates fall back to Classic and report `template_fallback_used`.
import { Component, useCallback, useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { logger } from '../utils/logger'
import { resolveTemplate, templateOptions, FALLBACK_TEMPLATE } from './registry'
import PrintPortal, { triggerPrint } from './PrintPortal'
import { shareInvoice, buildWhatsAppLink, buildPublicInvoiceLink } from './share'
import PageLoader from '../components/PageLoader'
import InvoiceAccountPanel from '../components/invoice/InvoiceAccountPanel'
import { PhoneIcon, DownloadIcon } from '../components/Icons'
import { useDocLabels } from '../hooks/useDocLabels'
import { useConfirm } from '../contexts/ConfirmContext'
const LAST_USED_KEY = (bizId) => `invoice.template.${bizId || 'default'}`

/** WhatsApp glyph (no dedicated icon in Icons.jsx). */
function WhatsAppIcon({ size = 15 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M12.04 2C6.58 2 2.13 6.45 2.13 11.91c0 1.75.46 3.45 1.32 4.95L2 22l5.25-1.38a9.9 9.9 0 004.79 1.22h.004c5.46 0 9.91-4.45 9.91-9.91 0-2.65-1.03-5.14-2.9-7.01A9.82 9.82 0 0012.04 2zm0 1.8c2.17 0 4.2.84 5.74 2.38a8.06 8.06 0 012.37 5.73c0 4.47-3.64 8.11-8.12 8.11a8.1 8.1 0 01-4.13-1.13l-.3-.18-3.11.82.83-3.04-.19-.31a8.03 8.03 0 01-1.24-4.29c0-4.47 3.64-8.11 8.12-8.11zm4.55 10.29c-.25-.13-1.47-.72-1.7-.81-.23-.08-.39-.13-.56.13-.16.25-.64.8-.79.97-.14.16-.29.18-.54.06-.25-.13-1.05-.39-2-1.23-.74-.66-1.24-1.47-1.38-1.72-.14-.25-.02-.39.11-.51.11-.11.25-.29.37-.43.13-.15.17-.25.25-.42.08-.16.04-.31-.02-.43-.06-.13-.56-1.35-.77-1.85-.2-.48-.41-.42-.56-.43l-.48-.01c-.16 0-.43.06-.66.31-.23.25-.86.85-.86 2.07 0 1.22.89 2.4 1.01 2.56.13.16 1.75 2.67 4.23 3.74.59.26 1.05.41 1.41.52.59.19 1.13.16 1.56.1.48-.07 1.47-.6 1.68-1.18.21-.58.21-1.07.14-1.18-.06-.11-.22-.17-.47-.29z"/>
    </svg>
  )
}

/** Deep-freeze the payload in dev/test so any template mutation throws loudly. */
function deepFreeze(obj) {
  if (obj && typeof obj === 'object' && !Object.isFrozen(obj)) {
    Object.getOwnPropertyNames(obj).forEach((k) => deepFreeze(obj[k]))
    Object.freeze(obj)
  }
  return obj
}

/** Fire-and-forget render-lifecycle beacon — never blocks the UI. */
function beacon(action, fields = {}) {
  try {
    api.post('/sales/print-events', { action, ...fields }).catch(() => {})
  } catch { /* never throw from logging */ }
}

/** A crashing template must never blank an invoice: catch the render error,
 *  report `print_render_failed`, and re-render with the Classic fallback. */
class TemplateBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { failed: false }
  }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch(error) {
    logger.error('Template render failed', this.props.templateKey, error)
    beacon('print_render_failed', {
      invoice_no: this.props.invoiceNo, template_type: this.props.templateKey,
      success: false, error: String(error).slice(0, 200),
    })
  }
  componentDidUpdate(prev) {
    if (prev.templateKey !== this.props.templateKey && this.state.failed) {
      this.setState({ failed: false })   // give the newly selected template a chance
    }
  }
  render() {
    if (this.state.failed && this.props.templateKey !== FALLBACK_TEMPLATE) {
      const Fallback = resolveTemplate(FALLBACK_TEMPLATE).entry.component
      return <Fallback payload={this.props.payload} />
    }
    return this.props.children
  }
}

export default function InvoiceViewer({ invoiceNo: invoiceNoProp = null, embedded = false, onBack = null }) {
  const label = useDocLabels()
  const confirm = useConfirm()
  // Embedded mode (e.g. inside the Payments page): the invoice number comes in
  // as a prop and Back returns to the host page instead of navigating away.
  // ALL toolbar functionality (templates, duplicate, credit note, set default,
  // WhatsApp, share, PDF, print) is identical in both modes.
  const params = useParams()
  const invoiceNo = invoiceNoProp || params.invoiceNo
  const navigate = useNavigate()
  const goBack = useCallback(() => {
    if (onBack) onBack()
    else navigate(-1)
  }, [onBack, navigate])
  const [payload, setPayload] = useState(null)
  const [error, setError] = useState(null)
  const [template, setTemplate] = useState(null)   // resolved after payload load
  const [savingDefault, setSavingDefault] = useState(false)

  // ── Load the payload ONCE. Freeze it. ──────────────────────────────────────
  useEffect(() => {
    let alive = true
    setPayload(null); setError(null)
    api.get(`/sales/${encodeURIComponent(invoiceNo)}/print-payload`)
      .then((data) => {
        if (!alive) return
        if (data?.invoice?.uid_token) {
          // Always rebuild against the PUBLIC web origin — the backend's
          // FRONTEND_URL may be unset (relative path) and on the desktop app
          // window.location.origin is localhost, which customers can't open.
          data.invoice.public_url = buildPublicInvoiceLink(data.invoice.uid_token)
        }
        deepFreeze(data)
        setPayload(data)
        // preference order: per-user last-used → business default → classic
        let pref = null
        try { pref = localStorage.getItem(LAST_USED_KEY(data?.seller?.biz_id)) } catch { /* ignore */ }
        setTemplate(pref || data?.meta?.template_default || FALLBACK_TEMPLATE)
      })
      .catch((e) => {
        if (!alive) return
        logger.error('InvoiceViewer payload fetch failed', e)
        setError(e?.detail || e?.message || 'Could not load the invoice')
      })
    return () => { alive = false }
  }, [invoiceNo])

  const { entry, fellBack } = resolveTemplate(template)
  useEffect(() => {
    if (fellBack && payload) {
      beacon('template_fallback_used', {
        invoice_no: invoiceNo, template_type: FALLBACK_TEMPLATE,
        extra: { requested: String(template) },
      })
    }
  }, [fellBack, payload, invoiceNo, template])

  const selectTemplate = useCallback((key) => {
    setTemplate((prev) => {
      if (key !== prev) {
        beacon('template_selected', {
          invoice_no: invoiceNo, template_type: key, extra: { previous: prev },
        })
        try { localStorage.setItem(LAST_USED_KEY(payload?.seller?.biz_id), key) } catch { /* ignore */ }
      }
      return key
    })
  }, [invoiceNo, payload])

  const onPrint = useCallback(() => {
    beacon('print_opened', { invoice_no: invoiceNo, template_type: entry.key })
    triggerPrint()
  }, [invoiceNo, entry.key])

  const onDownloadPdf = useCallback(() => {
    // Phase 1: browser print-to-PDF via the same pixel-exact print CSS.
    // (Server-rendered PDF arrives in Phase 3.)
    beacon('pdf_generated', { invoice_no: invoiceNo, template_type: entry.key })
    triggerPrint()
  }, [invoiceNo, entry.key])

  const onShare = useCallback(async () => {
    try {
      const result = await shareInvoice(payload)
      beacon('shared', {
        invoice_no: invoiceNo, template_type: entry.key,
        extra: { channel: result.method },
      })
      confirm({ mode: 'alert', title: 'Link shared', message: `Invoice link shared via ${result.method === 'native' ? 'device share' : 'clipboard'}.` })
    } catch (e) {
      if (e.message) confirm({ mode: 'alert', title: 'Share failed', message: e.message })
    }
  }, [invoiceNo, entry.key, payload, confirm])

  const onShareWhatsApp = useCallback(() => {
    if (!payload?.invoice?.uid_token) { confirm({ mode: 'alert', title: 'No public link', message: "Invoice doesn't have a public link." }); return }
    const link = buildPublicInvoiceLink(payload.invoice.uid_token)
    const text = `Here is your invoice ${invoiceNo} for ${payload.totals?.total_amount}.\nView it here: ${link}`
    // If we had the customer phone we could pre-fill it here
    const waLink = buildWhatsAppLink(payload.buyer?.phone || '', text)
    window.open(waLink, '_blank')
    beacon('shared', { invoice_no: invoiceNo, template_type: entry.key, extra: { channel: 'whatsapp' } })
  }, [invoiceNo, entry.key, payload, confirm])

  const onDuplicate = useCallback(() => {
    navigate('/sales', { state: { duplicateFrom: invoiceNo } })
  }, [navigate, invoiceNo])

  const onCreditNote = useCallback(() => {
    navigate('/sales', { state: { creditNoteFrom: invoiceNo } })
  }, [navigate, invoiceNo])

  const onSetDefault = useCallback(async () => {
    setSavingDefault(true)
    try {
      await api.put('/settings', { print: { invoice_template: entry.key } })
      beacon('print_settings_saved', { template_type: entry.key })
    } catch (e) {
      logger.warn('Could not save default template (cashier?)', e)
    } finally {
      setSavingDefault(false)
    }
  }, [entry.key])

  // ── Render ──────────────────────────────────────────────────────────────────
  if (error) {
    return (
      <div className="invoice-viewer" data-testid="invoice-viewer-error" style={{ padding: 24 }}>
        <p>{error}</p>
        <button className="btn" onClick={goBack}>Go back</button>
      </div>
    )
  }
  if (!payload || !template) {
    return <PageLoader />
  }

  const Template = entry.component
  const body = (
    <TemplateBoundary templateKey={entry.key} invoiceNo={invoiceNo} payload={payload}>
      <Template payload={payload} />
    </TemplateBoundary>
  )

  return (
    <div className="invoice-viewer" data-testid="invoice-viewer" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* toolbar (hidden in print via .no-print) */}
      <div className="invoice-viewer-toolbar no-print" style={{
        display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap',
        padding: '8px 14px', position: 'sticky', top: 0, zIndex: 5,
        background: 'var(--bg-3)', borderBottom: '1px solid var(--border)',
      }}>
        {/* ← Back + title */}
        <button className="btn btn-ghost btn-icon" onClick={goBack} aria-label="Back" style={{ flexShrink: 0 }}>←</button>
        <span style={{ fontWeight: 700, fontSize: '0.88rem', color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 200 }}>
          {payload.invoice.title} {payload.invoice.number}
        </span>

        {/* divider */}
        <span style={{ width: 1, height: 20, background: 'var(--border)', flexShrink: 0, margin: '0 2px' }} />

        {/* Template tabs */}
        <div role="tablist" aria-label="Invoice template" style={{ display: 'flex', gap: 3, background: 'var(--bg-4, var(--bg-1))', borderRadius: 'var(--radius-sm)', padding: '3px' }}>
          {templateOptions().map((opt) => (
            <button
              key={opt.key} role="tab" aria-selected={entry.key === opt.key}
              title={opt.description}
              onClick={() => selectTemplate(opt.key)}
              style={{
                fontSize: '0.78rem', fontWeight: 600, padding: '4px 10px',
                borderRadius: 'calc(var(--radius-sm) - 2px)',
                border: 'none', cursor: 'pointer',
                background: entry.key === opt.key ? 'var(--accent)' : 'transparent',
                color: entry.key === opt.key ? '#fff' : 'var(--text-secondary)',
                transition: 'background 0.15s, color 0.15s',
              }}>
              {opt.label}
            </button>
          ))}
        </div>

        <span style={{ flex: 1 }} />

        {/* Secondary actions */}
        <div style={{ display: 'flex', gap: 4 }}>
          <button className="btn btn-ghost btn-sm" onClick={onDuplicate}>Duplicate</button>
          <button className="btn btn-ghost btn-sm" onClick={onCreditNote}>{label('sale_return')}</button>
          <button className="btn btn-ghost btn-sm" onClick={onSetDefault} disabled={savingDefault}>
            {savingDefault ? 'Saving…' : 'Set as default'}
          </button>
        </div>

        {/* divider */}
        <span style={{ width: 1, height: 20, background: 'var(--border)', flexShrink: 0, margin: '0 2px' }} />

        {/* Share actions (WhatsApp + Download PDF now live beside the customer
            name in the right panel as icon buttons). */}
        <div style={{ display: 'flex', gap: 4 }}>
          <button className="btn btn-ghost btn-sm" onClick={onShare}>Share Link</button>
        </div>

        {/* Primary: Print */}
        <button
          className="btn btn-primary btn-sm"
          data-testid="invoice-print-btn"
          onClick={onPrint}>
          Print
        </button>
      </div>

      {/* ── Body: preview + side panel ────────────────────────────────────────── */}
      <div className="no-print" style={{ display: 'flex', flex: 1, minHeight: 0, overflow: 'hidden' }}>

        {/* Invoice preview (scrollable) */}
        <div style={{
          flex: 1, overflowY: 'auto', overflowX: 'auto',
          padding: '24px 20px', background: 'var(--bg)',
          WebkitOverflowScrolling: 'touch',
        }}>
          <div style={{
            boxShadow: 'var(--shadow-md)', background: '#fff',
            width: '100%', maxWidth: 820,
            minWidth: entry.key.includes('thermal') ? 'auto' : '800px',
            margin: '0 auto', borderRadius: 'var(--radius-sm)',
          }}>
            {body}
          </div>
        </div>

        {/* ── Right side panel: customer, items, summary + payments/returns.
             Shown in both standalone and modal (embedded) mode — the account
             details that used to sit in a top strip now live here, on-theme. ── */}
        {(() => {
          const tot = payload.totals || {}
          const buyer = payload.buyer || {}
          const lines = payload.lines || []
          const fmtAmt = (n) => n != null ? `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '₹0'
          const grandTotal = tot.grand_total || 0
          const amtPaid = tot.amount_paid || 0
          const balanceDue = tot.balance_due ?? Math.max(0, grandTotal - amtPaid)
          const isPaid = balanceDue <= 0
          return (
            <div style={{
              width: 'min(340px, 38vw)', flexShrink: 0,
              borderLeft: '1px solid var(--border)',
              background: 'var(--bg-2)',
              display: 'flex', flexDirection: 'column',
              overflow: 'hidden',
            }}>
              <style>{`
                .ivp-label { font-size: 0.67rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px; color: var(--text-muted); margin-bottom: 8px; display: flex; align-items: center; gap: 5px; }
                .ivp-label::after { content: ''; flex: 1; height: 1px; background: var(--border); margin-left: 4px; }
                .ivp-card { background: var(--bg-1); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 13px 15px; display: flex; flex-direction: column; gap: 5px; }
                .ivp-row { display: flex; justify-content: space-between; align-items: center; font-size: 0.82rem; padding: 2px 0; }
                .ivp-row .lbl { color: var(--text-secondary); }
                .ivp-row .val { font-weight: 600; color: var(--text-primary); }
              `}</style>

              {/* Pinned customer header — stays at the top while the details below
                  scroll under it. */}
              <div style={{ padding: '16px 16px 12px', flexShrink: 0, borderBottom: '1px solid var(--border)', background: 'var(--bg-2)' }}>
                <div className="ivp-label">Customer</div>
                <div className="ivp-card" style={{ gap: 6 }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                    <div style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--text-primary)', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {buyer.name || 'Walk-in Customer'}
                    </div>
                    <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                      <button onClick={onShareWhatsApp} title="Send on WhatsApp" aria-label="Send on WhatsApp"
                        style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 28, height: 28, borderRadius: '50%', border: 'none', cursor: 'pointer', background: '#25D366', color: '#fff' }}>
                        <WhatsAppIcon size={15} />
                      </button>
                      <button onClick={onDownloadPdf} title="Download PDF" aria-label="Download PDF"
                        style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 28, height: 28, borderRadius: '50%', border: '1px solid var(--border)', cursor: 'pointer', background: 'var(--bg-2)', color: 'var(--text-secondary)' }}>
                        <DownloadIcon size={14} />
                      </button>
                    </div>
                  </div>
                  {buyer.phone && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                      <PhoneIcon size={12} /> {buyer.phone}
                    </div>
                  )}
                  {buyer.place_of_supply && (
                    <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>📍 {buyer.place_of_supply}</div>
                  )}
                  {payload.invoice?.payment_mode && (
                    <div style={{ marginTop: 2 }}>
                      <span style={{
                        fontSize: '0.68rem', fontWeight: 700, padding: '2px 8px',
                        borderRadius: '99px', background: 'var(--accent-dim)',
                        color: 'var(--accent)', border: '1px solid var(--border-subtle)',
                        textTransform: 'uppercase', letterSpacing: '0.5px',
                      }}>
                        {payload.invoice.payment_mode}
                      </span>
                    </div>
                  )}
                </div>
              </div>

              {/* Scrolling details — roll under the pinned customer header. */}
              <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '14px 16px 20px', display: 'flex', flexDirection: 'column', gap: 18 }}>

                {/* — Items — */}
                <div>
                  <div className="ivp-label">
                    Items
                    {lines.length > 0 && (
                      <span style={{
                        fontSize: '0.64rem', fontWeight: 700, padding: '1px 6px',
                        borderRadius: '99px', background: 'var(--bg-3)',
                        color: 'var(--text-muted)', border: '1px solid var(--border)',
                      }}>{lines.length}</span>
                    )}
                  </div>
                  <div style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', overflow: 'hidden' }}>
                    {lines.length === 0 ? (
                      <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '18px 12px', fontSize: '0.8rem', background: 'var(--bg-1)' }}>
                        No items on this invoice
                      </div>
                    ) : (
                      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.79rem' }}>
                        <thead>
                          <tr style={{ background: 'var(--bg-3)', borderBottom: '1px solid var(--border)' }}>
                            <th style={{ padding: '6px 10px', textAlign: 'left', fontWeight: 600, color: 'var(--text-muted)', fontSize: '0.68rem', textTransform: 'uppercase', letterSpacing: '0.4px' }}>Item</th>
                            <th style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 600, color: 'var(--text-muted)', fontSize: '0.68rem', textTransform: 'uppercase', letterSpacing: '0.4px' }}>Qty</th>
                            <th style={{ padding: '6px 10px', textAlign: 'right', fontWeight: 600, color: 'var(--text-muted)', fontSize: '0.68rem', textTransform: 'uppercase', letterSpacing: '0.4px' }}>Total</th>
                          </tr>
                        </thead>
                        <tbody>
                          {lines.map((line, i) => (
                            <tr key={i} style={{ borderBottom: i < lines.length - 1 ? '1px solid var(--border)' : 'none', background: i % 2 === 0 ? 'var(--bg-1)' : 'var(--bg-2)' }}>
                              <td style={{ padding: '8px 10px', color: 'var(--text-primary)', fontWeight: 500, lineHeight: 1.3 }}>
                                <div>{line.name}</div>
                                {line.rate > 0 && <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: 1 }}>{fmtAmt(line.rate)} / {line.unit || 'Nos'}</div>}
                              </td>
                              <td style={{ padding: '8px', textAlign: 'right', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>{line.qty} {line.unit || 'Nos'}</td>
                              <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 700, color: 'var(--text-primary)', whiteSpace: 'nowrap' }}>{fmtAmt(line.line_total)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                </div>

                {/* — Summary — */}
                <div>
                  <div className="ivp-label">Summary</div>
                  <div className="ivp-card">
                    {tot.subtotal > 0 && (
                      <div className="ivp-row"><span className="lbl">Subtotal</span><span className="val">{fmtAmt(tot.subtotal)}</span></div>
                    )}
                    {tot.total_discount > 0 && (
                      <div className="ivp-row"><span className="lbl">Discount</span><span style={{ fontWeight: 600, color: 'var(--success)' }}>−{fmtAmt(tot.total_discount)}</span></div>
                    )}
                    {tot.cgst_total > 0 && (
                      <div className="ivp-row"><span className="lbl">CGST</span><span className="val">{fmtAmt(tot.cgst_total)}</span></div>
                    )}
                    {tot.sgst_total > 0 && (
                      <div className="ivp-row"><span className="lbl">SGST</span><span className="val">{fmtAmt(tot.sgst_total)}</span></div>
                    )}
                    {tot.igst_total > 0 && (
                      <div className="ivp-row"><span className="lbl">IGST</span><span className="val">{fmtAmt(tot.igst_total)}</span></div>
                    )}
                    {tot.round_off != null && tot.round_off !== 0 && (
                      <div className="ivp-row"><span className="lbl">Round Off</span><span className="val">{tot.round_off > 0 ? '+' : ''}{fmtAmt(tot.round_off)}</span></div>
                    )}
                    <div style={{ height: 1, background: 'var(--border)', margin: '5px 0' }} />
                    {/* Grand total strip */}
                    <div style={{
                      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                      background: 'var(--accent-dim)', border: '1px solid var(--border-subtle)',
                      borderRadius: 'var(--radius-sm)', padding: '9px 12px', margin: '2px -1px 0',
                    }}>
                      <span style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-primary)' }}>Grand Total</span>
                      <span style={{ fontSize: '1.1rem', fontWeight: 800, color: 'var(--accent)' }}>{fmtAmt(grandTotal)}</span>
                    </div>
                  </div>
                </div>

                {/* — Payment status — */}
                {grandTotal > 0 && (
                  <div>
                    <div className="ivp-label">Payment</div>
                    <div className="ivp-card" style={{ gap: 8 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>Amount Paid</span>
                        <span style={{ fontSize: '0.86rem', fontWeight: 700, color: 'var(--success)' }}>{fmtAmt(amtPaid)}</span>
                      </div>
                      <div style={{ height: 5, background: 'var(--bg-3)', borderRadius: '99px', overflow: 'hidden' }}>
                        <div style={{
                          height: '100%', borderRadius: '99px', transition: 'width 0.4s ease',
                          width: `${Math.min(100, (amtPaid / grandTotal) * 100)}%`,
                          background: isPaid ? 'var(--success)' : 'var(--warning)',
                        }} />
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>Balance Due</span>
                        <span style={{ fontSize: '0.86rem', fontWeight: 700, color: isPaid ? 'var(--success)' : 'var(--danger)' }}>
                          {isPaid ? '✓ Paid' : fmtAmt(balanceDue)}
                        </span>
                      </div>
                    </div>
                  </div>
                )}

                {/* — Payments received & returns (screen-only, from /account) — */}
                {payload.invoice?.id && (
                  <InvoiceAccountPanel authFetch={(p) => api.raw(p)} invoiceId={payload.invoice.id} />
                )}

              </div>
            </div>
          )
        })()}
      </div>

      {/* print-only copy (portal outside the app layout) */}
      <PrintPortal>{body}</PrintPortal>
    </div>
  )
}
