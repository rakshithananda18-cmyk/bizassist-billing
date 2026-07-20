// ============================================================================
// Settings shared primitives — extracted verbatim from pages/Settings.jsx
// (repo restructure): BrandLoader, Toggle, SettingRow, SectionHeader + the
// shared modal style constants.
// ============================================================================
import React from 'react'
import { SkylineLoader } from '../Logo'

// ============================================================================
// ─── Brand Loading Animation (matches PageLoader / frontend-ai style) ─────────
export function BrandLoader({ message = 'Loading settings…' }) {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 20,
      padding: '80px 0',
    }}>
      <div style={{ color: 'var(--accent)' }}>
        <SkylineLoader size={72} />
      </div>
      <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', letterSpacing: '0.01em' }}>{message}</div>
    </div>
  )
}

// ─── Toggle Switch ────────────────────────────────────────────────────────────
export function Toggle({ checked, onChange, id, disabled = false }) {
  return (
    <label
      htmlFor={id}
      style={{
        position: 'relative',
        display: 'inline-block',
        width: 42,
        height: 24,
        cursor: disabled ? 'not-allowed' : 'pointer',
        flexShrink: 0,
      }}
    >
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={e => !disabled && onChange(e.target.checked)}
        style={{ opacity: 0, width: 0, height: 0, position: 'absolute' }}
        disabled={disabled}
      />
      <span style={{
        position: 'absolute',
        inset: 0,
        borderRadius: 24,
        background: checked ? 'var(--accent)' : 'var(--border)',
        transition: 'background 0.2s',
        opacity: disabled ? 0.5 : 1,
      }} />
      <span style={{
        position: 'absolute',
        top: 3,
        left: checked ? 21 : 3,
        width: 18,
        height: 18,
        borderRadius: '50%',
        background: '#fff',
        transition: 'left 0.2s',
        boxShadow: '0 1px 3px rgba(0,0,0,0.25)',
      }} />
    </label>
  )
}

// ─── Setting Row ──────────────────────────────────────────────────────────────
export function SettingRow({ label, description, children, id }) {
  return (
    <div id={id} className="setting-row" style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 16,
      padding: '14px 0',
      borderBottom: '1px solid var(--border)',
      borderRadius: 'var(--radius-sm)',
    }}>
      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: 600, fontSize: '0.88rem', color: 'var(--text)' }}>{label}</div>
        {description && (
          <div style={{ fontSize: '0.77rem', color: 'var(--text-muted)', marginTop: 2 }}>{description}</div>
        )}
      </div>
      <div style={{ flexShrink: 0 }}>{children}</div>
    </div>
  )
}

// ─── Section Header ───────────────────────────────────────────────────────────
export function SectionHeader({ title }) {
  return (
    <div style={{
      fontSize: '0.72rem',
      fontWeight: 700,
      color: 'var(--accent)',
      letterSpacing: '0.1em',
      textTransform: 'uppercase',
      marginTop: 24,
      marginBottom: 4,
    }}>
      {title}
    </div>
  )
}

export const overlayStyle = {
  position: 'fixed', inset: 0, zIndex: 9000,
  background: 'rgba(0,0,0,0.4)', backdropFilter: 'blur(8px)',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  padding: 20, pointerEvents: 'all', touchAction: 'none',
}
export const boxStyle = {
  background: 'var(--bg-2)', border: '1px solid var(--border)',
  borderRadius: 'var(--radius-xl)', padding: '28px 28px 24px',
  width: '100%', maxWidth: 360, boxShadow: 'var(--shadow-lg)',
  display: 'flex', flexDirection: 'column', gap: 16,
}
export const inputStyle = {
  padding: '10px 14px', background: 'var(--bg-3)',
  border: '1px solid var(--border)', borderRadius: 'var(--radius-md)',
  color: 'var(--text-primary)', fontSize: '1rem',
  outline: 'none', width: '100%', boxSizing: 'border-box',
  textAlign: 'center', letterSpacing: '0.15em',
}

