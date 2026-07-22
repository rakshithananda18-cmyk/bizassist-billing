// useDocLabels.js
// Returns a getter function `label(key)` that resolves a document type name
// from the user's custom labels settings, falling back to the built-in default.
import { useAuth } from '../contexts/AuthContext'

const DEFAULTS = {
  sale:             'Sales Invoice',
  purchase:         'Purchase Bill',
  estimate:         'Estimate',
  proforma:         'Proforma Invoice',
  delivery_challan: 'Delivery Challan',
  sale_return:      'Credit Note',
  purchase_return:  'Debit Note',
  payment_in:       'Payment Receipt',
  payment_out:      'Payment Out',
  expense:          'Expense',
  income:           'Other Income',
  sale_order:       'Sale Order',
  purchase_order:   'Purchase Order',
}

export function useDocLabels() {
  const auth = useAuth()
  const labels = auth?.settings?.labels || {}
  // Returns the custom label if set and non-empty, else the built-in default
  return (key) => (labels[key] && labels[key].trim()) || DEFAULTS[key] || key
}

export { DEFAULTS as DOC_LABEL_DEFAULTS }
