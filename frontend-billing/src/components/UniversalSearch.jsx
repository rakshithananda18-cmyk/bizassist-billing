import React from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { logger } from '../utils/logger'
import { SearchIcon, CloseIcon } from './Icons'
import { matchPages, matchSettings, settingsRoute } from '../config/searchIndex'

/**
 * UniversalSearch — one place to find anything, from anywhere.
 *
 * Three kinds of result in one list:
 *   · records  — from GET /search (products, customers, vendors, invoices)
 *   · pages    — navigation targets, matched locally
 *   · settings — individual fields, deep-linked to the row
 *
 * GROUPED, NOT RANKED. There is no scoring function across the three kinds
 * because there is no honest way to compare "a customer named Ram" with "the
 * Reports page". Fixed sections with hard caps mean the static entries cannot
 * drown the records and the records cannot drown the static ones. It also falls
 * out nicely: pages and settings match locally so they paint on the keystroke,
 * while records arrive ~250ms later and the list simply grows — no skeleton.
 *
 * MOUNTED BESIDE PageHelp, not in a top bar, because there is no top bar: the
 * sidebar, the mobile bottom bar and the mobile header are all gated on
 * `!isSalesPage`, so /sales — the page the counter spends its day on — has no
 * chrome at all. One fixed pill covers desktop, mobile and POS with one
 * implementation.
 */

const DEBOUNCE_MS = 250
const MAX_RECORDS = 8
const MAX_STATIC = 4

const KIND_LABEL = {
  product: 'Product',
  customer: 'Customer',
  vendor: 'Supplier',
  invoice: 'Invoice',
}

/** Where a record result goes.
 *
 *  Only invoices have a record route. Products and customers have none, so they
 *  seed the destination list's OWN search box — the pattern Purchases.jsx
 *  already uses for `?vendor=`. That is a deliberate trade: no shareable URL for
 *  a single product, but it sidesteps the duplicate-name problem rather than
 *  pretending to solve it. Two customers called "Ram Traders" appear as two rows
 *  here; the owner picks, and the list shows what it shows. */
function recordRoute(item) {
  switch (item.kind) {
    case 'invoice':  return `/invoice/${encodeURIComponent(item.id)}/view`
    case 'vendor':   return `/stock/purchase?vendor=${encodeURIComponent(item.title)}`
    case 'product':  return `/stock/inventory?q=${encodeURIComponent(item.title)}`
    case 'customer': return `/parties/contacts?q=${encodeURIComponent(item.title)}`
    default:         return null
  }
}

export default function UniversalSearch() {
  const { authFetch, user } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = React.useState(false)
  const [query, setQuery] = React.useState('')
  const [records, setRecords] = React.useState([])
  const [cursor, setCursor] = React.useState(0)
  const inputRef = React.useRef(null)

  const isCashier = ((user?.role || '').toLowerCase() === 'cashier')

  // ── Results ───────────────────────────────────────────────────────────────
  const results = React.useMemo(() => {
    const q = query.trim()
    if (!q) return []
    const pages = matchPages(q, { isCashier }).slice(0, MAX_STATIC).map(p => ({
      group: 'Pages & actions', label: p.label, hint: '', route: p.route,
    }))
    const settings = matchSettings(q, { isCashier }).slice(0, MAX_STATIC).map(s => ({
      group: 'Settings', label: s.label, hint: 'Settings', route: settingsRoute(s),
    }))
    const recs = records.slice(0, MAX_RECORDS).map(r => ({
      group: 'Records', label: r.title, hint: `${KIND_LABEL[r.kind] || r.kind}${r.subtitle ? ' · ' + r.subtitle : ''}`,
      route: recordRoute(r),
    })).filter(r => r.route)
    return [...recs, ...pages, ...settings]
  }, [query, records, isCashier])

  // ── Record lookup, debounced ──────────────────────────────────────────────
  React.useEffect(() => {
    const q = query.trim()
    if (!open || !q) { setRecords([]); return }
    let cancelled = false
    const t = setTimeout(async () => {
      try {
        const res = await authFetch(`/search?q=${encodeURIComponent(q)}`)
        if (!cancelled && res.ok) setRecords((await res.json()).items || [])
      } catch (err) {
        // The static half still works, so a failed lookup degrades rather than
        // empties. The endpoint answers 200-with-empty for bad input precisely
        // so typing never produces an error toast.
        logger.error('[SEARCH] record lookup failed:', err)
      }
    }, DEBOUNCE_MS)
    return () => { cancelled = true; clearTimeout(t) }
  }, [query, open, authFetch])

  React.useEffect(() => { setCursor(0) }, [query])

  const close = React.useCallback(() => {
    setOpen(false); setQuery(''); setRecords([])
  }, [])

  const go = React.useCallback((item) => {
    if (!item?.route) return
    close()
    navigate(item.route)
  }, [close, navigate])

  // ── Keyboard ──────────────────────────────────────────────────────────────
  // CAPTURE phase, on window. The POS binds Escape, Ctrl+S, Ctrl+P and `+` at
  // the window (pages/Sales.jsx) and does not always check whether focus is in
  // an input — so while this is open, every key is stopped before it can reach
  // those handlers. `stopPropagation` does NOT cancel the default action, so
  // typing still works and React's onChange still fires; a broad preventDefault
  // here would block typing entirely.
  React.useEffect(() => {
    const onKeyDown = (e) => {
      const openCombo = (e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')
      if (!open) {
        if (openCombo) {
          e.preventDefault()          // Chrome binds Ctrl+K to the address bar
          setOpen(true)
        }
        return
      }

      // stopIMMEDIATEPropagation, not stopPropagation. Sales.jsx binds its
      // handler on `window` too, and plain stopPropagation only prevents an
      // event reaching OTHER targets — listeners on the SAME target still run.
      // With the weaker call, one Escape in the palette both closed it and
      // triggered proceed-to-payment at the counter.
      //
      // Typing is unaffected: this cancels neither the default action (the
      // character is still inserted) nor React's onChange, which is driven by
      // the separate native `input` event, not by keydown.
      e.stopImmediatePropagation()

      if (e.key === 'Escape') { e.preventDefault(); close(); return }
      if (openCombo) { e.preventDefault(); close(); return }
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setCursor(c => Math.min(c + 1, Math.max(results.length - 1, 0)))
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        setCursor(c => Math.max(c - 1, 0))
      } else if (e.key === 'Enter') {
        e.preventDefault()
        go(results[cursor])
      }
    }
    window.addEventListener('keydown', onKeyDown, true)   // capture
    return () => window.removeEventListener('keydown', onKeyDown, true)
  }, [open, results, cursor, close, go])

  React.useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 0)
  }, [open])

  const grouped = []
  let lastGroup = null
  results.forEach((r, i) => {
    if (r.group !== lastGroup) { grouped.push({ header: r.group }); lastGroup = r.group }
    grouped.push({ ...r, index: i })
  })

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Search"
        title="Search anything (Ctrl+K)"
        style={{
          position: 'fixed', top: 14, right: 16, zIndex: 900,
          display: 'inline-flex', alignItems: 'center', gap: 7,
          padding: '7px 11px', borderRadius: 999,
          background: 'var(--bg-2, #1a1a1a)', border: '1px solid var(--border)',
          color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '0.75rem',
          boxShadow: '0 2px 10px rgba(0,0,0,0.18)',
        }}
      >
        <SearchIcon size={14} />
        <span className="hide-on-mobile" style={{ fontWeight: 600 }}>Search</span>
        <kbd className="hide-on-mobile" style={{
          fontSize: '0.62rem', padding: '1px 5px', borderRadius: 4,
          border: '1px solid var(--border)', color: 'var(--text-muted)',
        }}>Ctrl K</kbd>
      </button>

      {open && createPortal(
        <div
          onMouseDown={close}
          style={{
            position: 'fixed', inset: 0, zIndex: 1200,
            background: 'rgba(0,0,0,0.55)', backdropFilter: 'blur(4px)',
            display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
            paddingTop: '12vh',
          }}
        >
          <div
            onMouseDown={(e) => e.stopPropagation()}
            role="dialog"
            aria-label="Search"
            style={{
              width: 'min(560px, calc(100% - 32px))', maxHeight: '70vh',
              display: 'flex', flexDirection: 'column',
              background: 'var(--bg-2, #1a1a1a)', border: '1px solid var(--border)',
              borderRadius: 14, boxShadow: '0 24px 70px rgba(0,0,0,0.5)', overflow: 'hidden',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 14px', borderBottom: '1px solid var(--border)' }}>
              <SearchIcon size={16} />
              <input
                ref={inputRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search invoices, products, contacts, pages, settings…"
                style={{
                  flex: 1, background: 'transparent', border: 'none', outline: 'none',
                  color: 'var(--text-primary)', fontSize: '0.92rem',
                }}
              />
              <button type="button" onClick={close} aria-label="Close search"
                style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', display: 'flex' }}>
                <CloseIcon size={15} />
              </button>
            </div>

            <div style={{ overflowY: 'auto', padding: 6 }}>
              {!query.trim() ? (
                <div style={{ padding: '18px 12px', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                  Type to search across your records, pages and settings.
                </div>
              ) : results.length === 0 ? (
                <div style={{ padding: '18px 12px', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                  Nothing matches “{query.trim()}”.
                </div>
              ) : grouped.map((row, i) => row.header ? (
                <div key={`h-${row.header}-${i}`} style={{
                  padding: '8px 10px 4px', fontSize: '0.66rem', fontWeight: 700,
                  letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--text-muted)',
                }}>{row.header}</div>
              ) : (
                <button
                  key={`r-${row.index}`}
                  type="button"
                  onClick={() => go(row)}
                  onMouseEnter={() => setCursor(row.index)}
                  style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    gap: 10, width: '100%', textAlign: 'left', padding: '8px 10px',
                    borderRadius: 8, cursor: 'pointer', border: 'none',
                    background: row.index === cursor ? 'var(--accent-dim, rgba(255,255,255,0.07))' : 'transparent',
                    color: 'inherit',
                  }}
                >
                  <span style={{ fontSize: '0.83rem', color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {row.label}
                  </span>
                  {row.hint && (
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', flexShrink: 0 }}>{row.hint}</span>
                  )}
                </button>
              ))}
            </div>
          </div>
        </div>,
        document.body,
      )}
    </>
  )
}
