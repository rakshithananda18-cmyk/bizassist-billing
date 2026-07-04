import { IS_LOCAL_APP, CLOUD_URL, LOCAL_URL } from '../config'
import { logger } from './logger'

/**
 * reconcileBizIdOnLogin — lightweight IDENTITY check after login. NOT a data sync.
 *
 * Design intent: cloud data is subscription-gated, so logging in must NOT silently
 * pull the whole dataset down. The only thing worth doing silently at login is a
 * tiny **BizID consistency check** — confirm the local account's BizID matches the
 * cloud's. A **full data sync (cloud → local) stays gated**: it happens only when
 * the user asks (the "Back up now" button) or during a migration.
 *
 * Scope (safe & read-only):
 *   • Downloaded app only (it can reach localhost:8001).
 *   • Local & Hybrid modes when online — Cloud mode is the identity home, nothing to reconcile.
 *   • Reads `/profile` on both backends and compares `public_id` (BizID). No writes, no bulk data.
 *
 * On mismatch we log a warning (the unify happens during backup/migration, where
 * `_upsert_users` copies the cloud BizID onto the local owner). Best-effort:
 * any failure is swallowed — login is already complete.
 */
export async function reconcileBizIdOnLogin(token, cloudToken = null) {
  try {
    if (!IS_LOCAL_APP) return
    if (typeof navigator !== 'undefined' && navigator.onLine === false) return

    const mode = (typeof localStorage !== 'undefined'
      && localStorage.getItem('bizassist_hosting_mode')) || 'local'
    if (mode === 'cloud') return   // cloud is the identity home — nothing to reconcile locally

    // IMPORTANT: tokens are backend-specific. The local backend signs JWTs
    // with its OWN secret (random per install on packaged builds), so the
    // cloud rejects them with 401 "Invalid token" — which both breaks this
    // check AND floods the cloud auth log. Cloud reads therefore require a
    // cloud-issued token; without one we skip the cloud half quietly.
    const headersFor = (t) => ({
      'Content-Type': 'application/json',
      ...(t ? { Authorization: `Bearer ${t}` } : {}),
    })
    const localHeaders = headersFor(token)
    const cloudHeaders = cloudToken ? headersFor(cloudToken) : null

    const readBiz = async (base, headers) => {
      if (!headers) return null
      try {
        const r = await fetch(`${base}/profile`, { headers })
        if (!r.ok) return null
        const p = await r.json()
        return p?.public_id || null
      } catch { return null }
    }

    if (!cloudHeaders) {
      logger.info('[LOGIN-IDENTITY] No cloud-issued token available — skipping cloud identity check (offline or no cloud account).')
    }

    const [cloudBiz, localBiz] = await Promise.all([
      readBiz(CLOUD_URL, cloudHeaders),
      readBiz(LOCAL_URL, localHeaders),
    ])

    if (!cloudBiz) {
      // No cloud identity reachable (offline / no cloud account yet) — nothing to do.
      return
    }
    if (!localBiz) {
      logger.warn(`[LOGIN-IDENTITY] Local account has no BizID; cloud=${cloudBiz}. It will unify on the next backup/migration.`)
    } else if (localBiz !== cloudBiz) {
      logger.warn(`[LOGIN-IDENTITY] BizID mismatch — local=${localBiz} cloud=${cloudBiz}. Run a backup/migration to unify identity.`)
    } else {
      logger.info(`[LOGIN-IDENTITY] BizID consistent (${localBiz}).`)
    }

    // ── Divergence sense: does the cloud hold data this device doesn't have? ──
    // Cheap, read-only COUNT comparison (no data pulled — stays gated). If the
    // cloud has meaningfully more records, nudge the user to sync. We never
    // auto-pull; we just surface that the local copy may be behind.
    const readTotal = async (base, headers) => {
      if (!headers) return null
      try {
        const r = await fetch(`${base}/api/data-transfer/count`, { headers })
        if (!r.ok) return null
        const counts = await r.json()
        return Object.values(counts || {}).reduce((a, n) => a + (Number(n) > 0 ? Number(n) : 0), 0)
      } catch { return null }
    }
    const [cloudTotal, localTotal] = await Promise.all([
      readTotal(CLOUD_URL, cloudHeaders),
      readTotal(LOCAL_URL, localHeaders),
    ])
    if (cloudTotal != null && localTotal != null && cloudTotal > localTotal) {
      logger.info(`[LOGIN-SENSE] Cloud has more data than this device (cloud=${cloudTotal}, local=${localTotal}) — nudging to sync.`)
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('cloud-data-available', {
          detail: { cloudTotal, localTotal, delta: cloudTotal - localTotal },
        }))
      }
    }
  } catch (e) {
    logger.warn('[LOGIN-IDENTITY] check skipped:', e?.message || e)
  }
}
