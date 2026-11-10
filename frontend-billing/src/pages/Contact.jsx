import React, { useState } from 'react'
import LegalLayout from '../layouts/LegalLayout'
import { useAuth } from '../contexts/AuthContext'
import { Link } from 'react-router-dom'

export default function Contact() {
  const { user } = useAuth()
  const [formData, setFormData] = useState({
    name: user?.business_name || '',
    email: user?.email || '',
    category: 'support',
    message: '',
  })
  const [sent, setSent] = useState(false)

  const handleSubmit = (e) => {
    e.preventDefault()
    // Prepare direct mailto link for reliable client-side delivery
    const subject = encodeURIComponent(`[Stater Bill ${formData.category.toUpperCase()}] Inquiry from ${formData.name || 'User'}`)
    const body = encodeURIComponent(
      `Name / Business: ${formData.name}\n` +
      `Email: ${formData.email}\n` +
      `Category: ${formData.category}\n` +
      `User ID: ${user?.public_id || 'Guest/Unregistered'}\n\n` +
      `Message:\n${formData.message}`
    )
    window.location.href = `mailto:rakshithananda18@gmail.com?subject=${subject}&body=${body}`
    setSent(true)
  }

  return (
    <LegalLayout
      title="Contact & Support"
      subtitle="We are here to assist with billing setups, technical support, hardware integration, or partnership queries."
      lastUpdated="November 2026"
    >
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 24, marginBottom: 36 }}>
        {/* Contact info card */}
        <div style={{
          padding: 22,
          borderRadius: 'var(--radius-lg, 12px)',
          backgroundColor: 'var(--surface, #ffffff)',
          border: '1px solid var(--border, #e5e7eb)',
          display: 'flex',
          flexDirection: 'column',
          gap: 16,
        }}>
          <div>
            <h3 style={{ fontSize: '1.05rem', fontWeight: 700, margin: '0 0 6px 0', color: 'var(--text-primary)' }}>
              Official Communication
            </h3>
            <p style={{ margin: 0, fontSize: '0.88rem', color: 'var(--text-secondary)' }}>
              Reach out directly to the core engineering & operations team.
            </p>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, fontSize: '0.9rem' }}>
            <div>
              <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                Primary Support Email
              </span>
              <p style={{ margin: '2px 0 0 0', fontWeight: 600 }}>
                <a href="mailto:rakshithananda18@gmail.com" style={{ color: 'var(--accent, #c15f3c)', textDecoration: 'none' }}>
                  rakshithananda18@gmail.com
                </a>
              </p>
            </div>

            <div>
              <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                Operating Hours
              </span>
              <p style={{ margin: '2px 0 0 0', color: 'var(--text-primary)' }}>
                Monday – Saturday: 10:00 AM – 6:00 PM (IST)
              </p>
            </div>

            <div>
              <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                Operational Location
              </span>
              <p style={{ margin: '2px 0 0 0', color: 'var(--text-primary)' }}>
                Bengaluru, Karnataka, India
              </p>
            </div>
          </div>

          {user && (
            <div style={{
              marginTop: 'auto',
              padding: 12,
              borderRadius: 'var(--radius-md, 8px)',
              backgroundColor: 'var(--bg-1, #f4f4f1)',
              fontSize: '0.82rem',
            }}>
              <strong>Signed-in Business:</strong> {user.business_name || user.username}
              <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem', marginTop: 2 }}>
                BizID: <code>{user.public_id || user.id}</code>
              </div>
            </div>
          )}
        </div>

        {/* Send message card */}
        <div style={{
          padding: 22,
          borderRadius: 'var(--radius-lg, 12px)',
          backgroundColor: 'var(--surface, #ffffff)',
          border: '1px solid var(--border, #e5e7eb)',
        }}>
          <h3 style={{ fontSize: '1.05rem', fontWeight: 700, margin: '0 0 14px 0', color: 'var(--text-primary)' }}>
            Send an Inquiry
          </h3>

          {sent ? (
            <div style={{
              padding: 18,
              borderRadius: 'var(--radius-md, 8px)',
              backgroundColor: 'var(--success-dim, rgba(31, 107, 58, 0.08))',
              border: '1px solid var(--success, #1f6b3a)',
              color: 'var(--success, #1f6b3a)',
            }}>
              <p style={{ fontWeight: 600, margin: '0 0 4px 0' }}>✓ Email client opened!</p>
              <p style={{ margin: 0, fontSize: '0.85rem' }}>
                Your message has been transferred to your email application. Simply click send, and our team will get back to you within 24 hours.
              </p>
              <button
                type="button"
                onClick={() => setSent(false)}
                style={{
                  marginTop: 12,
                  padding: '6px 12px',
                  borderRadius: 6,
                  border: '1px solid currentColor',
                  background: 'none',
                  color: 'inherit',
                  cursor: 'pointer',
                  fontSize: '0.8rem',
                }}
              >
                Send another message
              </button>
            </div>
          ) : (
            <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.78rem', fontWeight: 600, marginBottom: 4 }}>
                  Your Name or Business
                </label>
                <input
                  type="text"
                  required
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  placeholder="e.g. Anand Trading Co."
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: 'var(--radius-md, 8px)',
                    border: '1px solid var(--border, #d1d5db)',
                    backgroundColor: 'var(--bg, #ffffff)',
                    color: 'inherit',
                    boxSizing: 'border-box',
                    fontSize: '0.88rem',
                  }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.78rem', fontWeight: 600, marginBottom: 4 }}>
                  Email Address
                </label>
                <input
                  type="email"
                  required
                  value={formData.email}
                  onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                  placeholder="you@example.com"
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: 'var(--radius-md, 8px)',
                    border: '1px solid var(--border, #d1d5db)',
                    backgroundColor: 'var(--bg, #ffffff)',
                    color: 'inherit',
                    boxSizing: 'border-box',
                    fontSize: '0.88rem',
                  }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.78rem', fontWeight: 600, marginBottom: 4 }}>
                  Category
                </label>
                <select
                  value={formData.category}
                  onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: 'var(--radius-md, 8px)',
                    border: '1px solid var(--border, #d1d5db)',
                    backgroundColor: 'var(--bg, #ffffff)',
                    color: 'inherit',
                    boxSizing: 'border-box',
                    fontSize: '0.88rem',
                  }}
                >
                  <option value="support">Technical Support / Bug Report</option>
                  <option value="hardware">Printer / Hardware Setup</option>
                  <option value="billing">GST, Tax & Invoicing Assistance</option>
                  <option value="sync">Cloud Sync & Database Migration</option>
                  <option value="subscription">Pro Subscription & Plans</option>
                  <option value="other">General Inquiry</option>
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.78rem', fontWeight: 600, marginBottom: 4 }}>
                  Message
                </label>
                <textarea
                  required
                  rows={4}
                  value={formData.message}
                  onChange={(e) => setFormData({ ...formData, message: e.target.value })}
                  placeholder="Describe your question or issue in detail..."
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: 'var(--radius-md, 8px)',
                    border: '1px solid var(--border, #d1d5db)',
                    backgroundColor: 'var(--bg, #ffffff)',
                    color: 'inherit',
                    boxSizing: 'border-box',
                    fontSize: '0.88rem',
                    resize: 'vertical',
                  }}
                />
              </div>

              <button
                type="submit"
                style={{
                  padding: '10px 16px',
                  borderRadius: 'var(--radius-md, 8px)',
                  backgroundColor: 'var(--accent, #c15f3c)',
                  color: '#ffffff',
                  border: 'none',
                  fontWeight: 600,
                  fontSize: '0.9rem',
                  cursor: 'pointer',
                  transition: 'opacity 0.2s',
                }}
              >
                Send Message →
              </button>
            </form>
          )}
        </div>
      </div>

      {/* Quick FAQ / In-App shortcuts */}
      <section style={{
        padding: 20,
        borderRadius: 'var(--radius-lg, 12px)',
        backgroundColor: 'var(--bg-1, #f4f4f1)',
        border: '1px solid var(--border, #e5e7eb)',
      }}>
        <h3 style={{ fontSize: '1rem', fontWeight: 700, margin: '0 0 10px 0', color: 'var(--text-primary)' }}>
          Already using Stater Bill?
        </h3>
        <p style={{ margin: '0 0 14px 0', fontSize: '0.88rem', color: 'var(--text-secondary)' }}>
          You can raise in-app tickets, run diagnostic health checks, and browse our troubleshooting guides right from your workspace.
        </p>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <Link
            to="/settings?tab=support"
            style={{
              fontSize: '0.82rem',
              fontWeight: 600,
              padding: '6px 12px',
              borderRadius: 6,
              backgroundColor: 'var(--surface, #ffffff)',
              border: '1px solid var(--border, #d1d5db)',
              color: 'var(--text-primary)',
              textDecoration: 'none',
            }}
          >
            In-App Support Center →
          </Link>
          <Link
            to="/settings?tab=ops"
            style={{
              fontSize: '0.82rem',
              fontWeight: 600,
              padding: '6px 12px',
              borderRadius: 6,
              backgroundColor: 'var(--surface, #ffffff)',
              border: '1px solid var(--border, #d1d5db)',
              color: 'var(--text-primary)',
              textDecoration: 'none',
            }}
          >
            System Health & Diagnostics →
          </Link>
        </div>
      </section>
    </LegalLayout>
  )
}
