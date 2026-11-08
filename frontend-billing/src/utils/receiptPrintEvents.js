export const RECEIPT_PRINT_START = 'billing:receipt-print-start'
export const RECEIPT_PRINT_END = 'billing:receipt-print-end'

// PDF frame print events do not bubble to the app window. Notify the receipt
// screen for both frame and page printing, including native cancellation.
export function requestReceiptPrint(print) {
  window.dispatchEvent(new Event(RECEIPT_PRINT_START))
  const ended = () => window.dispatchEvent(new Event(RECEIPT_PRINT_END))
  try {
    const result = print()
    if (result?.then) return Promise.resolve(result).finally(ended)
    ended()
    return result
  } catch (error) { ended(); throw error }
}
