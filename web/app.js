// grindcap browser test: share the game window, live EXP/min, before/after mesos and items.
import { loadImage } from './lib/img.js';
import { ocrReady } from './lib/ocr.js';
import { readStatus, readMesosField } from './lib/statusbar.js';
import { StackDigits } from './lib/digits.js';
import { ItemDB } from './lib/itemdb.js';
import { locateInventory, coveredSlots, detectTab, tabFromItems, readPage, PageWatcher, LookCache, UNKNOWN } from './lib/inventory.js';
import { Capture, ticker } from './lib/capture.js';
import { buildSnapshot, compare, liveSeries, COUNTED_TABS, SKIP_TABS } from './lib/session.js';

const $ = (id) => document.getElementById(id);
const fmt = (v, d = 0) => (v == null || Number.isNaN(v) ? '–' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d }));
const store = {
  get: (k) => { try { return JSON.parse(localStorage.getItem('grindcap.' + k)); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem('grindcap.' + k, JSON.stringify(v)); } catch { /* full or blocked */ } },
};

const S = {
  cap: null, ctx: {}, title: null, digits: null, itemdb: new ItemDB(), cache: new LookCache(),
  busy: false, lastTick: 0, lastGrab: 0,
  live: store.get('live') || { on: false, rows: [], fails: 0 },
  start: store.get('start'), end: null, collect: null, result: null,
};

// ------------------------------------------------------------------ setup

async function init() {
  S.ctx.expLabel = await loadImage('./data/exp_label.png');
  S.title = await loadImage('./data/inventory_title.png');
  const builtin = await (await fetch('./data/stack_digits.json')).json();
  let taught = null;
  try { const r = await fetch('./local/digits.json'); if (r.ok) taught = await r.json(); } catch { /* none */ }
  S.digits = new StackDigits(builtin, taught);
  ocrReady().catch((e) => note(`OCR failed to load: ${e.message}`));
  try {
    const r = await fetch('./local/itemdb.json');
    if (!r.ok) throw new Error('missing');
    $('data').textContent = 'Loading item icons...';
    await S.itemdb.load(await r.json(), (t) => { $('data').textContent = `Item data: ${t}`; });
    $('data').textContent = `Item data: ${S.itemdb.icons.size} icons` + (taught ? ', your taught digits loaded' : '');
  } catch {
    $('data').innerHTML = '<span class="bad">No item data: run <code>python scripts/export_web_data.py</code> (grindcap-web.bat does it). Items will show as "?".</span>';
  }
  render();
}

$('share').onclick = async () => {
  S.cap = new Capture(() => { render(); });
  try { await S.cap.start(); } catch (e) { note(`Sharing cancelled or refused: ${e.message}`); S.cap = null; return; }
  ticker(500, () => onTick().catch((e) => note(`error: ${e.message}`)));
  document.addEventListener('visibilitychange', () => S.cap && S.cap.note(document.hidden ? 'this tab went to the background' : 'this tab is in front again'));
  render();
};
$('saveFrame').onclick = () => S.cap && S.cap.saveLastFrame();

function note(text) { if (S.cap) S.cap.note(text); else $('capLog').textContent = text + '\n' + $('capLog').textContent; renderCapture(); }
function snapNote(text) { $('snapLog').textContent = `${new Date().toLocaleTimeString()}  ${text}\n` + $('snapLog').textContent; }

// ------------------------------------------------------------------ the loop

async function onTick() {
  const now = Date.now();
  renderCapture();
  if (!S.cap || !S.cap.live || S.busy) return;
  S.busy = true;
  try {
    if (S.collect) await pageTick(now);
    else if (S.live.on && now - (S.live.rows.at(-1)?.t || 0) >= +$('every').value * 1000 && now - (S.live.lastTry || 0) >= +$('every').value * 1000) await liveRead(now);
    else if (now - S.lastGrab > 1000) { await S.cap.grab(false); S.lastGrab = now; }   // keeps the capture stats honest
  } finally { S.busy = false; }
}

async function liveRead(now) {
  S.live.lastTry = now;
  const frame = await S.cap.grab();
  if (!frame) return;
  const prior = S.live.rows.at(-1)?.level ?? S.start?.level ?? null;
  const st = await readStatus(frame, S.ctx, prior);
  if (st.checked) {
    S.live.rows.push({ t: now, level: st.level, exp: st.exp, pct: st.pct });
    $('liveNote').textContent = '';
  } else {
    S.live.fails = (S.live.fails || 0) + 1;
    $('liveNote').innerHTML = `<span class="bad">Last read didn't fit the EXP table</span> (read "${(st.texts || []).join(' | ')}", level ${st.level ?? '?'}${st.why ? ', ' + st.why : ''})`;
  }
  store.set('live', S.live);
  renderLive();
}

$('liveBtn').onclick = () => {
  S.live.on = !S.live.on;
  if (S.live.on && !S.start) S.live.rows = [];
  S.live.lastTry = 0;
  store.set('live', S.live);
  render();
};

// ------------------------------------------------------------------ snapshots

async function beginCollect(kind) {
  const t = Date.now();
  const frame = await S.cap.grab();
  const st = frame ? await readStatus(frame, S.ctx, S.start?.level ?? S.live.rows.at(-1)?.level ?? null) : {};
  snapNote(`${kind}: level ${st.level ?? '?'}, EXP ${fmt(st.exp)} [${st.pct ?? '?'}%]${st.checked ? '' : ' (not checked against the EXP table)'}`);
  if (st.checked && (kind === 'start' || S.live.on)) {
    if (kind === 'start') S.live.rows = [];
    S.live.rows.push({ t, level: st.level, exp: st.exp, pct: st.pct });
  }
  S.collect = { kind, t, status: st, pages: {}, mesos: [], watcher: new PageWatcher(), lastNew: 0, seen: new Set(), lastWarn: 0 };
  render();
}

async function pageTick(now) {
  const c = S.collect;
  const frame = await S.cap.grab();
  if (!frame) return;
  const inv = locateInventory(frame, S.title, S.ctx);
  if (!inv) { if (now - c.lastWarn > 5000) { snapNote('inventory not found (is it open?)'); c.lastWarn = now; } return; }
  const sig = PageWatcher.signature(frame, inv.grid);
  if (!c.watcher.feed(sig)) return maybeFinish(now);
  if (coveredSlots(frame, inv.grid).length) {          // a tooltip is over the items: try again without it
    c.watcher.rejectLast();
    snapNote('a tooltip covers some items: move the mouse off the grid');
    return;
  }
  const button = detectTab(frame, inv.grid);
  const page = await readPage(frame, inv.grid, S.digits, S.itemdb, S.cache, `${c.kind}`);
  const tab = tabFromItems(page, S.itemdb) || button;
  if (!tab) { snapNote('page skipped: could not tell which tab is open'); return; }
  if (SKIP_TABS.includes(tab)) { snapNote(`${tab} page skipped (not counted)`); return; }
  (c.pages[tab] = c.pages[tab] || []).push(page);
  c.seen.add(tab);
  c.lastNew = Date.now();
  const counts = new Map(); for (const v of c.mesos) if (v != null) counts.set(v, (counts.get(v) || 0) + 1);
  if (Math.max(0, ...counts.values()) < 3) c.mesos.push((await readMesosField(frame, inv.grid)).value);
  const named = page.flat().filter((s) => s.id && s.id !== UNKNOWN);
  const unknown = named.filter((s) => typeof s.id !== 'number').length;
  snapNote(`${tab} page ${c.pages[tab].length}: ${named.length} items${unknown ? `, ${unknown} not recognised` : ''}; mesos read ${fmt(c.mesos.at(-1))}`);
  render();
}

function maybeFinish(now) {
  const c = S.collect;
  if (COUNTED_TABS.every((t) => c.seen.has(t)) && c.lastNew && now - c.lastNew > 4000) finishCollect();
}

function finishCollect() {
  const c = S.collect;
  if (!c) return;
  const time = c.kind === 'start' ? (c.lastNew || c.t) : c.t;   // start: when the last page was taken; end: when End was pressed
  const snap = buildSnapshot(time, c.status, c.pages, c.mesos);
  S.collect = null;
  if (c.kind === 'start') {
    S.start = snap; store.set('start', snap);
    S.live.on = true; store.set('live', S.live);
    snapNote(`Start saved: mesos ${fmt(snap.mesos)}, ${Object.keys(snap.items).length} kinds of items in ${Object.keys(snap.tabs).join(', ') || 'no tabs'}. Go grind; press End when done.`);
  } else {
    S.end = snap;
    S.live.on = false; store.set('live', S.live);
    S.result = compare(S.start, S.end, (id) => S.itemdb.items[id]?.price ?? null);
    snapNote('End read. Results below.');
  }
  render();
}

$('startSnap').onclick = () => { S.end = null; S.result = null; beginCollect('start'); };
$('endSnap').onclick = () => beginCollect('end');
$('finishSnap').onclick = () => finishCollect();
$('resetSnap').onclick = () => {
  if (!confirm('Forget the start snapshot and the live readings?')) return;
  Object.assign(S, { start: null, end: null, result: null, collect: null });
  S.live = { on: false, rows: [], fails: 0 };
  store.set('start', null); store.set('live', S.live);
  $('snapLog').textContent = '';
  render();
};
$('download').onclick = () => {
  const blob = new Blob([JSON.stringify({ start: S.start, end: S.end, result: S.result, live: S.live.rows }, null, 1)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = `grindcap-session-${new Date().toISOString().slice(0, 16).replace(':', '')}.json`; a.click();
};

// ------------------------------------------------------------------ rendering

function render() {
  const sharing = !!(S.cap && S.cap.live);
  $('share').disabled = sharing;
  $('saveFrame').disabled = !sharing;
  $('liveBtn').disabled = !sharing;
  $('liveBtn').textContent = S.live.on ? 'Stop live EXP' : 'Start live EXP';
  $('startSnap').disabled = !sharing || !!S.collect;
  $('endSnap').disabled = !sharing || !!S.collect || !S.start || !!S.end;
  $('finishSnap').disabled = !S.collect;
  $('download').disabled = !S.start;
  const c = S.collect;
  $('tabs').innerHTML = c ? `<b>${c.kind === 'start' ? 'Start' : 'End'} pages:</b> ` + COUNTED_TABS.map((t) => `<span class="${c.seen.has(t) ? 'done' : ''}">${t}${c.pages[t] ? ' ' + c.pages[t].length : ''}</span>`).join('')
    : (S.start && !S.end ? `<span class="mute">Started ${S.start.when}. Mesos ${fmt(S.start.mesos)}.</span>` : '');
  renderCapture(); renderLive(); renderResult();
}

function renderCapture() {
  const st = S.cap?.stats;
  if (!st) return;
  const ago = st.last ? ((performance.now() - st.last) / 1000).toFixed(1) : '–';
  $('capStats').innerHTML = [
    ['Status', S.cap.live ? '<span class="ok">sharing</span>' : '<span class="bad">not sharing</span>'],
    ['Frame size', st.size || '–'], ['Grab method', st.method || '–'],
    ['Frames grabbed', `${st.grabs} (${st.hiddenGrabs} while this tab was hidden)`],
    ['Longest gap', `${st.maxGap.toFixed(1)} s`], ['Last frame', `${ago} s ago`],
    ['Game scale', S.ctx.gameScale ? `${S.ctx.gameScale.toFixed(3)} screen px per game px` : '–'],
  ].map(([k, v]) => `<div><span>${k}</span>${v}</div>`).join('');
  $('capLog').textContent = st.log.join('\n');
}

function renderLive() {
  const rows = S.live.rows, ser = liveSeries(rows), last = rows.at(-1), lastS = ser.at(-1);
  $('liveStats').innerHTML = [
    ['Level / EXP', last ? `${last.level} · ${fmt(last.exp)} [${last.pct}%]` : '–'],
    ['EXP gained', fmt(lastS?.gained)],
    ['EXP/min (5-min avg)', `<span class="big">${fmt(lastS?.ema)}</span>`],
    ['EXP/min (session)', fmt(lastS?.cum)], ['EXP/hr (session)', fmt(lastS ? lastS.cum * 60 : null)],
    ['Readings', `${rows.length}${S.live.fails ? ` (${S.live.fails} failed)` : ''}`],
  ].map(([k, v]) => `<div><span>${k}</span>${v}</div>`).join('');
  $('liveTable').innerHTML = '<tr><th>Time</th><th>Level</th><th>EXP</th><th>%</th><th>EXP/min</th></tr>' + rows.slice(-8).reverse().map((r, i, arr) => {
    const s = ser.find((x) => Math.abs(x.min - (r.t - rows[0].t) / 60000) < 1e-9);
    return `<tr><td>${new Date(r.t).toLocaleTimeString()}</td><td>${r.level}</td><td>${fmt(r.exp)}</td><td>${r.pct}</td><td>${fmt(s?.rate)}</td></tr>`;
  }).join('');
  drawGraph(ser);
}

function drawGraph(ser) {
  const cv = $('graph'), g = cv.getContext('2d'), W = cv.width, H = cv.height, P = 34;
  g.clearRect(0, 0, W, H);
  const css = getComputedStyle(document.documentElement);
  const ink = css.getPropertyValue('--mute'), acc = css.getPropertyValue('--acc');
  if (ser.length < 1) { g.fillStyle = ink; g.font = '13px system-ui'; g.fillText('EXP/min appears after two readings.', P, H / 2); return; }
  const xmax = Math.max(1, ser.at(-1).min), ys = ser.flatMap((p) => [p.ema, p.cum]);
  const ymax = Math.max(...ys) * 1.15 || 1, ymin = Math.max(0, Math.min(...ys) * 0.85);
  const X = (m) => P + (W - P - 8) * m / xmax, Y = (v) => H - 18 - (H - 26) * (v - ymin) / (ymax - ymin);
  g.strokeStyle = ink; g.globalAlpha = 0.3; g.beginPath(); g.moveTo(P, H - 18); g.lineTo(W - 8, H - 18); g.stroke(); g.globalAlpha = 1;
  g.fillStyle = ink; g.font = '11px system-ui';
  g.fillText(fmt(ymax), 2, 12); g.fillText(fmt(ymin), 2, H - 20); g.fillText(`${xmax.toFixed(1)} min`, W - 60, H - 4);
  g.fillStyle = acc; g.globalAlpha = 0.45;
  for (const p of ser) { const y = Math.min(H - 18, Math.max(2, Y(p.rate))); g.beginPath(); g.arc(X(p.min), y, 2.5, 0, 7); g.fill(); }
  g.globalAlpha = 1; g.strokeStyle = acc; g.lineWidth = 2;
  g.beginPath(); ser.forEach((p, i) => (i ? g.lineTo(X(p.min), Y(p.ema)) : g.moveTo(X(p.min), Y(p.ema)))); g.stroke();
  g.setLineDash([5, 4]); g.lineWidth = 1.5; g.strokeStyle = ink;
  g.beginPath(); ser.forEach((p, i) => (i ? g.lineTo(X(p.min), Y(p.cum)) : g.moveTo(X(p.min), Y(p.cum)))); g.stroke();
  g.setLineDash([]);
}

function renderResult() {
  const r = S.result;
  if (!r) { $('result').innerHTML = ''; return; }
  const k = [
    ['Minutes', fmt(r.minutes, 1)], ['EXP gained', fmt(r.exp)], ['EXP/hr', fmt(r.exp_per_hr)],
    ['Mesos change', fmt(r.mesos)], ['Mesos/hr', fmt(r.mesos_per_hr)],
    ['Items gained (value)', fmt(r.items_gained_value)], ['Items used (value)', fmt(r.items_used_value)],
    ['Net mesos/hr incl. items', `<span class="big">${fmt(r.net_per_hr)}</span>`],
  ];
  const rows = r.items.map((i) => `<tr><td>${i.name}</td><td>${fmt(i.before)}</td><td>${fmt(i.after)}</td><td>${i.change > 0 ? '+' : ''}${fmt(i.change)}</td><td>${fmt(i.per_hr)}</td><td>${fmt(i.price)}</td><td>${fmt(i.value)}</td></tr>`).join('');
  $('result').innerHTML = `<div class="stats">${k.map(([a, b]) => `<div><span>${a}</span>${b}</div>`).join('')}</div>
    <table><tr><th>Item</th><th>Before</th><th>After</th><th>Change</th><th>/hr</th><th>Price</th><th>Value</th></tr>${rows || '<tr><td colspan="7" class="mute">No item changes</td></tr>'}</table>
    ${r.unpriced.length ? `<p class="mute">No price for: ${r.unpriced.join(', ')}</p>` : ''}
    ${r.tabs_left_out.length ? `<p class="mute">Tabs only one snapshot read (not compared): ${r.tabs_left_out.join(', ')}</p>` : ''}`;
}

init();
