// components/sales/CartItemRow.jsx
// ================================
// One row of the POS cart table: per-column cells incl. the editable qty / rate /
// (custom) name / tax inputs, batch + price-option selectors, and the remove
// button. Extracted VERBATIM from Sales.jsx (R5, CartTable slice 3).
//
// IMPORTANT: keyboard cell-navigation in Sales.jsx focuses inputs by DOM query
// (`.pos-cart-table tbody tr input.qty-input`, `input.rate-input`, …), NOT React
// refs — so the input classNames here MUST stay identical for F-key nav to work.
// Returns a <tr> so it sits directly inside the existing <tbody>.
import React from 'react'
import { AlertIcon, CloseIcon } from '../../components/Icons'
import { fmt } from '../../utils/format'
import { lineTotal } from '../../utils/invoiceMath'

export default function CartItemRow({
  item,
  index,
  columnOrder,
  colVisible,
  stickyOffsets,
  products,
  productBatches,
  setProductBatches,
  isIntrastate,
  setItem,
  onQtyChange,
  onRemove,
  setForm,
  getPriceOptions,
  authFetch,
  logger,
}) {
  return (
    <tr className="item-row">
      <td style={{
        position: 'sticky',
        left: 0,
        zIndex: 2,
        background: 'var(--bg-2)',
        fontWeight: 600,
        color: 'var(--text-muted)'
      }}>{index + 1}</td>
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
          zIndex: isSticky ? 2 : undefined,
          background: 'var(--bg-2)',
        };
        if (isSticky) {
          style.position = 'sticky';
          style.left = stickyOffsets[col];
          if (col === 'name') {
            style.borderRight = '1px solid var(--border)';
            style.boxShadow = '4px 0 4px -2px rgba(0,0,0,0.1)';
            style.textAlign = 'left';
          }
        }

        const renderCell = () => {
          if (col === 'sku') {
            return (
              <td key="sku" style={style}>
                <span className="pos-cell-text" style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                  {item.sku || '—'}
                </span>
              </td>
            );
          }

          if (col === 'name') {
            return (
              <td key="name" style={style}>
                {item.is_custom ? (
                  <input
                    className="pos-cell-input"
                    style={{ textAlign: 'left' }}
                    placeholder="Type item name…"
                    value={item.product}
                    onChange={e => setItem(index, 'product', e.target.value)}
                    required
                  />
                ) : (
                  <div>
                    <span className="pos-cell-text">{item.product}</span>
                  </div>
                )}
              </td>
            );
          }

          if (col === 'batch') {
            return (
              <td key="batch" style={{ ...style, textAlign: 'center', padding: '4px 8px' }}>
                {item.product_id ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'center', justifyContent: 'center' }}>
                    <select
                      style={{ fontSize: '0.72rem', padding: '2px 4px', border: '1px solid var(--border)', borderRadius: '4px', background: 'var(--bg-3)', color: 'var(--text-primary)', maxWidth: '130px', textOverflow: 'ellipsis' }}
                      value={item.batch_no || ''}
                      onChange={e => {
                        const selectedBatchNo = e.target.value
                        const batches = productBatches[item.product_id] || []
                        const found = batches.find(b => b.batch_no === selectedBatchNo)
                        setItem(index, {
                          batch_no: selectedBatchNo,
                          expiry_date: found ? found.expiry_date : ''
                        })
                      }}
                    >
                      <option value="">-- Select Batch --</option>
                      {(productBatches[item.product_id] || []).map(b => (
                        <option key={b.batch_no} value={b.batch_no}>
                          {b.batch_no || 'No Batch'} ({b.godown_name || 'Main'}) - Stock: {b.stock} {b.expiry_date ? `(Exp: ${b.expiry_date})` : ''}
                        </option>
                      ))}
                    </select>
                    {item.expiry_date && (
                      (() => {
                        const today = new Date()
                        const expDate = new Date(item.expiry_date)
                        const diffTime = expDate - today
                        const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24))
                        if (diffDays <= 0) {
                          return <span style={{ fontSize: '0.68rem', color: 'var(--danger)', fontWeight: 600, display: 'block' }}><AlertIcon size={10} style={{ display: 'inline', marginRight: 2, verticalAlign: 'middle' }} />Expired!</span>
                        } else if (diffDays <= 30) {
                          return <span style={{ fontSize: '0.68rem', color: 'var(--warning)', fontWeight: 600, display: 'block' }}><AlertIcon size={10} style={{ display: 'inline', marginRight: 2, verticalAlign: 'middle' }} />Expiring in {diffDays} days</span>
                        }
                        return <span style={{ fontSize: '0.68rem', color: 'var(--success)', display: 'block' }}>Expires: {item.expiry_date}</span>
                      })()
                    )}
                  </div>
                ) : (
                  <span style={{ color: 'var(--text-muted)' }}>—</span>
                )}
              </td>
            );
          }

          if (col === 'price_option') {
            const opts = getPriceOptions(item)
            return (
              <td key="price_option" style={{ ...style, textAlign: 'center', padding: '4px 8px' }}>
                {item.product_id ? (
                  <select
                    style={{ fontSize: '0.72rem', padding: '2px 4px', border: '1px solid var(--border)', borderRadius: '4px', background: 'var(--bg-3)', color: 'var(--text-primary)', maxWidth: '145px', textOverflow: 'ellipsis' }}
                    value={item.selected_price_label || 'Standard Price'}
                    onFocus={async () => {
                      try {
                        const res = await authFetch(`/products/${item.product_id}/stock`)
                        if (res.ok) {
                          const data = await res.json()
                          setProductBatches(prev => ({
                            ...prev,
                            [item.product_id]: data.batches || []
                          }))
                        }
                      } catch (err) {
                        logger.error('[SALES] failed to update batches', err)
                      }
                    }}
                    onChange={e => {
                      const selectedLabel = e.target.value
                      const selectedOpt = opts.find(o => o.label === selectedLabel)
                      if (selectedOpt) {
                        const pVal = parseFloat(selectedOpt.price) || 0
                        setItem(index, {
                          selected_price: pVal,
                          selected_price_label: selectedLabel
                        })
                      }
                    }}
                  >
                    {opts.map(opt => (
                      <option key={opt.label} value={opt.label}>
                        {opt.label} (₹{opt.price})
                      </option>
                    ))}
                    {item.selected_price_label === 'Custom Price' && (
                      <option value="Custom Price">Custom Price (₹{parseFloat(item.selected_price || item.price).toFixed(2)})</option>
                    )}
                  </select>
                ) : (
                  <span style={{ color: 'var(--text-muted)' }}>—</span>
                )}
              </td>
            );
          }

          if (col === 'mrp') {
            return (
              <td key="mrp" style={{ ...style, textAlign: 'right' }}>
                <span className="pos-cell-text" style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                  {fmt(item.mrp || products.find(p => p.id === item.product_id)?.mrp || 0)}
                </span>
              </td>
            );
          }

          if (col === 'hsn') {
            return (
              <td key="hsn" style={{ ...style, textAlign: 'center' }}>
                <span className="pos-cell-text" style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                  {products.find(p => p.id === item.product_id)?.hsn || '—'}
                </span>
              </td>
            );
          }

          if (col === 'qty') {
            return (
              <td key="qty" style={style}>
                <input
                  type="number"
                  min="0.01"
                  step="any"
                  className="pos-cell-input qty-input"
                  value={item.qty}
                  onChange={e => onQtyChange(index, e.target.value)}
                  required
                />
              </td>
            );
          }

          if (col === 'unit') {
            return (
              <td key="unit" style={{ ...style, textAlign: 'center', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)' }}>
                pcs
              </td>
            );
          }

          if (col === 'rate') {
            const currentRate = parseFloat(item.price) || 0
            return (
              <td key="rate" style={style}>
                {item.product_id || item.is_custom ? (
                  <input
                    type="number"
                    min="0"
                    step="any"
                    className="pos-cell-input rate-input"
                    style={{ textAlign: 'right', fontWeight: 600, color: 'var(--primary)' }}
                    value={isNaN(currentRate) ? '' : parseFloat(currentRate.toFixed(2))}
                    onChange={e => {
                      const newRate = parseFloat(e.target.value) || 0
                      setItem(index, {
                        selected_price: newRate,
                        selected_price_label: 'Custom Price'
                      })
                    }}
                  />
                ) : (
                  <span style={{ color: 'var(--text-muted)' }}>—</span>
                )}
              </td>
            );
          }

          if (col === 'price') {
            return (
              <td key="price" style={{ ...style, textAlign: 'right' }}>
                <span className="pos-cell-text" style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                  {item.product ? fmt(lineTotal(item)) : '—'}
                </span>
              </td>
            );
          }

          if (col === 'discount') {
            return (
              <td key="discount" style={style}>
                {item.product_id || item.is_custom ? (
                  <input
                    type="number"
                    min="0"
                    step="any"
                    className="pos-cell-input discount-input"
                    style={{ textAlign: 'right', color: 'var(--text-secondary)' }}
                    value={parseFloat(item.discount) || 0}
                    onChange={e => {
                      const newDisc = parseFloat(e.target.value) || 0
                      setItem(index, 'discount', newDisc)
                    }}
                  />
                ) : (
                  <span style={{ color: 'var(--text-muted)' }}>—</span>
                )}
              </td>
            );
          }

          if (col === 'tax') {
            const cgstRate = parseFloat(item.cgst_rate) || 0
            const sgstRate = parseFloat(item.sgst_rate) || 0
            const igstRate = item.igst_rate ? parseFloat(item.igst_rate) : (cgstRate + sgstRate)
            const totalRate = isIntrastate ? (cgstRate + sgstRate) : igstRate
            return (
              <td key="tax" style={{ ...style, textAlign: 'center', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                {item.is_custom ? (
                  <input
                    type="number"
                    min="0"
                    max="100"
                    className="pos-cell-input"
                    style={{ textAlign: 'center', width: '60px' }}
                    value={totalRate || ''}
                    onChange={e => {
                      const rate = parseFloat(e.target.value) || 0
                      setForm(f => {
                        const items = [...f.items]
                        if (items[index]) {
                          items[index] = {
                            ...items[index],
                            cgst_rate: rate / 2,
                            sgst_rate: rate / 2,
                            igst_rate: rate
                          }
                        }
                        return { ...f, items }
                      })
                    }}
                  />
                ) : (
                  <span>{totalRate > 0 ? `${totalRate}% · ${fmt(lineTotal(item) * totalRate / 100)}` : '0%'}</span>
                )}
              </td>
            );
          }

          if (col === 'total') {
            const cgstR = parseFloat(item.cgst_rate) || 0
            const sgstR = parseFloat(item.sgst_rate) || 0
            const igstR = item.igst_rate ? parseFloat(item.igst_rate) : (cgstR + sgstR)
            const rate = isIntrastate ? (cgstR + sgstR) : igstR
            const totalAfterTax = lineTotal(item) * (1 + rate / 100)
            return (
              <td key="total" style={{ ...style, textAlign: 'right', fontWeight: 700, fontSize: '0.85rem', color: 'var(--text-primary)' }}>
                {item.product ? fmt(totalAfterTax) : '—'}
              </td>
            );
          }

          return null;
        };
        const cellEl = renderCell();
        if (cellEl) {
          return React.cloneElement(cellEl, { className: `${cellEl.props.className || ''} col-${col}`.trim() });
        }
        return null;
      })}
      <td style={{ textAlign: 'center' }}>
        <button
          type="button"
          className="btn btn-ghost btn-icon btn-sm"
          onClick={() => onRemove(index)}
          style={{ color: 'var(--danger)', padding: 4 }}
         aria-label="Close"><CloseIcon size={16} /></button>
      </td>
    </tr>
  )
}
