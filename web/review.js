// Review panel: what was read, with the pictures it was read from, and corrections.
// Like the Python app's review page: status (with the meso field as captured), unrecognised icons
// with the item data's closest guesses, every item with its slot pictures, and the captured pages.
// Corrections go into S.fixes and are applied by session.withFixes; nothing here changes what was read.
import { withFixes } from './lib/session.js';
import { flat as statFlat } from './lib/stats.js';

const STAT_ROWS = [['level', 'Level'], ['ap', 'AP left'], ['str', 'STR'], ['dex', 'DEX'], ['int', 'INT'], ['luk', 'LUK'], ['hp', 'Max HP'], ['mp', 'Max MP'],
  ['attack_min', 'Attack (min)'], ['attack_max', 'Attack (max)'], ['wdef', 'Weapon def'], ['magic', 'Magic'], ['mdef', 'Magic def'], ['accuracy', 'Accuracy'],
  ['avoid', 'Avoid'], ['hands', 'Hands'], ['speed', 'Speed %'], ['jump', 'Jump %'], ['fame', 'Fame']];

const esc = (v) => String(v ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt = (v) => (v == null ? '–' : Number(v).toLocaleString());
const KINDS = ['start', 'end'];
const open = new Set();          // item rows opened to show their slots
let showAll = false, bound = false, shownVersion = -1;

export function renderReview(el, S, h) {
  if (!S.start) { el.innerHTML = ''; shownVersion = -1; return; }
  if (shownVersion === S.reviewVersion && el.innerHTML) return;   // nothing changed: don't disturb typing
  shownVersion = S.reviewVersion;
  const snaps = { start: S.start, end: S.end };
  const eff = { start: withFixes(S.start, 'start', S.fixes, h.nameOf), end: withFixes(S.end, 'end', S.fixes, h.nameOf) };
  const looks = { ...(S.start.looks || {}), ...((S.end && S.end.looks) || {}) };
  if (!bound) { bind(el, S, h); bound = true; }
  el._ctx = { S, h, looks };

  // ---- status
  const field = (kind, k) => {
    const snap = snaps[kind];
    if (!snap) return '–';
    const fix = S.fixes.status[kind]?.[k];
    return `<input class="st" data-kind="${kind}" data-k="${k}" value="${esc(fix ?? '')}" placeholder="${esc(snap[k] ?? 'not read')}" title="read: ${esc(snap[k])}${fix != null && fix !== '' ? ' (you fixed it)' : ''}">`;
  };
  const mapCell = (kind) => {
    const snap = snaps[kind], m = snap.map, fix = S.fixes.status[kind]?.map;
    return `<input class="mapfix" data-kind="${kind}" list="mapnames" value="${esc(fix ?? '')}" placeholder="${esc(m ? m.name : 'not read')}" title="${m ? `read: ${esc((m.raw || []).join(' / '))}${m.matched ? '' : ' (not in the map list)'}` : 'the minimap was not visible'}">
      ${snap.map_picture ? `<br><img class="meso" src="${snap.map_picture}" alt="minimap title">` : ''}`;
  };
  const mesoPics = (snap) => {
    const list = snap.meso_pictures || (snap.meso_picture ? [{ value: snap.mesos, pages: [], img: snap.meso_picture }] : []);
    if (!list.length) return '<span class="mute">–</span>';
    return list.map((p) => `<div class="shot"><img class="meso" src="${p.img}" alt="meso field"><span class="small ${p.value === snap.mesos ? '' : 'mute'}">read ${p.value == null ? 'nothing' : fmt(p.value)}${p.pages.length ? ` · ${esc(p.pages.join(', '))}` : ''}${p.value === snap.mesos && list.length > 1 ? ' · used' : ''}</span></div>`).join('');
  };
  let html = `<h3>Status read from the screen</h3>
    <table><tr><th>Snapshot</th><th class="l">Map</th><th>Level</th><th class="l">EXP <span class="mute small">(as captured)</span></th><th class="l">Mesos <span class="mute small">(meso field as captured)</span></th></tr>
    ${KINDS.filter((k) => snaps[k]).map((k) => `<tr><td>${k} <span class="mute">${esc(snaps[k].when)}</span>
      ${snaps[k].exp_checked ? '' : '<span class="bad" title="EXP did not fit the EXP table">EXP unchecked</span>'}
      ${snaps[k].mesos_changed ? `<span class="bad" title="different totals on different pages; ${k === 'end' ? 'the first (when End was pressed)' : 'the last (when the start scan finished)'} is used">mesos changed during the scan</span>`
        : snaps[k].mesos_checked ? '' : `<span class="bad" title="pages read: ${esc((snaps[k].mesos_reads || []).join(', '))}">mesos unchecked</span>`}</td>
      <td class="l">${mapCell(k)}</td>
      <td>${field(k, 'level')}</td>
      <td class="l">${field(k, 'exp')}${snaps[k].exp_picture ? `<br><img class="meso" src="${snaps[k].exp_picture}" alt="EXP">` : ''}</td>
      <td class="l">${field(k, 'mesos')}${mesoPics(snaps[k])}</td></tr>`).join('')}
    </table><p class="mute">Type a value to correct a misread; clear it to go back to what was read.</p>`;
  // ---- character stats (stat window, optional)
  {
    const ks = KINDS.filter((k) => snaps[k]);
    const read = Object.fromEntries(ks.map((k) => [k, statFlat(snaps[k].stats?.values)]));
    const cell = (kind, key) => {
      const st = snaps[kind].stats, v = read[kind][key], fix = S.fixes.status[kind]?.stats?.[key];
      const parts = st?.values?.[key];
      const how = parts && parts.base != null ? ` (${parts.base}+${parts.bonus})` : '';
      return `<input class="statfix" data-kind="${kind}" data-k="${key}" value="${esc(fix ?? '')}" placeholder="${esc(v ?? '–')}" title="${v == null ? 'not read' : `read: ${esc(parts?.raw || v)}`}${fix != null ? ' (you fixed it)' : ''}">${how ? `<span class="mute small">${how}</span>` : ''}`;
    };
    const any = ks.some((k) => snaps[k].stats);
    html += `<h3>Character stats <span class="mute small">from the stat window (S), if it was open during a scan</span></h3>`;
    html += `<table class="stats"><tr><th class="l">Stat</th>${ks.map((k) => `<th>${k}${snaps[k].stats && !snaps[k].stats.ok ? ` <span class="bad" title="${esc(snaps[k].stats.why)}">check</span>` : ''}</th>`).join('')}</tr>
      ${STAT_ROWS.map(([key, name]) => `<tr><td class="l">${name}</td>${ks.map((k) => `<td>${cell(k, key)}</td>`).join('')}</tr>`).join('')}</table>`;
    html += any ? `<div class="pages">${ks.filter((k) => snaps[k].stats?.picture).map((k) => `<figure><a href="${snaps[k].stats.picture}" target="_blank"><img src="${snaps[k].stats.picture}" alt="stat window"></a><figcaption>${k}: stat window as captured</figcaption></figure>`).join('')}</div>`
      : '<p class="mute">No stat window read in this session. Open it (S) during the Start or End scan to save your stats with the session, or type them in above.</p>';
  }
  html += '<p class="mute small">Naming an icon here also teaches this browser: later scans name it by itself (export or clear them under "icons you named" at the bottom of the page).</p>';

  // ---- unrecognised icons
  const slotsOf = (kind, key) => (eff[kind] ? Object.values(eff[kind].tabs).flat(2).filter((s) => s.look === key) : []);
  const unknown = Object.entries(looks).filter(([key, l]) => typeof l.id !== 'number' && l.id !== 'ignore' && S.fixes.looks[key] == null);
  html += `<h3>Not recognised (${unknown.length})</h3>`;
  html += unknown.length ? `<div class="cards">${unknown.map(([key, l]) => {
    const n = KINDS.map((k) => slotsOf(k, key).reduce((a, s) => a + s.qty, 0));
    const m = l.match || {};
    return `<div class="card"><img class="slot" src="${l.crop || ''}" alt="">
      <div><b>${esc(l.name)}</b> <span class="mute">start ${n[0]} · end ${S.end ? n[1] : '–'}</span>
      <div class="mute small">${esc(m.why || 'no item data loaded')}</div>
      <div class="cands">${(m.cands || []).map((c) => `<button class="pick" data-key="${key}" data-id="${c.id}" title="score ${c.score} (lower = closer)">${esc(c.name)} <span class="mute">${c.score}</span></button>`).join('')}</div>
      <div class="row"><input class="search" data-key="${key}" list="itemnames" placeholder="type an item name"><button class="pick" data-key="${key}" data-id="ignore" title="not an item / don't count it">Don't count</button></div></div></div>`;
  }).join('')}</div>` : '<p class="mute">None: every icon was named.</p>';

  // ---- items
  const ids = new Set([...Object.keys(eff.start.items), ...Object.keys(eff.end ? eff.end.items : {})]);
  const rows = [...ids].map((id) => {
    const a = eff.start.items[id]?.qty || 0, b = eff.end ? eff.end.items[id]?.qty || 0 : null;
    const price = h.priceOf(isNaN(+id) ? id : +id);
    return { id, name: (eff.end?.items[id] || eff.start.items[id]).name || id, a, b, change: b == null ? null : b - a, price, value: b == null || price == null ? null : (b - a) * price };
  }).filter((r) => showAll || !S.end || r.change !== 0)
    .sort((x, y) => Math.abs(y.value || 0) - Math.abs(x.value || 0) || Math.abs(y.change || 0) - Math.abs(x.change || 0) || x.name.localeCompare(y.name));
  html += `<h3>${S.end ? 'Items' : 'Items in the start snapshot'} <label class="mute small"><input type="checkbox" id="showAll" ${showAll ? 'checked' : ''}> show unchanged</label></h3>
    <table class="items"><tr><th></th><th>Item</th><th>How it was named</th><th>Before</th><th>After</th><th>Change</th><th>Price</th><th>Value</th></tr>`;
  for (const r of rows) {
    const slots = KINDS.flatMap((k) => (eff[k] ? Object.values(eff[k].tabs).flat(2).filter((s) => String(s.id) === r.id).map((s) => ({ ...s, kind: k })) : []));
    const pic = slots.find((s) => s.crop)?.crop;
    const lk = [...new Set(slots.map((s) => s.look))].map((k) => looks[k]).filter(Boolean);
    const fixedName = slots.some((s) => s.fixedName), fixedQty = slots.some((s) => s.fixedQty);
    const m = lk.find((l) => l.match && l.match.ratio)?.match;
    const how = fixedName ? '<span class="tag">you named it</span>'
      : slots.some((s) => s.how === 'from grindcap-gui') ? '<span class="tag" title="named in grindcap-gui (the Python app)">from grindcap-gui</span>'
      : isNaN(+r.id) ? '<span class="tag bad">not recognised</span>'
      : m ? `<span class="tag" title="score ${m.score}; next: ${esc(m.runnerUp)}">${m.ratio}× better than ${esc(m.runnerUp)}</span>` : '<span class="tag">re-checked look</span>';
    html += `<tr class="itemrow" data-id="${esc(r.id)}"><td>${pic ? `<img class="slot" src="${pic}" alt="">` : ''}</td>
      <td class="l">${esc(r.name)} ${fixedQty ? '<span class="tag">count fixed</span>' : ''}</td><td class="l">${how}</td>
      <td>${fmt(r.a)}</td><td>${fmt(r.b)}</td><td>${r.change > 0 ? '+' : ''}${fmt(r.change)}</td><td><input class="price" data-id="${esc(r.id)}" value="${h.userPrice(r.id) ?? ''}" placeholder="${h.basePrice(r.id) == null ? 'price?' : fmt(h.basePrice(r.id))}" title="Mesos each. Your price is used in every session; clear it to go back to ${h.basePrice(r.id) == null ? 'no price' : 'the NPC price ' + fmt(h.basePrice(r.id))}."></td><td>${fmt(r.value)}</td></tr>`;
    if (open.has(r.id)) {
      html += `<tr class="detail"><td colspan="8">${KINDS.filter((k) => eff[k]).map((k) => `<div class="col"><b>${k}</b><div class="slotgrid">${slots.filter((s) => s.kind === k).map((s) => `
        <div class="slotbox"><img class="slot" src="${s.crop || ''}" alt="">
          <div class="small mute">${esc(s.ref.split(':')[1] || s.ref)} · read "${esc(s.text || '')}"</div>
          <input class="qty" type="number" min="0" data-kind="${k}" data-ref="${esc(s.ref)}" value="${s.qty}" title="stack count; change it if the number was misread">
          <input class="search" data-key="${s.look}" list="itemnames" placeholder="wrong item? type its name"></div>`).join('') || '<span class="mute">none</span>'}</div></div>`).join('')}</td></tr>`;
    }
  }
  html += '</table><p class="mute">Click a row to see the slots it was read from, fix a count, or rename a look (renaming applies to every slot with that icon).</p>';

  // ---- pages
  html += '<h3>Pages captured</h3>' + KINDS.filter((k) => snaps[k]).map((k) => `<div><b>${k}</b><div class="pages">${(snaps[k].pictures || []).map((p) =>
    `<figure><a href="${p.img}" target="_blank"><img src="${p.img}" alt=""></a><figcaption>${esc(p.tab)} ${p.n}</figcaption></figure>`).join('') || '<span class="mute">not kept (too big for browser storage)</span>'}</div></div>`).join('');

  // datalist of item names for the search boxes
  if (!document.getElementById('mapnames') && h.maps && h.maps.length) {
    const dl = document.createElement('datalist'); dl.id = 'mapnames';
    dl.innerHTML = [...new Set(h.maps.map((m) => m.name).filter(Boolean))].sort().map((n) => `<option value="${esc(n)}">`).join('');
    document.body.appendChild(dl);
  }
  if (!document.getElementById('itemnames')) {
    const dl = document.createElement('datalist'); dl.id = 'itemnames';
    const names = [...new Set(Object.values(S.itemdb.items).map((i) => i.name))].sort();
    dl.innerHTML = names.map((n) => `<option value="${esc(n)}">`).join('');
    document.body.appendChild(dl);
  }
  el.innerHTML = html;
}

function bind(el, S0, h0) {
  el.addEventListener('click', (e) => {
    const { S, h } = el._ctx;
    const b = e.target.closest('button.pick');
    if (b) {
      const id = b.dataset.id === 'ignore' ? 'ignore' : +b.dataset.id;
      S.fixes.looks[b.dataset.key] = id; h.learn(b.dataset.key, id, id === 'ignore' ? 'ignored' : 'picked a guess'); h.recompute(); return;
    }
    if (e.target.closest('input')) return;              // typing a price shouldn't open the row
    const row = e.target.closest('tr.itemrow');
    if (row) { const id = row.dataset.id; open.has(id) ? open.delete(id) : open.add(id); S.reviewVersion++; h.recompute(); }
  });
  el.addEventListener('change', (e) => {
    const { S, h } = el._ctx;
    const t = e.target;
    if (t.id === 'showAll') { showAll = t.checked; h.recompute(); return; }
    if (t.classList.contains('st')) {
      const v = t.value.replace(/[^\d]/g, '');
      if (v === '') delete S.fixes.status[t.dataset.kind][t.dataset.k]; else S.fixes.status[t.dataset.kind][t.dataset.k] = +v;
      h.recompute();
    } else if (t.classList.contains('statfix')) {
      const v = t.value.replace(/[^\d]/g, ''), st = S.fixes.status[t.dataset.kind];
      st.stats = st.stats || {};
      if (v === '') delete st.stats[t.dataset.k]; else st.stats[t.dataset.k] = +v;
      h.recompute();
    } else if (t.classList.contains('mapfix')) {
      const v = t.value.trim();
      if (v === '') delete S.fixes.status[t.dataset.kind].map; else S.fixes.status[t.dataset.kind].map = v;
      h.recompute();
    } else if (t.classList.contains('price')) {
      const v = t.value.replace(/[^\d.]/g, '');
      h.setPrice(t.dataset.id, v === '' ? null : +v);
    } else if (t.classList.contains('qty')) {
      S.fixes.qty[`${t.dataset.kind}|${t.dataset.ref}`] = Math.max(0, +t.value || 0);
      h.recompute();
    } else if (t.classList.contains('search')) {
      // case, spaces and punctuation don't matter (’ vs ', "skeledogs bone"); a part of a name that fits one item works too
      const norm = (x) => (x || '').toLowerCase().normalize('NFKD').replace(/[^a-z0-9]/g, '');
      const want = norm(t.value), items = S.itemdb.items;
      let ids = want ? Object.keys(items).filter((k) => norm(items[k].name) === want) : [];
      if (!ids.length && want.length >= 4) ids = Object.keys(items).filter((k) => norm(items[k].name).includes(want));
      const names = [...new Set(ids.map((k) => items[k].name))];
      if (names.length === 1) {
        const id = +ids.find((k) => h.icons?.has?.(+k)) || +ids[0];
        t.value = names[0]; t.style.outline = '';
        S.fixes.looks[t.dataset.key] = id; h.learn(t.dataset.key, id, 'typed the name'); h.recompute();
      } else {
        t.style.outline = '2px solid var(--bad)';
        t.title = names.length ? `Several items fit: ${names.slice(0, 8).join(', ')}${names.length > 8 ? ', ...' : ''}` : 'No item with that name in the item data';
      }
    }
  });
}
