import release from '../../../backend/release.json'

// Shared with the packaged backend; CI checks package/lock metadata against it.
export const APP_VERSION = release.version
