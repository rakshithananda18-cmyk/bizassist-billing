// components/sales/PosSettingsModals.jsx
// ======================================
// The two POS leaf modals extracted VERBATIM from Sales.jsx (R5 decomposition):
//   • <PosCounterSettingsModal>  — the gear modal: UPI VPA, merchant state,
//     visible columns, column reorder, inline hotkey picks, advanced settings.
//   • <PosHotkeyModal>           — the dedicated "Configure POS Hotkeys" modal.
// Presentational: state + setters are passed in; localStorage writes stay inline
// (it's global), so behaviour is unchanged.

export function PosCounterSettingsModal({
  onClose,
  upiVpa, setUpiVpa,
  merchantState, setMerchantState,
  settings,
  onToggleColumn,
  columnOrder, colVisible, colLabels, onMoveColumn,
  funcKeys, setFuncKeys,
  onAdvancedSettings,
}) {
  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 450 }}>
        <div className="modal-header">
          <span className="modal-title" style={{ color: '#0f172a', fontWeight: 700 }}><SettingsIcon size={16} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> POS Counter Settings</span>
          <button className="btn btn-ghost btn-icon" onClick={onClose} style={{ color: '#64748b' }} aria-label="Close"><CloseIcon size={16} /></button>
        </div>
        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={{ fontSize: '0.75rem', fontWeight: 700, color: '#334155' }}>Your UPI ID (VPA) for Collections</label>
            <input
              type="text"
              className="pos-form-input"
              style={{ height: 35, fontSize: '0.85rem', padding: '4px 8px', border: '1px solid #cbd5e1', borderRadius: '4px' }}
              placeholder="e.g. name@upi"
              value={upiVpa}
              onChange={e => {
                setUpiVpa(e.target.value)
                localStorage.setItem('pos_upi_vpa', e.target.value)
              }}
            />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={{ fontSize: '0.75rem', fontWeight: 700, color: '#334155' }}>Merchant GST State Code</label>
            <select
              className="pos-form-select"
              style={{ height: 35, fontSize: '0.85rem', padding: '4px 8px', border: '1px solid #cbd5e1', borderRadius: '4px' }}
              value={merchantState}
              onChange={e => {
                setMerchantState(e.target.value)
                localStorage.setItem('pos_merchant_state', e.target.value)
              }}
            >
              <option value="37">37 - Andhra Pradesh (AP)</option>
              <option value="29">29 - Karnataka (KA)</option>
              <option value="33">33 - Tamil Nadu (TN)</option>
              <option value="27">27 - Maharashtra (MH)</option>
              <option value="07">07 - Delhi (DL)</option>
              <option value="09">09 - Uttar Pradesh (UP)</option>
              <option value="19">19 - West Bengal (WB)</option>
            </select>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 4 }}>
            <label style={{ fontSize: '0.75rem', fontWeight: 700, color: '#334155', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Visible Columns</label>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 16px', background: '#f8fafc', padding: '12px', borderRadius: '6px', border: '1px solid #e2e8f0' }}>
              {[
                { label: 'Item SKU/Code', key: 'pos_show_sku', toggleable: true },
                { label: 'Item Name', key: 'name', toggleable: false },
                { label: 'Batch Selector', key: 'pos_show_batch', toggleable: true },
                { label: 'Price Option', key: 'price_option', toggleable: false },
                { label: 'MRP', key: 'pos_show_mrp', toggleable: true },
                { label: 'HSN/SAC Code', key: 'pos_show_hsn', toggleable: true },
                { label: 'Quantity', key: 'qty', toggleable: false },
                { label: 'Unit', key: 'pos_show_unit', toggleable: true },
                { label: 'Price Per Unit Before Tax', key: 'rate', toggleable: false },
                { label: 'Total Before Tax', key: 'price', toggleable: false },
                { label: 'Discount', key: 'pos_show_discount', toggleable: true },
                { label: 'Tax', key: 'pos_show_tax', toggleable: true },
                { label: 'Total After Tax', key: 'total', toggleable: false }
              ].map(col => {
                const checkedVal = !col.toggleable
                  ? true
                  : (col.key === 'pos_show_hsn' || col.key === 'pos_show_mrp'
                      ? settings?.transactions?.[col.key] === true
                      : settings?.transactions?.[col.key] !== false);
                return (
                  <label key={col.key} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.8rem', fontWeight: 600, color: '#334155', cursor: col.toggleable ? 'pointer' : 'not-allowed', opacity: col.toggleable ? 1 : 0.6 }}>
                    <input
                      type="checkbox"
                      checked={checkedVal}
                      disabled={!col.toggleable}
                      onChange={e => col.toggleable && onToggleColumn(col.key, e.target.checked)}
                      style={{ accentColor: 'var(--accent)', width: 14, height: 14 }}
                    />
                    {col.label}
                  </label>
                );
              })}
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 4 }}>
            <label style={{ fontSize: '0.75rem', fontWeight: 700, color: '#334155', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Rearrange Columns</label>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, background: '#f8fafc', padding: '12px', borderRadius: '6px', border: '1px solid #e2e8f0', maxHeight: '200px', overflowY: 'auto' }}>
              {columnOrder.map((col, idx) => {
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

                return (
                  <div key={col} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 8px', background: isVisible ? '#ffffff' : '#f1f5f9', border: '1px solid #e2e8f0', borderRadius: '4px', opacity: isVisible ? 1 : 0.6 }}>
                    <span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#334155' }}>
                      {colLabels[col]} {!isVisible && <span style={{ fontSize: '0.7rem', color: '#94a3b8' }}>(Hidden)</span>}
                    </span>
                    <div style={{ display: 'flex', gap: 4 }}>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        style={{ padding: '2px 6px', fontSize: '0.75rem', border: '1px solid #cbd5e1' }}
                        disabled={idx === 0}
                        onClick={() => onMoveColumn(idx, 'up')}
                      >
                        ▲
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        style={{ padding: '2px 6px', fontSize: '0.75rem', border: '1px solid #cbd5e1' }}
                        disabled={idx === columnOrder.length - 1}
                        onClick={() => onMoveColumn(idx, 'down')}
                      >
                        ▼
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 4 }}>
            <label style={{ fontSize: '0.75rem', fontWeight: 700, color: '#334155', textTransform: 'uppercase', letterSpacing: '0.05em' }}>POS Hotkey Settings</label>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, background: '#f8fafc', padding: '12px', borderRadius: '6px', border: '1px solid #e2e8f0', maxHeight: '180px', overflowY: 'auto' }}>
              {[
                { label: 'Change Quantity', key: 'qtyFocus' },
                { label: 'Item Discount', key: 'discountFocus' },
                { label: 'Remove Item', key: 'removeItem' },
                { label: 'Receive Amount / Pay', key: 'amountReceivedFocus' },
                { label: 'Search Item / Barcode', key: 'barcodeFocus' },
                { label: 'Select Customer', key: 'customerFocus' },
                { label: 'Remarks / Notes', key: 'remarksFocus' },
                { label: 'Configure Shortcuts', key: 'configureShortcuts' },
                { label: 'Proceed Payment / Save', key: 'paymentProceed' },
                { label: 'Cancel Payment / Close', key: 'paymentCancel' },
                { label: '⏩ Flow: Move FORWARD', key: 'flowForward', isFlow: true },
                { label: '⏪ Flow: Move BACK', key: 'flowBack', isFlow: true },
              ].map(item => (
                <div key={item.key} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 8px', background: item.isFlow ? '#eff6ff' : '#ffffff', border: item.isFlow ? '1px solid #bfdbfe' : '1px solid #e2e8f0', borderRadius: '4px' }}>
                  <span style={{ fontSize: '0.78rem', fontWeight: 600, color: item.isFlow ? '#1d4ed8' : '#334155' }}>{item.label}</span>
                  <select
                    className="pos-form-select"
                    style={{ width: '120px', height: '26px', padding: '2px 4px', fontSize: '0.75rem' }}
                    value={funcKeys[item.key] || ''}
                    onChange={e => {
                      const nextKeys = { ...funcKeys, [item.key]: e.target.value }
                      setFuncKeys(nextKeys)
                      localStorage.setItem('pos_func_keys', JSON.stringify(nextKeys))
                    }}
                  >
                    {(item.isFlow
                      ? ['Enter', 'Shift+Enter', 'Tab', 'F5', 'F6', 'F7']
                      : ['F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12', 'Enter', 'Escape']
                    ).map(k => (
                      <option key={k} value={k}>{k}</option>
                    ))}
                  </select>
                </div>
              ))}
            </div>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 14, borderTop: '1px solid #e2e8f0', paddingTop: 12 }}>
            <button
              type="button"
              className="btn btn-ghost"
              style={{ color: 'var(--accent)', fontWeight: 600, fontSize: '0.85rem', padding: '6px 0' }}
              onClick={onAdvancedSettings}
            >
              Advanced Settings <ChevronRightIcon size={14} style={{ marginLeft: 4, display: 'inline-block', verticalAlign: 'middle' }} />
            </button>
            <button type="button" className="btn btn-secondary btn-sm" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export function PosHotkeyModal({ onClose, funcKeys, setFuncKeys, defaultFuncKeys }) {
  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 450 }}>
        <div className="modal-header">
          <span className="modal-title" style={{ color: '#0f172a', fontWeight: 700, display: 'inline-flex', alignItems: 'center', gap: 6 }}><KeyboardIcon size={18} /> Configure POS Hotkeys</span>
          <button className="btn btn-ghost btn-icon" onClick={onClose} style={{ color: '#64748b' }} aria-label="Close"><CloseIcon size={16} /></button>
        </div>
        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <p style={{ fontSize: '0.8rem', color: '#64748b', marginBottom: 2 }}>
            Select key mappings from the dropdown options below to customize your counter shortcuts.
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxHeight: '340px', overflowY: 'auto', paddingRight: '4px' }}>
            {/* Flow navigation keys — highlighted section */}
            <div style={{ background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: '8px', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={{ fontSize: '0.7rem', fontWeight: 700, color: '#1d4ed8', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2, display: 'inline-flex', alignItems: 'center', gap: 4 }}><KeyboardIcon size={12} /> Payment Flow Navigation</div>
              {[
                {
                  label: (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                      <CartIcon size={14} /> &rarr; <CashIcon size={14} /> Proceed to Payment
                    </span>
                  ),
                  key: 'proceedToPayment',
                  hint: 'From barcode scanner → start payment (goes to Customer Name)',
                  options: ['Escape', 'F5', 'F6', 'F7', 'F10', 'Enter'],
                  highlight: '#f97316',
                },
                { label: 'Move FORWARD (field by field)', key: 'flowForward', hint: 'Customer → Amount → Payment Mode → Confirm', options: ['Enter', 'Shift+Enter', 'Tab', 'F5', 'F6', 'F7'] },
                { label: 'Move BACK (go back one field)', key: 'flowBack', hint: 'Payment Mode → Amount → Customer → Barcode', options: ['Shift+Enter', 'Enter', 'Tab', 'F5', 'F6', 'F7'] },
              ].map(item => (
                <div key={item.key}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: '0.82rem', fontWeight: 700, color: item.highlight || '#1d4ed8' }}>{item.label}</span>
                    <select
                      className="pos-form-select"
                      style={{ width: '130px', height: '28px', padding: '2px 4px', fontSize: '0.8rem', borderColor: item.highlight ? '#fed7aa' : '#bfdbfe' }}
                      value={funcKeys[item.key] || ''}
                      onChange={e => {
                        const nextKeys = { ...funcKeys, [item.key]: e.target.value }
                        setFuncKeys(nextKeys)
                        localStorage.setItem('pos_func_keys', JSON.stringify(nextKeys))
                      }}
                    >
                      {item.options.map(k => (
                        <option key={k} value={k}>{k}</option>
                      ))}
                    </select>
                  </div>
                  <div style={{ fontSize: '0.68rem', color: '#64748b', marginTop: 2 }}>{item.hint}</div>
                </div>
              ))}
            </div>

            {/* Other function keys */}
            {[
              { label: 'Change Quantity', key: 'qtyFocus' },
              { label: 'Item Discount', key: 'discountFocus' },
              { label: 'Remove Item', key: 'removeItem' },
              { label: 'Receive Amount / Pay', key: 'amountReceivedFocus' },
              { label: 'Search Item / Barcode', key: 'barcodeFocus' },
              { label: 'Select Customer', key: 'customerFocus' },
              { label: 'Remarks / Notes', key: 'remarksFocus' },
              { label: 'Configure Shortcuts', key: 'configureShortcuts' },
              { label: 'Proceed Payment / Save', key: 'paymentProceed' },
              { label: 'Cancel Payment / Close', key: 'paymentCancel' }
            ].map(item => (
              <div key={item.key} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#f8fafc', padding: '8px 12px', borderRadius: '6px', border: '1px solid #e2e8f0' }}>
                <span style={{ fontSize: '0.82rem', fontWeight: 600, color: '#334155' }}>{item.label}</span>
                <select
                  className="pos-form-select"
                  style={{ width: '110px', height: '28px', padding: '2px 4px', fontSize: '0.8rem' }}
                  value={funcKeys[item.key] || ''}
                  onChange={e => {
                    const nextKeys = { ...funcKeys, [item.key]: e.target.value }
                    setFuncKeys(nextKeys)
                    localStorage.setItem('pos_func_keys', JSON.stringify(nextKeys))
                  }}
                >
                  {['F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12', 'Enter', 'Escape'].map(k => (
                    <option key={k} value={k}>{k}</option>
                  ))}
                </select>
              </div>
            ))}
          </div>

          <div style={{ borderTop: '1px solid #e2e8f0', margin: '4px 0' }} />
          <label style={{ fontSize: '0.75rem', fontWeight: 700, color: '#334155', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Standard Control Shortcuts</label>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 16px', background: '#f8fafc', padding: '12px', borderRadius: '6px', border: '1px solid #e2e8f0' }}>
            {[
              { label: 'Save & Print Bill', key: 'Ctrl+P' },
              { label: 'Save Bill Only', key: 'Ctrl+S' },
              { label: 'New Active Tab', key: 'Ctrl+T' },
              { label: 'Close Active Tab', key: 'Ctrl+W' },
              { label: 'Toggle Breakup', key: 'Ctrl+F' },
              { label: 'Credit Payment', key: 'Ctrl+M' }
            ].map(item => (
              <div key={item.label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '0.75rem', fontWeight: 600, color: '#475569' }}>{item.label}</span>
                <span style={{ fontSize: '0.7rem', fontWeight: 700, color: '#475569', background: '#e2e8f0', padding: '1px 6px', borderRadius: '4px' }}>{item.key}</span>
              </div>
            ))}
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 14, borderTop: '1px solid #e2e8f0', paddingTop: 12 }}>
            <button
              type="button"
              className="btn btn-ghost"
              style={{ color: 'var(--accent)', fontWeight: 600, fontSize: '0.82rem', padding: '6px 0' }}
              onClick={() => {
                setFuncKeys(defaultFuncKeys);
                localStorage.setItem('pos_func_keys', JSON.stringify(defaultFuncKeys));
              }}
            >
              Reset Defaults
            </button>
            <button type="button" className="btn btn-secondary btn-sm" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

import { CartIcon, CashIcon, ChevronRightIcon, CloseIcon, SettingsIcon, KeyboardIcon } from '../../components/Icons'