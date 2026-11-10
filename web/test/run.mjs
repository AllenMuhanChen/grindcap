// node web/test/run.mjs : serves the repo, runs test.html in Chromium, exits 1 on a mismatch.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const types = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.png': 'image/png', '.wasm': 'application/wasm', '.gz': 'application/gzip' };
const server = http.createServer((req, res) => {
  const p = path.join(root, decodeURIComponent(new URL(req.url, 'http://x').pathname));
  if (!p.startsWith(root) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { 'Content-Type': types[path.extname(p)] || 'application/octet-stream' });
  fs.createReadStream(p).pipe(res);
}).listen(0);
const port = server.address().port;
const browser = await chromium.launch();
const page = await browser.newPage();
page.on('console', (m) => console.log(m.text()));
page.on('pageerror', (e) => console.log('PAGE ERROR', e.message));
await page.goto(`http://localhost:${port}/web/test/${process.env.PAGE || "test.html"}${process.env.NOISE ? "?noise=" + process.env.NOISE : ""}`);
const r = await page.waitForFunction(() => window.__result, null, { timeout: 240000 }).then((h) => h.jsonValue());
await browser.close();
server.close();
process.exit(r.fails.length ? 1 : 0);
