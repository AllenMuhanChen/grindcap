// The inventory window: find it, split it into slots, read each slot. Port of src/grindcap/inventory.py,
// except that the window is found by its "ITEM INVENTORY" title (no calibration) and items are keyed
// by their item-data id directly.
import { crop, gray, resizeArea, findScaled, matchCCoeff, toImageData } from './img.js';
import { slotPatch } from './digits.js';
import { BASE_SCALE, scaleRange } from './statusbar.js';

export const TABS = ['Equip', 'Use', 'Setup', 'Etc', 'Cash', 'Deco'];
export const UNKNOWN = '?';
const COLS = 5, ROWS = 6;
const QTY_BOX = [0.0, 0.62, 0.75, 0.38];
// Measured on the five test screenshots: first slot = title position + (3, 63) px, slots 44 px,
// all at 1920x1080 for a 1366x768 game (BASE_SCALE). Scaled with the game's stretch.
const TITLE_TO_SLOT = [3, 63], SLOT = 44;
const PITCH = [36, 34];   // native px between slot columns / rows (rows are closer together)

export class Grid {
  constructor(first, last, cols = COLS, rows = ROWS) { Object.assign(this, { first, last, cols, rows }); }
  pitch() {
    return [(this.last[0] - this.first[0]) / Math.max(1, this.cols - 1), (this.last[1] - this.first[1]) / Math.max(1, this.rows - 1)];
  }
  slotBoxes() {
    const [x0, y0, w, h] = this.first, [px, py] = this.pitch();
    return Array.from({ length: this.rows }, (_, r) => Array.from({ length: this.cols }, (_, c) =>
      [Math.round(x0 + c * px), Math.round(y0 + r * py), w, h]));
  }
}

/** Find the inventory window. `ctx` remembers the scale and last place, so later frames are fast.
 * Returns {grid, score} or null if the inventory isn't open. */
export function locateInventory(frame, title, ctx) {
  let f = null;
  const k0 = ctx.gameScale ? ctx.gameScale / BASE_SCALE : null;
  if (ctx.invAt && k0) {   // near where it was last time
    const tw = Math.round(title.w * k0), th = Math.round(title.h * k0);
    const t = Math.abs(k0 - 1) < 1e-3 ? gray(title) : resizeArea(gray(title), tw, th);
    const [ax, ay] = ctx.invAt, g = gray(crop(frame, ax - 40, ay - 40, tw + 80, th + 80));
    const r = matchCCoeff(g, t);
    if (r.score >= 0.75) f = { x: Math.max(0, ax - 40) + r.x, y: Math.max(0, ay - 40) + r.y, score: r.score, scale: k0 };
  }
  if (!f) {
    const r = findScaled(frame, title, k0 ? [k0] : scaleRange(), null, k0 ? 2 : 3);
    if (r && r.score >= 0.75) f = r;
  }
  if (!f) { ctx.invAt = null; return null; }
  ctx.invAt = [f.x, f.y];
  ctx.gameScale = f.scale * BASE_SCALE;
  const k = f.scale, [pu, pv] = PITCH.map((p) => p * ctx.gameScale);
  const first = [Math.round(f.x + TITLE_TO_SLOT[0] * k), Math.round(f.y + TITLE_TO_SLOT[1] * k), Math.round(SLOT * k), Math.round(SLOT * k)];
  const last = [Math.round(first[0] + (COLS - 1) * pu), Math.round(first[1] + (ROWS - 1) * pv), first[2], first[3]];
  return { grid: new Grid(first, last), score: f.score };
}

function qtyMask(h, w) {
  const m = new Uint8Array(w * h).fill(1);
  const [fx, fy, fw, fh] = QTY_BOX;
  for (let y = Math.trunc(fy * h); y < Math.trunc((fy + fh) * h); y++)
    for (let x = Math.trunc(fx * w); x < Math.trunc((fx + fw) * w); x++) m[y * w + x] = 0;
  return m;
}

const tooltipPx = (r, g, b) => { const blue = b - (r + g) / 2; return blue > 25 && blue < 75 && Math.abs(r - g) < 15 && r > 10 && r < 115; };

/** True if an item tooltip (dark see-through navy) covers this slot. */
export function isCovered(img, frac = 0.15) {
  let n = 0;
  for (let i = 0; i < img.w * img.h; i++) n += tooltipPx(img.data[3 * i], img.data[3 * i + 1], img.data[3 * i + 2]);
  return n / (img.w * img.h) > frac;
}

/** (row, col) of slots a tooltip covers even a little: tooltip colour in solid 6x6 patches. */
/** The game's mouse pointer (a white glove) over the item grid, or null. cursors = web/data/cursors.json
 * (screen-pixel templates at scale cursors.scale). Masked normalised correlation on grey, step 2 then
 * refined; >= 0.8 counts (test screenshots without a pointer: <= 0.64; the pointer: 1.0). */
export function findCursor(frame, grid, cursors, gameScale = null, thresh = 0.8) {
  if (!cursors) return null;
  const k = (gameScale || BASE_SCALE) / cursors.scale;
  const b = grid.slotBoxes(), [x0, y0] = b[0][0], l = b[b.length - 1][b[0].length - 1];
  let best = null;
  for (const c of cursors.cursors) {
    const t = prepCursor(c, k);
    const X0 = Math.max(0, Math.round(x0 - t.w)), Y0 = Math.max(0, Math.round(y0 - t.h));
    const X1 = Math.min(frame.w - t.w, Math.round(l[0] + l[2])), Y1 = Math.min(frame.h - t.h, Math.round(l[1] + l[3]));
    if (X1 <= X0 || Y1 <= Y0) continue;
    const g = gray(crop(frame, X0, Y0, X1 - X0 + t.w, Y1 - Y0 + t.h));
    const at = (x, y) => {
      let si = 0, si2 = 0, sit = 0;
      for (let i = 0; i < t.idx.length; i++) {
        const v = g.data[(y + t.dy[i]) * g.w + x + t.dx[i]];
        si += v; si2 += v * v; sit += v * t.tv[i];
      }
      const n = t.idx.length, vi = si2 - (si * si) / n;
      return vi > 1e-6 ? sit / Math.sqrt(vi * t.tt) : 0;
    };
    let bs = -1, bx = 0, by = 0;
    for (let y = 0; y <= Y1 - Y0; y += 2) for (let x = 0; x <= X1 - X0; x += 2) { const v = at(x, y); if (v > bs) { bs = v; bx = x; by = y; } }
    for (let y = Math.max(0, by - 2); y <= Math.min(Y1 - Y0, by + 2); y++) for (let x = Math.max(0, bx - 2); x <= Math.min(X1 - X0, bx + 2); x++) {
      const v = at(x, y); if (v > bs) { bs = v; bx = x; by = y; }
    }
    if (!best || bs > best.score) best = { name: c.name, score: bs, x: X0 + bx, y: Y0 + by };
  }
  return best && best.score >= thresh ? best : null;
}
const cursorCache = new Map();
function prepCursor(c, k) {
  const key = `${c.name}:${k.toFixed(3)}`;
  if (cursorCache.has(key)) return cursorCache.get(key);
  let grey = { w: c.w, h: c.h, c: 1, data: Float32Array.from(c.grey) }, mask = { w: c.w, h: c.h, c: 1, data: Float32Array.from(c.mask) };
  if (Math.abs(k - 1) > 0.02) {
    const w = Math.max(4, Math.round(c.w * k)), h = Math.max(4, Math.round(c.h * k));
    grey = resizeArea(grey, w, h); mask = resizeArea(mask, w, h);
  }
  const idx = [], dx = [], dy = [], vals = [];
  for (let y = 0; y < grey.h; y++) for (let x = 0; x < grey.w; x++) if (mask.data[y * grey.w + x] > 0.5) { idx.push(idx.length); dx.push(x); dy.push(y); vals.push(grey.data[y * grey.w + x]); }
  const m = vals.reduce((a, v) => a + v, 0) / vals.length, tv = vals.map((v) => v - m);
  const t = { w: grey.w, h: grey.h, idx, dx, dy, tv, tt: tv.reduce((a, v) => a + v * v, 0) };
  cursorCache.set(key, t);
  return t;
}

export function coveredSlots(frame, grid, frac = 0.04) {
  const out = [];
  grid.slotBoxes().forEach((row, r) => row.forEach(([x, y, w, h], c) => {
    let img = crop(frame, x, y, w, h);
    if (!img.w || !img.h) return;
    // the 6x6 patch size is in 1920x1080 pixels (44 px slots): bigger screens are brought down to that first
    if (img.w > 48) img = resizeArea(img, Math.round(img.w * 44 / w), Math.round(img.h * 44 / w));
    const W = img.w, H = img.h, m = new Uint8Array(W * H);
    for (let i = 0; i < W * H; i++) m[i] = tooltipPx(img.data[3 * i], img.data[3 * i + 1], img.data[3 * i + 2]);
    // opening with a 6x6 kernel (anchor 3,3): erode, then dilate
    const er = new Uint8Array(W * H), op = new Uint8Array(W * H);
    for (let yy = 0; yy < H; yy++) for (let xx = 0; xx < W; xx++) {
      let on = 1;
      for (let j = -3; j <= 2 && on; j++) for (let i = -3; i <= 2; i++) {
        const a = yy + j, b = xx + i;
        if (a >= 0 && a < H && b >= 0 && b < W && !m[a * W + b]) { on = 0; break; }
      }
      er[yy * W + xx] = on;
    }
    let s = 0;
    for (let yy = 0; yy < H; yy++) for (let xx = 0; xx < W; xx++) {
      let on = 0;
      for (let j = -2; j <= 3 && !on; j++) for (let i = -2; i <= 3; i++) {
        const a = yy + j, b = xx + i;
        if (a >= 0 && a < H && b >= 0 && b < W && er[a * W + b]) { on = 1; break; }
      }
      op[yy * W + xx] = on; s += on;
    }
    if (s / (W * H) > frac) out.push([r, c]);
  }));
  return out;
}

/** A slot is empty when the middle of its icon area is flat (grey std below stdMax). */
export function isEmpty(img, stdMax = 6) {
  const g = gray(img), h = g.h, w = g.w, m = qtyMask(h, w);
  const vals = [];
  for (let y = Math.trunc(0.15 * h); y < h - Math.trunc(0.15 * h); y++)
    for (let x = Math.trunc(0.15 * w); x < w - Math.trunc(0.15 * w); x++)
      if (m[y * w + x]) vals.push(g.data[y * w + x]);
  if (!vals.length) return true;
  const mu = vals.reduce((a, b) => a + b, 0) / vals.length;
  const sd = Math.sqrt(vals.reduce((a, b) => a + (b - mu) ** 2, 0) / vals.length);
  return sd < stdMax;
}

/** Which tab is open: the active tab button above the grid is pink-red. */
export function detectTab(frame, grid) {
  const [px, py] = grid.pitch(), [x0, y0] = grid.first;
  const ya = Math.trunc(y0 - 0.75 * py), yb = Math.trunc(y0 - 0.15 * py);
  const xa = Math.trunc(x0 - 0.3 * px), xb = Math.trunc(x0 + 5.6 * px);
  const band = crop(frame, xa, ya, xb - xa, yb - ya);
  if (!band.w || !band.h) return null;
  const red = (x, y) => { const i = (y * band.w + x) * 3, r = band.data[i], g = band.data[i + 1], b = band.data[i + 2]; return r > 180 && r - g > 60 && r - b > 40; };
  const blocks = []; let start = null;
  for (let x = 0; x <= band.w; x++) {
    let on = false;
    if (x < band.w) { let n = 0; for (let y = 0; y < band.h; y++) n += red(x, y); on = n > Math.max(5, Math.floor(band.h / 5)); }
    if (on && start === null) start = x;
    else if (!on && start !== null) {
      if (x - start >= 0.4 * px) { let s = 0; for (let xx = start; xx < x; xx++) for (let y = 0; y < band.h; y++) s += red(xx, y); blocks.push([s, start, x]); }
      start = null;
    }
  }
  if (!blocks.length) return null;
  blocks.sort((a, b) => b[0] - a[0] || b[1] - a[1]);
  const [, a, z] = blocks[0];
  const cx = (a + z - 1) / 2 + Math.max(0, xa);
  const i = Math.round(((cx - x0) / px - 0.385) / 0.9);
  return i >= 0 && i < TABS.length ? TABS[i] : null;
}

/** The tab from what's in the page: named items carry their category. 2+ items, 70% agreeing. */
export function tabFromItems(page, itemdb) {
  const votes = new Map();
  for (const row of page) for (const s of row) {
    const cat = s.id && s.id !== UNKNOWN && itemdb.items[s.id] ? itemdb.items[s.id].category : null;
    if (cat) votes.set(cat, (votes.get(cat) || 0) + 1);
  }
  let tab = null, n = 0, tot = 0;
  for (const [k, v] of votes) { tot += v; if (v > n) { n = v; tab = k; } }
  return tab && n >= 2 && n >= 0.7 * tot ? tab : null;
}

/** Which tab a page is. Items decide (a flashing tab can fool the button colour), except when the
 * button says Cash or Deco: cash items aren't in the item data, so a few of them look like Equip or
 * Etc items by accident. Then the items only win if 70% of all filled slots agree on one tab. */
export function pageTab(page, itemdb, button) {
  const fromItems = tabFromItems(page, itemdb);
  if (!button || !['Cash', 'Deco'].includes(button) || !fromItems) return fromItems || button;
  let filled = 0, agree = 0;
  for (const row of page) for (const s of row) {
    if (s.id == null && !s.ignored) continue;
    filled++;
    if (s.id !== UNKNOWN && itemdb.items[s.id] && itemdb.items[s.id].category === fromItems) agree++;
  }
  return agree >= 0.7 * filled ? fromItems : button;
}

/** Small colour picture of a slot's icon (stack-number area blanked), to recognise it again quickly. */
function signature(img) {
  const m = qtyMask(img.h, img.w), c = { ...img, data: Float32Array.from(img.data) };
  for (let i = 0; i < m.length; i++) if (!m[i]) c.data[3 * i] = c.data[3 * i + 1] = c.data[3 * i + 2] = 0;
  return resizeArea(c, 24, 24).data;
}

/** Remembers which item each icon look turned out to be, so each look is searched only once. */
export class LookCache {
  constructor(threshold = 6) {
    this.looks = []; this.threshold = threshold;
    this.prefix = Math.random().toString(36).slice(2, 6);   // keys stay unique across page reloads
  }
  /** Looks within the threshold, closest first. */
  near(sig) {
    const out = [];
    for (const l of this.looks) {
      const d = this.dist(sig, l);
      if (d <= this.threshold) out.push([d, l]);
    }
    return out.sort((a, b) => a[0] - b[0]).map((x) => x[1]);
  }
  dist(sig, l) { let d = 0; for (let i = 0; i < sig.length; i++) d += Math.abs(sig[i] - l.sig[i]); return d / sig.length; }
  /** match = what the item data said about this look (best guess, runner-up, ratio, candidates). */
  add(sig, id, name, neighbors = [], match = null, crop = null) {
    const l = { key: `${this.prefix}-${this.looks.length + 1}`, sig, id, name, neighbors, match, crop };
    this.looks.push(l);
    return l;
  }
}

/** A slot as a small PNG data URL, for the review panel. */
export function slotPicture(img) {
  if (typeof document === 'undefined') return null;
  const cv = document.createElement('canvas');
  cv.width = img.w; cv.height = img.h;
  cv.getContext('2d').putImageData(toImageData(img), 0, 0);
  return cv.toDataURL('image/png');
}

/** One picture of the visible grid -> rows of {id, qty, name, ref}. id = item-data id, a
 * "look-N" id for an icon the item data doesn't name, UNKNOWN under a tooltip, null if empty. */
export async function readPage(frame, grid, digits, itemdb, cache, pageKey = '', yieldEvery = 4) {
  const rows = grid.slotBoxes(), flat = rows.flat(), [px, py] = grid.pitch();
  const view = digits.pageView(frame, flat, px, true);
  const origins = digits.slotOrigins(view, flat, px, py, flat[0]);
  const numbers = digits.readView(view, origins);
  const out = [];
  let i = 0;
  for (let r = 0; r < rows.length; r++) {
    const line = [];
    for (let c = 0; c < rows[r].length; c++) {
      const [x, y, w, h] = rows[r][c], img = crop(frame, x, y, w, h), num = numbers[i], [u, v] = origins[i];
      const ref = `${pageKey}:r${r + 1}c${c + 1}`;
      i++;
      if (!img.w || !img.h) { line.push({ id: null, qty: 0, ref }); continue; }
      if (isCovered(img)) { line.push({ id: UNKNOWN, qty: 0, ref }); continue; }
      if (isEmpty(img)) { line.push({ id: null, qty: 0, ref }); continue; }
      const sig = signature(img);
      const patch = itemdb && itemdb.ready ? slotPatch(view, u, v) : null;
      const near = cache.near(sig);
      // A look you named yourself wins when it is clearly the same icon (the item data's icon may be
      // why it wasn't recognised); a merely similar one (another ore colour) still goes through the re-check.
      let look = near.length && near[0].match && near[0].match.corrected && cache.dist(sig, near[0]) <= cache.threshold / 2 ? near[0] : null;
      if (!look && near.length) {
        // Seen a look like this before. Look-alikes (ores that differ only in colour) can be within
        // the threshold too, so the named ones and their neighbours are re-checked on this slot.
        const named = near.filter((l) => typeof l.id === 'number');
        if (patch && named.length) {
          const ids = [...new Set(named.flatMap((l) => [l.id, ...l.neighbors]))];
          const sc = itemdb.scores(patch, ids);
          let best = null, bs = Infinity;
          for (const [id, v] of sc) if (v < bs) { bs = v; best = id; }
          if (best !== null && bs <= itemdb.maxScore) {
            look = named.find((l) => l.id === best);
            if (!look) look = cache.add(sig, best, itemdb.name(best), [], { rechecked: true, score: Math.round(bs) }, slotPicture(img));
          }
        }
        if (!look) look = near.find((l) => typeof l.id !== 'number') || (patch ? null : near[0]);
      }
      if (!look) {
        let m = null;
        if (patch) {
          let ignore = null;
          if (num.text) {
            const [ox, oy] = digits.lastOffset;
            ignore = digits.digitMask(num, patch.h, patch.w, -4 - ox, -4 - oy);
          }
          m = itemdb.identify(patch, ignore);
          if (i % yieldEvery === 0) await new Promise((res) => setTimeout(res));
        }
        const pic = slotPicture(img);
        look = m && m.id ? cache.add(sig, m.id, m.name, m.neighbors, m, pic)
                         : cache.add(sig, `look-${cache.looks.length + 1}`, m && m.bestName ? `? (looks like ${m.bestName})` : '?', [], m, pic);
      }
      if (look.id === 'ignore') { line.push({ id: null, qty: 0, ref, look: look.key, ignored: true }); continue; }
      line.push({ id: look.id, qty: num.value || 1, name: look.name, ref, text: num.text, look: look.key, crop: slotPicture(img) });
    }
    out.push(line);
  }
  return out;
}

// ---------------------------------------------------------------- stitching scrolled pages

function rowsAgree(a, b) {
  let compared = 0, mismatched = 0;
  for (let r = 0; r < Math.min(a.length, b.length); r++) {
    for (let c = 0; c < Math.min(a[r].length, b[r].length); c++) {
      const sa = a[r][c], sb = b[r][c];
      if (sa.id === UNKNOWN || sb.id === UNKNOWN) continue;
      if (sa.id || sb.id) {
        compared++;
        if (sa.id !== sb.id || (sa.qty !== sb.qty && sa.qty && sb.qty)) mismatched++;
      }
    }
  }
  return compared > 0 && mismatched <= Math.floor(compared / 5);
}

function find(merged, page) {
  for (let i = 0; i + page.length <= merged.length; i++) if (rowsAgree(merged.slice(i, i + page.length), page)) return i;
  return null;
}

function fill(mr, pr) {
  for (let r = 0; r < Math.min(mr.length, pr.length); r++)
    for (let c = 0; c < mr[r].length; c++) if (mr[r][c].id === UNKNOWN && pr[r][c].id !== UNKNOWN) mr[r][c] = pr[r][c];
}

/** Stitch the pages of one tab, counting every row once (see inventory.merge_pages). */
export function mergePages(pages, log = []) {
  const merged = [];
  pages.forEach((page, n) => {
    const at = merged.length ? find(merged, page) : null;
    if (at !== null) { fill(merged.slice(at, at + page.length), page); log.push(`page ${n + 1}: already seen, skipped`); return; }
    let best = 0;
    for (let k = Math.min(merged.length, page.length); k > 0; k--) if (rowsAgree(merged.slice(-k), page.slice(0, k))) { best = k; break; }
    if (best) fill(merged.slice(-best), page.slice(0, best));
    for (const row of page.slice(best)) merged.push([...row]);
    log.push(`page ${n + 1}: ` + (best ? `overlaps ${best} rows, added ${page.length - best}` : `no overlap, added all ${page.length} rows`));
  });
  return merged;
}

export function totals(tabs) {
  const out = {};
  for (const rows of Object.values(tabs)) for (const row of rows) for (const s of row)
    if (s.id && s.id !== UNKNOWN) out[s.id] = { qty: (out[s.id]?.qty || 0) + s.qty, name: s.name };
  return out;
}

/** Decides when to capture a page: the grid changed, then held still for `stable` frames, and this
 * view wasn't captured before. */
export class PageWatcher {
  constructor(stable = 2, diff = 4) { Object.assign(this, { stable, diff, last: null, count: 0, captured: [], rejected: [] }); }
  static signature(frame, grid) {
    const b = grid.slotBoxes(), [x0, y0] = b[0][0], l = b[b.length - 1][b[0].length - 1];
    const c = crop(frame, x0, y0, l[0] + l[2] - x0, l[1] + l[3] - y0);
    return c.w && c.h ? resizeArea(gray(c), 48, 72).data : null;
  }
  same(a, b) { if (!a || !b) return false; let d = 0; for (let i = 0; i < a.length; i++) d += Math.abs(a[i] - b[i]); return d / a.length < this.diff; }
  feed(sig) {
    if (!sig) { this.last = null; this.count = 0; return false; }
    if (this.same(sig, this.last)) this.count++; else { this.last = sig; this.count = 1; }
    const near = (a, b, t) => { let d = 0; for (let i = 0; i < a.length; i++) d += Math.abs(a[i] - b[i]); return d / a.length < t; };
    if (this.count >= this.stable && !this.captured.some((c) => this.same(sig, c)) && !this.rejected.some((r) => near(sig, r, 1))) {
      this.captured.push(sig); return true;
    }
    return false;
  }
  rejectLast() { if (this.captured.length) this.rejected.push(this.captured.pop()); }
}
