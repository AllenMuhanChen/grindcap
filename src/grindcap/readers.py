"""Turn a screen crop into a number.

BarReader  - how full a horizontal coloured bar is (0..1). Pure pixel maths, no OCR.
TextReader - OCR the digits in a box with Tesseract, e.g. "312/450" -> (312, 450).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

import numpy as np


def crop(frame: np.ndarray, box) -> np.ndarray:
    x, y, w, h = (int(v) for v in box)
    return frame[y:y + h, x:x + w]


@dataclass
class Reading:
    value: float | None          # current value (points, or fraction 0..1 for an uncalibrated bar)
    max: float | None = None     # max value when the reader can see it (text "cur/max")
    raw: str = ""                # what OCR saw, for debugging


class BarReader:
    """Measures the fill of a left-to-right bar.

    For each column of the bar's middle band, a column counts as filled when most of its pixels are
    within `tol` (RGB distance) of the fill colour. The fill is the rightmost filled column, which keeps
    working when the game draws white HP text over the middle of the bar.
    """

    def __init__(self, box, fill_rgb, tol: float = 45, scale: float | None = None):
        self.box = box
        self.fill_bgr = np.array(fill_rgb[::-1], dtype=np.float32)
        self.tol = tol
        self.scale = scale  # max points; None returns a fraction

    def fraction(self, frame: np.ndarray) -> float:
        c = crop(frame, self.box).astype(np.float32)
        h = c.shape[0]
        band = c[max(0, h // 2 - 1): h // 2 + 2]  # 3 middle rows
        dist = np.linalg.norm(band - self.fill_bgr, axis=2)
        filled_cols = (dist < self.tol).mean(axis=0) >= 0.5
        idx = np.flatnonzero(filled_cols)
        if idx.size == 0:
            return 0.0
        return float(idx[-1] + 1) / c.shape[1]

    def read(self, frame: np.ndarray) -> Reading:
        f = self.fraction(frame)
        if self.scale:
            return Reading(round(f * self.scale), self.scale)
        return Reading(f)


class TextReader:
    """OCR digits with Tesseract. Re-runs OCR only when the crop actually changes."""

    NUM = re.compile(r"\d[\d,]*")

    def __init__(self, box, tesseract_cmd: str | None = None, upscale: int | None = None):
        import pytesseract  # optional dependency: pip install grindcap[ocr]

        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        self._tess = pytesseract
        self.box = box
        self.upscale = upscale
        self._last_hash = None
        self._last = Reading(None)

    def preprocess(self, c: np.ndarray) -> np.ndarray:
        import cv2

        g = cv2.cvtColor(c, cv2.COLOR_BGR2GRAY)
        # Scale so text is roughly 40-60 px tall, which is where Tesseract does best.
        f = self.upscale or max(1, round(50 / max(1, g.shape[0])))
        g = cv2.resize(g, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
        _, th = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if th.mean() < 127:  # Tesseract wants dark text on light background
            th = 255 - th
        return cv2.copyMakeBorder(th, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)

    @classmethod
    def parse(cls, text: str) -> Reading:
        nums = [int(n.replace(",", "")) for n in cls.NUM.findall(text)]
        if not nums:
            return Reading(None, raw=text)
        return Reading(nums[0], nums[1] if len(nums) > 1 else None, raw=text)

    def read(self, frame: np.ndarray) -> Reading:
        c = crop(frame, self.box)
        h = hashlib.blake2b(c.tobytes(), digest_size=8).digest()
        if h == self._last_hash:
            return self._last
        img = self.preprocess(c)
        text = self._tess.image_to_string(
            img, config="--psm 7 -c tessedit_char_whitelist=0123456789/,.%[]()")
        self._last_hash, self._last = h, self.parse(text.strip())
        return self._last


def build_readers(cfg, strict: bool = False) -> dict:
    """Create a reader for every configured box.

    strict=True (live tracking) requires max_hp/max_mp for bar readers; otherwise an HP/MP bar without
    a max just reports how full it is (0-1), which is fine for checking calibration.
    """
    out = {}
    ch = cfg["character"]
    for name, rc in cfg.configured_readers().items():
        if rc.get("mode", "bar") == "bar":
            if not rc.get("fill_rgb"):
                raise ValueError(f"Reader '{name}' is a bar but has no fill_rgb. Run `grindcap calibrate`.")
            scale = {"hp": ch.get("max_hp"), "mp": ch.get("max_mp")}.get(name)
            if strict and name in ("hp", "mp") and not scale:
                raise ValueError(f"Live tracking reads HP/MP from the bar, so set your max {name.upper()} "
                                 f"in config.yaml under character: max_{name}: <number>.")
            out[name] = BarReader(rc["box"], rc["fill_rgb"], rc.get("tol", 45), scale)
        else:
            out[name] = TextReader(rc["box"], cfg["session"].get("tesseract_cmd"))
    return out
