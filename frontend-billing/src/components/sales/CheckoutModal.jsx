import React, { useRef, useEffect, useState, useCallback } from 'react'
import { AlertIcon, CashIcon, CheckIcon, CloseIcon, EditIcon, PhoneIcon, PlusIcon, UserIcon, VolumeIcon } from '../../components/Icons'
import InvoiceBreakdownCard from './InvoiceBreakdownCard'
import TenderChips from './TenderChips'
import { changeDue, paymentBalance } from '../../utils/invoiceMath'
import { buildUpiUri, qrImageUrl } from '../../utils/share'
import { logger } from '../../utils/logger'
import CustomSelect from '../../components/common/CustomSelect'
import { useBillingProfile } from '../../hooks/useBillingProfile'

const fmt = (n) =>
  n != null ? `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '—'

export default function CheckoutModal({
  open,
  onClose,
  form,
  setForm,
  subtotal,
  gstAmt,
  grandTotal,
  payable,
  roundOff,
  cashDiscountAmt,
  cgstAmt,
  sgstAmt,
  igstAmt,
  billDiscountAmt,
  customers,
  setCustomers,
  godowns,
  upiVpa,
  authFetch,
  onSaveInvoice,
  submitting,
  setAlert,
  focusTarget,
  funcKeys
}) {
  const customerRef = useRef(null)
  const godownRef = useRef(null)
  const invoiceDateRef = useRef(null)
  const amountReceivedRef = useRef(null)
  const paymentModeRef = useRef(null)
  const discountRef = useRef(null)
  const notesRef = useRef(null)
  const modalRef = useRef(null)
  const customerDropdownRef = useRef(null)

  // Drawer input refs
  const drawerNameRef = useRef(null)
  const drawerPhoneRef = useRef(null)
  const drawerGstinRef = useRef(null)
  const drawerPriceTierRef = useRef(null)
  const drawerSaveBtnRef = useRef(null)
  const drawerCancelBtnRef = useRef(null)

  const [customerSearchQuery, setCustomerSearchQuery] = useState('')
  const [showCustomerDropdown, setShowCustomerDropdown] = useState(false)
  const [customerSelectedIndex, setCustomerSelectedIndex] = useState(-1)

  // Business-type billing profile (plan Phase 2). FAIL-OPEN: when the profile
  // can't load (offline), guardedSave applies NO restriction — billing never
  // blocks on config. Customer-first verticals (wholesale/services/repair/
  // b2b_supplier) require a customer before the bill can be saved.
  const { profile: billingProfile } = useBillingProfile()
  const guardedSave = useCallback((paidAndPrint) => {
    if (billingProfile?.customer_required && !form.customer_id) {
      const who = billingProfile?.terminology?.customer || 'Customer'
      logger.info('checkout blocked: customer required by billing profile', billingProfile.mode_key)
      setAlert?.({ type: 'danger', msg: `${who} selection is required for ${billingProfile?.label || 'this business type'} billing.` })
      customerRef.current?.focus()
      return
    }
    onSaveInvoice(paidAndPrint)
  }, [billingProfile, form.customer_id, onSaveInvoice, setAlert])

  const [showCustDrawer, setShowCustDrawer] = useState(false)
  const [custModalFields, setCustModalFields] = useState({
    id: '',
    name: '',
    phone: '',
    gstin: '',
    price_tier: 'standard'
  })
  const [savingCustomer, setSavingCustomer] = useState(false)

  // Automatically focus customer drawer Name field when drawer opens
  useEffect(() => {
    if (showCustDrawer) {
      setTimeout(() => {
        drawerNameRef.current?.focus()
        drawerNameRef.current?.select()
      }, 50)
    }
  }, [showCustDrawer])

  // Pending dues for the selected customer (shown inline below the totals).
  const [customerDues, setCustomerDues] = useState(null)
  useEffect(() => {
    if (!open || !form.customer_id) { setCustomerDues(null); return }
    let cancelled = false
    authFetch(`/billing/customers/${form.customer_id}/ledger`)
      .then(r => (r && r.ok) ? r.json() : null)
      .then(d => {
        if (cancelled || !d) return
        const unpaid = (d.entries || []).filter(e => (e.outstanding || 0) > 0.01)
        setCustomerDues({ total: d.outstanding_total || 0, invoices: unpaid.map(e => e.invoice_no).filter(Boolean) })
      })
      .catch(() => { if (!cancelled) setCustomerDues(null) })
    return () => { cancelled = true }
  }, [open, form.customer_id, authFetch])

  // Scroll active customer suggestion item into view inside the dropdown list container
  useEffect(() => {
    if (showCustomerDropdown && customerDropdownRef.current && customerSelectedIndex >= 0) {
      const dropdown = customerDropdownRef.current
      const activeEl = dropdown.children[customerSelectedIndex]
      if (activeEl) {
        const dropdownRect = dropdown.getBoundingClientRect()
        const activeRect = activeEl.getBoundingClientRect()
        if (activeRect.bottom > dropdownRect.bottom) {
          dropdown.scrollTop += (activeRect.bottom - dropdownRect.bottom)
        } else if (activeRect.top < dropdownRect.top) {
          dropdown.scrollTop -= (dropdownRect.top - activeRect.top)
        }
      }
    }
  }, [customerSelectedIndex, showCustomerDropdown])

  // Focus trap to keep browser keyboard focus inside modal and avoid leakage to background POS
  useEffect(() => {
    if (!open) return

    const handleFocusIn = (e) => {
      if (modalRef.current && !modalRef.current.contains(e.target)) {
        e.preventDefault()
        e.stopPropagation()
        if (showCustomerDropdown && customerRef.current) {
          customerRef.current.focus()
        } else if (amountReceivedRef.current) {
          amountReceivedRef.current.focus()
        }
      }
    }

    document.addEventListener('focusin', handleFocusIn)
    return () => document.removeEventListener('focusin', handleFocusIn)
  }, [open, showCustomerDropdown])
  // const [soundboxStatus, setSoundboxStatus] = useState('idle')
  // 
  // useEffect(() => {
  //   let autoCheckoutTimer;
  //   let timer;
  // 
  //   if (open && form.payment_mode === 'upi' && grandTotal > 0) {
  //     setSoundboxStatus('waiting');
  //     
  //     timer = setTimeout(() => {
  //       setSoundboxStatus('success');
  //       
  //       // Voice synthesis announcement
  //       if (window.speechSynthesis) {
  //         try {
  //           window.speechSynthesis.cancel();
  //           const text = `Payment of Rupees ${Math.round(grandTotal)} received on UPI!`;
  //           const utterance = new SpeechSynthesisUtterance(text);
  //           utterance.lang = 'en-IN';
  //           window.speechSynthesis.speak(utterance);
  //         } catch (err) {
  //           console.error('SpeechSynthesis error:', err);
  //         }
  //       }
  // 
  //       autoCheckoutTimer = setTimeout(() => {
  //         onSaveInvoice(true);
  //       }, 1500);
  //     }, 4000);
  //   } else {
  //     setSoundboxStatus('idle');
  //   }
  // 
  //   return () => {
  //     if (timer) clearTimeout(timer);
  //     if (autoCheckoutTimer) clearTimeout(autoCheckoutTimer);
  //     if (window.speechSynthesis) {
  //       window.speechSynthesis.cancel();
  //     }
  //   };
  // }, [open, form.payment_mode, grandTotal, onSaveInvoice]);

  const setField = (k, v) => setForm(f => ({ ...f, [k]: v }))
  // What the customer actually pays = grand total − post-tax cash discount.
  // payable === grandTotal when there's no cash discount, so all existing flows
  // (tenders, change-due, amount-received) are unchanged.
  const pay = (payable ?? grandTotal)
  const amountReceivedNum = parseFloat(form.amount_received) || 0
  const changeToReturn = changeDue(amountReceivedNum, pay)
  // Signed balance: negative = short (still owed), shown in red below.
  const balance = paymentBalance(amountReceivedNum, pay)
  const isCredit = form.payment_mode === 'credit'

  // Autofocus logic
  useEffect(() => {
    if (open) {
      if (focusTarget === 'customer') {
        setTimeout(() => {
          customerRef.current?.focus()
          customerRef.current?.select()
        }, 50)
      } else if (focusTarget === 'amountReceived') {
        setTimeout(() => {
          amountReceivedRef.current?.focus()
          amountReceivedRef.current?.select()
        }, 50)
      } else if (focusTarget === 'remarks') {
        setTimeout(() => {
          document.getElementById('checkout-notes')?.focus()
        }, 50)
      } else {
        setTimeout(() => {
          customerRef.current?.focus()
        }, 50)
      }
    }
  }, [open, focusTarget])

  // Sync customer search query with selected customer id
  useEffect(() => {
    if (open) {
      const current = customers.find(c => String(c.id) === String(form.customer_id))
      setCustomerSearchQuery(current ? (current.name + (current.phone ? ` (${current.phone})` : '')) : '')
    }
  }, [open, form.customer_id, customers])

  // Keep amount_received in sync with payable dynamically when discount or items change
  useEffect(() => {
    if (open) {
      setForm(f => {
        if (f.payment_mode === 'credit') {
          return { ...f, amount_received: '0' }
        } else {
          return { ...f, amount_received: pay.toFixed(2) }
        }
      })
    }
  }, [pay, open, form.payment_mode, setForm])

  // matchesKey helper
  const matchesKey = (e, descriptor) => {
    if (!descriptor) return false
    const parts = descriptor.split('+')
    const key = parts[parts.length - 1]
    const wantsShift = parts.includes('Shift')
    const wantsCtrl  = parts.includes('Ctrl')
    const wantsAlt   = parts.includes('Alt')
    return (
      e.key === key &&
      e.shiftKey === wantsShift &&
      e.ctrlKey  === wantsCtrl  &&
      e.altKey   === wantsAlt
    )
  }

  const handleCustomerKeyDown = (e) => {
    const currentSelectedLabel = (() => {
      if (!form.customer_id || customers.length === 0) return ''
      const c = customers.find(x => String(x.id) === String(form.customer_id))
      return c ? (c.name + (c.phone ? ` (${c.phone})` : '')) : ''
    })()
    const query = customerSearchQuery.trim().toLowerCase()
    const filteredCustomers = (() => {
      if (!query || query === currentSelectedLabel.trim().toLowerCase()) {
        return customers
      }
      return customers.filter(c =>
        c.name.toLowerCase().includes(query) ||
        (c.phone && c.phone.toLowerCase().includes(query))
      )
    })()

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      if (!showCustomerDropdown) setShowCustomerDropdown(true)
      // Allow selecting up to filteredCustomers.length (for the add customer item)
      setCustomerSelectedIndex(prev => Math.min(filteredCustomers.length > 0 ? filteredCustomers.length : 0, prev + 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setCustomerSelectedIndex(prev => Math.max(-1, prev - 1))
    } else if (matchesKey(e, funcKeys?.flowBack || 'Shift+Enter')) {
      e.preventDefault()
      setShowCustomerDropdown(false)
      setCustomerSelectedIndex(-1)
      setTimeout(() => paymentModeRef.current?.focus(), 50)
    } else if (matchesKey(e, funcKeys?.flowForward || 'Enter')) {
      e.preventDefault()
      if (showCustomerDropdown && customerSelectedIndex !== -1) {
        if (customerSelectedIndex === (filteredCustomers.length > 0 ? filteredCustomers.length : 0)) {
          // Trigger add customer drawer
          const isPhone = /^\d+$/.test(customerSearchQuery.trim())
          setCustModalFields({
            id: '',
            name: isPhone ? '' : customerSearchQuery,
            phone: isPhone ? customerSearchQuery : '',
            gstin: '',
            price_tier: 'standard'
          })
          setShowCustomerDropdown(false)
          setCustomerSelectedIndex(-1)
          setShowCustDrawer(true)
        } else if (filteredCustomers[customerSelectedIndex]) {
          const c = filteredCustomers[customerSelectedIndex]
          setForm(f => ({ ...f, customer_id: c.id }))
          setCustomerSearchQuery(c.name + (c.phone ? ` (${c.phone})` : ''))
          setShowCustomerDropdown(false)
          setCustomerSelectedIndex(-1)
          setTimeout(() => godownRef.current?.focus(), 50)
        }
      } else if (showCustomerDropdown && filteredCustomers.length > 0 && customerSearchQuery.trim()) {
        const c = filteredCustomers[0]
        setForm(f => ({ ...f, customer_id: c.id }))
        setCustomerSearchQuery(c.name + (c.phone ? ` (${c.phone})` : ''))
        setShowCustomerDropdown(false)
        setCustomerSelectedIndex(-1)
        setTimeout(() => godownRef.current?.focus(), 50)
      } else {
        if (form.customer_id || !customerSearchQuery.trim()) {
          godownRef.current?.focus()
        } else {
          const isPhone = /^\d+$/.test(customerSearchQuery.trim())
          setCustModalFields({
            id: '',
            name: isPhone ? '' : customerSearchQuery,
            phone: isPhone ? customerSearchQuery : '',
            gstin: '',
            price_tier: 'standard'
          })
          setShowCustomerDropdown(false)
          setShowCustDrawer(true)
        }
      }
    } else if (e.key === 'Escape') {
      e.preventDefault()
      if (showCustomerDropdown) {
        setShowCustomerDropdown(false)
        setCustomerSelectedIndex(-1)
      } else {
        onClose()
      }
    }
  }

  const handleDrawerKeyDown = (e, fieldName) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      if (e.shiftKey) {
        // Navigate backwards
        if (fieldName === 'cancel') {
          drawerSaveBtnRef.current?.focus()
        } else if (fieldName === 'save') {
          drawerPriceTierRef.current?.focus()
        } else if (fieldName === 'price_tier') {
          drawerGstinRef.current?.focus()
        } else if (fieldName === 'gstin') {
          drawerPhoneRef.current?.focus()
        } else if (fieldName === 'phone') {
          drawerNameRef.current?.focus()
          drawerNameRef.current?.select()
        }
      } else {
        // Navigate forwards
        if (fieldName === 'name') {
          drawerPhoneRef.current?.focus()
          drawerPhoneRef.current?.select()
        } else if (fieldName === 'phone') {
          drawerGstinRef.current?.focus()
          drawerGstinRef.current?.select()
        } else if (fieldName === 'gstin') {
          drawerPriceTierRef.current?.focus()
        } else if (fieldName === 'price_tier') {
          drawerSaveBtnRef.current?.focus()
        } else if (fieldName === 'save') {
          handleSaveCustomer(e)
        } else if (fieldName === 'cancel') {
          setShowCustDrawer(false)
          setTimeout(() => {
            customerRef.current?.focus()
            customerRef.current?.select()
          }, 50)
        }
      }
    } else if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      setShowCustDrawer(false)
      setTimeout(() => {
        customerRef.current?.focus()
        customerRef.current?.select()
      }, 50)
    }
  }

  const handlePaymentModeButtonKeyDown = (e, currentMode) => {
    const modes = ['cash', 'upi', 'card', 'credit']
    const idx = modes.indexOf(currentMode)
    
    if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
      e.preventDefault()
      const nextIdx = (idx - 1 + modes.length) % modes.length
      const nextMode = modes[nextIdx]
      setForm(f => {
        const updates = { ...f, payment_mode: nextMode }
        if (nextMode === 'credit') {
          updates.amount_received = '0'
        } else {
          updates.amount_received = pay.toFixed(2)
        }
        return updates
      })
      setTimeout(() => {
        const btn = document.querySelector(`.payment-mode-btn-${nextMode}`)
        btn?.focus()
      }, 30)
    } else if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
      e.preventDefault()
      const nextIdx = (idx + 1) % modes.length
      const nextMode = modes[nextIdx]
      setForm(f => {
        const updates = { ...f, payment_mode: nextMode }
        if (nextMode === 'credit') {
          updates.amount_received = '0'
        } else {
          updates.amount_received = pay.toFixed(2)
        }
        return updates
      })
      setTimeout(() => {
        const btn = document.querySelector(`.payment-mode-btn-${nextMode}`)
        btn?.focus()
      }, 30)
    } else if (matchesKey(e, funcKeys?.flowBack || 'Shift+Enter')) {
      e.preventDefault()
      e.stopPropagation()
      setTimeout(() => {
        amountReceivedRef.current?.focus()
        amountReceivedRef.current?.select()
      }, 30)
    } else if (matchesKey(e, funcKeys?.flowForward || 'Enter')) {
      e.preventDefault()
      e.stopPropagation()
      guardedSave(true)
    } else if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      onClose()
    }
  }

  const handlePaymentPopupKeyDown = (e) => {
    if (matchesKey(e, funcKeys?.flowBack || 'Shift+Enter')) {
      e.preventDefault()
      e.stopPropagation()
      discountRef.current?.focus()
      discountRef.current?.select()
    } else if (matchesKey(e, funcKeys?.flowForward || 'Enter')) {
      e.preventDefault()
      e.stopPropagation()
      setTimeout(() => paymentModeRef.current?.focus(), 50)
    } else if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      onClose()
    } else if (e.ctrlKey && e.key.toLowerCase() === 's') {
      e.preventDefault()
      e.stopPropagation()
      guardedSave(false)
    }
  }

  // Global event listener for modal hotkeys
  useEffect(() => {
    if (!open) return

    const handleGlobalKeyDown = (e) => {
      if (showCustDrawer) return

      if (e.key === 'Escape') {
        if (showCustomerDropdown) {
          setShowCustomerDropdown(false)
          setCustomerSelectedIndex(-1)
          e.preventDefault()
          e.stopPropagation()
        } else {
          e.preventDefault()
          e.stopPropagation()
          onClose()
        }
      }

      if ((e.ctrlKey && e.key.toLowerCase() === 'p') || e.key === 'F10') {
        e.preventDefault()
        e.stopPropagation()
        guardedSave(true)
      }

      if (e.ctrlKey && e.key.toLowerCase() === 's') {
        e.preventDefault()
        e.stopPropagation()
        guardedSave(false)
      }

      if (matchesKey(e, funcKeys?.customerFocus || 'F11')) {
        e.preventDefault()
        e.stopPropagation()
        customerRef.current?.focus()
        customerRef.current?.select()
      } else if (matchesKey(e, funcKeys?.remarksFocus || 'F12')) {
        e.preventDefault()
        e.stopPropagation()
        document.getElementById('checkout-notes')?.focus()
      } else if (matchesKey(e, funcKeys?.amountReceivedFocus || 'F8')) {
        e.preventDefault()
        e.stopPropagation()
        amountReceivedRef.current?.focus()
        amountReceivedRef.current?.select()
      } else if (matchesKey(e, funcKeys?.checkoutDiscountFocus || 'F7')) {
        e.preventDefault()
        e.stopPropagation()
        discountRef.current?.focus()
        discountRef.current?.select()
      }
    }

    window.addEventListener('keydown', handleGlobalKeyDown)
    return () => window.removeEventListener('keydown', handleGlobalKeyDown)
  }, [open, showCustDrawer, showCustomerDropdown, funcKeys, onClose, guardedSave])

  // Save Customer Handler
  const handleSaveCustomer = async (e) => {
    if (e && typeof e.preventDefault === 'function') e.preventDefault()
    if (!custModalFields.name.trim()) return
    setSavingCustomer(true)
    try {
      const isEdit = !!custModalFields.id
      const url = isEdit ? `/billing/customers/${custModalFields.id}` : '/billing/customers'
      const method = isEdit ? 'PATCH' : 'POST'
      const res = await authFetch(url, {
        method,
        body: JSON.stringify({
          name: custModalFields.name,
          phone: custModalFields.phone || null,
          gstin: custModalFields.gstin || null,
          price_tier: custModalFields.price_tier || 'standard'
        })
      })
      if (res.ok) {
        const savedCust = await res.json()
        setAlert({ type: 'success', msg: `Customer ${isEdit ? 'updated' : 'created'} successfully!` })
        setShowCustDrawer(false)
        const updatedCustRes = await authFetch('/billing/customers')
        if (updatedCustRes.ok) {
          const custData = await updatedCustRes.json()
          let custItems = Array.isArray(custData) ? custData : (custData && Array.isArray(custData.items) ? custData.items : [])
          // The refetched list can lag a just-committed write (local cache); make
          // sure the customer we just saved is present so the Edit button's lookup
          // finds it — otherwise a brand-new customer opens a blank "Add" form and
          // looks "not editable". Upsert savedCust into the list.
          if (savedCust && savedCust.id != null) {
            const idx = custItems.findIndex(c => String(c.id) === String(savedCust.id))
            if (idx === -1) custItems = [savedCust, ...custItems]
            else custItems[idx] = { ...custItems[idx], ...savedCust }
          }
          setCustomers(custItems)
          setForm(f => ({ ...f, customer_id: savedCust.id }))
          setCustomerSearchQuery(savedCust.name + (savedCust.phone ? ` (${savedCust.phone})` : ''))
          setTimeout(() => godownRef.current?.focus(), 50)
        } else {
          // Even if the refetch failed, keep the new customer usable/editable.
          if (savedCust && savedCust.id != null) {
            setCustomers(prev => {
              const arr = Array.isArray(prev) ? prev.slice() : []
              if (!arr.some(c => String(c.id) === String(savedCust.id))) arr.unshift(savedCust)
              return arr
            })
            setForm(f => ({ ...f, customer_id: savedCust.id }))
          }
          setTimeout(() => godownRef.current?.focus(), 50)
        }
      } else {
        const err = await res.json().catch(() => ({}))
        logger.error('[SALES] save customer failed', res.status, err.detail)
        setAlert({ type: 'danger', msg: err.detail || 'Failed to save customer.' })
      }
    } catch (err) {
      logger.error('[SALES] save customer network error', err)
      setAlert({ type: 'danger', msg: 'Network error. Please try again.' })
    } finally {
      setSavingCustomer(false)
    }
  }

  if (!open) return null

  return (
    <>
      <div
        className="payment-modal-overlay"
        style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(0, 0, 0, 0.25)',
          backdropFilter: 'blur(20px)',
          WebkitBackdropFilter: 'blur(20px)',
          zIndex: 2000,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center'
        }}
        onClick={onClose}
      >
        <div
          ref={modalRef}
          className="payment-modal-card"
          style={{
            background: 'var(--glass-bg, var(--bg-2))',
            backdropFilter: 'blur(30px) saturate(190%)',
            WebkitBackdropFilter: 'blur(30px) saturate(190%)',
            color: 'var(--text-primary)',
            border: '1px solid var(--glass-border, var(--border))',
            borderRadius: 'var(--radius-xl)',
            width: '100%',
            maxWidth: '850px',
            padding: '24px',
            boxShadow: 'var(--shadow-lg)',
            zIndex: 2010,
            display: 'flex',
            flexDirection: 'column',
            gap: '16px',
            maxHeight: 'calc(100vh - 40px)',
            overflowY: 'auto'
          }}
          onClick={e => e.stopPropagation()}
        >
          {/* Header */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border)', paddingBottom: '12px' }}>
            <span style={{ fontSize: '1.3rem', fontWeight: 800, color: 'var(--text-primary)' }}>POS Checkout</span>
            <button
              type="button"
              style={{ color: 'var(--text-muted)', fontSize: '1.2rem', padding: '0 4px', cursor: 'pointer', background: 'none', border: 'none' }}
              onClick={onClose}
             aria-label="Close"><CloseIcon size={16} /></button>
          </div>

          {/* Two Column Layout */}
          <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>
            
            {/* Left Column - Billing & Breakdown */}
            <div style={{ flex: 1, minWidth: '350px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--accent)', borderBottom: '1px dashed var(--border)', paddingBottom: '4px' }}>
                <UserIcon size={16} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Billing Info
              </div>

              {/* Customer search select dropdown */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', position: 'relative' }}>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontWeight: 600 }}>Customer Name</label>
                <div style={{ display: 'flex', gap: 6 }}>
                  <div style={{ flex: 1, position: 'relative' }}>
                    <input
                      ref={customerRef}
                      type="text"
                      style={{
                        background: 'var(--bg-3)',
                        border: '1px solid var(--border)',
                        color: 'var(--text-primary)',
                        height: 35,
                        padding: '4px 8px',
                        borderRadius: 'var(--radius-md)',
                        width: '100%',
                        outline: 'none',
                        paddingRight: '28px'
                      }}
                      value={customerSearchQuery}
                      onChange={e => {
                        setCustomerSearchQuery(e.target.value)
                        setShowCustomerDropdown(true)
                      }}
                      onFocus={e => {
                        e.target.select()
                        setShowCustomerDropdown(true)
                      }}
                      onKeyDown={handleCustomerKeyDown}
                      placeholder="Search customer [F11]..."
                    />
                    {form.customer_id && (
                      <span
                        style={{
                          position: 'absolute',
                          right: 8,
                          top: '50%',
                          transform: 'translateY(-50%)',
                          cursor: 'pointer',
                          color: 'var(--text-muted)',
                          fontSize: '0.8rem',
                          fontWeight: 'bold',
                          padding: '4px'
                        }}
                        onClick={() => {
                          setForm(f => ({ ...f, customer_id: '' }))
                          setCustomerSearchQuery('')
                        }}
                        title="Clear Selection"
                      ><CloseIcon size={12} /></span>
                    )}
                  </div>
                  <button
                    type="button"
                    style={{
                      padding: '0 12px',
                      fontSize: '0.9rem',
                      height: 35,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontWeight: 'bold',
                      background: 'var(--accent)',
                      color: '#ffffff',
                      border: 'none',
                      borderRadius: 'var(--radius-md)',
                      cursor: 'pointer'
                    }}
                    title={form.customer_id ? "Edit Current Customer" : "Add New Customer"}
                    onClick={() => {
                      const current = customers.find(c => String(c.id) === String(form.customer_id))
                      if (current) {
                        setCustModalFields({
                          id: current.id,
                          name: current.name || '',
                          phone: current.phone || '',
                          gstin: current.gstin || '',
                          price_tier: current.price_tier || 'standard'
                        })
                      } else {
                        const isPhone = /^\d+$/.test(customerSearchQuery.trim())
                        setCustModalFields({
                          id: '',
                          name: isPhone ? '' : customerSearchQuery,
                          phone: isPhone ? customerSearchQuery : '',
                          gstin: '',
                          price_tier: 'standard'
                        })
                      }
                      setShowCustDrawer(true)
                    }}
                  >
                    {form.customer_id ? <EditIcon size={14} /> : <PlusIcon size={14} />}
                  </button>
                </div>

                {/* Customer Dropdown Overlay */}
                {showCustomerDropdown && (
                  <>
                    <div
                      style={{
                        position: 'fixed',
                        inset: 0,
                        zIndex: 998
                      }}
                      onClick={() => {
                        setShowCustomerDropdown(false)
                        setCustomerSelectedIndex(-1)
                      }}
                    />
                    <div
                      ref={customerDropdownRef}
                      className="pos-customer-dropdown-overlay"
                      style={{
                        position: 'absolute',
                        top: '100%',
                        left: 0,
                        right: 0,
                        background: 'var(--bg-2)',
                        border: '1px solid var(--border)',
                        borderRadius: 'var(--radius-md)',
                        boxShadow: 'var(--shadow-lg)',
                        zIndex: 999,
                        marginTop: 6,
                        maxHeight: '160px',
                        overflowY: 'auto'
                      }}
                    >
                      {(() => {
                        const currentSelectedLabel = (() => {
                          if (!form.customer_id || customers.length === 0) return ''
                          const c = customers.find(x => String(x.id) === String(form.customer_id))
                          return c ? (c.name + (c.phone ? ` (${c.phone})` : '')) : ''
                        })()

                        const query = customerSearchQuery.trim().toLowerCase()
                        const filteredCustomers = (() => {
                          if (!query || query === currentSelectedLabel.trim().toLowerCase()) {
                            return customers
                          }
                          return customers.filter(c =>
                            c.name.toLowerCase().includes(query) ||
                            (c.phone && c.phone.toLowerCase().includes(query))
                          )
                        })()

                        const isAddActive = customerSelectedIndex === (filteredCustomers.length > 0 ? filteredCustomers.length : 0)

                        return (
                          <>
                            {filteredCustomers.length > 0 ? (
                              filteredCustomers.map((c, idx) => {
                                const isSelected = idx === customerSelectedIndex || String(form.customer_id) === String(c.id)
                                return (
                                  <div
                                    key={c.id}
                                    className={`pos-customer-dropdown-item ${isSelected ? 'active' : ''}`}
                                    style={{
                                      background: isSelected ? 'var(--accent)' : 'transparent',
                                      color: isSelected ? '#ffffff' : 'var(--text-primary)',
                                      cursor: 'pointer',
                                      padding: '8px 12px'
                                    }}
                                    onClick={() => {
                                      setForm(f => ({ ...f, customer_id: c.id }))
                                      setCustomerSearchQuery(c.name + (c.phone ? ` (${c.phone})` : ''))
                                      setShowCustomerDropdown(false)
                                      setCustomerSelectedIndex(-1)
                                      setTimeout(() => godownRef.current?.focus(), 50)
                                    }}
                                    onMouseEnter={() => setCustomerSelectedIndex(idx)}
                                  >
                                    <div className="pos-customer-dropdown-item-title" style={{ fontWeight: 600 }}>{c.name}</div>
                                    {c.phone && <div className="pos-customer-dropdown-item-phone" style={{ fontSize: '0.75rem', opacity: 0.8 }}><PhoneIcon size={14} style={{ marginRight: 4, display: 'inline-block', verticalAlign: 'middle' }} /> {c.phone}</div>}
                                  </div>
                                )
                              })
                            ) : (
                              <div style={{ padding: '10px 12px', color: 'var(--text-muted)', fontSize: '0.82rem', textAlign: 'center' }}>
                                No matching customer found.
                              </div>
                            )}

                            {/* Persistent Add/Create customer option at bottom of dropdown */}
                            <div
                              className={`pos-customer-dropdown-item ${isAddActive ? 'active' : ''}`}
                              style={{
                                padding: '8px 12px',
                                cursor: 'pointer',
                                background: isAddActive ? 'var(--accent)' : 'var(--bg-3)',
                                color: isAddActive ? '#ffffff' : 'var(--accent)',
                                fontWeight: 600,
                                fontSize: '0.82rem',
                                textAlign: 'center',
                                borderTop: '1px solid var(--border)'
                              }}
                              onClick={() => {
                                const isPhone = /^\d+$/.test(customerSearchQuery.trim())
                                setCustModalFields({
                                  id: '',
                                  name: isPhone ? '' : customerSearchQuery,
                                  phone: isPhone ? customerSearchQuery : '',
                                  gstin: '',
                                  price_tier: 'standard'
                                })
                                setShowCustomerDropdown(false)
                                setCustomerSelectedIndex(-1)
                                setShowCustDrawer(true)
                              }}
                              onMouseEnter={() => setCustomerSelectedIndex(filteredCustomers.length > 0 ? filteredCustomers.length : 0)}
                            >
                              <PlusIcon size={14} style={{ marginRight: 4, display: 'inline-block', verticalAlign: 'middle' }} />
                              {customerSearchQuery.trim() ? `Create customer "${customerSearchQuery}"` : 'Add New Customer'}
                            </div>
                          </>
                        )
                      })()}
                    </div>
                  </>
                )}
              </div>

              {/* Customer Creation/Edit Drawer */}
              {showCustDrawer && (
                <div
                  style={{
                    background: 'var(--bg-3)',
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius-md)',
                    padding: '14px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '12px',
                    marginTop: '4px',
                    boxShadow: 'inset 0 1px 2px rgba(0,0,0,0.05)'
                  }}
                  onKeyDown={e => {
                    // Stop Escape key propagation to keep it within the drawer context
                    if (e.key === 'Escape') {
                      e.stopPropagation()
                    }
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border)', paddingBottom: '6px' }}>
                    <span style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--accent)' }}>
                      <UserIcon size={14} style={{ marginRight: 4, display: 'inline-block', verticalAlign: 'middle' }} />
                      {custModalFields.id ? 'Edit Customer Details' : 'Add New Customer'}
                    </span>
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                    {/* Customer Name */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                      <label style={{ fontSize: '0.72rem', fontWeight: 700, color: 'var(--text-secondary)' }}>Customer Name *</label>
                      <input
                        ref={drawerNameRef}
                        type="text"
                        required
                        className="pos-form-input"
                        value={custModalFields.name}
                        onChange={e => setCustModalFields(prev => ({ ...prev, name: e.target.value }))}
                        onKeyDown={e => handleDrawerKeyDown(e, 'name')}
                        placeholder="Enter customer name..."
                        style={{ height: 32, fontSize: '0.85rem' }}
                      />
                    </div>

                    {/* Phone & GSTIN row */}
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        <label style={{ fontSize: '0.72rem', fontWeight: 700, color: 'var(--text-secondary)' }}>Phone Number</label>
                        <input
                          ref={drawerPhoneRef}
                          type="text"
                          className="pos-form-input"
                          value={custModalFields.phone}
                          onChange={e => setCustModalFields(prev => ({ ...prev, phone: e.target.value }))}
                          onKeyDown={e => handleDrawerKeyDown(e, 'phone')}
                          placeholder="e.g. 9876543210"
                          style={{ height: 32, fontSize: '0.85rem' }}
                        />
                      </div>
                      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        <label style={{ fontSize: '0.72rem', fontWeight: 700, color: 'var(--text-secondary)' }}>GSTIN</label>
                        <input
                          ref={drawerGstinRef}
                          type="text"
                          className="pos-form-input"
                          value={custModalFields.gstin}
                          onChange={e => setCustModalFields(prev => ({ ...prev, gstin: e.target.value }))}
                          onKeyDown={e => handleDrawerKeyDown(e, 'gstin')}
                          placeholder="15-digit GSTIN..."
                          style={{ height: 32, fontSize: '0.85rem' }}
                        />
                      </div>
                    </div>

                    {/* Price Tier */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                      <label style={{ fontSize: '0.72rem', fontWeight: 700, color: 'var(--text-secondary)' }}>Price Tier</label>
                      <CustomSelect
                        ref={drawerPriceTierRef}
                        className="pos-form-select"
                        value={custModalFields.price_tier}
                        onChange={e => setCustModalFields(prev => ({ ...prev, price_tier: e.target.value }))}
                        onKeyDown={e => handleDrawerKeyDown(e, 'price_tier')}
                        style={{ height: 32, fontSize: '0.85rem' }}
                      >
                        <option value="standard">Standard Pricing</option>
                        <option value="wholesale">Wholesale Pricing</option>
                        <option value="distributor">Distributor Pricing</option>
                      </CustomSelect>
                    </div>

                    {/* Buttons */}
                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '6px', borderTop: '1px solid var(--border)', paddingTop: '10px' }}>
                      <button
                        ref={drawerCancelBtnRef}
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() => {
                          setShowCustDrawer(false)
                          setTimeout(() => {
                            customerRef.current?.focus()
                            customerRef.current?.select()
                          }, 50)
                        }}
                        onKeyDown={e => handleDrawerKeyDown(e, 'cancel')}
                        style={{ height: 30, padding: '0 12px', fontSize: '0.8rem' }}
                      >
                        Cancel
                      </button>
                      <button
                        ref={drawerSaveBtnRef}
                        type="button"
                        className="btn btn-primary btn-sm"
                        disabled={savingCustomer}
                        onClick={handleSaveCustomer}
                        onKeyDown={e => handleDrawerKeyDown(e, 'save')}
                        style={{ background: 'var(--accent)', borderColor: 'var(--accent)', height: 30, padding: '0 12px', fontSize: '0.8rem' }}
                      >
                        {savingCustomer ? 'Saving...' : 'Save Customer'}
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* Godown Selection & Date Selection Row */}
              <div style={{ display: 'flex', gap: '12px' }}>
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <label style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontWeight: 600 }}>Godown</label>
                  <CustomSelect
                    ref={godownRef}
                    className="pos-form-select"
                    style={{
                      background: 'var(--bg-3)',
                      border: '1px solid var(--border)',
                      color: 'var(--text-primary)',
                      height: 35,
                      padding: '4px 8px',
                      borderRadius: 'var(--radius-md)',
                      outline: 'none'
                    }}
                    value={form.godown_id}
                    onChange={e => setField('godown_id', e.target.value)}
                    onKeyDown={e => {
                      if (matchesKey(e, funcKeys?.flowBack || 'Shift+Enter')) {
                        e.preventDefault()
                        customerRef.current?.focus()
                        customerRef.current?.select()
                      } else if (matchesKey(e, funcKeys?.flowForward || 'Enter')) {
                        e.preventDefault()
                        invoiceDateRef.current?.focus()
                      }
                    }}
                    required
                  >
                    <option value="">-- Select Godown --</option>
                    {godowns.map(g => (
                      <option key={g.id} value={g.id}>
                        {g.name}
                      </option>
                    ))}
                  </CustomSelect>
                </div>

                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <label style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontWeight: 600 }}>Invoice Date</label>
                  <input
                    ref={invoiceDateRef}
                    type="date"
                    style={{
                      background: 'var(--bg-3)',
                      border: '1px solid var(--border)',
                      color: 'var(--text-primary)',
                      height: 35,
                      padding: '4px 8px',
                      borderRadius: 'var(--radius-md)',
                      width: '100%',
                      outline: 'none'
                    }}
                    value={form.due_date}
                    onChange={e => setField('due_date', e.target.value)}
                    onKeyDown={e => {
                      if (matchesKey(e, funcKeys?.flowBack || 'Shift+Enter')) {
                        e.preventDefault()
                        godownRef.current?.focus()
                      } else if (matchesKey(e, funcKeys?.flowForward || 'Enter')) {
                        e.preventDefault()
                        notesRef.current?.focus()
                      }
                    }}
                  />
                </div>
              </div>

              {/* Invoice Breakdown card */}
              <InvoiceBreakdownCard
                subtotal={subtotal}
                discount={billDiscountAmt}
                cgstAmt={cgstAmt}
                sgstAmt={sgstAmt}
                igstAmt={igstAmt}
                gstAmt={gstAmt}
                grandTotal={grandTotal}
              />

              {/* Selected customer's pending dues — inline, below the totals */}
              {customerDues && customerDues.total > 0.01 && (
                <div style={{
                  background: 'var(--danger-dim)',
                  border: '1px solid var(--danger)',
                  borderRadius: 'var(--radius-md)',
                  padding: '8px 10px',
                  fontSize: '0.78rem',
                  color: 'var(--danger)',
                  lineHeight: 1.4
                }}>
                  <strong>Pending due: {fmt(customerDues.total)}</strong>
                  {customerDues.invoices.length > 0 && (
                    <span> · {customerDues.invoices.slice(0, 4).join(', ')}
                      {customerDues.invoices.length > 4 ? ` +${customerDues.invoices.length - 4} more` : ''}</span>
                  )}
                </div>
              )}

              {/* Remarks / Reference Notes */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontWeight: 600 }}>Remarks / Notes</label>
                <textarea
                  id="checkout-notes"
                  style={{
                    background: 'var(--bg-3)',
                    border: '1px solid var(--border)',
                    color: 'var(--text-primary)',
                    minHeight: 50,
                    padding: '8px 10px',
                    borderRadius: 'var(--radius-md)',
                    resize: 'none',
                    outline: 'none',
                    fontSize: '0.85rem'
                  }}
                  placeholder="Remarks or internal notes…"
                  value={form.notes}
                  onChange={e => setField('notes', e.target.value)}
                  ref={notesRef}
                  onKeyDown={e => {
                    if (matchesKey(e, funcKeys?.flowBack || 'Shift+Enter')) {
                      e.preventDefault()
                      invoiceDateRef.current?.focus()
                    } else if (matchesKey(e, funcKeys?.flowForward || 'Enter')) {
                      e.preventDefault()
                      discountRef.current?.focus()
                      discountRef.current?.select()
                    }
                  }}
                />
              </div>
            </div>

            {/* Right Column - Tendering & Checkout */}
            <div style={{ flex: 1, minWidth: '350px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--accent)', borderBottom: '1px dashed var(--border)', paddingBottom: '4px' }}>
                <CashIcon size={16} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Tendering
              </div>

              {/* Single Discount (post-tax — reduces the payable, NOT GST) + automatic round-off */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontWeight: 600 }}>Discount (₹)</label>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <span style={{ fontSize: '1rem', color: 'var(--text-muted)', fontWeight: 700 }}>₹</span>
                  <input
                    ref={discountRef}
                    type="number"
                    min="0"
                    step="any"
                    value={form.cash_discount}
                    onChange={e => setField('cash_discount', e.target.value)}
                    placeholder="0.00"
                    title="Discount on the payable. Does not change GST. Round-off is automatic."
                    onKeyDown={e => {
                      if (matchesKey(e, funcKeys?.flowBack || 'Shift+Enter')) {
                        e.preventDefault()
                        notesRef.current?.focus()
                      } else if (matchesKey(e, funcKeys?.flowForward || 'Enter')) {
                        e.preventDefault()
                        amountReceivedRef.current?.focus()
                        amountReceivedRef.current?.select()
                      }
                    }}
                    style={{
                      flex: 1,
                      background: 'var(--bg-3)',
                      border: '1px solid var(--border)',
                      color: 'var(--text-primary)',
                      height: 38,
                      padding: '4px 12px',
                      borderRadius: 'var(--radius-md)',
                      outline: 'none',
                      fontSize: '1rem',
                      fontWeight: 600
                    }}
                  />
                </div>
                {/* Auto round-off + discount → payable, computed live */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginTop: 2, fontSize: '0.85rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-muted)' }}>
                    <span>Grand total</span><span>{fmt(grandTotal)}</span>
                  </div>
                  {Math.abs(roundOff || 0) >= 0.005 && (
                    <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-muted)' }}>
                      <span>Round-off (auto)</span><span>{(roundOff || 0) > 0 ? '+ ' : '− '}{fmt(Math.abs(roundOff || 0))}</span>
                    </div>
                  )}
                  {cashDiscountAmt > 0 && (
                    <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--success)', fontWeight: 600 }}>
                      <span>Cash discount</span><span>− {fmt(cashDiscountAmt)}</span>
                    </div>
                  )}
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 800, fontSize: '1rem', color: 'var(--text-primary)', borderTop: '1px dashed var(--border)', paddingTop: 4, marginTop: 2 }}>
                    <span>Payable</span><span>{fmt(pay)}</span>
                  </div>
                </div>
              </div>

              {/* Amount Received Input */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontWeight: 600 }}>Amount received</label>
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  background: 'var(--bg-3)',
                  border: '1.5px solid var(--accent)',
                  borderRadius: 'var(--radius-md)',
                  padding: '8px 14px'
                }}>
                  <span style={{ fontSize: '1.25rem', color: 'var(--text-muted)', marginRight: '6px' }}>₹</span>
                  <input
                    ref={amountReceivedRef}
                    type="number"
                    min="0"
                    step="any"
                    style={{
                      background: 'transparent',
                      border: 'none',
                      color: 'var(--text-primary)',
                      fontSize: '1.5rem',
                      fontWeight: '700',
                      width: '100%',
                      outline: 'none'
                    }}
                    placeholder="0.00"
                    value={form.amount_received}
                    onChange={e => setField('amount_received', e.target.value)}
                    onKeyDown={handlePaymentPopupKeyDown}
                  />
                </div>
              </div>

              {/* Tender Chips — target the payable (= grand − cash discount) */}
              <TenderChips
                grandTotal={pay}
                onSelect={(val) => {
                  setForm(f => {
                    const updates = { ...f, amount_received: val.toString() }
                    if (f.payment_mode === 'credit' && val > 0) {
                      updates.payment_mode = 'cash'
                    }
                    return updates
                  })
                  setTimeout(() => amountReceivedRef.current?.focus(), 30)
                }}
              />

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '6px' }}>
                {['cash', 'upi', 'card', 'credit'].map(mode => {
                  const isActive = form.payment_mode === mode
                  return (
                    <button
                      key={mode}
                      type="button"
                      className={`payment-mode-btn-${mode}`}
                      ref={isActive ? paymentModeRef : null}
                      onKeyDown={(e) => handlePaymentModeButtonKeyDown(e, mode)}
                      style={{
                        background: isActive ? 'var(--accent)' : 'var(--bg-3)',
                        border: isActive ? '1px solid var(--accent)' : '1px solid var(--border)',
                        borderRadius: 'var(--radius-md)',
                        padding: '10px 0',
                        color: isActive ? '#ffffff' : 'var(--text-primary)',
                        fontSize: '0.85rem',
                        fontWeight: '700',
                        textTransform: 'capitalize',
                        cursor: 'pointer',
                        transition: 'all 0.15s ease',
                        outline: 'none',
                        boxShadow: 'none'
                      }}
                      onClick={() => {
                        setForm(f => {
                          const updates = { ...f, payment_mode: mode }
                          if (mode === 'credit') {
                            updates.amount_received = '0'
                          } else {
                            updates.amount_received = pay.toFixed(2)
                          }
                          return updates
                        })
                        setTimeout(() => amountReceivedRef.current?.focus(), 30)
                      }}
                    >
                      {mode}
                    </button>
                  )
                })}
              </div>

              {/* Dynamic UPI QR Code */}
              {form.payment_mode === 'upi' && grandTotal > 0 && (
                <div style={{
                  background: 'var(--bg-3)',
                  borderRadius: 'var(--radius-md)',
                  padding: '12px',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: '8px',
                  border: '1px solid var(--border)'
                }}>
                  <img
                    src={qrImageUrl(buildUpiUri({
                      vpa: upiVpa,
                      payeeName: localStorage.getItem('billing_user')
                        ? JSON.parse(localStorage.getItem('billing_user')).business_name || 'BizAssist Merchant'
                        : 'BizAssist Merchant',
                      amount: pay,
                      note: 'POS-Invoicing',
                    }))}
                    alt="UPI QR Code"
                    style={{ width: 120, height: 120 }}
                  />
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                    VPA: <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{upiVpa}</span>
                  </div>
                  {/* Soundbox Simulator Panel
                  <div style={{
                    width: '100%',
                    padding: '10px',
                    borderRadius: 'var(--radius-sm)',
                    background: soundboxStatus === 'waiting' ? '#eff6ff' : soundboxStatus === 'success' ? '#f0fdf4' : '#fafaf9',
                    border: soundboxStatus === 'waiting' ? '1px solid #bfdbfe' : soundboxStatus === 'success' ? '1px solid #bbf7d0' : '1px solid var(--border)',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    gap: '6px',
                    transition: 'all 0.3s ease',
                    marginTop: '4px'
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{ fontSize: '1.1rem' }}><VolumeIcon size={16} /></span>
                      <span style={{ fontSize: '0.75rem', fontWeight: 800, color: soundboxStatus === 'waiting' ? '#1d4ed8' : soundboxStatus === 'success' ? '#15803d' : '#475569' }}>
                        UPI Soundbox Simulator
                      </span>
                    </div>

                    {soundboxStatus === 'waiting' && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.7rem', color: '#2563eb', fontWeight: 600 }}>
                        <span className="spinner" style={{ width: 12, height: 12, border: '2px solid #2563eb', borderTopColor: 'transparent', display: 'inline-block', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
                        Waiting for payment... (4s)
                      </div>
                    )}

                    {soundboxStatus === 'success' && (
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2px' }}>
                        <span style={{ fontSize: '0.7rem', color: '#16a34a', fontWeight: 700 }}>
                          <CheckIcon size={18} style={{ color: 'var(--success)', display: 'inline-block', verticalAlign: 'middle', marginRight: 6 }} /> Payment Successful!
                        </span>
                        <span style={{ fontSize: '0.65rem', color: '#15803d', textAlign: 'center' }}>
                          Voice confirmation played. Auto-printing...
                        </span>
                      </div>
                    )}
                  </div>
                  */}
                </div>
              )}

              {grandTotal > 50000 && (
                <div style={{
                  background: 'var(--warning-dim)',
                  border: '1px solid rgba(255,149,0,0.15)',
                  borderRadius: 'var(--radius-md)',
                  padding: '10px 12px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  fontSize: '0.8rem',
                  color: 'var(--warning)',
                  fontWeight: '600'
                }}>
                  <AlertIcon size={14} style={{ flexShrink: 0 }} />
                  <span><strong>E-Way Bill Required:</strong> Total exceeds ₹50,000 threshold.</span>
                </div>
              )}

              <div style={{ borderTop: '1px dotted var(--border)', margin: '4px 0' }} />

              {/* Change to return (positive) OR balance still due (negative → red) */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                  {balance < 0 ? 'Balance still due' : 'Change to return'}
                </span>
                <span style={{ fontSize: '1.25rem', fontWeight: 800, color: balance < 0 ? 'var(--danger)' : 'var(--success)' }}>
                  {balance < 0 ? `− ${fmt(Math.abs(balance))}` : fmt(balance)}
                </span>
              </div>

              {/* Actions */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '4px' }}>
                <button
                  type="button"
                  disabled={submitting}
                  style={{
                    background: 'var(--accent)',
                    border: 'none',
                    borderRadius: 'var(--radius-md)',
                    padding: '12px',
                    color: '#ffffff',
                    fontSize: '1rem',
                    fontWeight: 'bold',
                    cursor: 'pointer',
                    transition: 'background 0.15s ease'
                  }}
                  onClick={() => guardedSave(true)}
                >
                  {submitting ? 'Saving Invoice...' : (isCredit ? 'Save & Print · Enter' : 'Paid & Print · Enter')}
                </button>
                
                <button
                  type="button"
                  disabled={submitting}
                  style={{
                    background: 'transparent',
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius-md)',
                    padding: '8px',
                    color: 'var(--text-muted)',
                    fontSize: '0.85rem',
                    fontWeight: '600',
                    cursor: 'pointer',
                    transition: 'color 0.15s ease'
                  }}
                  onClick={() => guardedSave(false)}
                >
                  Save Bill Only (Ctrl+S)
                </button>
              </div>
            </div>

          </div>
        </div>
      </div>


    </>
  )
}
