import { logger } from './logger'

/** Observe UI background work without allowing rejected promises to escape. */
export function runAsync(action, { notify = true, message = 'Unable to complete this action. Please try again.' } = {}) {
  const report = error => {
    if (error?.name === 'AbortError' || error?.name === 'CanceledError'
        || error?.code === 'ERR_CANCELED' || error?.message === 'Session changed'
        || error?.message === 'Session expired') return
    // Reporting must also be safe during teardown or blocked browser storage.
    try {
      logger.error('[UI action failed]', error)
      if (notify && typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('show_toast', { detail: { type: 'error', msg: message } }))
      }
    } catch { /* An error reporter must never create another rejected promise. */ }
  }
  // Start synchronously so keyboard/form handlers can still prevent the
  // browser's default action before awaiting their network request.
  try {
    Promise.resolve(action()).catch(report)
  } catch (error) {
    report(error)
  }
}
