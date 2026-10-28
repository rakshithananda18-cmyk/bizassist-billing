import React, { useEffect, useRef, useState } from 'react'
import AppLayout from '../layouts/AppLayout'
import { useAuth } from '../contexts/AuthContext'
import { BuildingMark } from '../components/Logo'
import { CheckIcon, ContactsIcon } from '../components/Icons'
import './settings-profile.css'

const EMPTY_PROFILE = {
  business_name: '', gstin: '', phone: '', email: '', address: '',
  state_code: '', pan: '', logo: '', upi_vpa: '',
}

export default function Profile({ embedded = false }) {
  const { authFetch, profile, fetchProfile } = useAuth()
  const [formData, setFormData] = useState(EMPTY_PROFILE)
  const [loading, setLoading] = useState(false)
  const [successMsg, setSuccessMsg] = useState('')
  const [errorMsg, setErrorMsg] = useState('')
  const successTimer = useRef(null)
  const autoSaveTimeoutRef = useRef(null)

  useEffect(() => {
    if (profile) {
      setFormData(Object.fromEntries(Object.keys(EMPTY_PROFILE).map(key => [key, profile[key] || ''])))
    }
  }, [profile])
  useEffect(() => () => clearTimeout(successTimer.current), [])

  const handleChange = e => {
    const { name, value } = e.target
    const nextForm = { ...formData, [name]: value }
    setFormData(nextForm)
    setSuccessMsg('')
    // Debounced background auto-save for edited fields
    clearTimeout(autoSaveTimeoutRef.current)
    if (nextForm.business_name && nextForm.business_name.trim().length > 1) {
      autoSaveTimeoutRef.current = setTimeout(async () => {
        try {
          const res = await authFetch('/profile', {
            method: 'PUT',
            body: JSON.stringify({ ...nextForm, business_name: nextForm.business_name.trim() }),
          })
          if (res.ok) {
            await fetchProfile()
          }
        } catch { /* background retry */ }
      }, 2500)
    }
  }

  const handleLogoChange = e => {
    const file = e.target.files?.[0]
    if (!file) return
    if (file.size > 2 * 1024 * 1024) {
      setErrorMsg('Logo file must be under 2MB')
      return
    }
    if (!file.type.startsWith('image/')) {
      setErrorMsg('Choose an image for your company logo')
      return
    }
    const reader = new FileReader()
    reader.onloadend = () => {
      setFormData(previous => ({ ...previous, logo: reader.result }))
      setErrorMsg('')
      setSuccessMsg('')
    }
    reader.readAsDataURL(file)
  }

  const handleSubmit = async e => {
    e.preventDefault()
    setSuccessMsg('')
    setErrorMsg('')
    if (!formData.business_name.trim()) {
      setErrorMsg('Business name is required')
      return
    }
    setLoading(true)
    try {
      const response = await authFetch('/profile', {
        method: 'PUT',
        body: JSON.stringify({ ...formData, business_name: formData.business_name.trim() }),
      })
      if (!response.ok) {
        const error = await response.json().catch(() => ({}))
        throw new Error(error.detail || 'Failed to update profile')
      }
      await fetchProfile()
      setSuccessMsg('Business profile saved successfully.')
      clearTimeout(successTimer.current)
      successTimer.current = setTimeout(() => setSuccessMsg(''), 4000)
    } catch (error) {
      setErrorMsg(error.message || 'Could not save your business profile')
    } finally {
      setLoading(false)
    }
  }

  const field = (name, label, { type = 'text', hint, full = false, ...props } = {}) => (
    <div className={`profile-field${full ? ' profile-field-full' : ''}`}>
      <label htmlFor={`profile-${name}`}>{label}</label>
      <input id={`profile-${name}`} name={name} type={type} className="form-input"
        value={formData[name]} onChange={handleChange} aria-describedby={hint ? `profile-${name}-hint` : undefined} {...props} />
      {hint && <p id={`profile-${name}-hint`}>{hint}</p>}
    </div>
  )

  const content = (
    <section className="profile-settings" aria-labelledby="profile-settings-title">
      <div className="settings-section-heading">
        <div>
          <p className="settings-eyebrow">Business identity</p>
          <h2 id="profile-settings-title">Business profile</h2>
          <p>Your business details, contact information, and billing identity in one place.</p>
        </div>
        <span className="settings-section-icon" aria-hidden="true"><ContactsIcon size={22} /></span>
      </div>

      {successMsg && <div className="profile-notice profile-notice-success" role="status"><CheckIcon size={16} />{successMsg}</div>}
      {errorMsg && <div className="profile-notice profile-notice-error" role="alert">{errorMsg}</div>}

      <form onSubmit={handleSubmit} className="profile-form">
        <fieldset className="profile-group">
          <legend>Brand &amp; business name</legend>
          <p className="profile-group-description">Recognisable details used throughout your workspace and on your bills.</p>
          <div className="profile-brand-editor">
            <div className="profile-logo-preview">
              {formData.logo ? <img src={formData.logo} alt="Company logo preview" /> : <BuildingMark size={36} />}
            </div>
            <div className="profile-logo-actions">
              <strong>Company logo</strong>
              <p>JPG, PNG or SVG, up to 2 MB. A square image works best.</p>
              <div>
                <label className="btn btn-secondary profile-upload">
                  Upload logo
                  <input type="file" accept="image/*" aria-label="Upload company logo" onChange={handleLogoChange} />
                </label>
                {formData.logo && <button type="button" className="btn btn-ghost" onClick={() => setFormData(previous => ({ ...previous, logo: '' }))}>Remove logo</button>}
              </div>
            </div>
          </div>
          {field('business_name', 'Business name', { required: true, autoComplete: 'organization', placeholder: 'e.g. Sri Lakshmi Medicals' })}
        </fieldset>

        <fieldset className="profile-group">
          <legend>Contact details</legend>
          <p className="profile-group-description">Where customers and suppliers can reach your business.</p>
          <div className="profile-fields-grid">
            {field('phone', 'Phone number', { type: 'tel', maxLength: 10, autoComplete: 'tel', placeholder: '10-digit phone number' })}
            {field('email', 'Email address', { type: 'email', autoComplete: 'email', placeholder: 'billing@company.com' })}
            <div className="profile-field profile-field-full">
              <label htmlFor="profile-address">Billing address</label>
              <textarea id="profile-address" name="address" className="form-textarea" rows={3}
                value={formData.address} onChange={handleChange} autoComplete="street-address" placeholder="Full business street address" />
            </div>
          </div>
        </fieldset>

        <fieldset className="profile-group">
          <legend>Tax &amp; payment details</legend>
          <p className="profile-group-description">Keep the identity on invoices and payment requests accurate.</p>
          <div className="profile-fields-grid">
            {field('gstin', 'GSTIN', { maxLength: 15, placeholder: '15-digit GSTIN' })}
            {field('pan', 'PAN', { maxLength: 10, placeholder: '10-digit PAN' })}
            {field('state_code', 'GST state code', { maxLength: 2, inputMode: 'numeric', placeholder: 'e.g. 29 for Karnataka' })}
            {field('upi_vpa', 'UPI ID (VPA)', { placeholder: 'yourname@okhdfcbank', hint: 'Used for payment QR codes and invoices. Leave blank to use your phone number.' })}
          </div>
        </fieldset>

        <div className="profile-save-row">
          <p>Changes apply to your business across billing.</p>
          <button type="submit" className="btn btn-primary" disabled={loading}>
            {loading ? <span className="spinner" /> : <CheckIcon size={15} />}
            {loading ? 'Saving profile…' : 'Save business profile'}
          </button>
        </div>
      </form>
    </section>
  )

  return embedded ? content : <AppLayout title="Business Profile">{content}</AppLayout>
}
