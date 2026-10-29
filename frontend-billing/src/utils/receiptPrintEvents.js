export const RECEIPT_PRINT_START = 'billing:receipt-print-start'
export const RECEIPT_PRINT_END = 'billing:receipt-print-end'

// PDF frame print events do not bubble to the app window. Notify the receipt
// screen for both frame and page printing, including native cancellation.
export function requestReceiptPrint(print) {
  window.dispatchEvent(new Event(RECEIPT_PRINT_START))
  try { return print() }
  finally { window.dispatchEvent(new Event(RECEIPT_PRINT_END)) }
}
