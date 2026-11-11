// Live EXP graph on a canvas: dots = each reading, solid = 5-min average, dashed = session average.
// mult converts EXP/min to the unit shown (60 = EXP/hr).
const fmt = (v) => (v == null ? '–' : Math.round(v).toLocaleString());
const AXIS = '13px system-ui', TAG = 'bold 15px system-ui', TAG_H = 24;

/** Draw in CSS pixels at the size the canvas is shown (sharp text at any width; the pop-out's canvas
 * is half the page's). Returns [context, width, height] in CSS px. */
function fit(cv) {
  const r = cv.ownerDocument.defaultView.devicePixelRatio || 1;
  const W = Math.round(cv.clientWidth || cv.width), H = Math.round(cv.clientHeight || cv.height);
  if (cv.width !== Math.round(W * r) || cv.height !== Math.round(H * r)) { cv.width = Math.round(W * r); cv.height = Math.round(H * r); }
  const g = cv.getContext('2d');
  g.setTransform(r, 0, 0, r, 0, 0);
  g.clearRect(0, 0, W, H);
  return [g, W, H];
}
const short = (v) => (v < 0 ? '-' + short(-v) : v >= 1e6 ? `${(v / 1e6).toFixed(2)}M` : v >= 1e5 ? `${(v / 1000).toFixed(0)}k` : v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v.toFixed(0));

/** Current values in boxes to the right of the plot: a dot on each line's end, a leader line from the dot
 * to its box's left edge. Boxes sit at their line's height, pushed apart (never overlapping) and kept
 * inside [top, bottom]. items: [{y, text, color}]; xEnd = where the lines end; xBox = boxes' left edge. */
function rightLabels(g, items, xEnd, xBox, top, bottom, ink, bg) {
  g.font = TAG;
  const h = TAG_H, gap = 4;
  const boxes = items.map((it) => ({ ...it, w: g.measureText(it.text).width + 14, by: it.y - h / 2 })).sort((a, b) => a.y - b.y);
  for (let i = 1; i < boxes.length; i++) boxes[i].by = Math.max(boxes[i].by, boxes[i - 1].by + h + gap);   // push down
  if (boxes.length) {
    const over = boxes.at(-1).by + h - bottom;
    if (over > 0) for (const b of boxes) b.by -= over;                                                      // back up into view
    boxes[0].by = Math.max(boxes[0].by, top);
    for (let i = 1; i < boxes.length; i++) boxes[i].by = Math.max(boxes[i].by, boxes[i - 1].by + h + gap);
  }
  for (const b of boxes) {
    const my = b.by + h / 2;
    const xe = b.x ?? xEnd;   // a line that ends earlier (an outdated part) has its own end
    g.strokeStyle = b.color; g.lineWidth = 1.5;
    if (xe < xEnd - 1) { g.setLineDash([2, 4]); g.globalAlpha = 0.5; }   // not a continuation of the line: a faint pointer
    g.beginPath(); g.moveTo(xe, b.y); g.lineTo(xBox, my); g.stroke(); g.setLineDash([]); g.globalAlpha = 1;
    g.fillStyle = b.color; g.beginPath(); g.arc(xe, b.y, 4, 0, 7); g.fill();
    g.fillStyle = bg; g.fillRect(xBox, b.by, b.w, h);
    g.strokeStyle = b.color; g.strokeRect(xBox + 0.75, b.by + 0.75, b.w - 1.5, h - 1.5);
    g.fillStyle = ink; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(b.text, xBox + b.w / 2, my + 1);
  }
  g.textAlign = 'left'; g.textBaseline = 'alphabetic';
}
const labelWidth = (g, texts) => { g.font = TAG; return Math.max(0, ...texts.map((t) => g.measureText(t).width + 14)); };

/** Y limits from the smoothed and session lines: their range plus 25% (at least 5% of the top), not from 0
 * (snapshot.y_range). floor = lowest allowed (null: may go negative). */
function yRange(vals, floor = 0) {
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = Math.max((hi - lo) * 0.25, Math.max(Math.abs(hi), Math.abs(lo)) * 0.05, 1);
  return nice(floor == null ? lo - pad : Math.max(floor, lo - pad), hi + pad);
}
/** Limits widened to whole steps of a round size (1, 2 or 5 x 10^k: 5k, 10k, 20k..., about 3-5 steps), so the grid lines
 * sit at round values. Returns [lo, hi, step]. */
export function nice(lo, hi) {
  const raw = (hi - lo) / 4, p = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * p).find((st) => st >= raw);
  return [Math.floor(lo / step + 1e-9) * step, Math.ceil(hi / step - 1e-9) * step, step];
}

/** A grid label in the unit of the axis' biggest value, with just enough decimals to show the step. */
export function tick(v, step, top) {
  const [d, u] = top >= 1e6 && step >= 1e5 ? [1e6, 'M'] : step >= 1000 ? [1000, 'k'] : [1, ''];
  const dec = Math.max(0, Math.min(3, Math.ceil(-Math.log10(step / d) - 1e-9)));
  const st = step / d, need = Math.abs(st - Math.round(st * 10 ** dec) / 10 ** dec) > 1e-9 ? dec + 1 : dec;
  return Math.abs(v) < step * 1e-6 ? '0' : `${(v / d).toFixed(need)}${u}`;
}
function axes(g, x0, x1, y0, y1, lo, hi, step, t1, title, ink, Y) {
  g.font = AXIS; g.textAlign = 'right'; g.textBaseline = 'middle';
  for (let k = 0, v = lo; v <= hi + step * 1e-6; v = lo + ++k * step) {
    g.strokeStyle = ink; g.globalAlpha = 0.2; g.beginPath(); g.moveTo(x0, Y(v)); g.lineTo(x1, Y(v)); g.stroke(); g.globalAlpha = 1;
    g.fillStyle = ink; g.fillText(tick(v, step, Math.max(Math.abs(lo), Math.abs(hi))), x0 - 4, Y(v));
  }
  if (lo < 0 && hi > 0) { g.strokeStyle = ink; g.globalAlpha = 0.6; g.beginPath(); g.moveTo(x0, Y(0)); g.lineTo(x1, Y(0)); g.stroke(); g.globalAlpha = 1; }
  g.textAlign = 'left'; g.textBaseline = 'top'; g.fillText(title, x0 + 4, 2);
  g.textAlign = 'right'; g.textBaseline = 'bottom'; g.fillText(`${t1.toFixed(1)} min`, x1, H0(g));
  g.textAlign = 'left'; g.textBaseline = 'alphabetic';
}
const H0 = (g) => g.canvas.clientHeight || g.canvas.height;

/** EXP/hr: dots = each reading, solid = 5-min average (current value boxed on the right), dashed = session. */
/** floor: lowest y the axis may start at (0 for EXP; null lets it go negative, e.g. net mesos/hr). */
export function drawGraph(cv, ser, mult = 1, unit = 'EXP/min', empty = null, floor = 0) {
  const [g, W, H] = fit(cv);
  const css = getComputedStyle(cv.ownerDocument.documentElement);
  const ink = css.getPropertyValue('--mute') || '#888', acc = css.getPropertyValue('--acc') || '#2f6fde';
  const text = css.getPropertyValue('--ink') || '#111', bg = css.getPropertyValue('--card') || '#fff';
  if (ser.length < 1) { g.fillStyle = ink; g.font = AXIS; g.fillText(empty ?? `${unit} appears after two readings.`, 8, H / 2); return; }
  const pts = ser.map((p) => ({ min: p.min, rate: p.rate * mult, ema: p.ema * mult, cum: p.cum * mult }));
  const per = unit.includes('/') ? unit.slice(unit.indexOf('/')) : '';
  const label = `${short(pts.at(-1).ema)}${per}`;
  const x0 = 62, x1 = W - labelWidth(g, [label]) - 22, y0 = H - 20, y1 = 22, t1 = Math.max(1, pts.at(-1).min);
  const [lo, hi, step] = yRange(pts.flatMap((p) => [p.ema, p.cum, ...(floor == null ? [p.rate] : [])]), floor);
  const X = (m) => x0 + (x1 - x0) * m / t1, Y = (v) => y0 - (y0 - y1) * (Math.min(Math.max(v, lo), hi) - lo) / (hi - lo);
  axes(g, x0, x1, y0, y1, lo, hi, step, t1, unit, ink, Y);
  g.fillStyle = acc; g.globalAlpha = 0.45;
  for (const p of pts) { g.beginPath(); g.arc(X(p.min), Y(p.rate), 2.5, 0, 7); g.fill(); }
  g.globalAlpha = 1; g.strokeStyle = acc; g.lineWidth = 2;
  g.beginPath(); pts.forEach((p, i) => (i ? g.lineTo(X(p.min), Y(p.ema)) : g.moveTo(X(p.min), Y(p.ema)))); g.stroke();
  g.setLineDash([5, 4]); g.lineWidth = 1.5; g.strokeStyle = ink;
  g.beginPath(); pts.forEach((p, i) => (i ? g.lineTo(X(p.min), Y(p.cum)) : g.moveTo(X(p.min), Y(p.cum)))); g.stroke();
  g.setLineDash([]);
  rightLabels(g, [{ y: Y(pts.at(-1).ema), text: label, color: acc }], X(pts.at(-1).min), x1 + 14, y1, y0, text, bg);
}

/** Mesos/hr spent on HP (orange) and MP (blue) potions, like gui.py's potion graph: per-reading rate
 * (faint dots), 5-min average (solid, current value boxed on the right), session (dashed). Net: potions
 * gained count as negative, so the axis may go below 0. */
export function drawPotionGraph(cv, pts) {
  const [g, W, H] = fit(cv);
  const css = getComputedStyle(cv.ownerDocument.documentElement);
  const ink = css.getPropertyValue('--mute') || '#888', text = css.getPropertyValue('--ink') || '#111', bg = css.getPropertyValue('--card') || '#fff';
  pts = pts.filter((p) => p.ema_hp != null);
  if (!pts.length) { g.fillStyle = ink; g.font = AXIS; g.fillText('Potion mesos/hr appears after two quick slot readings.', 8, H / 2); return; }
  const kinds = [['hp', HP, 'HP'], ['mp', MP, 'MP']];
  const last = pts.at(-1), labels = kinds.map(([kind, , name]) => `${name} ${short(last[`ema_${kind}`])}/hr`);
  const x0 = 58, x1 = W - labelWidth(g, labels) - 22, y0 = H - 20, y1 = 22, t1 = Math.max(last.t, 1);
  const [lo, hi, step] = yRange(pts.flatMap((p) => ['ema_hp', 'ema_mp', 'cum_hp', 'cum_mp'].map((k) => p[k])).filter((v) => v != null), null);
  const X = (t) => x0 + (x1 - x0) * t / t1, Y = (v) => y0 - (y0 - y1) * (Math.min(Math.max(v, lo), hi) - lo) / (hi - lo);
  axes(g, x0, x1, y0, y1, lo, hi, step, t1, 'potion mesos/hr', ink, Y);
  for (const [kind, color] of kinds) {
    g.fillStyle = color; g.globalAlpha = 0.4;
    for (const p of pts) if (p[`raw_${kind}`] != null) { g.beginPath(); g.arc(X(p.t), Y(p[`raw_${kind}`]), 2.5, 0, 7); g.fill(); }
    g.globalAlpha = 1;
  }
  if (pts.length > 1) for (const [kind, color] of kinds) {
    g.strokeStyle = color;
    for (const [key, dash, w] of [[`cum_${kind}`, [5, 4], 1.5], [`ema_${kind}`, [], 2]]) {
      g.setLineDash(dash); g.lineWidth = w; g.beginPath();
      pts.forEach((p, i) => (i ? g.lineTo(X(p.t), Y(p[key])) : g.moveTo(X(p.t), Y(p[key])))); g.stroke();
    }
    g.setLineDash([]);
  }
  rightLabels(g, kinds.map(([kind, color], i) => ({ y: Y(last[`ema_${kind}`]), text: labels[i], color })), X(last.t), x1 + 14, y1, y0, text, bg);
}

export const HP = '#eb6834', MP = '#2a78d6';

/** Several rate lines on one axis (y may go below 0): lines [{label, color (null = ink), width, pts: [{min, v}]}].
 * Each point is a dot, joined by its line; a line stops where its part was last read, so an outdated part shows
 * as a line that ends early. Every line's newest value is boxed on the right with its name. */
export function drawLines(cv, lines, unit, empty) {
  const [g, W, H] = fit(cv);
  const css = getComputedStyle(cv.ownerDocument.documentElement);
  const ink = css.getPropertyValue('--mute') || '#888', text = css.getPropertyValue('--ink') || '#111', bg = css.getPropertyValue('--card') || '#fff';
  lines = (lines || []).filter((l) => l.pts.length);
  if (!lines.length) { g.fillStyle = ink; g.font = AXIS; g.fillText(empty, 8, H / 2); return; }
  const labels = lines.map((l) => `${l.label} ${short(l.pts.at(-1).v)}`);
  const x0 = 62, x1 = W - labelWidth(g, labels) - 22, y0 = H - 20, y1 = 22;
  const t1 = Math.max(1, ...lines.map((l) => l.pts.at(-1).min));
  const [lo, hi, step] = yRange(lines.flatMap((l) => l.pts.map((p) => p.v)), null);
  const X = (m) => x0 + (x1 - x0) * m / t1, Y = (v) => y0 - (y0 - y1) * (Math.min(Math.max(v, lo), hi) - lo) / (hi - lo);
  axes(g, x0, x1, y0, y1, lo, hi, step, t1, unit, ink, Y);
  for (const l of lines) {
    const c = l.color || text;
    g.strokeStyle = c; g.fillStyle = c; g.lineWidth = l.width || 1.5;
    g.beginPath(); l.pts.forEach((p, i) => (i ? g.lineTo(X(p.min), Y(p.v)) : g.moveTo(X(p.min), Y(p.v)))); g.stroke();
    for (const p of l.pts) { g.beginPath(); g.arc(X(p.min), Y(p.v), l.width ? 3.5 : 2.5, 0, 7); g.fill(); }
  }
  rightLabels(g, lines.map((l, i) => ({ y: Y(l.pts.at(-1).v), x: X(l.pts.at(-1).min), text: labels[i], color: l.color || text })), X(t1), x1 + 14, y1, y0, text, bg);
}

/** One line under a potion graph: mesos/hr over the whole session and mesos spent so far, per kind. */
export function potionSummary(pts) {
  const p = (pts || []).filter((q) => q.cum_hp != null).at(-1);
  if (!p) return '';
  const f = (v) => (v == null ? '–' : Math.round(v).toLocaleString());
  return `Session average: <b style="color:${HP}">HP ${f(p.cum_hp)}/hr</b> (${f(p.hp)} spent) · <b style="color:${MP}">MP ${f(p.cum_mp)}/hr</b> (${f(p.mp)} spent)`;
}
