"""Read inventory stack numbers, in the game's own stack-number font.

What the font looks like (measured on a real 1920x1080 screenshot of MapleStory Classic):

- The game draws its picture at a lower resolution (here 1366x768) and stretches it to the window.
  So everything is first mapped back to the game's own pixels ("native" pixels). The scale comes
  from the slot pitch (slots are 36 native pixels apart); the sub-pixel offset of the stretch is
  found by trying offsets and keeping the sharpest result.
- Digits are 11 native pixels tall: a 1 px light stroke (grey at the top, blue at the bottom) with a
  1 px black outline. Where strokes are close the outlines merge, so digits look mostly black.
- The number is left-aligned in the slot's bottom-left corner. Every digit is 8 px wide except "1",
  which is 5 px, so once the first digit is known the next one's position is known too.
- Holes in the digits (inside a 0, 6, 8 ...) show the item icon behind them.

Reading: at each digit position, compare the pixels with a template of every digit using normalised
correlation over the digit's own pixels only (outline and stroke, not the holes), take the best, and
stop when nothing matches. Templates ship with grindcap (`data/stack_digits.npz`, cut from the real
screenshot in tests/fixtures/game_frame.png); `grindcap teach-digits` adds your own examples on top.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

DIGITS = "0123456789"
ADV = {d: (5 if d == "1" else 8) for d in DIGITS}   # native px from one digit to the next
FONT_H = 11                                          # native px
SLOT_PITCH = 36                                      # native px between slot columns
DIGIT_TOP = 20                                       # native px from slot top to digit top (nominal)
MAX_DIGITS = 5
END_COST = 0.45   # 1 - correlation; above this, "no digit here" (true digits ~<0.2, non-digits >0.5)
SEARCH = 4        # native px searched around the expected digit position, per page

BUILTIN = Path(__file__).parent / "data" / "stack_digits.npz"
NATIVE_W = (800, 1024, 1280, 1366, 1600, 1920)
NATIVE_H = (600, 720, 768, 900, 1080)


# ---------------------------------------------------------------- mapping the screen to game pixels

def native_scale(pitch_x: float, frame_shape) -> tuple[float, float]:
    """Screen px per native px, horizontally and vertically, from the measured slot pitch."""
    s = pitch_x / SLOT_PITCH
    if abs(s - 1) < 0.04:
        return 1.0, 1.0
    h, w = frame_shape[:2]
    nw = min(NATIVE_W, key=lambda n: abs(w / n - s))
    nh = min(NATIVE_H, key=lambda n: abs(h / n - s))
    sx = w / nw if abs(w / nw - s) / s < 0.04 else s
    sy = h / nh if abs(h / nh - s) / s < 0.04 else s
    return sx, sy


@dataclass
class NativeView:
    """A grey image of part of the frame, resampled to native game pixels.

    Native pixel (u, v) is centred on screen point (sx*u + (sx-1)/2 + px, sy*v + (sy-1)/2 + py).
    `img` covers native pixels u0.. and v0.. .
    """
    img: np.ndarray
    u0: int
    v0: int
    sx: float
    sy: float
    px: float = 0.0
    py: float = 0.0

    def to_native(self, x: float, y: float) -> tuple[int, int]:
        """Screen point -> native pixel index (global)."""
        return (int(round((x - (self.sx - 1) / 2 - self.px) / self.sx)),
                int(round((y - (self.sy - 1) / 2 - self.py) / self.sy)))

    def crop(self, u: int, v: int, w: int, h: int) -> np.ndarray | None:
        a, b = u - self.u0, v - self.v0
        if a < 0 or b < 0 or b + h > self.img.shape[0] or a + w > self.img.shape[1]:
            return None
        return self.img[b:b + h, a:a + w]


def _gray(frame: np.ndarray) -> np.ndarray:
    import cv2

    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    return g.astype(np.float32)


def _resample(gray, u0, v0, nw, nh, sx, sy, px, py) -> np.ndarray:
    import cv2

    m = np.float32([[sx, 0, sx * u0 + (sx - 1) / 2 + px], [0, sy, sy * v0 + (sy - 1) / 2 + py]])
    return cv2.warpAffine(gray, m, (nw, nh), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                          borderMode=cv2.BORDER_REPLICATE)


def native_view(frame: np.ndarray, box, sx: float, sy: float, steps: int = 10) -> NativeView:
    """Resample screen box [x, y, w, h] to native pixels, choosing the sharpest sub-pixel offset."""
    import cv2

    gray = _gray(frame)
    x, y, w, h = box
    if sx == 1.0 and sy == 1.0:
        x0, y0 = max(0, int(x)), max(0, int(y))
        return NativeView(gray[y0:int(y + h), x0:int(x + w)], x0, y0, 1.0, 1.0)
    u0, v0 = int(np.floor(x / sx)), int(np.floor(y / sy))
    nw, nh = int(np.ceil(w / sx)) + 1, int(np.ceil(h / sy)) + 1

    def sharp(img):
        return float(np.abs(cv2.Laplacian(img, cv2.CV_32F)).mean())

    offs_x = [sx * (i / steps - 0.5) for i in range(steps)]
    offs_y = [sy * (i / steps - 0.5) for i in range(steps)]
    # The two directions are independent enough to search one at a time.
    px = max(offs_x, key=lambda p: sharp(_resample(gray, u0, v0, nw, nh, sx, sy, p, 0.0)))
    py = max(offs_y, key=lambda p: sharp(_resample(gray, u0, v0, nw, nh, sx, sy, px, p)))
    return NativeView(_resample(gray, u0, v0, nw, nh, sx, sy, px, py), u0, v0, sx, sy, px, py)


# ---------------------------------------------------------------- templates

def glyph_mask(t: np.ndarray, dark: float = 100) -> np.ndarray:
    """The digit's own pixels: the black outline plus the 1 px stroke sandwiched inside it."""
    d = t < dark
    left, right, up, down = (np.zeros_like(d) for _ in range(4))
    left[:, 1:], right[:, :-1], up[1:], down[:-1] = d[:, :-1], d[:, 1:], d[:-1], d[1:]
    return d | (left & right) | (up & down)


@dataclass
class _Template:
    img: np.ndarray
    mask: np.ndarray
    zn: np.ndarray = field(init=False)   # masked pixels, zero-mean, unit norm

    def __post_init__(self):
        v = self.img[self.mask].astype(np.float64)
        v = v - v.mean()
        self.zn = v / (np.linalg.norm(v) or 1.0)

    def cost(self, patch: np.ndarray) -> float:
        """1 - normalised correlation over the template's own pixels (0 = perfect, ~1 = unrelated)."""
        v = patch[self.mask].astype(np.float64)
        v = v - v.mean()
        n = np.linalg.norm(v)
        return 1.0 if n < 1e-6 else 1.0 - float(v @ self.zn) / n


def _load(path: Path) -> tuple[dict[str, list[np.ndarray]], tuple[int, int] | None]:
    inst: dict[str, list[np.ndarray]] = {}
    offset = None
    if path.exists():
        z = np.load(path)
        for d in DIGITS:
            if f"d{d}" in z:
                inst[d] = list(z[f"d{d}"])
        if "offset" in z:
            offset = tuple(int(v) for v in z["offset"])
    return inst, offset


@dataclass
class SlotReading:
    value: int | None          # None: no number drawn (counts as 1 item)
    text: str
    costs: list[float]         # per digit, 1 - correlation


class StackDigits:
    """Stack-number reader. Built-in templates plus any you taught (saved in `path`)."""

    def __init__(self, path: str | Path | None = None, builtin: Path = BUILTIN):
        self.path = Path(path) if path else None
        self.builtin, off = _load(builtin)
        self.offset = off or (0, DIGIT_TOP)   # digit origin relative to the slot's top-left, native px
        self.taught, toff = _load(self.path) if self.path else ({}, None)
        if toff:
            self.offset = toff
        self._build()

    def _build(self):
        self.templates: dict[str, _Template] = {}
        for d in DIGITS:
            ex = self.taught.get(d, []) + self.builtin.get(d, [])
            if ex:
                t = np.median(np.stack(ex), axis=0).astype(np.float32)
                self.templates[d] = _Template(t, glyph_mask(t))

    @property
    def ready(self) -> bool:
        return len(self.templates) == len(DIGITS)

    # --- reading

    def read_number(self, view: NativeView, u: int, v: int) -> SlotReading:
        """Read the number whose first digit's top-left is native pixel (u, v)."""
        text, costs = "", []
        while len(text) < MAX_DIGITS:
            best, bc = None, END_COST
            for d, t in self.templates.items():
                p = view.crop(u, v, ADV[d], FONT_H)
                if p is None:
                    continue
                c = t.cost(p)
                if c < bc:
                    best, bc = d, c
            if best is None:
                break
            text += best
            costs.append(round(bc, 3))
            u += ADV[best]
        if text.startswith("0"):
            return SlotReading(None, text, costs)   # a stack count never starts with 0: not a number
        return SlotReading(int(text) if text else None, text, costs)

    def _first_cost(self, view, u, v) -> float:
        cs = [t.cost(p) for d, t in self.templates.items() if d != "0"
              if (p := view.crop(u, v, ADV[d], FONT_H)) is not None]
        return min(cs + [END_COST])

    def locate(self, view: NativeView, origins: list[tuple[int, int]]) -> tuple[int, int]:
        """Digit origin offset that fits this page best (the grid boxes are only roughly placed)."""
        ox, oy = self.offset
        best, bs = (ox, oy), None
        for dy in range(-SEARCH, SEARCH + 1):
            for dx in range(-SEARCH, SEARCH + 1):
                s = sum(self._first_cost(view, u + ox + dx, v + oy + dy) for u, v in origins)
                if bs is None or s < bs - 1e-9:
                    best, bs = (ox + dx, oy + dy), s
        return best

    def page_view(self, frame, boxes: list[tuple[int, int, int, int]], pitch_x: float) -> NativeView:
        sx, sy = native_scale(pitch_x, frame.shape)
        x0 = min(b[0] for b in boxes) - 4 * sx
        y0 = min(b[1] for b in boxes) - 4 * sy
        x1 = max(b[0] + b[2] for b in boxes) + 4 * sx
        y1 = max(b[1] + b[3] for b in boxes) + 4 * sy
        return native_view(frame, (x0, y0, x1 - x0, y1 - y0), sx, sy)

    def slot_origins(self, view: NativeView, boxes, pitch_x: float, pitch_y: float, first) -> list:
        """Native top-left of each slot, using whole-native-pixel pitches so rounding can't drift."""
        fu, fv = view.to_native(first[0], first[1])
        pu, pv = round(pitch_x / view.sx), round(pitch_y / view.sy) if pitch_y else 0
        return [(fu + round((b[0] - first[0]) / pitch_x) * pu if pitch_x else fu,
                 fv + (round((b[1] - first[1]) / pitch_y) * pv if pitch_y else 0)) for b in boxes]

    def read_slots(self, frame, boxes, pitch_x: float, pitch_y: float) -> list[SlotReading]:
        """Read the stack number in every slot box (screen [x, y, w, h]); boxes[0] anchors the grid."""
        if not boxes:
            return []
        view = self.page_view(frame, boxes, pitch_x)
        origins = self.slot_origins(view, boxes, pitch_x, pitch_y, boxes[0])
        ox, oy = self.locate(view, origins)
        return [self.read_number(view, u + ox, v + oy) for u, v in origins]

    # --- teaching

    def teach(self, frame, boxes, labels: list[str], pitch_x: float, pitch_y: float) -> int:
        """Add the digits of slots whose number you know (labels[i] for boxes[i]; '' = skip)."""
        view = self.page_view(frame, boxes, pitch_x)
        origins = self.slot_origins(view, boxes, pitch_x, pitch_y, boxes[0])
        ox, oy = self.locate(view, [o for o, lab in zip(origins, labels) if lab])
        n = 0
        for (u, v), lab in zip(origins, labels):
            u += ox
            for d in lab:
                p = view.crop(u, v + oy, ADV[d], FONT_H)
                if p is not None:
                    self.taught.setdefault(d, []).append(p.copy())
                    n += 1
                u += ADV[d]
        self.offset = (ox, oy)
        self._build()
        return n

    def save(self, path: str | Path | None = None, which: str = "taught"):
        path = Path(path or self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        src = self.taught if which == "taught" else self.builtin
        arrays = {f"d{d}": np.stack(v).astype(np.float32) for d, v in src.items() if v}
        np.savez_compressed(path, offset=np.array(self.offset), **arrays)
