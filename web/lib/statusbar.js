// Level, EXP and the meso total: a port of src/grindcap/statusbar.py.
//
// Level: white digits on orange tiles ("LV. [3][3]") -> white-only picture -> OCR, majority of sizes.
// EXP: "53,791 [97.98%]" right of the "EXP." label -> OCR; every way to split number and percent is
// tried and the one that fits the EXP table is kept (that also checks the level).
// Mesos: the white field under the inventory grid -> OCR, needs groups of 3 digits and 2 sizes agreeing.
import { crop, gray, resizeCubic, otsu, mean, invert, pad, findScaled, mat } from './img.js';
import { ocr } from './ocr.js';
import { ratio } from './mapname.js';
import { EXP_TO_NEXT } from './gamedata.js';

export const pyRound = (x) => {            // Python's round(): halves go to the even neighbour
  const f = Math.floor(x), d = x - f;
  if (Math.abs(d - 0.5) < 1e-9) return f % 2 === 0 ? f : f + 1;
  return Math.round(x);
};

// ------------------------------------------------------------------ level

const isOrange = (r, g, b) => r > 200 && g > 80 && g < 190 && b < 90;

function levelTiles(reg) {
  const spans = []; let start = null;
  for (let x = 0; x <= reg.w; x++) {
    let on = false;
    if (x < reg.w) {
      let n = 0;
      for (let y = 0; y < reg.h; y++) {
        const i = (y * reg.w + x) * 3;
        if (isOrange(reg.data[i], reg.data[i + 1], reg.data[i + 2])) n++;
      }
      on = n > 3;
    }
    if (on && start === null) start = x;
    else if (!on && start !== null) { if (x - start >= 6) spans.push([start, x]); start = null; }
  }
  return spans;
}

function isTile(reg, [a, b]) {
  const w = b - a, rows = [];
  for (let y = 0; y < reg.h; y++) {
    let n = 0;
    for (let x = a; x < b; x++) {
      const i = (y * reg.w + x) * 3;
      if (isOrange(reg.data[i], reg.data[i + 1], reg.data[i + 2])) n++;
    }
    if (n > 2) rows.push(y);
  }
  if (!rows.length) return false;
  const y0 = rows[0], y1 = rows[rows.length - 1], h = y1 - y0 + 1;
  let white = 0, orange = 0;
  for (let y = y0; y <= y1; y++) {
    for (let x = a; x < b; x++) {
      const i = (y * reg.w + x) * 3, r = reg.data[i], g = reg.data[i + 1], bl = reg.data[i + 2];
      if (Math.min(r, g, bl) > 150) white++;
      if (isOrange(r, g, bl)) orange++;
    }
  }
  const n = h * w;
  return h / w >= 0.7 && h / w <= 1.6 && orange / n >= 0.5 && white / n >= 0.05;
}

async function readTiles(reg) {
  const spans = levelTiles(reg).filter((s) => isTile(reg, s));
  if (!spans.length) return null;
  const group = [spans[0]];
  for (const s of spans.slice(1)) {
    if (s[0] - group[group.length - 1][1] <= 6) group.push(s); else break;
  }
  const widths = group.map(([a, b]) => b - a);
  if (group.length > 3 || Math.max(...widths) > 3 * Math.min(...widths) || Math.max(...widths) > 40) return null;
  const a = group[0][0], b = group[group.length - 1][1];
  let sub = crop(reg, a, 0, b - a, reg.h);
  const orows = [];
  for (let y = 0; y < sub.h; y++) {
    let n = 0;
    for (let x = 0; x < sub.w; x++) {
      const i = (y * sub.w + x) * 3;
      if (sub.data[i] > 200 && sub.data[i + 2] < 90) n++;
    }
    if (n > 3) orows.push(y);
  }
  if (orows.length) sub = crop(sub, 0, orows[0], sub.w, orows[orows.length - 1] - orows[0] + 1);
  const white = mat(sub.w, sub.h, 1);
  for (let i = 0; i < sub.w * sub.h; i++) {
    white.data[i] = Math.min(sub.data[3 * i], sub.data[3 * i + 1], sub.data[3 * i + 2]) > 150 ? 255 : 0;
  }
  const votes = new Map(), texts = [];
  for (const sc of [3, 4, 6]) {
    const u = resizeCubic(white, sc);
    const img = pad(invert(u), 30, 30, 30, 30, 255);
    const raw = await ocr(img, 8, '0123456789');
    const t = raw.replace(/\D/g, '');
    texts.push(raw);
    if (t && t.length === group.length) {
      const v = parseInt(t, 10);
      votes.set(v, (votes.get(v) || 0) + 1);
      if (votes.get(v) >= 2) break;
    }
  }
  let v = null, best = 0;
  for (const [k, n] of votes) if (n > best) { best = n; v = k; }
  return v !== null && v >= 1 && v <= 200 ? v : null;
}

/** Where the orange LV tiles are: {x0, x1, y0, y1} in frame pixels, or null. */
export function tilesBox(frame) {
  const H = frame.h, W = frame.w, top = Math.floor(H * 0.93);
  const reg = crop(frame, 0, top, Math.floor(W * 0.4), H - top);
  const spans = levelTiles(reg).filter((s) => isTile(reg, s));
  if (!spans.length) return null;
  const group = [spans[0]];
  for (const sp of spans.slice(1)) { if (sp[0] - group.at(-1)[1] <= 6) group.push(sp); else break; }
  const a = group[0][0], b = group.at(-1)[1];
  let y0 = null, y1 = null;
  for (let y = 0; y < reg.h; y++) {
    let n = 0;
    for (let x = a; x < b; x++) { const i = (y * reg.w + x) * 3; if (isOrange(reg.data[i], reg.data[i + 1], reg.data[i + 2])) n++; }
    if (n > 2) { if (y0 == null) y0 = y; y1 = y; }
  }
  return y0 == null ? null : { x0: a, x1: b, y0: y0 + top, y1: y1 + top };
}

/** Class (job) and character name: the two white lines right of the LV tiles ("Spearman" over the name).
 * Returns {job, name, raw: [line1, line2], box} or null. Several OCR sizes; the job is snapped to the
 * known job names, the name is the reading most sizes agree on. */
export const JOBS = ['Beginner', 'Swordsman', 'Fighter', 'Crusader', 'Hero', 'Page', 'White Knight', 'Paladin', 'Spearman',
  'Dragon Knight', 'Dark Knight', 'Magician', 'Wizard', 'Mage', 'Arch Mage', 'Cleric', 'Priest', 'Bishop',
  'Fire/Poison Wizard', 'Ice/Lightning Wizard', 'Fire/Poison Mage', 'Ice/Lightning Mage', 'Fire/Poison Arch Mage', 'Ice/Lightning Arch Mage',
  'Archer', 'Hunter', 'Ranger', 'Bowmaster', 'Crossbowman', 'Sniper', 'Marksman', 'Rogue', 'Assassin', 'Hermit', 'Night Lord',
  'Bandit', 'Chief Bandit', 'Shadower', 'Pirate', 'Brawler', 'Marauder', 'Buccaneer', 'Gunslinger', 'Outlaw', 'Corsair'];
export async function readCharacter(frame, known = []) {
  const t = tilesBox(frame);
  if (!t) return null;
  const th = t.y1 - t.y0 + 1, s = th / 17;                       // tiles are ~17 px tall at 1920x1080
  const x = t.x1 + Math.round(14 * s), w = Math.min(frame.w - x, Math.round(176 * s));
  const mid = Math.round((t.y0 + t.y1) / 2), lh = Math.round(19 * s);
  const lines = [[mid - lh - Math.round(1 * s), lh + Math.round(2 * s)], [mid - Math.round(1 * s), lh + Math.round(3 * s)]];
  const raw = [];
  for (const [y, h] of lines) {
    const c = crop(frame, x, Math.max(0, y), w, Math.min(h, frame.h - y));
    // the text is thin white strokes on a dark gradient: the grey picture, and a soft threshold
    const g = gray(c), votes = new Map();
    const thr = mat(g.w, g.h, 1, g.data.map((v) => (v > 110 ? 255 : 0)));
    for (const [img, k] of [[g, 3], [g, 4], [g, 5], [g, 6], [thr, 3], [thr, 4], [thr, 5]]) {
      const u = resizeCubic(img, k);
      for (let i = 0; i < u.data.length; i++) u.data[i] = Math.max(0, Math.min(255, u.data[i]));
      const txt = (await ocr(pad(invert(u), 20, 20, 20, 20, 255), 7, '')).trim().replace(/\s+/g, ' ');
      if (txt) votes.set(txt, (votes.get(txt) || 0) + 1);
    }
    raw.push(votes);
  }
  // job: the reading closest to a job name; name: letters and digits only, the most common length,
  // then a majority per letter (each size misreads a different letter)
  let job = null, jr = 0;
  for (const t of raw[0].keys()) for (const j of JOBS) { const r = ratio(t.replace(/[^A-Za-z/ ]/g, '').trim().toLowerCase(), j.toLowerCase()); if (r > jr) { jr = r; job = j; } }
  if (jr < 0.75) job = null;
  const names = [];
  for (const [t, n] of raw[1]) for (let i = 0; i < n; i++) names.push(t.replace(/[^A-Za-z0-9]/g, ''));
  const lens = new Map();
  for (const t of names) if (t.length >= 2) lens.set(t.length, (lens.get(t.length) || 0) + 1);
  const L = [...lens.entries()].sort((a, b) => b[1] - a[1] || b[0] - a[0])[0]?.[0];
  let name = null;
  if (L) {
    const same = names.filter((t) => t.length === L);
    name = [...Array(L).keys()].map((i) => {
      const c = new Map(); for (const t of same) c.set(t[i], (c.get(t[i]) || 0) + 1);
      return [...c.entries()].sort((a, b) => b[1] - a[1])[0][0];
    }).join('');
    for (const k of known) if (ratio(name.toLowerCase(), k.toLowerCase()) >= 0.8) { name = k; break; }   // a character seen before
  }
  return { job, name, raw: raw.map((v) => [...v.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] || ''), box: [t.x0, mid - lh - 2, x + w - t.x0, 2 * lh + 6] };
}

/** Level from the orange tiles in the bottom-left of the window. */
export async function readLevel(frame) {
  const H = frame.h, W = frame.w;
  const y0 = Math.floor(H * 0.93);
  return readTiles(crop(frame, 0, y0, Math.floor(W * 0.4), H - y0));
}

// ------------------------------------------------------------------ EXP

export const BASE_SCALE = 1920 / 1366;   // the templates were cut from a 1366x768 game shown at 1920x1080

/** Where "53,791 [97.98%]" is: right of the "EXP." label. `gameScale` = screen px per game px
 * (null: searched). Returns {box, gameScale, score} or null. */
export function expTextBox(frame, label, gameScale = null) {
  const H = frame.h;
  const y0 = Math.floor(H * 0.9);
  const scales = gameScale ? [gameScale / BASE_SCALE] : scaleRange();
  const f = findScaled(frame, label, scales, [0, y0, frame.w, H - y0], gameScale ? 2 : 3);
  if (!f || f.score < 0.8) return null;
  const s = f.scale;
  return { box: [f.x + f.w + Math.trunc(2 * s), f.y - Math.trunc(2 * s), Math.trunc(140 * s), f.h + Math.trunc(4 * s)],
           gameScale: s * BASE_SCALE, score: f.score };
}

/** Template scale factors to try when the game's stretch isn't known yet. */
export function scaleRange() {
  const out = [];
  for (let s = 0.5; s <= 1.45; s += 0.02) out.push(+s.toFixed(3));
  return out;
}

/** OCR of the EXP text box at a few sizes; stops at the first reading good() accepts. */
export async function readExpTexts(frame, box, good = null) {
  const [x, y, w, h] = box;
  const g = gray(crop(frame, x, y, w, h));
  const out = [];
  const base = Math.max(3, pyRound(60 / Math.max(1, g.h)));
  for (const f of [base, base + 1, base - 1, base + 2]) {
    let th = otsu(resizeCubic(g, f));
    if (mean(th) < 127) th = invert(th);
    th = pad(th, 10, 10, 10, 10, 255);
    out.push(await ocr(th, 7, '0123456789,.[]%'));
    if (good && good(out[out.length - 1])) break;
  }
  return out;
}

function fits(exp, pct, level) {
  const need = EXP_TO_NEXT[level];
  if (!need || exp >= need) return false;
  return Math.abs(exp / need * 100 - pct) <= 0.0051;
}

/** Every (exp, percent) the OCR text could mean. */
export function expSplits(text) {
  const t = text.replace(/ /g, '');
  const out = [], seen = new Set();
  const re = /(\d{1,3})\.(\d{2})%/g;
  let m;
  while ((m = re.exec(t))) {
    const s1 = m.index, e1 = m.index + m[1].length;
    for (let k = 1; k <= e1 - s1; k++) {
      const pct = parseFloat(t.slice(e1 - k, e1) + '.' + m[2]);
      if (pct > 100) continue;
      const head = t.slice(0, e1 - k);
      for (const drop of [1, 0]) {
        const h = drop ? head.slice(0, -1) : head;
        const digits = h.replace(/\D/g, '');
        if (digits) {
          const key = `${parseInt(digits, 10)}|${pct}`;
          if (!seen.has(key)) { seen.add(key); out.push([parseInt(digits, 10), pct]); }
        }
      }
    }
  }
  return out;
}

export function resolve(text, levelRead, prior = null, up = 5) {
  const splits = expSplits(text);
  if (levelRead != null) {
    const fit = splits.filter(([e, p]) => fits(e, p, levelRead));
    if (fit.length) {
      fit.sort((a, b) => b[0] - a[0] || b[1] - a[1]);
      const [e, p] = fit[0];
      return { exp: e, pct: p, level: levelRead, checked: true, level_ocr: levelRead, level_fixed: false, level_options: [] };
    }
  }
  let levels = Object.keys(EXP_TO_NEXT).map(Number);
  if (prior) levels = levels.filter((lv) => prior <= lv && lv <= prior + up);
  const target = levels.includes(levelRead) ? levelRead : (prior || levelRead);
  let best = null;
  for (const [exp, pct] of splits) {
    for (const lv of levels) {
      if (!fits(exp, pct, lv)) continue;
      const key = [target ? Math.abs(lv - target) : 0, levelRead === lv ? 0 : 1, -exp];
      if (!best || cmp(key, best[0]) < 0) best = [key, exp, pct, lv];
    }
  }
  if (!best) {
    const lv = (!prior || levels.includes(levelRead)) ? levelRead : prior;
    return { exp: splits.length ? splits[0][0] : null, pct: splits.length ? splits[0][1] : null, level: lv,
             checked: false, level_ocr: levelRead };
  }
  const [, exp, pct, lv] = best;
  const options = levels.filter((x) => fits(exp, pct, x));
  return { exp, pct, level: lv, checked: true, level_ocr: levelRead,
           level_fixed: levelRead != null && lv !== levelRead,
           level_options: options.length > 1 && !options.includes(levelRead) ? options : [] };
}

const cmp = (a, b) => { for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] - b[i]; return 0; };

export function resolveMany(texts, levelRead, prior = null, up = 5) {
  const rs = texts.map((t) => resolve(t, levelRead, prior, up));
  const ok = rs.filter((r) => r.checked);
  if (!ok.length) return rs[0] || { exp: null, pct: null, level: levelRead, checked: false };
  const c = new Map();
  for (const r of ok) { const k = `${r.exp}|${r.level}`; c.set(k, (c.get(k) || 0) + 1); }
  let top = null, n = 0;
  for (const [k, v] of c) if (v > n) { n = v; top = k; }
  return { ...ok.find((r) => `${r.exp}|${r.level}` === top), texts };
}

/** Level + EXP from one frame, cross-checked. `ctx` keeps the EXP label template and the scale. */
export async function readStatus(frame, ctx, prior = null) {
  const out = { level: null, exp: null, pct: null, checked: false, texts: [] };
  const level = await readLevel(frame);
  out.level_ocr = level;
  const where = expTextBox(frame, ctx.expLabel, ctx.gameScale);
  if (!where && ctx.gameScale) {   // the window was resized: search all scales again
    ctx.gameScale = null;
    return readStatus(frame, ctx, prior);
  }
  if (!where) { out.why = 'EXP label not found on the status bar'; out.level = level; return out; }
  ctx.gameScale = where.gameScale;
  out.expBox = where.box;
  const up = 5;
  const texts = await readExpTexts(frame, where.box,
    (t) => level != null && resolve(t, level, prior, up).checked);
  out.texts = texts;
  const r = resolveMany(texts, level, prior, up);
  out.exp = r.exp; out.pct = r.pct; out.checked = !!r.checked;
  out.level = r.checked && r.level != null ? r.level : level;
  out.level_options = r.level_options || [];
  return out;
}

// ------------------------------------------------------------------ mesos

function longestRun(mask) {
  let best = [0, 0], start = null;
  for (let i = 0; i <= mask.length; i++) {
    const m = i < mask.length && mask[i];
    if (m && start === null) start = i;
    else if (!m && start !== null) { if (i - start > best[1] - best[0]) best = [start, i]; start = null; }
  }
  return best;
}

const MESO_TEXT = /^\d{1,3}([.,]\d{3})*$/;

export function mesoFieldBox(grid) {
  const [px, py] = grid.pitch();
  const x0 = grid.first[0], ly = grid.last[1];
  const xa = Math.trunc(x0 + 0.1 * px), ya = Math.trunc(ly + 1.0 * py);
  const xb = Math.trunc(x0 + 4.6 * px), yb = Math.trunc(ly + 2.0 * py);
  return [xa, ya, xb - xa, yb - ya];
}

/** The meso total in the white field under the inventory grid: {value, raw}. */
export async function readMesosField(frame, grid) {
  const [, py] = grid.pitch(), [px] = grid.pitch();
  const [xa, ya, w, h] = mesoFieldBox(grid);
  const reg = crop(frame, xa, ya, w, h);
  if (!reg.w || !reg.h) return { value: null, raw: 'field outside the picture' };
  const g = gray(reg);
  const white = (x, y) => g.data[y * g.w + x] > 235;
  const rowOn = [];
  for (let y = 0; y < g.h; y++) { let n = 0; for (let x = 0; x < g.w; x++) n += white(x, y); rowOn.push(n / g.w > 0.5); }
  const [r0, r1] = longestRun(rowOn);
  const cols = [];
  if (r1 > r0) {
    for (let x = 0; x < g.w; x++) {
      let n = 0;
      for (let y = r0; y < r1; y++) n += white(x, y);
      if (n / (r1 - r0) > 0.5) cols.push(x);
    }
  }
  if (r1 - r0 < 0.15 * py || cols.length < 0.8 * px) return { value: null, raw: 'meso field not visible (covered?)' };
  const fld = crop(g, cols[0], r0, cols[cols.length - 1] - cols[0] + 1, r1 - r0);
  const votes = new Map(), texts = [];
  for (const k of [4, 3, 5]) {
    const th = pad(otsu(resizeCubic(fld, k)), 12, 12, 12, 12, 255);
    const t = (await ocr(th, 7, '0123456789,.')).replace(/ /g, '');
    texts.push(t);
    if (MESO_TEXT.test(t)) {
      const v = parseInt(t.replace(/\D/g, ''), 10);
      votes.set(v, (votes.get(v) || 0) + 1);
      if (votes.get(v) >= 2) return { value: v, raw: texts.join(' | '), box: [xa, ya, w, h] };
    }
  }
  return { value: null, raw: texts.join(' | '), box: [xa, ya, w, h] };
}
