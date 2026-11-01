// Name inventory items by their icons: a port of src/grindcap/itemdb.py.
//
// Every icon from the game's item data (maplestory.io, region MCW) is slid over the slot at native
// resolution and compared on its opaque pixels (mean squared colour difference). A quick half-size
// pass shortlists 120 icons first. The best is accepted only if it beats the best icon with a different
// name by min_ratio.
import { mat, resizeArea, sqdiffMin, decodeBlob } from './img.js';

const MIN_PIXELS = 40;

export class ItemDB {
  constructor(minRatio = 1.25, maxScore = 9000) {
    this.minRatio = minRatio; this.maxScore = maxScore;
    this.items = {}; this.icons = new Map(); this.small = new Map();
  }

  /** data = {items: {id: {name, category, price}}, icons: {id: base64 png}} (scripts/export_web_data.py) */
  async load(data, progress = () => {}) {
    this.items = data.items;
    const ids = Object.keys(data.icons);
    let n = 0;
    for (const id of ids) {
      const bin = Uint8Array.from(atob(data.icons[id]), (c) => c.charCodeAt(0));
      this.addIcon(+id, await decodeBlob(new Blob([bin], { type: 'image/png' }), true));
      if (++n % 250 === 0) { progress(`icons ${n}/${ids.length}`); await new Promise((r) => setTimeout(r)); }
    }
    progress(`${this.icons.size} icons ready`);
  }

  /** One icon from an RGBA mat (c=4): opaque pixels (alpha > 200) are the icon. */
  addIcon(id, im) {
    const N = im.w * im.h, img = mat(im.w, im.h, 3), mask = new Uint8Array(N);
    let msum = 0;
    for (let i = 0; i < N; i++) {
      img.data[3 * i] = im.data[4 * i]; img.data[3 * i + 1] = im.data[4 * i + 1]; img.data[3 * i + 2] = im.data[4 * i + 2];
      if (im.data[4 * i + 3] > 200) { mask[i] = 1; msum++; }
    }
    if (msum < MIN_PIXELS) return;
    this.icons.set(id, { img, mask, msum });
    const sw = Math.max(1, im.w >> 1), sh = Math.max(1, im.h >> 1);   // half-size copy for the first pass
    const si = resizeArea(img, sw, sh);
    const mm = mat(im.w, im.h, 1); for (let i = 0; i < N; i++) mm.data[i] = mask[i];
    const sm = resizeArea(mm, sw, sh), smask = new Uint8Array(sw * sh);
    let ssum = 0;
    for (let i = 0; i < sw * sh; i++) if (sm.data[i] > 0.99) { smask[i] = 1; ssum++; }
    this.small.set(id, { img: si, mask: smask, msum: ssum });
  }

  get ready() { return this.icons.size > 0; }
  name(id) { return (this.items[id] || {}).name || `#${id}`; }

  shortlist(patch, k = 120) {
    const sp = resizeArea(patch, patch.w >> 1, patch.h >> 1);
    const scored = [];
    for (const [id, s] of this.small) {
      if (s.img.h > sp.h || s.img.w > sp.w || s.msum < 3) continue;
      scored.push([sqdiffMin(sp, s.img, s.mask, s.msum), id]);
    }
    scored.sort((a, b) => a[0] - b[0]);
    return scored.slice(0, k).map((s) => s[1]);
  }

  rank(patch, k = 120) {
    const ids = k && this.icons.size > k ? this.shortlist(patch, k) : [...this.icons.keys()];
    const out = [];
    for (const id of ids) {
      const ic = this.icons.get(id);
      if (ic.img.h > patch.h || ic.img.w > patch.w) continue;
      out.push([sqdiffMin(patch, ic.img, ic.mask, ic.msum), id]);
    }
    return out.sort((a, b) => a[0] - b[0]);
  }

  /** Scores for just these ids (cheap: re-checks an icon look seen before). */
  scores(patch, ids) {
    const out = new Map();
    for (const id of ids) {
      const ic = this.icons.get(id);
      if (ic && ic.img.h <= patch.h && ic.img.w <= patch.w) out.set(id, sqdiffMin(patch, ic.img, ic.mask, ic.msum));
    }
    return out;
  }

  /** rank() for a few ids, leaving out patch pixels marked in `ignore` (the stack number). */
  rescore(patch, ignore, ids) {
    const out = [];
    for (const id of ids) {
      const { img, mask, msum } = this.icons.get(id);
      let best = null;
      for (let y = 0; y + img.h <= patch.h; y++) {
        for (let x = 0; x + img.w <= patch.w; x++) {
          let n = 0, s = 0;
          for (let j = 0; j < img.h; j++) for (let i = 0; i < img.w; i++) {
            const ti = j * img.w + i;
            if (!mask[ti] || ignore[(y + j) * patch.w + x + i]) continue;
            n++;
            const pi = ((y + j) * patch.w + x + i) * 3;
            for (let c = 0; c < 3; c++) { const d = patch.data[pi + c] - img.data[ti * 3 + c]; s += d * d; }
          }
          if (n < 0.5 * msum) continue;
          const sc = s / (3 * n);
          if (best === null || sc < best) best = sc;
        }
      }
      if (best !== null) out.push([best, id]);
    }
    return out.sort((a, b) => a[0] - b[0]);
  }

  /** The item in this slot ({id, name, score, ratio, runnerUp}) or null if nothing matches clearly. */
  identify(patch, ignore = null) {
    let ranked = this.rank(patch);
    if (ignore && ignore.some((v) => v) && ranked.length) {
      ranked = [...this.rescore(patch, ignore, ranked.slice(0, 12).map((r) => r[1])), ...ranked.slice(12)];
    }
    if (!ranked.length) return null;
    const [s0, best] = ranked[0];
    const name = this.name(best);
    const other = ranked.slice(1).find(([, i]) => this.name(i) !== name);
    const ratio = other ? (s0 > 0 ? other[0] / s0 : Infinity) : Infinity;
    if (s0 > this.maxScore || ratio < this.minRatio) {
      return { id: null, name: null, score: s0, ratio, best, bestName: name, runnerUp: other ? this.name(other[1]) : '' };
    }
    const neighbors = ranked.slice(1).filter(([, i]) => this.name(i) !== name).slice(0, 8).map(([, i]) => i);
    return { id: best, name, score: +s0.toFixed(1), ratio: +ratio.toFixed(2), runnerUp: other ? this.name(other[1]) : '', neighbors };
  }
}
