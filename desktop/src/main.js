/**
 * main.js — BizAssist desktop shell.
 *
 * Boot sequence:
 *   1. single-instance lock
 *   2. spawn bundled FastAPI backend (PyInstaller) → wait for /health on :8001
 *   3. serve frontend-billing dist on http://127.0.0.1:8450
 *      serve frontend-ai      dist on http://127.0.0.1:8451  ("Dashboard BIZASSIST")
 *   4. open main window on :8450, create tray, start auto-updater
 *
 * Shutdown: kill backend tree, close static servers.
 *
 * Dev mode:  BIZASSIST_DEV=1 npx electron .
 *   → loads Vite dev servers (5174 / 5173) and expects `start_dev.bat`'s backend.
 */
const { app, BrowserWindow, Tray, Menu, shell, nativeImage, dialog } = require('electron');
const path = require('path');
const fs = require('fs');
const log = require('electron-log');

const { serveDist } = require('./static-server');
const { startBackend, stopBackend } = require('./backend');
const { initAutoUpdater, checkNow } = require('./updater');
const { sendTelemetry, logTail } = require('./telemetry');

const IS_DEV = !app.isPackaged || process.env.BIZASSIST_DEV === '1';
const BILLING_PORT = 8450;
const AI_PORT = 8451;
// Dev Vite servers may bind IPv6-only ([::1]) — "localhost" resolves either way.
const BILLING_URL = IS_DEV ? 'http://localhost:5174' : `http://127.0.0.1:${BILLING_PORT}`;
const AI_URL = IS_DEV ? 'http://localhost:5173' : `http://127.0.0.1:${AI_PORT}`;

// Set FRAMELESS to true for a borderless window (app renders its own chrome).
const FRAMELESS = false;

let mainWindow = null;
let aiWindow = null;
let tray = null;
let servers = [];
let quitting = false;

log.transports.file.level = 'info';
log.info(`BizAssist desktop starting (dev=${IS_DEV})`);

// Kill the default "File Edit View Window Help" bar on Windows/Linux.
// Kept on macOS: the app menu supplies Cmd+C/V/Q and is expected there.
if (process.platform !== 'darwin') Menu.setApplicationMenu(null);

// ── Single instance ───────────────────────────────────────────────────────────
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });
}

// ── Windows ───────────────────────────────────────────────────────────────────
function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 640,
    fullscreen: true,          // distraction-free POS: launch fullscreen (F11 toggles)
    frame: !FRAMELESS,
    titleBarStyle: FRAMELESS ? 'hidden' : 'default',
    backgroundColor: '#0b1020',
    show: false,
    icon: path.join(__dirname, '..', 'build', 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.loadURL(BILLING_URL);

  // No menu bar → wire the essentials ourselves: F11 exits/re-enters
  // fullscreen, Ctrl+Shift+I opens DevTools (field debugging).
  mainWindow.webContents.on('before-input-event', (e, input) => {
    if (input.type !== 'keyDown') return;
    if (input.key === 'F11') {
      mainWindow.setFullScreen(!mainWindow.isFullScreen());
      e.preventDefault();
    }
    if (input.control && input.shift && input.key.toLowerCase() === 'i') {
      mainWindow.webContents.toggleDevTools();
      e.preventDefault();
    }
    // Ctrl+R -> Reload/Refresh
    if (input.control && input.key.toLowerCase() === 'r') {
      if (input.shift) {
        // Ctrl+Shift+R -> Hard Reload (clear cache first)
        mainWindow.webContents.session.clearCache().then(() => {
          mainWindow.webContents.reloadIgnoringCache();
        });
      } else {
        mainWindow.webContents.reload();
      }
      e.preventDefault();
    }
    // Ctrl+F5 -> Hard Reload
    if (input.control && input.key === 'F5') {
      mainWindow.webContents.session.clearCache().then(() => {
        mainWindow.webContents.reloadIgnoringCache();
      });
      e.preventDefault();
    }
  });

  // "Dashboard BIZASSIST" (frontend-ai) opens in its own window;
  // every other external target goes to the OS browser.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith(AI_URL)) {
      openAiWindow(url);
      return { action: 'deny' };
    }
    if (/^https?:\/\//.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });

  // Close-to-tray: the POS keeps running in the background.
  mainWindow.on('close', (e) => {
    if (!quitting) {
      e.preventDefault();
      mainWindow.hide();
    }
  });
  mainWindow.on('closed', () => { mainWindow = null; });
}

function openAiWindow(url) {
  if (aiWindow && !aiWindow.isDestroyed()) {
    if (url) {
      aiWindow.loadURL(url);
    }
    aiWindow.show();
    aiWindow.focus();
    return;
  }
  aiWindow = new BrowserWindow({
    width: 1280,
    height: 840,
    backgroundColor: '#0b1020',
    title: 'Dashboard BIZASSIST',
    icon: path.join(__dirname, '..', 'build', 'icon.png'),
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  
  aiWindow.webContents.on('before-input-event', (e, input) => {
    if (input.type !== 'keyDown') return;
    if (input.key === 'F11') {
      aiWindow.setFullScreen(!aiWindow.isFullScreen());
      e.preventDefault();
    }
    if (input.control && input.shift && input.key.toLowerCase() === 'i') {
      aiWindow.webContents.toggleDevTools();
      e.preventDefault();
    }
    // Ctrl+R -> Reload/Refresh
    if (input.control && input.key.toLowerCase() === 'r') {
      if (input.shift) {
        aiWindow.webContents.session.clearCache().then(() => {
          aiWindow.webContents.reloadIgnoringCache();
        });
      } else {
        aiWindow.webContents.reload();
      }
      e.preventDefault();
    }
    // Ctrl+F5 -> Hard Reload
    if (input.control && input.key === 'F5') {
      aiWindow.webContents.session.clearCache().then(() => {
        aiWindow.webContents.reloadIgnoringCache();
      });
      e.preventDefault();
    }
  });

  aiWindow.loadURL(url || AI_URL);
  aiWindow.on('closed', () => { aiWindow = null; });
}

// ── Tray ──────────────────────────────────────────────────────────────────────
function createTray() {
  const iconFile = process.platform === 'win32' ? 'icon.ico' : 'trayTemplate.png';
  const iconPath = path.join(__dirname, '..', 'build', iconFile);
  const icon = fs.existsSync(iconPath)
    ? nativeImage.createFromPath(iconPath)
    : nativeImage.createEmpty();

  tray = new Tray(icon.isEmpty() ? icon : icon.resize({ width: 16, height: 16 }));
  tray.setToolTip('BizAssist — Billing & POS');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Open BizAssist', click: () => { mainWindow ? mainWindow.show() : createMainWindow(); } },
    { label: 'Dashboard BIZASSIST', click: () => openAiWindow() },
    { type: 'separator' },
    { label: 'Check for updates…', click: () => checkNow(), enabled: !IS_DEV },
    { type: 'separator' },
    { label: 'Quit', click: () => { quitting = true; app.quit(); } },
  ]));
  tray.on('double-click', () => { mainWindow ? mainWindow.show() : createMainWindow(); });
}

// ── Boot ──────────────────────────────────────────────────────────────────────
async function boot() {
  const bootStart = Date.now();
  if (!IS_DEV) {
    sendTelemetry('boot_start', { version: app.getVersion() });
    const rendererRoot = path.join(process.resourcesPath, 'renderer');

    const ok = await startBackend(process.resourcesPath, app.getPath('userData'));
    if (!ok) {
      // Ship the log tail so field failures are debuggable without file access.
      sendTelemetry('backend_start_failed', { logTail: logTail(40) }, 'error');
      dialog.showErrorBox(
        'BizAssist could not start',
        'The local engine failed to start. Please restart the app.\n' +
        `Log: ${log.transports.file.getFile().path}`
      );
      app.exit(1);
      return;
    }

    servers.push(await serveDist(path.join(rendererRoot, 'billing'), BILLING_PORT));
    const aiDist = path.join(rendererRoot, 'ai');
    if (fs.existsSync(aiDist)) servers.push(await serveDist(aiDist, AI_PORT));
    sendTelemetry('boot_ok', { ms: Date.now() - bootStart, aiBundled: fs.existsSync(aiDist) });
  }

  createMainWindow();
  createTray();
  if (!IS_DEV) initAutoUpdater();
}

app.whenReady().then(boot).catch((err) => {
  log.error(`boot failed: ${err.stack || err}`);
  sendTelemetry('boot_crashed', { error: String(err.message || err), logTail: logTail(40) }, 'error');
  dialog.showErrorBox('BizAssist failed to start', String(err.message || err));
  app.exit(1);
});

app.on('activate', () => {           // macOS dock re-open
  if (mainWindow) mainWindow.show();
  else if (app.isReady()) createMainWindow();
});

app.on('before-quit', () => { quitting = true; });

app.on('window-all-closed', () => {
  // Keep running in tray on all platforms; Quit only via tray/menu.
});

app.on('quit', () => {
  stopBackend();
  servers.forEach((s) => { try { s.close(); } catch (_) { /* noop */ } });
  servers = [];
});

// Absolute last resort — never leave an orphaned backend.
process.on('exit', stopBackend);
