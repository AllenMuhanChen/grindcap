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
