import React from 'react'

/** Readable phone list row with 3 separated sections: details, activity, actions all aligned in same line and centered. */
export default function PhoneRecord({
  title,
  amount,
  amountTone,
  meta,
  status,
  onOpen,
  primary,
  children,
}) {
  const toneClass = amountTone ? ` amount-${amountTone}` : ''
  return (
    <article className="phone-record">
      <div className="phone-record-row">
        {/* 1. Details: title and meta */}
        <div className="phone-record-col phone-record-col-details">
          <div className="phone-record-title">
            {onOpen ? (
              <button type="button" onClick={onOpen}>{title}</button>
            ) : (
              <strong>{title}</strong>
            )}
          </div>
          {meta && <div className="phone-record-meta">{meta}</div>}
        </div>

        {/* 2. Activity: status badge and amount, centered in middle */}
        <div className="phone-record-col phone-record-col-activity">
          {status && <div className="phone-record-status">{status}</div>}
          {amount != null && (
            <strong className={`phone-record-amount${toneClass}`}>{amount}</strong>
          )}
        </div>

        {/* 3. Actions: particular action button on right */}
        <div className="phone-record-col phone-record-col-actions">
          {primary}
        </div>
      </div>

      {/* Expandable details & secondary actions */}
      {children && (
        <details className="phone-record-details">
          <summary>Details &amp; actions</summary>
          <div className="phone-record-details-body">{children}</div>
        </details>
      )}
    </article>
  )
}
