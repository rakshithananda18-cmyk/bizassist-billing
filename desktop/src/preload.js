/**
 * preload.js — minimal, safe bridge.
 * Exposes only what the renderer needs to know it's running inside the desktop shell.
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('bizassistDesktop', {
  isDesktop: true,
  platform: process.platform,
  versions: { electron: process.versions.electron },
  // Telemetry attribution: the billing app reports the logged-in business's
  // BizID (public_id) so shell diagnostics can be grouped per business.
  // Send-only, sanitized in the main process — exposes nothing back.
  setTelemetryBizId: (bizid) => ipcRenderer.send('telemetry:set-bizid', String(bizid || '')),
});
