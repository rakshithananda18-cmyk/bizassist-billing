// components/sales/CartFooterRow.jsx
// ==================================
// The POS cart table's sticky footer: the "COLUMN TOTALS" row (summed qty,
// pre-tax total, discount, GST, grand total). Extracted VERBATIM from Sales.jsx
// (R5, CartTable slice 4 — final). Pure presentational; returns a <tfoot> so it
// sits inside the existing <table>. The caller still gates it on items > 0.
import React from 'react'
import { fmt } from '../../utils/format'

export default function CartFooterRow({ columnOrder, colVisible, stickyOffsets, colFooter, gstAmt, grandTotal }) {
  return (
    <tfoot>
      <tr className="pos-cart-foot">
        <td style={{
          position: 'sticky',
          left: 0,
          bottom: 0,
          zIndex: 12,
          background: 'var(--bg-3)',
          fontWeight: 600,
          borderTop: '1px solid var(--border)'
        }}></td>
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
            bottom: 0,
            zIndex: isSticky ? 12 : 10,
            background: 'var(--bg-3)',
            fontWeight: 600,
            borderTop: '1px solid var(--border)'
          };
          if (isSticky) {
            style.left = stickyOffsets[col];
          }
          const renderFoot = () => {
            if (col === 'name')     return <td key="name" style={{ ...style, fontSize: '0.75rem', fontWeight: 'bold', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>COLUMN TOTALS</td>;
            if (col === 'qty')      return <td key="qty" style={{ ...style, textAlign: 'center' }}>{colFooter.qty}</td>;
            if (col === 'price')    return <td key="price" style={{ ...style, textAlign: 'right' }}>{fmt(colFooter.total)}</td>;
            if (col === 'discount') return <td key="discount" style={{ ...style, textAlign: 'right' }}>{fmt(colFooter.discount)}</td>;
            if (col === 'tax')      return <td key="tax" style={{ ...style, textAlign: 'center' }}>{fmt(gstAmt)}</td>;
            if (col === 'total')    return <td key="total" style={{ ...style, textAlign: 'right' }}>{fmt(grandTotal)}</td>;
            return <td key={col} style={style}></td>;
          };
          const footEl = renderFoot();
          if (footEl) {
            return React.cloneElement(footEl, { className: `${footEl.props.className || ''} col-${col}`.trim() });
          }
          return null;
        })}
        <td style={{
          position: 'sticky',
          bottom: 0,
          zIndex: 10,
          background: 'var(--bg-3)',
          borderTop: '1px solid var(--border)'
        }}></td>
      </tr>
    </tfoot>
  )
}
