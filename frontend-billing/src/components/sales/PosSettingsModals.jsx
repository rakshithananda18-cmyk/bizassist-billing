import CustomSelect from '../../components/common/CustomSelect';
import React, { useState, useEffect, useRef } from 'react'
import { 
  CartIcon, 
  CashIcon, 
  ChevronRightIcon, 
  CloseIcon, 
  SettingsIcon, 
  KeyboardIcon 
} from '../../components/Icons'

export function PosCounterSettingsModal({
  onClose,
  upiVpa, setUpiVpa,
  merchantState, setMerchantState,
  settings,
  onToggleColumn,
  columnOrder, colVisible, colLabels, onMoveColumn,
  funcKeys, setFuncKeys,
  onAdvancedSettings,
  defaultFuncKeys = {},
  initialTab = 'general',
}) {
  const [activeTab, setActiveTab] = useState(initialTab)
  const [bindingKey, setBindingKey] = useState(null)
  const modalRef = useRef(null)

  // Focus trap for settings modal.
  // IMPORTANT: CustomSelect renders its option list through a portal on
  // document.body (id="custom-dropdown-…"), i.e. OUTSIDE modalRef. The old
  // trap yanked focus back to the first input the instant the dropdown (or
  // any portaled element) received focus — instantly closing the dropdown and
  // making the settings feel un-editable. Treat portaled pickers as inside,
  // and never fight a transient body focus.
  useEffect(() => {
    const focusable = modalRef.current?.querySelectorAll('input, select, button, textarea')
    if (focusable && focusable.length > 0) {
      focusable[0].focus()
    }

    const isInsidePortalPicker = (el) =>
      !!(el && el.closest && el.closest('[id^="custom-dropdown-"], .custom-select-dropdown'))

    const handleFocusIn = (e) => {
      if (!modalRef.current) return
      if (modalRef.current.contains(e.target)) return
      if (isInsidePortalPicker(e.target)) return          // portaled dropdown = inside
      if (e.target === document.body) return              // transient blur — don't fight it
      e.preventDefault()
      e.stopPropagation()
      const els = modalRef.current.querySelectorAll('input, select, button, textarea')
      if (els.length > 0) els[0].focus()
    }

    document.addEventListener('focusin', handleFocusIn)
    return () => document.removeEventListener('focusin', handleFocusIn)
  }, [])

  // Sync activeTab when initialTab prop updates
  useEffect(() => {
    setActiveTab(initialTab)
  }, [initialTab])

  // Listen to keyboard press to record new shortcut bindings
  useEffect(() => {
    if (!bindingKey) return

    const handleRecordKey = (e) => {
      e.preventDefault()
      e.stopPropagation()

      let pressedKey = e.key
      // Build modifier prefix if needed (e.g. Shift+Enter)
      const modifiers = []
      if (e.ctrlKey && pressedKey !== 'Control') modifiers.push('Ctrl')
      if (e.shiftKey && pressedKey !== 'Shift') modifiers.push('Shift')
      if (e.altKey && pressedKey !== 'Alt') modifiers.push('Alt')

      if (pressedKey.length === 1) {
        pressedKey = pressedKey.toUpperCase()
      }

      const fullKeyName = [...modifiers, pressedKey].join('+')

      const nextKeys = { ...funcKeys, [bindingKey.action]: fullKeyName }
      setFuncKeys(nextKeys)
      localStorage.setItem('pos_func_keys', JSON.stringify(nextKeys))
      setBindingKey(null)
    }

    window.addEventListener('keydown', handleRecordKey, true)
    return () => window.removeEventListener('keydown', handleRecordKey, true)
  }, [bindingKey, funcKeys, setFuncKeys])

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div ref={modalRef} className="modal" style={{ maxWidth: 480, width: '100%' }}>
        <div className="modal-header" style={{ borderBottom: '1px solid var(--border)', paddingBottom: 10 }}>
          <span className="modal-title" style={{ color: 'var(--text-primary)', fontWeight: 700, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <SettingsIcon size={18} /> POS Counter Settings
          </span>
          <button className="btn btn-ghost btn-icon" onClick={onClose} style={{ color: 'var(--text-muted)' }} aria-label="Close">
            <CloseIcon size={16} />
          </button>
        </div>

        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 14, paddingTop: 12 }}>
          {/* Modern Capsule Tab Selector */}
          <div style={{ display: 'flex', gap: 6, background: 'var(--bg-3)', padding: 4, borderRadius: 'var(--radius-md)', border: '1px solid var(--border)' }}>
            {[
              { id: 'general', label: 'General Settings' },
              { id: 'columns', label: 'Table Columns' },
              { id: 'shortcuts', label: 'Shortcuts / Keys' }
            ].map(tab => {
              const isSelected = activeTab === tab.id
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setActiveTab(tab.id)}
                  style={{
                    flex: 1,
                    padding: '6px 12px',
                    borderRadius: '4px',
                    border: 'none',
                    background: isSelected ? 'var(--bg-2)' : 'transparent',
                    color: isSelected ? 'var(--accent)' : 'var(--text-secondary)',
                    fontWeight: 700,
                    fontSize: '0.78rem',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                    textAlign: 'center',
                    boxShadow: isSelected ? 'var(--shadow-sm)' : 'none'
                  }}
                >
                  {tab.label}
                </button>
              )
            })}
          </div>

          {/* Tab Content Container */}
          <div style={{ paddingRight: 4, display: 'flex', flexDirection: 'column', gap: 14 }}>
            
            {/* GENERAL SETTINGS TAB */}
            {activeTab === 'general' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <label style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-secondary)' }}>Your UPI ID (VPA) for Collections</label>
                  <input
                    type="text"
                    className="pos-form-input"
                    style={{ height: 35, fontSize: '0.85rem', padding: '4px 8px', border: '1px solid var(--border)', borderRadius: '4px', background: 'var(--bg-3)', color: 'var(--text-primary)' }}
                    placeholder="e.g. name@upi"
                    value={upiVpa}
                    onChange={e => {
                      setUpiVpa(e.target.value)
                      localStorage.setItem('pos_upi_vpa', e.target.value)
                    }}
                  />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <label style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-secondary)' }}>Merchant GST State Code</label>
                  <CustomSelect
                    className="pos-form-select"
                    style={{ height: 35, fontSize: '0.85rem', padding: '4px 8px', border: '1px solid var(--border)', borderRadius: '4px', background: 'var(--bg-3)', color: 'var(--text-primary)' }}
                    value={merchantState}
                    onChange={e => {
                      setMerchantState(e.target.value)
                      localStorage.setItem('pos_merchant_state', e.target.value)
                    }}
                  >
                    {/* Full CBIC GST state-code list — every merchant can pick theirs */}
                    <option value="01">01 - Jammu & Kashmir</option>
                    <option value="02">02 - Himachal Pradesh</option>
                    <option value="03">03 - Punjab</option>
                    <option value="04">04 - Chandigarh</option>
                    <option value="05">05 - Uttarakhand</option>
                    <option value="06">06 - Haryana</option>
                    <option value="07">07 - Delhi</option>
                    <option value="08">08 - Rajasthan</option>
                    <option value="09">09 - Uttar Pradesh</option>
                    <option value="10">10 - Bihar</option>
                    <option value="11">11 - Sikkim</option>
                    <option value="12">12 - Arunachal Pradesh</option>
                    <option value="13">13 - Nagaland</option>
                    <option value="14">14 - Manipur</option>
                    <option value="15">15 - Mizoram</option>
                    <option value="16">16 - Tripura</option>
                    <option value="17">17 - Meghalaya</option>
                    <option value="18">18 - Assam</option>
                    <option value="19">19 - West Bengal</option>
                    <option value="20">20 - Jharkhand</option>
                    <option value="21">21 - Odisha</option>
                    <option value="22">22 - Chhattisgarh</option>
                    <option value="23">23 - Madhya Pradesh</option>
                    <option value="24">24 - Gujarat</option>
                    <option value="26">26 - Dadra & Nagar Haveli and Daman & Diu</option>
                    <option value="27">27 - Maharashtra</option>
                    <option value="29">29 - Karnataka</option>
                    <option value="30">30 - Goa</option>
                    <option value="31">31 - Lakshadweep</option>
                    <option value="32">32 - Kerala</option>
                    <option value="33">33 - Tamil Nadu</option>
                    <option value="34">34 - Puducherry</option>
                    <option value="35">35 - Andaman & Nicobar Islands</option>
                    <option value="36">36 - Telangana</option>
                    <option value="37">37 - Andhra Pradesh</option>
                    <option value="38">38 - Ladakh</option>
                  </CustomSelect>
                </div>
              </div>
            )}

            {/* TABLE COLUMNS TAB */}
            {activeTab === 'columns' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <label style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Visible Columns</label>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 16px', background: 'var(--bg-3)', padding: '12px', borderRadius: '6px', border: '1px solid var(--border)' }}>
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
                        <label key={col.key} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)', cursor: col.toggleable ? 'pointer' : 'not-allowed', opacity: col.toggleable ? 1 : 0.6 }}>
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

                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <label style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Rearrange Columns</label>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, background: 'var(--bg-3)', padding: '12px', borderRadius: '6px', border: '1px solid var(--border)', maxHeight: '180px', overflowY: 'auto' }}>
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
                        <div key={col} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 8px', background: isVisible ? 'var(--bg-2)' : 'var(--bg-3)', border: '1px solid var(--border)', borderRadius: '4px', opacity: isVisible ? 1 : 0.6 }}>
                          <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                            {colLabels[col]} {!isVisible && <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>(Hidden)</span>}
                          </span>
                          <div style={{ display: 'flex', gap: 4 }}>
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm"
                              style={{ padding: '2px 6px', fontSize: '0.75rem', border: '1px solid var(--border)' }}
                              disabled={idx === 0}
                              onClick={() => onMoveColumn(idx, 'up')}
                            >
                              ▲
                            </button>
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm"
                              style={{ padding: '2px 6px', fontSize: '0.75rem', border: '1px solid var(--border)' }}
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
              </div>
            )}

            {/* SHORTCUTS / HOTKEYS TAB */}
            {activeTab === 'shortcuts' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: 2 }}>
                  Customize F-key bindings and reference standard fixed POS keyboard mappings.
                </p>

                {/* Flow navigation keys section */}
                <div style={{ background: 'var(--accent-glow)', border: '1px solid var(--accent)', borderRadius: '8px', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <div style={{ fontSize: '0.7rem', fontWeight: 700, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                    <KeyboardIcon size={12} /> Payment Flow Navigation
                  </div>
                  {[
                    { label: 'Proceed to Payment / Go to Customer', key: 'proceedToPayment' },
                    { label: 'Move FORWARD (field by field)', key: 'flowForward' },
                    { label: 'Move BACK (go back one field)', key: 'flowBack' },
                  ].map(item => {
                    const isBinding = bindingKey && bindingKey.action === item.key
                    const currentVal = funcKeys[item.key] || 'Not set'
                    return (
                      <div key={item.key} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-secondary)' }}>{item.label}</span>
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          style={{
                            width: '120px',
                            height: '28px',
                            fontSize: '0.75rem',
                            fontWeight: 700,
                            background: isBinding ? 'var(--accent)' : 'var(--bg-2)',
                            color: isBinding ? '#ffffff' : 'var(--text-primary)',
                            border: isBinding ? '1px solid var(--accent)' : '1px solid var(--border)',
                            borderRadius: 'var(--radius-md)',
                            cursor: 'pointer',
                            textAlign: 'center',
                            outline: 'none',
                            boxShadow: 'var(--shadow-sm)'
                          }}
                          onClick={() => {
                            if (isBinding) {
                              setBindingKey(null)
                            } else {
                              setBindingKey({ action: item.key })
                            }
                          }}
                        >
                          {isBinding ? 'Press key...' : currentVal}
                        </button>
                      </div>
                    )
                  })}
                </div>

                {/* Function hotkeys section */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <div style={{ fontSize: '0.72rem', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 2 }}>
                    F-Key / Action Mappings
                  </div>

                  {/* POS Screen Hotkeys container */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, background: 'var(--bg-3)', padding: '10px', borderRadius: '8px', border: '1px solid var(--border)' }}>
                    <div style={{ fontSize: '0.7rem', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>
                      POS Screen Hotkeys
                    </div>
                    {[
                      { label: 'Change Quantity', key: 'qtyFocus' },
                      { label: 'Remove Item', key: 'removeItem' },
                      { label: 'Search Item / Barcode', key: 'barcodeFocus' },
                      { label: 'Open Checkout / Pay', key: 'amountReceivedFocus' }
                    ].map(item => {
                      const isBinding = bindingKey && bindingKey.action === item.key
                      const currentVal = funcKeys[item.key] || 'Not set'
                      return (
                        <div key={item.key} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 6px' }}>
                          <span style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-secondary)' }}>{item.label}</span>
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            style={{
                              width: '120px',
                              height: '28px',
                              fontSize: '0.75rem',
                              fontWeight: 700,
                              background: isBinding ? 'var(--accent)' : 'var(--bg-2)',
                              color: isBinding ? '#ffffff' : 'var(--text-primary)',
                              border: isBinding ? '1px solid var(--accent)' : '1px solid var(--border)',
                              borderRadius: 'var(--radius-md)',
                              cursor: 'pointer',
                              textAlign: 'center',
                              outline: 'none',
                              boxShadow: 'var(--shadow-sm)'
                            }}
                            onClick={() => {
                              if (isBinding) {
                                      setBindingKey(null)
                              } else {
                                      setBindingKey({ action: item.key })
                              }
                            }}
                          >
                            {isBinding ? 'Press key...' : currentVal}
                          </button>
                        </div>
                      )
                    })}
                  </div>

                  {/* Checkout Modal Hotkeys container */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, background: 'var(--bg-3)', padding: '10px', borderRadius: '8px', border: '1px solid var(--border)' }}>
                    <div style={{ fontSize: '0.7rem', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>
                      Checkout Modal Hotkeys
                    </div>
                    {[
                      { label: 'Select Customer', key: 'customerFocus' },
                      { label: 'Bill Discount (Checkout)', key: 'checkoutDiscountFocus' },
                      { label: 'Remarks / Notes', key: 'remarksFocus' }
                    ].map(item => {
                      const isBinding = bindingKey && bindingKey.action === item.key
                      const currentVal = funcKeys[item.key] || 'Not set'
                      return (
                        <div key={item.key} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 6px' }}>
                          <span style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-secondary)' }}>{item.label}</span>
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            style={{
                              width: '120px',
                              height: '28px',
                              fontSize: '0.75rem',
                              fontWeight: 700,
                              background: isBinding ? 'var(--accent)' : 'var(--bg-2)',
                              color: isBinding ? '#ffffff' : 'var(--text-primary)',
                              border: isBinding ? '1px solid var(--accent)' : '1px solid var(--border)',
                              borderRadius: 'var(--radius-md)',
                              cursor: 'pointer',
                              textAlign: 'center',
                              outline: 'none',
                              boxShadow: 'var(--shadow-sm)'
                            }}
                            onClick={() => {
                              if (isBinding) {
                                      setBindingKey(null)
                              } else {
                                      setBindingKey({ action: item.key })
                              }
                            }}
                          >
                            {isBinding ? 'Press key...' : currentVal}
                          </button>
                        </div>
                      )
                    })}
                  </div>
                </div>

                {/* Standard Fixed Controls section */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 4 }}>
                  <label style={{ fontSize: '0.72rem', fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Standard Control Shortcuts (Fixed)</label>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 16px', background: 'var(--bg-3)', padding: '10px 12px', borderRadius: '6px', border: '1px solid var(--border)' }}>
                    {[
                      { label: 'Save & Print Bill', key: 'Ctrl+P' },
                      { label: 'Save Bill Only', key: 'Ctrl+S' },
                      { label: 'New Active Tab', key: 'Ctrl+T' },
                      { label: 'Close Active Tab', key: 'Ctrl+W' },
                      { label: 'Toggle Breakup', key: 'Ctrl+F' },
                      { label: 'Credit Payment', key: 'Ctrl+M' }
                    ].map(item => (
                      <div key={item.label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)' }}>{item.label}</span>
                        <span style={{ fontSize: '0.7rem', fontWeight: 700, color: 'var(--text-primary)', background: 'var(--bg-4)', padding: '1px 6px', borderRadius: '4px' }}>{item.key}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Footer Actions */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 8, borderTop: '1px solid var(--border)', paddingTop: 12 }}>
            {activeTab === 'shortcuts' ? (
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
            ) : (
              <button
                type="button"
                className="btn btn-ghost"
                style={{ color: 'var(--accent)', fontWeight: 600, fontSize: '0.82rem', padding: '6px 0', display: 'flex', alignItems: 'center' }}
                onClick={onAdvancedSettings}
              >
                Advanced Settings <ChevronRightIcon size={14} style={{ marginLeft: 4 }} />
              </button>
            )}
            <button type="button" className="btn btn-secondary btn-sm" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}