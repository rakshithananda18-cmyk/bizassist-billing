import React from 'react'
import { createPortal } from 'react-dom'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { logger } from '../utils/logger'
import {
  SearchIcon, CloseIcon, PackageIcon, ContactsIcon,
  TruckIcon, BillsIcon, SettingsIcon, ChevronRightIcon, ExpandIcon, SparkleIcon,
} from './Icons'

/** Dismissing the floating trigger has to outlive a reload, or the close
 *  button is decoration. The sidebar row is the permanent way back. */
const HIDE_KEY = 'usearch_fab_hidden'
import { matchPages, matchSettings, settingsRoute } from '../config/searchIndex'
import { getAiDashboardUrl, openAiDashboard } from '../config/aiDashboard'

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
// Below this the query is more likely a half-typed product name than a
// question, and offering to spend router tokens on it is noise.
const MIN_ASK_CHARS = 6
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
  const { authFetch, user, settings } = useAuth()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const [open, setOpen] = React.useState(false)
  const [hidden, setHidden] = React.useState(() => {
    try { return localStorage.getItem(HIDE_KEY) === '1' } catch { return false }
  })
  const [slot, setSlot] = React.useState(null)

  // ── Ask AI (Phase 1: read-only Q&A) ───────────────────────────────────────
  // `ask` is null until the user explicitly chooses the Ask AI row. NOTHING
  // here runs on a keystroke: /search is debounced and cheap, but the AI router
  // costs ~841 tokens per invocation before the model even answers
  // (docs/AI_TOKEN_ECONOMICS_2026-08-07.md), so firing it per character typed
  // would be ruinous. It is an explicit act, always.
  const [ask, setAsk] = React.useState(null)   // {q, text, status, error, done}
  // Latched when the backend says 503 — "AI features aren't configured on this
  // device" (no GROQ_API_KEY). That is not an error the counter can act on, so
  // the row disappears for the session instead of failing every time it is used.
  const [aiUnavailable, setAiUnavailable] = React.useState(false)
  const askAbortRef = React.useRef(null)
  const [query, setQuery] = React.useState('')
  const [records, setRecords] = React.useState([])
  const [cursor, setCursor] = React.useState(0)
  const inputRef = React.useRef(null)

  const isCashier = ((user?.role || '').toLowerCase() === 'cashier')

  // AI is Pro-only and refuses cashiers — both enforced server-side on
  // /ask/stream (require_plan("pro", force_enforcement=True) + restrict_cashier).
  // Mirrored here so a free plan is never SHOWN a control that would 402: the
  // server decides, the client just avoids offering a dead end.
  const isPro = ((settings?.subscription?.plan || '').toLowerCase() === 'pro')
  const aiEligible = isPro && !isCashier && !aiUnavailable

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
    // NOT named `settings` — that shadows the auth context's `settings`, which
    // this memo now depends on for the plan check.
    const settingsRows = matchSettings(q, { isCashier }).slice(0, MAX_STATIC).map(s => ({
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
    // LAST, always. A record the owner was reaching for must never be pushed
    // down the list by an offer to think about it instead. Below MIN_ASK_CHARS
    // the query is more likely a half-typed name than a question.
    const aiRow = (aiEligible && q.length >= MIN_ASK_CHARS) ? [{
      group: 'Ask AI', label: q, hint: 'Ask the assistant', ask: true, Icon: SparkleIcon,
    }] : []
    return [...recs, ...pages, ...settingsRows, ...aiRow]
  }, [query, records, isCashier, aiEligible])

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

  // Editing the query retires the previous answer: it belonged to a different
  // question, and leaving it on screen under new text reads as a reply to the
  // new one. The in-flight request is aborted rather than left to land.
  React.useEffect(() => {
    askAbortRef.current?.abort()
    setAsk(null)
  }, [query])

  const close = React.useCallback(() => {
    setOpen(false); setQuery(''); setRecords([])
    askAbortRef.current?.abort()
    setAsk(null)
  }, [])

  /** Ask the assistant. Explicit-only — never called from the typing path.
   *
   *  Streams /ask/stream, the same endpoint frontend-ai uses. Reusing it rather
   *  than adding a second AI route keeps ONE router, one cache, one set of
   *  failure rules; a parallel path would drift the way two hosting-mode
   *  implementations already did.
   *
   *  Phase 1 is READ-ONLY: whatever comes back is rendered as text. The router
   *  can return ACTION results (drafting an email, for one), and a search box
   *  must not fire one off the back of a keystroke and an Enter. Actions get an
   *  explicit confirm step in Phase 2 or they do not ship. */
  const runAsk = React.useCallback(async (q) => {
    askAbortRef.current?.abort()
    const ctl = new AbortController()
    askAbortRef.current = ctl
    setAsk({ q, text: '', status: 'Thinking…', error: null, done: false })

    try {
      const res = await authFetch('/ask/stream', {
        method: 'POST',
        body: JSON.stringify({ message: q }),
        signal: ctl.signal,
      })

      if (!res.ok || !res.body) {
        // Two envelope shapes reach here and only one used to be read: the /ask
        // pipeline raises AskError -> {error, code}, while a FastAPI
        // HTTPException returns {detail}. 402 (plan), 403 (role) and 503 (no
        // GROQ_API_KEY) are all the second shape.
        const body = await res.json().catch(() => ({}))
        if (res.status === 503) setAiUnavailable(true)
        setAsk(a => ({
          ...a, done: true, status: null,
          error: body.error || body.detail || `Request failed (HTTP ${res.status})`,
        }))
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      // A stream can end with no terminal event — a proxy idle-timeout, a
      // container restart — and the reader just returns done:true. Without this
      // the pane would sit on "Thinking…" forever with nothing thrown and
      // nothing logged: the eternal-spinner shape.
      let sawTerminal = false

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop()
        for (const part of parts) {
          const t = part.trim()
          if (!t.startsWith('data: ')) continue
          let evt
          try { evt = JSON.parse(t.slice(6)) } catch { continue }
          if (evt.type === 'status') setAsk(a => a && ({ ...a, status: evt.content }))
          else if (evt.type === 'token') setAsk(a => a && ({ ...a, text: a.text + evt.content, status: null }))
          else if (evt.type === 'replace') setAsk(a => a && ({ ...a, text: evt.content, status: null }))
          else if (evt.type === 'error') {
            sawTerminal = true
            setAsk(a => a && ({ ...a, done: true, status: null, error: evt.content || 'The assistant could not answer.' }))
          } else if (evt.type === 'done') {
            sawTerminal = true
            // `source` decides whether this is an answer or a proposal. The
            // router returns source:'action' for the five write actions
            // (send_payment_reminders, mark_invoice_paid, …) with a confirm
            // chip in `suggestions` — and NEVER executes them itself.
            setAsk(a => a && ({ ...a, done: true, status: null, source: evt.source }))
          }
        }
      }
      if (!sawTerminal) {
        setAsk(a => a && ({
          ...a, done: true, status: null,
          error: a.text ? null : 'The connection ended before an answer arrived.',
        }))
      }
    } catch (err) {
      if (ctl.signal.aborted) return          // the user moved on; not a failure
      logger.error('[SEARCH] ask failed:', err)
      setAsk(a => a && ({ ...a, done: true, status: null, error: 'Could not reach the assistant.' }))
    }
  }, [authFetch])

  const go = React.useCallback((item) => {
    if (item?.ask) { runAsk(item.label); return }   // stays open to show the answer
    if (!item?.route) return
    close()
    navigate(item.route)
  }, [close, navigate, runAsk])

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

      if (e.key === 'Escape') {
        e.preventDefault()
        // One Escape dismisses the ANSWER, the next closes the palette. Closing
        // both at once would throw away a result the owner is still reading
        // because they reached for the key that normally means "back".
        if (ask) { askAbortRef.current?.abort(); setAsk(null); return }
        close(); return
      }
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
  }, [open, results, cursor, close, go, ask])

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

            {/* The answer sits ABOVE the list, not instead of it: the records
                that matched are still the fastest way to what the owner wanted,
                and replacing them with prose would make asking a question a
                one-way door. */}
            {ask && (
              <div className="usearch-ask">
                <div className="usearch-ask-head">
                  <SparkleIcon size={13} />
                  <span>{ask.q}</span>
                  <button type="button" onClick={() => { askAbortRef.current?.abort(); setAsk(null) }}
                          aria-label="Dismiss answer">
                    <CloseIcon size={13} />
                  </button>
                </div>
                {ask.error ? (
                  <div className="usearch-ask-error">{ask.error}</div>
                ) : (
                  <div className="usearch-ask-body">
                    {ask.text}
                    {/* A status line, not a spinner: the router is legitimately
                        silent for seconds at a time and "Thinking…" that never
                        says what it is doing is how the eternal spinner hid. */}
                    {ask.status && <div className="usearch-ask-status">{ask.status}</div>}
                    {!ask.text && !ask.status && !ask.done && (
                      <div className="usearch-ask-status">Working…</div>
                    )}
                    {/* HAND-OFF, not a second confirm flow.
                        source:'action' means the router proposed one of the five
                        write actions — two of which email customers and one of
                        which marks an invoice paid. It has already refused to run
                        it and returned a confirm chip.
                        The palette does not render that chip on purpose: a
                        money-and-email confirmation implemented in two surfaces
                        is two places to drift, and Ctrl+Space → type → Enter is
                        the wrong ceremony for "email 20 customers". The AI page
                        owns confirmation; this points at it. */}
                    {ask.done && ask.source === 'action' && (
                      <div className="usearch-ask-handoff">
                        <span>Confirming this happens in the AI Advisor, where you
                              can review exactly what will be sent or changed.</span>
                        {getAiDashboardUrl()
                          ? <button type="button" onClick={() => openAiDashboard()}>
                              Open AI Advisor
                            </button>
                          : <span className="usearch-ask-status">
                              The AI Advisor is not available from this device.
                            </span>}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

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
