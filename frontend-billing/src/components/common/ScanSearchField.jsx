// ============================================================================
// common/ScanSearchField.jsx — ONE field for both scanning and searching.
// ----------------------------------------------------------------------------
// Every stock/ordering screen used to carry two adjacent inputs: a loud
// accent-bordered "Scan barcode…" box and a plain "Search…" box. That is two
// controls for what is, to the user, one action — "find me this item" — and the
// heavy border made the scan box shout on a screen where nothing else does.
//
// This is a single input with a quiet barcode glyph:
//   · typing filters the list live (onSearch)
//   · pressing Enter, or a scanner's trailing newline, submits the exact value
//     as a CODE (onScan) — and if that resolves, the field self-clears so the
//     next scan can land immediately
//   · if the code doesn't resolve, the text simply stays as the search filter,
//     which is exactly what a human typing a partial name wants
//
// It only takes visual emphasis (accent ring) while FOCUSED, so an armed
// scanner is still obvious without permanently colouring the toolbar.
//
//   <ScanSearchField
//     value={q} onChange={setQ}
//     onScan={code => tryAddByCode(code)}   // return true if it resolved
//     placeholder="Scan or search items…"
//   />
// ============================================================================
import React, { forwardRef, useState } from 'react'
import { BarcodeIcon } from '../Icons'

const ScanSearchField = forwardRef(function ScanSearchField({
  value,
  onChange,
  onScan,
  placeholder = 'Scan barcode or search…',
  disabled = false,
  error = null,
  busy = false,
  autoFocus = false,
  width,
  style = {},
  className = '',
  title = 'Scan a barcode, or type to search. Press Enter to add by code.',
}, ref) {
  const [focused, setFocused] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    const code = String(value || '').trim()
    if (!code || !onScan) return
    const resolved = await onScan(code)
    // Only clear when the code actually matched something — otherwise the user
    // was mid-search and wiping their text would be infuriating.
    if (resolved) onChange('')
  }

  return (
    <form
      onSubmit={submit}
      className={`scan-search${focused ? ' is-focused' : ''}${error ? ' is-error' : ''}${disabled ? ' is-disabled' : ''} ${className}`.trim()}
      style={{ ...(width ? { width, flex: '0 0 auto' } : null), ...style }}
      title={title}
      role="search"
    >
      <span className="scan-search-icon" aria-hidden="true">
        {busy ? <span className="scan-search-spin" /> : <BarcodeIcon size={15} />}
      </span>
      <input
        ref={ref}
        type="text"
        value={value}
        onChange={e => onChange(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        placeholder={placeholder}
        disabled={disabled}
        autoFocus={autoFocus}
        autoComplete="off"
        spellCheck={false}
        aria-label={placeholder}
      />
      {value && (
        <button
          type="button"
          className="scan-search-clear"
          onClick={() => onChange('')}
          aria-label="Clear"
          tabIndex={-1}
        >×</button>
      )}
    </form>
  )
})

export default ScanSearchField
