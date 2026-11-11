import { useState } from 'react'
import { TourPrivateValue } from '../../demo/TourPrivatePreview'
import { EditIcon, PlusIcon } from '../Icons'
import PhoneActionMenu from '../common/PhoneActionMenu'

export default function StockPhoneCatalogue({ products, selection, onToggle, onToggleAll, allSelected, someSelected, onIntake, onEdit, getStatus, derive, num, pct, protectTour, getActions }) {
  const [expanded, setExpanded] = useState(null)
  if (!products.length) return <div className="empty-state"><h3>No products found</h3><p>Try another search or filter.</p></div>
  return (
    <div className="stock-phone-catalogue">
      <div className="stock-phone-list-heading">
        <label><input type="checkbox" aria-label="Select all products" checked={allSelected} ref={el => { if (el) el.indeterminate = someSelected }} onChange={onToggleAll} /><span>{products.length} items</span></label>
        <span>Stock · selling price</span>
      </div>
      {products.map(product => {
        const status = getStatus(product)
        const values = derive(product)
        const show = expanded === product.id
        const privateValue = value => protectTour ? <TourPrivateValue /> : value
        const details = [
          ['Code', product.sku || '—'], ['Barcode', product.barcode || '—'], ['HSN', product.hsn_sac || '—'],
          ['MRP', num(values.mrp || null)], ['Cost', privateValue(num(values.cost || null))],
          ['Wholesale', privateValue(product.wholesale_price > 0 ? num(product.wholesale_price) : '—')],
          ['Distributor', privateValue(product.distributor_price > 0 ? num(product.distributor_price) : '—')],
          ['GST', values.gst ? `${values.gst.toFixed(0)}%` : '—'], ['Discount', pct(values.discPct)],
          ['ROI', privateValue(pct(values.roi))], ['Margin', privateValue(pct(values.profit))],
          ['Net cost', privateValue(num(values.netCost))], ['Net MRP', privateValue(num(values.netMrp))],
        ]
        return <article key={product.id} className={`stock-phone-item stock-phone-item--${status === 'Out' ? 'out' : status === 'Low' ? 'low' : 'available'}`}>
          <div className="stock-phone-item-top">
            <input type="checkbox" aria-label={`Select ${product.name}`} checked={selection.has(product.id)} onChange={() => onToggle(product.id)} />
            <div className="stock-phone-item-title"><strong>{product.name}</strong><span>{product.is_active === false ? 'Inactive · ' : ''}{product.sku || 'No item code'}</span></div>
            <span className={`stock-phone-status ${status !== 'In Stock' ? 'is-alert' : ''}`}>{status === 'Out' ? 'Out' : status === 'Low' ? 'Low' : 'In stock'}</span>
          </div>
          <div className="stock-phone-item-facts">
            <span><b>{product.stock_qty ?? product.quantity ?? 0}</b> {product.unit || 'pcs'}<small>{product.min_stock > 0 ? `Min ${product.min_stock}` : 'On hand'}</small></span>
            <span><b>₹{num(values.sell || null)}</b><small>Selling price</small></span>
          </div>
          <div className="stock-phone-item-actions">
            <button type="button" onClick={() => setExpanded(show ? null : product.id)} aria-expanded={show} aria-label={`${show ? 'Hide' : 'Show'} details for ${product.name}`}>{show ? 'Less details' : 'Details'}<span aria-hidden="true">{show ? '−' : '+'}</span></button>
            <button type="button" aria-label={`Edit ${product.name}`} onClick={() => onEdit(product)}><EditIcon size={15} />Edit</button>
            <button type="button" className="stock-phone-receive" aria-label={`Receive stock for ${product.name}`} onClick={() => onIntake(product)}><PlusIcon size={15} />Receive</button>
            <PhoneActionMenu label={`Actions for ${product.name}`} actions={getActions(product)} />
          </div>
          {show && <dl className="stock-phone-item-details">{details.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>}
        </article>
      })}
    </div>
  )
}
