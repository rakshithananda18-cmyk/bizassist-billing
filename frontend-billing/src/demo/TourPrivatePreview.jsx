import React from 'react'
import './tourPrivatePreview.css'

// These are decorative placeholders, never a blurred copy of the underlying
// value. Selecting text or using assistive technology cannot reveal that value.
export function TourPrivateValue({ label = 'Value available after sign-in' }) {
  return <span className="tour-private-value" role="img" aria-label={label}>
    <span aria-hidden="true">••••••</span>
  </span>
}

export default function TourPrivatePreview({ compact = false, label = 'Full workflow available after sign-in.' }) {
  return <div className={`tour-private-preview${compact ? ' is-compact' : ''}`} data-tour-private="protected-workflow">
    <div className="tour-private-preview-shapes" aria-hidden="true"><span /><span /><span /><span /><span /></div>
    <div className="tour-private-preview-copy"><span>PREVIEW PROTECTED</span><p>{label}</p></div>
  </div>
}
