"""Read the inventory window: split it into slots, recognise each item by its icon, read stack sizes.

Items are identified by icon, not by name. The first time an icon is seen it gets an id (item-001, ...)
in the catalog (data/catalog.json + data/icons/). The same icon in a later screenshot matches that id,
so before/after inventories can be compared without OCR'ing item names. You can label ids with names
and prices afterwards.

Scrolling: you capture the visible grid page by page. Consecutive pages usually overlap by a few rows,
so pages are merged by finding the largest block of identical rows at the end of one page and the start
of the next.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

SIG = 24  # icon signature size (pixels per side)
Slot = tuple  # (item_id or None, qty)


@dataclass
class Grid:
    first: list          # [x, y, w, h] of the top-left visible slot
    last: list           # [x, y, w, h] of the bottom-right visible slot
    cols: int = 4
    rows: int = 6
    qty_box: list = field(default_factory=lambda: [0.0, 0.62, 0.75, 0.38])  # fraction of slot: x, y, w, h

    @classmethod
    def from_cfg(cls, inv: dict) -> "Grid":
        if not inv.get("first_slot") or not inv.get("last_slot"):
            raise ValueError("Inventory grid not calibrated. Run `grindcap calibrate --only inventory`.")
        return cls(inv["first_slot"], inv["last_slot"], inv["cols"], inv["rows"],
                   inv.get("qty_box") or [0.0, 0.62, 0.75, 0.38])

    def pitch(self) -> tuple[float, float]:
        """Screen pixels from one slot to the next, across and down."""
        return ((self.last[0] - self.first[0]) / max(1, self.cols - 1),
                (self.last[1] - self.first[1]) / max(1, self.rows - 1))

    def slot_boxes(self) -> list[list[tuple[int, int, int, int]]]:
        x0, y0, w, h = self.first
        px, py = self.pitch()
        return [[(round(x0 + c * px), round(y0 + r * py), w, h) for c in range(self.cols)]
                for r in range(self.rows)]


def _qty_mask(h: int, w: int, qty_box) -> np.ndarray:
    """True where the icon is, False where the stack number is drawn."""
    m = np.ones((h, w), bool)
    fx, fy, fw, fh = qty_box
    m[int(fy * h): int((fy + fh) * h), int(fx * w): int((fx + fw) * w)] = False
    return m


def signature(slot_img: np.ndarray, qty_box) -> np.ndarray:
    """Small float image of the icon with the stack-number area blanked out."""
    import cv2

    h, w = slot_img.shape[:2]
    img = slot_img.astype(np.float32).copy()
    img[~_qty_mask(h, w, qty_box)] = 0
    return cv2.resize(img, (SIG, SIG), interpolation=cv2.INTER_AREA)


def is_empty(slot_img: np.ndarray, qty_box, std_max: float) -> bool:
    """A slot is empty when its middle is flat. The edges are left out, so a box drawn a few pixels
    off (taking in the slot border) still counts as empty."""
    import cv2

    g = cv2.cvtColor(slot_img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    h, w = g.shape
    m = _qty_mask(h, w, qty_box)
    keep = np.zeros_like(m)
    keep[int(0.15 * h): h - int(0.15 * h), int(0.15 * w): w - int(0.15 * w)] = True
    v = g[m & keep]
    return v.size == 0 or float(v.std()) < std_max


class Catalog:
    """Known icons. Persisted as data/catalog.json plus one PNG per icon."""

    def __init__(self, folder: str | Path = "data"):
        self.folder = Path(folder)
        self.icons_dir = self.folder / "icons"
        self.path = self.folder / "catalog.json"
        self.items: dict[str, dict] = {}
        self._sigs: dict[str, np.ndarray] = {}
        if self.path.exists():
            self.items = json.loads(self.path.read_text())
            for iid in self.items:
                p = self.icons_dir / f"{iid}.npy"
                if p.exists():
                    self._sigs[iid] = np.load(p)

    def save(self):
        self.icons_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.items, indent=2))

    def match(self, sig: np.ndarray, slot_img: np.ndarray, threshold: float) -> str:
        best, best_d = None, 1e9
        for iid, s in self._sigs.items():
            d = float(np.abs(s - sig).mean())
            if d < best_d:
                best, best_d = iid, d
        if best is not None and best_d <= threshold:
            return best
        return self._add(sig, slot_img)

    def _add(self, sig, slot_img) -> str:
        import cv2

        n = 1 + max([int(re.sub(r"\D", "", k) or 0) for k in self.items] or [0])
        iid = f"item-{n:03d}"
        self.icons_dir.mkdir(parents=True, exist_ok=True)
        np.save(self.icons_dir / f"{iid}.npy", sig)
        cv2.imwrite(str(self.icons_dir / f"{iid}.png"), slot_img)
        self.items[iid] = {"name": None, "price": None}
        self._sigs[iid] = sig
        self.save()
        return iid

    def label(self, iid: str, name: str | None = None, price: float | None = None):
        if iid not in self.items:
            raise KeyError(f"Unknown item id {iid}")
        if name is not None:
            self.items[iid]["name"] = name
        if price is not None:
            self.items[iid]["price"] = price
        self.save()

    def name(self, iid: str) -> str:
        return (self.items.get(iid) or {}).get("name") or iid


def read_page(frame: np.ndarray, grid: Grid, catalog: Catalog, digits,
              empty_std: float = 6.0, match_threshold: float = 12.0) -> list[list[Slot]]:
    """One screenshot of the visible inventory grid -> rows of (item_id or None, qty).

    `digits` is a digits.StackDigits. Slots with no number (equipment, single items) count as 1.
    """
    rows = grid.slot_boxes()
    flat = [b for row in rows for b in row]
    numbers = digits.read_slots(frame, flat, *grid.pitch())
    out, i = [], 0
    for row in rows:
        line = []
        for (x, y, w, h) in row:
            img = frame[max(0, y):y + h, max(0, x):x + w]
            n = numbers[i].value
            i += 1
            if img.size == 0 or is_empty(img, grid.qty_box, empty_std):
                line.append((None, 0))
                continue
            iid = catalog.match(signature(img, grid.qty_box), img, match_threshold)
            line.append((iid, n or 1))
        out.append(line)
    return out


def _row_key(row) -> tuple:
    return tuple((a, b) for a, b in row)


def merge_pages(pages: list[list[list[Slot]]]) -> list[list[Slot]]:
    """Stitch scrolled pages of one inventory tab, dropping rows that appear on both pages.

    Overlap = the largest k where the last k rows of what we have equal the first k rows of the next page.
    Overlapping rows must contain at least one item, so runs of empty rows don't cause false matches.
    """
    if not pages:
        return []
    merged = [list(r) for r in pages[0]]
    for page in pages[1:]:
        if _contained(merged, page):
            continue  # scrolled back up to rows already counted
        best = 0
        for k in range(min(len(merged), len(page)), 0, -1):
            a = [_row_key(r) for r in merged[-k:]]
            b = [_row_key(r) for r in page[:k]]
            if a == b and any(iid for r in page[:k] for iid, _ in r):
                best = k
                break
        merged.extend(list(r) for r in page[best:])
    return merged


def _contained(merged, page) -> bool:
    """True if every row of `page` already appears, in order and contiguously, in `merged`."""
    if not any(iid for r in page for iid, _ in r):
        return False
    pk = [_row_key(r) for r in page]
    mk = [_row_key(r) for r in merged]
    n = len(pk)
    return any(mk[i:i + n] == pk for i in range(len(mk) - n + 1))


class PageWatcher:
    """Decides when to capture an inventory page automatically.

    Feed it frames a few times a second. It finds the inventory (by its landmark), looks at the item
    grid, and returns True once the grid has changed and then held still for `stable` frames, i.e.
    you scrolled or switched tabs and stopped. Frames where the inventory isn't visible are ignored.
    """

    def __init__(self, cfg, stable: int = 2, diff: float = 4.0):
        self.cfg = cfg
        self.stable = stable
        self.diff = diff
        self._last = None
        self._count = 0
        self._captured = None

    def grid_signature(self, frame):
        import cv2

        from .anchors import shifted

        try:
            fc = shifted(self.cfg, frame, ("inventory",))
        except LookupError:
            return None
        g = Grid.from_cfg(fc["inventory"])
        boxes = g.slot_boxes()
        x0, y0 = boxes[0][0][0], boxes[0][0][1]
        x1 = boxes[-1][-1][0] + boxes[-1][-1][2]
        y1 = boxes[-1][-1][1] + boxes[-1][-1][3]
        crop = frame[max(0, y0):y1, max(0, x0):x1]
        if crop.size == 0:
            return None
        small = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (48, 72), interpolation=cv2.INTER_AREA)
        return small.astype(np.float32)

    def _same(self, a, b) -> bool:
        return a is not None and b is not None and float(np.abs(a - b).mean()) < self.diff

    def feed(self, frame) -> bool:
        sig = self.grid_signature(frame)
        if sig is None:
            self._last, self._count = None, 0
            return False
        if self._same(sig, self._last):
            self._count += 1
        else:
            self._last, self._count = sig, 1
        if self._count >= self.stable and not self._same(sig, self._captured):
            self._captured = sig
            return True
        return False


def totals(tabs: dict[str, list[list[Slot]]]) -> dict[str, int]:
    """Total quantity per item id across all tabs."""
    out: dict[str, int] = {}
    for rows in tabs.values():
        for row in rows:
            for iid, n in row:
                if iid:
                    out[iid] = out.get(iid, 0) + n
    return out
