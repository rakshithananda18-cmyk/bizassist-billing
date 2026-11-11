// ============================================================================
// MenuCataloguePane — the right-pane menu/catalogue grid shown in `menu` entry
// mode (restaurant-style POS), extracted verbatim from pages/Sales.jsx
// (repo restructure). Also fixes a latent crash: the original inline JSX used
// <InventoryIcon> without importing it in Sales.jsx.
// ============================================================================
import React, { useEffect, useState } from 'react'
import { InventoryIcon } from '../Icons'
import { fmt } from '../../utils/format'
import usePhoneLayout from '../../hooks/usePhoneLayout'

export default function MenuCataloguePane({ groupedProducts, onSelectProduct }) {
  const phone = usePhoneLayout()
  const [category, setCategory] = useState('')
  const categories = Object.keys(groupedProducts)
  useEffect(() => { if (category && !groupedProducts[category]) setCategory('') }, [category, groupedProducts])
  if (phone) {
    const entries = category ? [[category, groupedProducts[category] || []]] : Object.entries(groupedProducts)
    return <div className="pos-right-pane pos-phone-catalogue">
      <div className="pos-phone-categories" aria-label="Product categories">
        <button type="button" aria-pressed={!category} onClick={() => setCategory('')}>All items</button>
        {categories.map(name => <button key={name} type="button" aria-pressed={category === name} onClick={() => setCategory(name)}>{name}</button>)}
      </div>
      <div className="pos-phone-catalogue-heading"><span>{entries.reduce((sum, [, items]) => sum + items.length, 0)} items</span><span>Tap an item to add</span></div>
      <div className="pos-phone-product-list">
        {entries.flatMap(([name, items]) => items.map(product => <button key={product.id} type="button" className="pos-phone-product" aria-label={`Add ${product.name} to bill`} onClick={() => onSelectProduct(product)}>
          <span className="pos-phone-product-mark" aria-hidden="true">{product.name?.slice(0, 1)}</span>
          <span className="pos-phone-product-copy"><strong>{product.name}</strong><small>{product.unit || 'pcs'}<span aria-hidden="true"> · </span>{name}</small></span>
          <span className="pos-phone-product-price">{fmt(product.selling_price)}<span aria-hidden="true">+</span></span>
        </button>))}
        {!entries.some(([, items]) => items.length) && <div className="pos-mobile-empty"><strong>No matching items</strong><span>Try a different search or category.</span></div>}
      </div>
    </div>
  }
  return (
    <div
      className="pos-right-pane"
      style={{
        width: '42%',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        padding: '16px',
        background: 'var(--bg)',
        borderLeft: '1px solid var(--border)',
        overflowY: 'auto',
        gap: '20px'
      }}
    >
      <div style={{ fontSize: '1.1rem', fontWeight: 800, color: 'var(--text-primary)', borderBottom: '2.5px solid var(--accent)', paddingBottom: '6px', marginBottom: '4px' }}>
        <InventoryIcon size={16} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Menu / Catalogue
      </div>
      {Object.keys(groupedProducts).length === 0 ? (
        <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.9rem', marginTop: '40px' }}>
          No products found in stock.
        </div>
      ) : (
        Object.entries(groupedProducts).map(([catName, items]) => (
          <div key={catName} style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <h3 style={{ fontSize: '0.9rem', fontWeight: 700, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              {catName}
            </h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: '10px' }}>
              {items.map(p => (
                <button
                  key={p.id}
                  type="button"
                  className="menu-product-card"
                  onClick={() => onSelectProduct(p)}
                  aria-label={`Add ${p.name} to bill`}
                  style={{
                    background: 'var(--bg-2)',
                    border: '1.5px solid var(--border)',
                    borderRadius: '10px',
                    padding: '10px',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'space-between',
                    minHeight: '85px',
                    boxShadow: '0 2px 4px rgba(0,0,0,0.02)',
                    color: 'inherit',
                    textAlign: 'left',
                    font: 'inherit'
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = 'var(--accent)'
                    e.currentTarget.style.transform = 'translateY(-2px)'
                    e.currentTarget.style.boxShadow = '0 4px 12px rgba(249,115,22,0.1)'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = 'var(--border)'
                    e.currentTarget.style.transform = 'none'
                    e.currentTarget.style.boxShadow = '0 2px 4px rgba(0,0,0,0.02)'
                  }}
                >
                  <div style={{ fontWeight: 600, fontSize: '0.82rem', color: 'var(--text-primary)', lineHeight: 1.3 }}>
                    {p.name}
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginTop: '6px' }}>
                    <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                      {p.unit || 'pcs'}
                    </span>
                    <span style={{ fontWeight: 700, fontSize: '0.85rem', color: 'var(--accent)' }}>
                      {fmt(p.selling_price)}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        ))
      )}
    </div>
  )
}
