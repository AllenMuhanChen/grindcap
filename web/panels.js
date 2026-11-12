// Movable, collapsible panels for the session view: each graph (and the text that goes with it), the results and
// the review get a title bar with a collapse button, up/down buttons and a drag handle. Order and collapsed state
// are kept in localStorage ("grindcap.panels"), so the page opens the way you left it.
const KEY = 'grindcap.panels';
const load = () => { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch { return {}; } };
const save = (st) => { try { localStorage.setItem(KEY, JSON.stringify(st)); } catch { /* private window */ } };

/** defs: [{id (the element's id), title}], all children of one parent, in the default order. The element's own
 * `hidden` (set by the app when there's nothing to show) hides the whole panel. */
export function makePanels(defs) {
  const st = load(), els = defs.map((d) => document.getElementById(d.id)).filter(Boolean);
  if (!els.length) return;
  const parent = els[0].parentNode, anchor = document.createComment('panels');
  parent.insertBefore(anchor, els[0]);
  const panels = {};
  for (const d of defs) {
    const el = document.getElementById(d.id);
    if (!el) continue;
    const p = document.createElement('div');
    p.className = 'panel'; p.dataset.id = d.id;
    p.innerHTML = `<div class="phead" draggable="true" title="Drag to move"><span class="grip">⠿</span><b>${d.title}</b><span class="pbtns">
      <button class="pup" title="Move up">↑</button><button class="pdown" title="Move down">↓</button><button class="pfold" title="Collapse / expand">▾</button></span></div><div class="pbody"></div>`;
    p.querySelector('.pbody').appendChild(el);
    panels[d.id] = p;
    // the app hides the inner element when it has nothing: hide the panel with it
    const sync = () => { p.hidden = el.hidden || (!el.childElementCount && !el.textContent.trim()); };   // empty: nothing to show
    new MutationObserver(sync).observe(el, { attributes: true, attributeFilter: ['hidden'], childList: true }); sync();
  }
  const order = [...(st.order || []).filter((id) => panels[id]), ...defs.map((d) => d.id).filter((id) => panels[id] && !(st.order || []).includes(id))];
  let at = anchor;
  for (const id of order) { at.parentNode.insertBefore(panels[id], at.nextSibling); at = panels[id]; }
  const persist = () => { st.order = [...parent.querySelectorAll(':scope > .panel')].map((p) => p.dataset.id); save(st); };
  const setFold = (p, folded) => {
    p.classList.toggle('folded', folded);
    p.querySelector('.pfold').textContent = folded ? '▸' : '▾';
    st.folded = { ...(st.folded || {}), [p.dataset.id]: folded }; save(st);
    if (!folded) for (const cv of p.querySelectorAll('canvas')) cv._redraw && cv._redraw();   // a canvas drawn while folded had no width
  };
  for (const p of Object.values(panels)) {
    if (st.folded?.[p.dataset.id]) setFold(p, true);
    p.querySelector('.pfold').onclick = () => setFold(p, !p.classList.contains('folded'));
    p.querySelector('b').ondblclick = () => setFold(p, !p.classList.contains('folded'));
    p.querySelector('.pup').onclick = () => { let q = p.previousElementSibling; while (q && q.hidden) q = q.previousElementSibling; if (q?.classList.contains('panel')) { parent.insertBefore(p, q); persist(); } };
    p.querySelector('.pdown').onclick = () => { let q = p.nextElementSibling; while (q && q.hidden) q = q.nextElementSibling; if (q?.classList.contains('panel')) { parent.insertBefore(q, p); persist(); } };
    const head = p.querySelector('.phead');
    head.addEventListener('dragstart', (e) => { e.dataTransfer.setData('text/plain', p.dataset.id); e.dataTransfer.effectAllowed = 'move'; p.classList.add('dragging'); });
    head.addEventListener('dragend', () => { p.classList.remove('dragging'); for (const q of Object.values(panels)) q.classList.remove('dropbefore', 'dropafter'); });
    p.addEventListener('dragover', (e) => {
      e.preventDefault();
      const r = p.getBoundingClientRect(), before = e.clientY < r.top + r.height / 2;
      p.classList.toggle('dropbefore', before); p.classList.toggle('dropafter', !before);
    });
    p.addEventListener('dragleave', () => p.classList.remove('dropbefore', 'dropafter'));
    p.addEventListener('drop', (e) => {
      e.preventDefault();
      const src = panels[e.dataTransfer.getData('text/plain')];
      const before = p.classList.contains('dropbefore');
      p.classList.remove('dropbefore', 'dropafter');
      if (!src || src === p) return;
      parent.insertBefore(src, before ? p : p.nextSibling); persist();
    });
  }
}
