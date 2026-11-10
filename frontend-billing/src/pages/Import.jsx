// ============================================================================
// Page: Import.jsx — SUPERSEDED.
// Data Migration now lives in Settings under the 'migration' tab
// (/settings?tab=migration). This stub redirects legacy bookmarks and deep-links.
// ============================================================================
import React from 'react'
import { Navigate } from 'react-router-dom'

export default function Import() {
  return <Navigate to="/settings?tab=migration" replace />
}
