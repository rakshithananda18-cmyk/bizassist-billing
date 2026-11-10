// Execute the actual desktop probe body with an in-memory HTTP transport.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { EventEmitter } = require('events');
const assert = require('assert');
const root = path.resolve(__dirname, '../../../..');
const source = fs.readFileSync(path.join(root, 'desktop/src/backend.js'), 'utf8');

async function check(status, body) {
  const fakeHttp = { get: (_options, callback) => {
    const req = new EventEmitter();
    req.destroy = () => {};
    queueMicrotask(() => {
      const res = new EventEmitter();
      res.statusCode = status;
      callback(res);
      res.emit('data', body);
      res.emit('end');
    });
    return req;
  }};
  const context = { module: { exports: {} }, process, setTimeout, clearTimeout,
    require: (name) => name === 'http' ? fakeHttp : name === 'electron-log' ? { info(){}, warn(){}, error(){} } : require(name),
  };
  vm.runInNewContext(source + '\nmodule.exports.auditProbe = probe;', context, { filename: 'desktop/src/backend.js' });
  return context.module.exports.auditProbe();
}

(async () => {
  const cases = [
    [200, '{"status":"error","db":"disconnected"}', false],
    [200, '{"status":"ok","db":"connected"}', true],
    [200, 'not-json', false],
    [503, '{"status":"ok","db":"connected"}', false],
  ];
  for (const [status, body, expected] of cases) assert.strictEqual(await check(status, body), expected);
  console.log(JSON.stringify({actualDesktopProbeCases: cases.length, passed: true}));
})().catch((error) => { console.error(error); process.exitCode = 1; });
