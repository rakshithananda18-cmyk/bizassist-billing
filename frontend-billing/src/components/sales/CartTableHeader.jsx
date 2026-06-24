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
        <th className="pos-header-index">#</th>
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
          const style = isSticky ? { left: stickyOffsets[col] } : {};

          const renderHeader = () => {
            if (col === 'sku') {
              return <th key="sku">ITEM CODE</th>;
            }
            if (col === 'name') {
              return (
                <th key="name">{(t('product', 'item')).toUpperCase()} NAME</th>
              );
            }
            if (col === 'batch') {
              return <th key="batch">BATCH</th>;
            }
            if (col === 'price_option') {
              return <th key="price_option">PRICE OPTION</th>;
            }
            if (col === 'mrp') {
              return <th key="mrp">MRP (₹)</th>;
            }
            if (col === 'hsn') {
              return <th key="hsn">HSN</th>;
            }
            if (col === 'qty') {
              return <th key="qty">QTY</th>;
            }
            if (col === 'unit') {
              return <th key="unit">UNIT</th>;
            }
            if (col === 'rate') {
              return (
                <th key="rate">
                  PRICE PER UNIT<br/>
                  <span className="pos-text-muted" style={{ fontSize: '0.65rem', fontWeight: 'normal' }}>BEFORE TAX (₹)</span>
                </th>
              );
            }
            if (col === 'price') {
              return (
                <th key="price">
                  TOTAL<br/>
                  <span className="pos-text-muted" style={{ fontSize: '0.65rem', fontWeight: 'normal' }}>BEFORE TAX (₹)</span>
                </th>
              );
            }
            if (col === 'discount') {
              return <th key="discount">DISCOUNT (₹)</th>;
            }
            if (col === 'tax') {
              return <th key="tax">TAX APPLIED(%)</th>;
            }
            if (col === 'total') {
              return (
                <th key="total">
                  TOTAL<br/>
                  <span className="pos-text-muted" style={{ fontSize: '0.65rem', fontWeight: 'normal' }}>AFTER TAX (₹)</span>
                </th>
              );
            }
            return null;
          };
          const headerEl = renderHeader();
          if (headerEl) {
            const extraClasses = `col-${col} ${isSticky ? 'pos-sticky-header sticky-left' : 'pos-sticky-header'} ${col === 'name' && isSticky ? 'pos-sticky-cell-name' : ''}`.trim();
            return React.cloneElement(headerEl, {
              className: `${headerEl.props.className || ''} ${extraClasses}`.trim(),
              style: { ...headerEl.props.style, ...style }
            });
          }
          return null;
        })}
        {hasItems && <th className="pos-sticky-header"></th>}
      </tr>
    </thead>
  )
}
