import React, { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { resolveTemplate, FALLBACK_TEMPLATE } from '../invoice/registry'
import { api } from '../api/client'

// Since it's public, we don't have an auth token. The client might try to send one
// if logged in, but the backend doesn't require it.

export default function PublicInvoiceViewer() {
  const { uid } = useParams()
  const [payload, setPayload] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [template, setTemplate] = useState(FALLBACK_TEMPLATE)

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(null)
    
    // We use a raw fetch because api client might add auth headers that we don't want
    // to strictly rely on, or maybe the public route is open. 
    // `api.get` is fine since it's just a fetch wrapper.
    api.get(`/public/invoice/${encodeURIComponent(uid)}?format=json`)
      .then((data) => {
        if (!alive) return
        if (data?.invoice?.public_url && data.invoice.public_url.startsWith('/')) {
          data.invoice.public_url = `${window.location.origin}${data.invoice.public_url}`
        }
        setPayload(data)
        setTemplate(data?.meta?.template_default || FALLBACK_TEMPLATE)
      })
      .catch((err) => {
        if (!alive) return
        setError(err?.detail || err?.message || 'Invoice not found or link expired.')
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
      
    return () => { alive = false }
  }, [uid])

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', background: '#fdfdfc' }}>
        <p>Loading invoice...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', background: '#fdfdfc' }}>
        <div style={{ textAlign: 'center' }}>
          <h2>Oops!</h2>
          <p>{error}</p>
        </div>
      </div>
    )
  }

  const { entry } = resolveTemplate(template)
  const Template = entry.component

  return (
    <div style={{ background: '#f4f4f1', minHeight: '100vh', padding: '20px', overflowX: 'auto', WebkitOverflowScrolling: 'touch' }}>
      <div style={{ 
        width: '100%',
        maxWidth: 820, 
        minWidth: entry.key.includes('thermal') ? 'auto' : '800px',
        margin: '0 auto', 
        background: '#fff', 
        boxShadow: '0 4px 16px rgba(26,23,20,0.10)' 
      }}>
        {/* We reuse the exact same React templates as the authenticated viewer */}
        <Template payload={payload} />
      </div>
      
      <div className="no-print" style={{ textAlign: 'center', marginTop: 24 }}>
        <p style={{ color: '#666', fontSize: '13px' }}>
          Powered by <a href="/" style={{ color: 'var(--accent, #c15f3c)', textDecoration: 'none', fontWeight: 'bold' }}>BizAssist</a>
        </p>
      </div>
    </div>
  )
}
