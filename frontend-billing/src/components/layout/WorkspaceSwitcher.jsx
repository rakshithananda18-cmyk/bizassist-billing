// src/components/layout/WorkspaceSwitcher.jsx
// Symmetric workspace switcher between Billing POS/ERP and companion Field Team app.
import React from 'react'
import { MonitorIcon, TruckIcon } from '../Icons'
import { getFieldTeamUrl } from '../../config/fieldTeam'

export default function WorkspaceSwitcher({ activeWorkspace = 'billing', user, onFieldTeam }) {
  const fieldUrl = getFieldTeamUrl()
  if (!fieldUrl || !onFieldTeam || ['cashier', 'supply_adder'].includes(user?.role)) return null

  return (
    <nav className="workspace-switch" aria-label="BizAssist workspaces" style={{
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

      <button
        type="button"
        onClick={onFieldTeam}
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
        title="Open companion Field Team workspace"
      >
        <TruckIcon size={13} /> Field Team
      </button>
    </nav>
  )
}
