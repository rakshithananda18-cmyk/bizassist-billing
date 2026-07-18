// ============================================================================
// lib/posKeys.js — POS function-key bindings (split from Sales.jsx, §2.5)
// ----------------------------------------------------------------------------
// The default key map, the localStorage loader, and the descriptor matcher.
// ============================================================================
import { logger } from '../utils/logger'

export const DEFAULT_FUNC_KEYS = {
  qtyFocus: 'F2',
  discountFocus: 'F3',
  checkoutDiscountFocus: 'F7',
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
  saveInvoice: 'Ctrl+S',
  printInvoice: 'Ctrl+P',
  newBill: 'Ctrl+T',
  closeTab: 'Ctrl+W',
}

/** Load saved bindings merged over defaults (bad JSON falls back to defaults). */
export function loadFuncKeys() {
  const saved = localStorage.getItem('pos_func_keys')
  if (saved) {
    try {
      return { ...DEFAULT_FUNC_KEYS, ...JSON.parse(saved) }
    } catch (e) {
      logger.error('[SALES] failed to parse pos_func_keys', e)
    }
  }
  return DEFAULT_FUNC_KEYS
}

/**
 * matchesKey — checks if a keyboard event matches a configurable key descriptor.
 * Descriptors can be plain keys like "Enter", "F5", "Escape",
 * or modifier combos like "Shift+Enter", "Shift+F5", "Ctrl+Enter".
 */
export function matchesKey(e, descriptor) {
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
