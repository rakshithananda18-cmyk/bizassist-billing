/** Keep the receipt alive until the PDF has loaded and print() was requested.
 * The caller must retain the saved cart/lock until this promise settles. */
export function printInvoicePdf(blob, { timeoutMs = 15000 } = {}) {
  return new Promise((resolve, reject) => {
    const frame = document.createElement('iframe')
    const pdf = blob.type === 'application/pdf' ? blob : new Blob([blob], { type: 'application/pdf' })
    const url = URL.createObjectURL(pdf)
    frame.title = 'Invoice print document'
    frame.dataset.invoicePrint = 'true'
    frame.setAttribute('aria-hidden', 'true')
    Object.assign(frame.style, { position: 'fixed', right: '0', bottom: '0', width: '1px', height: '1px', opacity: '0', border: '0' })
    let settled = false
    let expiry
    let cleanupTimer
    const cleanup = () => {
      clearTimeout(expiry)
      clearTimeout(cleanupTimer)
      frame.onload = null
      frame.onerror = null
      frame.remove()
      URL.revokeObjectURL(url)
    }
    const fail = error => {
      if (settled) return
      settled = true
      cleanup()
      reject(error)
    }
    frame.onload = () => {
      if (settled) return
      try {
        if (!frame.contentWindow) throw new Error('Print document unavailable')
        frame.contentWindow.focus()
        frame.contentWindow.print()
        settled = true
        clearTimeout(expiry)
        // Removing the frame immediately can cancel an active print preview.
        cleanupTimer = setTimeout(cleanup, 60000)
        resolve()
      } catch (error) { fail(error) }
    }
    frame.onerror = () => fail(new Error('Invoice PDF could not be loaded'))
    expiry = setTimeout(() => fail(new Error('Invoice PDF print timed out')), timeoutMs)
    frame.src = url
    document.body.appendChild(frame)
  })
}
