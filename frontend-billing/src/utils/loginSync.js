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

    const readProfile = async (base, headers) => {
      if (!headers) return null
      try {
        const r = await fetch(`${base}/profile`, { headers })
        if (!r.ok) return null
        return await r.json()
      } catch { return null }
    }

    if (!cloudHeaders) {
      logger.info('[LOGIN-IDENTITY] No cloud-issued token available — skipping cloud identity check (offline or no cloud account).')
    }

    const [cloudProfile, localProfile] = await Promise.all([
      readProfile(CLOUD_URL, cloudHeaders),
      readProfile(LOCAL_URL, localHeaders),
    ])
    const cloudBiz = cloudProfile?.public_id || null
    const localBiz = localProfile?.public_id || null

    // Cloud is the account authority for the premium flag. The cross-device sync
    // nudges below are a PAID feature, so we only surface them for premium
    // accounts. Free accounts still work fully offline — they just don't get the
    // sync prompt.
    const isPremium = !!(cloudProfile?.is_premium ?? localProfile?.is_premium)

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

    // ── Divergence sense (PREMIUM only): is either side missing data the other
    // side holds? Cheap, read-only COUNT comparison — no data is pulled or
    // pushed here (that stays gated behind the user pressing "Sync now"). We
    // surface it on EVERY login (not just the first) so a premium user never
    // silently works on a stale copy.
    if (!isPremium) {
      logger.info('[LOGIN-SENSE] Account is free-tier — skipping cross-device sync nudge (premium feature).')
      return
    }

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

    if (cloudTotal == null || localTotal == null) return

    if (cloudTotal > localTotal) {
      // Cloud is ahead → offer to pull it down onto this device (cloud → local).
      logger.info(`[LOGIN-SENSE] Cloud has more data than this device (cloud=${cloudTotal}, local=${localTotal}) — nudging to sync.`)
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('cloud-data-available', {
          detail: { direction: 'cloud-to-local', cloudTotal, localTotal, delta: cloudTotal - localTotal },
        }))
      }
    } else if (localTotal > cloudTotal) {
      // This device is ahead → the cloud (and other devices) are missing data
      // that lives here. Offer to push it up so nothing is missed on the other
      // devices (local → cloud).
      logger.info(`[LOGIN-SENSE] This device has more data than the cloud (local=${localTotal}, cloud=${cloudTotal}) — nudging to push up.`)
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('cloud-data-available', {
          detail: { direction: 'local-to-cloud', cloudTotal, localTotal, delta: localTotal - cloudTotal },
        }))
      }
    }
  } catch (e) {
    logger.warn('[LOGIN-IDENTITY] check skipped:', e?.message || e)
  }
}
