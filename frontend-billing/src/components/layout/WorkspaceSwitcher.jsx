// src/components/layout/WorkspaceSwitcher.jsx
// Symmetric workspace switcher between Billing POS/ERP and companion Field Team app.
import React from 'react'
import { Link } from 'react-router-dom'
import { MonitorIcon, TruckIcon } from '../Icons'
import { fieldTeamLaunchUrl } from '../../config/fieldTeam'
import { isDemoMode } from '../../demo/demoEngine'

export default function WorkspaceSwitcher({ activeWorkspace = 'billing', user, onFieldTeam, isDemoSession = false }) {
  const demoProtected = Boolean(isDemoSession || user?.is_demo || isDemoMode())
  const fieldUrl = demoProtected ? '/demo-preview/field-team' : fieldTeamLaunchUrl(user)
  if (!fieldUrl || !onFieldTeam || ['cashier', 'supply_adder'].includes(user?.role)) return null
  const FieldLink = demoProtected ? Link : 'a'
  const fieldLinkProps = demoProtected ? { to: fieldUrl } : {
    href: fieldUrl,
    onClick: event => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return
      event.preventDefault()
      onFieldTeam()
    },
  }

  return (
    <nav className="workspace-switch" aria-label="Stater workspaces" style={{
      display: 'inline-flex',
      alignItems: 'center',
      background: 'var(--bg-1)',
      border: '1px solid var(--border)',
      borderRadius: '999px',
      padding: '2px',
      gap: 2,
    }}>
      <span
        className={`workspace-tab ${activeWorkspace === 'billing' ? 'active' : ''}`}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 5,
          padding: '3px 10px',
          borderRadius: '999px',
          fontSize: '0.74rem',
          fontWeight: 700,
          background: activeWorkspace === 'billing' ? 'var(--bg-3)' : 'transparent',
          color: activeWorkspace === 'billing' ? 'var(--accent)' : 'var(--text-muted)',
          cursor: 'default',
        }}
      >
        <MonitorIcon size={13} /> Billing
      </span>

      <FieldLink
        {...fieldLinkProps}
        className="workspace-tab"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 5,
          padding: '3px 10px',
          borderRadius: '999px',
          fontSize: '0.74rem',
          fontWeight: 600,
          background: 'transparent',
          border: 'none',
          color: 'var(--text-secondary)',
          cursor: 'pointer',
          transition: 'all 0.15s ease',
        }}
        title={demoProtected ? 'Field Team — protected demo preview' : 'Open companion Field Team workspace'}
      >
        <TruckIcon size={13} /> Field Team
        {demoProtected && <span style={{ fontSize: '0.62rem', fontWeight: 700, color: 'var(--accent)' }}>Protected</span>}
      </FieldLink>
    </nav>
  )
}
