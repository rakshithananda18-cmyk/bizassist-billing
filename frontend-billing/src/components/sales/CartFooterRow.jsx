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
        <td className="pos-footer-index"></td>
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

          const renderFoot = () => {
            if (col === 'name')     return <td key="name" className="pos-footer-totals-label">COLUMN TOTALS</td>;
            if (col === 'qty')      return <td key="qty" className="pos-align-center">{colFooter.qty}</td>;
            if (col === 'price')    return <td key="price" className="pos-align-right">{fmt(colFooter.total)}</td>;
            if (col === 'discount') return <td key="discount" className="pos-align-right">{fmt(colFooter.discount)}</td>;
            if (col === 'tax')      return <td key="tax" className="pos-align-center">{fmt(gstAmt)}</td>;
            if (col === 'total')    return <td key="total" className="pos-align-right">{fmt(grandTotal)}</td>;
            return <td key={col}></td>;
          };
          const footEl = renderFoot();
          if (footEl) {
            const extraClasses = `col-${col} ${isSticky ? 'pos-sticky-footer sticky-left' : 'pos-sticky-footer'} ${col === 'name' && isSticky ? 'pos-sticky-cell-name' : ''}`.trim();
            return React.cloneElement(footEl, {
              className: `${footEl.props.className || ''} ${extraClasses}`.trim(),
              style: { ...footEl.props.style, ...style }
            });
          }
          return null;
        })}
        <td className="pos-sticky-footer"></td>
      </tr>
    </tfoot>
  )
}
