import React, { useEffect, useState, useCallback, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import AppLayout from '../layouts/AppLayout'
import { useAuth, useBusinessConfig } from '../contexts/AuthContext'
import { SettingsIcon, SearchIcon, AlertIcon, CheckIcon, CloseIcon, BillsIcon, ChevronRightIcon } from '../components/Icons'
// Shared formatting helpers (money / today / amount-in-words) live in utils/format.
import { fmt, getTodayDateStr, numberToWords } from '../utils/format'
// Invoice money-math (line totals, intra/inter GST split, change due) — pure + tested.
import { lineTotal, computeInvoiceTotals, changeDue, buildInvoicePayload, columnTotals, suggestedTenders, schemeDiscount, gstSlabBreakdown } from '../utils/invoiceMath'
import { logger } from '../utils/logger'
import TotalBreakupModal from '../components/sales/TotalBreakupModal'
import PosTotalBar from '../components/sales/PosTotalBar'
import InvoiceBreakdownCard from '../components/sales/InvoiceBreakdownCard'
import TenderChips from '../components/sales/TenderChips'
import CheckoutModal from '../components/sales/CheckoutModal'
import usePaymentFlow from '../hooks/usePaymentFlow'
import { getHeaderLayout } from '../utils/printLayout'

const colLabels = {
  sku: 'Item Code',
  name: 'Item Name',
  batch: 'Batch',
  price_option: 'Price Option',
  mrp: 'MRP',
  hsn: 'HSN',
  qty: 'Quantity',
  unit: 'Unit',
  rate: 'Price Per Unit Before Tax',
  price: 'Total Before Tax',
  discount: 'Discount',
  tax: 'Tax',
  total: 'Total After Tax'
}

const emptyItem = () => ({ product_id: '', product: '', qty: 1, price: '', discount: 0, sku: '—', is_custom: false, batch_no: '', expiry_date: '', selected_price: '', selected_price_label: 'Standard Price' })

const defaultForm = {
  customer_id: '',
  godown_id: '',
  due_date: getTodayDateStr(),
  items: [],
  gst_enabled: false,
  notes: '',
  payment_mode: 'cash',
  amount_received: '',
  bill_discount_type: 'amount',   // 'amount' (flat ₹) | 'percent'
  bill_discount_value: '',        // the ₹ or % the cashier types at checkout
  cash_discount: '',              // POST-tax cash discount / round-off (₹) — reduces payable, not GST (R4)
}

export default function Sales() {
  const { authFetch, profile, user } = useAuth()
  const { config, attributesSchema, t } = useBusinessConfig()
  const navigate = useNavigate()

  const [customers, setCustomers]     = useState([])
  const [products, setProducts]       = useState([])
  const [godowns, setGodowns]         = useState([])
  const [loading, setLoading]         = useState(true)
  const [settings, setSettings]       = useState(null)
  const [submitting, setSubmitting]   = useState(false)
  const [alert, setAlert]             = useState(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(-1)
  const [showSettingsModal, setShowSettingsModal] = useState(false)
  const [showBreakupModal, setShowBreakupModal] = useState(false)
  const [bindingAction, setBindingAction] = useState(null)
  const [dbInvoices, setDbInvoices]   = useState([])
  const [showPayConfirmModal, setShowPayConfirmModal] = useState(false)

  const defaultFuncKeys = {
    qtyFocus: 'F2',
    discountFocus: 'F3',
    removeItem: 'F4',
    amountReceivedFocus: 'F8',
    barcodeFocus: 'F9',
    customerFocus: 'F11',
    remarksFocus: 'F12',
    configureShortcuts: 'F1',
    paymentProceed: 'Enter',
    paymentCancel: 'Escape',
    // Payment flow navigation
    flowForward: 'Enter',
    flowBack: 'Shift+Enter',
    // Key to move from item scanning → payment flow (customer → amount → mode)
    proceedToPayment: 'Escape',
  }

  const [funcKeys, setFuncKeys] = useState(() => {
    const saved = localStorage.getItem('pos_func_keys')
    if (saved) {
      try {
        return JSON.parse(saved)
      } catch (e) {
        logger.error('[SALES] failed to parse pos_func_keys', e)
      }
    }
    return defaultFuncKeys
  })

  const [columnOrder, setColumnOrder] = useState(() => {
    const saved = localStorage.getItem('pos_column_order')
    if (saved) {
      try {
        const parsed = JSON.parse(saved)
        if (Array.isArray(parsed) && parsed.length > 0) {
          if (!parsed.includes('batch')) {
            const nameIdx = parsed.indexOf('name')
            if (nameIdx !== -1) {
              parsed.splice(nameIdx + 1, 0, 'batch')
            } else {
              parsed.push('batch')
            }
          }
          if (!parsed.includes('price_option')) {
            const batchIdx = parsed.indexOf('batch')
            if (batchIdx !== -1) {
              parsed.splice(batchIdx + 1, 0, 'price_option')
            } else {
              parsed.push('price_option')
            }
          }
          if (!parsed.includes('rate')) {
            const qtyIdx = parsed.indexOf('qty')
            if (qtyIdx !== -1) {
              parsed.splice(qtyIdx + 1, 0, 'rate')
            } else {
              parsed.push('rate')
            }
          }
          return parsed
        }
      } catch (e) {
        logger.error('[SALES] failed to parse pos_column_order', e)
      }
    }
    return ['sku', 'name', 'batch', 'price_option', 'mrp', 'hsn', 'qty', 'unit', 'rate', 'price', 'discount', 'tax', 'total']
  })

  const [showHotkeySettingsModal, setShowHotkeySettingsModal] = useState(false)
  const [priceSelectorIndex, setPriceSelectorIndex] = useState(null)
  const [selectedPriceOptIndex, setSelectedPriceOptIndex] = useState(0)

  const handleMoveColumn = (index, direction) => {
    const nextOrder = [...columnOrder]
    if (direction === 'up' && index > 0) {
      const temp = nextOrder[index - 1]
      nextOrder[index - 1] = nextOrder[index]
      nextOrder[index] = temp
    } else if (direction === 'down' && index < nextOrder.length - 1) {
      const temp = nextOrder[index + 1]
      nextOrder[index + 1] = nextOrder[index]
      nextOrder[index] = temp
    }
    setColumnOrder(nextOrder)
    localStorage.setItem('pos_column_order', JSON.stringify(nextOrder))
  }

  const getStickyLeftOffsets = (order, visibleObj) => {
    const offsets = {}
    let currentOffset = 40
    let freezeAllowed = true

    for (let i = 0; i < order.length; i++) {
      const col = order[i]
      const isVisible = col === 'sku' ? visibleObj.sku :
                        col === 'mrp' ? visibleObj.mrp :
                        col === 'hsn' ? visibleObj.hsn :
                        col === 'unit' ? visibleObj.unit :
                        col === 'discount' ? visibleObj.discount :
                        col === 'tax' ? visibleObj.tax :
                        col === 'batch' ? visibleObj.batch :
                        col === 'price_option' ? visibleObj.price_option :
                        col === 'rate' ? visibleObj.rate :
                        true

      if (!isVisible) continue

      if (freezeAllowed && (col === 'sku' || col === 'name')) {
        offsets[col] = currentOffset
        if (col === 'sku') {
          currentOffset += 95
        } else if (col === 'name') {
          currentOffset += 180
        }
      } else {
        freezeAllowed = false
      }
    }
    return offsets
  }

  const getPriceOptions = (item) => {
    if (!item || item.is_custom || !item.product_id) return []
    const p = products.find(prod => prod.id === item.product_id)
    if (!p) return []

    const rawOptions = []

    // Base standard prices first
    rawOptions.push(
      { label: 'Standard Price', price: p.selling_price, created_at: null, formatted_date: 'Base Product' },
      { label: 'Wholesale Price', price: p.wholesale_price, created_at: null, formatted_date: 'Base Product' },
      { label: 'Distributor Price', price: p.distributor_price, created_at: null, formatted_date: 'Base Product' },
      { label: 'MRP', price: p.mrp, created_at: null, formatted_date: 'Base Product' }
    )

    // Gather batches and sort them by created_at descending (latest first)
    const batches = productBatches[item.product_id] || []
    const sortedBatches = [...batches].sort((a, b) => {
      const dateA = a.created_at ? new Date(a.created_at) : new Date(0)
      const dateB = b.created_at ? new Date(b.created_at) : new Date(0)
      return dateB - dateA
    })

    sortedBatches.forEach(b => {
      if (b.selling_price && b.selling_price > 0) {
        rawOptions.push({
          label: `Batch ${b.batch_no || '—'} Price`,
          price: b.selling_price,
          created_at: b.created_at,
          formatted_date: b.created_at ? new Date(b.created_at).toLocaleDateString('en-GB') : '—'
        })
      }
      if (b.mrp && b.mrp > 0) {
        rawOptions.push({
          label: `Batch ${b.batch_no || '—'} MRP`,
          price: b.mrp,
          created_at: b.created_at,
          formatted_date: b.created_at ? new Date(b.created_at).toLocaleDateString('en-GB') : '—'
        })
      }
    })

    const seen = new Set()
    const options = []
    rawOptions.forEach(opt => {
      const val = parseFloat(opt.price)
      if (val && val > 0 && !seen.has(val)) {
        seen.add(val)
        options.push({
          label: opt.label,
          price: val,
          created_at: opt.created_at,
          formatted_date: opt.formatted_date
        })
      }
    })

    return options
  }

  const handlePriceInputFocus = (index) => {
    // Popup selector is disabled in favor of inline dropdown and rate columns
    setPriceSelectorIndex(null)
  }

  const handleSelectPriceOption = (price, label) => {
    if (priceSelectorIndex !== null) {
      setForm(f => {
        const items = [...f.items]
        const item = items[priceSelectorIndex]
        if (item) {
          const p = products.find(prod => prod.id === item.product_id)
          let newPrice = price
          let newDiscount = 0
          const qty = parseFloat(item.qty) || 1
          
          if (p && parseFloat(p.mrp) > 0 && price <= parseFloat(p.mrp)) {
             newPrice = parseFloat(p.mrp)
             newDiscount = schemeDiscount(p.mrp, price, qty)
          }

          items[priceSelectorIndex] = {
            ...item,
            price: newPrice,
            discount: newDiscount,
            selected_price: price,
            selected_price_label: label || 'Custom Price'
          }
        }
        return { ...f, items }
      })
      setPriceSelectorIndex(null)
      setSelectedPriceOptIndex(0)
      setTimeout(() => barcodeRef.current?.focus(), 50)
    }
  }

  // Update a line's quantity AND keep the auto "MRP-as-price" scheme discount in
  // sync with qty. The discount is stored as an absolute amount = (MRP − chosen
  // price) × qty, so it MUST rescale when qty changes — otherwise the line bills
  // toward MRP (the overcharge bug: chose ₹200 at qty 1, raised to qty 4, was
  // billing ₹920 instead of ₹800). Mirrors the re-add path. We only touch the
  // discount while the line is in scheme mode (price == MRP, a chosen price at/
  // below MRP, no manually-typed price); otherwise qty alone changes.
  // Returns a copy of `item` with qty set and the MRP-scheme discount rescaled to
  // the new qty. EVERY qty-change path (typing, +, arrow keys) must go through
  // this, or the absolute discount stays at its old-qty value and the line bills
  // toward MRP. No rescale when the cashier typed a custom price (no scheme).
  const withQty = (item, newQty) => {
    const updated = { ...item, qty: newQty }
    if (updated.product_id) {
      const p = products.find(prod => prod.id === updated.product_id)
      const mrp = p ? (parseFloat(p.mrp) || 0) : (parseFloat(updated.mrp) || 0)
      const selPrice = parseFloat(updated.selected_price) || 0
      
      if (mrp > 0 && selPrice <= mrp) {
        updated.price = mrp
        updated.discount = schemeDiscount(mrp, selPrice, newQty)
      } else {
        updated.price = selPrice
        updated.discount = 0
      }
    }
    return updated
  }

  const handleQtyChange = (index, value) => {
    setForm(f => {
      const items = [...f.items]
      if (!items[index]) return f
      items[index] = withQty(items[index], value)
      return { ...f, items }
    })
  }

  const [tabs, setTabs] = useState(() => {
    const savedTabsStr = localStorage.getItem('pos_minimized_tabs')
    const savedActiveId = localStorage.getItem('pos_minimized_active_id')
    if (savedTabsStr && savedActiveId) {
      try {
        const savedTabs = JSON.parse(savedTabsStr)
        if (Array.isArray(savedTabs) && savedTabs.length > 0) {
          return savedTabs
        }
      } catch (e) {
        logger.error('[SALES] failed to parse minimized tabs', e)
      }
    }
    return [
      { id: '1', name: 'Invoice #1001', form: defaultForm }
    ]
  })

  const [activeTabId, setActiveTabId] = useState(() => {
    const savedActiveId = localStorage.getItem('pos_minimized_active_id')
    if (savedActiveId) return savedActiveId
    return '1'
  })

  const activeTab = tabs.find(t => t.id === activeTabId) || tabs[0] || { id: '1', name: 'Invoice #1001', form: defaultForm }
  const form = activeTab.form

  const setForm = useCallback((updater) => {
    setTabs(prevTabs => prevTabs.map(t => {
      if (t.id === activeTabId) {
        const nextForm = typeof updater === 'function' ? updater(t.form) : updater
        return { ...t, form: nextForm }
      }
      return t
    }))
  }, [activeTabId])

  useEffect(() => {
    localStorage.setItem('pos_minimized_tabs', JSON.stringify(tabs))
    localStorage.setItem('pos_minimized_active_id', activeTabId)
  }, [tabs, activeTabId])

  useEffect(() => {
    setPriceSelectorIndex(null)
    setSelectedPriceOptIndex(0)
  }, [activeTabId])

  const syncTabNames = useCallback((currentTabs, existingInvoices) => {
    let maxDbNum = 0
    let prefix = 'INV-'
    existingInvoices.forEach(inv => {
      const invNo = inv.invoice_number || inv.invoice_no || ''
      if (invNo) {
        const match = invNo.match(/([a-zA-Z0-9_\-]+?)?(\d+)/)
        if (match) {
          const pfx = match[1] || ''
          const num = parseInt(match[2])
          if (num > maxDbNum) {
            maxDbNum = num
            prefix = pfx
          }
        }
      }
    })
    const nextDbVal = maxDbNum + 1

    const usedNumbers = new Set(existingInvoices.map(inv => inv.invoice_number || inv.invoice_no || ''))
    
    let currentNum = nextDbVal
    return currentTabs.map(tab => {
      const hasItems = tab.form?.items?.length > 0
      const currentTabName = tab.name
      
      if (hasItems && !usedNumbers.has(currentTabName) && currentTabName !== 'Invoice #1001' && !currentTabName.startsWith('Invoice #')) {
        usedNumbers.add(currentTabName)
        return tab
      } else {
        let candidate = `${prefix}${String(currentNum).padStart(4, '0')}`
        while (usedNumbers.has(candidate)) {
          currentNum++
          candidate = `${prefix}${String(currentNum).padStart(4, '0')}`
        }
        usedNumbers.add(candidate)
        currentNum++
        return { ...tab, name: candidate }
      }
    })
  }, [])

  const handleToggleColumnSetting = async (key, val) => {
    if (!settings) return
    const updated = {
      ...settings,
      transactions: {
        ...settings.transactions,
        [key]: val
      }
    }
    setSettings(updated)
    try {
      await authFetch('/settings', {
        method: 'PUT',
        body: JSON.stringify(updated)
      })
    } catch (err) {
      logger.error('[SALES] failed to save settings', err)
    }
  }



  useEffect(() => {
    localStorage.removeItem('pos_minimized')
    window.dispatchEvent(new Event('pos_minimized_changed'))
  }, [])
  
  const [productBatches, setProductBatches] = useState({})
  
  const [upiVpa, setUpiVpa] = useState(() => localStorage.getItem('pos_upi_vpa') || 'bizassist@upi')
  const [merchantState, setMerchantState] = useState(() => localStorage.getItem('pos_merchant_state') || '37')

  const barcodeRef = useRef(null)
  const tableContainerRef = useRef(null)

  // Focus handling is managed directly in openPaymentFlow

  // Dynamic empty row count — fills the visible table area
  const [emptyRowCount, setEmptyRowCount] = useState(12)
  useEffect(() => {
    const el = tableContainerRef.current
    if (!el) return
    const ROW_H = 35
    const HEAD_H = 37
    const update = () => {
      const used = HEAD_H + form.items.length * ROW_H
      const extra = Math.max(3, Math.floor((el.clientHeight - used) / ROW_H))
      setEmptyRowCount(extra)
    }
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [form.items.length])

  const getNextInvoiceNo = useCallback((existingInvoices) => {
    let maxNum = 0
    let prefix = 'INV-'
    existingInvoices.forEach(inv => {
      const invNo = inv.invoice_number || inv.invoice_no || ''
      if (invNo) {
        const match = invNo.match(/([a-zA-Z0-9_\-]+?)?(\d+)/)
        if (match) {
          const pfx = match[1] || ''
          const num = parseInt(match[2])
          if (num > maxNum) {
            maxNum = num
            prefix = pfx
          }
        }
      }
    })
    const nextVal = maxNum > 0 ? maxNum + 1 : 1
    const padded = String(nextVal).padStart(4, '0')
    return `${prefix}${padded}`
  }, [])

  /**
   * matchesKey — checks if a keyboard event matches a configurable key descriptor.
   * Descriptors can be plain keys like "Enter", "F5", "Escape",
   * or modifier combos like "Shift+Enter", "Shift+F5", "Ctrl+Enter".
   */
  const matchesKey = (e, descriptor) => {
    if (!descriptor) return false
    const parts = descriptor.split('+')
    const key = parts[parts.length - 1]          // last segment is the actual key
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

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([
      authFetch('/billing/customers').then(r => r.ok ? r.json() : []).catch(() => []),
      authFetch('/products?per_page=1000').then(r => r.ok ? r.json() : { items: [] }).catch(() => ({ items: [] })),
      authFetch('/billing/godowns').then(r => r.ok ? r.json() : []).catch(() => []),
      authFetch('/settings').then(r => r.ok ? r.json() : null).catch(() => null),
      authFetch('/billing/invoices').then(r => r.ok ? r.json() : []).catch(() => []),
    ]).then(([cust, prod, gods, sett, invs]) => {
      const custItems = Array.isArray(cust) ? cust : (cust && Array.isArray(cust.items) ? cust.items : [])
      const prodItems = prod && Array.isArray(prod.items) ? prod.items : []
      setCustomers(custItems)
      setProducts(prodItems)
      setGodowns(gods)
      setDbInvoices(invs)
      if (sett) {
        setSettings(sett)
      }
      
      const defaultGodownId = gods.length > 0 ? gods[0].id : ''
      setForm(f => ({
        ...f,
        customer_id: f.customer_id || '',
        godown_id: f.godown_id || defaultGodownId
      }))

      // Dynamically rename initial tab to match database next number and resolve duplicates
      setTabs(prev => syncTabNames(prev, invs))
    }).finally(() => {
      setLoading(false)
      setTimeout(() => barcodeRef.current?.focus(), 100)
    })
  }, [authFetch, setForm, getNextInvoiceNo])

  useEffect(() => {
    load()
    window.addEventListener('focus', load)
    return () => {
      window.removeEventListener('focus', load)
    }
  }, [load])

  // Listen for window focus to reload batches/dated prices for all items in the cart
  useEffect(() => {
    const handleFocusRefresh = async () => {
      if (form.items && form.items.length > 0) {
        for (const item of form.items) {
          if (item.product_id && !item.is_custom) {
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
              logger.error('[SALES] failed to update batches on focus', err)
            }
          }
        }
      }
    }

    window.addEventListener('focus', handleFocusRefresh)
    return () => {
      window.removeEventListener('focus', handleFocusRefresh)
    }
  }, [form.items, authFetch])

  const colVisible = {
    sku: settings?.transactions?.pos_show_sku !== false,
    unit: settings?.transactions?.pos_show_unit !== false,
    discount: settings?.transactions?.pos_show_discount !== false,
    tax: settings?.transactions?.pos_show_tax !== false,
    hsn: settings?.transactions?.pos_show_hsn === true,
    mrp: settings?.transactions?.pos_show_mrp === true,
    batch: settings?.transactions?.pos_show_batch !== false,
    price_option: true,
    rate: true
  }

  const handleNewBill = () => {
    const newId = Date.now().toString()
    const newForm = {
      ...defaultForm,
      customer_id: '',
      godown_id: godowns.length > 0 ? godowns[0].id : '',
      due_date: getTodayDateStr(),
    }
    setTabs(prev => {
      const updated = [...prev, { id: newId, name: 'TEMP', form: newForm }]
      return syncTabNames(updated, dbInvoices)
    })
    setActiveTabId(newId)
    setPriceSelectorIndex(null)
    setSelectedPriceOptIndex(0)
    setTimeout(() => barcodeRef.current?.focus(), 100)
  }

  const closeTab = useCallback((tabId, e, forceClose = false) => {
    if (e) e.stopPropagation()
    const tabToClose = tabs.find(t => t.id === tabId)
    if (!forceClose && tabToClose && tabToClose.form.items.length > 0) {
      if (!window.confirm(`Are you sure you want to close ${tabToClose.name}? Unsaved changes will be lost.`)) {
        return
      }
    }
    
    setPriceSelectorIndex(null)
    setSelectedPriceOptIndex(0)

    if (tabs.length === 1) {
      const newId = Date.now().toString()
      const newForm = {
        ...defaultForm,
        customer_id: '',
        godown_id: godowns.length > 0 ? godowns[0].id : '',
        due_date: getTodayDateStr(),
      }
      setTabs([{ id: newId, name: 'TEMP', form: newForm }])
      setActiveTabId(newId)
      authFetch('/billing/invoices').then(r => r.ok ? r.json() : []).then(invs => {
        setTabs(prev => syncTabNames(prev, invs))
      }).catch(() => {})
      setTimeout(() => barcodeRef.current?.focus(), 100)
      return
    }

    const newTabs = tabs.filter(t => t.id !== tabId)
    setTabs(newTabs)
    if (activeTabId === tabId) {
      const remainingTab = newTabs[newTabs.length - 1]
      setActiveTabId(remainingTab.id)
    }
  }, [tabs, activeTabId, godowns, authFetch, syncTabNames])

  const handleMinimize = () => {
    localStorage.setItem('pos_minimized', 'true')
    window.dispatchEvent(new Event('pos_minimized_changed'))
    navigate('/')
  }


  
  useEffect(() => {
    if (!form.customer_id || customers.length === 0) return
    const cust = customers.find(c => String(c.id) === String(form.customer_id))
    if (cust) {
      setField('gst_enabled', !!cust.gstin)
      
      const tier = cust.price_tier || 'standard'
      setForm(f => {
        const items = f.items.map(it => {
          if (it.is_custom || it.has_custom_price) return it
          const prod = products.find(p => p.id === it.product_id)
          if (!prod) return it
          let basePrice = prod.selling_price || 0
          if (tier === 'wholesale') {
            basePrice = prod.wholesale_price || basePrice
          } else if (tier === 'distributor') {
            basePrice = prod.distributor_price || basePrice
          }
          
          let finalPrice = basePrice
          let finalDiscount = 0
          if (prod.mrp && parseFloat(prod.mrp) > 0 && basePrice <= parseFloat(prod.mrp)) {
            finalPrice = parseFloat(prod.mrp)
            finalDiscount = finalPrice - basePrice
          }
          
          return { ...it, price: finalPrice, discount: finalDiscount }
        })
        return { ...f, items }
      })
    }
  }, [form.customer_id, customers, products])

  const setField = (k, v) => setForm(f => ({ ...f, [k]: v }))
  
  const setItem = (i, kOrUpdates, v) => setForm(f => {
    const items = [...f.items]
    const item = items[i]
    if (item) {
      const updates = typeof kOrUpdates === 'object' ? kOrUpdates : { [kOrUpdates]: v }
      const updatedItem = { ...item, ...updates }
      
      const qty = parseFloat(updatedItem.qty) || 0
      const mrpFieldVal = parseFloat(updatedItem.price) || 0
      const selPrice = parseFloat(updatedItem.selected_price) || 0
      const p = products.find(prod => prod.id === updatedItem.product_id)
      const mrp = p ? (parseFloat(p.mrp) || 0) : mrpFieldVal
      
      if (updatedItem.product_id) {
        if (mrp > 0 && selPrice <= mrp) {
          updatedItem.price = mrp
          updatedItem.discount = schemeDiscount(mrp, selPrice, qty)
        } else {
          updatedItem.price = selPrice
          updatedItem.discount = 0
        }
      } else {
        if ('selected_price' in updates) {
          updatedItem.price = parseFloat(updatedItem.selected_price) || 0
        }
      }
      
      items[i] = updatedItem
    }
    return { ...f, items }
  })
  
  const addCustomItemToCart = useCallback(() => {
    setForm(f => {
      let items = [...f.items]
      items.push({
        product_id: '',
        product: '',
        price: '',
        sku: '—',
        discount: 0,
        qty: 1,
        is_custom: true,
        batch_no: '',
        expiry_date: '',
        selected_price: '',
        selected_price_label: 'Standard Price'
      })
      return { ...f, items }
    })
    setSearchQuery('')
    setSelectedIndex(-1)
  }, [])

  const removeItem = (i) => {
    setForm(f => ({ ...f, items: f.items.filter((_, idx) => idx !== i) }))
    setPriceSelectorIndex(null)
    setSelectedPriceOptIndex(0)
  }

  // Buyer state vs merchant state decides intra (CGST+SGST) vs inter (IGST).
  const selectedCust = customers.find(c => String(c.id) === String(form.customer_id))
  const custState = selectedCust && selectedCust.gstin ? selectedCust.gstin.trim().slice(0, 2) : ''
  const isIntrastate = custState ? custState === merchantState : true

  // Money-math is pure + unit-tested in utils/invoiceMath (lineTotal imported above).
  const { subtotal, discount: billDiscountAmt, discountedSubtotal, cgstAmt, sgstAmt, igstAmt, gstAmt, grandTotal, roundOff, cashDiscount: cashDiscountAmt, payable } =
    computeInvoiceTotals(form.items, {
      isIntrastate,
      billDiscountType: form.bill_discount_type,
      billDiscountValue: form.bill_discount_value,
      cashDiscount: parseFloat(form.cash_discount) || 0,
    })
  const colFooter = columnTotals(form.items)   // per-column totals for the cart footer row

  // Receipt header lines, rendered in the saved order + alignment (Settings → Print).
  const renderReceiptHeaderLine = (key, align) => {
    const p = settings?.print || {}
    const textAlign = align || 'center'
    switch (key) {
      case 'logo':
        if (!p.print_logo || !profile?.logo) return null
        return <div key="logo" style={{ textAlign, marginBottom: 2 }}><img src={profile.logo} alt="logo" style={{ maxHeight: 26, maxWidth: 96, objectFit: 'contain' }} /></div>
      case 'company_name':
        if (p.print_company_name === false) return null
        return <h3 key="company_name" style={{ textAlign }}>{(profile?.business_name || 'BIZASSIST POS').toUpperCase()}</h3>
      case 'company_address':
        if (p.print_company_address === false || !profile?.address) return null
        return <p key="company_address" style={{ textAlign }}>{profile.address}</p>
      case 'company_contact': {
        const showPhone = p.print_company_phone !== false && profile?.phone
        const showEmail = p.print_company_email !== false && profile?.email
        if (!showPhone && !showEmail) return null
        return <p key="company_contact" style={{ textAlign }}>{showPhone ? `Phone: ${profile.phone}` : ''}{showPhone && showEmail ? '  ·  ' : ''}{showEmail ? `Email: ${profile.email}` : ''}</p>
      }
      case 'gstin':
        if (p.print_gstin === false || !profile?.gstin) return null
        return <p key="gstin" style={{ textAlign }}>GSTIN: {profile.gstin}</p>
      default:
        return null
    }
  }

  const amountReceivedNum = parseFloat(form.amount_received) || 0
  // Change is against the PAYABLE (= grand total − cash discount). With no cash
  // discount, payable === grandTotal, so this is unchanged for existing flows.
  const changeToReturn = changeDue(amountReceivedNum, payable)

  const {
    showPaymentPopup,
    setShowPaymentPopup,
    paymentFocusTarget,
    setPaymentFocusTarget,
    openPaymentFlow,
    executeSaveInvoice,
    handleSaveInvoice,
  } = usePaymentFlow({
    form,
    setForm,
    grandTotal,
    payable,
    cashDiscountAmt,
    gstAmt,
    billDiscountAmt,
    changeToReturn,
    activeTab,
    activeTabId,
    closeTab,
    setTabs,
    syncTabNames,
    setDbInvoices,
    settings,
    authFetch,
    setAlert,
    setSubmitting,
    barcodeRef,
  })

  const entryMode = config?.billing?.entry_mode || 'search'
  const groupedProducts = products.reduce((acc, p) => {
    const cat = p.category || 'General';
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(p);
    return acc;
  }, {})

  const fetchBatchesForProduct = useCallback(async (productId) => {
    if (!productId || productBatches[productId]) return
    try {
      const res = await authFetch(`/products/${productId}/stock`)
      if (res.ok) {
        const data = await res.json()
        setProductBatches(prev => ({
          ...prev,
          [productId]: data.batches || []
        }))
      }
    } catch (err) {
      logger.error('[SALES] failed to fetch batches', err)
    }
  }, [authFetch, productBatches])

  const addProductToCart = useCallback(async (product) => {
    // 1. Fetch batches to get the latest stock/price options
    let batches = null
    if (product.id) {
      try {
        const res = await authFetch(`/products/${product.id}/stock`)
        if (res.ok) {
          const data = await res.json()
          batches = data.batches || []
          setProductBatches(prev => ({ ...prev, [product.id]: batches }))
        }
      } catch (err) {
        logger.error('[SALES] batch fetch failed', err)
      }
    }

    // Determine if the product is already in the cart
    const isAlreadyPresent = form.items.some(it => it.product_id === product.id)

    // Resolve default price tier based on customer tier OR profile category type
    let resolvedTier = 'standard'
    setForm(f => {
      const cust = customers.find(c => String(c.id) === String(f.customer_id))
      let tier = cust ? (cust.price_tier || 'standard') : 'standard'
      
      if (tier === 'standard') {
        let businessDefaultTier = 'standard'
        const bizCategory = (profile?.business_category || profile?.business_type || profile?.category || '').toLowerCase()
        const savedUser = localStorage.getItem('billing_user')
        let userRole = ''
        if (savedUser) {
          try {
            userRole = (JSON.parse(savedUser).role || '').toLowerCase()
          } catch (e) {
            logger.debug('[SALES] could not parse billing_user for price tier; defaulting role to ""', e)
          }
        }
        if (bizCategory.includes('wholesale') || userRole.includes('wholesale')) {
          businessDefaultTier = 'wholesale'
        } else if (bizCategory.includes('distributor') || userRole.includes('distributor')) {
          businessDefaultTier = 'distributor'
        }
        tier = businessDefaultTier
      }
      resolvedTier = tier
      return f
    })

    const defaultPrice = (() => {
      let price = product.selling_price || 0
      if (resolvedTier === 'wholesale') {
        price = product.wholesale_price || price
      } else if (resolvedTier === 'distributor') {
        price = product.distributor_price || price
      }
      return price
    })()

    setForm(f => {
      let items = [...f.items]
      const existingIdx = items.findIndex(it => it.product_id === product.id)
      if (existingIdx !== -1) {
        items[existingIdx] = {
          ...items[existingIdx],
          qty: (parseFloat(items[existingIdx].qty) || 0) + 1,
          price: items[existingIdx].price, // preserve already selected price
          cgst_rate: product.cgst_rate || 0,
          sgst_rate: product.sgst_rate || 0,
          igst_rate: product.igst_rate || 0,
        }
        const updatedItem = items[existingIdx]
        const qty = updatedItem.qty
        const selPrice = parseFloat(updatedItem.selected_price) || 0
        const mrp = parseFloat(product.mrp) || 0
        if (mrp > 0 && selPrice <= mrp) {
          updatedItem.discount = schemeDiscount(mrp, selPrice, qty)
        }
      } else {
        let finalPrice = defaultPrice
        let finalDiscount = 0
        if (product.mrp && parseFloat(product.mrp) > 0 && defaultPrice <= parseFloat(product.mrp)) {
          finalPrice = parseFloat(product.mrp)
          finalDiscount = schemeDiscount(product.mrp, defaultPrice, 1)
        }
        items.push({
          product_id: product.id,
          product: product.name,
          price: finalPrice,
          sku: product.sku || product.barcode || '—',
          discount: finalDiscount,
          qty: 1,
          is_custom: false,
          batch_no: '',
          expiry_date: '',
          cgst_rate: product.cgst_rate || 0,
          sgst_rate: product.sgst_rate || 0,
          igst_rate: product.igst_rate || 0,
          selected_price: defaultPrice,
          selected_price_label: resolvedTier === 'wholesale' ? 'Wholesale Price' :
                                resolvedTier === 'distributor' ? 'Distributor Price' :
                                'Standard Price'
        })
      }
      return { ...f, items }
    })
    
    setSearchQuery('')
    setSelectedIndex(-1)
    
    // Check if there are extra prices apart from standard 4 base prices
    const standardBasePrices = [
      parseFloat(product.selling_price),
      parseFloat(product.wholesale_price),
      parseFloat(product.distributor_price),
      parseFloat(product.mrp)
    ].filter(v => v && v > 0)

    const rawOptions = [
      { label: 'Standard Price', price: product.selling_price },
      { label: 'Wholesale Price', price: product.wholesale_price },
      { label: 'Distributor Price', price: product.distributor_price },
      { label: 'MRP', price: product.mrp }
    ]
    if (batches) {
      batches.forEach(b => {
        if (b.selling_price && b.selling_price > 0) {
          rawOptions.push({ label: `Batch ${b.batch_no || '—'} Price`, price: b.selling_price })
        }
        if (b.mrp && b.mrp > 0) {
          rawOptions.push({ label: `Batch ${b.batch_no || '—'} MRP`, price: b.mrp })
        }
      })
    }
    const seen = new Set()
    const options = []
    rawOptions.forEach(opt => {
      const val = parseFloat(opt.price)
      if (val && val > 0 && !seen.has(val)) {
        seen.add(val)
        options.push({ label: opt.label, price: val })
      }
    })

    const hasNonStandardPrices = options.some(opt => {
      const pVal = parseFloat(opt.price)
      return !standardBasePrices.includes(pVal)
    })

    const shouldShowSelector = hasNonStandardPrices && !isAlreadyPresent

    if (shouldShowSelector) {
      setForm(f => {
        const targetIdx = f.items.findIndex(it => it.product_id === product.id)
        if (targetIdx !== -1) {
          setPriceSelectorIndex(targetIdx)
          setSelectedPriceOptIndex(0)
        }
        return f
      })
    } else {
      setPriceSelectorIndex(null)
      setSelectedPriceOptIndex(0)
      setTimeout(() => barcodeRef.current?.focus(), 50)
    }
  }, [customers, fetchBatchesForProduct, productBatches, authFetch, profile])

  const handleSelectProduct = useCallback((product) => {
    addProductToCart(product)
  }, [addProductToCart])

  const handleSearchKeyDown = (e) => {
    if (priceSelectorIndex !== null) {
      const options = getPriceOptions(form.items[priceSelectorIndex])
      if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        e.preventDefault()
        e.stopPropagation()
        setSelectedPriceOptIndex(prev => Math.max(0, prev - 1))
        return
      }
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
        e.preventDefault()
        e.stopPropagation()
        setSelectedPriceOptIndex(prev => Math.min(options.length - 1, prev + 1))
        return
      }
      if (e.key === 'Enter' || e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        const opt = options[selectedPriceOptIndex] || options[0]
        if (opt) {
          handleSelectPriceOption(opt.price, opt.label)
        } else {
          setPriceSelectorIndex(null)
          setTimeout(() => barcodeRef.current?.focus(), 50)
        }
        return
      }
    }

    if (!searchQuery.trim()) {
      if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
        e.preventDefault()
        setForm(f => {
          if (f.items.length === 0) return f
          const items = [...f.items]
          const lastIdx = items.length - 1
          if (!items[lastIdx].product) return f
          const currentQty = parseFloat(items[lastIdx].qty) || 0
          const newQty = e.key === 'ArrowUp' ? currentQty + 1 : Math.max(1, currentQty - 1)
          items[lastIdx] = withQty(items[lastIdx], newQty)
          return { ...f, items }
        })
      }
      // Proceed-to-payment key (default: Esc) when barcode is empty
      if (matchesKey(e, funcKeys.proceedToPayment) || e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        if (form.items.length > 0) {
          openPaymentFlow('customer')
        }
        return
      }
      // Enter on empty barcode with items in cart → open payment popup
      if (e.key === 'Enter') {
        e.preventDefault()
        if (form.items.length > 0) {
          openPaymentFlow('customer')
        }
        return
      }
      return
    }

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex(prev => Math.min(filteredProducts.length - 1, prev + 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex(prev => Math.max(-1, prev - 1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (selectedIndex !== -1 && filteredProducts[selectedIndex]) {
        addProductToCart(filteredProducts[selectedIndex])
      } else if (searchQuery.trim()) {
        const code = searchQuery.trim()
        const exactMatch = products.find(p => p.barcode === code || (p.sku && p.sku === code))
        if (exactMatch) {
          addProductToCart(exactMatch)
        } else if (filteredProducts.length > 0) {
          addProductToCart(filteredProducts[0])
        } else {
          addCustomItemToCart()
          setForm(f => {
            const items = [...f.items]
            if (items.length > 0) {
              items[items.length - 1].product = code
            }
            return { ...f, items }
          })
        }
      }
    } else if (e.key === 'Escape') {
      // If text in search → clear it (stay focused for user to try again or click Custom Item)
      e.preventDefault()
      setSearchQuery('')
      setSelectedIndex(-1)
    }
  }



  // usePaymentFlow hook now provides handleSaveInvoice, openPaymentFlow, and executeSaveInvoice




  const handleClear = () => {
    if (form.items.length > 0) {
      if (!window.confirm('Reset current bill fields? Unsaved changes will be lost.')) return
    }
    setForm({
      ...defaultForm,
      customer_id: '',
      godown_id: godowns.length > 0 ? godowns[0].id : '',
      due_date: getTodayDateStr(),
    })
    setPriceSelectorIndex(null)
    setSelectedPriceOptIndex(0)
    setAlert(null)
    setSearchQuery('')
    setTimeout(() => barcodeRef.current?.focus(), 100)
  }

  // Accidental exit prevention handler
  const handleCloseConfirm = useCallback(() => {
    if (form.items.length > 0) {
      if (window.confirm('Are you sure you want to close this bill? Unsaved changes will be lost.')) {
        navigate('/')
      }
    } else {
      navigate('/')
    }
  }, [form.items, navigate])

  // Helper selectors to focus cells for hotkeys
  const focusLastQty = () => {
    const inputs = document.querySelectorAll('.pos-cart-table tbody tr input.qty-input')
    if (inputs.length > 0) {
      inputs[inputs.length - 1].focus()
    }
  }

  const focusLastDiscount = () => {
    const inputs = document.querySelectorAll('.pos-cart-table tbody tr input.discount-input')
    if (inputs.length > 0) {
      inputs[inputs.length - 1].focus()
    }
  }

  const removeLastItem = () => {
    if (form.items.length > 0) {
      removeItem(form.items.length - 1)
    }
  }

  const focusNotes = () => {
    const el = document.querySelector('.pos-form-section textarea')
    el?.focus()
  }

  // Keyboard POS Shortcuts
  useEffect(() => {
    const handleKeyDown = (e) => {
      // If we are currently binding a key, capture the key press
      if (bindingAction) {
        e.preventDefault()
        e.stopPropagation()
        const pressedKey = e.key
        if (pressedKey !== 'Escape') {
          let keyToSave = pressedKey
          if (pressedKey.length === 1) {
            keyToSave = pressedKey.toUpperCase()
          }
          const nextKeys = { ...funcKeys, [bindingAction]: keyToSave }
          setFuncKeys(nextKeys)
          localStorage.setItem('pos_func_keys', JSON.stringify(nextKeys))
        }
        setBindingAction(null)
        return
      }

      // If price selector is active, prioritize price selector navigation keys
      if (priceSelectorIndex !== null) {
        const item = form.items[priceSelectorIndex]
        const options = getPriceOptions(item)
        if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
          e.preventDefault()
          setSelectedPriceOptIndex(prev => Math.max(0, prev - 1))
          return
        }
        if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
          e.preventDefault()
          setSelectedPriceOptIndex(prev => Math.min(options.length - 1, prev + 1))
          return
        }
        if (e.key === 'Enter' || e.key === 'Escape') {
          e.preventDefault()
          const opt = options[selectedPriceOptIndex] || options[0]
          if (opt) {
            handleSelectPriceOption(opt.price, opt.label)
          } else {
            setPriceSelectorIndex(null)
            setTimeout(() => barcodeRef.current?.focus(), 50)
          }
          return
        }
        return
      }

      if (showSettingsModal || showBreakupModal || showHotkeySettingsModal) return

      if (showPaymentPopup) {
        return
      }

      // New Bill (Ctrl+T)
      if (e.ctrlKey && e.key.toLowerCase() === 't') {
        e.preventDefault()
        handleNewBill()
      }

      // Close Bill Tab (Ctrl+W)
      if (e.ctrlKey && e.key.toLowerCase() === 'w') {
        e.preventDefault()
        closeTab(activeTabId)
      }

      // Save & Print Bill (Ctrl+P / F10)
      if ((e.ctrlKey && e.key.toLowerCase() === 'p') || e.key === 'F10') {
        e.preventDefault()
        handleSaveInvoice(true)
      }

      // Save Bill Only (Ctrl+S)
      if (e.ctrlKey && e.key.toLowerCase() === 's') {
        e.preventDefault()
        handleSaveInvoice(false)
      }

      // Other/Credit payments shortcut (Ctrl+M)
      if (e.ctrlKey && e.key.toLowerCase() === 'm') {
        e.preventDefault()
        setForm(f => ({ ...f, payment_mode: 'credit', amount_received: '0' }))
        openPaymentFlow('amountReceived')
      }

      // Full Breakup modal toggle (Ctrl+F)
      if (e.ctrlKey && e.key.toLowerCase() === 'f') {
        e.preventDefault()
        setShowBreakupModal(true)
      }

      // Increment last item quantity on pressing "+"
      if (e.key === '+') {
        const activeEl = document.activeElement
        const isSearchInput = activeEl === barcodeRef.current
        const isBody = activeEl === document.body || !activeEl || activeEl.tagName === 'BUTTON' || activeEl.className === 'pos-hotkey-btn'
        
        if (isSearchInput || isBody) {
          e.preventDefault()
          e.stopPropagation()
          
          setForm(f => {
            if (f.items.length === 0) return f
            const items = [...f.items]
            const lastIdx = items.length - 1
            const currentQty = parseFloat(items[lastIdx].qty) || 0
            items[lastIdx] = withQty(items[lastIdx], currentQty + 1)
            return { ...f, items }
          })
          
          // Clear any + character typed in search input
          setSearchQuery(prev => prev.replace('+', ''))
          setTimeout(() => barcodeRef.current?.focus(), 50)
          return
        }
      }

      // Check which action is mapped to e.key
      const getActionForKey = (key) => {
        return Object.keys(funcKeys).find(action => {
          const boundKey = funcKeys[action]
          if (!boundKey || !key) return false
          if (boundKey.length === 1 && key.length === 1) {
            return boundKey.toLowerCase() === key.toLowerCase()
          }
          return boundKey === key
        })
      }

      const action = getActionForKey(e.key)
      if (action) {
        e.preventDefault()
        if (action === 'qtyFocus') focusLastQty()
        else if (action === 'discountFocus') focusLastDiscount()
        else if (action === 'removeItem') removeLastItem()
        else if (action === 'amountReceivedFocus') openPaymentFlow()
        else if (action === 'barcodeFocus') barcodeRef.current?.focus()
        else if (action === 'customerFocus') openPaymentFlow('customer')
        else if (action === 'remarksFocus') openPaymentFlow('remarks')
        else if (action === 'configureShortcuts') setShowHotkeySettingsModal(true)
      }

      // ── Universal Proceed-to-Payment (Escape / configurable) ──────────────────
      // Fires from ANYWHERE in the POS: barcode, qty cell, discount cell, etc.
      // Modals and price-selector already returned early above.
      if (matchesKey(e, funcKeys.proceedToPayment) || e.key === 'Escape') {
        const activeEl = document.activeElement
        const isInTable = activeEl && (activeEl.closest?.('table') || activeEl.classList?.contains('pos-cell-input'))
        if (isInTable) {
          e.preventDefault()
          e.stopPropagation()
          barcodeRef.current?.focus()
          return
        }

        // If we are in the barcode scanner and there is text, let the search keydown handler clear the text (don't proceed to payment)
        if (document.activeElement === barcodeRef.current && searchQuery.trim() !== '') {
          if (e.key === 'Escape') {
            return
          }
          e.preventDefault()
          e.stopPropagation()
          setSearchQuery('')
          setSelectedIndex(-1)
          return
        }



        e.preventDefault()
        e.stopPropagation()

        // Toggle to payment section
        if (searchQuery) {
          setSearchQuery('')
          setSelectedIndex(-1)
        }

        // Blur whichever cell input the user was in, then go to customer field
        document.activeElement?.blur()
        openPaymentFlow('customer')
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [showSettingsModal, showBreakupModal, showHotkeySettingsModal, showPayConfirmModal, searchQuery, handleSaveInvoice, activeTabId, closeTab, handleNewBill, funcKeys, bindingAction, priceSelectorIndex, selectedPriceOptIndex, form.items, matchesKey, showPaymentPopup, openPaymentFlow, executeSaveInvoice])

  const stickyOffsets = getStickyLeftOffsets(columnOrder, colVisible)

  const filteredProducts = searchQuery.trim()
    ? products.filter(p =>
        p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (p.barcode && p.barcode.toLowerCase().includes(searchQuery.toLowerCase())) ||
        (p.sku && p.sku.toLowerCase().includes(searchQuery.toLowerCase()))
      ).slice(0, 8)
    : []

  return (
    <AppLayout title="POS Counter">
      <div style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
        

        {/* Tab-Style Bar */}
        <div className="pos-top-bar">
          <div className="pos-top-bar-left">
            <div className="pos-tabs-row">
              {tabs.map(tab => {
                const isActive = tab.id === activeTabId;
                return (
                  <div
                    key={tab.id}
                    className={`pos-tab ${isActive ? '' : 'inactive'}`}
                    onClick={() => setActiveTabId(tab.id)}
                    style={{ cursor: 'pointer' }}
                  >
                    <span>{tab.name}</span>
                    {isActive && (
                      <span style={{ fontSize: '0.65rem', color: '#94a3b8', marginLeft: 8, marginRight: 4 }}>Ctrl+W</span>
                    )}
                    <span className="pos-tab-close" onClick={(e) => closeTab(tab.id, e)}>✕</span>
                  </div>
                );
              })}
              <div className="pos-tab-add" title="New Invoice (Ctrl+T)" onClick={handleNewBill}>
                ＋ New Bill [Ctrl+T]
              </div>
            </div>
          </div>
          <div className="pos-top-bar-right" style={{ gap: 12 }}>
            <span style={{ display: 'flex', alignItems: 'center', cursor: 'pointer', color: 'var(--text-muted)' }} onClick={() => setShowSettingsModal(true)} title="Settings">
              <SettingsIcon size={16} />
            </span>
            <span style={{ color: 'var(--border)' }}>|</span>
            <div style={{ display: 'flex', gap: 2 }}>
              <span className="pos-window-control-btn" style={{ width: 20, height: 20, fontSize: '0.75rem', cursor: 'pointer' }} onClick={handleMinimize} title="Minimize to Sidebar">—</span>
              <span className="pos-window-control-btn close-btn" style={{ width: 20, height: 20, fontSize: '0.75rem', cursor: 'pointer' }} onClick={handleCloseConfirm} title="Close POS">✕</span>
            </div>
          </div>
        </div>

        {/* Workspace body split */}
        <div className="pos-workspace">
          
          {/* Left Pane (72% width) */}
          <div className="pos-left-pane">
            
            {alert && (
              <div className={`alert alert-${alert.type} mb-3`} style={{ padding: '8px 12px', fontSize: '0.82rem', alignItems: 'center' }}>
                {alert.type === 'success' ? <CheckIcon size={14} style={{ marginRight: 4 }} /> : <AlertIcon size={14} style={{ marginRight: 4 }} />}
                <span>{alert.msg}</span>
                <button onClick={() => setAlert(null)} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'inherit', cursor: 'pointer' }}>✕</button>
              </div>
            )}

            {/* Product autocomplete search */}
            <div className="pos-search-container" style={{ position: 'relative' }}>
              <div style={{ display: 'flex', gap: 8 }}>
                <div className="search-bar" style={{ flex: 1, padding: '8px 12px', background: 'var(--bg-2)', borderColor: 'var(--border)' }}>
                  <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center' }}><SearchIcon size={14} /></span>
                  <input
                    ref={barcodeRef}
                    value={searchQuery}
                    onChange={e => {
                      setSearchQuery(e.target.value)
                      setSelectedIndex(-1)
                    }}
                    onKeyDown={handleSearchKeyDown}
                    placeholder={`Scan barcode or search by ${t('product', 'item')} code, model no or name (F9)…`}
                    style={{ width: '100%', color: '#0f172a' }}
                  />
                </div>
                <button type="button" className="btn btn-secondary" onClick={addCustomItemToCart} style={{ whiteSpace: 'nowrap', fontSize: '0.8rem', padding: '0 16px' }}>
                  ＋ Custom Item
                </button>
              </div>

              {/* Autocomplete Overlay */}
              {filteredProducts.length > 0 && (
                <div style={{
                  position: 'absolute',
                  top: '100%',
                  left: 0,
                  right: 0,
                  background: 'var(--bg-2)',
                  border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-md)',
                  boxShadow: 'var(--shadow-lg)',
                  zIndex: 1000,
                  marginTop: 6,
                  overflow: 'hidden'
                }}>
                  {filteredProducts.map((p, idx) => {
                    const isSelected = idx === selectedIndex;
                    return (
                      <div
                        key={p.id}
                        style={{
                          padding: '10px 14px',
                          background: isSelected ? '#eff6ff' : 'transparent',
                          color: isSelected ? '#1d4ed8' : '#0f172a',
                          cursor: 'pointer',
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          borderBottom: '1px solid #f1f5f9'
                        }}
                        onClick={() => addProductToCart(p)}
                        onMouseEnter={() => setSelectedIndex(idx)}
                      >
                        <div style={{ display: 'flex', flexDirection: 'column' }}>
                          <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>{p.name}</span>
                          <span style={{ fontSize: '0.72rem', color: '#64748b' }}>SKU: {p.sku || '—'} {p.barcode ? `| Barcode: ${p.barcode}` : ''}</span>
                        </div>
                        <span style={{ fontWeight: 700, fontSize: '0.85rem', color: '#16a34a' }}>{fmt(p.selling_price)}</span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Cart Table list container */}
            <div className="pos-cart-wrapper" style={{ position: 'relative', display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
              <div ref={tableContainerRef} className="pos-cart-container" style={{ flex: 1, overflow: 'auto' }}>
                <table className="pos-cart-table">
                  <thead>
                    <tr>
                      <th style={{ position: 'sticky', left: 0, top: 0, zIndex: 12, background: 'var(--bg-3)', width: 40, minWidth: 40 }}>#</th>
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
                          top: 0,
                          zIndex: isSticky ? 12 : 10,
                          background: 'var(--bg-3)',
                        };
                        if (isSticky) {
                          style.left = stickyOffsets[col];
                        }

                        const renderHeader = () => {
                          if (col === 'sku') {
                            return <th key="sku" style={{ ...style, width: 95, minWidth: 95 }}>ITEM CODE</th>;
                          }
                          if (col === 'name') {
                            return (
                              <th key="name" style={{
                                ...style,
                                width: '100%',
                                minWidth: 180,
                                borderRight: '1px solid var(--border)',
                                boxShadow: '4px 0 4px -2px rgba(0,0,0,0.1)'
                              }}>{(t('product', 'item')).toUpperCase()} NAME</th>
                            );
                          }
                          if (col === 'batch') {
                            return <th key="batch" style={{ ...style, width: 140, minWidth: 140, textAlign: 'center' }}>BATCH</th>;
                          }
                          if (col === 'price_option') {
                            return <th key="price_option" style={{ ...style, width: 155, minWidth: 155, textAlign: 'center' }}>PRICE OPTION</th>;
                          }
                          if (col === 'mrp') {
                            return <th key="mrp" style={{ ...style, width: 90, minWidth: 90, textAlign: 'right' }}>MRP (₹)</th>;
                          }
                          if (col === 'hsn') {
                            return <th key="hsn" style={{ ...style, width: 80, minWidth: 80, textAlign: 'center' }}>HSN</th>;
                          }
                          if (col === 'qty') {
                            return <th key="qty" style={{ ...style, width: 80, minWidth: 80, textAlign: 'center' }}>QTY</th>;
                          }
                          if (col === 'unit') {
                            return <th key="unit" style={{ ...style, width: 70, minWidth: 70, textAlign: 'center' }}>UNIT</th>;
                          }
                          if (col === 'rate') {
                            return (
                              <th key="rate" style={{ ...style, width: 150, minWidth: 150, textAlign: 'right' }}>
                                PRICE PER UNIT<br/>
                                <span style={{ fontSize: '0.65rem', fontWeight: 'normal' }}>BEFORE TAX (₹)</span>
                              </th>
                            );
                          }
                          if (col === 'price') {
                            return (
                              <th key="price" style={{ ...style, width: 130, minWidth: 130, textAlign: 'right' }}>
                                TOTAL<br/>
                                <span style={{ fontSize: '0.65rem', fontWeight: 'normal' }}>BEFORE TAX (₹)</span>
                              </th>
                            );
                          }
                          if (col === 'discount') {
                            return <th key="discount" style={{ ...style, width: 100, minWidth: 100, textAlign: 'right' }}>DISCOUNT (₹)</th>;
                          }
                          if (col === 'tax') {
                            return <th key="tax" style={{ ...style, width: 110, minWidth: 110, textAlign: 'center' }}>TAX APPLIED(%)</th>;
                          }
                          if (col === 'total') {
                            return (
                              <th key="total" style={{ ...style, width: 130, minWidth: 130, textAlign: 'right' }}>
                                TOTAL<br/>
                                <span style={{ fontSize: '0.65rem', fontWeight: 'normal' }}>AFTER TAX (₹)</span>
                              </th>
                            );
                          }
                          return null;
                        };
                        const headerEl = renderHeader();
                        if (headerEl) {
                          return React.cloneElement(headerEl, { className: `${headerEl.props.className || ''} col-${col}`.trim() });
                        }
                        return null;
                      })}
                      {form.items.length > 0 && <th style={{ position: 'sticky', top: 0, zIndex: 10, background: 'var(--bg-3)', width: 40, minWidth: 40, textAlign: 'center' }}></th>}
                    </tr>
                  </thead>
                  <tbody>
                    {form.items.length === 0 ? (
                      Array.from({ length: emptyRowCount }).map((_, idx) => (
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
                      ))
                    ) : (
                      form.items.map((item, i) => (
                        <tr key={i} className="item-row">
                          <td style={{
                            position: 'sticky',
                            left: 0,
                            zIndex: 2,
                            background: 'var(--bg-2)',
                            fontWeight: 600,
                            color: '#64748b'
                          }}>{i + 1}</td>
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
                                    <span className="pos-cell-text" style={{ fontSize: '0.8rem', color: '#475569' }}>
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
                                        onChange={e => setItem(i, 'product', e.target.value)}
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
                                          style={{ fontSize: '0.72rem', padding: '2px 4px', border: '1px solid #cbd5e1', borderRadius: '4px', background: '#f8fafc', color: '#334155', maxWidth: '130px', textOverflow: 'ellipsis' }}
                                          value={item.batch_no || ''}
                                          onChange={e => {
                                            const selectedBatchNo = e.target.value
                                            const batches = productBatches[item.product_id] || []
                                            const found = batches.find(b => b.batch_no === selectedBatchNo)
                                            setItem(i, {
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
                                      <span style={{ color: '#94a3b8' }}>—</span>
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
                                        style={{ fontSize: '0.72rem', padding: '2px 4px', border: '1px solid #cbd5e1', borderRadius: '4px', background: '#f8fafc', color: '#334155', maxWidth: '145px', textOverflow: 'ellipsis' }}
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
                                            setItem(i, {
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
                                      <span style={{ color: '#94a3b8' }}>—</span>
                                    )}
                                  </td>
                                );
                              }

                              if (col === 'mrp') {
                                return (
                                  <td key="mrp" style={{ ...style, textAlign: 'right' }}>
                                    <span className="pos-cell-text" style={{ fontSize: '0.8rem', color: '#475569' }}>
                                      {fmt(products.find(p => p.id === item.product_id)?.mrp || item.price)}
                                    </span>
                                  </td>
                                );
                              }

                              if (col === 'hsn') {
                                return (
                                  <td key="hsn" style={{ ...style, textAlign: 'center' }}>
                                    <span className="pos-cell-text" style={{ fontSize: '0.8rem', color: '#475569' }}>
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
                                      onChange={e => handleQtyChange(i, e.target.value)}
                                      required
                                    />
                                  </td>
                                );
                              }

                              if (col === 'unit') {
                                return (
                                  <td key="unit" style={{ ...style, textAlign: 'center', fontSize: '0.8rem', fontWeight: 600, color: '#64748b' }}>
                                    pcs
                                  </td>
                                );
                              }

                              if (col === 'rate') {
                                const currentRate = parseFloat(item.selected_price) || (parseFloat(item.price) - (parseFloat(item.discount) / (parseFloat(item.qty) || 1)))
                                return (
                                  <td key="rate" style={style}>
                                    {item.product_id ? (
                                      <input
                                        type="number"
                                        min="0"
                                        step="any"
                                        className="pos-cell-input rate-input"
                                        style={{ textAlign: 'right', fontWeight: 600, color: 'var(--primary)' }}
                                        value={isNaN(currentRate) ? '' : parseFloat(currentRate.toFixed(2))}
                                        onChange={e => {
                                          const newRate = parseFloat(e.target.value) || 0
                                          setItem(i, {
                                            selected_price: newRate,
                                            selected_price_label: 'Custom Price'
                                          })
                                        }}
                                      />
                                    ) : (
                                      <span style={{ color: '#94a3b8' }}>—</span>
                                    )}
                                  </td>
                                );
                              }

                              if (col === 'price') {
                                return (
                                  <td key="price" style={{ ...style, textAlign: 'right' }}>
                                    <span className="pos-cell-text" style={{ fontSize: '0.8rem', color: '#475569' }}>
                                      {item.product ? fmt(lineTotal(item)) : '—'}
                                    </span>
                                  </td>
                                );
                              }

                              if (col === 'discount') {
                                return (
                                  <td key="discount" style={{ ...style, textAlign: 'right' }}>
                                    <span className="pos-cell-text" style={{ fontSize: '0.8rem', color: '#475569' }}>
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
                                  <td key="tax" style={{ ...style, textAlign: 'center', fontSize: '0.8rem', fontWeight: 600, color: '#475569' }}>
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
                                            if (items[i]) {
                                              items[i] = {
                                                ...items[i],
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
                                  <td key="total" style={{ ...style, textAlign: 'right', fontWeight: 700, fontSize: '0.85rem', color: '#0f172a' }}>
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
                              onClick={() => removeItem(i)}
                              style={{ color: '#ef4444', padding: 4 }}
                            >
                              ✕
                            </button>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                  {form.items.length > 0 && (
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
                  )}
                </table>
              </div>

              {priceSelectorIndex !== null && (
                <div
                  className="modal-overlay"
                  onClick={() => setPriceSelectorIndex(null)}
                  style={{ zIndex: 2010 }}
                >
                  <div
                    className="modal"
                    style={{
                      maxWidth: '580px',
                      background: 'rgba(255, 255, 255, 0.85)',
                      backdropFilter: 'blur(30px) saturate(190%)',
                      WebkitBackdropFilter: 'blur(30px) saturate(190%)',
                      border: '1px solid rgba(255, 255, 255, 0.45)',
                      color: '#1c1917',
                      boxShadow: '0 30px 60px rgba(0,0,0,0.12), inset 0 1px 0 rgba(255,255,255,0.7)'
                    }}
                    onClick={e => e.stopPropagation()}
                  >
                    <div className="modal-header" style={{ borderBottom: '1px solid var(--border)' }}>
                      <span className="modal-title" style={{ fontSize: '1.1rem', fontWeight: 800 }}>
                        🏷️ Price Selection — {form.items[priceSelectorIndex]?.product}
                      </span>
                      <button
                        className="btn btn-ghost btn-icon"
                        onClick={() => setPriceSelectorIndex(null)}
                        style={{ color: '#78716c' }}
                      >
                        ✕
                      </button>
                    </div>
                    <div className="modal-body" style={{ padding: '16px 20px' }}>
                      <p style={{ fontSize: '0.82rem', color: '#78716c', marginBottom: '12px' }}>
                        Multiple prices found for this item. Use <kbd>↑</kbd> <kbd>↓</kbd> arrows and <kbd>Enter</kbd> / <kbd>Esc</kbd> or click a row to select.
                      </p>
                      
                      <div style={{ overflowX: 'auto', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)' }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.88rem' }}>
                          <thead>
                            <tr style={{ background: '#fafaf9', borderBottom: '1px solid var(--border)', textAlign: 'left' }}>
                              <th style={{ padding: '10px 12px', fontWeight: 700, color: '#78716c' }}>Price Option</th>
                              <th style={{ padding: '10px 12px', fontWeight: 700, color: '#78716c' }}>Date Added</th>
                              <th style={{ padding: '10px 12px', fontWeight: 700, color: '#78716c', textAlign: 'right' }}>Price</th>
                            </tr>
                          </thead>
                          <tbody>
                            {getPriceOptions(form.items[priceSelectorIndex]).map((opt, oIdx) => {
                              const isSelected = oIdx === selectedPriceOptIndex;
                              return (
                                <tr
                                  key={oIdx}
                                  style={{
                                    background: isSelected ? 'var(--accent-dim)' : 'transparent',
                                    borderBottom: '1px solid var(--border)',
                                    cursor: 'pointer',
                                    transition: 'background 0.15s ease',
                                    color: isSelected ? 'var(--text-primary)' : '#1c1917',
                                    fontWeight: isSelected ? 600 : 'normal'
                                  }}
                                  onClick={() => handleSelectPriceOption(opt.price, opt.label)}
                                  onMouseEnter={() => setSelectedPriceOptIndex(oIdx)}
                                >
                                  <td style={{ padding: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                                    {isSelected ? '👉' : '  '}
                                    <span>{opt.label}</span>
                                  </td>
                                  <td style={{ padding: '12px', color: isSelected ? 'var(--text-primary)' : '#78716c' }}>
                                    {opt.formatted_date}
                                  </td>
                                  <td style={{ padding: '12px', textAlign: 'right', fontWeight: 700, color: isSelected ? 'var(--accent)' : '#000000' }}>
                                    {fmt(opt.price)}
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Bottom Sticky Totals Bar — extracted to components/sales/PosTotalBar */}
            {!showPaymentPopup && (
              <PosTotalBar
                subtotal={subtotal}
                gstAmt={gstAmt}
                grandTotal={grandTotal}
                onShowShortcuts={() => setShowHotkeySettingsModal(true)}
                onPay={openPaymentFlow}
              />
            )}

          </div>

          {/* Right Pane (42% in menu mode) */}
          {entryMode === 'menu' && (
            <div
              className="pos-right-pane"
              style={{
                width: '42%',
                height: '100%',
                display: 'flex',
                flexDirection: 'column',
                padding: '16px',
                background: '#f8fafc',
                borderLeft: '1px solid var(--border)',
                overflowY: 'auto',
                gap: '20px'
              }}
            >
              <div style={{ fontSize: '1.1rem', fontWeight: 800, color: 'var(--text-primary)', borderBottom: '2.5px solid var(--accent)', paddingBottom: '6px', marginBottom: '4px' }}>
                🍽️ Menu / Catalogue
              </div>
              {Object.keys(groupedProducts).length === 0 ? (
                <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.9rem', marginTop: '40px' }}>
                  No products found in stock.
                </div>
              ) : (
                Object.entries(groupedProducts).map(([catName, items]) => (
                  <div key={catName} style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <h3 style={{ fontSize: '0.9rem', fontWeight: 700, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                      {catName}
                    </h3>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: '10px' }}>
                      {items.map(p => (
                        <div
                          key={p.id}
                          className="menu-product-card"
                          onClick={() => handleSelectProduct(p)}
                          style={{
                            background: 'var(--bg-2)',
                            border: '1.5px solid var(--border)',
                            borderRadius: '10px',
                            padding: '10px',
                            cursor: 'pointer',
                            transition: 'all 0.15s ease',
                            display: 'flex',
                            flexDirection: 'column',
                            justifyContent: 'space-between',
                            minHeight: '85px',
                            boxShadow: '0 2px 4px rgba(0,0,0,0.02)'
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.borderColor = 'var(--accent)'
                            e.currentTarget.style.transform = 'translateY(-2px)'
                            e.currentTarget.style.boxShadow = '0 4px 12px rgba(249,115,22,0.1)'
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.borderColor = 'var(--border)'
                            e.currentTarget.style.transform = 'none'
                            e.currentTarget.style.boxShadow = '0 2px 4px rgba(0,0,0,0.02)'
                          }}
                        >
                          <div style={{ fontWeight: 600, fontSize: '0.82rem', color: '#1e293b', lineHeight: 1.3 }}>
                            {p.name}
                          </div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginTop: '6px' }}>
                            <span style={{ fontSize: '0.72rem', color: '#64748b' }}>
                              {p.unit || 'pcs'}
                            </span>
                            <span style={{ fontWeight: 700, fontSize: '0.85rem', color: 'var(--accent)' }}>
                              {fmt(p.selling_price)}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))
              )}
            </div>
          )}

        </div>

      </div>

      {/* Breakup Details Modal — extracted to components/sales/TotalBreakupModal */}
      <TotalBreakupModal
        open={showBreakupModal}
        onClose={() => setShowBreakupModal(false)}
        subtotal={subtotal}
        gstAmt={gstAmt}
        isIntrastate={isIntrastate}
        cgstAmt={cgstAmt}
        sgstAmt={sgstAmt}
        igstAmt={igstAmt}
        grandTotal={grandTotal}
        amountReceived={amountReceivedNum}
        changeToReturn={changeToReturn}
        paymentMode={form.payment_mode}
        upiVpa={upiVpa}
      />

      {/* Payment Tendering Modal Popup */}
      {/* Checkout Modal Component */}
      <CheckoutModal
        open={showPaymentPopup}
        onClose={() => setShowPaymentPopup(false)}
        form={form}
        setForm={setForm}
        subtotal={subtotal}
        gstAmt={gstAmt}
        grandTotal={grandTotal}
        payable={payable}
        roundOff={roundOff}
        cashDiscountAmt={cashDiscountAmt}
        cgstAmt={cgstAmt}
        sgstAmt={sgstAmt}
        igstAmt={igstAmt}
        billDiscountAmt={billDiscountAmt}
        customers={customers}
        setCustomers={setCustomers}
        godowns={godowns}
        upiVpa={upiVpa}
        authFetch={authFetch}
        onSaveInvoice={executeSaveInvoice}
        submitting={submitting}
        setAlert={setAlert}
        focusTarget={paymentFocusTarget}
        funcKeys={funcKeys}
      />

      {/* Main Settings Modal */}
      {showSettingsModal && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowSettingsModal(false)}>
          <div className="modal" style={{ maxWidth: 450 }}>
            <div className="modal-header">
              <span className="modal-title" style={{ color: '#0f172a', fontWeight: 700 }}>⚙️ POS Counter Settings</span>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowSettingsModal(false)} style={{ color: '#64748b' }}>✕</button>
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
                          onChange={e => col.toggleable && handleToggleColumnSetting(col.key, e.target.checked)}
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
                            onClick={() => handleMoveColumn(idx, 'up')}
                          >
                            ▲
                          </button>
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            style={{ padding: '2px 6px', fontSize: '0.75rem', border: '1px solid #cbd5e1' }}
                            disabled={idx === columnOrder.length - 1}
                            onClick={() => handleMoveColumn(idx, 'down')}
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
                  onClick={() => {
                    setShowSettingsModal(false);
                    navigate('/settings');
                  }}
                >
                  Advanced Settings ➔
                </button>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => setShowSettingsModal(false)}>
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Hotkey Settings Modal */}
      {showHotkeySettingsModal && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowHotkeySettingsModal(false)}>
          <div className="modal" style={{ maxWidth: 450 }}>
            <div className="modal-header">
              <span className="modal-title" style={{ color: '#0f172a', fontWeight: 700 }}>⌨️ Configure POS Hotkeys</span>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowHotkeySettingsModal(false)} style={{ color: '#64748b' }}>✕</button>
            </div>
            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <p style={{ fontSize: '0.8rem', color: '#64748b', marginBottom: 2 }}>
                Select key mappings from the dropdown options below to customize your counter shortcuts.
              </p>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxHeight: '340px', overflowY: 'auto', paddingRight: '4px' }}>
                {/* Flow navigation keys — highlighted section */}
                <div style={{ background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: '8px', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <div style={{ fontSize: '0.7rem', fontWeight: 700, color: '#1d4ed8', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2 }}>⌨️ Payment Flow Navigation</div>
                  {[
                    {
                      label: '🛒 → 💳 Proceed to Payment',
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
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => setShowHotkeySettingsModal(false)}>
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      
      {/* Print-only thermal receipt container rendered via Portal directly in document.body */}
      {activeTab && createPortal(
        <div 
          id="thermal-receipt" 
          className={`size-${settings?.print?.thermal_page_size || '3inch'} text-size-${settings?.print?.text_size || 'medium'} theme-${settings?.print?.thermal_theme || 'theme_standard'}`}
        >
          <div className="receipt-header">
            {getHeaderLayout(settings?.print).map(line => renderReceiptHeaderLine(line.key, line.align))}
            <div className="dashed" />
          </div>

          <div className="receipt-info">
            <p><strong>Bill No:</strong> {activeTab.name}</p>
            <p><strong>Date:</strong> {getTodayDateStr()} &nbsp; <strong>Time:</strong> {new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}</p>
            <p><strong>Cashier:</strong> {user?.username || 'POS'} &nbsp; <strong>Counter:</strong> {settings?.print?.counter_id || 'CTR1'}</p>
            {(() => {
              const c = customers.find(x => String(x.id) === String(form.customer_id))
              return c ? (
                <>
                  <p><strong>Customer:</strong> {c.name}</p>
                  {c.phone && <p><strong>Phone:</strong> {c.phone}</p>}
                  {c.gstin && <p><strong>GSTIN:</strong> {c.gstin}</p>}
                </>
              ) : null
            })()}
            <div className="dashed" />
          </div>

          <table className="receipt-table">
            <thead>
              {settings?.print?.thermal_theme === 'theme_compact' ? (
                <tr>
                  <th colSpan={settings?.print?.print_item_hsn ? 3 : 2}>Description</th>
                  <th className="text-right">Amt</th>
                </tr>
              ) : (
                <tr>
                  {settings?.print?.print_item_sno !== false && <th style={{ width: '25px' }}>#</th>}
                  <th>Item</th>
                  {settings?.print?.print_item_hsn && <th>HSN</th>}
                  <th className="text-right">MRP</th>
                  <th className="text-right">Rate</th>
                  <th className="text-right">Qty</th>
                  {settings?.print?.print_item_tax !== false && <th className="text-right">GST</th>}
                  <th className="text-right">Amt</th>
                </tr>
              )}
            </thead>
            <tbody>
              {form.items.map((it, idx) => {
                const cgstRate = parseFloat(it.cgst_rate) || 0
                const sgstRate = parseFloat(it.sgst_rate) || 0
                const igstRate = it.igst_rate ? parseFloat(it.igst_rate) : (cgstRate + sgstRate)
                const totalRate = isIntrastate ? (cgstRate + sgstRate) : igstRate
                const lineUnitPrice = parseFloat(it.price) || 0

                if (settings?.print?.thermal_theme === 'theme_compact') {
                  return (
                    <tr key={idx} style={{ borderBottom: '1px dotted #ccc' }}>
                      <td colSpan={settings?.print?.print_item_hsn ? 2 : 1}>
                        <div style={{ fontWeight: 'bold', fontSize: '10px' }}>{it.product}</div>
                        <div style={{ fontSize: '9px', color: '#555' }}>
                          {it.qty} {it.unit || 'Nos'} · MRP ₹{lineUnitPrice.toFixed(2)} → ₹{((parseFloat(it.qty) || 1) ? lineTotal(it) / (parseFloat(it.qty) || 1) : lineUnitPrice).toFixed(2)}
                          {settings?.print?.print_item_hsn && it.hsn_sac && ` (HSN: ${it.hsn_sac})`}
                          {settings?.print?.print_item_tax !== false && totalRate > 0 && ` (Tax: ${totalRate}%)`}
                        </div>
                      </td>
                      <td className="text-right" style={{ verticalAlign: 'bottom', fontSize: '10px' }}>
                        ₹{lineTotal(it).toFixed(2)}
                      </td>
                    </tr>
                  )
                } else {
                  const qn = parseFloat(it.qty) || 1
                  const rate = qn ? lineTotal(it) / qn : lineUnitPrice   // chosen selling price per unit
                  return (
                    <tr key={idx}>
                      {settings?.print?.print_item_sno !== false && <td>{idx + 1}</td>}
                      <td>{it.product}</td>
                      {settings?.print?.print_item_hsn && <td>{it.hsn_sac || '—'}</td>}
                      <td className="text-right">₹{lineUnitPrice.toFixed(2)}</td>
                      <td className="text-right">₹{rate.toFixed(2)}</td>
                      <td className="text-right">{it.qty}</td>
                      {settings?.print?.print_item_tax !== false && <td className="text-right">{totalRate}%</td>}
                      <td className="text-right">₹{lineTotal(it).toFixed(2)}</td>
                    </tr>
                  )
                }
              })}
            </tbody>
          </table>

          <div className="dashed" />

          <div className="receipt-totals">
            <div className="receipt-row">
              <span>Subtotal:</span>
              <span>₹{subtotal.toFixed(2)}</span>
            </div>
            {billDiscountAmt > 0 && (
              <div className="receipt-row">
                <span>Discount:</span>
                <span>− ₹{billDiscountAmt.toFixed(2)}</span>
              </div>
            )}
            {settings?.print?.print_tax_breakdown !== false && (
              <>
                {cgstAmt > 0 && (
                  <div className="receipt-row">
                    <span>CGST:</span>
                    <span>₹{cgstAmt.toFixed(2)}</span>
                  </div>
                )}
                {sgstAmt > 0 && (
                  <div className="receipt-row">
                    <span>SGST:</span>
                    <span>₹{sgstAmt.toFixed(2)}</span>
                  </div>
                )}
                {igstAmt > 0 && (
                  <div className="receipt-row">
                    <span>IGST:</span>
                    <span>₹{igstAmt.toFixed(2)}</span>
                  </div>
                )}
              </>
            )}
            {(cashDiscountAmt > 0 || Math.abs(roundOff || 0) >= 0.005) ? (
              <>
                <div className="receipt-row">
                  <span>Total:</span>
                  <span>₹{grandTotal.toFixed(2)}</span>
                </div>
                {cashDiscountAmt > 0 && (
                  <div className="receipt-row">
                    <span>(−) Cash Discount:</span>
                    <span>₹{cashDiscountAmt.toFixed(2)}</span>
                  </div>
                )}
                {Math.abs(roundOff || 0) >= 0.005 && (
                  <div className="receipt-row">
                    <span>Round Off:</span>
                    <span>{(roundOff || 0) > 0 ? '+' : '−'} ₹{Math.abs(roundOff || 0).toFixed(2)}</span>
                  </div>
                )}
                <div className="receipt-row grand-total">
                  <span>PAYABLE:</span>
                  <span>₹{payable.toFixed(2)}</span>
                </div>
              </>
            ) : (
              <div className="receipt-row grand-total">
                <span>GRAND TOTAL:</span>
                <span>₹{grandTotal.toFixed(2)}</span>
              </div>
            )}
            {settings?.print?.print_amount_in_words && (
              <div className="receipt-row" style={{ fontSize: '9px', fontStyle: 'italic', textTransform: 'capitalize', marginTop: '2px' }}>
                <span>In Words: {numberToWords(payable)}</span>
              </div>
            )}
            <div className="receipt-row" style={{ marginTop: 4 }}>
              <span>Payment Mode:</span>
              <span>{form.payment_mode ? form.payment_mode.toUpperCase() : 'CASH'}</span>
            </div>
            <div className="receipt-row">
              <span>Amount Received:</span>
              <span>₹{parseFloat(form.amount_received || 0).toFixed(2)}</span>
            </div>
            {changeToReturn > 0 && (
              <div className="receipt-row">
                <span>Change Return:</span>
                <span>₹{changeToReturn.toFixed(2)}</span>
              </div>
            )}
            <div className="receipt-row" style={{ marginTop: 4 }}>
              <span>Qty: {colFooter.qty}</span>
              <span>Items: {form.items.length}</span>
            </div>
            {(colFooter.discount + billDiscountAmt + cashDiscountAmt) > 0.005 && (
              <div className="receipt-row" style={{ fontWeight: 700 }}>
                <span>You have Saved:</span>
                <span>₹{(colFooter.discount + billDiscountAmt + cashDiscountAmt).toFixed(2)}</span>
              </div>
            )}
          </div>

          {/* Per-slab GST tax table (Tax% · Taxable · CGST/SGST), like the kirana receipt */}
          {settings?.print?.print_tax_breakdown !== false && form.items.length > 0 && (() => {
            const slabs = gstSlabBreakdown(form.items, { isIntrastate })
            if (!slabs.length) return null
            return (
              <>
                <div className="dashed" />
                <table className="receipt-table" style={{ fontSize: '9px' }}>
                  <thead>
                    <tr>
                      <th>Tax%</th>
                      <th className="text-right">Taxable</th>
                      {isIntrastate
                        ? (<><th className="text-right">CGST</th><th className="text-right">SGST</th></>)
                        : (<th className="text-right">IGST</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {slabs.map((s, i) => (
                      <tr key={i}>
                        <td>{s.rate}%</td>
                        <td className="text-right">₹{s.taxable.toFixed(2)}</td>
                        {isIntrastate
                          ? (<><td className="text-right">₹{s.cgst.toFixed(2)}</td><td className="text-right">₹{s.sgst.toFixed(2)}</td></>)
                          : (<td className="text-right">₹{s.igst.toFixed(2)}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )
          })()}

          {(settings?.print?.fssai_no || settings?.print?.prices_incl_gst) && (
            <div style={{ fontSize: '9px', textAlign: 'center', marginTop: 4 }}>
              {settings?.print?.prices_incl_gst && <div>E. &amp; O.E. · Prices Incl. GST</div>}
              {settings?.print?.fssai_no && <div>FSSAI: {settings.print.fssai_no}</div>}
            </div>
          )}

          {form.notes && (
            <>
              <div className="dashed" />
              <div className="receipt-notes">
                <p><strong>Notes:</strong> {form.notes}</p>
              </div>
            </>
          )}

          {settings?.print?.print_terms_conditions && settings?.print?.terms_conditions_text && (
            <>
              <div className="dashed" />
              <div className="receipt-terms" style={{ fontSize: '9px', textAlign: 'center' }}>
                <p><strong>Terms & Conditions:</strong></p>
                <p style={{ whiteSpace: 'pre-wrap' }}>{settings.print.terms_conditions_text}</p>
              </div>
            </>
          )}

          {/* Signature lines */}
          {(settings?.print?.customer_signature || settings?.print?.print_signature) && (
            <div style={{ marginTop: '20px', display: 'flex', justifyContent: 'space-between', fontSize: '9px' }}>
              {settings?.print?.customer_signature && (
                <div style={{ textAlign: 'center', flex: 1 }}>
                  <div style={{ borderBottom: '1px solid #000', width: '80%', margin: '0 auto 4px auto', height: '15px' }} />
                  <div>{settings.print.customer_signature_label || 'Customer Signature'}</div>
                </div>
              )}
              {settings?.print?.print_signature && (
                <div style={{ textAlign: 'center', flex: 1 }}>
                  <div style={{ borderBottom: '1px solid #000', width: '80%', margin: '0 auto 4px auto', height: '15px' }} />
                  <div>{settings.print.signature_label || 'Authorised Signatory'}</div>
                </div>
              )}
            </div>
          )}

          <div className="dashed" />
          <div className="receipt-footer">
            <p>Thank you for shopping with us!</p>
            <p>Powered by BizAssist</p>
          </div>
        </div>,
        document.body
      )}
    </AppLayout>
  )
}
