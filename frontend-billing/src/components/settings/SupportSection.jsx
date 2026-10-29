import React, { useEffect, useId, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'
import { logger } from '../../utils/logger'
import { IS_LOCAL_APP } from '../../config'
import { SUPPORT_CONTACTS } from '../../config/supportContacts'
import { version } from '../../../package.json'
import './support-section.css'
import {
  AlertIcon, CheckIcon, PhoneIcon, MailIcon, MessageIcon,
  PrinterIcon, SyncIcon, ShieldIcon, SparkleIcon,
  ChevronDownIcon, ChevronRightIcon, InfoIcon, BillsIcon,
  BugIcon, WhatsAppOutlineIcon
} from '../Icons'

const CATEGORIES = [
  { id: 'bug', label: 'Bug / Issue', icon: <BugIcon size={17} />, desc: 'Something broke or behaves incorrectly' },
  { id: 'hardware', label: 'Printer / Hardware', icon: <PrinterIcon size={17} />, desc: 'Thermal printer, barcode scanner, USB' },
  { id: 'billing', label: 'GST & Invoicing', icon: <BillsIcon size={17} />, desc: 'Tax calculations, invoice formats, GSTR' },
  { id: 'sync', label: 'Cloud Sync & Backup', icon: <SyncIcon size={17} />, desc: 'Multi-device sync, database backup, offline' },
  { id: 'feature', label: 'Feature Request', icon: <SparkleIcon size={17} />, desc: 'Suggest a new tool or workflow improvement' },
  { id: 'guidance', label: 'General Guidance', icon: <InfoIcon size={17} />, desc: 'Questions on how to use BizAssist features' },
]

const FAQS = [
  {
    q: 'Thermal printer prints blank, cut off, or misaligned receipts',
    a: 'Go to Settings > Print & PDF and check the configured roll width (80mm or 58mm). Reopen a saved invoice to test Print or Download PDF. Check paper size, margins and cutter options in your printer driver if the receipt is cut off.',
  },
  {
    q: 'Bills saved offline are not syncing to other devices',
    a: 'Ensure your device has an active internet connection. Check the sync indicator in the top header. You can trigger an instant sync by navigating to Settings > Network & Discovery or Ops & Health. If the issue persists, verify that both devices are logged into the same business account.',
  },
  {
    q: 'How do I customize invoice prefix, numbering series, or terms?',
    a: 'Go to Settings > Print & PDF or Transactions. You can customize the invoice prefix (e.g. INV-, RET-), reset or adjust sequence numbers, and customize the invoice header, footer notes, and terms & conditions.',
  },
  {
    q: 'How to export GSTR-1 and tax reports for my accountant?',
    a: 'Navigate to Reports > GST & Compliance. Choose the report and tax period, generate it, then use Export CSV to share the results with your accountant.',
  },
  {
    q: 'How do I backup my database or move to a new billing computer?',
    a: 'Open Settings > Data Migration to export CSV records and review product, customer or vendor imports before saving. These CSV exports are not a complete database backup. Contact support for help moving a full local database to another computer.',
  },
]

export default function SupportSection() {
  const navigate = useNavigate()
  const { user, profile, authFetch, networkMode } = useAuth()
  const formId = useId()
  const cloudHosted = !IS_LOCAL_APP || networkMode === 'cloud'
  const showDirectContacts = SUPPORT_CONTACTS.enabled
  const [online, setOnline] = useState(() => navigator.onLine !== false)

  const [category, setCategory] = useState('bug')
  const [priority, setPriority] = useState('normal')
  const [subject, setSubject] = useState('')
  const [message, setMessage] = useState('')
  const [contact, setContact] = useState(profile?.phone || profile?.email || user?.username || '')
  const [attachLogs, setAttachLogs] = useState(!cloudHosted)
  const [submitting, setSubmitting] = useState(false)
  const [status, setStatus] = useState(null)
  const [expandedFaq, setExpandedFaq] = useState(0)
  const [showDiagnostics, setShowDiagnostics] = useState(false)

  const bizId = profile?.biz_id || profile?.public_id || user?.public_id || user?.biz_id || 'Unavailable'
  const appVersion = `v${version}`
  const hostingLabel = cloudHosted ? 'Cloud' : networkMode === 'hybrid' ? 'Desktop (Local + Cloud)' : 'Desktop (Local)'
  const selectedCategoryObj = CATEGORIES.find(c => c.id === category)
  const formattedMessage = [
    `[Category: ${selectedCategoryObj?.label || category}] [Priority: ${priority.toUpperCase()}]`,
    subject.trim() ? `Subject: ${subject.trim()}` : null,
    contact.trim() ? `Contact: ${contact.trim()}` : null,
    bizId !== 'Unavailable' ? `BizID: ${bizId}` : null,
    `Hosting: ${hostingLabel}`,
    `\nDetails:\n${message.trim()}`,
  ].filter(Boolean).join('\n')

  useEffect(() => {
    const updateOnline = () => setOnline(navigator.onLine !== false)
    window.addEventListener('online', updateOnline)
    window.addEventListener('offline', updateOnline)
    return () => {
      window.removeEventListener('online', updateOnline)
      window.removeEventListener('offline', updateOnline)
    }
  }, [])
  useEffect(() => { if (cloudHosted) setAttachLogs(false) }, [cloudHosted])

  async function handleSubmit(e) {
    e.preventDefault()
    if (!message.trim()) {
      setStatus({ type: 'error', msg: 'Please provide details about your issue or question.' })
      return
    }
    if (formattedMessage.length > 8000) {
      setStatus({ type: 'error', msg: 'The support request exceeds 8,000 characters including its summary and contact details. Please shorten it before submitting.' })
      return
    }

    setSubmitting(true)
    setStatus(null)

    try {
      const formData = new FormData()
      formData.append('message', formattedMessage)
      formData.append('attach_logs', attachLogs && !cloudHosted ? 'true' : 'false')

      const res = await authFetch('/feedback/submit', {
        method: 'POST',
        body: formData,
      })

      const data = await res.json().catch(() => ({}))
      if (res.ok) {
        setStatus({
          type: 'success',
          msg: 'Your support request was submitted successfully.',
        })
        setMessage('')
        setSubject('')
      } else {
        throw new Error(data.detail || data.error || 'Failed to submit support request.')
      }
    } catch (err) {
      logger.error('Feedback submit error:', err)
      setStatus({ type: 'error', msg: err.message || 'Network error occurred while submitting. Please try again later.' })
    } finally {
      setSubmitting(false)
    }
  }

  const openWhatsAppSupport = () => {
    if (!showDirectContacts || !SUPPORT_CONTACTS.phone) return
    const text = encodeURIComponent(
      `Hello BizAssist Support Team,\nI need assistance with my billing software.\n• BizID: ${bizId}\n• Version: ${appVersion}\n• Issue Type: ${category}\n• Details: ${subject || message || 'Need technical assistance'}`
    )
    window.open(`https://wa.me/${SUPPORT_CONTACTS.phone.replace(/\D/g, '')}?text=${text}`, '_blank', 'noopener,noreferrer')
  }

  const openEmailSupport = () => {
    if (!showDirectContacts || !SUPPORT_CONTACTS.email) return
    const mailSubject = encodeURIComponent(`[Support Request] ${subject || category} — BizID: ${bizId}`)
    const mailBody = encodeURIComponent(`BizID: ${bizId}\nApp Version: ${appVersion}\nHosting: ${hostingLabel}\n\nIssue Details:\n${message}`)
    window.location.href = `mailto:${SUPPORT_CONTACTS.email}?subject=${mailSubject}&body=${mailBody}`
  }

  return (
    <div className="support-section" style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      {/* Top Header Strip */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        flexWrap: 'wrap', gap: 16, paddingBottom: 16, borderBottom: '1px solid var(--border)'
      }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <h2 style={{ fontSize: '1.25rem', fontWeight: 800, color: 'var(--text-primary)', margin: 0 }}>
              Feedback &amp; Support Desk
            </h2>
            <span style={{
              fontSize: '0.72rem', fontWeight: 700, padding: '2px 8px',
              borderRadius: '99px', background: 'var(--accent-dim)',
              color: 'var(--accent)', border: '1px solid var(--border-subtle)'
            }}>
              Support
            </span>
          </div>
          <p style={{ margin: '4px 0 0', fontSize: '0.84rem', color: 'var(--text-muted)' }}>
            Submit support requests and use self-help troubleshooting guides.
          </p>
        </div>

        {/* Quick System Status Badge */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 14, background: 'var(--bg-1)',
          padding: '8px 14px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border)'
        }}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
            <span style={{ fontSize: '0.68rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)' }}>
              Network Connection
            </span>
            <span style={{ fontSize: '0.82rem', fontWeight: 700, color: online ? 'var(--success)' : 'var(--warning)', display: 'flex', alignItems: 'center', gap: 5 }}>
              {online ? <CheckIcon size={14} /> : <AlertIcon size={14} />}
              {online ? 'Network available' : 'Offline'}
            </span>
          </div>
          <span style={{ width: 1, height: 24, background: 'var(--border)' }} />
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
            <span style={{ fontSize: '0.68rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)' }}>
              BizID
            </span>
            <span style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono, monospace)' }}>
              {bizId}
            </span>
          </div>
        </div>
      </div>

      {/* 2-Column Main Workspace */}
      <div className="support-workspace">

        {/* ── Left Column: Support Form ── */}
        <div className="support-form-card" style={{
          background: 'var(--bg-2)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-lg)', padding: '24px 28px',
          boxShadow: 'var(--shadow-sm)', display: 'flex', flexDirection: 'column', gap: 20
        }}>
          <div>
            <h3 style={{ fontSize: '1.05rem', fontWeight: 700, color: 'var(--text-primary)', margin: '0 0 6px 0' }}>
              Submit a Support Request
            </h3>
            <p style={{ fontSize: '0.84rem', color: 'var(--text-secondary)', margin: 0, lineHeight: 1.5 }}>
              Encountered a bug or need technical guidance? Fill in the details below. Our engineering desk will review your submission and diagnostic logs.
            </p>
          </div>

          {status && (
            <div role={status.type === 'success' ? 'status' : 'alert'} style={{
              background: status.type === 'success' ? 'var(--success-dim)' : 'var(--danger-dim)',
              border: `1px solid ${status.type === 'success' ? 'rgba(31, 107, 58, 0.3)' : 'rgba(234, 67, 53, 0.3)'}`,
              borderRadius: 'var(--radius-md)', padding: '14px 18px',
              color: status.type === 'success' ? 'var(--success)' : 'var(--danger)',
              display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: '0.86rem', lineHeight: 1.5
            }}>
              <div style={{ flexShrink: 0, marginTop: 2 }}>
                {status.type === 'success' ? <CheckIcon size={18} /> : <AlertIcon size={18} />}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 700 }}>{status.type === 'success' ? 'Request Dispatched' : 'Submission Alert'}</div>
                <div>{status.msg}</div>
                {status.type === 'success' && showDirectContacts && SUPPORT_CONTACTS.phone && (
                  <div style={{ marginTop: 10, display: 'flex', gap: 10 }}>
                    <button
                      type="button"
                      onClick={openWhatsAppSupport}
                      style={{
                        background: '#25D366', color: '#fff', border: 'none',
                        padding: '6px 14px', borderRadius: 'var(--radius-sm)',
                        fontSize: '0.78rem', fontWeight: 600, cursor: 'pointer',
                        display: 'inline-flex', alignItems: 'center', gap: 6
                      }}
                    >
                      <WhatsAppOutlineIcon size={14} />
                      Follow up on WhatsApp &rarr;
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}

          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

            {/* Category selector with outline SVG icons */}
            <div>
              <label style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px', display: 'block', marginBottom: 8 }}>
                Issue Category
              </label>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 8 }}>
                {CATEGORIES.map(cat => (
                  <button
                    key={cat.id}
                    type="button"
                    aria-pressed={category === cat.id}
                    onClick={() => setCategory(cat.id)}
                    style={{
                      padding: '10px 12px', textAlign: 'left',
                      borderRadius: 'var(--radius-md)', cursor: 'pointer',
                      border: category === cat.id ? '2px solid var(--accent)' : '1px solid var(--border)',
                      background: category === cat.id ? 'var(--accent-dim)' : 'var(--bg-1)',
                      color: category === cat.id ? 'var(--accent)' : 'var(--text-primary)',
                      display: 'flex', flexDirection: 'column', gap: 4,
                      transition: 'all 0.15s ease'
                    }}
                  >
                    <div style={{ fontSize: '0.86rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 7 }}>
                      <span style={{ display: 'inline-flex', alignItems: 'center', color: category === cat.id ? 'var(--accent)' : 'var(--text-secondary)' }}>
                        {cat.icon}
                      </span>
                      <span>{cat.label}</span>
                    </div>
                    <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', lineHeight: 1.3 }}>
                      {cat.desc}
                    </span>
                  </button>
                ))}
              </div>
            </div>

            {/* Subject & Priority */}
            <div className="support-subject-row">
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <label htmlFor={`${formId}-subject`} style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                  Summary / Subject
                </label>
                <input
                  id={`${formId}-subject`}
                  maxLength={200}
                  type="text"
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  placeholder="Brief 1-line summary (e.g. Printer not auto-cutting after bill)"
                  disabled={submitting}
                  style={{
                    background: 'var(--bg-1)', border: '1px solid var(--border)',
                    borderRadius: 'var(--radius-sm)', padding: '9px 12px',
                    color: 'var(--text-primary)', fontSize: '0.88rem', outline: 'none'
                  }}
                />
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <label htmlFor={`${formId}-priority`} style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                  Priority
                </label>
                <select
                  id={`${formId}-priority`}
                  value={priority}
                  onChange={(e) => setPriority(e.target.value)}
                  disabled={submitting}
                  style={{
                    background: 'var(--bg-1)', border: '1px solid var(--border)',
                    borderRadius: 'var(--radius-sm)', padding: '9px 12px',
                    color: 'var(--text-primary)', fontSize: '0.88rem', outline: 'none',
                    fontWeight: 600
                  }}
                >
                  <option value="normal">Normal</option>
                  <option value="urgent">Urgent (Billing Blocked)</option>
                </select>
              </div>
            </div>

            {/* Description */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <label htmlFor={`${formId}-message`} style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                  Detailed Description *
                </label>
                <span style={{ fontSize: '0.74rem', color: 'var(--text-muted)' }}>
                  {formattedMessage.length} / 8,000 total
                </span>
              </div>
              <textarea
                id={`${formId}-message`}
                maxLength={8000}
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="Please describe what happened, steps to reproduce, or your exact feature idea..."
                disabled={submitting}
                style={{
                  width: '100%', minHeight: 140,
                  background: 'var(--bg-1)', border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-md)', padding: '12px 14px',
                  color: 'var(--text-primary)', fontSize: '0.88rem',
                  fontFamily: 'inherit', lineHeight: 1.5, resize: 'vertical',
                  outline: 'none', transition: 'border-color 0.15s'
                }}
                onFocus={e => { e.currentTarget.style.borderColor = 'var(--accent)' }}
                onBlur={e => { e.currentTarget.style.borderColor = 'var(--border)' }}
              />
            </div>

            {/* Contact Information */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <label htmlFor={`${formId}-contact`} style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                Your Contact Phone / Email (For Support Follow-Up)
              </label>
              <input
                id={`${formId}-contact`}
                maxLength={200}
                type="text"
                value={contact}
                onChange={(e) => setContact(e.target.value)}
                placeholder="e.g. 9876543210 or yourname@business.com"
                disabled={submitting}
                style={{
                  background: 'var(--bg-1)', border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-sm)', padding: '9px 12px',
                  color: 'var(--text-primary)', fontSize: '0.88rem', outline: 'none'
                }}
              />
            </div>

            {/* Attach Diagnostics */}
            <label
              style={{
                display: 'flex', alignItems: 'flex-start', gap: 10,
                background: 'var(--bg-1)', border: '1px solid var(--border)',
                borderRadius: 'var(--radius-md)', padding: '12px 16px',
                cursor: 'pointer'
              }}
            >
              <input
                type="checkbox"
                checked={attachLogs}
                onChange={e => setAttachLogs(e.target.checked)}
                disabled={submitting || cloudHosted}
                style={{
                  cursor: 'pointer', accentColor: 'var(--accent)',
                  width: 17, height: 17, marginTop: 2
                }}
              />
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <span style={{ fontSize: '0.86rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                  Attach application diagnostics log files (recommended for fast resolution)
                </span>
                <span style={{ fontSize: '0.76rem', color: 'var(--text-muted)', lineHeight: 1.4 }}>
                  {cloudHosted ? 'Desktop log attachments are available when using the downloaded app with its local backend.' : 'Includes available application log files from this device. Review sensitive details before choosing to attach logs.'}
                </span>
              </div>
            </label>

            {/* Submit Buttons Strip */}
            <div className="support-submit-row" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: 6 }}>
              <button
                type="button"
                onClick={() => setShowDiagnostics(!showDiagnostics)}
                style={{
                  background: 'transparent', border: 'none', color: 'var(--text-muted)',
                  fontSize: '0.8rem', cursor: 'pointer', textDecoration: 'underline'
                }}
              >
                {showDiagnostics ? 'Hide diagnostic details' : 'Preview diagnostic data'}
              </button>

              <button
                type="submit"
                disabled={submitting}
                style={{
                  padding: '11px 24px', borderRadius: 'var(--radius-md)',
                  background: 'var(--accent-solid, var(--accent))', color: 'var(--accent-foreground, #ffffff)',
                  border: 'none', cursor: submitting ? 'not-allowed' : 'pointer',
                  fontSize: '0.92rem', fontWeight: 700,
                  boxShadow: '0 2px 8px rgba(193, 95, 60, 0.28)',
                  display: 'inline-flex', alignItems: 'center', gap: 8,
                  opacity: submitting ? 0.75 : 1, transition: 'all 0.15s ease'
                }}
              >
                <MessageIcon size={16} />
                <span>{submitting ? 'Packaging Logs & Submitting...' : 'Submit Support Ticket'}</span>
              </button>
            </div>

            {/* Diagnostic preview accordion */}
            {showDiagnostics && (
              <div style={{
                background: 'var(--bg-3)', border: '1px solid var(--border)',
                borderRadius: 'var(--radius-sm)', padding: '12px 14px',
                fontSize: '0.76rem', fontFamily: 'var(--font-mono, monospace)',
                color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: 4
              }}>
                <div><strong>BizID:</strong> {bizId}</div>
                <div><strong>Platform:</strong> {navigator.platform || 'Desktop Client'}</div>
                <div><strong>User Agent:</strong> {navigator.userAgent.slice(0, 75)}&hellip;</div>
                <div><strong>Resolution:</strong> {window.innerWidth} &times; {window.innerHeight}</div>
                <div><strong>Hosting:</strong> {hostingLabel}</div>
                <div><strong>App Version:</strong> {appVersion}</div>
              </div>
            )}
          </form>
        </div>

        {/* ── Right Column: Direct Channels & FAQs ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

          {/* Direct Channels Card */}
          {showDirectContacts && <div style={{
            background: 'var(--bg-2)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius-lg)', padding: '20px 22px',
            boxShadow: 'var(--shadow-sm)', display: 'flex', flexDirection: 'column', gap: 14
          }}>
            <div>
              <h4 style={{ fontSize: '0.96rem', fontWeight: 700, color: 'var(--text-primary)', margin: '0 0 4px 0' }}>
                Direct Contact Channels
              </h4>
              <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', margin: 0 }}>
                Contact hours: {SUPPORT_CONTACTS.hours}
              </p>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {/* WhatsApp */}
              {SUPPORT_CONTACTS.phone && <button
                type="button"
                onClick={openWhatsAppSupport}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '12px 14px', borderRadius: 'var(--radius-md)',
                  background: 'rgba(37, 211, 102, 0.08)', border: '1px solid rgba(37, 211, 102, 0.3)',
                  cursor: 'pointer', textAlign: 'left', transition: 'all 0.15s ease'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div style={{
                    width: 32, height: 32, borderRadius: '50%', background: '#25D366',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff'
                  }}>
                    <WhatsAppOutlineIcon size={17} />
                  </div>
                  <div>
                    <div style={{ fontSize: '0.88rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                      WhatsApp Desk
                    </div>
                    <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)' }}>
                      Open a support conversation
                    </div>
                  </div>
                </div>
                <span style={{ fontSize: '0.8rem', fontWeight: 700, color: '#128C7E' }}>Chat Now &rarr;</span>
              </button>}

              {/* Email */}
              {SUPPORT_CONTACTS.email && <button
                type="button"
                onClick={openEmailSupport}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '12px 14px', borderRadius: 'var(--radius-md)',
                  background: 'var(--bg-1)', border: '1px solid var(--border)',
                  cursor: 'pointer', textAlign: 'left', transition: 'all 0.15s ease'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div style={{
                    width: 32, height: 32, borderRadius: '50%', background: 'var(--accent-dim)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--accent)'
                  }}>
                    <MailIcon size={16} />
                  </div>
                  <div>
                    <div style={{ fontSize: '0.88rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                      Email Desk
                    </div>
                    <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)' }}>
                      {SUPPORT_CONTACTS.email}
                    </div>
                  </div>
                </div>
                <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)' }}>Send Mail &rarr;</span>
              </button>}

              {/* Phone */}
              {SUPPORT_CONTACTS.phone && <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '12px 14px', borderRadius: 'var(--radius-md)',
                background: 'var(--bg-1)', border: '1px solid var(--border)'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div style={{
                    width: 32, height: 32, borderRadius: '50%', background: 'var(--bg-3)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-primary)'
                  }}>
                    <PhoneIcon size={16} />
                  </div>
                  <div>
                    <div style={{ fontSize: '0.88rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                      Support Helpline
                    </div>
                    <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)' }}>
                      {SUPPORT_CONTACTS.hours}
                    </div>
                  </div>
                </div>
                <a
                  href={`tel:${SUPPORT_CONTACTS.phone}`}
                  style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--accent)', textDecoration: 'none' }}
                >
                  Call Support
                </a>
              </div>}
            </div>
          </div>}

          {/* Quick Self-Help FAQs */}
          <div style={{
            background: 'var(--bg-2)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius-lg)', padding: '20px 22px',
            boxShadow: 'var(--shadow-sm)', display: 'flex', flexDirection: 'column', gap: 12
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
              <SparkleIcon size={16} fill="var(--accent)" />
              <h4 style={{ fontSize: '0.96rem', fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>
                Quick Self-Help &amp; Solutions
              </h4>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {FAQS.map((faq, idx) => {
                const isOpen = expandedFaq === idx
                return (
                  <div
                    key={idx}
                    style={{
                      border: '1px solid var(--border)', borderRadius: 'var(--radius-md)',
                      overflow: 'hidden', background: isOpen ? 'var(--bg-1)' : 'transparent',
                      transition: 'background 0.15s ease'
                    }}
                  >
                    <button
                      type="button"
                      aria-expanded={isOpen}
                      onClick={() => setExpandedFaq(isOpen ? null : idx)}
                      style={{
                        width: '100%', padding: '10px 14px', background: 'transparent',
                        border: 'none', cursor: 'pointer', textAlign: 'left',
                        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                        gap: 10, fontSize: '0.83rem', fontWeight: 600, color: 'var(--text-primary)'
                      }}
                    >
                      <span>{faq.q}</span>
                      <span style={{ color: 'var(--text-muted)', flexShrink: 0 }}>
                        {isOpen ? <ChevronDownIcon size={15} /> : <ChevronRightIcon size={15} />}
                      </span>
                    </button>
                    {isOpen && (
                      <div style={{
                        padding: '0 14px 12px', fontSize: '0.8rem',
                        color: 'var(--text-secondary)', lineHeight: 1.5,
                        borderTop: '1px dashed var(--border)', paddingTop: 10
                      }}>
                        {faq.a}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>

          {/* Documentation & Manuals Links */}
          {(user?.role || '').toLowerCase() !== 'cashier' && <div style={{
            background: 'var(--bg-1)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius-md)', padding: '14px 18px',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <InfoIcon size={18} />
              <span style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                Looking for database migration or backup?
              </span>
            </div>
            <button
              type="button"
              onClick={() => navigate('/settings?tab=migration')}
              style={{
                fontSize: '0.78rem', fontWeight: 700, color: 'var(--accent)',
                background: 'transparent', border: 'none', cursor: 'pointer',
                padding: 0, textDecoration: 'underline'
              }}
            >
              Go to Migration &rarr;
            </button>
          </div>}

        </div>

      </div>
    </div>
  )
}
