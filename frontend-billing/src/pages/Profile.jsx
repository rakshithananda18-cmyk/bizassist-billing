import React, { useState, useEffect } from 'react'
import AppLayout from '../layouts/AppLayout'
import { useAuth } from '../contexts/AuthContext'
import { ContactsIcon, CheckIcon } from '../components/Icons'

export default function Profile() {
  const { authFetch, profile, fetchProfile } = useAuth()
  const [formData, setFormData] = useState({
    business_name: '',
    gstin: '',
    phone: '',
    email: '',
    address: '',
    state_code: '',
    pan: '',
    logo: ''
  })
  const [loading, setLoading] = useState(false)
  const [successMsg, setSuccessMsg] = useState('')
  const [errorMsg, setErrorMsg] = useState('')

  useEffect(() => {
    if (profile) {
      setFormData({
        business_name: profile.business_name || '',
        gstin: profile.gstin || '',
        phone: profile.phone || '',
        email: profile.email || '',
        address: profile.address || '',
        state_code: profile.state_code || '',
        pan: profile.pan || '',
        logo: profile.logo || ''
      })
    }
  }, [profile])

  const handleChange = (e) => {
    const { name, value } = e.target
    setFormData(prev => ({ ...prev, [name]: value }))
  }

  const handleLogoChange = (e) => {
    const file = e.target.files[0]
    if (!file) return

    // Limit to 2MB logo size
    if (file.size > 2 * 1024 * 1024) {
      setErrorMsg('Logo file must be under 2MB')
      return
    }

    const reader = new FileReader()
    reader.onloadend = () => {
      setFormData(prev => ({ ...prev, logo: reader.result }))
      setErrorMsg('')
    }
    reader.readAsDataURL(file)
  }

  const handleRemoveLogo = () => {
    setFormData(prev => ({ ...prev, logo: '' }))
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setSuccessMsg('')
    setErrorMsg('')

    if (!formData.business_name.trim()) {
      setErrorMsg('Business Name is required')
      setLoading(false)
      return
    }

    try {
      const res = await authFetch('/profile', {
        method: 'PUT',
        body: JSON.stringify(formData)
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || 'Failed to update profile')
      }

      await fetchProfile()
      setSuccessMsg('Business settings updated successfully!')
      setTimeout(() => setSuccessMsg(''), 4000)
    } catch (err) {
      setErrorMsg(err.message || 'An error occurred during update')
    } finally {
      setLoading(false)
    }
  }

  return (
    <AppLayout title="My Profile">
      <div className="slide-up">
        <div className="page-header">
          <div className="page-header-left">
            <h1 className="page-title">My Profile</h1>
            <p className="page-subtitle">Manage your company branding, billing identity, and taxation details.</p>
          </div>
        </div>

        {successMsg && (
          <div style={{
            background: 'var(--success-dim)',
            color: 'var(--success)',
            padding: '12px 16px',
            borderRadius: 'var(--radius-md)',
            border: '1px solid var(--success)',
            marginBottom: '20px',
            fontSize: '0.9rem',
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}>
            <CheckIcon size={16} />
            {successMsg}
          </div>
        )}

        {errorMsg && (
          <div style={{
            background: 'var(--danger-dim)',
            color: 'var(--danger)',
            padding: '12px 16px',
            borderRadius: 'var(--radius-md)',
            border: '1px solid var(--danger)',
            marginBottom: '20px',
            fontSize: '0.9rem'
          }}>
            {errorMsg}
          </div>
        )}

        <form onSubmit={handleSubmit} className="card" style={{ padding: '28px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          
          {/* Logo Section */}
          <div style={{ display: 'flex', gap: '20px', alignItems: 'center', borderBottom: '1px solid var(--border)', paddingBottom: '20px' }}>
            <div style={{
              width: '80px',
              height: '80px',
              borderRadius: 'var(--radius-md)',
              border: '1px dashed var(--border)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: 'var(--bg-3)',
              overflow: 'hidden',
              flexShrink: 0
            }}>
              {formData.logo ? (
                <img src={formData.logo} alt="Company logo preview" style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
              ) : (
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textAlign: 'center', padding: '4px' }}>No Logo</span>
              )}
            </div>
            
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={{ fontWeight: '600', fontSize: '0.95rem' }}>Company Logo</div>
              <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>JPG, PNG or SVG under 2MB. Square dimensions recommended.</div>
              <div style={{ display: 'flex', gap: '10px' }}>
                <label className="btn btn-secondary" style={{ cursor: 'pointer', fontSize: '0.8rem', padding: '6px 12px' }}>
                  Upload Logo
                  <input type="file" accept="image/*" onChange={handleLogoChange} style={{ display: 'none' }} />
                </label>
                {formData.logo && (
                  <button type="button" className="btn btn-danger" onClick={handleRemoveLogo} style={{ fontSize: '0.8rem', padding: '6px 12px' }}>
                    Remove
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Form Fields */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            <div className="form-group" style={{ gridColumn: 'span 2' }}>
              <label className="form-label" style={{ fontWeight: '600' }}>Business Name *</label>
              <input
                type="text"
                name="business_name"
                className="form-input"
                placeholder="e.g. Acme Retailers"
                value={formData.business_name}
                onChange={handleChange}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label" style={{ fontWeight: '600' }}>GSTIN</label>
              <input
                type="text"
                name="gstin"
                className="form-input"
                placeholder="15-digit GSTIN"
                maxLength={15}
                value={formData.gstin}
                onChange={handleChange}
              />
            </div>

            <div className="form-group">
              <label className="form-label" style={{ fontWeight: '600' }}>PAN</label>
              <input
                type="text"
                name="pan"
                className="form-input"
                placeholder="10-digit PAN"
                maxLength={10}
                value={formData.pan}
                onChange={handleChange}
              />
            </div>

            <div className="form-group">
              <label className="form-label" style={{ fontWeight: '600' }}>Phone Number</label>
              <input
                type="tel"
                name="phone"
                className="form-input"
                placeholder="10-digit phone"
                maxLength={10}
                value={formData.phone}
                onChange={handleChange}
              />
            </div>

            <div className="form-group">
              <label className="form-label" style={{ fontWeight: '600' }}>Email Address</label>
              <input
                type="email"
                name="email"
                className="form-input"
                placeholder="billing@company.com"
                value={formData.email}
                onChange={handleChange}
              />
            </div>

            <div className="form-group" style={{ gridColumn: 'span 2' }}>
              <label className="form-label" style={{ fontWeight: '600' }}>Billing Address</label>
              <textarea
                name="address"
                className="form-textarea"
                placeholder="Full business street address"
                value={formData.address}
                onChange={handleChange}
              />
            </div>

            <div className="form-group" style={{ gridColumn: 'span 2' }}>
              <label className="form-label" style={{ fontWeight: '600' }}>State Code (GST State Digit Prefix)</label>
              <input
                type="text"
                name="state_code"
                className="form-input"
                placeholder="e.g. 29 for Karnataka, 27 for Maharashtra"
                maxLength={2}
                value={formData.state_code}
                onChange={handleChange}
              />
            </div>
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '10px', borderTop: '1px solid var(--border)', paddingTop: '20px' }}>
            <button
              type="submit"
              className="btn btn-accent"
              disabled={loading}
              style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 24px' }}
            >
              {loading && <span className="spinner" style={{ width: '14px', height: '14px' }} />}
              Save Profile Settings
            </button>
          </div>
        </form>
      </div>
    </AppLayout>
  )
}
