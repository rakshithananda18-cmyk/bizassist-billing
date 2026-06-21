// components/sales/CartEmptyRows.jsx
// ==================================
// The blank filler rows shown in the POS cart when no items are added yet (keeps
// the table at a stable height). Extracted VERBATIM from Sales.jsx (R5, CartTable
// slice 2): pure presentational. Returns a fragment of <tr> so it sits directly
// inside the existing <tbody>.
export default function CartEmptyRows({ rowCount, columnOrder, colVisible, stickyOffsets }) {
  return (
    <>
      {Array.from({ length: rowCount }).map((_, idx) => (
        <tr key={`empty-${idx}`} style={{ height: '35px' }}>
          <td style={{ position: 'sticky', left: 0, background: 'var(--bg-2)' }}></td>
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
            const style = { background: 'var(--bg-2)' };
            if (isSticky) {
              style.position = 'sticky';
              style.left = stickyOffsets[col];
              if (col === 'name') {
                style.borderRight = '1px solid var(--border)';
                style.boxShadow = '4px 0 4px -2px rgba(0,0,0,0.1)';
              }
            }
            return <td key={col} className={`col-${col}`} style={style}></td>;
          })}
        </tr>
      ))}
    </>
  )
}
