import { isEmbeddedGuidedTour } from './guidedTourRuntime'

// Preview redaction belongs only to the public, embedded sample tour. It must
// never replace a signed-in store's working data or its own privacy setting.
export function isProtectedTourPreview(user, location = window.location, framed) {
  return user?.is_demo === true && (framed !== undefined ? isEmbeddedGuidedTour(location, framed) : isEmbeddedGuidedTour(location))
}

export const PRIVATE_STOCK_COLUMNS = new Set(['cost', 'wholesale', 'distributor', 'roi', 'profit', 'netcost', 'netmrp'])
