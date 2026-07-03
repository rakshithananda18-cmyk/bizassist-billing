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
import CustomSelect from '../../components/common/CustomSelect'

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
  extraAttrFields = [],
}) {
  return (
    <tr className="item-row">
      <td className="pos-sticky-index pos-hover-remove-cell" onClick={() => onRemove(index)} style={{ cursor: 'pointer', textAlign: 'center' }} title="Click to remove">
        <span className="index-number">{index + 1}</span>
        <button
          type="button"
          className="btn btn-ghost btn-icon btn-sm pos-delete-btn-hover"
          aria-label="Remove item"
          tabIndex="-1"
          style={{ padding: 0, height: 24, width: 24 }}
        >
          <CloseIcon size={14} color="var(--error)" />
        </button>
      </td>
      {columnOrder.map(col => {
        const isVisible = col === 'attrs' ? colVisible.attrs :
                          col === 'sku' ? colVisible.sku :
                          col === 'mrp' ? colVisible.mrp :
                          col === 'hsn' ? colVisible.hsn :
                          col === 'unit' ? colVisible.unit :
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

        const renderCell = () => {
          if (col === 'sku') {
            return (
              <td key="sku">
                <span className="pos-cell-text pos-cell-secondary-text">
                  {item.sku || '—'}
                </span>
              </td>
            );
          }

          if (col === 'name') {
            return (
              <td key="name">
                {item.is_custom ? (
                  <input
                    className="pos-cell-input pos-align-left"
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
              <td key="batch" className="pos-align-center pos-cell-padded">
                {item.product_id ? (
                  <div className="pos-flex-col-center">
                    <CustomSelect
                      className="pos-dropdown-select pos-batch-select"
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
                    </CustomSelect>
                    {item.expiry_date && (
                      (() => {
                        const today = new Date()
                        const expDate = new Date(item.expiry_date)
                        const diffTime = expDate - today
                        const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24))
                        if (diffDays <= 0) {
                          return <span className="pos-expiry-alert expired"><AlertIcon size={10} className="pos-icon-inline" />Expired!</span>
                        } else if (diffDays <= 30) {
                          return <span className="pos-expiry-alert expiring"><AlertIcon size={10} className="pos-icon-inline" />Expiring in {diffDays} days</span>
                        }
                        return <span className="pos-expiry-alert valid">Expires: {item.expiry_date}</span>
                      })()
                    )}
                  </div>
                ) : (
                  <span className="pos-text-muted">—</span>
                )}
              </td>
            );
          }

          if (col === 'serial') {
            // Serial / IMEI capture (electronics · mobile · repair verticals).
            // Snapshots onto the invoice line (backend serial_no column) and
            // prints via the payload's serial column.
            return (
              <td key="serial" className="pos-align-center pos-cell-padded">
                <input
                  type="text"
                  className="pos-cell-input serial-input"
                  placeholder="Serial / IMEI"
                  value={item.serial_no || ''}
                  onChange={e => setItem(index, { serial_no: e.target.value })}
                  style={{ minWidth: 110 }}
                />
              </td>
            );
          }

          if (col === 'attrs') {
            // Dynamic vertical fields (textile size/color, electronics warranty,
            // repair job-card…) — packed into the line's `attributes` JSON blob;
            // presentation-only, never enters the money math.
            return (
              <td key="attrs" className="pos-align-center pos-cell-padded">
                <div className="pos-flex-col-center" style={{ gap: 4 }}>
                  {extraAttrFields.map(f => (
                    <input
                      key={f}
                      type="text"
                      className="pos-cell-input attr-input"
                      placeholder={f.replace(/_/g, ' ')}
                      value={item.attributes?.[f] || ''}
                      onChange={e => setItem(index, {
                        attributes: { ...(item.attributes || {}), [f]: e.target.value }
                      })}
                      style={{ minWidth: 90 }}
                    />
                  ))}
                </div>
              </td>
            );
          }

          if (col === 'price_option') {
            const opts = getPriceOptions(item)
            return (
              <td key="price_option" className="pos-align-center pos-cell-padded">
                {item.product_id ? (
                  <CustomSelect
                    className="pos-dropdown-select pos-price-select"
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
                  </CustomSelect>
                ) : (
                  <span className="pos-text-muted">—</span>
                )}
              </td>
            );
          }

          if (col === 'mrp') {
            return (
              <td key="mrp" className="pos-align-right">
                <span className="pos-cell-text pos-cell-secondary-text">
                  {fmt(products.find(p => p.id === item.product_id)?.mrp || item.price)}
                </span>
              </td>
            );
          }

          if (col === 'hsn') {
            return (
              <td key="hsn" className="pos-align-center">
                <span className="pos-cell-text pos-cell-secondary-text">
                  {products.find(p => p.id === item.product_id)?.hsn || '—'}
                </span>
              </td>
            );
          }

          if (col === 'qty') {
            return (
              <td key="qty">
                <input
                  type="number"
                  min="0.01"
                  step="any"
                  className="pos-cell-input qty-input pos-align-center"
                  value={item.qty}
                  onChange={e => onQtyChange(index, e.target.value)}
                  required
                />
              </td>
            );
          }

          if (col === 'unit') {
            return (
              <td key="unit" className="pos-align-center pos-text-muted" style={{ fontSize: '0.8rem', fontWeight: 600 }}>
                pcs
              </td>
            );
          }

          if (col === 'rate') {
            const currentRate = parseFloat(item.selected_price) || (parseFloat(item.price) - (parseFloat(item.discount) / (parseFloat(item.qty) || 1)))
            return (
              <td key="rate" className="pos-align-right">
                {item.product_id ? (
                  <input
                    type="number"
                    min="0"
                    step="any"
                    className="pos-cell-input rate-input pos-rate-input"
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
                  <span className="pos-text-muted">—</span>
                )}
              </td>
            );
          }

          if (col === 'price') {
            return (
              <td key="price" className="pos-align-right">
                <span className="pos-cell-text pos-cell-secondary-text">
                  {item.product ? fmt(lineTotal(item)) : '—'}
                </span>
              </td>
            );
          }

          if (col === 'discount') {
            return (
              <td key="discount" className="pos-align-right">
                <span className="pos-cell-text pos-cell-secondary-text">
                  {fmt(parseFloat(item.discount) || 0)}
                </span>
              </td>
            );
          }

          if (col === 'tax') {
            const cgstRate = parseFloat(item.cgst_rate) || 0
            const sgstRate = parseFloat(item.sgst_rate) || 0
            const igstRate = item.igst_rate ? parseFloat(item.igst_rate) : (cgstRate + sgstRate)
            const totalRate = isIntrastate ? (cgstRate + sgstRate) : igstRate
            return (
              <td key="tax" className="pos-cell-tax">
                {item.is_custom ? (
                  <input
                    type="number"
                    min="0"
                    max="100"
                    className="pos-cell-input pos-tax-input"
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
              <td key="total" className="pos-cell-total">
                {item.product ? fmt(totalAfterTax) : '—'}
              </td>
            );
          }

          return null;
        };
        const cellEl = renderCell();
        if (cellEl) {
          const extraClasses = `col-${col} ${isSticky ? 'pos-sticky-cell' : ''} ${col === 'name' && isSticky ? 'pos-sticky-cell-name' : ''}`.trim();
          return React.cloneElement(cellEl, {
            className: `${cellEl.props.className || ''} ${extraClasses}`.trim(),
            style: { ...cellEl.props.style, ...style }
          });
        }
        return null;
      })}

    </tr>
  )
}
