const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const modulePath = path.join(__dirname, '../src/printing.js');
const { createPrintHandler, pdfWindowOpenOptions } = fs.existsSync(modulePath) ? require(modulePath) : {};

function fixture() {
  const calls = [];
  const frame = { url: 'http://127.0.0.1:8450/invoices' };
  const contents = { mainFrame: frame, isDestroyed: () => false,
    getURL: () => frame.url, print: (...args) => calls.push(args) };
  const win = { webContents: contents, isDestroyed: () => false };
  const handler = createPrintHandler({ getWindow: () => win, billingUrl: 'http://127.0.0.1:8450' });
  return { calls, contents, frame, win, handler, event: { sender: contents, senderFrame: frame } };
}

test('page printing uses the native dialog and waits for its completion callback', async () => {
  const f = fixture();
  let settled = false;
  const result = f.handler(f.event).then(value => { settled = true; return value; });
  assert.equal(f.calls.length, 1);
  assert.deepEqual(f.calls[0][0], { silent: false, printBackground: true });
  await Promise.resolve();
  assert.equal(settled, false);
  f.calls[0][1](true);
  assert.deepEqual(await result, { success: true, cancelled: false });
});

test('cancelling the native dialog is distinct from a printer failure', async () => {
  const f = fixture();
  const cancelled = f.handler(f.event);
  f.calls[0][1](false, 'Print job canceled');
  assert.deepEqual(await cancelled, { success: false, cancelled: true });
  const failed = f.handler(f.event);
  f.calls[1][1](false, 'Invalid printer settings C:/private/device');
  assert.deepEqual(await failed, { success: false, cancelled: false, reason: 'failed' });
});

test('duplicate clicks do not open a second native print dialog', async () => {
  const f = fixture();
  const first = f.handler(f.event);
  assert.deepEqual(await f.handler(f.event), { success: false, cancelled: false, reason: 'busy' });
  assert.equal(f.calls.length, 1);
  f.calls[0][1](false, 'Print job canceled');
  await first;
  const next = f.handler(f.event);
  assert.equal(f.calls.length, 2);
  f.calls[1][1](true);
  await next;
});

test('only the billing main frame of the current main window can print', async () => {
  const f = fixture();
  for (const change of [
    { sender: { ...f.contents } },
    { senderFrame: { url: f.frame.url } },
    { senderFrame: null },
  ]) {
    await assert.rejects(() => f.handler({ ...f.event, ...change }), /not allowed/);
  }
  for (const url of ['https://evil.test/', 'http://127.0.0.1:8451/',
    'http://127.0.0.1:8450@evil.test/', 'about:blank', 'blob:http://127.0.0.1:8450/print']) {
    f.frame.url = url;
    await assert.rejects(() => f.handler(f.event), /not allowed/);
  }
  assert.equal(f.calls.length, 0);
});

test('an unavailable window or native printer exception returns a usable failure', async () => {
  const absent = createPrintHandler({ getWindow: () => null, billingUrl: 'http://127.0.0.1:8450' });
  assert.deepEqual(await absent({}), { success: false, cancelled: false, reason: 'unavailable' });
  const f = fixture();
  f.contents.print = () => { throw new Error('native printer failed'); };
  assert.deepEqual(await f.handler(f.event), { success: false, cancelled: false, reason: 'failed' });
  assert.deepEqual(await f.handler(f.event), { success: false, cancelled: false, reason: 'failed' });
});

test('preload exposes only the fixed page-print IPC operation', async () => {
  let bridge;
  const calls = [];
  const result = { success: true, cancelled: false };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../src/preload.js'), 'utf8'), {
    require: name => {
      assert.equal(name, 'electron');
      return { contextBridge: { exposeInMainWorld: (name, value) => {
        assert.equal(name, 'bizassistDesktop'); bridge = value;
      } }, ipcRenderer: { send() {}, invoke: (...args) => { calls.push(args); return Promise.resolve(result); } } };
    },
    process: { platform: 'win32', versions: { electron: '31.3.0' } },
  });
  assert.equal(typeof bridge.print, 'function');
  assert.equal(await bridge.print({ silent: true, url: 'https://evil.test' }), result);
  assert.deepEqual(calls, [['billing:print']]);
});

test('validated billing blob PDFs open in an isolated viewer with no app preload', () => {
  const url = 'blob:http://127.0.0.1:8450/550e8400-e29b-41d4-a716-446655440000';
  const options = pdfWindowOpenOptions({ url, billingUrl: 'http://127.0.0.1:8450',
    pageUrl: 'http://127.0.0.1:8450/sales' });
  assert.equal(options.action, 'allow');
  assert.deepEqual(options.overrideBrowserWindowOptions.webPreferences, {
    contextIsolation: true, nodeIntegration: false, sandbox: true, plugins: true, preload: null,
  });
});

test('blob recovery windows require an exact billing origin and a browser blob UUID', () => {
  const uuid = '550e8400-e29b-41d4-a716-446655440000';
  for (const url of [
    `blob:https://evil.test/${uuid}`, `blob:http://127.0.0.1:8451/${uuid}`,
    `blob:http://127.0.0.1:8450@evil.test/${uuid}`, `blob:null/${uuid}`,
    `https://127.0.0.1:8450/${uuid}`, 'data:application/pdf;base64,cGRm',
    `file:///tmp/${uuid}.pdf`, `blob:http://127.0.0.1:8450/${uuid}/extra`,
    'blob:http://127.0.0.1:8450/not-a-browser-blob',
    `blob:http://127.0.0.1:8450/${uuid}?extra=1`, `blob:http://127.0.0.1:8450/${uuid}#fragment`,
  ]) {
    assert.equal(pdfWindowOpenOptions({ url, billingUrl: 'http://127.0.0.1:8450',
      pageUrl: 'http://127.0.0.1:8450/sales' }), null, url);
  }
});

test('a navigated billing window cannot open a trusted-origin PDF recovery window', () => {
  const url = 'blob:http://127.0.0.1:8450/550e8400-e29b-41d4-a716-446655440000';
  for (const pageUrl of ['https://evil.test/', 'http://127.0.0.1:8451/', 'about:blank',
    'blob:http://127.0.0.1:8450/550e8400-e29b-41d4-a716-446655440000', '']) {
    assert.equal(pdfWindowOpenOptions({ url, billingUrl: 'http://127.0.0.1:8450', pageUrl }), null);
  }
});
