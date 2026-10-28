// src/components/settings/SettingsSearch.jsx
import React from 'react'
import { SearchIcon, CloseIcon } from '../Icons'

export default function SettingsSearch({ query, onQueryChange, placeholder = 'Search preferences…' }) {
  return (
    <div className="settings-search-box" style={{
      padding: '8px 12px',
      borderBottom: '1px solid var(--border)',
      background: 'var(--bg-2)',
      display: 'flex',
      alignItems: 'center',
      gap: 6
    }}>
      <SearchIcon size={13} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
      <input
        type="search"
        value={query}
        onChange={e => onQueryChange(e.target.value)}
        placeholder={placeholder}
        aria-label="Search settings"
        style={{
          border: 'none',
          background: 'transparent',
          fontSize: '0.78rem',
          color: 'var(--text-primary)',
          outline: 'none',
          width: '100%',
          padding: 0
        }}
      />
      {query && (
        <button
          type="button"
          onClick={() => onQueryChange('')}
          style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 2, display: 'flex', color: 'var(--text-muted)' }}
          aria-label="Clear settings search"
        >
          <CloseIcon size={12} />
        </button>
      )}
    </div>
  )
}
