// Live EXP graph on a canvas: dots = each reading, solid = 5-min average, dashed = session average.
// mult converts EXP/min to the unit shown (60 = EXP/hr).
const fmt = (v) => (v == null ? '–' : Math.round(v).toLocaleString());

export function drawGraph(cv, ser, mult = 1, unit = 'EXP/min') {
  const g = cv.getContext('2d'), W = cv.width, H = cv.height, P = 46;
  g.clearRect(0, 0, W, H);
  const css = getComputedStyle(cv.ownerDocument.documentElement);
  const ink = css.getPropertyValue('--mute') || '#888', acc = css.getPropertyValue('--acc') || '#2f6fde';
  if (ser.length < 1) { g.fillStyle = ink; g.font = '13px system-ui'; g.fillText(`${unit} appears after two readings.`, 8, H / 2); return; }
  const pts = ser.map((p) => ({ min: p.min, rate: p.rate * mult, ema: p.ema * mult, cum: p.cum * mult }));
  const xmax = Math.max(1, pts.at(-1).min), ys = pts.flatMap((p) => [p.ema, p.cum]);
  const ymax = Math.max(...ys) * 1.15 || 1, ymin = Math.max(0, Math.min(...ys) * 0.85);
  const X = (m) => P + (W - P - 8) * m / xmax, Y = (v) => H - 18 - (H - 26) * (v - ymin) / (ymax - ymin || 1);
  g.strokeStyle = ink; g.globalAlpha = 0.3; g.beginPath(); g.moveTo(P, H - 18); g.lineTo(W - 8, H - 18); g.stroke(); g.globalAlpha = 1;
  g.fillStyle = ink; g.font = '11px system-ui';
  g.fillText(fmt(ymax), 2, 12); g.fillText(fmt(ymin), 2, H - 20); g.fillText(`${xmax.toFixed(1)} min`, W - 60, H - 4);
  g.fillStyle = acc; g.globalAlpha = 0.45;
  for (const p of pts) { const y = Math.min(H - 18, Math.max(2, Y(p.rate))); g.beginPath(); g.arc(X(p.min), y, 2.5, 0, 7); g.fill(); }
  g.globalAlpha = 1; g.strokeStyle = acc; g.lineWidth = 2;
  g.beginPath(); pts.forEach((p, i) => (i ? g.lineTo(X(p.min), Y(p.ema)) : g.moveTo(X(p.min), Y(p.ema)))); g.stroke();
  g.setLineDash([5, 4]); g.lineWidth = 1.5; g.strokeStyle = ink;
  g.beginPath(); pts.forEach((p, i) => (i ? g.lineTo(X(p.min), Y(p.cum)) : g.moveTo(X(p.min), Y(p.cum)))); g.stroke();
  g.setLineDash([]);
}

/** Mesos/hr spent on HP (orange) and MP (blue) potions, like gui.py's potion graph: per-reading rate
 * (faint dots), 5-min average (solid, current value boxed at its end), session (dashed). Net: potions
 * gained count as negative, so the axis may go below 0. The y-axis fits the lines (snapshot.y_range). */
export function drawPotionGraph(cv, pts) {
  const g = cv.getContext('2d'), W = cv.width, H = cv.height;
  g.clearRect(0, 0, W, H);
  const css = getComputedStyle(cv.ownerDocument.documentElement);
  const ink = css.getPropertyValue('--mute') || '#888', text = css.getPropertyValue('--ink') || '#111', bg = css.getPropertyValue('--card') || '#fff';
  pts = pts.filter((p) => p.ema_hp != null);
  if (!pts.length) { g.fillStyle = ink; g.font = '13px system-ui'; g.fillText('Potion mesos/hr appears after two quick slot readings.', 8, H / 2); return; }
  const vals = pts.flatMap((p) => ['ema_hp', 'ema_mp', 'cum_hp', 'cum_mp'].map((k) => p[k])).filter((v) => v != null);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = Math.max((hi - lo) * 0.25, Math.max(Math.abs(hi), Math.abs(lo)) * 0.05, 1);
  lo -= pad; hi += pad;
  const x0 = 50, x1 = W - 8, y0 = H - 22, y1 = 8, t1 = Math.max(pts.at(-1).t, 1);
  const X = (t) => x0 + (x1 - x0) * t / t1, Y = (v) => y0 - (y0 - y1) * (Math.min(Math.max(v, lo), hi) - lo) / (hi - lo);
  const k = (v) => (v < 0 ? '-' + k(-v) : v >= 100000 ? `${(v / 1000).toFixed(0)}k` : v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v.toFixed(0));
  g.font = '11px system-ui'; g.textAlign = 'right'; g.textBaseline = 'middle';
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
  // current 5-min value of each line in a box at its end; the lower line's box goes below it
  const h = 16, ends = kinds.map(([kind, color, name]) => [Y(pts.at(-1)[`ema_${kind}`]), kind, color, name]).sort((a, b) => a[0] - b[0]);
  let prev = null; g.font = 'bold 11px system-ui'; g.textAlign = 'center';
  ends.forEach(([ey, kind, color, name], i) => {
    const tag = `${name} ${k(pts.at(-1)[`ema_${kind}`])}/hr`, w = g.measureText(tag).width + 12;
    let by = i === 0 ? ey - h - 3 : ey + 3;
    by = Math.min(Math.max(by, y1), y0 - h);
    if (i === 1 && by < prev + h + 1) { by = Math.min(prev + h + 1, y0 - h); if (by < prev + h + 1) by = prev - h - 1; }
    g.fillStyle = bg; g.fillRect(x1 - w, by, w, h); g.strokeStyle = color; g.lineWidth = 1; g.strokeRect(x1 - w + 0.5, by + 0.5, w - 1, h - 1);
    g.fillStyle = text; g.fillText(tag, x1 - w / 2, by + h / 2 + 1);
    prev = by;
  });
  g.textAlign = 'left'; g.textBaseline = 'alphabetic';
}
