/**
 * src/invoice/share.js
 * Helpers for sharing public invoice links via WhatsApp or clipboard.
 */

export function buildPublicInvoiceLink(uid_token) {
  return `${window.location.origin}/public/invoice/${uid_token}`
}

export function buildWhatsAppLink(phone, message) {
  const urlParams = new URLSearchParams()
  if (phone) {
    // Strip non-digits from phone
    const digits = String(phone).replace(/\D/g, '')
    urlParams.set('phone', digits)
  }
  urlParams.set('text', message)
  return `https://wa.me/?${urlParams.toString()}`
}

export async function shareInvoice(payload) {
  if (!payload || !payload.invoice || !payload.invoice.uid_token) {
    throw new Error('Invoice is missing public link token (uid_token).')
  }

  const link = buildPublicInvoiceLink(payload.invoice.uid_token)
  const text = `${payload.invoice.title || 'Invoice'} ${payload.invoice.number} from ${payload.seller?.name || 'us'}\n\nView or download it here: ${link}`

  // If mobile with native share support, use it.
  if (navigator.share) {
    try {
      await navigator.share({
        title: `Invoice ${payload.invoice.number}`,
        text: text,
        url: link
      })
      return { method: 'native' }
    } catch (e) {
      if (e.name !== 'AbortError') {
        throw e
      }
      return { method: 'aborted' }
    }
  }

  // Fallback: Copy to clipboard
  await navigator.clipboard.writeText(text)
  return { method: 'clipboard', text }
}
