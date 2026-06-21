// Premium logging utility for the BizAssist Billing Frontend
const PREFIX = '💎 [BizAssist:Billing]'

export const logger = {
  debug: (...args) => {
    if (import.meta.env.DEV) {
      console.log(`%c${PREFIX} [DEBUG]`, 'color: #8b93b8; font-weight: 600;', ...args)
    }
  },
  info: (...args) => {
    console.log(`%c${PREFIX} [INFO]`, 'color: #6c63ff; font-weight: bold;', ...args)
  },
  warn: (...args) => {
    console.warn(`%c${PREFIX} [WARN]`, 'color: #f59e0b; font-weight: bold;', ...args)
  },
  error: (...args) => {
    console.error(`%c${PREFIX} [ERROR]`, 'color: #ef4444; font-weight: bold;', ...args)
  }
}
