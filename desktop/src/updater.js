/**
 * updater.js — silent background auto-update via GitHub Releases.
 *
 * Flow: check on launch (+ every 4h) → download silently → small dialog
 * "Restart now / Later". "Later" installs on next quit automatically.
 *
 * NOTE: works while the GitHub repo is PUBLIC. If the repo goes private,
 * either (a) publish releases to a separate public repo (change `publish`
 * in package.json), or (b) switch to a generic provider (S3/R2/any static
 * host serving latest.yml + installers). electron-updater cannot read
 * private GitHub releases without shipping a token inside the app.
 */
const { dialog, BrowserWindow } = require('electron');
const { autoUpdater } = require('electron-updater');
const log = require('electron-log');
const { sendTelemetry } = require('./telemetry');

const FOUR_HOURS = 4 * 60 * 60 * 1000;
let promptShown = false;

function initAutoUpdater() {
  autoUpdater.logger = log;
  autoUpdater.autoDownload = true;          // silent download in background
  autoUpdater.autoInstallOnAppQuit = true;  // "Later" still applies on quit

  autoUpdater.on('update-available', (info) => {
    log.info(`[updater] update available: ${info.version} — downloading silently`);
    sendTelemetry('update_available', { to: info.version });
  });

  autoUpdater.on('update-downloaded', async (info) => {
    if (promptShown) return;
    promptShown = true;
    const win = BrowserWindow.getAllWindows()[0];
    const { response } = await dialog.showMessageBox(win, {
      type: 'info',
      title: 'Update ready',
      message: `BizAssist ${info.version} has been downloaded.`,
      detail: 'Restart to apply the update. Your data is untouched.',
      buttons: ['Restart now', 'Later'],
      defaultId: 0,
      cancelId: 1,
    });
    if (response === 0) {
      sendTelemetry('update_install_now', { to: info.version });
      setImmediate(() => autoUpdater.quitAndInstall(true, true));
    } else {
      sendTelemetry('update_deferred', { to: info.version });
      promptShown = false; // allow re-prompt on next cycle
    }
  });

  autoUpdater.on('error', (err) => {
    log.warn(`[updater] ${err.message}`);
    sendTelemetry('update_error', { error: err.message }, 'warn');
  });

  const check = () => autoUpdater.checkForUpdates().catch((e) => log.warn(`[updater] ${e.message}`));
  // First check shortly after launch so it never delays window paint.
  setTimeout(check, 10_000);
  setInterval(check, FOUR_HOURS);
}

/** Manual "Check for updates" from the tray menu. */
function checkNow() {
  autoUpdater.checkForUpdates().catch((e) => log.warn(`[updater] ${e.message}`));
}

module.exports = { initAutoUpdater, checkNow };
