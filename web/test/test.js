// Runs the JS readers on the screenshots in tests/fixtures and compares with what the Python readers
// read (expected.json). Open /web/test/test.html from a server at the repo root, or run run.mjs.
import { loadImage } from '../lib/img.js';
import { readStatus, readMesosField, readCharacter } from '../lib/statusbar.js';
import { locateInventory, detectTab, coveredSlots, readPage, LookCache, findCursor, Grid } from '../lib/inventory.js';
import { StackDigits } from '../lib/digits.js';
import { ItemDB } from '../lib/itemdb.js';
import { mat } from '../lib/img.js';
import { readMap, snapScore } from '../lib/mapname.js';
import { liveSeries, plausibleRows } from '../lib/session.js';
import { expToNext } from '../lib/gamedata.js';
import { alignPage, partStates, activeStates, partPoints, liveNet } from '../lib/liveinv.js';
import { cleanTag, ensureTag, editTags, renameIn, rangeIds } from '../lib/tags.js';
import { statsTests } from './stats_test.js';
import { readQuickslot, potionSeries, prices, describe, matchByCount, trackKeys } from '../lib/quickslot.js';

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
// Class and character name from the status bar
for (const [f, job] of [['etc_ant_tunnel.png', 'Spearman'], ['game_frame.png', 'Swordsman']]) {
  const ch = await readCharacter(await loadImage(`../../tests/fixtures/${f}`));
  log(`${f} character: ${JSON.stringify(ch && { job: ch.job, name: ch.name, raw: ch.raw })}`);
  if (!ch || ch.job !== job || ch.name !== 'ImmovableObj') fails.push(`${f} character: got ${JSON.stringify(ch)}`);
}
{ const ch = await readCharacter(await loadImage('../../tests/fixtures/etc_ant_tunnel.png'), ['ImmovableObj']);
  if (ch.name !== 'ImmovableObj') fails.push('character snap to a known name'); }
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
  eq(potionSeries({ time: 0, pauses: [[300, 900]] }, rows2, prices({ 'Blue Potion': ['mp', 190] })).map((p) => [p.t, p.hp, p.mp]), [[0, 0, 0], [2, 1600, 380], [3, 1600, 570], [4, 2400, 570], [6, 2400, 570], [7, 3200, 570]], 'series with pause + misread (restock while paused not counted)');
  eq(describe([{ key: 'Del', count: 155, name: 'Orange Potion' }, { key: 'PgUp', count: 12, name: null }], prices()), 'Potions: Del Orange Potion 155 · PgUp unknown item 12 (not counted)', 'describe');
  const items = { 1: { name: 'Orange Potion', qty: 155 }, 2: { name: 'Lemon', qty: 248 }, 3: { name: 'Blue Potion', qty: 20 }, 4: { name: 'Orange', qty: 20 }, 5: { name: 'Snail Shell', qty: 158 } };
  eq(matchByCount([{ key: 'Del', count: 155, name: 'Orange' }, { key: 'End', count: 246, name: 'Orange Potion' }, { key: 'Ins', count: 20, name: 'Blue Potion' }, { key: 'Hm', count: 20, name: null }], items),
    { Del: 'Orange Potion', End: 'Lemon', Ins: 'Blue Potion' }, 'match_by_count');
  const g = potionSeries({ time: 0 }, [[0, 100], [60, 103]].map(([t, n]) => ({ time: t, potions: [{ key: 'End', count: n, name: 'Lemon' }] })), prices()).at(-1);
  eq([g.mp, g.raw_mp], [-450, -27000], 'gains negative');
  // a potion swapped on a key mid-run: the old one's use stops, the new one's starts, no fake restock
  const sw = [[0, 'Orange Potion', 100], [60, 'Orange Potion', 90], [120, 'White Potion', 200], [180, 'White Potion', 190]]
    .map(([t, n, c]) => ({ time: t, potions: [{ key: 'Del', count: c, name: n }] }));
  const last = potionSeries({ time: 0 }, sw, prices()).at(-1);
  eq([last.hp, last.used], [10 * 160 + 10 * 320, { 'Orange Potion': 10, 'White Potion': 10 }], 'swap mid-run');
  // the icon check: the same key's look stays put across frames; another item's look is a change
  const fr = await loadImage('../../tests/fixtures/game_frame.png'), fr2 = await loadImage('../../tests/fixtures/use_tab_tooltip.png');   // same session, counts changed
  const base = Object.fromEntries(readQuickslot(fr, panel, digits).map((p) => [p.key, p.sig]));
  const same = readQuickslot(fr2, panel, digits, null, {}, {}, null, { sigs: base });
  if (same.some((p) => p.changed)) fails.push(`swap check: unchanged keys flagged ${JSON.stringify(same.filter((p) => p.changed).map((p) => p.key))}`);
  const moved = readQuickslot(fr2, panel, digits, null, {}, {}, null, { sigs: { Del: base.End, End: base.Del, PgUp: base.PgUp } });
  eq(moved.filter((p) => p.changed).map((p) => p.key).sort(), ['Del', 'End'], 'swap check: changed keys');
  // names stay put: an icon miss on one reading, or a false "changed" whose count didn't go up, keeps the name
  {
    const sg = [[1, 2, 3]], st = { qsNames: {}, qsSigs: {} };
    trackKeys(st, [{ key: 'Del', count: 150, name: 'Orange Potion', sig: sg }], null);
    const r2 = [{ key: 'Del', count: 148, name: null, sig: sg }];
    trackKeys(st, r2, [{ key: 'Del', count: 150, name: 'Orange Potion' }]);
    const r3 = [{ key: 'Del', count: 140, name: null, sig: sg, changed: true }];
    const n3 = trackKeys(st, r3, r2);
    const r4 = [{ key: 'Del', count: 300, name: null, sig: sg, changed: true }];
    const n4 = trackKeys(st, r4, r3);
    const r5 = [{ key: 'Del', count: 300, name: 'White Potion', sig: [[9, 9, 9]], changed: true }];
    const n5 = trackKeys(st, r5, r4);
    eq([r2[0].name, r3[0].name, n3.length, r4[0].name, n4[0].kind, n5[0].name, st.qsNames.Del],
      ['Orange Potion', 'Orange Potion', 0, null, 'unnamed', 'White Potion', 'White Potion'], 'quick slot names kept');
  }
}
// map names with <...> and a numeral: punctuation ignored, a lone "|" is the numeral I
{
  const maps = ['Excavation Site I', 'Excavation Site II', 'Excavation Site III', 'Excavation Site <Camp>', 'Remains <Tomb> I', 'Remains <Tomb> II',
    'Remains <Tomb> III', 'Remains <Tomb> IV', 'Remains <Cliff>'].map((name) => ({ streetName: 'Victoria Road', name }));
  const got = [['Victoria Road', 'Remains (Tomb) |'], ['Victoria Road', 'Remains <Tomb> Il'], ['Victorla Road', 'Remalns «Tomb» lV'], ['', 'Remains Tomb I'], ['Victoria Road', 'Remains <Cliff>']]
    .map(([a, b]) => snapScore(a, b, maps)?.[2]);
  const want = ['Remains <Tomb> I', 'Remains <Tomb> II', 'Remains <Tomb> IV', 'Remains <Tomb> I', 'Remains <Cliff>'];
  if (JSON.stringify(got) !== JSON.stringify(want)) fails.push(`map names with <> and numerals: got ${JSON.stringify(got)}`);
}
// Live EXP around a level-up: a reading misread one level too high (or a level-down) must not spike EXP/hr
{
  const N = expToNext(44), M = expToNext(45), m = 60000;
  const rows = [[0, 44, N - 40000], [1, 44, N - 30000], [2, 44, N - 20000], [3, 46, 5000], [4, 45, 5000], [5, 45, 15000], [6, 44, 25000], [7, 45, 25000]]
    .map(([t, level, exp]) => ({ t: t * m, level, exp }));
  const ser = liveSeries(rows);
  const maxRate = Math.max(...ser.map((p) => p.rate));
  if (maxRate > 20000) fails.push(`level-up spike: max EXP/min ${maxRate}`);
  if (Math.round(ser.at(-1).gained) !== 65000) fails.push(`level-up gained: ${ser.at(-1).gained}`);
  log(`level-up series: kept ${plausibleRows(rows).map((r) => r.t / m).join(',')}, rates ${ser.map((p) => Math.round(p.rate)).join(',')}`);
  // the newest reading alone jumps a whole level: held back until the next one
  const tail = [[0, 44, 1000], [1, 44, 11000], [2, 44, 21000], [3, 45, 21000]].map(([t, level, exp]) => ({ t: t * m, level, exp }));
  if (plausibleRows(tail).length !== 3) fails.push('tail spike not held back');
}
// A 2560x1440 screen (the game stretched to 1440p): every reader on upscaled screenshots
{
  const up = async (name) => {
    const im = new Image(); im.src = `../../tests/fixtures/${name}`; await im.decode();
    const cv = new OffscreenCanvas(2560, 1440), g = cv.getContext('2d');
    g.imageSmoothingQuality = 'high'; g.drawImage(im, 0, 0, 2560, 1440);
    const d = g.getImageData(0, 0, 2560, 1440).data, m = mat(2560, 1440, 3);
    for (let i = 0; i < 2560 * 1440; i++) { m.data[3 * i] = d[4 * i]; m.data[3 * i + 1] = d[4 * i + 1]; m.data[3 * i + 2] = d[4 * i + 2]; }
    return m;
  };
  const panel = await loadImage('../data/quickslot_panel.png', true);
  for (const name of ['etc_excavation.png', 'use_tab_tooltip.png', 'equip_burnt_land.png']) {
    const fr = await up(name), want = expected[name], ctx = { expLabel: label };
    const st = await readStatus(fr, ctx), inv = locateInventory(fr, title, ctx);
    const got = { level: st.level, exp: st.exp, pct: st.pct };
    if (inv) {
      got.mesos = (await readMesosField(fr, inv.grid)).value; got.tab = detectTab(fr, inv.grid); got.covered = coveredSlots(fr, inv.grid);
      got.nums = (await readPage(fr, inv.grid, digits, null, new LookCache())).map((row) => row.map((s) => (s.id && s.id !== '?' ? s.qty : 0)));
    }
    for (const k of ['level', 'exp', 'pct', 'mesos', 'tab', 'covered', 'nums']) if (JSON.stringify(got[k]) !== JSON.stringify(want[k])) fails.push(`1440p ${name} ${k}: got ${JSON.stringify(got[k])}, want ${JSON.stringify(want[k])}`);
    const q = readQuickslot(fr, panel, digits).map((p) => p.count).join(',');
    const ch = await readCharacter(fr);
    log(`1440p ${name}: scale ${ctx.gameScale?.toFixed(3)}, quick slots ${q}, ${ch && ch.job}/${ch && ch.name}`);
    if (!ch || ch.name !== 'ImmovableObj') fails.push(`1440p ${name} character: ${JSON.stringify(ch)}`);
  }
}
// The pointing-hand pointer, on a page picture the browser version saved (screen pixels, 1920x1080 game)
{
  const frame = await loadImage('../../tests/fixtures/cursor_page.png');
  const grid = new Grid([22, 48, 44, 44], [22 + 4 * 50.6, 48 + 5 * 47.8, 44, 44]);
  const cur = findCursor(frame, grid, cursors, 1920 / 1366);
  if (!cur || cur.name !== 'point') fails.push(`cursor_page.png: got ${JSON.stringify(cur)}, want the pointing hand`);
  log(`cursor_page.png: ${JSON.stringify(cur)}`);
}
// Session tags
{
  const eq = (a, b, what) => { if (JSON.stringify(a) !== JSON.stringify(b)) fails.push(`tags ${what}: got ${JSON.stringify(a)}, want ${JSON.stringify(b)}`); };
  eq(cleanTag('  bought   pots '), 'bought pots', 'clean');
  eq(ensureTag(['Party'], 'party'), [['Party'], 'Party'], 'same tag ignoring case');
  eq(ensureTag(['Party'], 'solo'), [['Party', 'solo'], 'solo'], 'new tag');
  eq(ensureTag(['Party'], '  '), [['Party'], null], 'blank');
  eq(editTags(['b'], { add: ['A', 'a', 'c'] }, ['a', 'b']), ['A', 'b', 'c'], 'add, list order');
  eq(editTags(['a', 'b'], { remove: ['B'] }), ['a'], 'remove');
  eq(renameIn(['x', 'y'], 'X', 'y'), ['y'], 'rename merges');
  eq(rangeIds(['1', '2', '3', '4'], '3', '1'), ['1', '2', '3'], 'range upward');
  eq(rangeIds(['1', '2'], '1', '9'), [], 'range off the list');
}
// Live mesos/hr from inventory reads while grinding: per part, change since its previous point / active time
{
  const eq = (a, b, what) => { if (JSON.stringify(a) !== JSON.stringify(b)) fails.push(`liveinv ${what}: got ${JSON.stringify(a)}, want ${JSON.stringify(b)}`); };
  const S = (id, qty, name = `item ${id}`) => ({ id, qty, name }), E = {};
  const row = (...x) => [...x, ...Array(5 - x.length).fill(E)];
  // Etc tab: 8 rows at Start; a later page shows rows 2..7 with grown stacks and a new item in an empty slot
  const etc = [row(S(1, 10), S(2, 5)), row(S(3, 1)), row(S(4, 7), S(5, 2)), row(S(6, 3)), row(S(7, 9)), row(S(8, 1)), row(S(9, 4)), row()];
  const page = etc.slice(2).map((r) => r.map((s) => ({ ...s })));
  page[0][0] = S(4, 17); page[5][0] = S(10, 2);           // +10 of item 4, 2 of a new item 10 in the empty row
  eq(alignPage(etc, page), 2, 'scrolled page offset');
  eq(alignPage([row(S(1, 1), S(2, 1))], [row(S(3, 1), S(4, 1))]), null, 'items moved: no offset');
  eq(alignPage([row()], [row(S(3, 1))]), 0, 'empty tab at Start');
  const ore = [row(S(5, 100), S(5, 100)), row(S(5, 100), S(5, 100)), row(S(5, 37), S(5, 12))];
  eq(alignPage(ore, [row(S(5, 100), S(5, 100)), row(S(5, 37), S(5, 12))]), 1, 'identical stacks: counts break the tie');
  const t0 = 1000000, min = 60000;
  const start = { time: t0, mesos: 1000, tabs: { Etc: etc, Use: [row(S(20, 100, 'Red Potion'), S(21, 0, 'Scroll'))] } };
  const price = (id) => ({ 4: 10, 10: 100, 20: 50, 21: 700 }[id] ?? null);
  // 10 s after Start (inventory still open after the scan), 30 min, 60 min; Use read at 30 min only
  const reads = [
    { t: t0 + 10000, tab: 'Etc', rows: etc.slice(2), mesos: 1050 },
    { t: t0 + 30 * min, tab: 'Etc', rows: page, mesos: 11000 },                       // +300 items, +10,000 mesos
    { t: t0 + 30 * min + 5000, tab: 'Use', rows: [row(S(20, 80, 'Red Potion'), S(21, 1, 'Scroll'))], mesos: 11000 },
    { t: t0 + 60 * min, tab: 'Etc', rows: page, mesos: 41000 },                       // +30,000 mesos, no items
  ];
  const { states } = partStates(start, reads, price, ['Equip', 'Use', 'Setup', 'Etc']);
  const parts = Object.fromEntries(Object.entries(states).map(([k, st]) => [k, activeStates(st, t0, [])]));
  const e = liveNet(parts, 60);
  const by = Object.fromEntries(e.parts.map((p) => [p.name, p]));
  const use = -300 * 60 / (30 + 5 / 60);
  eq(by.Mesos.points.map((p) => Math.round(p.rate)), [20000, 60000], 'mesos: each point = change since the previous / time (the 10 s read is not a point)');
  eq(by.Etc.points.map((p) => Math.round(p.rate)), [600, 0], 'Etc points');
  eq(Math.round(by.Use.latest), Math.round(use), 'Use: -20 potions + scroll over 30 min');
  eq([e.net_latest, e.waiting], [Math.round(60000 + use), []], 'net = every part at its newest rate');
  eq(e.total.map((p) => p.est), [20600, Math.round(20600 + use), Math.round(60000 + use)], 'net after each point');
  // a pause in between: selling Etc + repotting while paused must not count
  const pauses = [[t0 + 20 * min, t0 + 25 * min]];
  const r2 = [{ t: t0 + 10 * min, tab: 'Etc', rows: etc.slice(2), mesos: 5000 },
    { t: t0 + 26 * min, tab: 'Etc', rows: [row(), row(), row(), row(), row(), row()], mesos: 905000 },  // sold everything: +900k
    { t: t0 + 36 * min, tab: 'Etc', rows: [row(S(4, 3)), row(), row(), row(), row(), row()], mesos: 915000 }];
  const st2 = partStates(start, r2, price, ['Etc']).states;
  const e2 = liveNet(Object.fromEntries(Object.entries(st2).map(([k, st]) => [k, activeStates(st, t0, pauses)])), 31);
  const b2 = Object.fromEntries(e2.parts.map((p) => [p.name, p]));
  eq(b2.Mesos.points.map((p) => [p.min, Math.round(p.rate)]), [[10, 24000], [31, 60000]], 'pause: the sale is not income');
  eq(b2.Etc.points.map((p) => Math.round(p.rate)), [0, 180], 'pause: the sold items are not a loss');
  // quick slot potions as their own part, left out of the Use tab
  const st3 = partStates(start, reads, price, ['Use'], null, { skipNames: ['Red Potion'] }).states;
  eq(st3.Use.map((s) => s.value), [0, 700], 'Use without the quick slot potions');
  // repotting while paused: the quick slot count going up then is not counted as income
  const ps = potionSeries({ time: 0, pauses: [[600, 900]] }, [0, 300, 600, 1000, 1300].map((time, i) => ({ time, potions: [{ key: 'Del', name: 'Red Potion', count: [100, 90, 80, 300, 290][i] }] })), { 'Red Potion': ['hp', 50] });
  eq(ps.map((p) => p.hp), [0, 500, 1000, 1000, 1500], 'potions: repot while paused');
  eq(partPoints([{ min: 0, value: 0 }, { min: 2, value: -100 }, { min: 4, value: -400 }]).map((p) => p.rate), [-6000], 'points need 3+ active min');
  // moving average over the last n points: gains added up / minutes added up (uneven intervals)
  const sm = partPoints([{ min: 0, value: 0 }, { min: 10, value: 1000 }, { min: 15, value: 2000 }, { min: 45, value: 2000 }], 3, 2);
  eq(sm.map((p) => Math.round(p.rate)), [6000, 12000, 0], 'raw rates');
  eq(sm.map((p) => Math.round(p.avg)), [6000, 8000, 1714], 'moving average over 2 reads');
  eq(liveNet({ A: [{ min: 0, value: 0 }, { min: 10, value: 1000 }, { min: 15, value: 2000 }] }, 15, 3, 2).net_latest, 8000, 'net uses the average');
  // a look you named on the review applies to live reads too
  const lk = { time: t0, mesos: 0, tabs: { Etc: [row({ ...S(1, 10), look: 'L1' })] } };
  const lp = [row({ ...S(1, 10), look: 'L1' }, { id: 'look-9', qty: 30, name: '?', look: 'L9' })];
  eq(partStates(lk, [{ t: t0 + 60 * min, tab: 'Etc', rows: lp, mesos: 0 }], (id) => (+id === 7 ? 1 : null), ['Etc'], { looks: { L9: 7 } }).states.Etc.map((s) => s.value), [0, 30], 'fixes on live reads');
}
// Stat window
await statsTests(log, fails);
log(fails.length ? `FAIL\n${fails.join('\n')}` : 'ALL OK');
window.__result = { results, fails };
