// The current map's name from the minimap window. Port of src/grindcap/mapname.py: find the "MINI MAP"
// title bar (web/data/minimap_header.png, 1920x1080, scaled by frame height), read the street and map
// lines with Tesseract (plain + white-letters-only variants), keep the pair closest to a real Classic
// World map name (maps from web/local/maps.json) and snap to it.
import { crop, gray, mat, resizeCubic, pad, findScaled } from './img.js';
import { ocr } from './ocr.js';

const TEXT_X = 64, LINE1 = [30, 50], LINE2 = [50, 72], MIN_SCORE = 0.8;

/** {x, y, s} of the minimap title bar, or null if the minimap isn't on screen. */
export function findHeader(frame, header) {
  const s = frame.h / 1080;
  const region = [0, 0, frame.w, Math.max(Math.round(header.h * s) + 1, Math.floor(frame.h * 3 / 4))];
  const f = findScaled(frame, header, [s], region, 2);
  return f && f.score >= MIN_SCORE ? { x: f.x, y: f.y, s } : null;
}

/** Where the minimap's plain title band ends (its width depends on the map). */
function rightEdge(frame, x0, y, maxW) {
  const at = (x) => { const i = (y * frame.w + x) * 3; return [frame.data[i], frame.data[i + 1], frame.data[i + 2]]; };
  const n = Math.max(0, Math.min(maxW, frame.w - x0));
  const bg = [0, 1, 2].map((c) => [0, 1, 2, 3].reduce((a, k) => a + at(x0 + k)[c], 0) / 4);
  const off = [];
  for (let i = 0; i < n; i++) { const p = at(x0 + i); off.push(Math.max(...p.map((v, c) => Math.abs(v - bg[c]))) > 40); }
  for (let i = 0; i < off.length - 2; i++) if (off[i] && off[i + 1] && off[i + 2]) return x0 + i;
  return x0 + off.length;
}

const clean = (t) => t.trim().replace(/[|/\\_]+\s*$/, '').trim();   // the window border OCRs as a trailing "|"
/** Compared without case or punctuation: "<Tomb>" OCRs as "(Tomb)", "«Tomb»", "Tomb". */
const key = (t) => t.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
const inv = (m) => mat(m.w, m.h, 1, m.data.map((v) => 255 - v));

/** A few readings of one line: the plain one and the white letters only (the minimap's picture can
 * show through behind the text). */
async function variants(img) {
  const out = [clean(await ocr(inv(resizeCubic(gray(img), 3)), 7, ''))];
  for (const [thr, k] of [[200, 3], [200, 4], [170, 4]]) {
    const w = mat(img.w, img.h, 1);
    for (let i = 0; i < img.w * img.h; i++) w.data[i] = Math.min(img.data[3 * i], img.data[3 * i + 1], img.data[3 * i + 2]) > thr ? 255 : 0;
    const u = resizeCubic(w, k);
    for (let i = 0; i < u.data.length; i++) u.data[i] = Math.max(0, Math.min(255, u.data[i]));
    out.push(clean(await ocr(pad(inv(u), 20, 20, 20, 20, 255), 7, '')));
  }
  return [...new Set(out)].filter(Boolean);
}

/** difflib.SequenceMatcher(None, a, b).ratio() (no junk heuristics: the strings are short). */
export function ratio(a, b) {
  if (!a.length && !b.length) return 1;
  const match = (a0, a1, b0, b1) => {
    let bi = 0, bj = 0, bk = 0;
    let prev = new Map();
    for (let i = a0; i < a1; i++) {
      const cur = new Map();
      for (let j = b0; j < b1; j++) {
        if (a[i] !== b[j]) continue;
        const k = (prev.get(j - 1) || 0) + 1;
        cur.set(j, k);
        if (k > bk) { bi = i - k + 1; bj = j - k + 1; bk = k; }
      }
      prev = cur;
    }
    if (!bk) return 0;
    return bk + match(a0, bi, b0, bj) + match(bi + bk, a1, bj + bk, b1);
  };
  return (2 * match(0, a.length, 0, b.length)) / (a.length + b.length);
}

/** A last word of I-like strokes is a Roman numeral: "Excavation Site ill" -> "Excavation Site III". */
export function numerals(name) {
  const w = name.split(/\s+/).filter(Boolean);
  if (w.length > 1 && /^[iIl1|!]+$/.test(w.at(-1))) w[w.length - 1] = 'I'.repeat(w.at(-1).length);
  else if (w.length > 1 && /^[iIl1|!]*[vVxX][iIl1|!]*$/.test(w.at(-1))) w[w.length - 1] = w.at(-1).replace(/[iIl1|!]/g, 'I').toUpperCase();
  return w.join(' ');
}

/** [similarity, street, name] of the closest real map, or null. */
export function snapScore(street, name, maps, cutoff = 0.75) {
  if (!maps || !maps.length) return null;
  name = numerals(name);
  const want = `${key(street)} | ${key(name)}`;
  let best = null, br = 0;
  for (const m of maps) {
    const r = ratio(want, `${key(m.streetName || '')} | ${key(m.name || '')}`);
    if (r > br) { best = m; br = r; }
  }
  if (!best || br < cutoff) {
    // the street line may be cut off or misread: the map name alone
    let hit = null, hr = 0;
    for (const m of maps) { const r = ratio(key(name), key(m.name || '')); if (r > hr) { hr = r; hit = m; } }
    if (!hit || hr < cutoff) return null;
    best = hit; br = hr;
  }
  return [br, best.streetName || '', best.name || ''];
}

/** {street, name, raw, matched} or null when no minimap is visible. */
export async function readMap(frame, header, maps = []) {
  const h = findHeader(frame, header);
  if (!h) return null;
  const { x, y, s } = h, x0 = x + Math.trunc(TEXT_X * s);
  const right = rightEdge(frame, x0, y + Math.trunc(27 * s), Math.trunc(700 * s));
  const vars = [];
  for (const [a, b] of [LINE1, LINE2]) {
    const c = crop(frame, x0, y + Math.trunc(a * s), right - x0, Math.trunc(b * s) - Math.trunc(a * s));
    vars.push(c.w && c.h ? await variants(c) : ['']);
  }
  let best = null;
  for (const st of vars[0].length ? vars[0] : ['']) for (const nm of vars[1].length ? vars[1] : ['']) {
    const r = snapScore(st, nm, maps);
    if (r && (!best || r[0] > best[0][0])) best = [r, st, nm];
  }
  const street = best ? best[1] : vars[0][0] || '', name = best ? best[2] : vars[1][0] || '';
  if (!street && !name) return null;
  const out = { street, name, raw: [street, name], matched: !!best, box: [x, y, Math.max(right - x, Math.trunc(200 * s)), Math.trunc(LINE2[1] * s)] };
  if (best) { out.street = best[0][1]; out.name = best[0][2]; }
  return out;
}
