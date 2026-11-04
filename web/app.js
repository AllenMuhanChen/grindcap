// grindcap browser test. One session at a time, like the control window: Start (status + inventory
// pages) -> live EXP while it runs -> End (status + pages) -> results. Finished sessions are kept in
// IndexedDB and can be paged through below; the review is the main part of the page.
import { loadImage, crop as cropMat, toImageData } from './lib/img.js';
import { ocrReady } from './lib/ocr.js';
import { readStatus, readMesosField, readCharacter, JOBS } from './lib/statusbar.js';
import { StackDigits } from './lib/digits.js';
import { ItemDB } from './lib/itemdb.js';
import { locateInventory, coveredSlots, findCursor, detectTab, pageTab, readPage, PageWatcher, LookCache, UNKNOWN } from './lib/inventory.js';
import { Capture, ticker } from './lib/capture.js';
import { buildSnapshot, compare, withFixes, liveSeries, isPaused, activeMs, COUNTED_TABS, SKIP_TABS } from './lib/session.js';
import * as store from './lib/store.js';
import { readMap } from './lib/mapname.js';
import { readQuickslot, matchByCount, describe, potionSeries, prices, trackKeys } from './lib/quickslot.js';
import { renderReview } from './review.js';
import { drawGraph, drawPotionGraph, potionSummary } from './graph.js';
import { openPopout, updatePopout, popoutOpen } from './popout.js';

const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt = (v, d = 0) => (v == null || Number.isNaN(v) ? '–' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d }));
const pctTxt = (v) => (v == null ? '' : ` <span class="mute">(${v.toFixed(1)}%/hr)</span>`);
const hms = (ms) => { const s = Math.max(0, Math.floor(ms / 1000)); return `${Math.floor(s / 3600)}:${String(Math.floor(s / 60) % 60).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; };
const noFixes = () => ({ looks: {}, qty: {}, status: { start: {}, end: {} } });
const blank = () => ({ id: null, name: null, start: null, end: null, live: { rows: [], fails: 0 }, pauses: [], fixes: noFixes(), result: null, potions: [], qsNames: {}, qsSigs: {}, lastPot: undefined, character: null });

await store.openStore();

// S.cur = the session being run (once it has ended it is also the saved record with the same id).
// S.view = the session shown below (S.cur, or a saved one loaded from IndexedDB).
const S = {
  cap: null, ctx: {}, title: null, digits: null, itemdb: new ItemDB(), cache: new LookCache(),
  busy: false, lastGrab: 0, collect: null, ver: 0, qsCache: {}, qsCtx: {},
  cur: {
    id: store.get('start')?.time ?? null, name: store.get('name'), start: store.get('start'), end: store.get('end'),
    live: store.get('live') || { rows: [], fails: 0 }, pauses: store.get('pauses') || [], fixes: store.get('fixes') || noFixes(), result: null,
    potions: store.get('potions') || [], qsNames: store.get('qsNames') || {}, qsSigs: store.get('qsSigs') || {}, lastPot: undefined, character: store.get('character'),
  },
  view: null,
  corrections: store.get('corrections') || [],   // icons you named; kept across sessions, exportable
  chars: store.get('characters') || [],          // characters seen: [{name, job}]
  char: store.get('char'),                       // the character you're playing now {name, job}
};
S.view = S.cur;
for (const c of S.corrections) S.cache.add(Float32Array.from(c.sig), c.id, c.name, [], { corrected: true }, c.crop);
const C = () => S.cur;

function resetCur() {
  S.cur = blank();
  for (const k of ['start', 'end', 'name']) store.set(k, null);
  store.set('live', S.cur.live); store.set('pauses', []); store.set('fixes', S.cur.fixes);
  store.set('potions', []); store.set('qsNames', {}); store.set('qsSigs', {}); store.set('character', null);
  S.view = S.cur;
}

// ------------------------------------------------------------------ setup

async function init() {
  S.ctx.expLabel = await loadImage('./data/exp_label.png');
  S.title = await loadImage('./data/inventory_title.png');
  S.cursors = await (await fetch('./data/cursors.json')).json();
  S.mapHeader = await loadImage('./data/minimap_header.png');
  S.qsPanel = await loadImage('./data/quickslot_panel.png', true);
  let qs = {};
  try { const r = await fetch('./local/quickslot.json'); if (r.ok) qs = await r.json(); } catch { /* defaults */ }
  S.qs = { enabled: qs.enabled ?? true, slots: qs.slots || {}, prices: qs.prices || {} };
  S.qsTable = prices(S.qs.prices);
  S.trackPotions = store.get('trackPotions') ?? S.qs.enabled;
  $('trackPot').checked = S.trackPotions;
  try { const r = await fetch('./local/maps.json'); S.maps = r.ok ? await r.json() : []; } catch { S.maps = []; }
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
  if (store.listSessions().some((x) => !('level' in x) || (x.result && !('pct_per_hr' in x.result)))) {   // saved before these columns
    for (const r of await store.allSessions()) {
      if (r.start && r.end && !(r.result && 'pct_per_hr' in r.result)) {
        r.fixes = r.fixes || noFixes();
        r.result = compare(withFixes(r.start, 'start', r.fixes, nameOf), withFixes(r.end, 'end', r.fixes, nameOf), priceOf, r.pauses || []);
        r.meta = meta(r);
        await store.putSession(r);
      }
    }
    await store.reindex();
  }
  showTab(tab);
  recompute(C());
  // an ended session from the older single-session version goes into the list
  if (C().end && !store.listSessions().some((x) => x.id === C().id)) await archive();
  renderStorage();
}

const popoutApi = {
  state: () => ({ ...S, ...C() }), start: startSession, end: endSession, finish: finishCollect, pause: togglePause, discard,
  running: () => running(), lastNote: () => S.lastNote, alert: () => alertNow(),
  potions: () => ({ pts: potPoints(C()), line: running() && S.trackPotions && C().lastPot !== undefined ? describe(C().lastPot, S.qsTable) : '' }),
};
const showPopout = () => openPopout(popoutApi).then(render).catch((e) => note(`pop-out: ${e.message}`));

$('share').onclick = async () => {
  S.cap = new Capture(() => { render(); });
  try { await S.cap.start(); } catch (e) { note(`Sharing cancelled or refused: ${e.message}`); S.cap = null; return; }
  ticker(500, () => onTick().catch((e) => note(`error: ${e.message}`)));
  document.addEventListener('visibilitychange', () => S.cap && S.cap.note(document.hidden ? 'this tab went to the background' : 'this tab is in front again'));
  showPopout();   // Chrome opens it only right after a click; if the share dialog took too long, Start opens it
  render();
};
$('saveFrame').onclick = () => S.cap && S.cap.saveLastFrame();
$('popout').onclick = showPopout;

function note(text) { if (S.cap) S.cap.note(text); else $('capLog').textContent = text + '\n' + $('capLog').textContent; renderCapture(); }
/** Something you need to do (move the mouse, open the inventory or minimap): a big banner in the top bar
 * and the pop-out, until a page is taken or the condition has not come back for a few seconds. */
function warn(text) { S.alert = { text, t: Date.now() }; snapNote(text); }
const alertNow = () => {
  const a = S.alert, c = S.collect;
  if (a && Date.now() - a.t < 6000) return a.text;
  return c && !c.map && c.mapWarn ? c.mapWarn : '';
};
function snapNote(text) { S.lastNote = text; $('lastNote').textContent = text; $('snapLog').textContent = `${new Date().toLocaleTimeString()}  ${text}\n` + $('snapLog').textContent; updatePopout(); }

// ------------------------------------------------------------------ the loop

async function onTick() {
  const now = Date.now();
  renderCapture(); renderSession(); updatePopout();
  if (!S.cap || !S.cap.live || S.busy) return;
  S.busy = true;
  try {
    const every = Math.max(60, +$('every').value) * 1000, live = C().live;   // at least a minute: shorter gaps are mostly noise
    if (S.collect) await pageTick(now).catch((e) => warn(`Page read failed: ${e.message}`));
    else if (liveActive() && now - (live.rows.at(-1)?.t || 0) >= every && now - (live.lastTry || 0) >= every) await liveRead(now);
    else if (now - S.lastGrab > 1000) { await S.cap.grab(false); S.lastGrab = now; }   // keeps the capture stats honest
  } finally { S.busy = false; }
}

async function liveRead(now) {
  const live = C().live;
  live.lastTry = now;
  const frame = await S.cap.grab();
  if (!frame) return;
  const st = await readStatus(frame, S.ctx, live.rows.at(-1)?.level ?? C().start?.level ?? null);
  if (st.checked) {
    live.rows.push({ t: now, level: st.level, exp: st.exp, pct: st.pct });
    live.why = '';
  } else {
    live.fails = (live.fails || 0) + 1;
    live.why = `Last read didn't fit the EXP table (read "${(st.texts || []).join(' | ')}", level ${st.level ?? '?'}${st.why ? ', ' + st.why : ''})`;
  }
  store.set('live', live);
  if (S.trackPotions) {                 // the quick slots on the same frame; a missed reading is skipped
    const p = readPotions(frame, C().qsNames, C());
    C().lastPot = p;
    if (p) { C().potions.push({ time: now / 1000, potions: p }); store.set('potions', C().potions); }
  }
  renderTop();
  if (S.view === C()) renderGraph();
}

/** What's on the quick slots ([{key, count, name}]); null if the panel wasn't found or reading failed.
 * Names: config slots, then the session's (from the start inventory), then the icon among Use items. */
function readPotions(frame, names = {}, cur = null) {
  try {
    S.qsCtx.sigs = cur?.qsSigs || {};
    S.itemdb.extraPrices = S.qs.prices;
    const out = readQuickslot(frame, S.qsPanel, S.digits, S.itemdb, { ...names, ...S.qs.slots }, S.qsCache, store.get('useIds') || null, S.qsCtx);
    if (cur) keepTrack(cur, out);
    for (const p of out) { delete p.sig; delete p.changed; }
    return out.length ? out : null;
  } catch (e) { console.warn('quick slot read failed', e); return null; }
}

/** A key's icon changed: you swapped potions. Each reading keeps the name it was read with, and the
 * series is per item, so the old potion's use stops there and the new one's starts (quickslot.trackKeys). */
function keepTrack(cur, out) {
  const prev = cur.lastPot ?? cur.potions?.at(-1)?.potions ?? null;
  for (const n of trackKeys(cur, out, prev)) {
    if (n.kind === 'now') snapNote(`Quick slot ${n.key}: now ${n.name}${n.was ? ` (was ${n.was})` : ''}`);
    else warn(`Quick slot ${n.key}: the item changed and couldn't be named; not counted until it is.`);
  }
  if (cur === C()) { store.set('qsNames', cur.qsNames); store.set('qsSigs', cur.qsSigs); }
}
$('trackPot').onchange = (e) => { S.trackPotions = e.target.checked; store.set('trackPotions', S.trackPotions); render(); };

const running = () => !!(C().start && !C().end);
const liveActive = () => running() && !S.collect && !isPaused(C().pauses);

function togglePause() {
  if (!running() || S.collect) return;
  const now = Date.now(), p = C().pauses;
  if (isPaused(p)) { p.at(-1)[1] = now; C().live.lastTry = 0; snapNote('Resumed.'); }
  else { p.push([now, null]); snapNote("Paused: this time won't count towards the per-hour rates."); }
  store.set('pauses', p);
  render();
}
$('pauseSnap').onclick = togglePause;

// ------------------------------------------------------------------ start / end

function startSession() {
  if (running() || S.collect || !S.cap?.live) return;
  if (!popoutOpen()) showPopout();
  resetCur();
  $('snapLog').textContent = '';
  beginCollect('start');
}
function endSession() {
  if (!running() || S.collect) return;
  if (!popoutOpen()) showPopout();
  S.view = S.cur;
  beginCollect('end');
}
$('startSnap').onclick = startSession;
$('endSnap').onclick = endSession;
$('finishSnap').onclick = () => finishCollect();

function discard(ask = confirm) {
  if (!running() && !S.collect) return;
  if (!ask('Discard this session? Its start snapshot and live readings are deleted.')) return;
  S.collect = null;
  resetCur();
  snapNote('Session discarded.');
  recompute(S.cur);
}
$('discardSnap').onclick = () => discard();

async function beginCollect(kind) {
  const t = Date.now(), cur = C();
  const c = S.collect = { kind, t, status: {}, pages: {}, mesos: [], pictures: [], mesoPics: [], expPic: null, watcher: new PageWatcher(), lastNew: 0, seen: new Set(), lastWarn: 0, reading: true };
  if (kind === 'end' && cur.start?.map) c.map = cur.start.map;      // same map as at Start: not read again
  render();
  try {
    if (kind === 'end' && isPaused(cur.pauses)) { cur.pauses.at(-1)[1] = t; store.set('pauses', cur.pauses); }   // End ends the pause
    const frame = await S.cap.grab();
    if (!frame) snapNote(`${kind}: no frame from the shared window yet; the status bar is read again during the scan`);
    else {
      await statusRead(frame, c, t);
      if (kind === 'start' && S.trackPotions) { const tmp = { qsNames: {}, qsSigs: {} }; c.potions = readPotions(frame, {}, tmp); c.potionSigs = tmp.qsSigs; }
      if (kind === 'start') await readChar(frame, c);
    }
  } catch (e) {
    warn(`Reading the status bar failed (${e.message}); the inventory scan goes on.`);
  } finally {
    c.reading = false;                   // never leave the scan waiting, whatever failed above
  }
  render();
}

/** Level + EXP for a Start/End scan, with the EXP text's picture. Not read (or not fitting the EXP table):
 * tried again on the scan's frames every few seconds (pageTick), so one bad frame can't lose it. */
async function statusRead(frame, c, t, retry = false) {
  const cur = C();
  c.lastStatusTry = Date.now(); c.statusTries = (c.statusTries || 0) + 1;
  let st;
  try { st = await readStatus(frame, S.ctx, cur.start?.level ?? cur.live.rows.at(-1)?.level ?? null); } catch (e) { st = { why: e.message }; }
  if (S.collect !== c) return;
  // keep the best reading: a checked one wins over an unchecked one
  if (!retry || st.checked || (!c.status.checked && st.exp != null && c.status.exp == null)) {
    c.status = st;
    if (st.expBox) {                     // the EXP text as captured (with the "EXP." label), for the review
      const [x, y, w, h] = st.expBox, lab = Math.round(40 * (S.ctx.gameScale || 1.4));
      c.expPic = picture(frame, x - lab, y, w + lab, h, 'image/png');
    } else if (!c.expPic) {              // label not found: the bottom of the window, so you can see why
      c.expPic = picture(frame, 0, Math.floor(frame.h * 0.9), Math.floor(frame.w * 0.6), Math.ceil(frame.h * 0.1), 'image/jpeg');
    }
  }
  if (st.checked) {
    if (c.kind === 'start') cur.live.rows = [];
    cur.live.rows = cur.live.rows.filter((r) => r.t < c.t);   // a retry replaces this scan's row
    cur.live.rows.push({ t: retry ? Date.now() : t, level: st.level, exp: st.exp, pct: st.pct });
    c.statusLate = retry;
    snapNote(`${c.kind}: level ${st.level}, EXP ${fmt(st.exp)} [${st.pct}%]${retry ? ' (read on a later frame of the scan)' : ''}`);
  } else if (!retry || c.statusTries === 2) {
    const why = st.why || (st.texts?.length ? `read "${st.texts.join(' | ')}"` : 'nothing read');
    warn(`${c.kind}: EXP not read from the status bar (${why}). Keep the status bar visible; it is tried again while you scan.`);
  }
}

/** Class and name from the status bar at Start. A name close to one seen before is taken as that one;
 * nothing read keeps the character you had. */
async function readChar(frame, c) {
  let ch = null;
  try { ch = await readCharacter(frame, S.chars.map((x) => x.name)); } catch (e) { note(`character read failed: ${e.message}`); }
  if (ch && ch.name) {
    c.character = { name: ch.name, job: ch.job || (S.char?.name === ch.name ? S.char.job : null), read: ch.raw, picture: picture(frame, ...ch.box, 'image/png') };
    setChar({ name: c.character.name, job: c.character.job });
    snapNote(`Character: ${ch.name}${ch.job ? ` (${ch.job})` : ''}`);
  } else snapNote(`Character not read from the status bar${S.char ? `; using ${S.char.name}` : ': type it in'}`);
}
function setChar(ch, replacing = null) {
  S.char = ch.name ? ch : null; store.set('char', S.char);
  if (!ch.name) return;
  S.chars = S.chars.filter((x) => x.name !== ch.name && (replacing == null || x.name !== replacing));
  S.chars.unshift({ name: ch.name, job: ch.job || null });
  store.set('characters', S.chars);
}
$('charJob').innerHTML = $('sessJob').innerHTML = '<option value="">class?</option>' + JOBS.map((j) => `<option>${j}</option>`).join('');
$('charName').onchange = $('charJob').onchange = () => {
  const old = S.char?.name, ch = { name: $('charName').value.trim(), job: $('charJob').value || null };
  setChar(ch, old);
  if (running() && ch.name) { C().character = { ...(C().character || {}), ...ch }; store.set('character', C().character); }
  render();
};
$('sessChar').onchange = $('sessJob').onchange = () => {
  const v = S.view, ch = { name: $('sessChar').value.trim(), job: $('sessJob').value || null };
  if (!v.start) return;
  const old = v.character?.name;
  v.character = ch.name ? { ...(v.character || {}), ...ch } : null;
  if (ch.name) setChar(ch, old);
  if (v === S.cur) store.set('character', v.character);
  recompute(v);
};

/** The map name from the minimap; asks for the minimap when it isn't on screen. */
async function tryMap(frame, now) {
  const c = S.collect;
  if (!c || c.map || now - (c.lastMapTry || 0) < 10000) return;
  c.lastMapTry = now;
  let m = null;
  try { m = await readMap(frame, S.mapHeader, S.maps); } catch (e) { note(`map read failed: ${e.message}`); }
  if (S.collect !== c) return;
  if (m && m.name) {
    c.map = { street: m.street, name: m.name, matched: m.matched, raw: m.raw };
    c.mapPic = picture(frame, ...m.box, 'image/png');
    c.mapWarn = '';
    snapNote(`Map: ${m.name}${m.matched ? '' : ' (not found in the map list: check it in the review)'}`);
  } else {
    c.mapWarn = 'Map name not visible: open the minimap (M) and leave it expanded so its title shows the map name.';
    if (!c.mapWarned) { warn(c.mapWarn); c.mapWarned = true; }
  }
  render();
}

async function pageTick(now) {
  const c = S.collect;
  if (c.reading) return;
  const frame = await S.cap.grab();
  if (!frame) return;
  if (!c.status.checked && (c.statusTries || 0) < 30 && now - (c.lastStatusTry || 0) > 2500) await statusRead(frame, c, c.t, true);
  if (S.collect !== c) return;
  if (!c.map && c.lastNew) await tryMap(frame, now);   // after the first page, so the map never holds up the scan
  const inv = locateInventory(frame, S.title, S.ctx);
  if (!inv) { if (now - c.lastWarn > 3000) { warn('Inventory not found: open it (I) and keep it fully on screen.'); c.lastWarn = now; } return; }
  const sig = PageWatcher.signature(frame, inv.grid);
  if (!c.watcher.feed(sig)) return maybeFinish(now);
  if (coveredSlots(frame, inv.grid).length) {          // a tooltip is over the items: try again without it
    c.watcher.rejectLast();
    warn('A tooltip covers the items: move the mouse off the inventory grid.');
    return;
  }
  const pointer = findCursor(frame, inv.grid, S.cursors, S.ctx.gameScale);
  if (pointer) {                                       // the mouse pointer hides part of a slot
    c.watcher.rejectLast();
    warn('The mouse pointer is over the items: move it off the inventory grid (page not taken).');
    return;
  }
  const button = detectTab(frame, inv.grid);
  const page = await readPage(frame, inv.grid, S.digits, S.itemdb, S.cache, `${c.kind}`);
  if (S.collect !== c) return;                           // discarded meanwhile
  const tab = pageTab(page, S.itemdb, button);
  if (!tab) { warn('Page skipped: could not tell which tab is open. Click the tab again.'); return; }
  if (SKIP_TABS.includes(tab)) { snapNote(`${tab} page skipped (not counted)`); return; }
  (c.pages[tab] = c.pages[tab] || []).push(page);
  S.alert = null;
  c.pictures.push({ tab, n: c.pages[tab].length, img: pagePicture(frame, inv.grid) });
  c.seen.add(tab);
  c.lastNew = Date.now();
  // the meso field on every page, each with its picture: the total can change during a scan (pet loot)
  const m = await readMesosField(frame, inv.grid);
  c.mesos.push(m.value);
  if (m.box) {
    const last = c.mesoPics.at(-1);
    if (last && last.value === m.value) last.pages.push(`${tab} ${c.pages[tab].length}`);
    else c.mesoPics.push({ value: m.value, raw: m.raw, pages: [`${tab} ${c.pages[tab].length}`], img: picture(frame, ...m.box, 'image/png') });
  }
  const named = page.flat().filter((s) => s.id && s.id !== UNKNOWN);
  const unknown = named.filter((s) => typeof s.id !== 'number').length;
  snapNote(`${tab} page ${c.pages[tab].length}: ${named.length} items${unknown ? `, ${unknown} not recognised` : ''}; mesos read ${fmt(c.mesos.at(-1))}`);
  render();
}

function maybeFinish(now) {
  const c = S.collect;
  if (COUNTED_TABS.every((t) => c.seen.has(t)) && c.lastNew && now - c.lastNew > 4000 && (c.status.checked || (c.statusTries || 0) >= 3)) finishCollect();
}

async function finishCollect() {
  const c = S.collect, cur = C();
  if (!c || c.reading) return;
  const time = c.kind === 'start' ? (c.lastNew || c.t) : c.t;   // start: when the last page was taken; end: when End was pressed
  const used = new Set(Object.values(c.pages).flat(Infinity).map((sl) => sl && sl.look).filter(Boolean));
  const looks = Object.fromEntries(S.cache.looks.filter((l) => used.has(l.key)).map((l) => [l.key, { id: l.id, name: l.name, match: l.match, crop: l.crop, sig: Array.from(l.sig, Math.round) }]));
  const snap = buildSnapshot(time, c.status, c.pages, c.mesos,
    { pictures: c.pictures, map: c.map || null, map_picture: c.mapPic || null, meso_pictures: c.mesoPics, meso_picture: c.mesoPics.find((p) => p.value != null)?.img || c.mesoPics[0]?.img || null, exp_picture: c.expPic, looks },
    c.kind === 'end' ? 'first' : 'last');
  S.collect = null;
  if (!c.status.checked) warn(`${c.kind}: EXP was never read from the status bar. Type it in on the review below (the picture shows what was captured).`);
  if (c.kind === 'start') {
    cur.start = snap; cur.id = snap.time; store.set('start', snap);
    cur.pauses = []; store.set('pauses', cur.pauses); store.set('live', cur.live);
    // quick slot number = that item's inventory total: names each key for the session
    const useIds = new Set(store.get('useIds') || []);
    for (const id of Object.keys(snap.items)) if (!isNaN(+id) && S.itemdb.items[id]?.category === 'Use') useIds.add(+id);
    store.set('useIds', [...useIds]);
    // the inventory count names a key; the icon guess fills keys it couldn't (kept for the whole session)
    cur.qsNames = c.potions ? { ...Object.fromEntries(c.potions.filter((p) => p.name).map((p) => [p.key, p.name])), ...matchByCount(c.potions, snap.items, S.itemdb) } : {};
    cur.qsSigs = c.potionSigs || {}; store.set('qsSigs', cur.qsSigs);
    cur.potions = c.potions ? [{ time: snap.time / 1000, potions: c.potions.map((p) => ({ ...p, name: cur.qsNames[p.key] ?? p.name })) }] : [];
    cur.lastPot = cur.potions[0]?.potions;
    cur.character = c.character ? { name: c.character.name, job: c.character.job } : S.char ? { ...S.char } : null;
    snap.character = c.character || null;
    store.set('character', cur.character); store.set('start', snap);
    store.set('qsNames', cur.qsNames); store.set('potions', cur.potions);
    snapNote(`Start saved: mesos ${fmt(snap.mesos)}, ${Object.keys(snap.items).length} kinds of items in ${Object.keys(snap.tabs).join(', ') || 'no tabs'}. Go grind; press End when done.`);
    recompute(cur);
  } else {
    cur.end = snap; store.set('end', snap); store.set('live', cur.live);
    recompute(cur);
    await archive();
    snapNote(`Session saved as "${cur.name}". Results and review below.`);
    render();
  }
}

/** Map and level as fixed on the review (for the summary list). */
function meta(v) {
  const a = withFixes(v.start, 'start', v.fixes, nameOf), b = withFixes(v.end, 'end', v.fixes, nameOf);
  return { map: a?.map?.name || b?.map?.name || null, level: a?.level ?? null, level_end: b?.level ?? null };
}
const record = (v) => ({ meta: v.start ? meta(v) : null, id: v.id, name: v.name, start: v.start, end: v.end, fixes: v.fixes, live: { rows: v.live.rows, fails: v.live.fails || 0 }, pauses: v.pauses, result: v.result, potions: v.potions || [], qsNames: v.qsNames || {}, character: v.character || null, saved: v.saved || Date.now() });
const isSaved = (v) => v.end && v.id != null && store.listSessions().some((x) => x.id === v.id);

/** Put the ended current session in the saved list. */
async function archive() {
  const cur = C();
  if (!cur.end || !cur.start) return;
  if (!cur.name) { cur.name = defaultName(cur); store.set('name', cur.name); }
  await store.putSession(record(cur)).catch((e) => snapNote(`Could not save the session: ${e.message}`));
  renderStorage();
}
function defaultName(r) {
  const d = new Date(r.start.time);
  const map = r.start.map?.name || r.end?.map?.name;
  return `${map ? map + ' · ' : ''}${d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} ${d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })} · ${Math.round(r.result?.minutes ?? 0)} min`;
}

const nameOf = (id) => S.itemdb.name(id);
// your prices (set on the review, kv "myPrices") win, then the item data's (your catalog price, else NPC), then
// prices that came with grindcap-gui items that have no item-data id (kv "prices")
const basePrice = (id) => S.itemdb.items[id]?.price ?? store.get('prices')?.[id] ?? null;
const userPrice = (id) => store.get('myPrices')?.[id] ?? null;
const priceOf = (id) => userPrice(id) ?? basePrice(id);
let repriceTimer = null;
/** A price you typed: every session is worked out again with it (the one shown at once, the others after). */
function setPrice(id, v) {
  const m = { ...(store.get('myPrices') || {}) };
  if (v == null || Number.isNaN(v)) delete m[id]; else m[id] = v;
  store.set('myPrices', m);
  recompute(S.view);
  clearTimeout(repriceTimer);
  repriceTimer = setTimeout(async () => {
    for (const r of await store.allSessions()) {
      if (!r.start || !r.end || r.id === S.view.id) continue;
      r.fixes = r.fixes || noFixes();
      r.result = compare(withFixes(r.start, 'start', r.fixes, nameOf), withFixes(r.end, 'end', r.fixes, nameOf), priceOf, r.pauses || []);
      await store.putSession(r);
    }
    renderNav(); if (tab === 'summary') renderSummary();
  }, 800);
}

/** Apply a session's fixes, compare, save, redraw. Called after every edit on the review panel. */
function recompute(v = S.view) {
  const a = withFixes(v.start, 'start', v.fixes, nameOf), b = withFixes(v.end, 'end', v.fixes, nameOf);
  v.result = a && b ? compare(a, b, priceOf, v.pauses) : null;
  if (v === S.cur) store.set('fixes', v.fixes);
  if (isSaved(v)) store.putSession(record(v)).then(() => { renderNav(); if (tab === 'summary') renderSummary(); });
  S.ver++;
  render();
}

// ------------------------------------------------------------------ corrections

/** You named a look on the review panel: remember it for every later scan (this browser), and keep
 * it in the corrections list you can export. id 'ignore' = not an item / don't count. */
function learn(key, id, how) {
  const v = S.view, l = { ...(v.start?.looks || {}), ...(v.end?.looks || {}) }[key];
  if (!l || !l.sig) return;
  const name = id === 'ignore' ? "(don't count)" : nameOf(id);
  S.corrections = S.corrections.filter((c) => c.key !== key);
  S.corrections.push({ key, id, name, how, was: l.name, best_guess: l.match?.bestName ?? null, t: new Date().toISOString(), crop: l.crop, sig: l.sig });
  store.set('corrections', S.corrections);
  const mine = S.cache.looks.find((x) => x.correctionOf === key);
  if (mine) Object.assign(mine, { id, name });
  else S.cache.add(Float32Array.from(l.sig), id, name, [], { corrected: true }, l.crop).correctionOf = key;
  renderStorage();
}
$('corrDownload').onclick = () => download(`grindcap-corrections-${new Date().toISOString().slice(0, 10)}.json`,
  { kind: 'grindcap-corrections', version: 1, made: new Date().toISOString(), signature: '24x24 RGB, stack-number corner blacked out, row-major', corrections: S.corrections });
$('corrClear').onclick = () => {
  if (!confirm('Forget every icon you named? Later scans go back to the item data alone.')) return;
  S.corrections = []; store.set('corrections', []);
  S.cache.looks = S.cache.looks.filter((l) => !(l.match && l.match.corrected));
  renderStorage();
};

function download(name, obj) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(obj)], { type: 'application/json' }));
  a.download = name; a.click();
}

// ------------------------------------------------------------------ saved sessions

async function showSession(id) {
  if (id === 'cur' || +id === C().id) S.view = S.cur;
  else {
    const r = await store.getSession(+id);
    if (!r) return;
    r.fixes = r.fixes || noFixes(); r.live = r.live || { rows: [] }; r.pauses = r.pauses || []; r.potions = r.potions || []; r.qsNames = r.qsNames || {};
    S.view = r;
  }
  S.ver++;
  render();
}
/** Newest first: the running session (if any), then the saved ones. */
function navIds() {
  const ids = store.listSessions().map((x) => String(x.id));
  if ((C().start && !C().end) || (!C().start && S.collect)) ids.unshift('cur');
  return ids;
}
const viewKey = () => (S.view === S.cur && !isSaved(S.cur) ? 'cur' : String(S.view.id));
$('sessSel').onchange = (e) => showSession(e.target.value);
$('prevSess').onclick = () => { const ids = navIds(), i = ids.indexOf(viewKey()); if (i >= 0 && i < ids.length - 1) showSession(ids[i + 1]); };
$('nextSess').onclick = () => { const ids = navIds(), i = ids.indexOf(viewKey()); if (i > 0) showSession(ids[i - 1]); };
$('sessName').onchange = (e) => {
  const v = S.view;
  if (!v.end) return;
  v.name = e.target.value.trim() || defaultName(v);
  if (v === S.cur) store.set('name', v.name);
  recompute(v);
};
$('deleteSess').onclick = async () => {
  const v = S.view;
  if (!v.end || !confirm(`Delete "${v.name}"? This can't be undone.`)) return;
  await store.deleteSession(v.id);
  if (v === S.cur) resetCur();
  const next = navIds()[0];
  if (next) await showSession(next); else { S.view = S.cur; S.ver++; render(); }
  renderStorage();
};

// ------------------------------------------------------------------ backup: everything in one file

const BACKUP_KEYS = ['myPrices', 'prices', 'start', 'end', 'live', 'pauses', 'fixes', 'name', 'potions', 'qsNames', 'character', 'corrections', 'characters', 'char', 'trackPotions', 'useIds'];
$('backup').onclick = async () => {
  const sessions = await store.allSessions();
  const kv = Object.fromEntries(BACKUP_KEYS.map((k) => [k, store.get(k)]));
  download(`grindcap-backup-${new Date().toISOString().slice(0, 10)}.json`,
    { kind: 'grindcap-backup', version: 1, made: new Date().toISOString(), sessions, kv });
  snapNote(`Backed up ${sessions.length} session${sessions.length === 1 ? '' : 's'}${C().start && !C().end ? ' and the running one' : ''}, ${S.corrections.length} named icons.`);
};
$('restoreBtn').onclick = () => $('restoreFile').click();
$('restoreFile').onchange = async (e) => {
  const f = e.target.files[0];
  e.target.value = '';
  if (!f) return;
  let b;
  try { b = JSON.parse(await f.text()); } catch { alert('That file is not a grindcap backup.'); return; }
  if (b.kind !== 'grindcap-backup' || !Array.isArray(b.sessions)) { alert('That file is not a grindcap backup.'); return; }
  const have = new Map((await store.allSessions()).map((r) => [r.id, r]));
  const add = b.sessions.filter((r) => !have.has(r.id)), newer = b.sessions.filter((r) => have.has(r.id) && (r.saved || 0) > (have.get(r.id).saved || 0));
  const kv = b.kv || {}, runHere = !!(C().start && !C().end) || !!S.collect, runThere = !!(kv.start && !kv.end);
  if (!confirm(`Restore from ${f.name}?\n\n${add.length} new session(s) added, ${newer.length} replaced by a newer copy, ${b.sessions.length - add.length - newer.length} already here.\n`
    + `Named icons and characters are merged.${runThere ? (runHere ? '\nThe backup has a running session, but one is running here: it is left out.' : '\nThe running session in the backup becomes the running session here.') : ''}`)) return;
  for (const r of [...add, ...newer]) {
    r.fixes = r.fixes || noFixes(); r.pauses = r.pauses || [];
    if (!r.result && r.start && r.end) {               // sessions from grindcap-gui come without a result
      const a = withFixes(r.start, 'start', r.fixes, nameOf), z = withFixes(r.end, 'end', r.fixes, nameOf);
      r.result = compare(a, z, (id) => S.itemdb.items[id]?.price ?? kv.prices?.[id] ?? store.get('prices')?.[id] ?? null, r.pauses);
    }
    if (!r.meta && r.start) r.meta = meta(r);
    await store.putSession(r);
  }
  if (kv.prices) store.set('prices', { ...kv.prices, ...(store.get('prices') || {}) });
  if (kv.myPrices) store.set('myPrices', { ...kv.myPrices, ...(store.get('myPrices') || {}) });   // a price set here wins
  // named icons: the backup's are added (a look named here wins)
  const keys = new Set(S.corrections.map((c) => c.key));
  for (const c of kv.corrections || []) if (!keys.has(c.key)) { S.corrections.push(c); S.cache.add(Float32Array.from(c.sig), c.id, c.name, [], { corrected: true }, c.crop); }
  store.set('corrections', S.corrections);
  for (const ch of (kv.characters || []).slice().reverse()) if (!S.chars.some((x) => x.name === ch.name)) S.chars.push(ch);
  store.set('characters', S.chars);
  if (!S.char && kv.char) { S.char = kv.char; store.set('char', S.char); }
  store.set('useIds', [...new Set([...(store.get('useIds') || []), ...(kv.useIds || [])])]);
  if (runThere && !runHere) {
    for (const k of ['start', 'end', 'live', 'pauses', 'fixes', 'name', 'potions', 'qsNames', 'character']) store.set(k, kv[k] ?? null);
    Object.assign(S.cur, { id: kv.start.time, name: kv.name, start: kv.start, end: null, live: kv.live || { rows: [], fails: 0 }, pauses: kv.pauses || [],
      fixes: kv.fixes || noFixes(), potions: kv.potions || [], qsNames: kv.qsNames || {}, character: kv.character || null, result: null });
  }
  snapNote(`Restored: ${add.length} session(s) added, ${newer.length} updated.`);
  recompute(S.view); renderStorage(); renderSummary();
};

// ------------------------------------------------------------------ tabs + summary

let tab = store.get('tab') || 'review';
function showTab(t) {
  tab = t; store.set('tab', t);
  $('tabReview').classList.toggle('on', t === 'review'); $('tabSummary').classList.toggle('on', t === 'summary');
  $('viewSec').hidden = t !== 'review'; $('summarySec').hidden = t !== 'summary';
  if (t === 'summary') renderSummary();
}
$('tabReview').onclick = () => showTab('review');
$('tabSummary').onclick = () => showTab('summary');
$('sumChar').onchange = $('sumMap').onchange = () => renderSummary();
let sumSort = store.get('sumSort') || { k: 'id', dir: -1 };

/** One row per saved session; filter by character and map, sort by clicking a column (newest first by default). */
function renderSummary() {
  const list = store.listSessions();
  const fill = (sel, vals) => { const pick = sel.value; sel.innerHTML = '<option value="">all</option>' + vals.map((n) => `<option ${n === pick ? 'selected' : ''}>${esc(n)}</option>`).join(''); return sel.value; };
  const pc = fill($('sumChar'), [...new Set(list.map((x) => x.character?.name).filter(Boolean))].sort());
  const pm = fill($('sumMap'), [...new Set(list.map((x) => x.map).filter(Boolean))].sort());
  const val = {
    id: (x) => x.id, name: (x) => (x.name || '').toLowerCase(), char: (x) => (x.character?.name || '').toLowerCase(), map: (x) => (x.map || '').toLowerCase(),
    level: (x) => x.level ?? -1, minutes: (x) => x.result?.minutes ?? -1, net: (x) => x.result?.net_per_hr ?? -Infinity,
    exp: (x) => x.result?.exp_per_hr ?? -Infinity, rev: (x) => x.result?.revenue_per_hr ?? -Infinity, cost: (x) => x.result?.cost_per_hr ?? -Infinity,
  };
  const { k, dir } = sumSort, f = val[k] || val.id;
  const rows = list.filter((x) => (!pc || x.character?.name === pc) && (!pm || x.map === pm))
    .sort((a, b) => { const p = f(a), q = f(b); return (p < q ? -1 : p > q ? 1 : 0) * dir || b.id - a.id; });
  const th = (key, label, cls = '') => `<th class="${cls}" data-k="${key}">${label}${k === key ? (dir > 0 ? ' ▲' : ' ▼') : ''}</th>`;
  const lv = (x) => (x.level == null ? '–' : x.level_end != null && x.level_end !== x.level ? `${x.level}→${x.level_end}` : x.level);
  $('summary').innerHTML = rows.length ? `<table><tr>${th('name', 'Session', 'l')}${th('char', 'Character', 'l')}${th('map', 'Map', 'l')}${th('level', 'Level')}${th('minutes', 'Minutes')}${th('rev', 'Revenue/hr')}${th('cost', 'Cost/hr')}${th('net', 'Net mesos/hr')}${th('exp', 'EXP/hr')}</tr>
    ${rows.map((x) => `<tr class="itemrow" data-id="${x.id}"><td class="l">${esc(x.name || new Date(x.id).toLocaleString())}</td>
      <td class="l">${esc(x.character ? `${x.character.name}${x.character.job ? ` (${x.character.job})` : ''}` : '–')}</td>
      <td class="l">${esc(x.map || '–')}</td><td>${lv(x)}</td>
      <td>${fmt(x.result?.minutes, 1)}</td><td>${fmt(x.result?.revenue_per_hr)}</td><td>${fmt(x.result?.cost_per_hr)}</td><td><b>${fmt(x.result?.net_per_hr)}</b></td><td><b>${fmt(x.result?.exp_per_hr)}</b>${x.result?.pct_per_hr != null ? `<br><span class="mute small">${x.result.pct_per_hr.toFixed(1)}%/hr</span>` : ''}</td></tr>`).join('')}</table>
    <p class="mute small">${rows.length} of ${list.length} sessions. Click a column to sort (again to reverse), a session to open it. More summary views come here later.</p>`
    : `<p class="mute">${list.length ? 'No sessions match these filters.' : 'No saved sessions yet.'}</p>`;
  for (const h of $('summary').querySelectorAll('th[data-k]')) h.onclick = () => {
    const key = h.dataset.k;
    sumSort = { k: key, dir: sumSort.k === key ? -sumSort.dir : (['name', 'char', 'map'].includes(key) ? 1 : -1) };
    store.set('sumSort', sumSort); renderSummary();
  };
  for (const tr of $('summary').querySelectorAll('tr[data-id]')) tr.onclick = () => { showSession(tr.dataset.id); showTab('review'); };
}

// ------------------------------------------------------------------ pictures

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

// ------------------------------------------------------------------ rendering

function render() {
  const sharing = !!(S.cap && S.cap.live);
  $('share').disabled = sharing;
  $('share').textContent = sharing ? 'Sharing the game window' : 'Share MapleStory window';
  $('saveFrame').disabled = !sharing;
  const run = running(), paused = isPaused(C().pauses);
  $('startSnap').disabled = !sharing || !!S.collect || run;
  $('endSnap').disabled = !sharing || !!S.collect || !run;
  $('pauseSnap').disabled = !run || !!S.collect;
  $('pauseSnap').textContent = paused ? 'Resume' : 'Pause';
  $('discardSnap').disabled = !run && !S.collect;
  $('finishSnap').hidden = !S.collect;
  $('capState').innerHTML = sharing ? '<span class="ok">● Sharing the game window</span>' : '<span class="bad">● Not sharing: press "Share MapleStory window" and pick the game</span>';
  if (document.activeElement !== $('charName')) $('charName').value = S.char?.name || '';
  $('charJob').value = S.char?.job || '';
  renderCapture(); renderSession(); renderTop(); renderNav(); renderView();
  updatePopout();
}

function renderSession() {
  const run = running(), paused = isPaused(C().pauses), c = S.collect;
  const a = alertNow();
  $('alert').hidden = !a; $('alert').textContent = a;
  $('scanHelp').hidden = !c;
  $('popout').hidden = popoutOpen();
  $('sessionLine').innerHTML = c
    ? `<b>${c.kind === 'start' ? 'Start' : 'End'}: scan your inventory</b> ` + COUNTED_TABS.map((t) => `<span class="chip ${c.seen.has(t) ? 'done' : ''}">${c.seen.has(t) ? '✓ ' : ''}${t}${c.pages[t] ? ' ' + c.pages[t].length : ''}</span>`).join('')
    : run ? `${paused ? '<b class="bad">PAUSED</b>' : '<span class="ok">Session running</span>'} <span class="timer">${hms(activeMs(C().start.time, Date.now(), C().pauses))}</span>${C().start.map ? ` · ${esc(C().start.map.name)}` : ''}`
    : '<span class="mute">No session running. Share the game window, then press Start.</span>';
}

function renderTop() {
  const live = C().live, rows = live.rows, ser = liveSeries(rows, 5, C().pauses), last = rows.at(-1), s = ser.at(-1);
  $('liveStats').innerHTML = running() || S.collect ? [
    ['Level', last ? `${last.level} · ${last.pct}%` : '–'],
    ['EXP/hr (5-min)', `<b>${fmt(s ? s.ema * 60 : null)}</b>${pctTxt(s?.emaPct)}`],
    ['EXP/hr (session)', `${fmt(s ? s.cum * 60 : null)}${pctTxt(s?.pct)}`],
    ['EXP gained', fmt(s?.gained)],
    ['Readings', `${rows.length}${live.fails ? ` (${live.fails} failed)` : ''}`],
  ].map(([k, v]) => `<div><span>${k}</span>${v}</div>`).join('') : '';
  $('liveNote').textContent = running() ? live.why || '' : '';
  $('potLine').textContent = running() && S.trackPotions && C().lastPot !== undefined ? describe(C().lastPot, S.qsTable) : '';
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

function renderNav() {
  const list = store.listSessions(), key = viewKey(), ids = navIds();
  const opts = [];
  if (ids[0] === 'cur') opts.push(['cur', `Current session (${S.collect ? 'scanning' : 'running'})`]);
  for (const x of list) opts.push([String(x.id), `${x.name || new Date(x.id).toLocaleString()}${x.character ? `  ·  ${x.character.name}` : ''}  ·  ${fmt(x.result?.exp_per_hr)} EXP/hr  ·  ${fmt(x.result?.net_per_hr)} net/hr`]);
  if (!opts.length) opts.push(['cur', 'No sessions yet']);
  $('sessSel').innerHTML = opts.map(([v, t]) => `<option value="${v}" ${v === key ? 'selected' : ''}>${esc(t)}</option>`).join('');
  const i = ids.indexOf(key);
  $('prevSess').disabled = i < 0 || i >= ids.length - 1;   // older
  $('nextSess').disabled = i <= 0;                          // newer
  const v = S.view;
  $('sessName').disabled = !v.end; $('deleteSess').disabled = !v.end;
  $('sessChar').disabled = $('sessJob').disabled = !v.start;
  if (document.activeElement !== $('sessChar')) $('sessChar').value = v.character?.name || '';
  $('sessJob').value = v.character?.job || '';
  if (document.activeElement !== $('sessName')) $('sessName').value = v.end ? v.name || '' : '';
  $('sessCount').textContent = `${list.length} saved`;
}

function renderGraph() {
  const v = S.view, ser = liveSeries(v.live?.rows || [], 5, v.pauses);
  $('graphWrap').hidden = !ser.length;
  if (ser.length) drawGraph($('graph'), ser, 60, 'EXP/hr');
  const pts = potPoints(v);
  $('potWrap').hidden = !pts.length;
  if (pts.length) drawPotionGraph($('potGraph'), pts);
  $('potSum').innerHTML = potionSummary(pts);
}

/** Potion mesos/hr points for a session (live readings up to its end), like review.py _potions. */
function potPoints(v) {
  if (!v.start || !(v.potions || []).length) return [];
  const toS = (ms) => (ms == null ? null : ms / 1000), endS = v.end ? v.end.time / 1000 : Infinity;
  const rows = v.potions.filter((r) => r.time <= endS + 1);
  return potionSeries({ time: v.start.time / 1000, pauses: (v.pauses || []).map(([a, b]) => [toS(a), toS(b)]) }, rows, S.qsTable, 5, {})   // each reading keeps the name it was read with (keys can change item mid-run)
    .filter((p) => p.ema_hp != null);
}

function renderView() {
  const v = S.view, r = v.result;
  renderGraph();
  if (r) {
    const k = [
      ['Net mesos/hr incl. items', `<span class="big">${fmt(r.net_per_hr)}</span>`], ['EXP/hr', `<span class="big">${fmt(r.exp_per_hr)}</span>${pctTxt(r.pct_per_hr)}`],
      ['Revenue/hr (mesos + items gained)', fmt(r.revenue_per_hr)], ['Cost/hr (items used)', fmt(r.cost_per_hr)],
      ['Minutes', fmt(r.minutes, 1) + (r.paused_minutes > 0.05 ? ` <span class="mute">(+${fmt(r.paused_minutes, 1)} paused)</span>` : '')],
      ['EXP gained', fmt(r.exp)], ['Mesos change', fmt(r.mesos)],
    ];
    $('result').innerHTML = `<div class="stats">${k.map(([a, b]) => `<div><span>${a}</span>${b}</div>`).join('')}</div>
      ${r.unpriced.length ? `<p class="mute small">No price for: ${esc(r.unpriced.join(', '))}</p>` : ''}
      ${r.tabs_left_out.length ? `<p class="mute small">Tabs only one scan read (not compared): ${r.tabs_left_out.join(', ')}</p>` : ''}`;
  } else {
    $('result').innerHTML = v.start ? `<p class="mute">Start: level ${v.start.level ?? '?'}, mesos ${fmt(v.start.mesos)}, ${Object.keys(v.start.items).length} kinds of items. Results appear after End.</p>`
      : '<p class="mute">Nothing here yet. Share the game window and press Start; finished sessions are kept and listed above.</p>';
  }
  renderReview($('review'), { ...v, itemdb: S.itemdb, reviewVersion: S.ver }, { nameOf, priceOf, userPrice, basePrice, setPrice, recompute: () => recompute(v), learn, maps: S.maps });
}

async function renderStorage() {
  const n = S.corrections.length;
  $('corrCount').textContent = n ? `${n} icon${n > 1 ? 's' : ''} you named` : 'No icons named yet';
  $('corrDownload').disabled = !n; $('corrClear').disabled = !n;
  const e = await store.usage();
  $('storage').textContent = e ? `Browser storage: ${(e.usage / 1e6).toFixed(1)} MB used of ${(e.quota / 1e9).toFixed(0)} GB allowed` : '';
}

init();
