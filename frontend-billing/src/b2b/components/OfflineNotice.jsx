// ============================================================================
// b2b/components/OfflineNotice.jsx
// ----------------------------------------------------------------------------
// Explains a degraded B2B mode instead of letting it look like an empty account.
//
// B2B data is cloud-authoritative and a desktop install reaches it through the
// local backend's own cloud token (routes/b2b_proxy.py). If that token doesn't
// exist yet — the device has never signed in while online — the tabs fall back
// to the read-only cloud→local mirror. Connections and orders then render as
// empty or stale lists, which an owner reads as "I have no suppliers", not
// "this machine is offline". Those are very different messages, and only one of
// them is true.
//
// Rendered once at the top of the workspace, above every tab, because the
// caveat applies to all of them equally.
// ============================================================================
import React from 'react'
import { AlertIcon } from '../../components/Icons'

export default function OfflineNotice({ status }) {
  // No status yet, or a healthy link → say nothing. Silence is correct here;
  // a banner that appears on every load would train people to ignore it.
  if (!status || status.cloud_linked !== false) return null

  return (
    <div className="b2b-offline-notice" role="status">
      <AlertIcon size={15} />
      <div>
        <strong>Showing a saved copy — B2B is offline on this device.</strong>
        <p>
          {status.reason ||
            "This device hasn't signed in to the network yet, so it's showing a saved " +
            'copy of your B2B data. Sign in once while you\'re online to send requests, ' +
            'place orders or change anything here.'}
        </p>
      </div>
    </div>
  )
}
