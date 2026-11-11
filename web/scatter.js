// Scatter tab: one dot per saved session, EXP/hr across, mesos/hr up, coloured by a field you pick
// (map, character, class, tag, or a number: level, minutes, date). Hover = the session's numbers,
// click = open it, click a legend entry = hide/show those sessions. Plain SVG, no library.
import { nice, tick } from './graph.js';

const esc = (v) => String(v ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt = (v) => (v == null ? '–' : Math.round(v).toLocaleString());
// dataviz reference palette, fixed order (light / dark steps); past 3 colours the shapes differ too, so
// colours are never the only way to tell categories apart; past 8 = "Other" (grey)
const CAT = [['#2a78d6', '#3987e5'], ['#eb6834', '#d95926'], ['#1baf7a', '#199e70'], ['#eda100', '#c98500'],
  ['#e87ba4', '#d55181'], ['#008300', '#008300'], ['#6250d6', '#9085e9'], ['#e34948', '#e66767']];
const OTHER = ['#98a2b3', '#667085'];
const SHAPES = ['circle', 'square', 'triangle', 'diamond'];
// sequential blue, light -> dark (ordinal-safe ends: step 250 .. 700)
const SEQ = ['#86b6ef', '#6da7ec', '#5598e7', '#3987e5', '#2a78d6', '#256abf', '#1c5cab', '#184f95', '#104281', '#0d366b'];

export const COLOR_BY = [['none', 'Nothing'], ['map', 'Map'], ['char', 'Character'], ['job', 'Class'], ['tag', 'Tag (first)'],
  ['level', 'Level (start)'], ['minutes', 'Minutes'], ['date', 'Date']];
export const Y_BY = [['net_per_hr', 'Net mesos/hr incl. items'], ['revenue_per_hr', 'Revenue/hr (mesos + items gained)'], ['mesos_per_hr', 'Mesos/hr (meso field only)']];

const catOf = {
  map: (x) => x.map || '(no map)', char: (x) => x.character?.name || '(no character)', job: (x) => x.character?.job || '(no class)',
  tag: (x, tl) => { const t = tl.find((t) => (x.tags || []).some((y) => y.toLowerCase() === t.toLowerCase())) || (x.tags || [])[0]; return t || '(no tags)'; },
};
const numOf = { level: (x) => x.level, minutes: (x) => x.result?.minutes, date: (x) => x.id };

function shape(kind, x, y, r) {
  if (kind === 'square') return `<rect x="${x - r * 0.88}" y="${y - r * 0.88}" width="${r * 1.76}" height="${r * 1.76}" rx="1.5"`;
  if (kind === 'triangle') return `<path d="M${x},${y - r * 1.1}L${x + r * 1.05},${y + r * 0.8}L${x - r * 1.05},${y + r * 0.8}Z"`;
  if (kind === 'diamond') return `<path d="M${x},${y - r * 1.2}L${x + r * 1.2},${y}L${x},${y + r * 1.2}L${x - r * 1.2},${y}Z"`;
  return `<circle cx="${x}" cy="${y}" r="${r}"`;
}

/** el: the scatter section's plot holder; list: light session index; opt: {colorBy, y, hidden: Set, tagList, dark};
 * onOpen(id) opens a session; onToggle(category) hides/shows one. */
export function renderScatter(el, list, opt, onOpen, onToggle) {
  const dark = opt.dark, yKey = opt.y, by = opt.colorBy;
  const all = list.filter((x) => x.result?.exp_per_hr != null && x.result?.[yKey] != null);
  const left = list.length - all.length;
  if (!all.length) { el.innerHTML = `<p class="mute">No saved sessions with both EXP/hr and ${esc(Y_BY.find((y) => y[0] === yKey)[1])} yet.</p>`; return; }

  // colour per session: categories by how many sessions each has (over all sessions, so hiding one never repaints the others)
  let legend = '', colorOf = () => CAT[0][dark ? 1 : 0], shapeOf = () => 'circle', catKey = () => null;
  if (catOf[by]) {
    catKey = (x) => catOf[by](x, opt.tagList || []);
    const n = new Map();
    for (const x of all) n.set(catKey(x), (n.get(catKey(x)) || 0) + 1);
    const order = [...n.keys()].sort((a, b) => n.get(b) - n.get(a) || String(a).localeCompare(String(b)));
    const slot = new Map(order.map((k, i) => [k, i < CAT.length ? i : -1]));
    colorOf = (x) => { const i = slot.get(catKey(x)); return (i >= 0 ? CAT[i] : OTHER)[dark ? 1 : 0]; };
    shapeOf = (x) => { const i = slot.get(catKey(x)); return i >= 0 ? SHAPES[i % SHAPES.length] : 'circle'; };
    legend = order.map((k) => {
      const i = slot.get(k), c = (i >= 0 ? CAT[i] : OTHER)[dark ? 1 : 0], sh = i >= 0 ? SHAPES[i % SHAPES.length] : 'circle', off = opt.hidden.has(k);
      return `<button class="lg ${off ? 'off' : ''}" data-cat="${esc(k)}" title="${off ? 'Show' : 'Hide'} these sessions"><svg width="14" height="14">${shape(sh, 7, 7, 5)} fill="${c}"/></svg>${esc(k)} <span class="mute">${n.get(k)}</span></button>`;
    }).join('') + (order.length > CAT.length ? '<span class="mute small">past 8: grey</span>' : '');
  } else if (numOf[by]) {
    const vals = all.map(numOf[by]).filter((v) => v != null);
    const lo = Math.min(...vals), hi = Math.max(...vals);
    colorOf = (x) => { const v = numOf[by](x); if (v == null) return OTHER[dark ? 1 : 0]; const f = hi > lo ? (v - lo) / (hi - lo) : 0.5; return SEQ[Math.round(f * (SEQ.length - 1))]; };
    const lab = (v) => (by === 'date' ? new Date(v).toLocaleDateString() : fmt(v));
    legend = vals.length ? `<span class="small mute">${lab(lo)}</span><span class="ramp" style="background:linear-gradient(90deg,${SEQ.join(',')})"></span><span class="small mute">${lab(hi)}</span>` : '';
  }
  const shown = all.filter((x) => !opt.hidden.has(catKey(x)));

  // axes fitted to the data (not from 0), round grid steps
  const W = 940, H = 440, x0 = 78, x1 = W - 20, y0 = H - 44, y1 = 16;
  const pad = (lo, hi) => { const p = Math.max((hi - lo) * 0.08, Math.abs(hi) * 0.05, 1); return nice(lo - p, hi + p); };
  const xs = all.map((x) => x.result.exp_per_hr), ys = all.map((x) => x.result[yKey]);
  const [xl, xh, xs_] = pad(Math.min(...xs), Math.max(...xs)), [yl, yh, ys_] = pad(Math.min(...ys), Math.max(...ys));
  const X = (v) => x0 + (x1 - x0) * (v - xl) / (xh - xl), Y = (v) => y0 - (y0 - y1) * (v - yl) / (yh - yl);
  let g = '';
  for (let v = yl; v <= yh + 1e-9; v += ys_) g += `<line x1="${x0}" x2="${x1}" y1="${Y(v)}" y2="${Y(v)}" class="${Math.abs(v) < ys_ * 1e-6 ? 'zero' : 'grid'}"/><text x="${x0 - 8}" y="${Y(v) + 4}" text-anchor="end">${tick(v, ys_, Math.max(Math.abs(yl), Math.abs(yh)))}</text>`;
  for (let v = xl; v <= xh + 1e-9; v += xs_) g += `<line x1="${X(v)}" x2="${X(v)}" y1="${y1}" y2="${y0}" class="grid"/><text x="${X(v)}" y="${y0 + 18}" text-anchor="middle">${tick(v, xs_, Math.max(Math.abs(xl), Math.abs(xh)))}</text>`;
  g += `<text x="${(x0 + x1) / 2}" y="${H - 6}" text-anchor="middle" class="ttl">EXP/hr</text>`;
  g += `<text x="16" y="${(y0 + y1) / 2}" text-anchor="middle" class="ttl" transform="rotate(-90 16 ${(y0 + y1) / 2})">${esc(Y_BY.find((y) => y[0] === yKey)[1])}</text>`;
  const dots = shown.map((x) => `<g class="dot" data-id="${x.id}">${shape('circle', X(x.result.exp_per_hr), Y(x.result[yKey]), 14)} class="hit"/>${shape(shapeOf(x), X(x.result.exp_per_hr), Y(x.result[yKey]), 6.5)} fill="${colorOf(x)}" class="mark"/></g>`).join('');
  el.innerHTML = `<div class="sclegend">${legend}</div>
    <div class="scwrap"><svg viewBox="0 0 ${W} ${H}" class="scatter" role="img" aria-label="EXP/hr against mesos/hr, one dot per session">${g}${dots}</svg><div class="sctip" hidden></div></div>
    <p class="mute small">${shown.length} of ${all.length} sessions shown${left ? ` (${left} without EXP/hr or this mesos figure left out)` : ''}. Hover a dot for the session, click it to open it${catOf[by] ? '; click a legend entry to hide or show those sessions' : ''}.</p>`;

  const tip = el.querySelector('.sctip'), wrap = el.querySelector('.scwrap'), byId = new Map(shown.map((x) => [String(x.id), x]));
  for (const d of el.querySelectorAll('g.dot')) {
    const x = byId.get(d.dataset.id);
    d.onmouseenter = () => {
      const lv = x.level == null ? '–' : x.level_end != null && x.level_end !== x.level ? `${x.level}→${x.level_end}` : x.level;
      tip.innerHTML = `<b>${esc(x.name || new Date(x.id).toLocaleString())}</b><br>${esc(x.map || 'no map')} · ${esc(x.character?.name || 'no character')} · Lv ${lv}<br>
        EXP/hr <b>${fmt(x.result.exp_per_hr)}</b> · ${esc(Y_BY.find((y) => y[0] === yKey)[1].split(' (')[0])} <b>${fmt(x.result[yKey])}</b><br>
        ${fmt(x.result.minutes)} min${(x.tags || []).length ? ` · ${esc(x.tags.join(', '))}` : ''}`;
      tip.hidden = false;
      const r = d.getBoundingClientRect(), w = wrap.getBoundingClientRect();
      tip.style.left = `${Math.min(r.left - w.left + 14, w.width - 260)}px`; tip.style.top = `${r.top - w.top + 14}px`;
      d.classList.add('on');
    };
    d.onmouseleave = () => { tip.hidden = true; d.classList.remove('on'); };
    d.onclick = () => onOpen(d.dataset.id);
  }
  for (const b of el.querySelectorAll('[data-cat]')) b.onclick = () => onToggle(b.dataset.cat);
}
