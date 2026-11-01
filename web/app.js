// grindcap browser test: share the game window, live EXP/min, before/after mesos and items.
import { loadImage } from './lib/img.js';
import { ocrReady } from './lib/ocr.js';
import { readStatus, readMesosField } from './lib/statusbar.js';
import { StackDigits } from './lib/digits.js';
import { ItemDB } from './lib/itemdb.js';
import { locateInventory, coveredSlots, detectTab, pageTab, readPage, PageWatcher, LookCache, UNKNOWN } from './lib/inventory.js';
import { Capture, ticker } from './lib/capture.js';
import { buildSnapshot, compare, withFixes, liveSeries, isPaused, activeMs, COUNTED_TABS, SKIP_TABS } from './lib/session.js';
import { renderReview } from './review.js';
import { drawGraph } from './graph.js';
import { openPopout, updatePopout } from './popout.js';
import { crop as cropMat, toImageData } from './lib/img.js';

const $ = (id) => document.getElementById(id);
const hms = (ms) => { const s = Math.max(0, Math.floor(ms / 1000)); return `${Math.floor(s / 3600)}:${String(Math.floor(s / 60) % 60).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; };
const fmt = (v, d = 0) => (v == null || Number.isNaN(v) ? '–' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d }));
const store = {
  get: (k) => { try { return JSON.parse(localStorage.getItem('grindcap.' + k)); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem('grindcap.' + k, JSON.stringify(v)); } catch { /* full or blocked */ } },
};

const S = {
  cap: null, ctx: {}, title: null, digits: null, itemdb: new ItemDB(), cache: new LookCache(),
  busy: false, lastTick: 0, lastGrab: 0,
  live: store.get('live') || { rows: [], fails: 0 },
  pauses: store.get('pauses') || [],
  start: store.get('start'), end: store.get('end'), collect: null, result: null,
  fixes: store.get('fixes') || { looks: {}, qty: {}, status: { start: {}, end: {} } },
  corrections: store.get('corrections') || [],   // icons you named; kept across sessions, exportable
};
for (const c of S.corrections) S.cache.add(Float32Array.from(c.sig), c.id, c.name, [], { corrected: true }, c.crop);

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
  recompute();
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
function snapNote(text) { S.lastNote = text; updatePopout(); $('snapLog').textContent = `${new Date().toLocaleTimeString()}  ${text}\n` + $('snapLog').textContent; }

// ------------------------------------------------------------------ the loop

async function onTick() {
  const now = Date.now();
  renderCapture(); renderSession(); updatePopout();
  if (!S.cap || !S.cap.live || S.busy) return;
  S.busy = true;
  try {
    if (S.collect) await pageTick(now);
    else if (liveActive() && now - (S.live.rows.at(-1)?.t || 0) >= +$('every').value * 1000 && now - (S.live.lastTry || 0) >= +$('every').value * 1000) await liveRead(now);
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

// One session, like the control window: Start (scan) -> live EXP while it runs -> End (scan).
const running = () => !!(S.start && !S.end);
const liveActive = () => running() && !S.collect && !isPaused(S.pauses);

function togglePause() {
  if (!running()) return;
  const now = Date.now();
  if (isPaused(S.pauses)) { S.pauses.at(-1)[1] = now; S.live.lastTry = 0; snapNote('Resumed.'); }
  else { S.pauses.push([now, null]); snapNote("Paused: this time won't count towards the per-hour rates."); }
  store.set('pauses', S.pauses);
  render();
}
$('pauseSnap').onclick = togglePause;

// ------------------------------------------------------------------ snapshots

async function beginCollect(kind) {
  const t = Date.now();
  const frame = await S.cap.grab();
  const st = frame ? await readStatus(frame, S.ctx, S.start?.level ?? S.live.rows.at(-1)?.level ?? null) : {};
  snapNote(`${kind}: level ${st.level ?? '?'}, EXP ${fmt(st.exp)} [${st.pct ?? '?'}%]${st.checked ? '' : ' (not checked against the EXP table)'}`);
  if (kind === 'end' && isPaused(S.pauses)) { S.pauses.at(-1)[1] = t; store.set('pauses', S.pauses); }   // End ends the pause
  if (st.checked) {
    if (kind === 'start') S.live.rows = [];
    S.live.rows.push({ t, level: st.level, exp: st.exp, pct: st.pct });
  }
  S.collect = { kind, t, status: st, pages: {}, mesos: [], pictures: [], mesoPic: null, watcher: new PageWatcher(), lastNew: 0, seen: new Set(), lastWarn: 0 };
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
  const tab = pageTab(page, S.itemdb, button);
  if (!tab) { snapNote('page skipped: could not tell which tab is open'); return; }
  if (SKIP_TABS.includes(tab)) { snapNote(`${tab} page skipped (not counted)`); return; }
  (c.pages[tab] = c.pages[tab] || []).push(page);
  c.pictures.push({ tab, n: c.pages[tab].length, img: pagePicture(frame, inv.grid) });
  c.seen.add(tab);
  c.lastNew = Date.now();
  const counts = new Map(); for (const v of c.mesos) if (v != null) counts.set(v, (counts.get(v) || 0) + 1);
  if (Math.max(0, ...counts.values()) < 3) {
    const m = await readMesosField(frame, inv.grid);
    c.mesos.push(m.value);
    if (m.box && (!c.mesoPic || (m.value != null && !c.mesoPicOk))) { c.mesoPic = picture(frame, ...m.box, 'image/png'); c.mesoPicOk = m.value != null; }
  }
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
  const used = new Set(Object.values(c.pages).flat(Infinity).map((sl) => sl && sl.look).filter(Boolean));
  const looks = Object.fromEntries(S.cache.looks.filter((l) => used.has(l.key)).map((l) => [l.key, { id: l.id, name: l.name, match: l.match, crop: l.crop, sig: Array.from(l.sig, Math.round) }]));
  const snap = buildSnapshot(time, c.status, c.pages, c.mesos, { pictures: c.pictures, meso_picture: c.mesoPic, looks });
  S.collect = null;
  if (c.kind === 'start') {
    S.start = snap; S.end = null; save('start', snap); save('end', null);
    S.fixes = { looks: {}, qty: {}, status: { start: {}, end: {} } }; store.set('fixes', S.fixes);
    S.pauses = []; store.set('pauses', S.pauses); store.set('live', S.live);
    snapNote(`Start saved: mesos ${fmt(snap.mesos)}, ${Object.keys(snap.items).length} kinds of items in ${Object.keys(snap.tabs).join(', ') || 'no tabs'}. Go grind; press End when done.`);
  } else {
    S.end = snap; save('end', snap);
    store.set('live', S.live);
    snapNote('End read. Results and review below.');
  }
  recompute();
}

/** Keep a snapshot across reloads; if it's too big for browser storage, keep it without page pictures. */
function save(k, snap) {
  try { localStorage.setItem('grindcap.' + k, JSON.stringify(snap)); }
  catch { store.set(k, snap && { ...snap, pictures: [] }); }
}

const nameOf = (id) => S.itemdb.name(id);
const priceOf = (id) => S.itemdb.items[id]?.price ?? null;

/** You named a look on the review panel: remember it for every later scan (this browser), and keep
 * it in the corrections list you can export. id 'ignore' = not an item / don't count. */
function learn(key, id, how) {
  const l = { ...(S.start?.looks || {}), ...(S.end?.looks || {}) }[key];
  if (!l || !l.sig) return;
  const name = id === 'ignore' ? "(don't count)" : nameOf(id);
  S.corrections = S.corrections.filter((c) => c.key !== key);
  S.corrections.push({ key, id, name, how, was: l.name, best_guess: l.match?.bestName ?? null, t: new Date().toISOString(), crop: l.crop, sig: l.sig });
  store.set('corrections', S.corrections);
  const mine = S.cache.looks.find((x) => x.correctionOf === key);
  if (mine) Object.assign(mine, { id, name });
  else S.cache.add(Float32Array.from(l.sig), id, name, [], { corrected: true }, l.crop).correctionOf = key;
  renderCorrections();
}

function renderCorrections() {
  $('corrCount').textContent = S.corrections.length ? `${S.corrections.length} icon${S.corrections.length > 1 ? 's' : ''} you named (kept in this browser)` : '';
  $('corrDownload').disabled = !S.corrections.length;
  $('corrClear').disabled = !S.corrections.length;
}
$('corrDownload').onclick = () => {
  const out = { kind: 'grindcap-corrections', version: 1, made: new Date().toISOString(), signature: '24x24 RGB, stack-number corner blacked out, row-major', corrections: S.corrections };
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(out)], { type: 'application/json' }));
  a.download = `grindcap-corrections-${new Date().toISOString().slice(0, 10)}.json`; a.click();
};
$('corrClear').onclick = () => {
  if (!confirm('Forget every icon you named? Later scans go back to the item data alone.')) return;
  S.corrections = []; store.set('corrections', []);
  S.cache.looks = S.cache.looks.filter((l) => !(l.match && l.match.corrected));
  renderCorrections();
};

/** Apply your fixes, compare, redraw. Called after every edit on the review panel. */
function recompute() {
  store.set('fixes', S.fixes);
  S.reviewVersion = (S.reviewVersion || 0) + 1;
  const a = withFixes(S.start, 'start', S.fixes, nameOf), b = withFixes(S.end, 'end', S.fixes, nameOf);
  S.result = a && b ? compare(a, b, priceOf, S.pauses) : null;
  render();
}

function picture(frame, x, y, w, h, type = 'image/jpeg') {
  const m = cropMat(frame, x, y, w, h);
  if (!m.w || !m.h) return null;
  const cv = document.createElement('canvas');
  cv.width = m.w; cv.height = m.h;
  cv.getContext('2d').putImageData(toImageData(m), 0, 0);
  return cv.toDataURL(type, 0.85);
}

/** The inventory window as captured: tab buttons, grid and meso field. */
function pagePicture(frame, grid) {
  const [px, py] = grid.pitch(), [x0, y0] = grid.first, [x1, y1, w, h] = grid.last;
  return picture(frame, x0 - 0.4 * px, y0 - 1.0 * py, x1 + w - x0 + 1.4 * px, y1 + h - y0 + 2.4 * py);
}

function startSession(ask = confirm) {
  if (running() || S.collect) return;
  if (S.end && !ask('Start a new session? The last result is cleared from this page (Download session JSON keeps it).')) return;
  S.end = null; S.result = null; beginCollect('start');
}
$('startSnap').onclick = () => startSession();
$('popout').onclick = () => openPopout({
  state: () => S, start: startSession, end: () => beginCollect('end'), finish: finishCollect, pause: togglePause, discard,
  running, lastNote: () => S.lastNote,
}).catch((e) => note(`pop-out failed: ${e.message}`));
$('endSnap').onclick = () => beginCollect('end');
$('finishSnap').onclick = () => finishCollect();
function discard(ask = confirm) {
  if (!ask(running() ? 'Discard this session? The start snapshot and live readings are deleted.' : 'Clear the finished session from this page?')) return;
  Object.assign(S, { start: null, end: null, result: null, collect: null, pauses: [] });
  S.live = { rows: [], fails: 0 };
  store.set('pauses', []);
  S.fixes = { looks: {}, qty: {}, status: { start: {}, end: {} } };
  store.set('start', null); store.set('end', null); store.set('live', S.live); store.set('fixes', S.fixes);
  $('snapLog').textContent = '';
  render();
}
$('discardSnap').onclick = () => discard();
$('download').onclick = () => {
  const blob = new Blob([JSON.stringify({ start: S.start, end: S.end, fixes: S.fixes, result: S.result, live: S.live.rows }, null, 1)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = `grindcap-session-${new Date().toISOString().slice(0, 16).replace(':', '')}.json`; a.click();
};

// ------------------------------------------------------------------ rendering

function render() {
  const sharing = !!(S.cap && S.cap.live);
  $('share').disabled = sharing;
  $('saveFrame').disabled = !sharing;
  const run = running(), paused = isPaused(S.pauses);
  $('startSnap').disabled = !sharing || !!S.collect || run;
  $('endSnap').disabled = !sharing || !!S.collect || !run;
  $('pauseSnap').disabled = !run || !!S.collect;
  $('pauseSnap').textContent = paused ? 'Resume' : 'Pause';
  $('discardSnap').disabled = !S.start && !S.collect;
  $('discardSnap').textContent = run || S.collect ? 'Discard' : 'Clear';
  renderSession();
  $('finishSnap').disabled = !S.collect;
  $('download').disabled = !S.start;
  const c = S.collect;
  $('tabs').innerHTML = c ? `<b>${c.kind === 'start' ? 'Start' : 'End'} pages:</b> ` + COUNTED_TABS.map((t) => `<span class="${c.seen.has(t) ? 'done' : ''}">${t}${c.pages[t] ? ' ' + c.pages[t].length : ''}</span>`).join('')
    : (S.start && !S.end ? `<span class="mute">Start: mesos ${fmt(S.start.mesos)}, ${Object.keys(S.start.items).length} kinds of items.</span>` : '');
  renderCapture(); renderLive(); renderResult();
  renderReview($('review'), S, { nameOf, priceOf, recompute, learn });
  renderCorrections();
  updatePopout();
}

function renderSession() {
  const run = running(), paused = isPaused(S.pauses);
  $('sessionLine').innerHTML = S.collect ? '' : run ? `${paused ? '<b class="bad">PAUSED</b>' : '<span class="ok">Session running</span>'} ${hms(activeMs(S.start.time, Date.now(), S.pauses))} <span class="mute">(started ${S.start.when}; live EXP read every ${$('every').value} s)</span>`
    : S.end ? '<span class="mute">Session finished. Results and review below.</span>' : '<span class="mute">No session. Press Start.</span>';
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
  const rows = S.live.rows, ser = liveSeries(rows, 5, S.pauses), last = rows.at(-1), lastS = ser.at(-1);
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
  drawGraph($('graph'), ser);
}

function renderResult() {
  const r = S.result;
  if (!r) { $('result').innerHTML = ''; return; }
  const k = [
    ['Minutes', fmt(r.minutes, 1) + (r.paused_minutes > 0.05 ? ` <span class="mute">(+${fmt(r.paused_minutes, 1)} paused)</span>` : '')], ['EXP gained', fmt(r.exp)], ['EXP/hr', fmt(r.exp_per_hr)],
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
