// Small image toolkit: the OpenCV calls grindcap's Python readers use, in plain JS.
//
// An image ("mat") is {w, h, c, data: Float32Array} with channels interleaved. Colour mats are RGB
// (the Python side is BGR; every colour rule below names its channels, so the order doesn't matter).

export function mat(w, h, c = 1, data = null) {
  return { w, h, c, data: data || new Float32Array(w * h * c) };
}

/** ImageData (RGBA bytes) -> RGB float mat. */
export function fromImageData(id) {
  const n = id.width * id.height, out = new Float32Array(n * 3), s = id.data;
  for (let i = 0; i < n; i++) {
    out[3 * i] = s[4 * i]; out[3 * i + 1] = s[4 * i + 1]; out[3 * i + 2] = s[4 * i + 2];
  }
  return mat(id.width, id.height, 3, out);
}

/** Grey like cv2.cvtColor(BGR2GRAY) on uint8: rounded 0.299 R + 0.587 G + 0.114 B. */
export function gray(m) {
  if (m.c === 1) return m;
  const n = m.w * m.h, out = new Float32Array(n), d = m.data;
  for (let i = 0; i < n; i++) {
    out[i] = Math.round(0.299 * d[3 * i] + 0.587 * d[3 * i + 1] + 0.114 * d[3 * i + 2]);
  }
  return mat(m.w, m.h, 1, out);
}

/** Crop [x, y, w, h], clipped to the image (like numpy slicing with max(0, ...)). */
export function crop(m, x, y, w, h) {
  const x0 = Math.max(0, Math.floor(x)), y0 = Math.max(0, Math.floor(y));
  const x1 = Math.min(m.w, Math.floor(x + w)), y1 = Math.min(m.h, Math.floor(y + h));
  const cw = Math.max(0, x1 - x0), ch = Math.max(0, y1 - y0), c = m.c;
  const out = new Float32Array(cw * ch * c);
  for (let r = 0; r < ch; r++) {
    const src = ((y0 + r) * m.w + x0) * c;
    out.set(m.data.subarray(src, src + cw * c), r * cw * c);
  }
  return mat(cw, ch, c, out);
}

export function px(m, x, y, k = 0) { return m.data[(y * m.w + x) * m.c + k]; }

/** cv2.resize INTER_AREA when shrinking (exact area weights); bilinear when growing. */
export function resizeArea(m, nw, nh) {
  if (nw >= m.w && nh >= m.h) return resizeLinear(m, nw, nh);
  const sx = m.w / nw, sy = m.h / nh, c = m.c, out = new Float32Array(nw * nh * c);
  const wx = axisWeights(m.w, nw, sx), wy = axisWeights(m.h, nh, sy);
  for (let y = 0; y < nh; y++) {
    for (const [sy0, fy] of wy[y]) {
      for (let x = 0; x < nw; x++) {
        for (const [sx0, fx] of wx[x]) {
          const f = fx * fy, si = (sy0 * m.w + sx0) * c, di = (y * nw + x) * c;
          for (let k = 0; k < c; k++) out[di + k] += f * m.data[si + k];
        }
      }
    }
  }
  return mat(nw, nh, c, out);
}

function axisWeights(n, nn, s) {
  const out = [];
  for (let i = 0; i < nn; i++) {
    const a = i * s, b = (i + 1) * s, w = [];
    for (let j = Math.floor(a); j < Math.min(n, Math.ceil(b)); j++) {
      const ov = Math.min(b, j + 1) - Math.max(a, j);
      if (ov > 1e-9) w.push([j, ov / s]);
    }
    out.push(w);
  }
  return out;
}

export function resizeLinear(m, nw, nh) {
  const c = m.c, out = new Float32Array(nw * nh * c), sx = m.w / nw, sy = m.h / nh;
  for (let y = 0; y < nh; y++) {
    let fy = (y + 0.5) * sy - 0.5; if (fy < 0) fy = 0;
    const y0 = Math.min(m.h - 1, Math.floor(fy)), y1 = Math.min(m.h - 1, y0 + 1), ay = fy - y0;
    for (let x = 0; x < nw; x++) {
      let fx = (x + 0.5) * sx - 0.5; if (fx < 0) fx = 0;
      const x0 = Math.min(m.w - 1, Math.floor(fx)), x1 = Math.min(m.w - 1, x0 + 1), ax = fx - x0;
      for (let k = 0; k < c; k++) {
        const a = m.data[(y0 * m.w + x0) * c + k], b = m.data[(y0 * m.w + x1) * c + k];
        const d = m.data[(y1 * m.w + x0) * c + k], e = m.data[(y1 * m.w + x1) * c + k];
        out[(y * nw + x) * c + k] = (a * (1 - ax) + b * ax) * (1 - ay) + (d * (1 - ax) + e * ax) * ay;
      }
    }
  }
  return mat(nw, nh, c, out);
}

function cubicW(t) {           // OpenCV's bicubic kernel, A = -0.75
  const A = -0.75, x = Math.abs(t);
  if (x <= 1) return ((A + 2) * x - (A + 3)) * x * x + 1;
  if (x < 2) return ((A * x - 5 * A) * x + 8 * A) * x - 4 * A;
  return 0;
}

/** cv2.resize(..., fx=f, fy=f, INTER_CUBIC) on a uint8 grey image; result rounded to 0..255. */
export function resizeCubic(m, f) {
  const nw = Math.round(m.w * f), nh = Math.round(m.h * f), out = new Float32Array(nw * nh);
  const cl = (v, n) => (v < 0 ? 0 : v >= n ? n - 1 : v);
  const tab = (n, nn) => Array.from({ length: nn }, (_, i) => {
    const s = (i + 0.5) / f - 0.5, i0 = Math.floor(s), t = s - i0;
    return [i0, [cubicW(1 + t), cubicW(t), cubicW(1 - t), cubicW(2 - t)]];
  });
  const tx = tab(m.w, nw), ty = tab(m.h, nh);
  for (let y = 0; y < nh; y++) {
    const [y0, wy] = ty[y];
    for (let x = 0; x < nw; x++) {
      const [x0, wx] = tx[x];
      let s = 0;
      for (let j = 0; j < 4; j++) {
        const row = cl(y0 - 1 + j, m.h) * m.w;
        let r = 0;
        for (let i = 0; i < 4; i++) r += wx[i] * m.data[row + cl(x0 - 1 + i, m.w)];
        s += wy[j] * r;
      }
      out[y * nw + x] = Math.min(255, Math.max(0, Math.round(s)));
    }
  }
  return mat(nw, nh, 1, out);
}

/** cv2.threshold(THRESH_BINARY + THRESH_OTSU) on a uint8 grey image. */
export function otsu(m) {
  const hist = new Float64Array(256), n = m.w * m.h;
  for (let i = 0; i < n; i++) hist[Math.min(255, Math.max(0, Math.round(m.data[i])))]++;
  let sum = 0;
  for (let i = 0; i < 256; i++) sum += i * hist[i];
  let sumB = 0, wB = 0, best = 0, t = 0;
  for (let i = 0; i < 256; i++) {
    wB += hist[i]; if (!wB) continue;
    const wF = n - wB; if (!wF) break;
    sumB += i * hist[i];
    const mB = sumB / wB, mF = (sum - sumB) / wF, v = wB * wF * (mB - mF) ** 2;
    if (v > best) { best = v; t = i; }
  }
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) out[i] = m.data[i] > t ? 255 : 0;
  return mat(m.w, m.h, 1, out);
}

export function mean(m) {
  let s = 0;
  for (let i = 0; i < m.data.length; i++) s += m.data[i];
  return s / m.data.length;
}

export function invert(m) {
  const out = new Float32Array(m.data.length);
  for (let i = 0; i < out.length; i++) out[i] = 255 - m.data[i];
  return mat(m.w, m.h, m.c, out);
}

/** Constant border of `v` around a grey image. */
export function pad(m, t, b, l, r, v = 255) {
  const w = m.w + l + r, h = m.h + t + b, out = new Float32Array(w * h).fill(v);
  for (let y = 0; y < m.h; y++) out.set(m.data.subarray(y * m.w, (y + 1) * m.w), (y + t) * w + l);
  return mat(w, h, 1, out);
}

/** Resample to native game pixels: dst(u, v) = src(sx*(u0+u) + (sx-1)/2 + px, sy*(v0+v) + (sy-1)/2 + py),
 * bilinear, edges replicated (cv2.warpAffine with WARP_INVERSE_MAP, BORDER_REPLICATE). */
export function resample(m, u0, v0, nw, nh, sx, sy, ox, oy) {
  const c = m.c, out = new Float32Array(nw * nh * c);
  const cl = (v, n) => (v < 0 ? 0 : v >= n ? n - 1 : v);
  for (let v = 0; v < nh; v++) {
    const fy = sy * (v0 + v) + (sy - 1) / 2 + oy, y0 = Math.floor(fy), ay = fy - y0;
    const ya = cl(y0, m.h) * m.w, yb = cl(y0 + 1, m.h) * m.w;
    for (let u = 0; u < nw; u++) {
      const fx = sx * (u0 + u) + (sx - 1) / 2 + ox, x0 = Math.floor(fx), ax = fx - x0;
      const xa = cl(x0, m.w), xb = cl(x0 + 1, m.w);
      for (let k = 0; k < c; k++) {
        const p = m.data[(ya + xa) * c + k], q = m.data[(ya + xb) * c + k];
        const r = m.data[(yb + xa) * c + k], s = m.data[(yb + xb) * c + k];
        out[(v * nw + u) * c + k] = (p * (1 - ax) + q * ax) * (1 - ay) + (r * (1 - ax) + s * ax) * ay;
      }
    }
  }
  return mat(nw, nh, c, out);
}

/** mean |Laplacian| (3x3 four-neighbour kernel, reflect-101 border), a sharpness score. */
export function laplacianMeanAbs(m) {
  const { w, h, data } = m;
  const rf = (i, n) => (i < 0 ? -i : i >= n ? 2 * n - 2 - i : i);
  let s = 0;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const c = data[y * w + x];
      const l = data[y * w + rf(x - 1, w)], r = data[y * w + rf(x + 1, w)];
      const u = data[rf(y - 1, h) * w + x], d = data[rf(y + 1, h) * w + x];
      s += Math.abs(l + r + u + d - 4 * c);
    }
  }
  return s / (w * h);
}

/** Best TM_CCOEFF_NORMED position of grey template t in grey image m, searched exhaustively
 * at positions x in [x0, x1), y in [y0, y1). Returns {x, y, score}. */
export function matchCCoeff(m, t, x0 = 0, y0 = 0, x1 = null, y1 = null, step = 1) {
  x1 = Math.min(x1 ?? m.w - t.w + 1, m.w - t.w + 1);
  y1 = Math.min(y1 ?? m.h - t.h + 1, m.h - t.h + 1);
  x0 = Math.max(0, x0); y0 = Math.max(0, y0);
  const n = t.w * t.h;
  let tm = 0;
  for (let i = 0; i < n; i++) tm += t.data[i];
  tm /= n;
  const tz = new Float32Array(n);
  let tn = 0;
  for (let i = 0; i < n; i++) { tz[i] = t.data[i] - tm; tn += tz[i] * tz[i]; }
  tn = Math.sqrt(tn) || 1;
  let best = { x: -1, y: -1, score: -2 };
  for (let y = y0; y < y1; y += step) {
    for (let x = x0; x < x1; x += step) {
      let s = 0, s2 = 0, st = 0;
      for (let j = 0; j < t.h; j++) {
        const row = (y + j) * m.w + x, trow = j * t.w;
        for (let i = 0; i < t.w; i++) {
          const v = m.data[row + i];
          s += v; s2 += v * v; st += v * tz[trow + i];
        }
      }
      const varI = s2 - (s * s) / n;
      const sc = varI > 1e-6 ? st / (Math.sqrt(varI) * tn) : 0;
      if (sc > best.score) best = { x, y, score: sc };
    }
  }
  return best;
}

/** Find a template anywhere in a region at an unknown scale: coarse search on shrunken copies,
 * then refined at full size. `scales` = candidate template scale factors. Returns
 * {x, y, score, scale, w, h} in full-image coordinates, or null. */
export function findScaled(m, tmpl, scales, region = null, shrink = 4) {
  const g = gray(m), tg = gray(tmpl);
  const [rx, ry, rw, rh] = region || [0, 0, g.w, g.h];
  const reg = crop(g, rx, ry, rw, rh);
  const small = resizeArea(reg, Math.max(1, Math.round(reg.w / shrink)), Math.max(1, Math.round(reg.h / shrink)));
  const cands = [];
  for (const s of scales) {
    const tw = Math.round(tg.w * s / shrink), th = Math.round(tg.h * s / shrink);
    if (tw < 4 || th < 3 || tw > small.w || th > small.h) continue;
    const ts = resizeArea(tg, tw, th);
    const b = matchCCoeff(small, ts);
    cands.push({ ...b, scale: s });
  }
  cands.sort((a, b) => b.score - a.score);
  let best = null;
  for (const cd of cands.slice(0, 3)) {
    const tw = Math.round(tg.w * cd.scale), th = Math.round(tg.h * cd.scale);
    const ts = Math.abs(cd.scale - 1) < 1e-3 ? tg : resizeArea(tg, tw, th);
    const cx = cd.x * reg.w / small.w, cy = cd.y * reg.h / small.h;
    const r = matchCCoeff(reg, ts, Math.floor(cx - shrink - 2), Math.floor(cy - shrink - 2),
      Math.ceil(cx + shrink + 3), Math.ceil(cy + shrink + 3));
    if (!best || r.score > best.score) best = { x: r.x + rx, y: r.y + ry, score: r.score, scale: cd.scale, w: tw, h: th };
  }
  return best;
}

/** min over positions of sum(mask * (patch - tmpl)^2) / sum(mask), colour (c=3) or grey.
 * mask is per pixel (w*h), 0/1. Like cv2.matchTemplate(TM_SQDIFF, mask) min / mask.sum(). */
export function sqdiffMin(patch, tmpl, mask, msum) {
  const c = tmpl.c, tw = tmpl.w, th = tmpl.h, pw = patch.w, P = patch.data, T = tmpl.data;
  let best = Infinity;
  for (let y = 0; y + th <= patch.h; y++) {
    for (let x = 0; x + tw <= pw; x++) {
      let s = 0;
      for (let j = 0; j < th && s < best; j++) {
        const pr = ((y + j) * pw + x) * c, tr = j * tw;
        for (let i = 0; i < tw; i++) {
          if (!mask[tr + i]) continue;
          const pi = pr + i * c, ti = (tr + i) * c;
          for (let k = 0; k < c; k++) { const d = P[pi + k] - T[ti + k]; s += d * d; }
        }
      }
      if (s < best) best = s;
    }
  }
  return best / (msum * c);
}

/** Grey mat -> ImageData (for OCR and for showing crops). */
export function toImageData(m) {
  const n = m.w * m.h, d = new Uint8ClampedArray(n * 4);
  for (let i = 0; i < n; i++) {
    if (m.c === 1) { const v = m.data[i]; d[4 * i] = d[4 * i + 1] = d[4 * i + 2] = v; }
    else { d[4 * i] = m.data[3 * i]; d[4 * i + 1] = m.data[3 * i + 1]; d[4 * i + 2] = m.data[3 * i + 2]; }
    d[4 * i + 3] = 255;
  }
  return new ImageData(d, m.w, m.h);
}

/** Decode an image URL into an RGB mat (or RGBA with keepAlpha). */
export async function loadImage(url, keepAlpha = false) {
  const blob = await (await fetch(url)).blob();
  return decodeBlob(blob, keepAlpha);
}

export async function decodeBlob(blob, keepAlpha = false) {
  const bmp = await createImageBitmap(blob, { premultiplyAlpha: 'none', colorSpaceConversion: 'none' });
  const cv = new OffscreenCanvas(bmp.width, bmp.height);
  const ctx = cv.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(bmp, 0, 0);
  const id = ctx.getImageData(0, 0, bmp.width, bmp.height, { colorSpace: 'srgb' });
  if (!keepAlpha) return fromImageData(id);
  const n = bmp.width * bmp.height, out = new Float32Array(n * 4);
  for (let i = 0; i < n * 4; i++) out[i] = id.data[i];
  return mat(bmp.width, bmp.height, 4, out);
}
