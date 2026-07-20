// ============================================================================
// PriceSelectorModal — "multiple prices found" picker for a cart line,
// extracted verbatim from pages/Sales.jsx (repo restructure).
// Presentational: options + selection index in, callbacks out.
// ============================================================================
import React from 'react'
import { TagIcon, CloseIcon } from '../Icons'
import { fmt } from '../../utils/format'

export default function PriceSelectorModal({ productName, options, selectedIndex, onHoverIndex, onSelect, onClose }) {
  return (
    <div
      className="modal-overlay"
      onClick={onClose}
      style={{ zIndex: 2010 }}
    >
      <div
        className="modal"
        style={{
          maxWidth: '580px',
          background: 'var(--glass-bg)',
          backdropFilter: 'blur(30px) saturate(190%)',
          WebkitBackdropFilter: 'blur(30px) saturate(190%)',
          border: '1px solid var(--glass-border)',
          color: 'var(--text-primary)',
          boxShadow: 'var(--shadow-lg)'
        }}
        onClick={e => e.stopPropagation()}
      >
        <div className="modal-header" style={{ borderBottom: '1px solid var(--border)' }}>
          <span className="modal-title" style={{ fontSize: '1.1rem', fontWeight: 800, display: 'inline-flex', alignItems: 'center', gap: '6px', color: 'var(--text-primary)' }}>
            <TagIcon size={18} style={{ color: 'var(--accent)' }} /> Price Selection — {productName}
          </span>
          <button
            className="btn btn-ghost btn-icon"
            onClick={onClose}
            style={{ color: 'var(--text-muted)' }}
           aria-label="Close"><CloseIcon size={16} /></button>
        </div>
        <div className="modal-body" style={{ padding: '16px 20px' }}>
          <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginBottom: '12px' }}>
            Multiple prices found for this item. Use <kbd>↑</kbd> <kbd>↓</kbd> arrows and <kbd>Enter</kbd> / <kbd>Esc</kbd> or click a row to select.
          </p>

          <div style={{ overflowX: 'auto', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.88rem' }}>
              <thead>
                <tr style={{ background: 'var(--bg-3)', borderBottom: '1px solid var(--border)', textAlign: 'left' }}>
                  <th style={{ padding: '10px 12px', fontWeight: 700, color: 'var(--text-muted)' }}>Price Option</th>
                  <th style={{ padding: '10px 12px', fontWeight: 700, color: 'var(--text-muted)' }}>Date Added</th>
                  <th style={{ padding: '10px 12px', fontWeight: 700, color: 'var(--text-muted)', textAlign: 'right' }}>Price</th>
                </tr>
              </thead>
              <tbody>
                {options.map((opt, oIdx) => {
                  const isSelected = oIdx === selectedIndex;
                  return (
                    <tr
                      key={oIdx}
                      style={{
                        background: isSelected ? 'var(--accent-glow)' : 'transparent',
                        borderBottom: '1px solid var(--border)',
                        cursor: 'pointer',
                        transition: 'background 0.15s ease',
                        color: isSelected ? 'var(--text-primary)' : 'var(--text-secondary)',
                        fontWeight: isSelected ? 600 : 'normal'
                      }}
                      onClick={() => onSelect(opt.price, opt.label)}
                      onMouseEnter={() => onHoverIndex(oIdx)}
                    >
                      <td style={{ padding: '12px' }}>
                        <span>{opt.label}</span>
                      </td>
                      <td style={{ padding: '12px', color: isSelected ? 'var(--text-primary)' : 'var(--text-muted)' }}>
                        {opt.formatted_date}
                      </td>
                      <td style={{ padding: '12px', textAlign: 'right', fontWeight: 700, color: isSelected ? 'var(--accent)' : 'var(--text-primary)' }}>
                        {fmt(opt.price)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
