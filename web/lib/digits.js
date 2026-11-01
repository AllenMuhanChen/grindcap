// Inventory stack numbers in the game's own font: a port of src/grindcap/digits.py.
//
// The game draws at a lower resolution (e.g. 1366x768) and stretches it to the window, which blurs
// the digits. So the inventory is first resampled back to game ("native") pixels: the scale comes from
// the slot pitch (36 native px), the sub-pixel offset is the one that gives the sharpest picture. Then
// every digit lands on the same pixels as the templates, read left to right at fixed advances.
import { gray, resample, laplacianMeanAbs, mat } from './img.js';

const DIGITS = '0123456789';
const ADV = Object.fromEntries([...DIGITS].map((d) => [d, d === '1' ? 5 : 8]));
const FONT_H = 11, SLOT_PITCH = 36, DIGIT_TOP = 20, MAX_DIGITS = 5;
const END_COST = 0.45, SEARCH = 4, TIE = 0.06, DIFF_GREY = 60;
const NATIVE_W = [800, 1024, 1280, 1366, 1600, 1920], NATIVE_H = [600, 720, 768, 900, 1080];

export function nativeScale(pitchX, frame) {
  const s = pitchX / SLOT_PITCH;
  if (Math.abs(s - 1) < 0.04) return [1, 1];
  const near = (list, v) => list.reduce((a, b) => (Math.abs(v / b - s) < Math.abs(v / a - s) ? b : a));
  const nw = near(NATIVE_W, frame.w), nh = near(NATIVE_H, frame.h);
  const sx = Math.abs(frame.w / nw - s) / s < 0.04 ? frame.w / nw : s;
  const sy = Math.abs(frame.h / nh - s) / s < 0.04 ? frame.h / nh : s;
  return [sx, sy];
}

/** Part of the frame resampled to native pixels: grey `img` (+ `color`), covering native u0.., v0... */
export class NativeView {
  constructor(img, u0, v0, sx, sy, px = 0, py = 0, color = null) {
    Object.assign(this, { img, u0, v0, sx, sy, px, py, color });
  }
  toNative(x, y) {
    return [Math.round((x - (this.sx - 1) / 2 - this.px) / this.sx), Math.round((y - (this.sy - 1) / 2 - this.py) / this.sy)];
  }
  crop(u, v, w, h) {
    const a = u - this.u0, b = v - this.v0;
    if (a < 0 || b < 0 || b + h > this.img.h || a + w > this.img.w) return null;
    const out = new Float32Array(w * h);
    for (let y = 0; y < h; y++) out.set(this.img.data.subarray((b + y) * this.img.w + a, (b + y) * this.img.w + a + w), y * w);
    return out;
  }
}

/** Resample screen box [x, y, w, h] to native pixels, choosing the sharpest sub-pixel offset. */
export function nativeView(frame, box, sx, sy, color = false, steps = 10) {
  const g = gray(frame);
  const [x, y, w, h] = box;
  if (sx === 1 && sy === 1) {
    const x0 = Math.max(0, Math.trunc(x)), y0 = Math.max(0, Math.trunc(y));
    const cw = Math.min(frame.w, Math.trunc(x + w)) - x0, ch = Math.min(frame.h, Math.trunc(y + h)) - y0;
    const sub = (m) => { const out = mat(cw, ch, m.c); for (let r = 0; r < ch; r++) out.data.set(m.data.subarray(((y0 + r) * m.w + x0) * m.c, ((y0 + r) * m.w + x0 + cw) * m.c), r * cw * m.c); return out; };
    return new NativeView(sub(g), x0, y0, 1, 1, 0, 0, color ? sub(frame) : null);
  }
  const u0 = Math.floor(x / sx), v0 = Math.floor(y / sy);
  const nw = Math.ceil(w / sx) + 1, nh = Math.ceil(h / sy) + 1;
  const offs = (s) => Array.from({ length: steps }, (_, i) => s * (i / steps - 0.5));
  const argmax = (arr, f) => { let b = arr[0], bv = -Infinity; for (const a of arr) { const v = f(a); if (v > bv) { bv = v; b = a; } } return b; };
  const px = argmax(offs(sx), (p) => laplacianMeanAbs(resample(g, u0, v0, nw, nh, sx, sy, p, 0)));
  const py = argmax(offs(sy), (p) => laplacianMeanAbs(resample(g, u0, v0, nw, nh, sx, sy, px, p)));
  return new NativeView(resample(g, u0, v0, nw, nh, sx, sy, px, py), u0, v0, sx, sy, px, py,
    color ? resample(frame, u0, v0, nw, nh, sx, sy, px, py) : null);
}

/** Colour pixels of one slot (native top-left u, v) plus `pad` px around it, edges replicated. */
export function slotPatch(view, u, v, size = 32, padPx = 4) {
  if (!view.color) return null;
  const n = size + 2 * padPx, a = u - view.u0 - padPx, b = v - view.v0 - padPx, C = view.color;
  const out = mat(n, n, 3);
  // numpy slicing clips to the image; the missing part is filled by replicating the crop's edge
  const xa = Math.max(0, a), xb = Math.min(C.w, Math.max(0, a + n)), ya = Math.max(0, b), yb = Math.min(C.h, Math.max(0, b + n));
  if (xb <= xa || yb <= ya) return null;
  for (let y = 0; y < n; y++) {
    const sy = Math.min(yb - 1, Math.max(ya, b + y));
    for (let x = 0; x < n; x++) {
      const sx = Math.min(xb - 1, Math.max(xa, a + x));
      for (let k = 0; k < 3; k++) out.data[(y * n + x) * 3 + k] = C.data[(sy * C.w + sx) * 3 + k];
    }
  }
  return out;
}

function glyphMask(t, w, h, dark = 100) {
  const d = (x, y) => t[y * w + x] < dark;
  const m = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const lr = x > 0 && x < w - 1 && d(x - 1, y) && d(x + 1, y);
      const ud = y > 0 && y < h - 1 && d(x, y - 1) && d(x, y + 1);
      m[y * w + x] = d(x, y) || lr || ud ? 1 : 0;
    }
  }
  return m;
}

class Template {
  constructor(img, mask, w) {
    this.img = img; this.mask = mask; this.w = w;
    const idx = []; for (let i = 0; i < mask.length; i++) if (mask[i]) idx.push(i);
    this.idx = idx;
    let mu = 0; for (const i of idx) mu += img[i]; mu /= idx.length || 1;
    const zn = idx.map((i) => img[i] - mu);
    const n = Math.hypot(...zn) || 1;
    this.zn = zn.map((v) => v / n);
  }
  cost(p) {
    let mu = 0; for (const i of this.idx) mu += p[i]; mu /= this.idx.length || 1;
    let n2 = 0, dot = 0;
    for (let k = 0; k < this.idx.length; k++) { const v = p[this.idx[k]] - mu; n2 += v * v; dot += v * this.zn[k]; }
    const n = Math.sqrt(n2);
    return n < 1e-6 ? 1 : 1 - dot / n;
  }
}

export class StackDigits {
  /** builtin / taught: {offset: [x, y], digits: {d: [flat 11 x w arrays]}} */
  constructor(builtin, taught = null) {
    this.offset = (taught && taught.offset) || builtin.offset || [0, DIGIT_TOP];
    this.templates = {};
    for (const d of DIGITS) {
      const ex = [...((taught && taught.digits[d]) || []), ...(builtin.digits[d] || [])];
      if (!ex.length) continue;
      const w = ADV[d], n = w * FONT_H;
      const t = new Float32Array(n);
      for (let i = 0; i < n; i++) t[i] = median(ex.map((e) => e[i]));
      const m = glyphMask(t, w, FONT_H);
      if (ex.length >= 3) {   // holes inside a digit show the icon behind: leave pixels that vary out
        for (let i = 0; i < n; i++) if (m[i] && median(ex.map((e) => Math.abs(e[i] - t[i]))) >= 40) m[i] = 0;
      }
      this.templates[d] = new Template(t, m, w);
    }
  }

  readNumber(view, u, v) {
    let text = ''; const costs = [];
    while (text.length < MAX_DIGITS) {
      const scored = [];
      for (const [d, t] of Object.entries(this.templates)) {
        const p = view.crop(u, v, ADV[d], FONT_H);
        if (p) { const c = t.cost(p); if (c < END_COST) scored.push([c, d, p]); }
      }
      if (!scored.length) break;
      scored.sort((a, b) => a[0] - b[0] || (a[1] < b[1] ? -1 : 1));
      let [bc, best, p] = scored[0];
      if (scored.length > 1 && scored[1][0] - bc < TIE) {
        best = this.tiebreak(best, scored[1][1], p);
        bc = scored.find((s) => s[1] === best)[0];
      }
      text += best; costs.push(+bc.toFixed(3)); u += ADV[best];
    }
    if (text.startsWith('0')) return { value: null, text, costs };
    return { value: text ? parseInt(text, 10) : null, text, costs };
  }

  tiebreak(a, b, p) {
    const ta = this.templates[a], tb = this.templates[b];
    if (ta.w !== tb.w) return a;
    let da = 0, db = 0, n = 0;
    for (let i = 0; i < ta.img.length; i++) {
      if ((ta.mask[i] || tb.mask[i]) && Math.abs(ta.img[i] - tb.img[i]) > DIFF_GREY) {
        da += Math.abs(p[i] - ta.img[i]); db += Math.abs(p[i] - tb.img[i]); n++;
      }
    }
    if (!n) return a;
    return db < da ? b : a;
  }

  firstCost(view, u, v) {
    let best = END_COST;
    for (const [d, t] of Object.entries(this.templates)) {
      if (d === '0') continue;
      const p = view.crop(u, v, ADV[d], FONT_H);
      if (p) best = Math.min(best, t.cost(p));
    }
    return best;
  }

  locate(view, origins) {
    const [ox, oy] = this.offset;
    let best = [ox, oy], bs = null;
    for (let dy = -SEARCH; dy <= SEARCH; dy++) {
      for (let dx = -SEARCH; dx <= SEARCH; dx++) {
        let s = 0;
        for (const [u, v] of origins) s += this.firstCost(view, u + ox + dx, v + oy + dy);
        if (bs === null || s < bs - 1e-9) { best = [ox + dx, oy + dy]; bs = s; }
      }
    }
    return best;
  }

  pageView(frame, boxes, pitchX, color = false) {
    const [sx, sy] = nativeScale(pitchX, frame);
    const x0 = Math.min(...boxes.map((b) => b[0])) - 4 * sx, y0 = Math.min(...boxes.map((b) => b[1])) - 4 * sy;
    const x1 = Math.max(...boxes.map((b) => b[0] + b[2])) + 4 * sx, y1 = Math.max(...boxes.map((b) => b[1] + b[3])) + 4 * sy;
    return nativeView(frame, [x0, y0, x1 - x0, y1 - y0], sx, sy, color);
  }

  slotOrigins(view, boxes, pitchX, pitchY, first) {
    const [fu, fv] = view.toNative(first[0], first[1]);
    const pu = Math.round(pitchX / view.sx), pv = pitchY ? Math.round(pitchY / view.sy) : 0;
    return boxes.map((b) => [fu + Math.round((b[0] - first[0]) / pitchX) * pu,
                             fv + (pitchY ? Math.round((b[1] - first[1]) / pitchY) * pv : 0)]);
  }

  readView(view, origins) {
    const [ox, oy] = this.locate(view, origins);
    this.lastOffset = [ox, oy];
    return origins.map(([u, v]) => this.readNumber(view, u + ox, v + oy));
  }

  /** Pixels covered by a reading's digits (grown by 1 px) in an h x w image whose top-left is native
   * pixel (u0, v0) relative to the digit start. Keeps stack numbers out of icon matching. */
  digitMask(reading, h, w, u0, v0) {
    const m = new Uint8Array(w * h);
    let x = -u0;
    for (const d of reading.text) {
      const t = this.templates[d];
      if (t) {
        for (let i = 0; i < t.mask.length; i++) {
          if (!t.mask[i]) continue;
          const yy = Math.floor(i / t.w) - v0, xx = (i % t.w) + x;
          if (yy >= 0 && yy < h && xx >= 0 && xx < w) m[yy * w + xx] = 1;
        }
      }
      x += ADV[d];
    }
    const out = new Uint8Array(w * h);   // 3x3 dilation
    for (let y = 0; y < h; y++) for (let xx = 0; xx < w; xx++) {
      let on = 0;
      for (let j = -1; j <= 1 && !on; j++) for (let i = -1; i <= 1; i++) {
        const a = y + j, b = xx + i;
        if (a >= 0 && a < h && b >= 0 && b < w && m[a * w + b]) { on = 1; break; }
      }
      out[y * w + xx] = on;
    }
    return out;
  }
}

function median(a) {
  const s = Float64Array.from(a).sort(), n = s.length;
  return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
}
