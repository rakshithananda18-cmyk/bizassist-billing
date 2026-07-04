/**
 * telemetry.js — testing-phase diagnostics from the desktop shell.
 *
 * Every event is:
 *   1. logged locally via electron-log (main.log), AND
 *   2. shipped fire-and-forget to the LOCAL backend and the CLOUD backend
 *      (POST /api/telemetry/log) so field installs can be debugged remotely.
 *
 * No business data — only app/install diagnostics (versions, timings, errors).
 * Kill switch: set TELEMETRY=0 in the app environment, or TELEMETRY_ENABLED=0
 * on the backends.
 */
const { app } = require('electron');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const log = require('electron-log');

const CLOUD_URL = process.env.BIZASSIST_CLOUD_URL || 'https://rakshit-dev-bizassist.hf.space';
const LOCAL_URL = 'http://127.0.0.1:8001';
const ENABLED = process.env.TELEMETRY !== '0';

let deviceId = null;
let currentBizId = null;

/** Stable anonymous install id, persisted in userData. */
function getDeviceId() {
  if (deviceId) return deviceId;
  try {
    const p = path.join(app.getPath('userData'), 'device-id');
    if (fs.existsSync(p)) {
      deviceId = fs.readFileSync(p, 'utf8').trim();
    } else {
      deviceId = crypto.randomUUID();
      fs.writeFileSync(p, deviceId);
    }
  } catch {
    deviceId = 'unknown-' + crypto.randomBytes(4).toString('hex');
  }
  return deviceId;
}

/**
 * BizID (business public_id) attribution. The renderer reports it after login
 * (IPC 'telemetry:set-bizid'); we persist the last-known value so pre-login
 * boot events on the NEXT launch are still attributable to the business.
 */
function _bizidPath() { return path.join(app.getPath('userData'), 'last-bizid'); }

function setTelemetryBizId(bizid) {
  const clean = String(bizid || '').replace(/[^A-Za-z0-9_\-]/g, '').slice(0, 64);
  currentBizId = clean || null;
  try {
    if (clean) fs.writeFileSync(_bizidPath(), clean);
    else if (fs.existsSync(_bizidPath())) fs.unlinkSync(_bizidPath());   // logout → detach
  } catch { /* best-effort */ }
}

function getTelemetryBizId() {
  if (currentBizId) return currentBizId;
  try {
    if (fs.existsSync(_bizidPath())) {
      currentBizId = fs.readFileSync(_bizidPath(), 'utf8').trim() || null;
    }
  } catch { /* best-effort */ }
  return currentBizId;
}

async function postTo(base, body) {
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 5000);
    await fetch(`${base}/api/telemetry/log`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    clearTimeout(t);
  } catch {
    /* fire-and-forget — never break the app over telemetry */
  }
}

/**
 * sendTelemetry('boot_ok', { ms: 4200 })
 * sendTelemetry('backend_start_failed', { logTail }, 'error')
 */
function sendTelemetry(event, payload = {}, level = 'info') {
  const line = `[telemetry] ${event} ${JSON.stringify(payload)}`;
  (level === 'error' ? log.error : level === 'warn' ? log.warn : log.info)(line);
  if (!ENABLED) return;

  const body = {
    source: 'desktop-shell',
    device_id: getDeviceId(),
    app_version: app.getVersion(),
    platform: `${process.platform}-${process.arch}`,
    events: [{ event, level, payload, at: new Date().toISOString() }],
  };
  const bizid = getTelemetryBizId();
  if (bizid) body.bizid = bizid;   // groups events per business on the backend
  // Local lands in the local backend's log file; cloud lands on the HF Space.
  postTo(LOCAL_URL, body);
  postTo(CLOUD_URL, body);
}

/** Last N lines of the shell's own log file (for failure reports). */
function logTail(lines = 40) {
  try {
    const p = log.transports.file.getFile().path;
    const content = fs.readFileSync(p, 'utf8');
    return content.split(/\r?\n/).slice(-lines).join('\n');
  } catch {
    return '(log unavailable)';
  }
}

module.exports = { sendTelemetry, logTail, setTelemetryBizId };
