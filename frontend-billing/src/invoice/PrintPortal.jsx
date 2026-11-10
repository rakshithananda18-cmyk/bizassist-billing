// src/invoice/PrintPortal.jsx — A4 print isolation (plan Phase 1).
// ================================================================
// Same proven pattern as ThermalReceipt: render the selected template into
// document.body via a portal; `@media print` CSS (index.css §invoice-a4) hides
// the app and shows ONLY #invoice-a4-root on an A4 page. The portal is mounted
// permanently while the viewer is open so window.print() needs no timing tricks.
import { createPortal } from 'react-dom'

export default function PrintPortal({ children }) {
  return createPortal(
    <div id="invoice-a4-root">{children}</div>,
    document.body,
  )
}

/** Trigger the browser print dialog (also the "Download PDF" path via
 *  print-to-PDF). Kept as a helper so tests can spy on it. */
export async function triggerPrint() {
  if (window.bizassistDesktop?.print) {
    const result = await window.bizassistDesktop.print()
    // Cancelling the native dialog is a normal outcome, not a print failure.
    if (!result?.success && !result?.cancelled) throw new Error('Native print dialog unavailable')
    return
  }
  window.print()
}
