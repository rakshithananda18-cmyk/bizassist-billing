import { NavLink, Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useState, useEffect } from 'react'

const ADMIN_NAV = [
  { to: '/admin/dashboard',  label: '📊 Overview' },
  { to: '/admin/businesses', label: '🏢 Businesses' },
  { to: '/admin/usage',      label: '📈 Usage & Limits' },
  { to: '/admin/cache',      label: '🗑 Cache & System' },
]

export default function AdminLayout() {
  const { adminUser, adminLogout } = useAuth()
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)

  function handleLogout() {
    adminLogout()
    navigate('/admin/login')
  }

  // Close menu when clicking outside
  useEffect(() => {
    function handler(e) {
      if (!e.target.closest('.admin-sidebar-wrap')) setMenuOpen(false)
    }
    document.addEventListener('click', handler)
    return () => document.removeEventListener('click', handler)
  }, [])

  return (
    <div style={{
      height: '100vh',
      overflow: 'hidden',
      background: 'var(--bg-color)',
      display: 'flex',
      flexDirection: 'column',
    }}>

      {/* ── TOP NAV BAR ── */}
      <header style={{
        height: 56,
        borderBottom: '1.5px solid var(--border-color)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 28px',
        background: 'var(--card-color)',
        boxShadow: 'var(--shadow-sm)',
        flexShrink: 0,
        zIndex: 50,
        position: 'sticky',
        top: 0,
      }}>
        {/* Logo */}
        <div style={{
          fontFamily: "'Crimson Pro', Georgia, serif",
          fontSize: 20,
          fontWeight: 700,
          color: 'var(--text-color)',
          letterSpacing: '-0.01em',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}>
          <span style={{ color: 'var(--accent-color)' }}>✦</span> BIZASSIST
          <span style={{
            fontSize: 11,
            fontFamily: "'DM Sans', sans-serif",
            fontWeight: 600,
            color: 'var(--accent-color)',
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            background: 'var(--accent-soft)',
            padding: '2px 8px',
            borderRadius: 999,
            marginLeft: 6,
          }}>ADMIN</span>
        </div>

        {/* Nav links */}
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
              {n.label}
            </NavLink>
          ))}
        </nav>

        {/* Sign out */}
        <button
          onClick={handleLogout}
          style={{
            padding: '8px 16px',
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
          Sign Out →
        </button>
      </header>

      {/* ── CONTENT AREA ── */}
      <main style={{
        flex: 1,
        minHeight: 0,
        overflowY: 'auto',
        padding: '32px 40px',
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
