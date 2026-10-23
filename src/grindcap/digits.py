"""Read small fixed-font numbers (inventory stack sizes) by matching digit templates.

The game draws stack numbers in one tiny bitmap font, which general OCR reads badly. Instead:
  1. isolate the text colour (pixels within `tol` of one of `colors`),
  2. split the mask into glyphs at empty columns,
  3. match each glyph against templates you taught once (`grindcap teach-digits`).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

GW, GH = 8, 12  # normalised glyph size


def text_mask(img: np.ndarray, rgb, tol: float) -> np.ndarray:
    d = np.linalg.norm(img.astype(np.float32) - np.array(rgb[::-1], np.float32), axis=2)
    return d < tol


def norm(g: np.ndarray) -> np.ndarray:
    import cv2

    ys = np.flatnonzero(g.any(axis=1))
    xs = np.flatnonzero(g.any(axis=0))
    if not ys.size:
        return np.zeros((GH, GW), np.float32)
    g = g[ys[0]: ys[-1] + 1, xs[0]: xs[-1] + 1].astype(np.float32)
    return cv2.resize(g, (GW, GH), interpolation=cv2.INTER_AREA)


def raw_glyphs(mask: np.ndarray, min_px: int = 2) -> list[np.ndarray]:
    """Unscaled glyph masks split at empty columns, with specks dropped."""
    cols = mask.any(axis=0)
    out, start = [], None
    for x, on in enumerate(list(cols) + [False]):
        if on and start is None:
            start = x
        elif not on and start is not None:
            g = mask[:, start:x]
            if g.sum() >= min_px:
                out.append(g)
            start = None
    if out:
        hs = [np.flatnonzero(g.any(axis=1)) for g in out]
        tall = max(h[-1] - h[0] + 1 for h in hs)
        out = [g for g, h in zip(out, hs) if h[-1] - h[0] + 1 >= 0.6 * tall]
    return out


def glyphs(mask: np.ndarray, min_px: int = 2) -> list[np.ndarray]:
    """Split a text mask into glyph images, left to right, each resized to GW x GH."""
    return [norm(g) for g in raw_glyphs(mask, min_px)]


def dominant_colors(img: np.ndarray, k: int = 8) -> list[tuple[int, int, int]]:
    """Most common colours in the image (RGB), as extra guesses for the digit colour."""
    q = (img // 16 * 16 + 8).reshape(-1, 3)
    vals, counts = np.unique(q, axis=0, return_counts=True)
    order = np.argsort(-counts)[:k]
    return [tuple(int(v) for v in vals[i][::-1]) for i in order]


class DigitReader:
    def __init__(self, path: str | Path, colors=((255, 255, 255), (0, 0, 0)), tol: float = 70,
                 max_dist: float = 0.25):
        self.path = Path(path)
        self.colors = [tuple(c) for c in colors]
        self.tol = tol
        self.max_dist = max_dist
        self.templates: dict[str, list[np.ndarray]] = {}
        self.color = None
        if self.path.exists():
            z = np.load(self.path, allow_pickle=True)
            self.templates = z["templates"].item()
            self.color = tuple(z["color"].tolist()) if "color" in z else None

    @property
    def ready(self) -> bool:
        return bool(self.templates) and self.color is not None

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(self.path, templates=np.array(self.templates, dtype=object), color=np.array(self.color))

    def teach(self, img: np.ndarray, number: str) -> bool:
        """Learn glyphs from an image whose number you know. Returns False if it couldn't split it."""
        cands = [self.color] if self.color else self.colors + dominant_colors(img)
        for c in cands:
            gs = glyphs(text_mask(img, c, self.tol))
            if len(gs) == len(number):
                self.color = c
                for ch, g in zip(number, gs):
                    self.templates.setdefault(ch, []).append(g)
                return True
        return False

    def read(self, img: np.ndarray) -> int | None:
        """Number in the image, or None if there is no text. Unrecognised glyphs also give None."""
        if not self.ready:
            raise RuntimeError("No digit templates yet. Run `grindcap teach-digits`.")
        raws = raw_glyphs(text_mask(img, self.color, self.tol))
        if not raws:
            return None
        s = ""
        for r in raws:
            ch, d = self._match(norm(r))
            if d > self.max_dist and r.shape[1] >= 4:
                # Two digits drawn touching: try every split column and keep the best pair.
                best = None
                for x in range(2, r.shape[1] - 1):
                    (c1, d1), (c2, d2) = self._match(norm(r[:, :x])), self._match(norm(r[:, x:]))
                    if best is None or max(d1, d2) < best[0]:
                        best = (max(d1, d2), c1 + c2)
                if best and best[0] <= self.max_dist:
                    s += best[1]
                    continue
            if d > self.max_dist:
                return None
            s += ch
        return int(s)

    def _match(self, g: np.ndarray) -> tuple[str, float]:
        best, bd = "", 1e9
        for ch, ts in self.templates.items():
            d = min(float(np.abs(t - g).mean()) for t in ts)
            if d < bd:
                best, bd = ch, d
        return best, bd
