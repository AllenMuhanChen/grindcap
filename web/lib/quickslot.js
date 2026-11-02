// Quick slot potions: a port of src/grindcap/quickslot.py. The 2x4 quick slot panel is found by masked
// grey template matching (web/data/quickslot_panel.png: frame + gaps only), each slot's number (that
// item's inventory total) is read by StackDigits, the item comes from config slots, the session's names
// (match_by_count on the start inventory), or the icon among your Use items. potionSeries turns the
// readings into mesos/hr spent on HP and MP potions at NPC shop price.
import { gray, crop, resizeArea } from './img.js';
import { slotPatch } from './digits.js';

const PANEL_SLOT0 = [13, 7], PITCH = [49.3, 48.0], SLOT = 40;
export const KEYS = ['Shift', 'Ins', 'Hm', 'PgUp', 'Ctrl', 'Del', 'End', 'PgDn'];
const LABEL_H = 10, MAX_DIFF = 900;

// NPC shop price (mesos) and what each potion restores. Override/add with quickslot.prices (config).
export const POTIONS = {
  'Red Potion': ['hp', 50], 'Orange Potion': ['hp', 160], 'White Potion': ['hp', 320],
  'Blue Potion': ['mp', 200], 'Mana Elixir': ['mp', 620],
  'Lemon': ['mp', 150],          // restores MP; not sold by NPCs, 150 = what Allen pays (2026-11-01)
};

export function prices(cfgPrices = null) {
  const out = { ...POTIONS };
  for (const [name, v] of Object.entries(cfgPrices || {})) out[name] = [String(v[0]).toLowerCase(), parseInt(v[1], 10)];
  return out;
}

/** Template prepared for a frame height: grey values + mask indices, full size and a /4 copy. */
const prepCache = new Map();
function prep(tmpl, s) {
  const key = s.toFixed(3);
  if (prepCache.has(key)) return prepCache.get(key);
  const n = tmpl.w * tmpl.h;
  let g = { w: tmpl.w, h: tmpl.h, c: 1, data: new Float32Array(n) }, m = { w: tmpl.w, h: tmpl.h, c: 1, data: new Float32Array(n) };
  for (let i = 0; i < n; i++) {
    const r = tmpl.data[4 * i], gg = tmpl.data[4 * i + 1], b = tmpl.data[4 * i + 2];
    g.data[i] = 0.299 * r + 0.587 * gg + 0.114 * b;
    m.data[i] = tmpl.data[4 * i + 3] > 127 ? 1 : 0;
  }
  if (Math.abs(s - 1) > 0.02) { const w = Math.round(tmpl.w * s), h = Math.round(tmpl.h * s); g = resizeArea(g, w, h); m = resizeArea(m, w, h); }
  const pts = (gm, mm) => { const o = []; for (let y = 0; y < gm.h; y++) for (let x = 0; x < gm.w; x++) if (mm.data[y * gm.w + x] > 0.5) o.push([x, y, gm.data[y * gm.w + x]]); return o; };
  const sm = 4, gs = resizeArea(g, Math.max(1, Math.round(g.w / sm)), Math.max(1, Math.round(g.h / sm)));
  const ms = resizeArea(m, gs.w, gs.h);
  const out = { w: g.w, h: g.h, full: pts(g, m), small: pts(gs, ms), sw: gs.w, sh: gs.h, sm };
  prepCache.set(key, out);
  return out;
}
const sqd = (img, pts, x, y, stop = Infinity) => {
  let s = 0;
  for (let i = 0; i < pts.length && s < stop; i++) { const [dx, dy, v] = pts[i], d = img.data[(y + dy) * img.w + x + dx] - v; s += d * d; }
  return s;
};

/** {x, y, s} of the quick slot panel (bottom third of the window), or null. `hint` = last position. */
export function findPanel(frame, tmpl, hint = null) {
  const s = frame.h / 1080, t = prep(tmpl, s);
  const y0 = Math.floor(frame.h * 2 / 3);
  const reg = gray(crop(frame, 0, y0, frame.w, frame.h - y0));
  if (reg.h < t.h || reg.w < t.w) return null;
  const refine = (cx, cy, r) => {
    let best = Infinity, bx = 0, by = 0;
    for (let y = Math.max(0, cy - r); y <= Math.min(reg.h - t.h, cy + r); y++) for (let x = Math.max(0, cx - r); x <= Math.min(reg.w - t.w, cx + r); x++) {
      const v = sqd(reg, t.full, x, y, best); if (v < best) { best = v; bx = x; by = y; }
    }
    return { score: best / t.full.length, x: bx, y: by };
  };
  if (hint) {                      // the panel doesn't move: check where it was first
    const r = refine(hint.x, hint.y - y0, 3);
    if (r.score <= MAX_DIFF) return { x: r.x, y: r.y + y0, s, score: r.score };
  }
  const small = resizeArea(reg, Math.max(1, Math.round(reg.w / t.sm)), Math.max(1, Math.round(reg.h / t.sm)));
  const cands = [];
  for (let y = 0; y + t.sh <= small.h; y++) for (let x = 0; x + t.sw <= small.w; x++) cands.push([sqd(small, t.small, x, y), x, y]);
  cands.sort((a, b) => a[0] - b[0]);
  let best = null;
  for (const [, x, y] of cands.slice(0, 3)) {
    const r = refine(x * t.sm, y * t.sm, t.sm + 2);
    if (!best || r.score < best.score) best = r;
  }
  return best && best.score <= MAX_DIFF ? { x: best.x, y: best.y + y0, s, score: best.score } : null;
}

export function slotBoxes(panel) {
  const { x, y, s } = panel, out = [];
  for (let r = 0; r < 2; r++) for (let c = 0; c < 4; c++) {
    out.push([Math.round(x + (PANEL_SLOT0[0] + PITCH[0] * c) * s), Math.round(y + (PANEL_SLOT0[1] + PITCH[1] * r) * s), Math.round(SLOT * s), Math.round(SLOT * s)]);
  }
  return out;
}

/** Every slot with a number: [{key, count, name}] (name null if it couldn't be told); [] if no panel.
 * names = {key: item name} (config slots, then the session's); cache = {key: [sig, name]}; candidates =
 * item-data ids the slot can be (Use items you have had). ctx.panel remembers where the panel was. */
export function readQuickslot(frame, tmpl, digits, itemdb = null, names = {}, cache = {}, candidates = null, ctx = {}) {
  const panel = findPanel(frame, tmpl, ctx.panel);
  if (!panel) return [];
  ctx.panel = panel;
  const boxes = slotBoxes(panel), s = frame.h / 1080, px = PITCH[0] * s, py = PITCH[1] * s;
  const useIcons = !!(itemdb && itemdb.ready);
  const view = digits.pageView(frame, boxes, px, true);      // colour: the icon's look tells a swapped item
  const origins = digits.slotOrigins(view, boxes, px, py, boxes[0]);
  const readings = digits.readView(view, origins);
  const [ox, oy] = digits.lastOffset;
  const out = [];
  KEYS.forEach((key, i) => {
    const r = readings[i];
    const n = r.text === '0' && r.costs[0] < 0.2 ? 0 : r.value;     // a lone "0" must be a clear one
    if (n == null) return;
    let name = names[key] ?? null, sig = null, changed = false;
    const [u, v] = origins[i];
    const patch = slotPatch(view, u, v);
    if (patch) {
      const ignore = digits.digitMask(r, patch.h, patch.w, -4 - ox, -4 - oy);
      ignore.fill(1, 0, (4 + LABEL_H) * patch.w);                      // the key label is drawn over the icon's top
      sig = keySig(patch, ignore);
      const base = ctx.sigs?.[key];
      if (base && sigDiff(sig, base) > SIG_CHANGE) {                   // a different item is on this key now
        changed = true;
        delete cache[key];
        name = useIcons ? identify(patch, ignore, itemdb, key, cache, potionIds(itemdb, candidates)) : null;
      } else if (name == null && useIcons) name = identify(patch, ignore, itemdb, key, cache, candidates);
    }
    out.push({ key, count: n, name, sig, changed });
  });
  return out;
}

/** The icon's look without the key label and the number: mean colour of each cell of a 6x6 grid, over the
 * pixels not covered. Stays put while the count changes; another item looks different. */
export const SIG_CHANGE = 18;
export function keySig(patch, ignore) {
  const G = 6, out = [];
  for (let gy = 0; gy < G; gy++) for (let gx = 0; gx < G; gx++) {
    const ya = Math.floor(gy * patch.h / G), yb = Math.floor((gy + 1) * patch.h / G), xa = Math.floor(gx * patch.w / G), xb = Math.floor((gx + 1) * patch.w / G);
    const acc = [0, 0, 0]; let n = 0;
    for (let y = ya; y < yb; y++) for (let x = xa; x < xb; x++) {
      const i = y * patch.w + x;
      if (ignore[i]) continue;
      for (let c = 0; c < 3; c++) acc[c] += patch.data[3 * i + c];
      n++;
    }
    out.push(n >= 4 ? acc.map((a) => Math.round(a / n)) : null);
  }
  return out;
}
/** Mean absolute colour difference over the cells both signatures have. */
export function sigDiff(a, b) {
  let s = 0, n = 0;
  for (let i = 0; i < a.length; i++) if (a[i] && b[i]) { for (let c = 0; c < 3; c++) s += Math.abs(a[i][c] - b[i][c]); n += 3; }
  return n ? s / n : 0;
}
/** Item-data ids a swapped-in item is looked for among: potions with a known price, then your Use items. */
function potionIds(itemdb, candidates) {
  const want = new Set(Object.keys(prices(itemdb.extraPrices)));
  const ids = Object.entries(itemdb.items).filter(([, it]) => it.category === 'Use' && want.has(it.name)).map(([id]) => +id);
  return [...new Set([...ids, ...(candidates || [])])];
}

function identify(patch, ignore, itemdb, key, cache, candidates) {
  const sig = resizeArea(patch, 8, 8).data;
  const hit = cache[key];
  if (hit) { let d = 0; for (let i = 0; i < sig.length; i++) d += Math.abs(hit[0][i] - sig[i]); if (d / sig.length < 12) return hit[1]; }
  const ids = candidates && candidates.length ? candidates
    : itemdb.rank(patch, null).filter(([, i]) => itemdb.items[i]?.category === 'Use').slice(0, 20).map(([, i]) => i);
  const ranked = itemdb.rescore(patch, ignore, ids);
  let name = null;
  if (ranked.length && ranked[0][0] <= itemdb.maxScore) {
    const [s0, best] = ranked[0];
    name = itemdb.items[best].name;
    const other = ranked.slice(1).find(([, i]) => itemdb.items[i].name !== name);
    if (other && s0 > 0 && other[0] / s0 < 1.1) name = null;           // two different items fit about equally
  }
  cache[key] = [sig, name];
  return name;
}

/** Name each quick slot from the start inventory: a quick slot's number is that item's inventory total.
 * items = snapshot.items {id: {qty, name}}; only Use items count. Several with that count: the icon guess
 * decides if it is one of them; no exact count: the closest within `near` if only one is that close. */
export function matchByCount(potions, items, itemdb = null, near = 5) {
  const isUse = (id) => !itemdb || !itemdb.ready || itemdb.items[id]?.category === 'Use';
  const pool = Object.entries(items || {}).filter(([id, it]) => !isNaN(+id) && it.name && isUse(id)).map(([, it]) => [it.qty, it.name]);
  const out = {};
  for (const p of potions || []) {
    const same = pool.filter(([n]) => n === p.count).map(([, name]) => name);
    if (same.length === 1) out[p.key] = same[0];
    else if (same.length > 1) { if (same.includes(p.name)) out[p.key] = p.name; }
    else {
      const close = pool.filter(([n]) => Math.abs(n - p.count) <= near).map(([n, name]) => [Math.abs(n - p.count), name]).sort((a, b) => a[0] - b[0] || a[1].localeCompare(b[1]));
      if (close.length && (close.length === 1 || close[1][0] > close[0][0])) out[p.key] = close[0][1];
    }
  }
  return out;
}

/** One line saying what the last quick slot reading found. */
export function describe(potions, table) {
  if (potions == null) return 'Potions: quick slots not found';
  const parts = potions.map((p) => `${p.key} ${p.name || 'unknown item'} ${p.count}${p.name in table ? '' : ' (not counted)'}`);
  return 'Potions: ' + (parts.length ? parts.join(' · ') : 'none on the quick slots');
}

/** A reading outside its two neighbours' range while they agree (within 20%) is a misread. */
function dropMisreads(xs) {
  const out = [...xs];
  for (let i = 1; i < xs.length - 1; i++) {
    const a = out[i - 1], x = xs[i], b = xs[i + 1];
    if (a == null || x == null || b == null) continue;
    if (!(Math.min(a, b) <= x && x <= Math.max(a, b)) && Math.abs(a - b) <= 0.2 * Math.max(a, b, 1)) out[i] = a;
  }
  return out;
}

const activeSec = (t0, t1, pauses) => {
  let s = t1 - t0;
  for (const [a, b] of pauses || []) s -= Math.max(0, Math.min(t1, b ?? t1) - Math.max(t0, a));
  return Math.max(0, s);
};
const r1 = (v) => (v == null ? null : Math.round(v * 10) / 10);

/** Mesos spent on HP and MP potions over a session. start = {time (s), pauses [[s, s|null]]}; rows =
 * [{time (s), potions: [{key, count, name}]}]. Per point: t (active minutes), hp, mp (mesos used so far),
 * used {name: count}, raw_/ema_/cum_ hp|mp in mesos/hr. Same as quickslot.potion_series. */
export function potionSeries(start, rows, table, tauMin = 5, keyNames = {}) {
  rows = rows.filter((r) => r.potions != null)
    .map((r) => ({ ...r, potions: r.potions.map((p) => ({ ...p, name: keyNames[p.key] ?? p.name })) }))
    .sort((a, b) => a.time - b.time);
  if (!rows.length) return [];
  const names = [...new Set(rows.flatMap((r) => r.potions.map((p) => p.name)).filter((n) => n in table))].sort();
  const usedSoFar = {};
  for (const n of names) {
    let last = null;
    const filled = rows.map((r) => { const p = r.potions.find((q) => q.name === n); last = p ? p.count : last; return last; });
    const sm = dropMisreads(filled);
    let total = 0;
    usedSoFar[n] = sm.map((x, i) => { if (i && x != null && sm[i - 1] != null) total += sm[i - 1] - x; return total; });
  }
  const out = [];
  rows.forEach((r, i) => {
    const secs = activeSec(start.time, r.time, start.pauses);
    const used = Object.fromEntries(names.map((n) => [n, usedSoFar[n][i]]));
    const cost = { hp: 0, mp: 0 };
    for (const [n, k] of Object.entries(used)) { const [kind, price] = table[n]; if (kind in cost) cost[kind] += k * price; }
    const p = { t: Math.round(secs / 60 * 100) / 100, hp: cost.hp, mp: cost.mp, used };
    const prev = out.at(-1), dt = prev ? secs - prev.t * 60 : 0;
    for (const kind of ['hp', 'mp']) {
      let raw = null, ema = null, cum = null;
      if (prev && dt > 0) {
        raw = (p[kind] - prev[kind]) / dt * 3600;
        const pe = prev[`ema_${kind}`];
        ema = pe == null ? raw : pe + (1 - Math.exp(-dt / (tauMin * 60))) * (raw - pe);
        cum = p[kind] / secs * 3600;
      } else if (prev) { raw = prev[`raw_${kind}`]; ema = prev[`ema_${kind}`]; cum = prev[`cum_${kind}`]; }
      p[`raw_${kind}`] = r1(raw); p[`ema_${kind}`] = r1(ema); p[`cum_${kind}`] = r1(cum);
    }
    out.push(p);
  });
  return out;
}
