// src/components/WorkspaceSwitcher.jsx
// Symmetric workspace switcher between Billing POS/ERP and companion Field Team app.
import React from 'react'
import { MonitorIcon, TruckIcon } from './Icons'
import { getBillingUrl } from '../lib/theme'

export default function WorkspaceSwitcher({ activeWorkspace = 'field' }) {
  const billingUrl = getBillingUrl()

  return (
    <nav
      className="workspace-switch-pill"
      aria-label="BizAssist workspaces"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        background: 'var(--bg-1)',
        border: '1px solid var(--border)',
        borderRadius: '999px',
        padding: '2px',
        gap: 2,
      }}
    >
      <a
        href={billingUrl}
        className={`workspace-tab ${activeWorkspace === 'billing' ? 'active' : ''}`}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 5,
          padding: '3px 10px',
          borderRadius: '999px',
          fontSize: '0.74rem',
          fontWeight: activeWorkspace === 'billing' ? 700 : 600,
          background: activeWorkspace === 'billing' ? 'var(--bg-3)' : 'transparent',
          color: activeWorkspace === 'billing' ? 'var(--accent)' : 'var(--text-secondary)',
          textDecoration: 'none',
          cursor: activeWorkspace === 'billing' ? 'default' : 'pointer',
          transition: 'all 0.15s ease',
        }}
        title="Switch to Billing POS/ERP"
      >
        <MonitorIcon size={13} /> <span>Billing</span>
      </a>

      <span
        className={`workspace-tab ${activeWorkspace === 'field' ? 'active' : ''}`}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 5,
          padding: '3px 10px',
          borderRadius: '999px',
          fontSize: '0.74rem',
          fontWeight: 700,
          background: activeWorkspace === 'field' ? 'var(--bg-3)' : 'transparent',
          color: activeWorkspace === 'field' ? 'var(--accent)' : 'var(--text-muted)',
          cursor: 'default',
        }}
      >
        <TruckIcon size={13} /> <span>Field Team</span>
      </span>
    </nav>
  )
}
