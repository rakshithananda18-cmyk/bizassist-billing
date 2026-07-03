/**
 * static-server.js — tiny zero-dependency static file server with SPA fallback.
 *
 * Why serve over http://127.0.0.1 instead of file:// ?
 *   1. frontend-billing/src/config.js decides "local app vs cloud" from
 *      window.location.hostname — localhost ⇒ LOCAL backend (:8001). ✔
 *   2. BrowserRouter needs a real origin + SPA fallback to work on refresh. ✔
 */
const http = require('http');
const fs = require('fs');
const path = require('path');

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.map': 'application/json',
  '.txt': 'text/plain; charset=utf-8',
  '.webmanifest': 'application/manifest+json',
};

/**
 * Serve `rootDir` (a Vite dist folder) on 127.0.0.1:`port`.
 * Any path that doesn't resolve to a file falls back to index.html (SPA).
 * Resolves with the http.Server instance.
 */
function serveDist(rootDir, port) {
  return new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      try {
        const urlPath = decodeURIComponent((req.url || '/').split('?')[0]);
        // Prevent path traversal.
        const safePath = path
          .normalize(urlPath)
          .replace(/^(\.\.[/\\])+/, '')
          .replace(/^[/\\]+/, '');
        let filePath = path.join(rootDir, safePath);

        if (!filePath.startsWith(path.normalize(rootDir))) {
          res.writeHead(403);
          return res.end('Forbidden');
        }
        if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
          const indexInDir = path.join(filePath, 'index.html');
          filePath = fs.existsSync(indexInDir)
            ? indexInDir
            : path.join(rootDir, 'index.html'); // SPA fallback
        }

        const ext = path.extname(filePath).toLowerCase();
        res.writeHead(200, {
          'Content-Type': MIME[ext] || 'application/octet-stream',
          'Cache-Control': ext === '.html' ? 'no-cache' : 'public, max-age=31536000, immutable',
        });
        fs.createReadStream(filePath)
          .on('error', () => {
            res.writeHead(500);
            res.end('Read error');
          })
          .pipe(res);
      } catch (err) {
        res.writeHead(500);
        res.end('Server error');
      }
    });

    server.on('error', reject);
    // 127.0.0.1 only — never exposed on the LAN.
    server.listen(port, '127.0.0.1', () => resolve(server));
  });
}

module.exports = { serveDist };
