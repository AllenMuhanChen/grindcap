// Browser storage in IndexedDB (localStorage holds only ~5 MB: 2-4 sessions with pictures).
// kv: the running session's pieces and your corrections, kept in memory and written through.
// sessions: one record per finished session {id, name, start, end, fixes, live, pauses, result, saved}.
const DB = 'grindcap', VER = 1;
let db = null;
const mem = new Map();

const req = (r) => new Promise((ok, bad) => { r.onsuccess = () => ok(r.result); r.onerror = () => bad(r.error); });
const tx = (store, mode = 'readonly') => db.transaction(store, mode).objectStore(store);

export async function openStore() {
  try {
    const r = indexedDB.open(DB, VER);
    r.onupgradeneeded = () => {
      const d = r.result;
      if (!d.objectStoreNames.contains('kv')) d.createObjectStore('kv');
      if (!d.objectStoreNames.contains('sessions')) d.createObjectStore('sessions', { keyPath: 'id' });
    };
    db = await req(r);
    const keys = await req(tx('kv').getAllKeys()), vals = await req(tx('kv').getAll());
    keys.forEach((k, i) => mem.set(k, vals[i]));
    // one-time move from the localStorage version
    for (const k of ['start', 'end', 'live', 'pauses', 'fixes', 'corrections']) {
      const v = localStorage.getItem('grindcap.' + k);
      if (v != null && !mem.has(k)) { try { set(k, JSON.parse(v)); } catch { /* bad json */ } }
      localStorage.removeItem('grindcap.' + k);
    }
    if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});
  } catch (e) {
    console.warn('IndexedDB unavailable, nothing will be kept after a reload', e);
    db = null;
  }
}

export const get = (k) => (mem.has(k) ? mem.get(k) : null);
export function set(k, v) {
  mem.set(k, v);
  if (db) tx('kv', 'readwrite').put(v, k).onerror = (e) => console.warn('save failed', k, e.target.error);
}

const light = (r) => ({ id: r.id, name: r.name, character: r.character || null, tags: r.tags || [],
  map: r.meta?.map ?? r.start?.map?.name ?? null, level: r.meta?.level ?? r.start?.level ?? null, level_end: r.meta?.level_end ?? r.end?.level ?? null, start_time: r.start?.time, end_time: r.end?.time,
  result: r.result && { minutes: r.result.minutes, exp_per_hr: r.result.exp_per_hr, net_per_hr: r.result.net_per_hr, mesos_per_hr: r.result.mesos_per_hr, revenue_per_hr: r.result.revenue_per_hr, cost_per_hr: r.result.cost_per_hr, pct_per_hr: r.result.pct_per_hr ?? null } });

/** Saves a finished session and keeps the light index (kv "sessions") in step. */
export async function putSession(rec) {
  set('sessions', [light(rec), ...(get('sessions') || []).filter((x) => x.id !== rec.id)].sort((a, b) => b.id - a.id));
  if (db) await req(tx('sessions', 'readwrite').put(rec));
}
/** Rebuild the light index from the full records (after the index gained fields). */
export async function reindex(lightOf = light) {
  const all = await allSessions();
  set('sessions', all.map(lightOf).sort((a, b) => b.id - a.id));
}
/** Every saved session, in full (for the backup file). */
export async function allSessions() { return db ? req(tx('sessions').getAll()) : []; }
export async function getSession(id) { return db ? req(tx('sessions').get(id)) : null; }
export async function deleteSession(id) {
  set('sessions', (get('sessions') || []).filter((x) => x.id !== id));
  if (db) await req(tx('sessions', 'readwrite').delete(id));
}
/** Newest first, without pictures: id, name, start/end time, key figures. */
export const listSessions = () => get('sessions') || [];
export async function usage() {
  try { const e = await navigator.storage.estimate(); return e; } catch { return null; }
}
