import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useState, useEffect } from 'react'
import { BuildingMark } from '../components/Logo'
import { Icon } from '../components/icons'

const ADMIN_NAV = [
  { to: '/admin/dashboard',  icon: 'dashboard', label: 'Overview' },
  { to: '/admin/businesses', icon: 'users',     label: 'Businesses' },
  { to: '/admin/usage',      icon: 'chart',     label: 'Usage & Limits' },
  { to: '/admin/health',     icon: 'alert',     label: 'Health & Audits' },
  { to: '/admin/telemetry',  icon: 'file',      label: 'Telemetry & Logs' },
  { to: '/admin/cache',      icon: 'trash',     label: 'Cache & System' },
]

export default function AdminLayout() {
  const { adminLogout } = useAuth()
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const [isMobile, setIsMobile] = useState(() => window.innerWidth <= 1024)

  function handleLogout() {
    adminLogout()
    navigate('/admin/login')
  }

  // Handle resize for responsiveness
  useEffect(() => {
    function handleResize() {
      setIsMobile(window.innerWidth <= 1024)
    }
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  // Close menu when clicking outside
  useEffect(() => {
    function handler(e) {
      if (menuOpen && !e.target.closest('.admin-drawer') && !e.target.closest('.admin-hamburger')) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [menuOpen])

  return (
    <div className="admin-layout">

      {/* ── TOP NAV BAR ── */}
      <header style={{
        height: 56,
        borderBottom: '1.5px solid var(--border-color)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: isMobile ? '0 16px' : '0 28px',
        background: 'var(--card-color)',
        boxShadow: 'var(--shadow-sm)',
        flexShrink: 0,
        zIndex: 50,
        position: 'relative',
      }}>
        {/* Left Side: Hamburger & Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {isMobile && (
            <button
              className="admin-hamburger"
              onClick={(e) => { e.stopPropagation(); setMenuOpen(prev => !prev); }}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--text-color)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '6px',
                borderRadius: '6px',
                transition: 'background 0.2s',
              }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--hover-bg)'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
              title="Toggle Menu"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="3" y1="12" x2="21" y2="12"></line>
                <line x1="3" y1="6" x2="21" y2="6"></line>
                <line x1="3" y1="18" x2="21" y2="18"></line>
              </svg>
            </button>
          )}

          {/* Logo */}
          <div style={{
            fontFamily: "'Crimson Pro', Georgia, serif",
            fontSize: isMobile ? 18 : 20,
            fontWeight: 700,
            color: 'var(--text-color)',
            letterSpacing: '-0.01em',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
          }}>
            <BuildingMark size={20} /> BIZASSIST
            <span style={{
              fontSize: 10,
              fontFamily: "'DM Sans', sans-serif",
              fontWeight: 600,
              color: 'var(--accent-color)',
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
              background: 'var(--accent-soft)',
              padding: '2px 6px',
              borderRadius: 999,
              marginLeft: 4,
            }}>ADMIN</span>
          </div>
        </div>

        {/* Nav links (Desktop Only) */}
        {!isMobile && (
          <nav style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            {ADMIN_NAV.map(n => (
              <NavLink
                key={n.to}
                to={n.to}
                style={({ isActive }) => ({
                  padding: '6px 14px',
                  borderRadius: 8,
                  fontSize: 13,
                  fontFamily: "'DM Sans', sans-serif",
                  fontWeight: 500,
                  textDecoration: 'none',
                  color: isActive ? 'var(--accent-color)' : 'var(--secondary-text)',
                  background: isActive ? 'var(--accent-soft)' : 'transparent',
                  transition: 'all 0.15s ease',
                })}
              >
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}><Icon name={n.icon} size={15} /> {n.label}</span>
              </NavLink>
            ))}
          </nav>
        )}

        {/* Sign out */}
        <button
          onClick={handleLogout}
          style={{
            padding: isMobile ? '6px 12px' : '8px 16px',
            border: '1px solid var(--border-color)',
            borderRadius: 8,
            background: 'transparent',
            color: 'var(--secondary-text)',
            fontFamily: "'DM Sans', sans-serif",
            fontSize: 13,
            fontWeight: 500,
            cursor: 'pointer',
            transition: 'all 0.15s',
          }}
          onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--accent-color)'; e.currentTarget.style.color = 'var(--accent-color)' }}
          onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border-color)'; e.currentTarget.style.color = 'var(--secondary-text)' }}
        >
          {isMobile ? 'Sign Out' : 'Sign Out →'}
        </button>
      </header>

      {/* ── MOBILE DRAWER ── */}
      {isMobile && (
        <>
          <div
            className="admin-drawer"
            style={{
              position: 'fixed',
              top: 0,
              left: 0,
              bottom: 0,
              width: '70vw',
              maxWidth: 300,
              height: '100dvh',
              background: 'var(--sidebar-color)',
              borderRight: '1px solid var(--border-color)',
              transform: menuOpen ? 'translateX(0)' : 'translateX(-100%)',
              transition: 'transform 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
              zIndex: 1010,
              display: 'flex',
              flexDirection: 'column',
              padding: '16px 12px',
              gap: 8,
              boxShadow: 'var(--shadow-lg)',
            }}
          >
            {/* Drawer Header */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              height: 38,
              padding: '0 4px',
              marginBottom: 8,
            }}>
              <div style={{
                fontFamily: "'Crimson Pro', Georgia, serif",
                fontSize: 18,
                fontWeight: 700,
                color: 'var(--text-color)',
              }}>
                BizAssist Admin
              </div>
              <button
                onClick={() => setMenuOpen(false)}
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: 'var(--text-color)',
                  fontSize: 22,
                  cursor: 'pointer',
                  width: 32,
                  height: 32,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                ×
              </button>
            </div>

            <div style={{ height: 1, background: 'var(--border-color)', margin: '0 4px 12px' }}></div>

            {/* Drawer Nav links */}
            {ADMIN_NAV.map(n => (
              <NavLink
                key={n.to}
                to={n.to}
                onClick={() => setMenuOpen(false)}
                style={({ isActive }) => ({
                  padding: '10px 14px',
                  borderRadius: 8,
                  fontSize: 14,
                  fontFamily: "'DM Sans', sans-serif",
                  fontWeight: 500,
                  textDecoration: 'none',
                  color: isActive ? 'var(--accent-color)' : 'var(--text-color)',
                  background: isActive ? 'var(--accent-soft)' : 'transparent',
                  transition: 'all 0.15s ease',
                  display: 'block',
                })}
              >
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}><Icon name={n.icon} size={15} /> {n.label}</span>
              </NavLink>
            ))}
          </div>

          {/* Backdrop Overlay */}
          <div
            onClick={() => setMenuOpen(false)}
            style={{
              position: 'fixed',
              inset: 0,
              background: 'rgba(0, 0, 0, 0.4)',
              backdropFilter: 'blur(1.5px)',
              WebkitBackdropFilter: 'blur(1.5px)',
              opacity: menuOpen ? 1 : 0,
              pointerEvents: menuOpen ? 'auto' : 'none',
              transition: 'opacity 0.3s ease',
              zIndex: 1000,
            }}
          />
        </>
      )}

      {/* ── CONTENT AREA ── */}
      <main style={{
        flex: 1,
        minHeight: 0,
        overflowY: 'auto',
        padding: isMobile ? '16px 20px' : '32px 40px',
        maxWidth: 1200,
        width: '100%',
        margin: '0 auto',
        boxSizing: 'border-box',
      }}>
        <Outlet />
      </main>
    </div>
  )
}
