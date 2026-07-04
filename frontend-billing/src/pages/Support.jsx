import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { API_BASE } from '../config'
import { AlertIcon, CheckIcon } from '../components/Icons'

export default function Support() {
  const navigate = useNavigate()
  const { authFetch } = useAuth()
  
  const [message, setMessage] = useState('')
  const [attachLogs, setAttachLogs] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [status, setStatus] = useState(null) // { type: 'success' | 'error', msg: string }

  async function handleSubmit(e) {
    e.preventDefault()
    if (!message.trim()) {
      setStatus({ type: 'error', msg: 'Please enter a description of your issue.' })
      return
    }

    setSubmitting(true)
    setStatus(null)

    try {
      const formData = new FormData()
      formData.append('message', message)
      formData.append('attach_logs', attachLogs ? 'true' : 'false')

      const res = await authFetch(`${API_BASE}/feedback/submit`, {
        method: 'POST',
        // Note: fetch automatically sets content-type for FormData with boundaries,
        // so we do not manually set Content-Type header.
        body: formData,
      })

      const data = await res.json()
      if (res.ok) {
        setStatus({ type: 'success', msg: 'Thank you! Your feedback and diagnostics have been shared with the support team.' })
        setMessage('')
      } else {
        throw new Error(data.detail || data.error || 'Failed to submit feedback.')
      }
    } catch (err) {
      console.error('Feedback submit error:', err)
      setStatus({ type: 'error', msg: err.message || 'Network error, please try again.' })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="admin-main" style={{ maxWidth: 640, margin: '40px auto', padding: '0 20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20 }}>
        <button
          onClick={() => navigate(-1)}
          style={{
            background: 'transparent',
            border: 'none',
            color: 'var(--text-muted, #9ca3af)',
            cursor: 'pointer',
            fontSize: '1.2rem',
            padding: '4px 8px',
            display: 'flex',
            alignItems: 'center'
          }}
          title="Go back"
        >
          ←
        </button>
        <h1 style={{ fontSize: '1.8rem', fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>
          Feedback & Support
        </h1>
      </div>

      <div
        className="admin-table-widget"
        style={{
          background: 'var(--card-color, #181818)',
          border: '1px solid var(--border-color, rgba(255,255,255,0.12))',
          borderRadius: 12,
          padding: '24px 28px',
          boxShadow: '0 10px 30px rgba(0,0,0,0.3)'
        }}
      >
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', lineHeight: 1.6, margin: '0 0 20px 0' }}>
          Encountered an issue or have a feature suggestion? Let us know! Submitting feedback compiles your local diagnostics log and uploads it directly to the cloud where the support team can resolve it.
        </p>

        {status && (
          <div
            style={{
              background: status.type === 'success' ? 'rgba(34, 197, 94, 0.08)' : 'rgba(239, 68, 68, 0.08)',
              border: `1px solid ${status.type === 'success' ? 'rgba(34, 197, 94, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
              borderRadius: 8,
              padding: '12px 16px',
              marginBottom: 20,
              fontSize: '0.85rem',
              color: status.type === 'success' ? '#22c55e' : '#ef4444',
              display: 'flex',
              alignItems: 'center',
              gap: 8
            }}
          >
            {status.type === 'success' ? <CheckIcon size={16} /> : <AlertIcon size={16} />}
            <span>{status.msg}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <label style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-muted)' }}>
              Describe the Issue / Suggestion
            </label>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Please provide details about what happened, steps to reproduce, or your feedback..."
              disabled={submitting}
              style={{
                width: '100%',
                minHeight: 140,
                background: 'rgba(0,0,0,0.2)',
                border: '1px solid var(--border-color, rgba(255,255,255,0.15))',
                borderRadius: 8,
                padding: '10px 14px',
                color: '#fff',
                fontSize: '0.88rem',
                fontFamily: 'inherit',
                lineHeight: 1.5,
                resize: 'vertical',
                outline: 'none'
              }}
            />
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }} onClick={() => !submitting && setAttachLogs(!attachLogs)}>
            <input
              type="checkbox"
              checked={attachLogs}
              onChange={() => {}} // handled by div click
              disabled={submitting}
              style={{
                cursor: 'pointer',
                accentColor: 'var(--accent, #6366f1)',
                width: 16,
                height: 16
              }}
            />
            <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              Attach application diagnostics log files (recommended for issue debugging)
            </span>
          </div>

          <button
            type="submit"
            disabled={submitting}
            style={{
              padding: '11px 20px',
              borderRadius: 8,
              background: 'var(--accent, #6366f1)',
              color: '#fff',
              border: 'none',
              cursor: submitting ? 'not-allowed' : 'pointer',
              fontSize: '0.9rem',
              fontWeight: 700,
              alignSelf: 'flex-start',
              opacity: submitting ? 0.7 : 1,
              transition: 'opacity 0.2s',
              display: 'flex',
              alignItems: 'center',
              gap: 8
            }}
          >
            {submitting ? 'Packaging Logs & Submitting...' : 'Submit Support Ticket'}
          </button>
        </form>
      </div>
    </div>
  )
}
