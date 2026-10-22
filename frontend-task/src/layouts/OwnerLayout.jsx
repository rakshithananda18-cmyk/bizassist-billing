import React, { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { cycleTheme, getTheme } from '../lib/theme'
import { BuildingMark } from '../components/Logo'
import { useToast } from '../components/ui'
import {
  AwardIcon, ClipboardIcon, ClockIcon, ContactsIcon, DashboardIcon, ListIcon, LogoutIcon, MapPinIcon,
  MonitorIcon, MoonIcon, OrderIcon, RouteIcon, SettingsIcon, SunIcon, TruckIcon, UserIcon,
} from '../components/Icons'

const NAV = [
  { section: 'Today', items: [
    { to: '/', icon: <DashboardIcon size={16} />, label: 'Dashboard', end: true },
    { to: '/live', icon: <MapPinIcon size={16} />, label: 'Live map' },
    { to: '/plan', icon: <TruckIcon size={16} />, label: 'Day plan' },
    { to: '/tasks', icon: <ClipboardIcon size={16} />, label: 'Tasks' },
    { to: '/requests', icon: <OrderIcon size={16} />, label: 'Shop requests' },
  ] },
  { section: 'Setup', items: [
    { to: '/shops', icon: <ContactsIcon size={16} />, label: 'Shops' },
    { to: '/routes', icon: <RouteIcon size={16} />, label: 'Routes' },
    { to: '/staff', icon: <UserIcon size={16} />, label: 'Staff' },
  ] },
  { section: 'Records', items: [
    { to: '/attendance', icon: <ClockIcon size={16} />, label: 'Attendance' },
    { to: '/scorecard', icon: <AwardIcon size={16} />, label: 'Scorecard' },
    { to: '/activity', icon: <ListIcon size={16} />, label: 'Activity' },
    { to: '/settings', icon: <SettingsIcon size={16} />, label: 'Settings' },
  ] },
]

const THEME_ICON = { system: <MonitorIcon size={16} />, light: <SunIcon size={16} />, dark: <MoonIcon size={16} /> }

export default function OwnerLayout() {
  const { me, logout } = useAuth()
  const toast = useToast()
  const [theme, setThemeState] = useState(getTheme())
  const copyBizId = async () => {
    try { await navigator.clipboard.writeText(me.public_id); toast('BizID copied — share it with your staff', 'success') } catch { /* ignore */ }
  }
  const items = NAV.flatMap(s => s.items)
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <BuildingMark size={30} />
          <div>
            <div className="brand-name">BizAssist</div>
            <div className="brand-tag">Field Team</div>
          </div>
        </div>
        <nav className="sidebar-nav">
          {NAV.map(sec => (
            <div key={sec.section}>
              <div className="nav-section-label">{sec.section}</div>
              {sec.items.map(it => (
                <NavLink key={it.to} to={it.to} end={it.end} className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
                  <span className="nav-icon">{it.icon}</span>{it.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="ellipsis" style={{ fontWeight: 700 }}>{me.business_name}</div>
          <div className="row">
            <button className="bizid-chip" onClick={copyBizId} title="Copy BizID">{me.public_id}</button>
            <span className="xs muted">tap to copy</span>
          </div>
          <div className="row">
            <button className="btn btn-ghost btn-sm" onClick={() => setThemeState(cycleTheme())} title={`Theme: ${theme}`}>{THEME_ICON[theme]} {theme}</button>
            <button className="btn btn-ghost btn-sm" onClick={logout}><LogoutIcon size={16} /> Sign out</button>
          </div>
        </div>
      </aside>
      <div className="mobile-topbar">
        <div className="row"><BuildingMark size={24} /><strong className="ellipsis">{me.business_name}</strong></div>
        <div className="row">
          <button className="bizid-chip" onClick={copyBizId}>{me.public_id}</button>
          <button className="btn btn-ghost btn-sm" onClick={logout} aria-label="Sign out"><LogoutIcon size={18} /></button>
        </div>
      </div>
      <nav className="mobile-tabs">
        {items.map(it => (
          <NavLink key={it.to} to={it.to} end={it.end} className={({ isActive }) => (isActive ? 'active' : '')}>{it.label}</NavLink>
        ))}
      </nav>
      <main className="main"><Outlet /></main>
    </div>
  )
}
