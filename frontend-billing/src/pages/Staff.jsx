import React, { useState, useEffect, useCallback } from 'react'
import AppLayout from '../layouts/AppLayout'
import { useAuth } from '../contexts/AuthContext'
import { logger } from '../utils/logger'
import { ContactsIcon, CheckIcon, CloseIcon } from '../components/Icons'

// Staff management — owner creates/removes cashier logins that share this
// business's data. The backend (/staff) is owner-only and tenant-scoped.
export default function Staff() {
  const { authFetch, settings } = useAuth()
  const [staff, setStaff] = useState([])
  const [loading, setLoading] = useState(true)
  const [form, setForm] = useState({ username: '', password: '', counter_prefix: '' })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  // Owner-defined named counters (multi-terminal POS §9.3a). Stored on the
  // owner's settings (transactions section → cashier-write-blocked). Each is
  // { name, prefix } e.g. { name:'Front Counter', prefix:'C1' }. Staff are then
  // ASSIGNED one (their users.counter_prefix) from this list via a dropdown.
  const counters = Array.isArray(settings?.transactions?.counters) ? settings.transactions.counters : []
  const [newCounter, setNewCounter] = useState({ name: '', prefix: '' })

  const saveCounters = async (list) => {
    const res = await authFetch('/settings', { method: 'PUT', body: JSON.stringify({ transactions: { counters: list } }) })
    if (res.ok) {
      window.dispatchEvent(new CustomEvent('refresh-settings'))  // AuthContext reloads settings
      return true
    }
    const err = await res.json().catch(() => ({}))
    setError(err.detail || 'Could not save counters.')
    return false
  }

  const addCounter = async () => {
    setError(''); setSuccess('')
    const name = newCounter.name.trim()
    const prefix = newCounter.prefix.replace(/[^a-zA-Z0-9_-]/g, '').replace(/-+$/, '').slice(0, 8)
    if (!prefix) { setError('A counter needs a prefix (e.g. C1).'); return }
    if (counters.some(c => (c.prefix || '').toUpperCase() === prefix.toUpperCase())) { setError(`Counter prefix "${prefix}" already exists.`); return }
    if (await saveCounters([...counters, { name: name || prefix, prefix }])) {
      setNewCounter({ name: '', prefix: '' })
      setSuccess(`Counter "${name || prefix}" added.`)
    }
  }

  const removeCounter = async (prefix) => {
    if (!window.confirm(`Remove counter "${prefix}"? Staff assigned to it keep their prefix until you reassign them.`)) return
    setError(''); setSuccess('')
    await saveCounters(counters.filter(c => c.prefix !== prefix))
  }

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
        body: JSON.stringify({ username: form.username.trim(), password: form.password, role: 'cashier', counter_prefix: form.counter_prefix.trim() || null }),
      })
      if (res.ok) {
        const created = await res.json()
        logger.info('[STAFF] created cashier', created.username)
        setSuccess(`Cashier "${created.username}" created.`)
        setForm({ username: '', password: '', counter_prefix: '' })
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

  const setCounter = async (s, prefix) => {
    setError(''); setSuccess('')
    try {
      const res = await authFetch(`/staff/${s.id}`, { method: 'PATCH', body: JSON.stringify({ counter_prefix: prefix }) })
      if (res.ok) {
        const updated = await res.json()
        setStaff(prev => prev.map(x => x.id === s.id ? { ...x, counter_prefix: updated.counter_prefix } : x))
        setSuccess(`Counter for "${s.username}" set to ${updated.counter_prefix || '(none)'}.`)
      } else {
        const err = await res.json().catch(() => ({}))
        setError(err.detail || 'Could not set counter.')
      }
    } catch (err) {
      logger.error('[STAFF] set counter failed', err)
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

          {/* Counters manager — owner defines the shop's named counters once */}
          <div className="card" style={{ margin: '20px 0', padding: 16 }}>
            <label className="form-label" style={{ display: 'block', marginBottom: 8 }}>Counters</label>
            <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: 0, marginBottom: 12 }}>
              Define each till once, then assign a cashier to it below. A cashier's bills auto-number with their counter's prefix (e.g. <strong>C1-0001</strong>) so two counters never share a number.
            </p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: counters.length ? 12 : 0 }}>
              {counters.map(c => (
                <span key={c.prefix} className="badge badge-muted" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 8px' }}>
                  {c.name} · <strong>{c.prefix}</strong>
                  <button type="button" onClick={() => removeCounter(c.prefix)} title="Remove counter"
                    style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--danger)', padding: 0, lineHeight: 1 }}>×</button>
                </span>
              ))}
            </div>
            <div className="staff-counter-form">
              <div className="form-group" style={{ margin: 0 }}>
                <label className="form-label" style={{ fontSize: '0.72rem' }}>Name</label>
                <input className="form-input" value={newCounter.name} placeholder="e.g. Front Counter"
                  onChange={e => setNewCounter(c => ({ ...c, name: e.target.value }))} />
              </div>
              <div className="form-group" style={{ margin: 0 }}>
                <label className="form-label" style={{ fontSize: '0.72rem' }}>Prefix</label>
                <input className="form-input" value={newCounter.prefix} placeholder="C1"
                  onChange={e => setNewCounter(c => ({ ...c, prefix: e.target.value.replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 8) }))} />
              </div>
              <button type="button" className="btn btn-secondary" style={{ height: 38 }} onClick={addCounter}>+ Add Counter</button>
            </div>
          </div>

          {/* Add cashier */}
          <form onSubmit={addStaff} className="card staff-add-form">
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
            <div className="form-group">
              <label className="form-label">Counter</label>
              <select
                className="form-input"
                value={form.counter_prefix}
                onChange={e => setForm(f => ({ ...f, counter_prefix: e.target.value }))}
                title="Assign this cashier to a counter (define counters above)"
              >
                <option value="">— none —</option>
                {counters.map(c => <option key={c.prefix} value={c.prefix}>{c.name} ({c.prefix})</option>)}
              </select>
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
                    <th>Counter</th>
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
                      <td>
                        <select
                          className="form-input"
                          style={{ height: 32, fontSize: '0.82rem', padding: '2px 6px', maxWidth: 200 }}
                          value={counters.some(c => c.prefix === s.counter_prefix) ? s.counter_prefix : (s.counter_prefix || '')}
                          onChange={e => setCounter(s, e.target.value)}
                        >
                          <option value="">— none —</option>
                          {/* keep a stale/unlisted prefix selectable so it isn't silently lost */}
                          {s.counter_prefix && !counters.some(c => c.prefix === s.counter_prefix) && (
                            <option value={s.counter_prefix}>{s.counter_prefix} (unlisted)</option>
                          )}
                          {counters.map(c => <option key={c.prefix} value={c.prefix}>{c.name} ({c.prefix})</option>)}
                        </select>
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
