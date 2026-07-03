/**
 * preload.js — minimal, safe bridge.
 * Exposes only what the renderer needs to know it's running inside the desktop shell.
 */
const { contextBridge } = require('electron');

contextBridge.exposeInMainWorld('bizassistDesktop', {
  isDesktop: true,
  platform: process.platform,
  versions: { electron: process.versions.electron },
});
