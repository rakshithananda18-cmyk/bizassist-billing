// Logging utility for the BizAssist AI app.
//
// Mirrors the billing app's logger API so logging is consistent across the repo:
// leveled, prefixed, and tagged with [BizId=…] for easy grepping and the future
// Elasticsearch/DDP pipeline. warn() and error() are also forwarded to the
// telemetry sink so front-end warnings/errors are captured server-side, not just
// in the browser console.
import { logEvent } from './telemetry'

const PREFIX = '[BizAssist:AI]'

let _bizId = null
/** Set the current BizID (public_id, e.g. "BA-JABXGD"); pass null on logout. */
export function setBizId(id) { _bizId = id || null }
export function getBizId() { return _bizId }

const tag = () => `[BizId=${_bizId || '-'}]`

function forward(level, args) {
  try {
    const msg = args
      .map(a => (typeof a === 'string' ? a : (a && a.message) ? a.message : (() => { try { return JSON.stringify(a) } catch { return String(a) } })()))
      .join(' ')
      .slice(0, 500)
    logEvent(`log_${level}`, { biz_id: _bizId || undefined, msg }, level)
  } catch { /* telemetry must never break logging */ }
}

export const logger = {
  debug: (...args) => {
    if (import.meta.env.DEV) {
      console.log(`%c${PREFIX} [DEBUG] ${tag()}`, 'color: #8b93b8; font-weight: 600;', ...args)
    }
  },
  info: (...args) => {
    console.log(`%c${PREFIX} [INFO] ${tag()}`, 'color: #6c63ff; font-weight: bold;', ...args)
  },
  warn: (...args) => {
    console.warn(`%c${PREFIX} [WARN] ${tag()}`, 'color: #f59e0b; font-weight: bold;', ...args)
    forward('warn', args)
  },
  error: (...args) => {
    console.error(`%c${PREFIX} [ERROR] ${tag()}`, 'color: #ef4444; font-weight: bold;', ...args)
    forward('error', args)
  }
}
