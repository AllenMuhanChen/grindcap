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

    def slot_boxes(self) -> list[list[tuple[int, int, int, int]]]:
        x0, y0, w, h = self.first
        x1, y1 = self.last[0], self.last[1]
        px = (x1 - x0) / max(1, self.cols - 1)
        py = (y1 - y0) / max(1, self.rows - 1)
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
    import cv2

    g = cv2.cvtColor(slot_img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    return float(g[_qty_mask(*g.shape, qty_box)].std()) < std_max


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


class QtyReader:
    """Reads the stack number in a slot. Slots with no number (equipment, single items) count as 1."""

    def __init__(self, qty_box, tesseract_cmd=None, upscale=5, digits=None):
        self.qty_box = qty_box
        self.upscale = upscale
        self.digits = digits if digits is not None and digits.ready else None
        self._tess = None
        if self.digits is None:
            import pytesseract

            if tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
            self._tess = pytesseract

    def region(self, slot_img: np.ndarray) -> np.ndarray:
        h, w = slot_img.shape[:2]
        fx, fy, fw, fh = self.qty_box
        return slot_img[int(fy * h): int((fy + fh) * h), int(fx * w): int((fx + fw) * w)]

    def read(self, slot_img: np.ndarray) -> tuple[int, str]:
        import cv2

        c = self.region(slot_img)
        if self.digits is not None:
            n = self.digits.read(c)
            return (n if n else 1), ("" if n is None else str(n))
        g = cv2.cvtColor(c, cv2.COLOR_BGR2GRAY)
        g = cv2.resize(g, None, fx=self.upscale, fy=self.upscale, interpolation=cv2.INTER_NEAREST)
        _, th = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if th.mean() < 127:
            th = 255 - th
        th = cv2.copyMakeBorder(th, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
        raw = self._tess.image_to_string(th, config="--psm 7 -c tessedit_char_whitelist=0123456789").strip()
        digits = re.sub(r"\D", "", raw)
        return (int(digits) if digits else 1), raw


def read_page(frame: np.ndarray, grid: Grid, catalog: Catalog, qty: QtyReader,
              empty_std: float = 6.0, match_threshold: float = 12.0) -> list[list[Slot]]:
    """One screenshot of the visible inventory grid -> rows of (item_id or None, qty)."""
    rows = []
    for row in grid.slot_boxes():
        out = []
        for (x, y, w, h) in row:
            img = frame[y:y + h, x:x + w]
            if img.size == 0 or is_empty(img, grid.qty_box, empty_std):
                out.append((None, 0))
                continue
            iid = catalog.match(signature(img, grid.qty_box), img, match_threshold)
            n, _ = qty.read(img)
            out.append((iid, n))
        rows.append(out)
    return rows


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
        best = 0
        for k in range(min(len(merged), len(page)), 0, -1):
            a = [_row_key(r) for r in merged[-k:]]
            b = [_row_key(r) for r in page[:k]]
            if a == b and any(iid for r in page[:k] for iid, _ in r):
                best = k
                break
        merged.extend(list(r) for r in page[best:])
    return merged


def totals(tabs: dict[str, list[list[Slot]]]) -> dict[str, int]:
    """Total quantity per item id across all tabs."""
    out: dict[str, int] = {}
    for rows in tabs.values():
        for row in rows:
            for iid, n in row:
                if iid:
                    out[iid] = out.get(iid, 0) + n
    return out
