import React from 'react'

/** Readable phone list row. Secondary facts/actions are disclosed on demand. */
export default function PhoneRecord({ title, amount, meta, status, onOpen, primary, children }) {
  return (
    <article className="phone-record">
      <div className="phone-record-heading">
        <div className="phone-record-title">
          {onOpen ? <button type="button" onClick={onOpen}>{title}</button> : <strong>{title}</strong>}
          {meta && <div className="phone-record-meta">{meta}</div>}
        </div>
        {amount != null && <strong className="phone-record-amount">{amount}</strong>}
      </div>
      {(status || primary || children) && <div className="phone-record-bottom">
        {status && <span className="phone-record-status">{status}</span>}
        {primary && <div>{primary}</div>}
        {children && <details className="phone-record-details"><summary>Details &amp; actions</summary><div>{children}</div></details>}
      </div>}
    </article>
  )
}
