// Runs the JS readers on the screenshots in tests/fixtures and compares with what the Python readers
// read (expected.json). Open /web/test/test.html from a server at the repo root, or run run.mjs.
import { loadImage } from '../lib/img.js';
import { readStatus, readMesosField } from '../lib/statusbar.js';
import { locateInventory, detectTab, coveredSlots, readPage, LookCache, findCursor, Grid } from '../lib/inventory.js';
import { StackDigits } from '../lib/digits.js';
import { ItemDB } from '../lib/itemdb.js';
import { mat } from '../lib/img.js';

const log = (s) => { document.getElementById('log').textContent += s + '\n'; console.log(s); };
const expected = await (await fetch('./expected.json')).json();
const label = await loadImage('../data/exp_label.png');
const title = await loadImage('../data/inventory_title.png');
const digits = new StackDigits(await (await fetch('../data/stack_digits.json')).json());
const cursors = await (await fetch('../data/cursors.json')).json();
const results = {}, fails = [];
for (const [name, want] of Object.entries(expected)) {
  const t0 = performance.now();
  const frame = await loadImage(`../../tests/fixtures/${name}`);
  const ctx = { expLabel: label };
  const st = await readStatus(frame, ctx);
  const t1 = performance.now();
  const inv = locateInventory(frame, title, ctx);
  const t2 = performance.now();
  const got = { level: st.level, exp: st.exp, pct: st.pct, texts: st.texts, scale: ctx.gameScale };
  if (inv) {
    got.grid = inv.grid.first;
    got.mesos = (await readMesosField(frame, inv.grid)).value;
    got.tab = detectTab(frame, inv.grid);
    got.covered = coveredSlots(frame, inv.grid);
    const cur = findCursor(frame, inv.grid, cursors, ctx.gameScale);
    got.cursor = cur && cur.name;
    const wantCursor = name === 'use_tab_tooltip.png' ? 'open' : null;   // the only one with the pointer over the grid
    if (got.cursor !== wantCursor) fails.push(`${name} cursor: got ${got.cursor} (${cur && cur.score.toFixed(3)}), want ${wantCursor}`);
    const page = await readPage(frame, inv.grid, digits, null, new LookCache());
    got.nums = page.map((row) => row.map((s) => (s.id && s.id !== '?' ? s.qty : 0)));
  }
  const t3 = performance.now();
  got.ms = { status: Math.round(t1 - t0), locate: Math.round(t2 - t1), inventory: Math.round(t3 - t2) };
  results[name] = got;
  for (const k of ['level', 'exp', 'pct', 'mesos', 'tab', 'covered', 'nums']) {
    if (JSON.stringify(got[k]) !== JSON.stringify(want[k])) fails.push(`${name} ${k}: got ${JSON.stringify(got[k])}, want ${JSON.stringify(want[k])}`);
  }
  log(`${name}: ${JSON.stringify(got)}`);
}
// Item names: a small item database whose icons were cut from the first 10 slots of etc_excavation.png,
// plus 300 random icons. Must name every slot as the Python reader does with the same data.
{
  const db = new ItemDB();
  await db.load(await (await fetch('./fake_itemdb.json')).json());
  let seed = 1;
  const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
  for (let k = 0; k < (new URLSearchParams(location.search).get("noise") || 300); k++) {
    const im = mat(32, 32, 4);
    for (let i = 0; i < 32 * 32; i++) { for (let c = 0; c < 3; c++) im.data[4 * i + c] = Math.floor(rnd() * 255); im.data[4 * i + 3] = rnd() < 0.6 ? 255 : 0; }
    db.items[4100000 + k] = { name: `Noise ${k}`, category: 'Use' };
    db.addIcon(4100000 + k, im);
  }
  const want = await (await fetch('./fake_want.json')).json();
  const frame = await loadImage('../../tests/fixtures/etc_excavation.png');
  const ctx = { expLabel: label, gameScale: 1920 / 1366 };
  const inv = locateInventory(frame, title, ctx);
  const t0 = performance.now();
  const page = await readPage(frame, inv.grid, digits, db, new LookCache());
  const ms = Math.round(performance.now() - t0);
  // what the Python reader names with the same item data (see fake_want.json)
  const got = page.map((row) => row.map((s) => (typeof s.id === 'number' ? s.id : null)));
  if (JSON.stringify(got) !== JSON.stringify(want)) fails.push(`items: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
  log(`items: ${JSON.stringify(got)} (${ms} ms for the page, ${db.icons.size} icons)`);
}
// The pointing-hand pointer, on a page picture the browser version saved (screen pixels, 1920x1080 game)
{
  const frame = await loadImage('../../tests/fixtures/cursor_page.png');
  const grid = new Grid([22, 48, 44, 44], [22 + 4 * 50.6, 48 + 5 * 47.8, 44, 44]);
  const cur = findCursor(frame, grid, cursors, 1920 / 1366);
  if (!cur || cur.name !== 'point') fails.push(`cursor_page.png: got ${JSON.stringify(cur)}, want the pointing hand`);
  log(`cursor_page.png: ${JSON.stringify(cur)}`);
}
log(fails.length ? `FAIL\n${fails.join('\n')}` : 'ALL OK');
window.__result = { results, fails };
