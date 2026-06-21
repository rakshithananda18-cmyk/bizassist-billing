// components/sales/CartTableHeader.jsx
// ====================================
// The POS cart table's <thead> — column headers in the owner's chosen order with
// sticky positioning. Extracted VERBATIM from Sales.jsx (R5, first safe slice of
// CartTable): pure presentational, no handlers/refs. Returns a <thead> so it sits
// directly inside the existing <table className="pos-cart-table">.
import React from 'react'

export default function CartTableHeader({ columnOrder, colVisible, stickyOffsets, t, hasItems }) {
  return (
    <thead>
      <tr>
        <th style={{ position: 'sticky', left: 0, top: 0, zIndex: 12, background: 'var(--bg-3)', width: 40, minWidth: 40 }}>#</th>
        {columnOrder.map(col => {
          const isVisible = col === 'sku' ? colVisible.sku :
                            col === 'mrp' ? colVisible.mrp :
                            col === 'hsn' ? colVisible.hsn :
                            col === 'unit' ? colVisible.unit :
                            col === 'discount' ? colVisible.discount :
                            col === 'tax' ? colVisible.tax :
                            col === 'batch' ? colVisible.batch :
                            col === 'price_option' ? colVisible.price_option :
                            col === 'rate' ? colVisible.rate :
                            true;
          if (!isVisible) return null;

          const isSticky = stickyOffsets[col] !== undefined;
          const style = {
            position: 'sticky',
            top: 0,
            zIndex: isSticky ? 12 : 10,
            background: 'var(--bg-3)',
          };
          if (isSticky) {
            style.left = stickyOffsets[col];
          }

          const renderHeader = () => {
            if (col === 'sku') {
              return <th key="sku" style={{ ...style, width: 95, minWidth: 95 }}>ITEM CODE</th>;
            }
            if (col === 'name') {
              return (
                <th key="name" style={{
                  ...style,
                  width: '100%',
                  minWidth: 180,
                  borderRight: '1px solid var(--border)',
                  boxShadow: '4px 0 4px -2px rgba(0,0,0,0.1)'
                }}>{(t('product', 'item')).toUpperCase()} NAME</th>
              );
            }
            if (col === 'batch') {
              return <th key="batch" style={{ ...style, width: 140, minWidth: 140, textAlign: 'center' }}>BATCH</th>;
            }
            if (col === 'price_option') {
              return <th key="price_option" style={{ ...style, width: 155, minWidth: 155, textAlign: 'center' }}>PRICE OPTION</th>;
            }
            if (col === 'mrp') {
              return <th key="mrp" style={{ ...style, width: 90, minWidth: 90, textAlign: 'right' }}>MRP (₹)</th>;
            }
            if (col === 'hsn') {
              return <th key="hsn" style={{ ...style, width: 80, minWidth: 80, textAlign: 'center' }}>HSN</th>;
            }
            if (col === 'qty') {
              return <th key="qty" style={{ ...style, width: 80, minWidth: 80, textAlign: 'center' }}>QTY</th>;
            }
            if (col === 'unit') {
              return <th key="unit" style={{ ...style, width: 70, minWidth: 70, textAlign: 'center' }}>UNIT</th>;
            }
            if (col === 'rate') {
              return (
                <th key="rate" style={{ ...style, width: 150, minWidth: 150, textAlign: 'right' }}>
                  PRICE PER UNIT<br/>
                  <span style={{ fontSize: '0.65rem', fontWeight: 'normal', color: 'var(--text-muted)' }}>BEFORE TAX (₹)</span>
                </th>
              );
            }
            if (col === 'price') {
              return (
                <th key="price" style={{ ...style, width: 130, minWidth: 130, textAlign: 'right' }}>
                  TOTAL<br/>
                  <span style={{ fontSize: '0.65rem', fontWeight: 'normal', color: 'var(--text-muted)' }}>BEFORE TAX (₹)</span>
                </th>
              );
            }
            if (col === 'discount') {
              return <th key="discount" style={{ ...style, width: 100, minWidth: 100, textAlign: 'right' }}>DISCOUNT (₹)</th>;
            }
            if (col === 'tax') {
              return <th key="tax" style={{ ...style, width: 110, minWidth: 110, textAlign: 'center' }}>TAX APPLIED(%)</th>;
            }
            if (col === 'total') {
              return (
                <th key="total" style={{ ...style, width: 130, minWidth: 130, textAlign: 'right' }}>
                  TOTAL<br/>
                  <span style={{ fontSize: '0.65rem', fontWeight: 'normal', color: 'var(--text-muted)' }}>AFTER TAX (₹)</span>
                </th>
              );
            }
            return null;
          };
          const headerEl = renderHeader();
          if (headerEl) {
            return React.cloneElement(headerEl, { className: `${headerEl.props.className || ''} col-${col}`.trim() });
          }
          return null;
        })}
        {hasItems && <th style={{ position: 'sticky', top: 0, zIndex: 10, background: 'var(--bg-3)', width: 40, minWidth: 40, textAlign: 'center' }}></th>}
      </tr>
    </thead>
  )
}
