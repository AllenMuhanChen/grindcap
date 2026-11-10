// Tesseract.js wrapper: the same "--psm N -c tessedit_char_whitelist=..." calls the Python side makes.
//
// Files come from web/vendor/tesseract/ when present (tests, offline use), else from jsDelivr.
import { toImageData } from './img.js';

const CDN = {
  lib: 'https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/tesseract.esm.min.js',
  worker: 'https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/worker.min.js',
  core: 'https://cdn.jsdelivr.net/npm/tesseract.js-core@5.1.1',
  lang: 'https://cdn.jsdelivr.net/npm/@tesseract.js-data/eng@1.0.0/4.0.0_best_int',
};

let ready = null;
const extra = {};   // other workers by name (the stat window reader runs beside the scan, not in its way)

async function localVendor() {
  const base = new URL('../vendor/tesseract/', import.meta.url).href;
  try {
    const r = await fetch(base + 'tesseract.esm.min.js', { method: 'HEAD' });
    if (r.ok) return { lib: base + 'tesseract.esm.min.js', worker: base + 'worker.min.js',
      core: base.slice(0, -1) + '/core', lang: base.slice(0, -1) + '/lang' };
  } catch (e) { /* no local copy */ }
  return null;
}

async function start() {
  const p = (await localVendor()) || CDN;
  const T = (await import(p.lib)).default;
  const worker = await T.createWorker('eng', 1, {
    workerPath: p.worker, corePath: p.core, langPath: p.lang, gzip: true,
    workerBlobURL: p === CDN,   // a cross-origin worker script must be wrapped in a blob URL
  });
  return { worker, params: '' };
}

/** OCR a grey mat. psm: page segmentation mode (7 = one line, 8 = one word). */
export async function ocr(m, psm, whitelist) {
  ready = ready || start();
  const t = await ready;
  const key = `${psm}|${whitelist}`;
  if (t.params !== key) {
    await t.worker.setParameters({ tessedit_pageseg_mode: String(psm), tessedit_char_whitelist: whitelist });
    t.params = key;
  }
  const cv = new OffscreenCanvas(m.w, m.h);
  cv.getContext('2d').putImageData(toImageData(m), 0, 0);
  const blob = await cv.convertToBlob({ type: 'image/png' });
  const r = await t.worker.recognize(blob);
  return (r.data.text || '').trim();
}

export function ocrReady() { ready = ready || start(); return ready; }

/** OCR with word boxes: [{text, conf, x0, y0, x1, y1}] (mat pixels). psm 11 = sparse text anywhere. */
export async function ocrWords(m, psm = 11, whitelist = '', worker = null) {
  let t;
  if (worker) t = await (extra[worker] = extra[worker] || start());
  else t = await (ready = ready || start());
  const key = `${psm}|${whitelist}`;
  if (t.params !== key) {
    await t.worker.setParameters({ tessedit_pageseg_mode: String(psm), tessedit_char_whitelist: whitelist });
    t.params = key;
  }
  const cv = new OffscreenCanvas(m.w, m.h);
  cv.getContext('2d').putImageData(toImageData(m), 0, 0);
  const blob = await cv.convertToBlob({ type: 'image/png' });
  const r = await t.worker.recognize(blob, {}, { text: true, blocks: true });
  const words = [];
  for (const b of r.data.blocks || []) for (const p of b.paragraphs || []) for (const l of p.lines || []) for (const w of l.words || []) {
    words.push({ text: w.text, conf: w.confidence, ...w.bbox });
  }
  if (!words.length && r.data.words) for (const w of r.data.words) words.push({ text: w.text, conf: w.confidence, ...w.bbox });
  return { text: (r.data.text || '').trim(), words };
}
