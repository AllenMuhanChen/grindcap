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
function axes(g, x0, x1, y0, y1, lo, hi, step, t1, title, ink, Y, t0 = 0) {
  g.font = AXIS; g.textAlign = 'right'; g.textBaseline = 'middle';
  for (let k = 0, v = lo; v <= hi + step * 1e-6; v = lo + ++k * step) {
    g.strokeStyle = ink; g.globalAlpha = 0.2; g.beginPath(); g.moveTo(x0, Y(v)); g.lineTo(x1, Y(v)); g.stroke(); g.globalAlpha = 1;
    g.fillStyle = ink; g.fillText(tick(v, step, Math.max(Math.abs(lo), Math.abs(hi))), x0 - 4, Y(v));
  }
  if (lo < 0 && hi > 0) { g.strokeStyle = ink; g.globalAlpha = 0.6; g.beginPath(); g.moveTo(x0, Y(0)); g.lineTo(x1, Y(0)); g.stroke(); g.globalAlpha = 1; }
  g.textAlign = 'left'; g.textBaseline = 'top'; g.fillText(title, x0 + 4, 2);
  const mm = (m) => (m >= 120 ? `${Math.floor(m / 60)}h${String(Math.round(m % 60)).padStart(2, '0')}` : `${m.toFixed(m < 10 ? 1 : 0)} min`);
  g.textAlign = 'right'; g.textBaseline = 'bottom'; g.fillText(mm(t1), x1, H0(g));
  if (t0 > 0.05) { g.textAlign = 'left'; g.fillText(mm(t0), x0, H0(g)); }
  g.textAlign = 'left'; g.textBaseline = 'alphabetic';
}
const H0 = (g) => g.canvas.clientHeight || g.canvas.height;

// ---- time window, zoom and pan. cv._view = {w: minutes shown (null = all), end: right edge (null = follow the
// newest point)}. Live graphs show the last LIVE_W minutes and follow the present; the review shows everything.
// Mouse wheel zooms around the pointer, dragging pans, double-click goes back to the default.
export const LIVE_W = 60;
function xWindow(cv, tMax, live) {
  const v = cv._view || {};
  const w = v.w ?? (live ? LIVE_W : Math.max(tMax, 1));
  const t1 = v.end ?? Math.max(tMax, live ? Math.min(w, 1) : 1);
  const t0 = Math.max(0, t1 - w);
  return [t0, Math.max(t1, t0 + 0.5)];
}
/** Points inside [t0, t1] plus one each side (so lines run to the edge). key = the time field. */
function inWin(pts, t0, t1, key = 'min') {
  const i0 = Math.max(0, pts.findIndex((p) => p[key] >= t0) - 1);
  let i1 = pts.length - 1;
  for (let i = 0; i < pts.length; i++) if (pts[i][key] > t1) { i1 = i; break; }
  return pts.findIndex((p) => p[key] >= t0) < 0 ? pts.slice(-1) : pts.slice(i0, i1 + 1);
}
const strictly = (pts, t0, t1, key = 'min') => pts.filter((p) => p[key] >= t0 - 1e-9 && p[key] <= t1 + 1e-9);
/** Wire the canvas once: wheel zoom, drag pan, double-click reset; each change redraws with cv._redraw. */
function interactive(cv, geom) {
  cv._geom = geom;
  if (cv._zoomInit) return;
  cv._zoomInit = true;
  cv.style.cursor = 'grab'; cv.style.touchAction = 'none';
  cv.title = 'Scroll to zoom, drag to move back and forth in time, double-click for the default view';
  const redraw = () => cv._redraw && cv._redraw();
  const frac = (e) => { const r = cv.getBoundingClientRect(), G = cv._geom; return Math.min(1, Math.max(0, (e.clientX - r.left - G.x0) / (G.x1 - G.x0))); };
  const set = (t0, t1) => {
    const G = cv._geom, w = Math.max(2, Math.min(t1 - t0, Math.max(G.tMax, 2)));
    let end = Math.min(Math.max(t0 + w, w), Math.max(G.tMax, w));
    cv._view = { w: Math.abs(w - Math.max(G.tMax, 1)) < 1e-6 && !G.live ? null : w, end: end >= G.tMax - 1e-6 ? null : end };   // at the newest point: follow it again
    redraw();
  };
  cv.addEventListener('wheel', (e) => {
    const G = cv._geom; if (!G) return;
    e.preventDefault();
    const f = frac(e), at = G.t0 + f * (G.t1 - G.t0), k = e.deltaY > 0 ? 1.25 : 0.8, w = (G.t1 - G.t0) * k;
    set(at - f * w, at + (1 - f) * w);
  }, { passive: false });
  let drag = null;
  cv.addEventListener('pointerdown', (e) => { const G = cv._geom; if (!G) return; drag = { x: e.clientX, t0: G.t0, t1: G.t1, px: (G.t1 - G.t0) / (G.x1 - G.x0) }; cv.setPointerCapture(e.pointerId); cv.style.cursor = 'grabbing'; });
  cv.addEventListener('pointermove', (e) => { if (!drag) return; const dt = (drag.x - e.clientX) * drag.px; set(drag.t0 + dt, drag.t1 + dt); });
  const up = () => { drag = null; cv.style.cursor = 'grab'; };
  cv.addEventListener('pointerup', up); cv.addEventListener('pointercancel', up);
  cv.addEventListener('dblclick', () => { cv._view = null; redraw(); });
}

/** EXP/hr: dots = each reading, solid = 5-min average (current value boxed on the right), dashed = session. */
/** floor: lowest y the axis may start at (0 for EXP; null lets it go negative, e.g. net mesos/hr). */
export function drawGraph(cv, ser, mult = 1, unit = 'EXP/min', empty = null, floor = 0, live = false) {
  cv._redraw = () => drawGraph(cv, ser, mult, unit, empty, floor, live);
  const [g, W, H] = fit(cv);
  const css = getComputedStyle(cv.ownerDocument.documentElement);
  const ink = css.getPropertyValue('--mute') || '#888', acc = css.getPropertyValue('--acc') || '#2f6fde';
  const text = css.getPropertyValue('--ink') || '#111', bg = css.getPropertyValue('--card') || '#fff';
  if (ser.length < 1) { g.fillStyle = ink; g.font = AXIS; g.fillText(empty ?? `${unit} appears after two readings.`, 8, H / 2); return; }
  const all = ser.map((p) => ({ min: p.min, rate: p.rate * mult, ema: p.ema * mult, cum: p.cum * mult }));
  const [t0, t1] = xWindow(cv, all.at(-1).min, live), pts = inWin(all, t0, t1), vis = strictly(all, t0, t1);
  const lastV = vis.at(-1) || pts.at(-1);
  const per = unit.includes('/') ? unit.slice(unit.indexOf('/')) : '';
  const label = `${short(lastV.ema)}${per}`;
  const x0 = 62, x1 = W - labelWidth(g, [label]) - 22, y0 = H - 20, y1 = 22;
  const [lo, hi, step] = yRange((vis.length ? vis : pts).flatMap((p) => [p.ema, p.cum, ...(floor == null ? [p.rate] : [])]), floor);
  const X = (m) => x0 + (x1 - x0) * (m - t0) / (t1 - t0), Y = (v) => y0 - (y0 - y1) * (Math.min(Math.max(v, lo), hi) - lo) / (hi - lo);
  interactive(cv, { x0, x1, t0, t1, tMax: all.at(-1).min, live });
  axes(g, x0, x1, y0, y1, lo, hi, step, t1, unit, ink, Y, t0);
  g.save(); g.beginPath(); g.rect(x0, 0, x1 - x0 + 1, H); g.clip();
  g.fillStyle = acc; g.globalAlpha = 0.45;
  for (const p of pts) { g.beginPath(); g.arc(X(p.min), Y(p.rate), 2.5, 0, 7); g.fill(); }
  g.globalAlpha = 1; g.strokeStyle = acc; g.lineWidth = 2;
  g.beginPath(); pts.forEach((p, i) => (i ? g.lineTo(X(p.min), Y(p.ema)) : g.moveTo(X(p.min), Y(p.ema)))); g.stroke();
  g.setLineDash([5, 4]); g.lineWidth = 1.5; g.strokeStyle = ink;
  g.beginPath(); pts.forEach((p, i) => (i ? g.lineTo(X(p.min), Y(p.cum)) : g.moveTo(X(p.min), Y(p.cum)))); g.stroke();
  g.setLineDash([]); g.restore();
  rightLabels(g, [{ y: Y(lastV.ema), text: label, color: acc }], X(lastV.min), x1 + 14, y1, y0, text, bg);
}

/** Mesos/hr spent on HP (orange) and MP (blue) potions, like gui.py's potion graph: per-reading rate
 * (faint dots), 5-min average (solid, current value boxed on the right), session (dashed). Net: potions
 * gained count as negative, so the axis may go below 0. */
export function drawPotionGraph(cv, pts, live = false) {
  cv._redraw = () => drawPotionGraph(cv, pts, live);
  const [g, W, H] = fit(cv);
  const css = getComputedStyle(cv.ownerDocument.documentElement);
  const ink = css.getPropertyValue('--mute') || '#888', text = css.getPropertyValue('--ink') || '#111', bg = css.getPropertyValue('--card') || '#fff';
  const allP = pts.filter((p) => p.ema_hp != null);
  if (!allP.length) { g.fillStyle = ink; g.font = AXIS; g.fillText('Potion mesos/hr appears after two quick slot readings.', 8, H / 2); return; }
  const kinds = [['hp', HP, 'HP'], ['mp', MP, 'MP']];
  const [t0, t1] = xWindow(cv, allP.at(-1).t, live);
  pts = inWin(allP, t0, t1, 't');
  const vis = strictly(allP, t0, t1, 't'), last = vis.at(-1) || pts.at(-1);
  const labels = kinds.map(([kind, , name]) => `${name} ${short(last[`ema_${kind}`])}/hr`);
  const x0 = 58, x1 = W - labelWidth(g, labels) - 22, y0 = H - 20, y1 = 22;
  const [lo, hi, step] = yRange((vis.length ? vis : pts).flatMap((p) => ['ema_hp', 'ema_mp', 'cum_hp', 'cum_mp'].map((k) => p[k])).filter((v) => v != null), null);
  const X = (t) => x0 + (x1 - x0) * (t - t0) / (t1 - t0), Y = (v) => y0 - (y0 - y1) * (Math.min(Math.max(v, lo), hi) - lo) / (hi - lo);
  interactive(cv, { x0, x1, t0, t1, tMax: allP.at(-1).t, live });
  axes(g, x0, x1, y0, y1, lo, hi, step, t1, 'potion mesos/hr', ink, Y, t0);
  g.save(); g.beginPath(); g.rect(x0, 0, x1 - x0 + 1, H); g.clip();
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
  g.restore();
  rightLabels(g, kinds.map(([kind, color], i) => ({ y: Y(last[`ema_${kind}`]), text: labels[i], color })), X(last.t), x1 + 14, y1, y0, text, bg);
}

export const HP = '#eb6834', MP = '#2a78d6';

/** Several rate lines on one axis (y may go below 0): lines [{label, color (null = ink), width, pts: [{min, v}]}].
 * Each point is a dot, joined by its line; a line stops where its part was last read, so an outdated part shows
 * as a line that ends early. Every line's newest value is boxed on the right with its name. */
export function drawLines(cv, lines, unit, empty, live = false) {
  cv._redraw = () => drawLines(cv, lines, unit, empty, live);
  const [g, W, H] = fit(cv);
  const css = getComputedStyle(cv.ownerDocument.documentElement);
  const ink = css.getPropertyValue('--mute') || '#888', text = css.getPropertyValue('--ink') || '#111', bg = css.getPropertyValue('--card') || '#fff';
  const allL = (lines || []).filter((l) => l.pts.length);
  if (!allL.length) { g.fillStyle = ink; g.font = AXIS; g.fillText(empty, 8, H / 2); return; }
  const tMax = Math.max(...allL.map((l) => l.pts.at(-1).min));
  const [t0, t1] = xWindow(cv, tMax, live);
  lines = allL.map((l) => ({ ...l, pts: inWin(l.pts, t0, t1), vis: strictly(l.pts, t0, t1) })).filter((l) => l.vis.length || l.pts.length);
  const lastOf = (l) => l.vis.at(-1) || l.pts.at(-1);
  const labels = lines.map((l) => `${l.label} ${short(lastOf(l).v)}`);
  const x0 = 62, x1 = W - labelWidth(g, labels) - 22, y0 = H - 20, y1 = 22;
  const vals = lines.flatMap((l) => (l.vis.length ? l.vis : l.pts).map((p) => p.v));
  const [lo, hi, step] = yRange(vals, null);
  const X = (m) => x0 + (x1 - x0) * (m - t0) / (t1 - t0), Y = (v) => y0 - (y0 - y1) * (Math.min(Math.max(v, lo), hi) - lo) / (hi - lo);
  interactive(cv, { x0, x1, t0, t1, tMax, live });
  axes(g, x0, x1, y0, y1, lo, hi, step, t1, unit, ink, Y, t0);
  g.save(); g.beginPath(); g.rect(x0, 0, x1 - x0 + 1, H); g.clip();
  for (const l of lines) {
    const c = l.color || text;
    g.strokeStyle = c; g.fillStyle = c; g.lineWidth = l.width || 1.5;
    g.beginPath(); l.pts.forEach((p, i) => (i ? g.lineTo(X(p.min), Y(p.v)) : g.moveTo(X(p.min), Y(p.v)))); g.stroke();
    for (const p of l.pts) { g.beginPath(); g.arc(X(p.min), Y(p.v), l.width ? 3.5 : 2.5, 0, 7); g.fill(); }
  }
  g.restore();
  const xr = Math.min(X(t1), X(tMax));
  rightLabels(g, lines.map((l, i) => ({ y: Y(lastOf(l).v), x: Math.max(x0, Math.min(X(lastOf(l).min), x1)), text: labels[i], color: l.color || text })), xr, x1 + 14, y1, y0, text, bg);
}

/** One line under a potion graph: mesos/hr over the whole session and mesos spent so far, per kind. */
export function potionSummary(pts) {
  const p = (pts || []).filter((q) => q.cum_hp != null).at(-1);
  if (!p) return '';
  const f = (v) => (v == null ? '–' : Math.round(v).toLocaleString());
  return `Session average: <b style="color:${HP}">HP ${f(p.cum_hp)}/hr</b> (${f(p.hp)} spent) · <b style="color:${MP}">MP ${f(p.cum_mp)}/hr</b> (${f(p.mp)} spent)`;
}
