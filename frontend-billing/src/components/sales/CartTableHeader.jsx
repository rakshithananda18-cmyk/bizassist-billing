// components/sales/CartTableHeader.jsx
// ====================================
// The POS cart table's <thead> — column headers in the owner's chosen order with
// sticky positioning. Extracted VERBATIM from Sales.jsx (R5, first safe slice of
// CartTable): pure presentational, no handlers/refs. Returns a <thead> so it sits
// directly inside the existing <table className="pos-cart-table">.
import React from 'react'
import { colLabels, colShortLabels, NON_COLLAPSIBLE } from '../../lib/posColumns'

// collapsedCols: { [col]: true } — fold-collapsed columns render as a narrow
// strip; click expands. onHeaderContextMenu(col, event) opens the fold menu.
export default function CartTableHeader({ columnOrder, colVisible, stickyOffsets, t, hasItems, extraAttrFields = [], collapsedCols = {}, onExpandColumn, onHeaderContextMenu }) {
  return (
    <thead>
      <tr>
        <th className="pos-header-index">#</th>
        {columnOrder.map(col => {
          const isVisible = col === 'attrs' ? colVisible.attrs :
                            col === 'sku' ? colVisible.sku :
                            col === 'mrp' ? colVisible.mrp :
                            col === 'mrp_total' ? colVisible.mrp_total :
                            col === 'hsn' ? colVisible.hsn :
                            col === 'unit' ? colVisible.unit :
                            col === 'discount_unit' ? colVisible.discount_unit :
                            col === 'discount' ? colVisible.discount :
                            col === 'tax' ? colVisible.tax :
                            col === 'batch' ? colVisible.batch :
                            col === 'serial' ? colVisible.serial :
                            col === 'price_option' ? colVisible.price_option :
                            col === 'rate' ? colVisible.rate :
                            true;
          if (!isVisible) return null;

          const isSticky = stickyOffsets[col] !== undefined;
          const style = isSticky ? { left: stickyOffsets[col] } : {};

          // Fold-collapsed → narrow strip; click to unfold.
          if (collapsedCols[col] && !NON_COLLAPSIBLE.includes(col)) {
            return (
              <th
                key={col}
                className={`pos-col-collapsed col-${col} ${isSticky ? 'pos-sticky-header sticky-left' : 'pos-sticky-header'}`}
                style={style}
                title={`Expand "${colLabels[col] || col}"`}
                onClick={() => onExpandColumn && onExpandColumn(col)}
                onContextMenu={e => { if (onHeaderContextMenu) { e.preventDefault(); onHeaderContextMenu(col, e) } }}
              >
                <span className="pos-col-collapsed-label">{colShortLabels[col] || '›'}</span>
              </th>
            );
          }

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
            if (col === 'serial') {
              return <th key="serial">SERIAL / IMEI</th>;
            }
            if (col === 'attrs') {
              // Dynamic vertical fields (textile size/color, warranty, job card…)
              return <th key="attrs">{extraAttrFields.map(f => f.replace(/_/g, ' ').toUpperCase()).join(' / ') || 'DETAILS'}</th>;
            }
            if (col === 'price_option') {
              return <th key="price_option" className="pos-align-center">PRICE OPTION</th>;
            }
            if (col === 'mrp') {
              return <th key="mrp" className="pos-align-right">MRP (₹)</th>;
            }
            if (col === 'mrp_total') {
              return (
                <th key="mrp_total" className="pos-align-right">
                  TOTAL MRP<br/>
                  <span className="pos-text-muted" style={{ fontSize: '0.65rem', fontWeight: 'normal' }}>(₹)</span>
                </th>
              );
            }
            if (col === 'hsn') {
              return <th key="hsn" className="pos-align-center">HSN</th>;
            }
            if (col === 'qty') {
              return <th key="qty" className="pos-align-center">QTY</th>;
            }
            if (col === 'unit') {
              return <th key="unit" className="pos-align-center">UNIT</th>;
            }
            if (col === 'rate') {
              return (
                <th key="rate" className="pos-align-right">
                  PRICE PER UNIT<br/>
                  <span className="pos-text-muted" style={{ fontSize: '0.65rem', fontWeight: 'normal' }}>BEFORE TAX (₹)</span>
                </th>
              );
            }
            if (col === 'price') {
              return (
                <th key="price" className="pos-align-right">
                  TOTAL<br/>
                  <span className="pos-text-muted" style={{ fontSize: '0.65rem', fontWeight: 'normal' }}>BEFORE TAX (₹)</span>
                </th>
              );
            }
            if (col === 'discount_unit') {
              return (
                <th key="discount_unit" className="pos-align-right">
                  DISCOUNT<br/>
                  <span className="pos-text-muted" style={{ fontSize: '0.65rem', fontWeight: 'normal' }}>PER UNIT (₹)</span>
                </th>
              );
            }
            if (col === 'discount') {
              return (
                <th key="discount" className="pos-align-right">
                  TOTAL<br/>
                  <span className="pos-text-muted" style={{ fontSize: '0.65rem', fontWeight: 'normal' }}>DISCOUNT (₹)</span>
                </th>
              );
            }
            if (col === 'tax') {
              return <th key="tax" className="pos-align-center">TAX APPLIED(%)</th>;
            }
            if (col === 'total') {
              return (
                <th key="total" className="pos-align-right">
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
              style: { ...headerEl.props.style, ...style },
              onContextMenu: e => { if (onHeaderContextMenu) { e.preventDefault(); onHeaderContextMenu(col, e) } }
            });
          }
          return null;
        })}
      </tr>
    </thead>
  )
}
