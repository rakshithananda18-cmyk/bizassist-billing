// Logging utility for the BizAssist Billing frontend.
//
// Every line is tagged with the current business's BizID (public_id) for easy
// grepping and to line up with the backend's [BizId=…] format and the future
// Elasticsearch/DDP pipeline. Call setBizId() on login/logout to keep it current.
//
// warn() and error() are ALSO forwarded to the telemetry sink (telemetry.js →
// /api/telemetry/log on the active backend AND cloud), so front-end warnings and
// errors are captured server-side / to the backend log file — not just the
// browser console.
import { logEvent } from './telemetry'

const PREFIX = '[BizAssist:Billing]'

let _bizId = null
/** Set the current BizID (public_id, e.g. "BA-JABXGD"); pass null on logout. */
export function setBizId(id) { _bizId = id || null }
export function getBizId() { return _bizId }

const tag = () => `[BizId=${_bizId || '-'}]`

// Fire-and-forget forward of warn/error to the telemetry pipeline. Never throws
// and never recurses back into the logger.
//
// THROTTLED: reconnect loops (e.g. SSE errors, repeated 401s) can emit the same
// error many times per second. We (1) drop an identical message if it was
// forwarded in the last _FWD_DEDUP_MS, and (2) cap total forwards per minute —
// so an error storm can't flood telemetry/network. Console logging is NOT
// throttled; only the telemetry forward is.
const _recentForwards = new Map()   // key -> last-sent timestamp
let _fwdWindowStart = Date.now()
let _fwdWindowCount = 0
const _FWD_DEDUP_MS = 10000         // same message: at most once per 10s
const _FWD_MAX_PER_MIN = 20         // overall cap

function forward(level, args) {
  try {
    const msg = args
      .map(a => (typeof a === 'string' ? a : (a && a.message) ? a.message : (() => { try { return JSON.stringify(a) } catch { return String(a) } })()))
      .join(' ')
      .slice(0, 500)

    const now = Date.now()
    const key = level + '|' + msg.slice(0, 140)
    const last = _recentForwards.get(key)
    if (last && (now - last) < _FWD_DEDUP_MS) return   // duplicate storm → drop
    _recentForwards.set(key, now)
    if (_recentForwards.size > 200) _recentForwards.clear()   // bound memory

    if (now - _fwdWindowStart > 60000) { _fwdWindowStart = now; _fwdWindowCount = 0 }
    if (_fwdWindowCount >= _FWD_MAX_PER_MIN) return    // rate cap reached this minute
    _fwdWindowCount++

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
