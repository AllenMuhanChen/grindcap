// Character stat window (S): STR/DEX/INT/LUK, AP, HP/MP, and the detail values (attack, defence, accuracy,
// avoid, speed, jump ...) when they're shown. Read-only, like everything else: only the picture is used.
//
// No template of the window yet, so it is found by its labels: one OCR pass over the whole frame looks for
// STR, DEX, INT and LUK stacked in one column (3 of 4, same x, top to bottom). A second pass reads the area
// around that column at 3x, and every line is parsed as "LABEL value". Labels are matched by name, so the
// exact layout doesn't matter and labels we don't know are skipped.
//
// Self-check: a stat shown as "total (base+bonus)" must add up; the review shows the window as captured.
import { gray, crop, resizeCubic, pad, mat, mean, invert } from './img.js';
import { ocrWords } from './ocr.js';

/** key, label spellings (letters only, upper case), how the value is written. */
export const FIELDS = [
  ['level', ['LEVEL', 'LV'], 'num'],
  ['exp', ['EXP'], 'exp'],
  ['hp', ['HP'], 'pair'],
  ['mp', ['MP'], 'pair'],
  ['fame', ['FAME', 'HONOR', 'POP'], 'num'],
  ['ap', ['AP', 'ABILITYPOINT', 'ABILITYPOINTS'], 'num'],
  ['str', ['STR'], 'stat'],
  ['dex', ['DEX'], 'stat'],
  ['int', ['INT'], 'stat'],
  ['luk', ['LUK'], 'stat'],
  ['attack', ['ATTACK', 'ATT', 'DAMAGE', 'WATT', 'WEAPONATTACK'], 'range'],
  ['wdef', ['WDEF', 'WEAPONDEF', 'WEAPONDEFENSE', 'DEF', 'DEFENSE'], 'num'],
  ['magic', ['MAGIC', 'MATT', 'MAGICATTACK'], 'num'],
  ['mdef', ['MDEF', 'MAGICDEF', 'MAGICDEFENSE'], 'num'],
  ['accuracy', ['ACCURACY', 'ACC'], 'num'],
  ['avoid', ['AVOID', 'AVOIDABILITY', 'AVOIDABILLITY', 'AVO'], 'num'],
  ['hands', ['HANDS', 'HAND'], 'num'],
  ['speed', ['SPEED'], 'num'],
  ['jump', ['JUMP'], 'num'],
];
const BY_LABEL = new Map();
for (const [k, names, kind] of FIELDS) for (const n of names) BY_LABEL.set(n, { key: k, kind });
export const MAIN = ['str', 'dex', 'int', 'luk'];
/** The fields the review lets you type over (each one number; pairs/ranges keep their parts). */
export const EDITABLE = ['level', 'ap', 'str', 'dex', 'int', 'luk', 'hp', 'mp', 'attack_min', 'attack_max', 'wdef', 'magic', 'mdef', 'accuracy', 'avoid', 'hands', 'speed', 'jump', 'fame'];

const letters = (t) => (t || '').toUpperCase().replace(/[^A-Z]/g, '');
// misreads of digits inside a number: O/o/D -> 0, l/I/i/| -> 1, S -> 5, B -> 8
const digitish = (t) => t.replace(/[Oo]/g, '0').replace(/[lIi|]/g, '1').replace(/S/g, '5').replace(/B/g, '8');

/** A label as OCR'd ("STR", "W.DEF", "lNT") -> {key, kind} or null. Only exact spellings (after mapping
 * the usual l/I and 0/O confusions): a fuzzy match turns "AP" into "HP". */
export function labelOf(text) {
  const plain = letters(text);
  if (BY_LABEL.has(plain)) return BY_LABEL.get(plain);
  const t = letters(text.replace(/0/g, 'O').replace(/[1|]/g, 'I'));
  for (const v of [t, t.replace(/L/g, 'I'), t.replace(/I/g, 'L')]) if (BY_LABEL.has(v)) return BY_LABEL.get(v);   // "lNT", "1NT", "IUK"
  return null;
}

/** Parse one value as written after its label. */
export function parseValue(kind, text) {
  const s = digitish(text).replace(/,/g, '').replace(/\s+/g, ' ').trim();
  const nums = (s.match(/\d+/g) || []).map(Number);
  if (!nums.length) return null;
  if (kind === 'stat') {
    const m = s.match(/(\d+)\s*\(\s*(\d+)\s*[+]\s*(\d+)\s*\)/);
    if (m) { const [total, base, bonus] = [+m[1], +m[2], +m[3]]; return { total, base, bonus, checked: total === base + bonus }; }
    return { total: nums[0], checked: false };
  }
  if (kind === 'pair') {
    const m = s.match(/(\d+)\s*[/|]\s*(\d+)/);
    return m ? { cur: +m[1], max: +m[2] } : { max: nums[0] };
  }
  if (kind === 'range') {
    const m = s.match(/(\d+)\s*[~\-–—]\s*(\d+)/);
    return m ? { min: +m[1], max: +m[2] } : { min: nums[0], max: nums[0] };
  }
  if (kind === 'exp') {
    const p = s.match(/(\d+(?:\.\d+)?)\s*%/);
    return { value: nums[0], pct: p ? +p[1] : null };
  }
  return { value: nums[0] };
}

/** Words -> lines (same row) -> {key: value}. Words: [{text, x0, y0, x1, y1}]. A label starts a field,
 * the words after it (up to the next label) are its value. */
export function parseWords(words) {
  const ws = words.filter((w) => w.text && w.text.trim()).map((w) => ({ ...w, cy: (w.y0 + w.y1) / 2, h: w.y1 - w.y0 }));
  ws.sort((a, b) => a.cy - b.cy);
  const lines = [];
  for (const w of ws) {
    const l = lines.find((x) => Math.abs(x.cy - w.cy) < Math.max(4, 0.5 * Math.min(x.h, w.h)));
    if (l) { l.words.push(w); l.cy = (l.cy * (l.words.length - 1) + w.cy) / l.words.length; } else lines.push({ cy: w.cy, h: w.h, words: [w] });
  }
  const out = {}, raw = [];
  for (const l of lines) {
    l.words.sort((a, b) => a.x0 - b.x0);
    raw.push(l.words.map((w) => w.text).join(' '));
    let cur = null;
    const flush = () => {
      if (!cur) return;
      const v = parseValue(cur.kind, cur.parts.join(' '));
      if (v && !(out[cur.key] && out[cur.key].checked && !v.checked)) out[cur.key] = { ...v, raw: `${cur.label} ${cur.parts.join(' ')}`.trim() };
      cur = null;
    };
    for (let i = 0; i < l.words.length; i++) {
      const w = l.words[i];
      // labels can be two words ("W. DEF", "Weapon Def"); try the pair first
      const two = i + 1 < l.words.length ? labelOf(w.text + l.words[i + 1].text) : null;
      const one = labelOf(w.text);
      const pair = !!two && /^[A-Za-z.]+$/.test(l.words[i + 1].text);
      const lab = pair ? two : one;
      if (lab && /^[A-Za-z][A-Za-z.]*:?\d*$/.test(w.text)) {   // a label word starts with a letter ("STR:104" in one word is fine)
        flush();
        cur = { ...lab, label: w.text, parts: [] };
        if (pair) { cur.label += ' ' + l.words[i + 1].text; i++; }
        // "STR:104" in one word
        const rest = w.text.replace(/^[A-Za-z.]+:?/, '');
        if (rest) cur.parts.push(rest);
      } else if (cur) cur.parts.push(w.text);
    }
    flush();
  }
  return { values: out, lines: raw };
}

/** Label words STR/DEX/INT/LUK in one column, top to bottom: [{key, x0, y0, x1, y1}] or null. */
export function findColumn(words, scale = 1.4) {
  const hits = [];
  for (const w of words) { const l = labelOf(w.text); if (l && MAIN.includes(l.key)) hits.push({ key: l.key, ...w }); }
  let best = null;
  for (const a of hits.filter((h) => h.key === 'str' || h.key === 'dex')) {
    const col = [a];
    for (const k of MAIN.slice(MAIN.indexOf(a.key) + 1)) {
      const prev = col.at(-1);
      const c = hits.filter((h) => h.key === k && Math.abs(h.x0 - a.x0) < 14 * scale && h.y0 > prev.y0 && h.y0 - prev.y0 < 60 * scale)
        .sort((p, q) => p.y0 - q.y0)[0];
      if (c) col.push(c);
    }
    if (col.length >= 3 && (!best || col.length > best.length)) best = col;
  }
  return best;
}

function toGrey3x(m) {
  let g = gray(m);
  if (mean(g) < 128) g = invert(g);            // dark window: dark text on light reads best
  const u = resizeCubic(g, 3);
  for (let i = 0; i < u.data.length; i++) u.data[i] = Math.max(0, Math.min(255, u.data[i]));
  return pad(u, 20, 20, 20, 20, 255);
}

/** Read the stat window off a frame. Returns null when no stat window is on screen, else
 * {values, lines, box, ok, why}: ok = all four main stats read and every "total (base+bonus)" adds up. */
export async function readStats(frame, gameScale = null) {
  const s = gameScale || 1.4 * frame.h / 1080;
  const g = gray(frame);
  const first = await ocrWords(g, 11, '', 'stats');
  const col = findColumn(first.words, s);
  if (!col) return null;
  const x = col[0].x0, top = col[0].y0, bot = col.at(-1).y1;
  const step = (bot - top) / Math.max(1, col.length - 1 + (MAIN.indexOf(col[0].key)));
  const x0 = Math.max(0, Math.round(x - 30 * s)), x1 = Math.min(frame.w, Math.round(x + 420 * s));
  const y0 = Math.max(0, Math.round(top - 12 * step)), y1 = Math.min(frame.h, Math.round(bot + 14 * step));
  const box = [x0, y0, x1 - x0, y1 - y0];
  const near = first.words.filter((w) => w.x0 >= x0 && w.x1 <= x1 && w.y0 >= y0 && w.y1 <= y1);
  const a = parseWords(near);
  const up = await ocrWords(toGrey3x(crop(frame, ...box)), 11, '', 'stats');
  const b = parseWords(up.words.map((w) => ({ ...w, x0: x0 + (w.x0 - 20) / 3, x1: x0 + (w.x1 - 20) / 3, y0: y0 + (w.y0 - 20) / 3, y1: y0 + (w.y1 - 20) / 3 })));
  // the 3x pass wins, unless only the native pass has a checked reading of that field
  const values = { ...a.values };
  for (const [k, v] of Object.entries(b.values)) if (!(a.values[k]?.checked && !v.checked)) values[k] = v;
  const missing = MAIN.filter((k) => !values[k]);
  const bad = Object.entries(values).filter(([, v]) => v.checked === false && v.base != null).map(([k]) => k.toUpperCase());
  const ok = !missing.length && !bad.length;
  const why = [missing.length ? `${missing.map((k) => k.toUpperCase()).join(', ')} not read` : '', bad.length ? `${bad.join(', ')}: base + bonus doesn't add up` : ''].filter(Boolean).join('; ');
  return { values, lines: b.lines.length ? b.lines : a.lines, box, ok, why };
}

/** One number per editable field ({str: 104, attack_min: 50, ...}) from read values. */
export function flat(values = {}) {
  const o = {};
  for (const [k, v] of Object.entries(values || {})) {
    if (v == null) continue;
    if (v.total != null) o[k] = v.total;
    else if (v.min != null) { o[`${k}_min`] = v.min; o[`${k}_max`] = v.max; }
    else if (v.max != null && (k === 'hp' || k === 'mp')) o[k] = v.max;
    else if (v.value != null) o[k] = v.value;
  }
  return o;
}

/** Stats with your corrections: fixes {field: number} over flat(read). */
export function withStatFixes(stats, fix = {}) {
  if (!stats) return Object.keys(fix || {}).length ? { ...fix } : null;
  const o = flat(stats.values);
  for (const [k, v] of Object.entries(fix || {})) if (v != null && v !== '') o[k] = +v;
  return o;
}
