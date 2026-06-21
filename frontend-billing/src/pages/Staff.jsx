import React, { useState, useEffect, useCallback } from 'react'
import AppLayout from '../layouts/AppLayout'
import { useAuth } from '../contexts/AuthContext'
import { logger } from '../utils/logger'
import { ContactsIcon, CheckIcon, CloseIcon } from '../components/Icons'

// Staff management — owner creates/removes cashier logins that share this
// business's data. The backend (/staff) is owner-only and tenant-scoped.
export default function Staff() {
  const { authFetch } = useAuth()
  const [staff, setStaff] = useState([])
  const [loading, setLoading] = useState(true)
  const [form, setForm] = useState({ username: '', password: '' })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await authFetch('/staff')
      if (res.ok) {
        setStaff(await res.json())
      } else if (res.status === 403) {
        setError('Only the business owner can manage staff.')
      }
    } catch (err) {
      logger.error('[STAFF] failed to load staff', err)
      setError('Could not load staff.')
    } finally {
      setLoading(false)
    }
  }, [authFetch])

  useEffect(() => { load() }, [load])

  const addStaff = async (e) => {
    e.preventDefault()
    setError(''); setSuccess('')
    if (!form.username.trim() || !form.password) {
      setError('Username and password are required.')
      return
    }
    setSubmitting(true)
    try {
      const res = await authFetch('/staff', {
        method: 'POST',
        body: JSON.stringify({ username: form.username.trim(), password: form.password, role: 'cashier' }),
      })
      if (res.ok) {
        const created = await res.json()
        logger.info('[STAFF] created cashier', created.username)
        setSuccess(`Cashier "${created.username}" created.`)
        setForm({ username: '', password: '' })
        load()
      } else {
        const err = await res.json().catch(() => ({}))
        setError(err.detail || 'Could not create staff.')
      }
    } catch (err) {
      logger.error('[STAFF] create failed', err)
      setError('Network error. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const resetPassword = async (s) => {
    const pw = window.prompt(`New password for "${s.username}" (8+ chars, with upper, lower and a number):`)
    if (!pw) return
    setError(''); setSuccess('')
    try {
      const res = await authFetch(`/staff/${s.id}`, { method: 'PATCH', body: JSON.stringify({ password: pw }) })
      if (res.ok) {
        setSuccess(`Password reset for "${s.username}".`)
      } else {
        const err = await res.json().catch(() => ({}))
        setError(err.detail || 'Could not reset password.')
      }
    } catch (err) {
      logger.error('[STAFF] password reset failed', err)
      setError('Network error. Please try again.')
    }
  }

  const removeStaff = async (s) => {
    if (!window.confirm(`Remove cashier "${s.username}"? They will no longer be able to log in.`)) return
    setError(''); setSuccess('')
    try {
      const res = await authFetch(`/staff/${s.id}`, { method: 'DELETE' })
      if (res.ok) {
        logger.info('[STAFF] removed', s.username)
        setSuccess(`Removed "${s.username}".`)
        setStaff(prev => prev.filter(x => x.id !== s.id))
      } else {
        const err = await res.json().catch(() => ({}))
        setError(err.detail || 'Could not remove staff.')
      }
    } catch (err) {
      logger.error('[STAFF] remove failed', err)
      setError('Network error. Please try again.')
    }
  }

  return (
    <AppLayout title="Staff">
      <div className="slide-up">
        {/* Header */}
        <div className="page-header">
          <div className="page-header-left">
            <h1 className="page-title">
              <ContactsIcon size={22} /> Staff & Cashiers
            </h1>
            <p className="page-subtitle">
              Cashiers can ring up sales and take payments on this shop's data, but can't see reports, returns, purchases, settings, or manage staff.
            </p>
          </div>
        </div>

        <div style={{ maxWidth: 820, margin: '0 auto', padding: '0 4px 24px' }}>
          {error && (
            <div className="alert alert-danger" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <CloseIcon size={16} /> {error}
            </div>
          )}
          {success && (
            <div className="alert alert-success" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <CheckIcon size={16} /> {success}
            </div>
          )}

          {/* Add cashier */}
          <form onSubmit={addStaff} className="card" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto', gap: '16px', alignItems: 'end', margin: '20px 0' }}>
            <div className="form-group">
              <label className="form-label">Username</label>
              <input 
                className="form-input"
                value={form.username} 
                onChange={e => setForm(f => ({ ...f, username: e.target.value }))}
                placeholder="cashier login" 
                autoComplete="off" 
              />
            </div>
            <div className="form-group">
              <label className="form-label">Password</label>
              <input 
                type="password" 
                className="form-input"
                value={form.password} 
                onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                placeholder="8+ chars, A-z, 0-9" 
                autoComplete="new-password" 
              />
            </div>
            <button type="submit" className="btn btn-primary" disabled={submitting} style={{ height: '38px' }}>
              {submitting ? 'Adding…' : '+ Add Cashier'}
            </button>
          </form>

          {/* Staff list */}
          {loading ? (
            <p style={{ color: 'var(--text-muted)' }}>Loading…</p>
          ) : staff.length === 0 ? (
            <p style={{ color: 'var(--text-muted)' }}>No cashiers yet. Add one above to let staff bill on this shop.</p>
          ) : (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Username</th>
                    <th>Role</th>
                    <th style={{ textAlign: 'right' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {staff.map(s => (
                    <tr key={s.id}>
                      <td className="td-primary">{s.username}</td>
                      <td>
                        <span className="badge badge-muted">{s.role}</span>
                      </td>
                      <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                        <button type="button" className="btn btn-ghost btn-sm" onClick={() => resetPassword(s)} style={{ marginRight: 6 }}>Reset password</button>
                        <button type="button" className="btn btn-ghost btn-sm" onClick={() => removeStaff(s)} style={{ color: 'var(--danger)' }}>Remove</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </AppLayout>
  )
}
