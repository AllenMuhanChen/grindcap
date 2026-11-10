// Session tags: names you make up ("bought pots", "test build", "party"), put on sessions in the review or
// on many sessions at once in the Summary list. kv "tagList" = every tag you made, in order; each session
// record carries tags: [name, ...]. Pure helpers, no DOM, so test.js can check them.

/** Trimmed, inner spaces collapsed, at most 40 characters; '' = not a tag. */
export const cleanTag = (s) => String(s ?? '').trim().replace(/\s+/g, ' ').slice(0, 40);

/** Same tag ignoring case: "Party" and "party" are one tag (the first spelling made wins). */
export const sameTag = (a, b) => cleanTag(a).toLowerCase() === cleanTag(b).toLowerCase();

/** The list with `name` in it (existing spelling kept); returns [list, the name as stored]. */
export function ensureTag(list, name) {
  const n = cleanTag(name);
  if (!n) return [list, null];
  const have = list.find((t) => sameTag(t, n));
  return have ? [list, have] : [[...list, n], n];
}

/** A session's tags with `add` added and `remove` taken out, in tag-list order (unknown ones last). */
export function editTags(tags, { add = [], remove = [] } = {}, list = []) {
  const out = (tags || []).filter((t) => !remove.some((r) => sameTag(r, t)));
  for (const a of add) if (cleanTag(a) && !out.some((t) => sameTag(t, a))) out.push(cleanTag(a));
  const pos = (t) => { const i = list.findIndex((x) => sameTag(x, t)); return i < 0 ? Infinity : i; };
  return out.map((t, i) => [t, i]).sort((a, b) => pos(a[0]) - pos(b[0]) || a[1] - b[1]).map(([t]) => t);
}

/** Rename a tag in one session's tags (merges into `to` if the session already has it). */
export const renameIn = (tags, from, to) => editTags([], { add: (tags || []).map((t) => (sameTag(t, from) ? cleanTag(to) : t)) }, []);

/** Ids between two rows of the shown order, both ends included (drag or shift-click range). */
export function rangeIds(order, a, b) {
  const i = order.indexOf(a), j = order.indexOf(b);
  if (i < 0 || j < 0) return [];
  return order.slice(Math.min(i, j), Math.max(i, j) + 1);
}

/** Colour of a tag: its place in your list picks one of 8 hues (stable until you reorder/delete). */
const HUES = [212, 145, 28, 280, 350, 180, 52, 95];
export const tagHue = (list, name) => { const i = list.findIndex((t) => sameTag(t, name)); return HUES[(i < 0 ? 0 : i) % HUES.length]; };
