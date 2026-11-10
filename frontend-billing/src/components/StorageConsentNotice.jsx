import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  OPEN_STORAGE_PREFERENCES, STORAGE_CONSENT_CHANGED, STORAGE_CONSENT_KEY,
  readStorageConsent, saveStorageConsent,
} from '../utils/storageConsent'
import './storageConsent.css'

export default function StorageConsentNotice() {
  const [visible, setVisible] = useState(() => !readStorageConsent())

  useEffect(() => {
    const open = () => setVisible(true)
    const changed = () => setVisible(!readStorageConsent())
    const stored = event => { if (event.key === STORAGE_CONSENT_KEY || event.key === null) changed() }
    window.addEventListener(OPEN_STORAGE_PREFERENCES, open)
    window.addEventListener(STORAGE_CONSENT_CHANGED, changed)
    window.addEventListener('storage', stored)
    return () => {
      window.removeEventListener(OPEN_STORAGE_PREFERENCES, open)
      window.removeEventListener(STORAGE_CONSENT_CHANGED, changed)
      window.removeEventListener('storage', stored)
    }
  }, [])

  if (!visible) return null
  const choose = diagnostics => { saveStorageConsent(diagnostics); setVisible(false) }

  return (
    <section className="storage-consent-notice" role="region" aria-labelledby="storage-consent-title">
      <div className="storage-consent-copy">
        <h2 id="storage-consent-title">Cookies &amp; browser storage</h2>
        <p>Stater uses essential browser storage for sign-in, preferences and offline billing. Optional diagnostics help us fix errors. We don’t use advertising or tracking cookies. <Link to="/privacy">Privacy &amp; storage details</Link></p>
      </div>
      <div className="storage-consent-actions">
        <button type="button" className="btn btn-secondary" onClick={() => choose(false)}>Essential only</button>
        <button type="button" className="btn btn-primary" onClick={() => choose(true)}>Accept all</button>
      </div>
    </section>
  )
}
