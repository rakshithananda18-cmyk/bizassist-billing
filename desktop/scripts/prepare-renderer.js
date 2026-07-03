/**
 * prepare-renderer.js — copy built frontends into desktop/resources/renderer.
 * Run AFTER `npm run build` in frontend-billing and frontend-ai.
 *
 *   node scripts/prepare-renderer.js
 *
 * Layout produced (consumed by electron-builder extraResources):
 *   desktop/resources/renderer/billing/   ← frontend-billing/dist
 *   desktop/resources/renderer/ai/        ← frontend-ai/dist
 */
const fs = require('fs');
const path = require('path');

const repoRoot = path.resolve(__dirname, '..', '..');
const out = path.resolve(__dirname, '..', 'resources', 'renderer');

const jobs = [
  { from: path.join(repoRoot, 'frontend-billing', 'dist'), to: path.join(out, 'billing'), required: true },
  { from: path.join(repoRoot, 'frontend-ai', 'dist'), to: path.join(out, 'ai'), required: false },
];

fs.rmSync(out, { recursive: true, force: true });

for (const { from, to, required } of jobs) {
  if (!fs.existsSync(path.join(from, 'index.html'))) {
    const msg = `Missing build: ${from} (run \`npm run build\` there first)`;
    if (required) { console.error('✖ ' + msg); process.exit(1); }
    console.warn('⚠ ' + msg + ' — skipping');
    continue;
  }
  fs.cpSync(from, to, { recursive: true });
  console.log(`✔ ${from} → ${to}`);
}
console.log('Renderer resources ready.');
