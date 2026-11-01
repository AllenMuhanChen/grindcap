// Runs the JS readers on the screenshots in tests/fixtures and compares with what the Python readers
// read (expected.json). Open /web/test/test.html from a server at the repo root, or run run.mjs.
import { loadImage } from '../lib/img.js';
import { readStatus, readMesosField } from '../lib/statusbar.js';
import { locateInventory, detectTab, coveredSlots, readPage, LookCache, findCursor, Grid } from '../lib/inventory.js';
import { StackDigits } from '../lib/digits.js';
import { ItemDB } from '../lib/itemdb.js';
import { mat } from '../lib/img.js';
import { readMap } from '../lib/mapname.js';
import { readQuickslot, potionSeries, prices, describe, matchByCount } from '../lib/quickslot.js';

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
// Map names from the minimap (same cases as tests/test_snapshot.py)
{
  const header = await loadImage('../data/minimap_header.png');
  const rain = [{ streetName: 'Victoria Road', name: 'The Rain-Forest East of Henesys' }, { streetName: 'Victoria Road', name: 'The Rain-Forest East of Henesys 2' }];
  const cases = [
    ['game_frame.png', rain, 'Victoria Road', 'The Rain-Forest East of Henesys'],
    ['use_tab_tooltip.png', rain, 'Victoria Road', 'The Rain-Forest East of Henesys'],
    ['etc_ant_tunnel.png', ['Ant Tunnel I', 'Ant Tunnel II', 'Ant Tunnel III', 'Ant Tunnel IV', 'Deep Ant Tunnel I'].map((n) => ({ streetName: 'Dungeon', name: n })), 'Dungeon', 'Ant Tunnel IV'],
    ['etc_excavation.png', ['I', 'II', 'III', 'IV'].map((n) => ({ streetName: 'Victoria Road', name: `Excavation Site ${n}` })), 'Victoria Road', 'Excavation Site III'],
  ];
  for (const [name, maps, street, map] of cases) {
    const m = await readMap(await loadImage(`../../tests/fixtures/${name}`), header, maps);
    if (!m || m.street !== street || m.name !== map) fails.push(`${name} map: got ${JSON.stringify(m)}, want ${street} / ${map}`);
    log(`${name} map: ${JSON.stringify(m && { street: m.street, name: m.name, matched: m.matched })}`);
  }
  const black = mat(1920, 1080, 3);
  if (await readMap(black, header, rain)) fails.push('map read on a black frame');
}
// Quick slot counts (same cases as tests/test_quickslot.py)
{
  const panel = await loadImage('../data/quickslot_panel.png', true);
  const cases = {
    game_frame: { PgUp: 12, Del: 155, End: 20 }, use_tab_tooltip: { PgUp: 8, Del: 158, End: 20 },
    etc_ant_tunnel: { PgUp: 45, Del: 84, End: 10 }, etc_excavation: { PgUp: 0, Del: 256, End: 2, PgDn: 102 },
    equip_burnt_land: { PgUp: 15, Del: 155, End: 248 },
  };
  for (const [name, want] of Object.entries(cases)) {
    const t0 = performance.now();
    const got = readQuickslot(await loadImage(`../../tests/fixtures/${name}.png`), panel, digits, null, { Del: 'Orange Potion' });
    const counts = Object.fromEntries(got.map((p) => [p.key, p.count]));
    if (JSON.stringify(counts) !== JSON.stringify(want)) fails.push(`${name} quick slots: got ${JSON.stringify(counts)}, want ${JSON.stringify(want)}`);
    if (got.find((p) => p.key === 'Del')?.name !== 'Orange Potion') fails.push(`${name}: Del not named from config`);
    log(`${name} quick slots: ${JSON.stringify(counts)} (${Math.round(performance.now() - t0)} ms)`);
  }
  if (readQuickslot(mat(1920, 1080, 3), panel, digits).length) fails.push('quick slots read on a black frame');
  // potion_series, describe, match_by_count: the Python unit tests
  const eq = (a, b, what) => { if (JSON.stringify(a) !== JSON.stringify(b)) fails.push(`${what}: got ${JSON.stringify(a)}, want ${JSON.stringify(b)}`); };
  const rows = [[0, 100], [60, 90], [120, 70]].map(([t, n]) => ({ time: t, potions: [{ key: 'Del', count: n, name: 'Red Potion' }] }));
  const [a, b, c] = potionSeries({ time: 0 }, rows, prices());
  eq([a.raw_hp, a.ema_hp], [null, null], 'series first');
  eq([b.raw_hp, b.ema_hp, b.cum_hp], [30000, 30000, 30000], 'series second');
  eq([c.raw_hp, c.cum_hp, c.ema_hp, c.raw_mp], [60000, 45000, Math.round((30000 + (1 - Math.exp(-1 / 5)) * 30000) * 10) / 10, 0], 'series third');
  const pot = (o, bl, x = null) => [{ key: 'Del', count: o, name: 'Orange Potion' }, { key: 'End', count: bl, name: 'Blue Potion' }, { key: 'PgUp', count: 9, name: x }];
  const rows2 = [{ time: 0, potions: pot(100, 50) }, { time: 60, exp: 1 }, { time: 120, potions: pot(90, 48) }, { time: 180, potions: pot(9, 47) },
    { time: 240, potions: pot(85, 47) }, { time: 960, potions: pot(200, 45, 'Pet Food') }, { time: 1020, potions: pot(195, 45) }];
  eq(potionSeries({ time: 0, pauses: [[300, 900]] }, rows2, prices({ 'Blue Potion': ['mp', 190] })).map((p) => [p.t, p.hp, p.mp]), [[0, 0, 0], [2, 1600, 380], [3, 1600, 570], [4, 2400, 570], [6, -16000, 950], [7, -15200, 950]], 'series with pause + misread + restock');
  eq(describe([{ key: 'Del', count: 155, name: 'Orange Potion' }, { key: 'PgUp', count: 12, name: null }], prices()), 'Potions: Del Orange Potion 155 · PgUp unknown item 12 (not counted)', 'describe');
  const items = { 1: { name: 'Orange Potion', qty: 155 }, 2: { name: 'Lemon', qty: 248 }, 3: { name: 'Blue Potion', qty: 20 }, 4: { name: 'Orange', qty: 20 }, 5: { name: 'Snail Shell', qty: 158 } };
  eq(matchByCount([{ key: 'Del', count: 155, name: 'Orange' }, { key: 'End', count: 246, name: 'Orange Potion' }, { key: 'Ins', count: 20, name: 'Blue Potion' }, { key: 'Hm', count: 20, name: null }], items),
    { Del: 'Orange Potion', End: 'Lemon', Ins: 'Blue Potion' }, 'match_by_count');
  const g = potionSeries({ time: 0 }, [[0, 100], [60, 103]].map(([t, n]) => ({ time: t, potions: [{ key: 'End', count: n, name: 'Lemon' }] })), prices()).at(-1);
  eq([g.mp, g.raw_mp], [-450, -27000], 'gains negative');
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
