// Snapshots and live EXP: building a snapshot from captured pages, comparing two, and EXP/min from
// live readings. Follows src/grindcap/snapshot.py (build_snapshot, exp_gained, compare, live_series).
import { expToNext } from './gamedata.js';
import { mergePages, totals } from './inventory.js';

export const COUNTED_TABS = ['Equip', 'Use', 'Setup', 'Etc'];
export const SKIP_TABS = ['Cash', 'Deco'];

/** EXP from (level a, exp a) to (level b, exp b), adding whole levels in between. */
export function expBetween(l0, e0, l1, e1) {
  if (e0 == null || e1 == null || l0 == null || l1 == null) return null;
  if (l1 === l0 && e1 < e0) l1 = l0 + 1;      // EXP went down: one level-up
  if (l1 === l0) return e1 - e0;
  let total = (expToNext(l0) || 0) - e0;
  for (let lv = l0 + 1; lv < l1; lv++) total += expToNext(lv) || 0;
  return total + e1;
}

/** pages: {tab: [page, ...]} -> snapshot. status = {level, exp, pct}; mesosReads = values read per page. */
export function buildSnapshot(time, status, pages, mesosReads, extra = {}) {
  const tabs = {}, mergeLog = {};
  for (const [tab, list] of Object.entries(pages)) { mergeLog[tab] = []; tabs[tab] = mergePages(list, mergeLog[tab]); }
  const c = new Map();
  for (const v of mesosReads) if (v != null) c.set(v, (c.get(v) || 0) + 1);
  let mesos = null, n = 0;
  for (const [v, k] of c) if (k > n) { n = k; mesos = v; }
  return {
    time, when: new Date(time).toLocaleString(),
    level: status.level, exp: status.exp, exp_pct: status.pct, exp_checked: status.checked,
    mesos, mesos_checked: n >= 2 || mesosReads.length === 1, mesos_reads: mesosReads,
    // every slot keeps its picture, what was read and which look it was, for the review panel
    tabs: Object.fromEntries(Object.entries(tabs).map(([t, rows]) => [t, rows.map((r) => r.map((s) => ({ ...s })))])),
    items: totals(tabs), merge_log: mergeLog, ...extra,
  };
}

/** A snapshot with your corrections applied. fixes = {looks: {lookKey: itemId}, qty: {"<kind>|<ref>": n},
 * status: {start|end: {level, exp, mesos}}}; kind = "start" or "end". nameOf(id) names an item id. */
export function withFixes(snap, kind, fixes, nameOf) {
  if (!snap) return snap;
  const st = (fixes.status || {})[kind] || {};
  const tabs = {};
  for (const [t, rows] of Object.entries(snap.tabs || {})) {
    tabs[t] = rows.map((r) => r.map((s) => {
      if (!s.id || s.id === '?') return s;
      const id = fixes.looks?.[s.look] ?? s.id;
      if (id === 'ignore') return { ...s, id: null, qty: 0, ignored: true };
      const q = fixes.qty?.[`${kind}|${s.ref}`];
      return { ...s, id, name: typeof id === 'number' ? nameOf(id) : s.name, qty: q ?? s.qty, fixedQty: q != null, fixedName: fixes.looks?.[s.look] != null };
    }));
  }
  const pick = (k) => (st[k] != null && st[k] !== '' ? Number(st[k]) : snap[k]);
  return { ...snap, tabs, items: totals(tabs), level: pick('level'), exp: pick('exp'), mesos: pick('mesos') };
}

/** Milliseconds between a and b that weren't paused. pauses: [[t0, t1|null], ...] (null = still paused). */
export function activeMs(a, b, pauses = []) {
  let ms = b - a;
  for (const [p0, p1] of pauses || []) ms -= Math.max(0, Math.min(b, p1 ?? b) - Math.max(a, p0));
  return Math.max(0, ms);
}
export const isPaused = (pauses) => !!(pauses && pauses.length && pauses.at(-1)[1] == null);

/** Before vs after. prices: item id -> mesos each (or null). Paused time is left out of every rate. */
export function compare(start, end, priceOf, pauses = []) {
  const hours = activeMs(start.time, end.time, pauses) / 3.6e6;
  const perHr = (v) => (hours > 0 && v != null ? Math.round(v / hours) : null);
  const tabsS = new Set(Object.keys(start.tabs || {})), tabsE = new Set(Object.keys(end.tabs || {}));
  const both = [...tabsS].filter((t) => tabsE.has(t));
  const where = {};
  for (const snap of [start, end]) for (const [t, rows] of Object.entries(snap.tabs || {})) for (const r of rows) for (const s of r) if (s.id) where[s.id] = t;
  const ids = [...new Set([...Object.keys(start.items), ...Object.keys(end.items)])];
  const leftOut = [], rows = [];
  for (const id of ids) {
    if (where[id] && !both.includes(where[id])) { leftOut.push(id); continue; }
    const a = start.items[id]?.qty || 0, b = end.items[id]?.qty || 0;
    if (a === b) continue;
    const price = priceOf(id);
    rows.push({ id, name: (end.items[id] || start.items[id]).name || id, before: a, after: b, change: b - a,
                per_hr: perHr(b - a), price, value: price != null ? (b - a) * price : null });
  }
  rows.sort((x, y) => (y.value || 0) - (x.value || 0) || y.change - x.change);
  const exp = expBetween(start.level, start.exp, end.level, end.exp);
  const mesos = start.mesos != null && end.mesos != null ? end.mesos - start.mesos : null;
  const gained = rows.filter((r) => r.value && r.change > 0).reduce((a, r) => a + r.value, 0);
  const used = rows.filter((r) => r.value && r.change < 0).reduce((a, r) => a - r.value, 0);
  const net = (mesos || 0) + gained - used;
  return {
    minutes: +(hours * 60).toFixed(1), paused_minutes: +((end.time - start.time) / 6e4 - hours * 60).toFixed(1), exp, exp_per_hr: perHr(exp), levels: (end.level || 0) - (start.level || 0),
    mesos, mesos_per_hr: perHr(mesos), items_gained_value: gained, items_used_value: used,
    net_mesos_incl_items: net, net_per_hr: perHr(net), revenue_per_hr: perHr((mesos || 0) + gained), cost_per_hr: perHr(used), items: rows,
    unpriced: rows.filter((r) => r.price == null).map((r) => r.name),
    tabs_left_out: [...new Set([...tabsS, ...tabsE])].filter((t) => !both.includes(t)),
    items_left_out: leftOut.map((id) => (end.items[id] || start.items[id]).name || id),
  };
}

/** Live readings [{t (ms), level, exp}] -> per-reading EXP/min, a 5-minute EMA and the session average. */
export function liveSeries(rows, tauMin = 5, pauses = []) {
  const out = [];
  if (rows.length < 2) return out;
  const t0 = rows[0].t, act = (t) => activeMs(t0, t, pauses) / 60000;   // x = active minutes
  let ema = null, total = 0;
  for (let i = 1; i < rows.length; i++) {
    const a = rows[i - 1], b = rows[i], dt = act(b.t) - act(a.t);
    const g = expBetween(a.level, a.exp, b.level, b.exp);
    if (g == null || dt <= 0) continue;
    total += g;
    const rate = g / dt;
    const k = 1 - Math.exp(-dt / tauMin);
    ema = ema == null ? rate : ema + k * (rate - ema);
    out.push({ min: act(b.t), rate, ema, cum: total / act(b.t), gained: total });
  }
  return out;
}
