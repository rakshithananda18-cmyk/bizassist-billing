import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

const ADMIN_NAV = [
  { to: '/admin/dashboard',  label: '📊 Overview' },
  { to: '/admin/businesses', label: '🏢 Businesses' },
  { to: '/admin/usage',      label: '📈 Usage & Limits' },
  { to: '/admin/cache',      label: '🗑 Cache & System' },
]

export default function AdminLayout() {
  const { adminUser, adminLogout } = useAuth()
  const navigate = useNavigate()

  function handleLogout() {
    adminLogout()
    navigate('/admin/login')
  }

  return (
    <div className="app-layout">
      <aside className="sidebar sidebar-admin">
        <div className="sidebar-logo">✦ BIZASSIST</div>
        <div className="sidebar-biz" style={{ color: '#c97c22' }}>Admin Workspace</div>
        <nav className="sidebar-nav">
          {ADMIN_NAV.map(n => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <button className="sidebar-logout" onClick={handleLogout}>
          Sign Out ➔
        </button>
      </aside>

      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
