// Logging utility for the BizAssist Admin Console.
//
// Mirrors the billing app's logger API so logging is consistent across the repo:
// leveled, prefixed, and tagged with [BizId=…] (the business currently in focus,
// when applicable) for easy grepping and the future Elasticsearch/DDP pipeline.
// The Admin Console has no telemetry sink, so this is console-only.

const PREFIX = '[BizAssist:Admin]'

let _bizId = null
/** Set the BizID currently in focus (e.g. when viewing one business); null to clear. */
export function setBizId(id) { _bizId = id || null }
export function getBizId() { return _bizId }

const tag = () => `[BizId=${_bizId || '-'}]`

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
  },
  error: (...args) => {
    console.error(`%c${PREFIX} [ERROR] ${tag()}`, 'color: #ef4444; font-weight: bold;', ...args)
  }
}
