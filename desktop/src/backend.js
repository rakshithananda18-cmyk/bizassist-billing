/**
 * backend.js — lifecycle of the bundled FastAPI backend (PyInstaller onedir build).
 *
 * Packaged layout (see electron-builder `extraResources`):
 *   <resources>/backend/bizassist-backend(.exe)   ← PyInstaller onedir entry
 *   <resources>/backend/_internal/...             ← its libs
 *
 * The exe runs uvicorn on 127.0.0.1:8001 (what frontend config.js expects).
 */
const { spawn, execSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');
const log = require('electron-log');

const BACKEND_HOST = '127.0.0.1';
const BACKEND_PORT = 8001;

let proc = null;

function exePath(resourcesPath) {
  const name = process.platform === 'win32' ? 'bizassist-backend.exe' : 'bizassist-backend';
  return path.join(resourcesPath, 'backend', name);
}

/** One health probe against GET /health. */
function probe() {
  return new Promise((resolve) => {
    const req = http.get(
      { host: BACKEND_HOST, port: BACKEND_PORT, path: '/health', timeout: 2000 },
      (res) => {
        res.resume();
        resolve(res.statusCode === 200);
      }
    );
    req.on('error', () => resolve(false));
    req.on('timeout', () => {
      req.destroy();
      resolve(false);
    });
  });
}

/** Poll /health until the backend answers (or time out). */
async function waitUntilHealthy(timeoutMs = 60000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await probe()) return true;
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

/**
 * Spawn the backend quietly (no console window) and wait for /health.
 * If something is already answering on :8001 (e.g. a dev backend), reuse it.
 */
async function startBackend(resourcesPath, userDataDir) {
  if (await probe()) {
    log.info('[backend] already running on :8001 — reusing');
    return true;
  }

  const exe = exePath(resourcesPath);
  if (!fs.existsSync(exe)) {
    log.error(`[backend] executable not found: ${exe}`);
    return false;
  }

  // Keep the SQLite DB + logs in the per-user app-data dir so updates never wipe data.
  const dataDir = path.join(userDataDir, 'data');
  fs.mkdirSync(dataDir, { recursive: true });

  proc = spawn(exe, ['--host', BACKEND_HOST, '--port', String(BACKEND_PORT)], {
    cwd: path.dirname(exe),
    env: {
      ...process.env,
      BIZASSIST_DATA_DIR: dataDir,
      BIZASSIST_DESKTOP: '1',
      // Persist a rotating backend log next to the DB so "Settings → Download
      // logs" (GET /diagnostics/logs) has something to package. Backend stdout is
      // still mirrored into the Electron main.log too.
      LOG_FILE: path.join(dataDir, 'bizassist.log'),
    },
    windowsHide: true, // no flashing console on Windows
    detached: false,
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  proc.stdout.on('data', (d) => log.info(`[backend] ${d.toString().trimEnd()}`));
  proc.stderr.on('data', (d) => log.warn(`[backend] ${d.toString().trimEnd()}`));
  proc.on('exit', (code, signal) => {
    log.info(`[backend] exited code=${code} signal=${signal}`);
    proc = null;
  });

  const healthy = await waitUntilHealthy();
  if (!healthy) log.error('[backend] failed to become healthy within 60s');
  return healthy;
}

/** Kill the backend and its whole process tree. Safe to call repeatedly. */
function stopBackend() {
  if (!proc || proc.killed) return;
  const pid = proc.pid;
  log.info(`[backend] stopping pid=${pid}`);
  try {
    if (process.platform === 'win32') {
      // /T kills child workers PyInstaller/uvicorn may have spawned.
      execSync(`taskkill /PID ${pid} /T /F`, { windowsHide: true, stdio: 'ignore' });
    } else {
      proc.kill('SIGTERM');
      // Escalate if it ignores SIGTERM.
      setTimeout(() => {
        try { proc && proc.kill('SIGKILL'); } catch (_) { /* already dead */ }
      }, 3000);
    }
  } catch (err) {
    log.warn(`[backend] kill error: ${err.message}`);
  }
  proc = null;
}

module.exports = { startBackend, stopBackend, BACKEND_PORT };
