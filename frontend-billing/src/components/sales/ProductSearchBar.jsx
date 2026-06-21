// components/sales/ProductSearchBar.jsx
// =====================================
// The POS product search: the barcode/search input + the autocomplete results
// overlay. Extracted VERBATIM from Sales.jsx (R5 decomposition).
//
// The input is exposed via forwardRef so the parent keeps its `barcodeRef` —
// the global POS keydown handler focuses it (F9, post-save, Escape-clear) exactly
// as before. Presentational otherwise: query/results/handlers are passed in.
import { forwardRef } from 'react'
import { fmt } from '../../utils/format'

const ProductSearchBar = forwardRef(function ProductSearchBar({
  searchQuery,
  onSearchChange,     // (value:string) => void  — set query + reset selection
  onKeyDown,          // handleSearchKeyDown
  placeholder,
  onAddCustom,        // addCustomItemToCart
  filteredProducts,
  selectedIndex,
  onHoverIndex,       // setSelectedIndex
  onPick,             // addProductToCart
}, ref) {
  return (
    <div className="pos-search-container" style={{ position: 'relative' }}>
      <div style={{ display: 'flex', gap: 8 }}>
        <div className="search-bar" style={{ flex: 1, padding: '8px 12px', background: 'var(--bg-2)', borderColor: 'var(--border)' }}>
          <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center' }}><SearchIcon size={14} /></span>
          <input
            ref={ref}
            value={searchQuery}
            onChange={e => onSearchChange(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={placeholder}
            style={{ width: '100%', color: 'var(--text-primary)' }}
          />
        </div>
        <button type="button" className="btn btn-secondary" onClick={onAddCustom} style={{ whiteSpace: 'nowrap', fontSize: '0.8rem', padding: '0 16px' }}>
          <PlusIcon size={14} /> Custom Item
        </button>
      </div>

      {/* Autocomplete Overlay */}
      {filteredProducts.length > 0 && (
        <div style={{
          position: 'absolute',
          top: '100%',
          left: 0,
          right: 0,
          background: 'var(--bg-2)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-md)',
          boxShadow: 'var(--shadow-lg)',
          zIndex: 1000,
          marginTop: 6,
          overflow: 'hidden'
        }}>
          {filteredProducts.map((p, idx) => {
            const isSelected = idx === selectedIndex;
            return (
              <div
                key={p.id}
                style={{
                  padding: '10px 14px',
                  background: isSelected ? 'var(--accent-glow)' : 'transparent',
                  color: isSelected ? 'var(--accent)' : 'var(--text-primary)',
                  cursor: 'pointer',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  borderBottom: '1px solid var(--border)'
                }}
                onClick={() => onPick(p)}
                onMouseEnter={() => onHoverIndex(idx)}
              >
                <div style={{ display: 'flex', flexDirection: 'column' }}>
                  <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>{p.name}</span>
                  <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>SKU: {p.sku || '—'} {p.barcode ? `| Barcode: ${p.barcode}` : ''}</span>
                </div>
                <span style={{ fontWeight: 700, fontSize: '0.85rem', color: 'var(--success)' }}>{fmt(p.selling_price)}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  )
})

export default ProductSearchBar

import { PlusIcon, SearchIcon } from '../../components/Icons'