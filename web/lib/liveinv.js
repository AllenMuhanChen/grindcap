// Live net mesos/hr from the inventory while you grind. Whenever the inventory is open during a running
// session, the page on screen and the meso field are read again. Each part (meso field, each tab, quick slot
// potions) has its own value over time; its rate is the change since its previous point divided by the active
// time in between, so it moves with what you do. A part not read lately keeps the rate it last had; the net is
// the parts added up. Changes across a pause (selling, buying potions) don't count. Pure logic: no screen, no DOM.
import { activeMs } from './session.js';
import { UNKNOWN } from './inventory.js';

/** A page's slots without pictures (what is kept in the session): [[{id, qty, name, look}|{}]]. */
export function liteRows(page) {
  return page.map((r) => r.map((s) => (s && s.id ? { id: s.id, qty: s.qty, name: s.name ?? null, look: s.look ?? null } : {})));
}

/** Which row of the known tab the page's first row is. Stacks grow and new items fill empty slots while you
 * grind, so only item ids are compared (not counts), and a slot that was empty, or is empty now, says nothing.
 * The offset with the most same-id slots wins, if at most 1 in 5 compared slots disagree. Nothing to compare
 * (an empty tab at Start) -> 0. Returns null when no offset fits (items were moved around). */
export function alignPage(known, page) {
  const maxOff = Math.max(0, known.length - page.length);
  let best = null, bestScore = -1, anyCompared = false;
  for (let off = 0; off <= maxOff; off++) {
    let same = 0, diff = 0, exact = 0;   // exact: same id and count (most stacks don't change): breaks ties
    for (let r = 0; r < page.length && off + r < known.length; r++) {
      for (let c = 0; c < page[r].length; c++) {
        const a = known[off + r]?.[c]?.id, b = page[r][c]?.id;
        if (!a || !b || a === UNKNOWN || b === UNKNOWN) continue;
        if (a === b) { same++; if (known[off + r][c].qty === page[r][c].qty) exact++; } else diff++;
      }
    }
    if (same + diff) anyCompared = true;
    const score = same * 1000 + exact;   // a tab full of one item (ore stacks) matches at every offset by id alone
    if (same + diff && diff <= Math.floor((same + diff) / 5) && score > bestScore) { best = off; bestScore = score; }
  }
  return best ?? (anyCompared ? null : 0);
}

/** The known rows of a tab with the page written over the rows it shows ("?" slots keep the old value). */
export function applyPage(known, page, off) {
  const rows = known.map((r) => r.slice());
  for (let r = 0; r < page.length; r++) {
    const row = rows[off + r] || (rows[off + r] = page[r].map(() => ({})));
    for (let c = 0; c < page[r].length; c++) if (page[r][c]?.id !== UNKNOWN) row[c] = page[r][c] || {};
  }
  return rows;
}

const lookFix = (fixes) => (s) => {
  if (!s || !s.id || s.id === UNKNOWN) return s;
  const id = fixes?.looks?.[s.look];
  if (id == null) return s;
  return id === 'ignore' ? {} : { ...s, id };
};

/** qty per item id over a tab's rows. */
function counts(rows) {
  const out = {};
  for (const r of rows) for (const s of r) if (s && s.id && s.id !== UNKNOWN) out[s.id] = { qty: (out[s.id]?.qty || 0) + (s.qty || 0), name: s.name };
  return out;
}

/** Each part's value over time, from the start snapshot and the reads (oldest first). start = the start snapshot
 * with your fixes applied; reads = [{t ms, tab, rows (liteRows), mesos}] (tab/rows missing: a meso-only read).
 * Parts: 'Mesos' (the meso field) and every counted tab the Start scan read, valued at priceOf (unpriced items
 * left out and listed). A tab's state = Start rows with each page written over the rows it shows (alignPage;
 * a page that fits nowhere is skipped). opts.skipNames: items left out of the tabs (quick slot potions, which
 * get their own part from the quick slot readings). Returns {states: {part: [{t, value}]}, unpriced: [name]}. */
export function partStates(start, reads, priceOf, counted = ['Equip', 'Use', 'Setup', 'Etc'], fixes = null, opts = {}) {
  const fix = lookFix(fixes), skip = new Set(opts.skipNames || []), unpriced = new Set();
  const value = (rows) => {
    let v = 0;
    for (const [id, c] of Object.entries(counts(rows))) {
      if (skip.has(c.name)) continue;
      const p = priceOf(id);
      if (p == null) { unpriced.add(c.name || id); continue; }
      v += c.qty * p;
    }
    return v;
  };
  const rowsOf = {}, states = {};
  if (start.mesos != null) states.Mesos = [{ t: start.time, value: start.mesos }];
  for (const tab of counted) {
    if (!start.tabs?.[tab]) continue;                       // the Start scan didn't read it: nothing to compare with
    rowsOf[tab] = start.tabs[tab].map((r) => r.map((x) => fix(x) || {}));
    states[tab] = [{ t: start.time, value: value(rowsOf[tab]) }];
  }
  for (const rd of reads || []) {
    if (rd.mesos != null && states.Mesos) states.Mesos.push({ t: rd.t, value: rd.mesos });
    if (!rd.tab || !rd.rows || !rowsOf[rd.tab]) continue;
    const page = rd.rows.map((r) => r.map(fix)), off = alignPage(rowsOf[rd.tab], page);
    if (off == null) continue;
    rowsOf[rd.tab] = applyPage(rowsOf[rd.tab], page, off);
    states[rd.tab].push({ t: rd.t, value: value(rowsOf[rd.tab]) });
  }
  return { states, unpriced: [...unpriced] };
}

/** Wall-clock states [{t, value}] -> [{min (active minutes since Start), value, gap}]; gap = a pause lies between
 * this state and the one before (what changed then, e.g. selling or buying potions, is not grinding). */
export function activeStates(states, startTime, pauses = []) {
  return states.map((s, i) => ({ min: activeMs(startTime, s.t, pauses) / 6e4, value: s.value,
    gap: i > 0 && (pauses || []).some(([p0, p1]) => p0 < s.t && (p1 ?? Infinity) > states[i - 1].t) }));
}

/** Rate points of one part: rate = change since the previous point / active time between them (mesos/hr); avg = the
 * moving average over the last n points (reads come at irregular times, so it's their gains added up / their minutes
 * added up: a long interval weighs more than a short one; n = 1: avg = rate). A point
 * needs at least minMin active minutes since the previous one (reads come every 15 s while the inventory is
 * open; a few mesos over seconds would be a huge rate). A pause in between restarts from the first state after
 * it, so nothing that changed while paused counts. states: [{min, value, gap}] (activeStates). */
export function partPoints(states, minMin = 3, n = 1) {
  const out = [];
  let anchor = states[0];
  for (const s of states.slice(1)) {
    if (s.gap) { anchor = s; continue; }
    const dm = s.min - anchor.min;
    if (dm < minMin) continue;
    out.push({ min: s.min, rate: (s.value - anchor.value) / dm * 60, gain: s.value - anchor.value, dmin: dm });
    anchor = s;
  }
  for (let i = 0; i < out.length; i++) {
    const w = out.slice(Math.max(0, i - Math.max(1, n) + 1), i + 1);
    out[i].avg = w.reduce((a, p) => a + p.gain, 0) / w.reduce((a, p) => a + p.dmin, 0) * 60;
  }
  return out;
}

/** parts: {name: [{min, value, gap}]} -> per part its points, latest rate (moving average over its last n points; how old) and session average
 * (sum of gains / minutes covered), and the net: latest = each part's newest rate added up (an outdated part
 * counts at the rate it last had), session = the session averages added up. total = the net after every point.
 * nowMin = active minutes now. Parts without a point yet are listed in waiting. */
export function liveNet(parts, nowMin, minMin = 3, n = 1) {
  const out = [], waiting = [];
  for (const [name, states] of Object.entries(parts)) {
    const points = partPoints(states, minMin, n);
    if (!points.length) { waiting.push(name); continue; }
    const gain = points.reduce((a, p) => a + p.gain, 0), covered = points.reduce((a, p) => a + p.dmin, 0);
    out.push({ name, points, latest: points.at(-1).avg, last_min: points.at(-1).min, age_min: nowMin - points.at(-1).min, session: gain / covered * 60, gain, covered_min: covered });
  }
  const sum = (k) => (out.length ? Math.round(out.reduce((a, p) => a + p[k], 0)) : null);
  // the net after each point: every part at its newest rate so far
  const events = out.flatMap((p) => p.points.map((q) => ({ min: q.min, name: p.name, rate: q.avg }))).sort((a, b) => a.min - b.min);
  const cur = {}, total = [];
  for (const e of events) {
    cur[e.name] = e.rate;
    const pt = { min: e.min, est: Math.round(Object.values(cur).reduce((a, b) => a + b, 0)) };
    if (total.length && total.at(-1).min === e.min) total[total.length - 1] = pt; else total.push(pt);
  }
  return { parts: out, waiting, net_latest: sum('latest'), net_session: sum('session'), total };
}

/** Same page as the last read of this tab (ids and counts) and same mesos: nothing new to keep. */
export function sameRead(a, b) {
  if (!a || !b || a.tab !== b.tab || a.mesos !== b.mesos) return false;
  return JSON.stringify((a.rows || []).map((r) => r.map((s) => [s.id, s.qty]))) === JSON.stringify((b.rows || []).map((r) => r.map((s) => [s.id, s.qty])));
}
