import React, { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import {
  SearchIcon, CloseIcon, DashboardIcon, MapPinIcon, TruckIcon,
  ClipboardIcon, OrderIcon, ContactsIcon, RouteIcon, UserIcon,
  ClockIcon, AwardIcon, ListIcon, SettingsIcon
} from './Icons'

const STATIC_PAGES = [
  { label: 'Dashboard', path: '/', category: 'Pages', icon: <DashboardIcon size={16} />, keywords: 'home overview stats metrics' },
  { label: 'Live Map', path: '/live', category: 'Pages', icon: <MapPinIcon size={16} />, keywords: 'gps tracking real time location staff' },
  { label: 'Day Plan', path: '/plan', category: 'Pages', icon: <TruckIcon size={16} />, keywords: 'routes runs stops deliveries beats' },
  { label: 'Tasks', path: '/tasks', category: 'Pages', icon: <ClipboardIcon size={16} />, keywords: 'assignments todos visits orders audits' },
  { label: 'Shop Requests', path: '/requests', category: 'Pages', icon: <OrderIcon size={16} />, keywords: 'orders notes requirements items' },
  { label: 'Shops Directory', path: '/shops', category: 'Setup', icon: <ContactsIcon size={16} />, keywords: 'customers stores retailers merchants' },
  { label: 'Routes & Beats', path: '/routes', category: 'Setup', icon: <RouteIcon size={16} />, keywords: 'weekly templates beats trips' },
  { label: 'Staff Management', path: '/staff', category: 'Setup', icon: <UserIcon size={16} />, keywords: 'delivery field agents workers team roster' },
  { label: 'Attendance', path: '/attendance', category: 'Records', icon: <ClockIcon size={16} />, keywords: 'check-in check-out duty hours shifts late' },
  { label: 'Scorecard', path: '/scorecard', category: 'Records', icon: <AwardIcon size={16} />, keywords: 'leaderboard points performance rankings' },
  { label: 'Activity Audit Log', path: '/activity', category: 'Records', icon: <ListIcon size={16} />, keywords: 'history audit actions events who when' },
  { label: 'Settings', path: '/settings', category: 'Records', icon: <SettingsIcon size={16} />, keywords: 'appearance theme gps radius geofence points' },
]

export default function UniversalSearchModal({ open, onClose }) {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [data, setData] = useState({ shops: [], staff: [], routes: [] })
  const inputRef = useRef(null)
  const dialogRef = useRef(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    let current = true
    setQuery('')
    setSelectedIndex(0)
    setData({ shops: [], staff: [], routes: [] })
    if (open) {
      Promise.allSettled([
        api.get('/api/shops'),
        api.get('/api/staff'),
        api.get('/api/routes')
      ]).then(([shopsRes, staffRes, routesRes]) => {
        if (!current) return
        setData({
          shops: shopsRes.status === 'fulfilled' && Array.isArray(shopsRes.value) ? shopsRes.value : [],
          staff: staffRes.status === 'fulfilled' && Array.isArray(staffRes.value) ? staffRes.value : [],
          routes: routesRes.status === 'fulfilled' && Array.isArray(routesRes.value) ? routesRes.value : [],
        })
      })
    }
    return () => { current = false }
  }, [open])

  useEffect(() => {
    if (!open) return undefined
    const previousFocus = document.activeElement
    const focusTimer = window.setTimeout(() => inputRef.current?.focus(), 0)
    const onKey = event => {
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        onCloseRef.current?.()
      } else if (event.key === 'Tab') {
        const controls = [...(dialogRef.current?.querySelectorAll('input:not([disabled]), button:not([disabled]), [href], [tabindex="0"]') || [])]
        const first = controls[0]
        const last = controls[controls.length - 1]
        if (!controls.length) { event.preventDefault(); dialogRef.current?.focus(); return }
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
      }
    }
    const dialog = dialogRef.current
    dialog?.addEventListener('keydown', onKey)
    return () => {
      window.clearTimeout(focusTimer)
      dialog?.removeEventListener('keydown', onKey)
      if (previousFocus?.isConnected) previousFocus.focus()
    }
  }, [open])

  useEffect(() => {
    const q = query.trim().toLowerCase()
    if (!q) {
      setResults(STATIC_PAGES.slice(0, 6))
      setSelectedIndex(0)
      return
    }

    const matchedPages = STATIC_PAGES.filter(p =>
      p.label.toLowerCase().includes(q) || p.keywords.toLowerCase().includes(q)
    ).map(p => ({ ...p, type: 'page' }))

    const matchedShops = data.shops.filter(s =>
      s.name?.toLowerCase().includes(q) ||
      s.area?.toLowerCase().includes(q) ||
      s.phone?.includes(q)
    ).slice(0, 5).map(s => ({
      label: s.name,
      sub: s.area ? `${s.area}${s.phone ? ` · ${s.phone}` : ''}` : s.phone,
      path: '/shops',
      category: 'Shops',
      icon: <ContactsIcon size={16} />,
      type: 'shop'
    }))

    const matchedStaff = data.staff.filter(st =>
      st.name?.toLowerCase().includes(q) ||
      st.phone?.includes(q) ||
      st.role?.toLowerCase().includes(q)
    ).slice(0, 4).map(st => ({
      label: st.name,
      sub: `${st.role || 'Staff'}${st.phone ? ` · ${st.phone}` : ''}`,
      path: '/staff',
      category: 'Staff',
      icon: <UserIcon size={16} />,
      type: 'staff'
    }))

    const matchedRoutes = data.routes.filter(r =>
      r.name?.toLowerCase().includes(q)
    ).slice(0, 4).map(r => ({
      label: r.name,
      sub: `${r.stops?.length || 0} stops`,
      path: '/routes',
      category: 'Routes',
      icon: <RouteIcon size={16} />,
      type: 'route'
    }))

    const combined = [...matchedPages, ...matchedShops, ...matchedStaff, ...matchedRoutes]
    setResults(combined)
    setSelectedIndex(0)
  }, [query, data])

  const handleSelect = (item) => {
    if (!item) return
    onClose()
    navigate(item.path)
  }

  const handleKeyDown = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex(idx => (idx + 1) % Math.max(1, results.length))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex(idx => (idx - 1 + results.length) % Math.max(1, results.length))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (results[selectedIndex]) handleSelect(results[selectedIndex])
    }
  }

  if (!open) return null

  return (
    <div
      className="universal-search-overlay"
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 10010,
        background: 'rgba(0, 0, 0, 0.55)',
        backdropFilter: 'blur(8px)',
        WebkitBackdropFilter: 'blur(8px)',
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'center',
        padding: 'calc(60px + env(safe-area-inset-top, 0px)) 16px 20px',
      }}
    >
      <div
        ref={dialogRef}
        className="universal-search-modal card"
        role="dialog"
        aria-modal="true"
        aria-label="Search workspaces"
        tabIndex={-1}
        style={{
          width: '100%',
          maxWidth: 540,
          background: 'var(--bg-1, #ffffff)',
          borderRadius: 16,
          boxShadow: '0 20px 50px rgba(0, 0, 0, 0.35)',
          border: '1px solid var(--border)',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          maxHeight: 'calc(100dvh - 120px)',
          padding: 0,
        }}
      >
        {/* Search Input Bar */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '12px 16px',
            borderBottom: '1px solid var(--border)',
            background: 'var(--bg-2, #fbfbfa)',
          }}
        >
          <SearchIcon size={20} className="muted" />
          <input
            ref={inputRef}
            type="search"
            aria-label="Search pages, shops, staff and routes"
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search pages, shops, staff, routes…"
            style={{
              flex: 1,
              border: 0,
              background: 'transparent',
              fontSize: '16px',
              minWidth: 0,
              fontWeight: 500,
              color: 'var(--text-primary)',
              outline: 'none',
              padding: 0,
            }}
          />
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onClose}
            aria-label="Close search"
            style={{ padding: 4, minWidth: 44, minHeight: 44, height: 44, borderRadius: 6 }}
          >
            <CloseIcon size={16} />
          </button>
        </div>

        {/* Results List */}
        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: '8px',
            display: 'flex',
            flexDirection: 'column',
            gap: 2,
          }}
        >
          {results.length === 0 ? (
            <div className="muted small" style={{ textAlign: 'center', padding: '24px 16px' }}>
              No matches found for “{query}”
            </div>
          ) : (
            results.map((item, idx) => {
              const active = idx === selectedIndex
              return (
                <button
                  key={`${item.path}-${item.label}-${idx}`}
                  type="button"
                  onClick={() => handleSelect(item)}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 12,
                    padding: '8px 12px',
                    borderRadius: 10,
                    border: '1px solid transparent',
                    background: active ? 'var(--accent-dim, rgba(193, 95, 60, 0.12))' : 'transparent',
                    color: active ? 'var(--accent)' : 'var(--text-primary)',
                    cursor: 'pointer',
                    textAlign: 'left',
                    font: 'inherit',
                    transition: 'all 0.12s ease',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0, flex: 1 }}>
                    <span style={{ color: active ? 'var(--accent)' : 'var(--text-muted)', display: 'grid', placeItems: 'center' }}>
                      {item.icon}
                    </span>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontWeight: 650, fontSize: '13.5px', lineHeight: 1.3 }} className="ellipsis">
                        {item.label}
                      </div>
                      {item.sub && (
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: 1 }} className="ellipsis">
                          {item.sub}
                        </div>
                      )}
                    </div>
                  </div>
                  <span
                    className="badge badge-muted"
                    style={{
                      fontSize: '10px',
                      textTransform: 'uppercase',
                      letterSpacing: '0.04em',
                      flexShrink: 0,
                    }}
                  >
                    {item.category}
                  </span>
                </button>
              )
            })
          )}
        </div>

        {/* Footer shortcuts */}
        <div
          style={{
            padding: '8px 14px',
            borderTop: '1px solid var(--border)',
            background: 'var(--bg-3, #f5f5f3)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            fontSize: '11px',
            color: 'var(--text-muted)',
          }}
        >
          <span>Use <b>↑</b> <b>↓</b> to navigate, <b>Enter</b> to select</span>
          <span><b>Esc</b> to close</span>
        </div>
      </div>
    </div>
  )
}
