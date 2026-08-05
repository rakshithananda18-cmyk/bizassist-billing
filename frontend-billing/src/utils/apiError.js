// utils/apiError.js — one readable line out of a FastAPI error body.
// ----------------------------------------------------------------------------
// `detail` arrives in three shapes and only one of them is a string:
//
//   422 validation → [{loc: ['body','connect_as'], msg: 'Field required', …}]
//   4xx raised     → "Product is used by 10 sales invoices…"
//   anything else  → an object, or nothing at all
//
// Handed straight to `new Error()` or an alert banner, the ARRAY case renders as
// "[object Object]" — which is how a plain missing-field error reads as an
// unexplained failure. That cost a debugging session on the B2B connect form.
//
// This existed as four near-copies (b2bClient, Parties, Stock ×2) that disagreed
// on whether to show the full `loc` path or its last segment. Last segment wins:
// the reader wants "connect_as", not "body.connect_as".
export function formatApiError(body, fallback = 'Something went wrong.') {
  const detail = body?.detail

  if (typeof detail === 'string' && detail) return detail

  if (Array.isArray(detail)) {
    const lines = detail.map(e => `${e?.loc?.slice(-1)[0] ?? 'field'}: ${e?.msg || 'invalid'}`)
    return lines.length ? lines.join('; ') : fallback
  }

  // A dict detail is unusual and has no agreed shape, so show it rather than
  // swallowing it — an ugly line beats a generic one when something is wrong.
  if (detail && typeof detail === 'object') return JSON.stringify(detail)

  return body?.message || fallback
}

export default formatApiError
