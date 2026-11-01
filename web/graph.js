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

/** A value in a box with its top at `by`, right-aligned at xr. */
function tag(g, text, xr, by, color, ink, bg) {
  g.font = TAG;
  const w = g.measureText(text).width + 14, h = TAG_H;
  g.fillStyle = bg; g.fillRect(xr - w, by, w, h);
  g.strokeStyle = color; g.lineWidth = 1.5; g.strokeRect(xr - w + 0.75, by + 0.75, w - 1.5, h - 1.5);
  g.fillStyle = ink; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(text, xr - w / 2, by + h / 2 + 1);
  g.textAlign = 'left'; g.textBaseline = 'alphabetic';
  return by;
}

export function drawGraph(cv, ser, mult = 1, unit = 'EXP/min') {
  const [g, W, H] = fit(cv), P = 62;
  const css = getComputedStyle(cv.ownerDocument.documentElement);
  const ink = css.getPropertyValue('--mute') || '#888', acc = css.getPropertyValue('--acc') || '#2f6fde';
  const text = css.getPropertyValue('--ink') || '#111', bg = css.getPropertyValue('--card') || '#fff';
  if (ser.length < 1) { g.fillStyle = ink; g.font = AXIS; g.fillText(`${unit} appears after two readings.`, 8, H / 2); return; }
  const pts = ser.map((p) => ({ min: p.min, rate: p.rate * mult, ema: p.ema * mult, cum: p.cum * mult }));
  const xmax = Math.max(1, pts.at(-1).min), ys = pts.flatMap((p) => [p.ema, p.cum]);
  const ymax = Math.max(...ys) * 1.15 || 1, ymin = Math.max(0, Math.min(...ys) * 0.85);
  const X = (m) => P + (W - P - 8) * m / xmax, Y = (v) => H - 18 - (H - 26) * (v - ymin) / (ymax - ymin || 1);
  g.strokeStyle = ink; g.globalAlpha = 0.3; g.beginPath(); g.moveTo(P, H - 18); g.lineTo(W - 8, H - 18); g.stroke(); g.globalAlpha = 1;
  g.fillStyle = ink; g.font = AXIS;
  g.fillText(short(ymax), 2, 14); g.fillText(short(ymin), 2, H - 20);
  g.textAlign = 'right'; g.fillText(`${xmax.toFixed(1)} min`, W - 8, H - 3); g.textAlign = 'left';
  g.fillStyle = acc; g.globalAlpha = 0.45;
  for (const p of pts) { const y = Math.min(H - 18, Math.max(2, Y(p.rate))); g.beginPath(); g.arc(X(p.min), y, 2.5, 0, 7); g.fill(); }
  g.globalAlpha = 1; g.strokeStyle = acc; g.lineWidth = 2;
  g.beginPath(); pts.forEach((p, i) => (i ? g.lineTo(X(p.min), Y(p.ema)) : g.moveTo(X(p.min), Y(p.ema)))); g.stroke();
  g.setLineDash([5, 4]); g.lineWidth = 1.5; g.strokeStyle = ink;
  g.beginPath(); pts.forEach((p, i) => (i ? g.lineTo(X(p.min), Y(p.cum)) : g.moveTo(X(p.min), Y(p.cum)))); g.stroke();
  g.setLineDash([]);
  // current EXP/hr (the 5-min average now) in a box at the end of its line, like gui.py
  const last = pts.at(-1);
  const ey = Y(last.ema), by = ey - TAG_H - 4 >= 2 ? ey - TAG_H - 4 : Math.min(ey + 4, H - 18 - TAG_H);   // above the line's end, below if no room
  tag(g, `${short(last.ema)}${unit.includes('/') ? unit.slice(unit.indexOf('/')) : ''}`, W - 8, by, acc, text, bg);
}

/** Mesos/hr spent on HP (orange) and MP (blue) potions, like gui.py's potion graph: per-reading rate
 * (faint dots), 5-min average (solid, current value boxed at its end), session (dashed). Net: potions
 * gained count as negative, so the axis may go below 0. The y-axis fits the lines (snapshot.y_range). */
export function drawPotionGraph(cv, pts) {
  const [g, W, H] = fit(cv);
  const css = getComputedStyle(cv.ownerDocument.documentElement);
  const ink = css.getPropertyValue('--mute') || '#888', text = css.getPropertyValue('--ink') || '#111', bg = css.getPropertyValue('--card') || '#fff';
  pts = pts.filter((p) => p.ema_hp != null);
  if (!pts.length) { g.fillStyle = ink; g.font = AXIS; g.fillText('Potion mesos/hr appears after two quick slot readings.', 8, H / 2); return; }
  const vals = pts.flatMap((p) => ['ema_hp', 'ema_mp', 'cum_hp', 'cum_mp'].map((k) => p[k])).filter((v) => v != null);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = Math.max((hi - lo) * 0.25, Math.max(Math.abs(hi), Math.abs(lo)) * 0.05, 1);
  lo -= pad; hi += pad;
  const x0 = 58, x1 = W - 8, y0 = H - 22, y1 = 8, t1 = Math.max(pts.at(-1).t, 1);
  const X = (t) => x0 + (x1 - x0) * t / t1, Y = (v) => y0 - (y0 - y1) * (Math.min(Math.max(v, lo), hi) - lo) / (hi - lo);
  const k = short;
  g.font = AXIS; g.textAlign = 'right'; g.textBaseline = 'middle';
  for (const f of [0, 0.5, 1]) {
    const v = lo + (hi - lo) * f;
    g.strokeStyle = ink; g.globalAlpha = 0.2; g.beginPath(); g.moveTo(x0, Y(v)); g.lineTo(x1, Y(v)); g.stroke(); g.globalAlpha = 1;
    g.fillStyle = ink; g.fillText(k(v), x0 - 4, Y(v));
  }
  if (lo < 0 && hi > 0) { g.strokeStyle = ink; g.globalAlpha = 0.6; g.beginPath(); g.moveTo(x0, Y(0)); g.lineTo(x1, Y(0)); g.stroke(); g.globalAlpha = 1; }
  g.textAlign = 'left'; g.fillStyle = ink; g.fillText('potion mesos/hr', x0 + 4, y1 + 6); g.textAlign = 'right'; g.fillText(`${t1.toFixed(1)} min`, x1, H - 6);
  const kinds = [['hp', '#eb6834', 'HP'], ['mp', '#2a78d6', 'MP']];
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
  // current 5-min value of each line in a box at its end, as near its line as it fits without overlapping
  const ends = kinds.map(([kind, color, name]) => [Y(pts.at(-1)[`ema_${kind}`]), kind, color, name]).sort((x, y) => x[0] - y[0]);
  const clear = (by, other) => other == null || by + TAG_H + 2 <= other || by >= other + TAG_H + 2;
  let prev = null;
  ends.forEach(([ey, kind, color, name], i) => {
    const label = `${name} ${k(pts.at(-1)[`ema_${kind}`])}/hr`;
    const tries = i === 0 ? [ey - TAG_H - 4, ey + 4] : [ey + 4, ey - TAG_H - 4];
    let by = tries.find((t) => t >= 0 && t + TAG_H <= y0 && clear(t, prev));
    if (by == null) by = prev != null && prev + 2 * TAG_H + 2 <= y0 ? prev + TAG_H + 2 : Math.max(0, (prev ?? ey) - TAG_H - 2);
    prev = tag(g, label, x1, by, color, text, bg);
  });
  g.textAlign = 'left'; g.textBaseline = 'alphabetic';
}
