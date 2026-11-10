// Live net mesos/hr from the inventory while you grind. Whenever the inventory is open during a running
// session, the page on screen and the meso field are read again. Each tab keeps its own last-seen state:
// the start snapshot's rows, with every page read since written over the rows it shows. A tab's item
// value change is turned into a rate over ITS OWN window (start -> when that tab was last read), and the
// meso field likewise, so a tab you looked at 20 minutes ago still counts at the rate it had then and a
// tab never opened since Start counts nothing (listed as not seen). Pure logic: no screen, no DOM.
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
  let best = null, bestSame = -1, anyCompared = false;
  for (let off = 0; off <= maxOff; off++) {
    let same = 0, diff = 0;
    for (let r = 0; r < page.length && off + r < known.length; r++) {
      for (let c = 0; c < page[r].length; c++) {
        const a = known[off + r]?.[c]?.id, b = page[r][c]?.id;
        if (!a || !b || a === UNKNOWN || b === UNKNOWN) continue;
        if (a === b) same++; else diff++;
      }
    }
    if (same + diff) anyCompared = true;
    if (same + diff && diff <= Math.floor((same + diff) / 5) && same > bestSame) { best = off; bestSame = same; }
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

/** Replays the reads (oldest first) on the start snapshot. start = the start snapshot with your fixes applied;
 * reads = [{t ms, tab, rows (liteRows), mesos}] (tab/rows may be missing: a meso-only read).
 * Returns {tabs: {tab: {rows, t, reads, skipped}}, mesos: {value, t}|null}. */
export function replay(start, reads, fixes = null) {
  const fix = lookFix(fixes);
  const tabs = {};
  for (const [t, rows] of Object.entries(start.tabs || {})) tabs[t] = { rows: rows.map((r) => r.map((s) => fix(s) || {})), t: null, reads: 0, skipped: 0 };
  let mesos = null;
  for (const rd of reads || []) {
    if (rd.mesos != null) mesos = { value: rd.mesos, t: rd.t };
    if (!rd.tab || !rd.rows) continue;
    const page = rd.rows.map((r) => r.map(fix));
    const cur = tabs[rd.tab];
    if (!cur) continue;                      // a tab the Start scan didn't read: nothing to compare with
    const off = alignPage(cur.rows, page);
    if (off == null) { cur.skipped++; continue; }
    cur.rows = applyPage(cur.rows, page, off);
    cur.t = rd.t; cur.reads++;
  }
  return { tabs, mesos };
}

/** The live estimate at time `now` (ms). priceOf(id) -> mesos or null. counted = tabs that count (Equip, Use,
 * Setup, Etc). potionCostPerHr (optional): quick slot potion spend, stands in for the Use tab until it is read.
 * Returns {net_per_hr, mesos: {...}|null, tabs: [{tab, seen, t, age_min, minutes, value, per_hr, items}],
 * not_seen: [tab], unpriced: [name], potion_fallback} — net_per_hr null until anything was read. */
export function estimate(start, reads, priceOf, pauses = [], now = Date.now(), counted = ['Equip', 'Use', 'Setup', 'Etc'], fixes = null, potionCostPerHr = null) {
  const st = replay(start, reads, fixes);
  const hrs = (t) => activeMs(start.time, t, pauses) / 3.6e6;
  const rate = (v, t) => { const h = hrs(t); return h > 0 ? v / h : null; };
  const fix = lookFix(fixes);
  const unpriced = new Set();
  let net = null;
  const add = (v) => { if (v != null) net = (net || 0) + v; };

  let mesos = null;
  if (st.mesos && start.mesos != null) {
    const change = st.mesos.value - start.mesos;
    mesos = { start: start.mesos, now: st.mesos.value, change, t: st.mesos.t, minutes: hrs(st.mesos.t) * 60, age_min: (now - st.mesos.t) / 6e4, per_hr: rate(change, st.mesos.t) };
    add(mesos.per_hr);
  }

  const tabs = [], notSeen = [];
  let potionFallback = null;
  for (const tab of counted) {
    const s = st.tabs[tab];
    if (!s || s.t == null) {
      notSeen.push(tab);                     // not read since Start (or not in the Start scan): counts nothing
      if (tab === 'Use' && potionCostPerHr != null) { potionFallback = -potionCostPerHr; add(potionFallback); }
      continue;
    }
    const before = counts((start.tabs?.[tab] || []).map((r) => r.map((x) => fix(x) || {}))), after = counts(s.rows);
    const items = [];
    let value = 0;
    for (const id of new Set([...Object.keys(before), ...Object.keys(after)])) {
      const a = before[id]?.qty || 0, b = after[id]?.qty || 0;
      if (a === b) continue;
      const p = priceOf(id), name = (after[id] || before[id]).name || id;
      if (p == null) { unpriced.add(name); items.push({ id, name, change: b - a, value: null }); continue; }
      value += (b - a) * p;
      items.push({ id, name, change: b - a, value: (b - a) * p });
    }
    items.sort((x, y) => (y.value || 0) - (x.value || 0));
    const per = rate(value, s.t);
    tabs.push({ tab, seen: true, t: s.t, age_min: (now - s.t) / 6e4, minutes: hrs(s.t) * 60, value, per_hr: per, items, reads: s.reads, skipped: s.skipped });
    add(per);
  }
  return { net_per_hr: net == null ? null : Math.round(net), mesos, tabs, not_seen: notSeen, unpriced: [...unpriced], potion_fallback: potionFallback };
}

/** The estimate after each read: [{min (active minutes), est}] for a graph. */
export function estimateSeries(start, reads, priceOf, pauses = [], counted, fixes = null) {
  const out = [];
  for (let i = 0; i < (reads || []).length; i++) {
    const t = reads[i].t, e = estimate(start, reads.slice(0, i + 1), priceOf, pauses, t, counted, fixes);
    if (e.net_per_hr != null) out.push({ min: activeMs(start.time, t, pauses) / 6e4, est: e.net_per_hr });
  }
  return out;
}

/** Same page as the last read of this tab (ids and counts) and same mesos: nothing new to keep. */
export function sameRead(a, b) {
  if (!a || !b || a.tab !== b.tab || a.mesos !== b.mesos) return false;
  return JSON.stringify((a.rows || []).map((r) => r.map((s) => [s.id, s.qty]))) === JSON.stringify((b.rows || []).map((r) => r.map((s) => [s.id, s.qty])));
}
