import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

const NAV = [
  { to: '/dashboard', label: '📊 Dashboard' },
  { to: '/chat',      label: '💬 AI Assistant' },
  { to: '/upload',    label: '📁 Upload Data' },
  { to: '/database',  label: '🗄 Database' },
]

export default function AppLayout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  function handleLogout() {
    logout()
    navigate('/login')
  }

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="sidebar-logo">✦ BIZASSIST</div>
        <div className="sidebar-biz">{user?.business_name || 'My Business'}</div>
        <nav className="sidebar-nav">
          {NAV.map(n => (
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
