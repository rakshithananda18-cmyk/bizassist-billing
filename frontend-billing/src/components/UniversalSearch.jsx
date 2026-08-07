import React from 'react'
import { createPortal } from 'react-dom'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { logger } from '../utils/logger'
import {
  SearchIcon, CloseIcon, PackageIcon, ContactsIcon,
  TruckIcon, BillsIcon, SettingsIcon, ChevronRightIcon, ExpandIcon,
} from './Icons'

/** Dismissing the floating trigger has to outlive a reload, or the close
 *  button is decoration. The sidebar row is the permanent way back. */
const HIDE_KEY = 'usearch_fab_hidden'
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

/** Record kinds carry their own icon so Records can be scanned by shape rather
 *  than by reading every hint. Pages and settings get one each, below. */
const KIND_META = {
  product:  { label: 'Product',  Icon: PackageIcon },
  customer: { label: 'Customer', Icon: ContactsIcon },
  vendor:   { label: 'Supplier', Icon: TruckIcon },
  invoice:  { label: 'Invoice',  Icon: BillsIcon },
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
  const { pathname } = useLocation()
  const [open, setOpen] = React.useState(false)
  const [hidden, setHidden] = React.useState(() => {
    try { return localStorage.getItem(HIDE_KEY) === '1' } catch { return false }
  })
  const [slot, setSlot] = React.useState(null)
  const [query, setQuery] = React.useState('')
  const [records, setRecords] = React.useState([])
  const [cursor, setCursor] = React.useState(0)
  const inputRef = React.useRef(null)

  const isCashier = ((user?.role || '').toLowerCase() === 'cashier')

  // ── Results ───────────────────────────────────────────────────────────────
  const results = React.useMemo(() => {
    const q = query.trim()
    if (!q) return []
    // Hints say what the group heading does not. A page's destination is its
    // own label, and repeating "Settings" on every settings row only restates
    // the heading above it — the useful fact there is which tab it lives on.
    const pages = matchPages(q, { isCashier }).slice(0, MAX_STATIC).map(p => ({
      group: 'Pages & actions', label: p.label, hint: '', route: p.route,
      Icon: ChevronRightIcon,
    }))
    const settings = matchSettings(q, { isCashier }).slice(0, MAX_STATIC).map(s => ({
      group: 'Settings', label: s.label, route: settingsRoute(s),
      hint: s.tab.charAt(0).toUpperCase() + s.tab.slice(1),
      Icon: SettingsIcon,
    }))
    const recs = records.slice(0, MAX_RECORDS).map(r => ({
      group: 'Records', label: r.title,
      hint: `${KIND_META[r.kind]?.label || r.kind}${r.subtitle ? ' · ' + r.subtitle : ''}`,
      route: recordRoute(r),
      Icon: KIND_META[r.kind]?.Icon || SearchIcon,
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
      // Ctrl+Space is the advertised one; Ctrl+K stays because it shipped and
      // people have it in their fingers. `e.code` is checked alongside `e.key`
      // because a modified space does not report `' '` consistently across
      // browsers, and `code` is layout-independent either way.
      const isSpace = e.key === ' ' || e.code === 'Space'
      const openCombo = (e.ctrlKey || e.metaKey) && (isSpace || e.key === 'k' || e.key === 'K')
      if (!open) {
        if (openCombo) {
          e.preventDefault()          // Chrome binds Ctrl+K to the address bar
          // Same shield as the open branch below, for the same reason: the POS
          // key map is user-rebindable (components/sales/PosSettingsModals.jsx
          // writes localStorage.pos_func_keys, which loadFuncKeys merges OVER
          // the defaults), so Ctrl+K is only free by default. Without this, an
          // owner who bound saveInvoice to Ctrl+K would open the palette AND
          // save the bill on one press.
          e.stopImmediatePropagation()
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

  // Re-resolved per route, not cached once: /sales renders no sidebar at all,
  // so the slot node is destroyed and recreated on the way back. A stale
  // reference would portal into a detached node and silently vanish.
  React.useEffect(() => {
    setSlot(document.getElementById('usearch-slot'))
  }, [pathname])

  const dismiss = React.useCallback(() => {
    setHidden(true)
    try { localStorage.setItem(HIDE_KEY, '1') } catch { /* ignore */ }
  }, [])

  const restore = React.useCallback(() => {
    setHidden(false)
    try { localStorage.removeItem(HIDE_KEY) } catch { /* ignore */ }
  }, [])

  // Headers carry their own group's size, so the list states how much of each
  // kind it found without the reader counting rows.
  const grouped = []
  let lastGroup = null
  results.forEach((r, i) => {
    if (r.group !== lastGroup) {
      grouped.push({ header: r.group, count: results.filter(x => x.group === r.group).length })
      lastGroup = r.group
    }
    grouped.push({ ...r, index: i })
  })

  return (
    <>
      {/* Floating trigger, or — once dismissed — a row in the sidebar. Never
          both, and never neither: on /sales there is no sidebar to fall back
          to, so the trigger stays regardless of the stored preference. */}
      {(!hidden || !slot) ? (
        <div className="usearch-dock">
          <button
            type="button"
            className="usearch-fab"
            onClick={() => setOpen(true)}
            // No `title`: the native tooltip is a black box that lands on top
            // of the pill saying exactly what the pill already expanded to
            // show. aria-label keeps the same text for screen readers, which
            // cannot see the label animate open.
            aria-label="Search anything (Ctrl+Space)"
          >
            <span className="usearch-search-icon" style={{ display: 'flex' }}><SearchIcon size={17} /></span>
            <span className="usearch-label">
              <span style={{ fontWeight: 600, fontSize: '0.78rem' }}>Search</span>
              <kbd>Ctrl Space</kbd>
            </span>
          </button>
          {slot && (
            <button
              type="button"
              className="usearch-close"
              onClick={dismiss}
              aria-label="Hide the search button"
              title="Hide — search stays in the sidebar"
            >
              <CloseIcon size={11} />
            </button>
          )}
        </div>
      ) : createPortal(
        // A container, not one button: the row does two different things, and
        // the expand glyph is the ONLY way back to the floating trigger once
        // it has been dismissed.
        <div className="usearch-slot-btn">
          <button
            type="button"
            className="usearch-slot-main"
            onClick={() => setOpen(true)}
            title="Search anything (Ctrl+Space)"
          >
            <SearchIcon size={14} />
            <span className="usearch-slot-text">Find anything</span>
          </button>
          <button
            type="button"
            className="usearch-slot-expand"
            onClick={restore}
            aria-label="Show the floating search button again"
            title="Show the floating search button again"
          >
            <ExpandIcon size={13} />
          </button>
        </div>,
        slot,
      )}

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
              borderRadius: 14, overflow: 'hidden',
              // Depth plus the premium halo, so the open palette reads as lit
              // rather than as a plain grey card on a dimmed page.
              boxShadow: '0 24px 70px rgba(0,0,0,0.5), var(--glow-premium)',
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
                <div key={`h-${row.header}-${i}`} className="usearch-group">
                  <span>{row.header}</span>
                  <span>{row.count}</span>
                </div>
              ) : (
                <button
                  key={`r-${row.index}`}
                  type="button"
                  className="usearch-row"
                  aria-selected={row.index === cursor}
                  onClick={() => go(row)}
                  onMouseEnter={() => setCursor(row.index)}
                >
                  <span className="usearch-icon"><row.Icon size={15} /></span>
                  <span style={{ flex: 1, minWidth: 0, fontSize: '0.83rem', color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {row.label}
                  </span>
                  {row.hint && (
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', flexShrink: 0 }}>{row.hint}</span>
                  )}
                </button>
              ))}
            </div>

            {/* The palette is keyboard-first; say so rather than leaving it to
                be discovered. Hints appear once there is something to move
                through; the restore whenever the trigger is put away. */}
            {(results.length > 0 || (hidden && slot)) && (
              <div className="usearch-foot">
                {results.length > 0 && (
                  <>
                    <span><kbd>↑</kbd><kbd>↓</kbd> move</span>
                    <span><kbd>↵</kbd> open</span>
                    <span><kbd>esc</kbd> close</span>
                  </>
                )}
                {/* The sidebar row's own glyph does this too, but it is
                    display:none in the 56px rail — so without this there is
                    no way back to the floating trigger while collapsed. */}
                {hidden && slot && (
                  <button
                    type="button"
                    className="usearch-restore"
                    onClick={() => { restore(); close() }}
                  >
                    <ExpandIcon size={12} /> Show floating button
                  </button>
                )}
              </div>
            )}
          </div>
        </div>,
        document.body,
      )}
    </>
  )
}
