// Always-on-top pop-out (Chrome/Edge Document Picture-in-Picture): the old control window's job.
// Session timer, EXP/hr, Start/End/Finish, the tab checklist while scanning, the live graph and the
// key results, so you don't have to switch back to the browser tab.
import { drawGraph, drawPotionGraph, potionSummary, HP, MP } from './graph.js';
import { liveSeries, isPaused, activeMs, COUNTED_TABS } from './lib/session.js';

let pip = null, api = null;
const FULL = [380, 560], SMALL = [260, 175];
let small = (() => { try { return localStorage.getItem('grindcap.popSmall') === '1'; } catch { return false; } })();
const fmt = (v) => (v == null || Number.isNaN(v) ? '–' : Math.round(v).toLocaleString());
const hms = (ms) => { const s = Math.max(0, Math.floor(ms / 1000)); return `${Math.floor(s / 3600)}:${String(Math.floor(s / 60) % 60).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; };

const CSS = `
  * { box-sizing: border-box; }
  body { margin: 0; padding: 10px; font: 13px/1.4 system-ui, sans-serif; background: var(--bg); color: var(--ink); }
  .top { display: flex; justify-content: space-between; align-items: baseline; }
  .big { font-size: 26px; font-weight: 650; font-variant-numeric: tabular-nums; }
  .mute { color: var(--mute); } .ok { color: var(--ok); } .bad { color: var(--bad); }
  .row { display: flex; gap: 6px; flex-wrap: wrap; margin: 8px 0; }
  button { font: inherit; padding: 5px 10px; border-radius: 7px; border: 1px solid var(--line); background: var(--card); color: var(--ink); cursor: pointer; }
  button.primary { background: var(--acc); border-color: var(--acc); color: #fff; }
  button:disabled { opacity: .4; cursor: default; }
  canvas { width: 100%; height: 150px; display: block; }
  .box { border: 1px solid var(--line); border-radius: 8px; padding: 8px; margin-top: 8px; background: var(--card); }
  .chips span { display: inline-block; padding: 1px 8px; margin: 2px 3px 2px 0; border-radius: 999px; border: 1px solid var(--line); }
  .chips span.done { border-color: var(--ok); color: var(--ok); }
  .kv { display: grid; grid-template-columns: 1fr auto; gap: 2px 10px; font-variant-numeric: tabular-nums; }
  .note { font-size: 12px; margin-top: 6px; }
  .timer { font-size: 26px; font-weight: 700; font-variant-numeric: tabular-nums; } .timer.idle { font-size: 14px; font-weight: 400; color: var(--mute); }
  .mode { padding: 0 9px; font-size: 16px; line-height: 20px; margin-left: 6px; }
  .mscan { font-size: 14px; margin-top: 3px; }
  .mpot { font-size: 15px; font-weight: 600; margin-top: 2px; } body.small { padding: 6px 10px; } body.small .top b { display: none; }
  .pct { font-size: 18px; font-weight: 600; } .warn { background: var(--bad); color: #fff; border-radius: 7px; padding: 8px 10px; margin: 6px 0; font-size: 15px; font-weight: 650; }
  .scan .help { font-size: 14px; }
`;

export async function openPopout(a) {
  api = a;
  if (pip && !pip.closed) { pip.focus(); return; }
  if (!('documentPictureInPicture' in window)) {
    alert('This browser has no always-on-top pop-out (Document Picture-in-Picture). Use Chrome or Edge 116 or newer.');
    return;
  }
  const [w0, h0] = small ? SMALL : FULL;
  pip = await window.documentPictureInPicture.requestWindow({ width: w0, height: h0 });
  const d = pip.document;
  // the page's colour tokens (light/dark), then the pop-out's own layout
  const root = getComputedStyle(document.documentElement);
  const vars = ['--bg', '--card', '--ink', '--mute', '--line', '--acc', '--ok', '--bad'].map((v) => `${v}:${root.getPropertyValue(v)}`).join(';');
  d.head.innerHTML = `<title>grindcap</title><style>:root{${vars}}${CSS}</style>`;
  d.body.innerHTML = `
    <div class="top"><b>grindcap</b><span><span id="share" class="mute"></span> <button id="mode" class="mode" title="Small window: timer, EXP/hr and potion cost only">–</button></span></div>
    <div class="warn" id="alert" hidden></div>
    <div id="mini" hidden>
      <div class="timer" id="mtimer"></div>
      <div><span class="big" id="mxph">–</span> <span class="mute">EXP/hr</span> <span id="mpph" class="pct"></span></div>
      <div class="mpot" id="mpot"></div>
      <div id="mscan" class="mscan" hidden></div>
    </div>
    <div id="full">
    <div class="top"><span id="timer" class="timer">No session</span><span id="lv" class="mute"></span></div>
    <div><span class="big" id="xph">–</span> <span class="mute">EXP/hr (5-min)</span> <span id="pph" class="pct"></span></div>
    <div class="mute" id="xph2"></div>
    <canvas id="g" width="720" height="240"></canvas>
    <div class="mute note" id="pot"></div>
    <canvas id="pg" width="720" height="180" style="height:120px" hidden></canvas>
    <div id="pgs" class="note"></div>
    <div class="row">
      <button id="start" class="primary">Start</button><button id="end">End</button>
      <button id="pause">Pause</button><button id="discard">Discard</button><button id="finish" title="Stop taking pages now">Finish pages</button>
    </div>
    <div class="box scan" id="scan" hidden></div>
    <div class="box" id="res" hidden></div>
    <div class="note mute" id="note"></div>
    </div>`;
  d.getElementById('mode').onclick = () => {
    small = !small;
    try { localStorage.setItem('grindcap.popSmall', small ? '1' : '0'); } catch { /* private window */ }
    try { pip.resizeTo(...(small ? SMALL : FULL)); } catch { /* the browser may refuse: the layout still changes */ }
    updatePopout();
  };
  d.getElementById('start').onclick = () => api.start(pip.confirm.bind(pip));
  d.getElementById('end').onclick = () => api.end();
  d.getElementById('finish').onclick = () => api.finish();
  d.getElementById('pause').onclick = () => api.pause();
  d.getElementById('discard').onclick = () => api.discard(pip.confirm.bind(pip));
  pip.addEventListener('pagehide', () => { pip = null; });
  updatePopout();
}

export function updatePopout() {
  if (!pip || pip.closed || !api) return;
  const S = api.state(), d = pip.document, $ = (id) => d.getElementById(id);
  const sharing = !!(S.cap && S.cap.live);
  $('share').innerHTML = sharing ? '<span class="ok">● sharing</span>' : '<span class="bad">● not sharing</span>';
  const running = api.running(), paused = isPaused(S.pauses);
  $('timer').innerHTML = S.collect ? `Scanning ${S.collect.kind} pages` : running ? `${paused ? '<span class="bad">PAUSED</span> ' : ''}${hms(activeMs(S.start.time, Date.now(), S.pauses))}` : S.end ? 'Session ended' : 'No session';
  $('timer').classList.toggle('idle', !running || !!S.collect);
  const ser = liveSeries(S.live.rows, 5, S.pauses), last = ser.at(-1), r = S.live.rows.at(-1);
  $('lv').textContent = r ? `Lv ${r.level} · ${r.pct}%` : '';
  $('xph').textContent = fmt(last ? last.ema * 60 : null);
  $('pph').textContent = last?.emaPct != null ? `${last.emaPct.toFixed(1)}%/hr` : '';
  $('xph2').textContent = last ? `session ${fmt(last.cum * 60)}/hr${last.pct != null ? ` (${last.pct.toFixed(1)}%/hr)` : ''} · +${fmt(last.gained)} EXP` : (running ? 'waiting for two readings…' : '');
  drawGraph($('g'), ser, 60, 'EXP/hr');
  const pot = api.potions ? api.potions() : { pts: [], line: '' };
  $('pot').textContent = pot.line;
  $('pg').hidden = !pot.pts.length;
  if (pot.pts.length) drawPotionGraph($('pg'), pot.pts);
  $('pgs').innerHTML = potionSummary(pot.pts);
  d.body.classList.toggle('small', small);
  $('mini').hidden = !small; $('full').hidden = small;
  $('mode').textContent = small ? '+' : '–'; $('mode').title = small ? 'Full window' : 'Small window: timer, EXP/hr and potion cost only';
  if (small) {
    $('mtimer').innerHTML = $('timer').innerHTML;
    $('mtimer').classList.toggle('idle', $('timer').classList.contains('idle'));
    $('mxph').textContent = $('xph').textContent; $('mpph').textContent = $('pph').textContent;
    const lp = pot.pts.at(-1);
    const cs = S.collect, ms = $('mscan');
    ms.hidden = !cs;
    if (cs) {
      const miss = COUNTED_TABS.filter((t) => !cs.seen.has(t));
      ms.innerHTML = `${cs.kind === 'start' ? 'Start' : 'End'} scan: ` + (miss.length ? `still to do <b>${miss.join(', ')}</b>` : '<span class="ok">all tabs read, finishing</span>');
    }
    $('mpot').innerHTML = lp ? `<span style="color:${HP}">HP ${fmt(lp.ema_hp)}/hr</span> · <span style="color:${MP}">MP ${fmt(lp.ema_mp)}/hr</span>` : '';
  }
  $('start').disabled = !sharing || !!S.collect || running;
  $('end').disabled = !sharing || !!S.collect || !running;
  $('pause').disabled = !running || !!S.collect;
  $('pause').textContent = paused ? 'Resume' : 'Pause';
  $('discard').disabled = !running && !S.collect;
  $('finish').hidden = !S.collect;
  const al = api.alert ? api.alert() : '';
  $('alert').hidden = !al; $('alert').textContent = al;
  const c = S.collect, scan = $('scan');
  scan.hidden = !c;
  if (c) {
    const missing = COUNTED_TABS.filter((t) => !c.seen.has(t));
    const left = c.lastNew ? 4 - (Date.now() - c.lastNew) / 1000 : 4;
    scan.innerHTML = `<b>${c.kind === 'start' ? 'Start' : 'End'}: scan your inventory</b>
      <div class="help">Open the inventory (I). Click <b>each tab</b> and scroll it to the bottom. A page is taken when the view holds still. <b>Keep the mouse off the items.</b></div>
      ${c.map ? `<div>Map: <b>${c.map.name}</b></div>` : ''}
      <div class="chips">${COUNTED_TABS.map((t) => `<span class="${c.seen.has(t) ? 'done' : ''}">${c.seen.has(t) ? '✓ ' : ''}${t}${c.pages[t] ? ' ' + c.pages[t].length : ''}</span>`).join('')}</div>
      <div>${missing.length ? `Still to do: <b>${missing.join(', ')}</b>` : left > 0 ? `<span class="ok">All tabs read. Finishing in ${Math.ceil(left)} s</span> (scroll on for more pages)` : '<span class="ok">Finishing…</span>'}</div>`;
  }
  const res = S.result, box = $('res');
  box.hidden = !res;
  if (res) {
    box.innerHTML = `<b>Session result</b><div class="kv">
      <span>Net mesos/hr incl. items</span><b>${fmt(res.net_per_hr)}</b>
      <span>EXP/hr</span><b>${fmt(res.exp_per_hr)}${res.pct_per_hr != null ? ` (${res.pct_per_hr.toFixed(1)}%/hr)` : ''}</b>
      <span>Mesos/hr</span><span>${fmt(res.mesos_per_hr)}</span>
      <span>Minutes</span><span>${res.minutes}${res.paused_minutes > 0.05 ? ` (+${res.paused_minutes} paused)` : ''}</span></div>
`;
  }
  $('note').textContent = api.lastNote() || '';
}

export const popoutOpen = () => !!(pip && !pip.closed);
