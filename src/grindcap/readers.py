"""Turn a screen crop into a number.

BarReader  - how full a horizontal coloured bar is (0..1). Pure pixel maths, no OCR.
TextReader - OCR the digits in a box with Tesseract, e.g. "312/450" -> (312, 450).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

import numpy as np


WINDOWS_TESSERACT = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]


def setup_tesseract(tesseract_cmd: str | None = None):
    """Point pytesseract at Tesseract: the configured path, PATH, or the usual Windows install folders."""
    import os
    import shutil

    import pytesseract

    candidates = [tesseract_cmd] if tesseract_cmd else []
    candidates += [shutil.which("tesseract")] + WINDOWS_TESSERACT
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(os.path.join(local, "Programs", "Tesseract-OCR", "tesseract.exe"))
    for c in candidates:
        if c and os.path.exists(c):
            pytesseract.pytesseract.tesseract_cmd = c
            return pytesseract
    raise RuntimeError(
        "Tesseract isn't installed (it reads the numbers on screen). Install it from "
        "https://github.com/UB-Mannheim/tesseract/wiki, keeping the default folder, then try again. "
        "If you installed it somewhere else, set session.tesseract_cmd in config.yaml to tesseract.exe.")


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

    def __init__(self, box, tesseract_cmd: str | None = None, upscale: int | None = None, pair: bool = False):
        self.pair = pair  # "cur/max" numbers like HP and MP
        self._tess = setup_tesseract(tesseract_cmd)
        self.box = box
        self.upscale = upscale
        self._last_hash = None
        self._last = Reading(None)

    def preprocess(self, c: np.ndarray, f: int | None = None, interp=None) -> np.ndarray:
        import cv2

        g = cv2.cvtColor(c, cv2.COLOR_BGR2GRAY)
        # Scale so text is roughly 40-60 px tall, which is where Tesseract does best.
        f = f or self.upscale or max(1, round(50 / max(1, g.shape[0])))
        g = cv2.resize(g, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC if interp is None else interp)
        _, th = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if th.mean() < 127:  # Tesseract wants dark text on light background
            th = 255 - th
        return cv2.copyMakeBorder(th, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)

    THOUSANDS = re.compile(r"(?<=\d)[.,' ](?=\d{3}(?!\d))")

    @classmethod
    def parse_pair(cls, text: str) -> Reading:
        """Parse "cur/max" (HP, MP). The slash in the game's font often OCRs as 4, 1, 7 or |,
        e.g. "1127/1127" -> "112741127". Without a slash, split the digits at the character that
        makes cur <= max with the two halves closest in length."""
        r = cls.parse(text)
        if "/" in text or r.value is None:
            return r
        digits = re.sub(r"\D", "", cls.THOUSANDS.sub("", text))
        best = None
        for k in range(1, len(digits) - 1):
            if digits[k] not in "4171|":
                continue
            a, b = digits[:k], digits[k + 1:]
            if b.startswith("0") or a.startswith("0") and len(a) > 1:
                continue
            if int(a) <= int(b):
                score = (abs(len(a) - len(b)), int(b) - int(a))
                if best is None or score < best[0]:
                    best = (score, int(a), int(b))
        if best:
            return Reading(best[1], best[2], raw=text)
        return r

    @classmethod
    def parse(cls, text: str) -> Reading:
        # The game's thousands comma often OCRs as a period or a space: "53.791" means 53,791.
        clean = cls.THOUSANDS.sub("", text)
        nums = [int(n.replace(",", "")) for n in cls.NUM.findall(clean)]
        if not nums:
            return Reading(None, raw=text)
        return Reading(nums[0], nums[1] if len(nums) > 1 else None, raw=text)

    def read(self, frame: np.ndarray) -> Reading:
        c = crop(frame, self.box)
        h = hashlib.blake2b(c.tobytes(), digest_size=8).digest()
        if h == self._last_hash:
            return self._last
        self._last_hash, self._last = h, self.vote(c)
        return self._last

    def vote(self, c: np.ndarray) -> Reading:
        """OCR the crop at a few scales and keep the most common reading.

        Tiny pixel fonts are fragile: one scale can drop or change a digit. Majority wins; ties go to
        the default scale.
        """
        import cv2
        from collections import Counter

        base = self.upscale or max(1, round(50 / max(1, c.shape[0])))
        tries = [(base, cv2.INTER_CUBIC), (base, cv2.INTER_NEAREST), (base + 1, cv2.INTER_NEAREST),
                 (max(2, base - 1), cv2.INTER_NEAREST), (base + 1, cv2.INTER_CUBIC)]
        reads = []
        for f, interp in tries:
            text = self._tess.image_to_string(
                self.preprocess(c, f, interp), config="--psm 7 -c tessedit_char_whitelist=0123456789/,.%[]()")
            reads.append(self.parse_pair(text.strip()) if self.pair else self.parse(text.strip()))
        counts = Counter(r.value for r in reads if r.value is not None)
        if not counts:
            return reads[0]
        best = max(counts.values())
        for r in reads:  # first (default scale) among the most common
            if r.value is not None and counts[r.value] == best:
                return r
        return reads[0]


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
            out[name] = TextReader(rc["box"], cfg["session"].get("tesseract_cmd"), pair=name in ("hp", "mp"))
    return out
