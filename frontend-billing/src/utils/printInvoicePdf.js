import { requestReceiptPrint } from './receiptPrintEvents'

/** Load a PDF for printing, retaining its frame until explicit disposal/expiry. */
export function printInvoicePdf(blob, { timeoutMs = 15000, signal, retainUntilDisposed = false } = {}) {
  return new Promise((resolve, reject) => {
    const mime = (blob.type || '').split(';')[0].trim().toLowerCase()
    if (!blob.size || (mime && mime !== 'application/pdf')) {
      reject(new Error('Invoice PDF is unavailable: the server returned an empty or non-PDF document'))
      return
    }
    const frame = document.createElement('iframe')
    const pdf = blob.type === 'application/pdf' ? blob : new Blob([blob], { type: 'application/pdf' })
    const url = URL.createObjectURL(pdf)
    frame.title = 'Invoice print document'
    frame.dataset.invoicePrint = 'true'
    frame.setAttribute('aria-hidden', 'true')
    Object.assign(frame.style, { position: 'fixed', right: '0', bottom: '0', width: '1px', height: '1px', opacity: '0', border: '0' })
    let settled = false
    let cleaned = false
    let expiry
    let cleanupTimer
    const cleanup = () => {
      if (cleaned) return
      cleaned = true
      clearTimeout(expiry)
      clearTimeout(cleanupTimer)
      frame.onload = null
      frame.onerror = null
      frame.remove()
      URL.revokeObjectURL(url)
      signal?.removeEventListener('abort', abort)
    }
    const fail = error => {
      if (settled) return
      settled = true
      cleanup()
      reject(error)
    }
    const abort = () => {
      if (settled) cleanup()
      else fail(new DOMException('Print preparation cancelled', 'AbortError'))
    }
    const print = () => {
      if (cleaned || !frame.contentWindow) throw new Error('Print document unavailable')
      requestReceiptPrint(() => {
        frame.contentWindow.focus()
        frame.contentWindow.print()
      })
    }
    if (signal?.aborted) { abort(); return }
    signal?.addEventListener('abort', abort, { once: true })
    frame.onload = () => {
      if (settled) return
      try {
        print()
        settled = true
        clearTimeout(expiry)
        // Removing the frame immediately can cancel an active print preview.
        if (!retainUntilDisposed) cleanupTimer = setTimeout(cleanup, 60000)
        resolve({ print, dispose: cleanup })
      } catch (error) { fail(error) }
    }
    frame.onerror = () => fail(new Error('Invoice PDF could not be loaded'))
    expiry = setTimeout(() => fail(new Error('Invoice PDF print timed out')), timeoutMs)
    frame.src = url
    document.body.appendChild(frame)
  })
}
