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
import { shareInvoice, buildWhatsAppLink } from './share'

const LAST_USED_KEY = (bizId) => `invoice.template.${bizId || 'default'}`

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

export default function InvoiceViewer() {
  const { invoiceNo } = useParams()
  const navigate = useNavigate()
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
      alert(`Invoice link shared via ${result.method === 'native' ? 'device share' : 'clipboard'}.`)
    } catch (e) {
      if (e.message) alert(e.message)
    }
  }, [invoiceNo, entry.key, payload])

  const onShareWhatsApp = useCallback(() => {
    if (!payload?.invoice?.uid_token) return alert("Invoice doesn't have a public link.")
    const link = `${window.location.origin}/public/invoice/${payload.invoice.uid_token}`
    const text = `Here is your invoice ${invoiceNo} for ${payload.totals?.total_amount}.\nView it here: ${link}`
    // If we had the customer phone we could pre-fill it here
    const waLink = buildWhatsAppLink(payload.buyer?.phone || '', text)
    window.open(waLink, '_blank')
    beacon('shared', { invoice_no: invoiceNo, template_type: entry.key, extra: { channel: 'whatsapp' } })
  }, [invoiceNo, entry.key, payload])

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
        <button className="btn" onClick={() => navigate(-1)}>Go back</button>
      </div>
    )
  }
  if (!payload || !template) {
    return <div className="invoice-viewer" data-testid="invoice-viewer-loading" style={{ padding: 24 }}>Loading invoice…</div>
  }

  const Template = entry.component
  const body = (
    <TemplateBoundary templateKey={entry.key} invoiceNo={invoiceNo} payload={payload}>
      <Template payload={payload} />
    </TemplateBoundary>
  )

  return (
    <div className="invoice-viewer" data-testid="invoice-viewer">
      {/* toolbar (hidden in print via .no-print) */}
      <div className="invoice-viewer-toolbar no-print" style={{
        display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap',
        padding: '10px 16px', position: 'sticky', top: 0, zIndex: 5,
        background: 'var(--bg, #fdfdfc)', borderBottom: '1px solid var(--border, #c8c5be)',
      }}>
        <button className="btn" onClick={() => navigate(-1)} aria-label="Back">←</button>
        <strong style={{ marginRight: 8 }}>{payload.invoice.title} {payload.invoice.number}</strong>

        <div role="tablist" aria-label="Invoice template" style={{ display: 'flex', gap: 4 }}>
          {templateOptions().map((opt) => (
            <button key={opt.key} role="tab" aria-selected={entry.key === opt.key}
                    className="btn" title={opt.description}
                    onClick={() => selectTemplate(opt.key)}
                    style={entry.key === opt.key ? {
                      background: 'var(--accent, #c15f3c)', color: '#fff',
                    } : undefined}>
              {opt.label}
            </button>
          ))}
        </div>

        <span style={{ flex: 1 }} />
        <button className="btn" onClick={onDuplicate}>Duplicate</button>
        <button className="btn" onClick={onCreditNote}>Credit Note</button>
        <button className="btn" onClick={onSetDefault} disabled={savingDefault}>
          {savingDefault ? 'Saving…' : 'Set as default'}
        </button>
        <button className="btn" onClick={onShareWhatsApp} style={{ background: '#25D366', color: '#fff', border: 'none' }}>WhatsApp</button>
        <button className="btn" onClick={onShare}>Share Link</button>
        <button className="btn" onClick={onDownloadPdf}>Download PDF</button>
        <button className="btn" data-testid="invoice-print-btn" onClick={onPrint}
                style={{ background: 'var(--accent, #c15f3c)', color: '#fff' }}>
          Print
        </button>
      </div>

      {/* on-screen preview */}
      <div className="invoice-viewer-preview no-print" style={{
        padding: '20px 8px', display: 'flex', justifyContent: 'center',
        background: 'var(--bg-3, #f4f4f1)', minHeight: '80vh',
      }}>
        <div style={{ boxShadow: '0 4px 16px rgba(26,23,20,0.10)', background: '#fff', width: '100%', maxWidth: 820 }}>
          {body}
        </div>
      </div>

      {/* print-only copy (portal outside the app layout) */}
      <PrintPortal>{body}</PrintPortal>
    </div>
  )
}
