// Stat window reader: value parsing, and a synthetic stat window drawn over a real game frame
// (the game's own window hasn't been captured yet; layout and font differ, the label logic is the same).
import { loadImage, toImageData, fromImageData } from '../lib/img.js';
import { parseValue, parseWords, labelOf, readStats, flat, withStatFixes } from '../lib/stats.js';

export async function statsTests(log, fails) {
  const srt = (o) => (o && typeof o === 'object' && !Array.isArray(o) ? Object.fromEntries(Object.keys(o).sort().map((k) => [k, srt(o[k])])) : o);
  const eq = (a, b, what) => { if (JSON.stringify(srt(a)) !== JSON.stringify(srt(b))) fails.push(`stats ${what}: got ${JSON.stringify(a)}, want ${JSON.stringify(b)}`); };
  eq(parseValue('stat', '104 (90+14)'), { total: 104, base: 90, bonus: 14, checked: true }, 'stat with bonus');
  eq(parseValue('stat', '1O4 (9O + 14)'), { total: 104, base: 90, bonus: 14, checked: true }, 'O read for 0');
  eq(parseValue('stat', '104 (90+13)').checked, false, "bonus that doesn't add up");
  eq(parseValue('stat', '35'), { total: 35, checked: false }, 'plain stat');
  eq(parseValue('pair', '2116 / 2116'), { cur: 2116, max: 2116 }, 'hp pair');
  eq(parseValue('range', '120 ~ 180'), { min: 120, max: 180 }, 'attack range');
  eq(parseValue('num', '100%'), { value: 100 }, 'percent');
  eq(parseValue('exp', '78 (0.03%)'), { value: 78, pct: 0.03 }, 'exp');
  eq([labelOf('STR')?.key, labelOf('lNT')?.key, labelOf('W.DEF')?.key, labelOf('Level')?.key, labelOf('AP')?.key, labelOf('HPX')], ['str', 'int', 'wdef', 'level', 'ap', null], 'labels');
  const w = (text, x0, y0) => ({ text, x0, y0, x1: x0 + 8 * text.length, y1: y0 + 12 });
  const p = parseWords([w('STR', 10, 100), w('104', 60, 101), w('(90+14)', 90, 100), w('ATTACK', 200, 99), w('50', 260, 100), w('~', 280, 100), w('80', 290, 100),
    w('M.', 200, 120), w('DEF', 215, 120), w('12', 260, 120)]);
  eq(flat(p.values), { str: 104, attack_min: 50, attack_max: 80, mdef: 12 }, 'two fields on one line, two-word label');
  eq(withStatFixes({ values: p.values }, { str: 105, dex: '' }).str, 105, 'fix wins');

  // a stat window drawn over game_frame.png
  const base = await loadImage('../../tests/fixtures/game_frame.png');
  const cv = new OffscreenCanvas(base.w, base.h), g = cv.getContext('2d');
  g.putImageData(toImageData(base), 0, 0);
  const X = 420, Y = 220;
  g.fillStyle = '#eeeeee'; g.fillRect(X, Y, 360, 400);
  g.fillStyle = '#222'; g.font = '13px Arial';
  const rows = [['NAME', 'ImmovableObj'], ['JOB', 'Spearman'], ['LEVEL', '44'], ['EXP', '12345 (12.34%)'], ['HP', '2116 / 2116'], ['MP', '749 / 749'],
    ['AP', '0'], ['STR', '214 (180+34)'], ['DEX', '71 (60+11)'], ['INT', '4 (4+0)'], ['LUK', '4 (4+0)']];
  rows.forEach(([a, b], i) => { g.fillText(a, X + 12, Y + 24 + i * 22); g.fillText(b, X + 80, Y + 24 + i * 22); });
  const det = [['ATTACK', '180 ~ 410'], ['W.DEF', '312'], ['MAGIC', '12'], ['M.DEF', '55'], ['ACCURACY', '102'], ['AVOID', '31'], ['HANDS', '45'], ['SPEED', '100%'], ['JUMP', '100%']];
  det.forEach(([a, b], i) => { g.fillText(a, X + 190, Y + 24 + i * 22); g.fillText(b, X + 270, Y + 24 + i * 22); });
  const frame = fromImageData(g.getImageData(0, 0, base.w, base.h));
  const t0 = performance.now();
  const r = await readStats(frame);
  log(`synthetic stat window (${Math.round(performance.now() - t0)} ms): ${JSON.stringify(r && { ok: r.ok, why: r.why, box: r.box, lines: r.lines, flat: flat(r.values) })}`);
  eq(r && r.ok, true, 'synthetic window ok');
  eq(r && flat(r.values), { level: 44, exp: 12345, hp: 2116, mp: 749, ap: 0, str: 214, dex: 71, int: 4, luk: 4,
    attack_min: 180, attack_max: 410, wdef: 312, magic: 12, mdef: 55, accuracy: 102, avoid: 31, hands: 45, speed: 100, jump: 100 }, 'synthetic window values');
  const none = await readStats(base);
  eq(none, null, 'no stat window on game_frame.png');
}
