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
Slot = tuple  # (item_id or None, qty[, ref]) where ref = "<page>:r<row>c<col>" says which screenshot slot it was


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


TABS = ("Equip", "Use", "Setup", "Etc", "Cash", "Deco")


def detect_tab(frame: np.ndarray, grid: "Grid") -> str | None:
    """Which inventory tab is open: the active tab button above the grid is pink-red.
    Tab buttons are 0.9 slot pitches apart, the first centred 0.385 pitches right of the grid's left."""
    px, py = grid.pitch()
    x0, y0 = grid.first[0], grid.first[1]
    ya, yb = int(y0 - 0.75 * py), int(y0 - 0.15 * py)
    xa, xb = int(x0 - 0.3 * px), int(x0 + 5.6 * px)
    band = frame[max(0, ya):max(0, yb), max(0, xa):max(0, xb)].astype(np.int16)
    if band.size == 0:
        return None
    b, g, r = band[..., 0], band[..., 1], band[..., 2]
    red = (r > 180) & (r - g > 60) & (r - b > 40)
    on = red.sum(axis=0) > max(5, band.shape[0] // 5)
    # Separate red blocks: a tab with new items flashes, so more than one tab can look highlighted.
    # Keep the block with the most red in it (the open tab is drawn solid).
    blocks, start = [], None
    for x, v in enumerate(list(on) + [False]):
        if v and start is None:
            start = x
        elif not v and start is not None:
            if x - start >= 0.4 * px:
                blocks.append((int(red[:, start:x].sum()), start, x))
            start = None
    if not blocks:
        return None
    _, a, z = max(blocks)
    cx = (a + z - 1) / 2 + max(0, xa)
    i = round(((cx - x0) / px - 0.385) / 0.9)
    return TABS[i] if 0 <= i < len(TABS) else None


def quick_tab(frame, grid: "Grid", catalog: "Catalog", itemdb, threshold: float = 12.0,
              empty_std: float = 6.0) -> str | None:
    """tab_from_items without reading the page: each slot's icon is only matched against items
    already in your catalog (fast). For telling which tab a page is while you're still capturing."""
    if itemdb is None:
        return None
    page = []
    for row in grid.slot_boxes():
        line = []
        for (x, y, w, h) in row:
            img = frame[max(0, y):y + h, max(0, x):x + w]
            if img.size == 0 or is_covered(img) or is_empty(img, grid.qty_box, empty_std):
                line.append((None, 0))
                continue
            c = catalog.candidates(signature(img, grid.qty_box), threshold)
            line.append((c[0] if c else None, 0))
        page.append(line)
    return tab_from_items(page, catalog, itemdb)


def tab_from_items(page, catalog: "Catalog", itemdb) -> str | None:
    """The tab a page belongs to, from what's in it: items named from the item data carry their
    category (Etc items only live in the Etc tab, and so on). Needs 2+ named items, 70% agreeing.
    Doesn't depend on how the tab buttons look (a flashing tab can fool the colour check)."""
    if itemdb is None:
        return None
    from collections import Counter

    votes = Counter()
    for row in page:
        for s in row:
            db = (catalog.items.get(s[0]) or {}).get("db") if s[0] and s[0] != UNKNOWN else None
            cat = (itemdb.items.get(int(db["id"])) or {}).get("category") if db else None
            if cat:
                votes[cat] += 1
    if not votes:
        return None
    tab, n = votes.most_common(1)[0]
    return tab if n >= 2 and n >= 0.7 * sum(votes.values()) else None


UNKNOWN = "?"   # item id for a slot something was drawn over (an item tooltip): not counted


def is_covered(slot_img: np.ndarray, frac: float = 0.15) -> bool:
    """True if an item tooltip covers this slot. The game's tooltip is a dark, see-through navy panel:
    blue well above red and green, which stay about equal. (Blue icons are far more saturated.)"""
    s = slot_img.astype(np.int16)
    b, g, r = s[..., 0], s[..., 1], s[..., 2]
    blue = b - (r + g) / 2
    m = (blue > 25) & (blue < 75) & (np.abs(r - g) < 15) & (r > 10) & (r < 115)
    return float(m.mean()) > frac


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
        self._sigs: list[tuple[str, np.ndarray]] = []   # (item id, signature); an item can have several
        if self.path.exists():
            self.items = json.loads(self.path.read_text())
            for it in self.items.values():   # older catalogs stored the NPC price as the price
                if it.get("price_source") == "npc sell":
                    it["npc_price"], it["price"] = it.get("price"), None
                    it.pop("price_source")
            for iid in self.items:
                for p in sorted(self.icons_dir.glob(f"{iid}.npy")) + sorted(self.icons_dir.glob(f"{iid}.alt*.npy")):
                    self._sigs.append((iid, np.load(p)))

    def save(self):
        self.icons_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.items, indent=2))

    def candidates(self, sig: np.ndarray, threshold: float) -> list[str]:
        """Known items whose icon signature is within `threshold`, closest first."""
        d = sorted((float(np.abs(s - sig).mean()), iid) for iid, s in self._sigs)
        out = []
        for dist, iid in d:
            if dist <= threshold and iid not in out:
                out.append(iid)
        return out

    def add_look(self, iid: str, sig: np.ndarray):
        """Remember another look of a known item (e.g. drawn at a different sub-pixel offset)."""
        self.icons_dir.mkdir(parents=True, exist_ok=True)
        k = sum(1 for i, _ in self._sigs if i == iid)
        np.save(self.icons_dir / f"{iid}.alt{k}.npy", sig)
        self._sigs.append((iid, sig))

    def add_named(self, name: str, db_id: int | None = None, price=None, icon_png: Path | None = None) -> str:
        """An item you picked by hand (e.g. which scroll a slot holds). It has no icon signature, so it
        never attracts automatic matches; slots are assigned to it on the review page."""
        import shutil

        n = 1 + max([int(re.sub(r"\D", "", k) or 0) for k in self.items] or [0])
        iid = f"item-{n:03d}"
        self.icons_dir.mkdir(parents=True, exist_ok=True)
        if icon_png is not None and Path(icon_png).exists():
            shutil.copy(icon_png, self.icons_dir / f"{iid}.png")
        self.items[iid] = {"name": name, "price": None, "npc_price": price, "manual": True}
        if db_id is not None:
            self.items[iid]["db"] = {"id": int(db_id), "manual": True}
        self.save()
        return iid

    def by_db(self, db_id: int) -> str | None:
        return next((iid for iid, it in self.items.items() if (it.get("db") or {}).get("id") == db_id), None)

    def match(self, sig: np.ndarray, slot_img: np.ndarray, threshold: float) -> str:
        """Known item id for this icon, or a new id."""
        c = self.candidates(sig, threshold)
        return c[0] if c else self._add(sig, slot_img)

    def _add(self, sig, slot_img) -> str:
        import cv2

        n = 1 + max([int(re.sub(r"\D", "", k) or 0) for k in self.items] or [0])
        iid = f"item-{n:03d}"
        self.icons_dir.mkdir(parents=True, exist_ok=True)
        np.save(self.icons_dir / f"{iid}.npy", sig)
        cv2.imwrite(str(self.icons_dir / f"{iid}.png"), slot_img)
        self.items[iid] = {"name": None, "price": None}
        self._sigs.append((iid, sig))
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

    def set_identity(self, iid: str, match, price=None):
        """Fill in a name found in the item database, unless you already named it yourself."""
        it = self.items[iid]
        if it.get("name_manual") or (it.get("name") and not it.get("db")):
            return
        it["name"] = match.name
        it["db"] = {"id": match.item_id, "score": match.score, "ratio": match.ratio,
                    "runner_up": match.runner_up, "neighbors": match.neighbors}
        if price is not None:
            it["npc_price"] = price
        self.save()

    def remove(self, iid: str):
        """Forget an item completely: catalog entry, icon picture and icon signatures."""
        self.items.pop(iid, None)
        for f in list(self.icons_dir.glob(f"{iid}.png")) + list(self.icons_dir.glob(f"{iid}.npy")) + \
                list(self.icons_dir.glob(f"{iid}.alt*.npy")):
            f.unlink(missing_ok=True)
        self._sigs = [(i, s) for i, s in self._sigs if i != iid]
        self.save()

    def price(self, iid: str):
        """Mesos each: your own price if you set one, else the NPC sell price, else None.
        Your price ("price") never replaces the NPC price ("npc_price"); clear it to go back."""
        it = self.items.get(iid) or {}
        return it["price"] if it.get("price") is not None else it.get("npc_price")

    def name(self, iid: str) -> str:
        return (self.items.get(iid) or {}).get("name") or iid


def read_page(frame: np.ndarray, grid: Grid, catalog: Catalog, digits, empty_std: float = 6.0,
              match_threshold: float = 12.0, itemdb=None, page_key: str = "") -> list[list[Slot]]:
    """One screenshot of the visible inventory grid -> rows of (item_id or None, qty, ref).

    `digits` is a digits.StackDigits. Slots with no number (equipment, single items) count as 1.
    With an `itemdb` (itemdb.ItemDB), items seen for the first time are named from the game's data.
    """
    from .digits import slot_patch

    rows = grid.slot_boxes()
    flat = [b for row in rows for b in row]
    px, py = grid.pitch()
    view = digits.page_view(frame, flat, px, color=itemdb is not None)
    origins = digits.slot_origins(view, flat, px, py, flat[0])
    numbers = digits.read_view(view, origins)
    out, i = [], 0
    for r, row in enumerate(rows):
        line = []
        for c, (x, y, w, h) in enumerate(row):
            img = frame[max(0, y):y + h, max(0, x):x + w]
            n, (u, v) = numbers[i].value, origins[i]
            ref = f"{page_key}:r{r + 1}c{c + 1}"
            i += 1
            if img.size == 0:
                line.append((None, 0, ref))
                continue
            if is_covered(img):
                line.append((UNKNOWN, 0, ref))
                continue
            if is_empty(img, grid.qty_box, empty_std):
                line.append((None, 0, ref))
                continue

            sig = signature(img, grid.qty_box)
            if itemdb is not None and itemdb.ready:
                patch = slot_patch(view, u, v)
                ignore = None
                if patch is not None and numbers[i - 1].text:
                    ox, oy = digits.last_offset
                    ignore = digits.digit_mask(numbers[i - 1], patch.shape[:2], -4 - ox, -4 - oy)
                iid = _identify_slot(catalog, itemdb, sig, img, patch, match_threshold, ignore)
            else:
                iid = catalog.match(sig, img, match_threshold)
            line.append((iid, n or 1, ref))
        out.append(line)
    return out


def _identify_slot(catalog: Catalog, itemdb, sig, img, patch, threshold: float, ignore=None) -> str:
    """Catalog id for a slot, using the item database to tell apart look-alikes (e.g. ores that differ
    only in colour) and to give each database item one catalog id.

    Fast path: the closest known icon that was itself identified is re-checked against its own database
    icon and its look-alikes (a few template matches). Only new or doubtful slots get the full search.
    """
    cands = catalog.candidates(sig, threshold)
    unnamed = None
    if cands:
        iid = cands[0]
        it = catalog.items[iid]
        db = it.get("db")
        if db and patch is not None:
            sc = itemdb.scores(patch, [db["id"]] + list(db.get("neighbors") or []))
            if sc and min(sc, key=sc.get) == db["id"]:
                return iid
        elif it.get("name") or patch is None or it.get("db_tried"):
            return iid      # named by you, or already searched for and not in the item data
        else:
            unnamed = iid                   # seen before but never named: try to name it now
    m = itemdb.identify(patch, ignore) if patch is not None else None
    if m is None:
        # Not in the database, or several items share this icon (scrolls): stays unnamed, and the
        # look-alike names are kept so the review page can offer them.
        iid = cands[0] if cands else catalog._add(sig, img)
        it = catalog.items[iid]
        if patch is not None and not it.get("name") and not it.get("db_tried"):
            it["candidates"] = itemdb.ties(patch)
            it["db_tried"] = True           # searched once; don't search all icons again every snapshot
            catalog.save()
        return iid
    known = catalog.by_db(m.item_id)
    if known:
        if known not in cands:
            catalog.add_look(known, sig)    # next time this look takes the fast path
        return known
    iid = unnamed or catalog._add(sig, img)
    catalog.set_identity(iid, m, itemdb.price(m.item_id))
    return iid


def _rows_agree(a_rows, b_rows) -> bool:
    """Do these rows show the same items? Compared by item and count, over slots where either side
    has an item. Allows 1 in 5 slots to differ (a cursor over one slot, a misread number), but small
    overlaps must match exactly. Slots under a tooltip don't count either way. Needs at least one item."""
    compared = mismatched = 0
    for ra, rb in zip(a_rows, b_rows):
        for sa, sb in zip(ra, rb):
            ia, ib = sa[0], sb[0]
            if UNKNOWN in (ia, ib):
                continue                  # covered on one page: no evidence either way
            if ia or ib:
                compared += 1
                # Same item AND same count. Ids alone let a page of look-alike rows (several
                # stacks of the same arrows) pass for a page already seen, losing those stacks.
                mismatched += ia != ib or (sa[1] != sb[1] and sa[1] and sb[1])
    return compared > 0 and mismatched <= compared // 5


def _contained(merged, page) -> bool:
    """True if the whole page already appears somewhere in `merged` (a page captured twice, a tab
    visited again, or scrolled back up)."""
    return _find(merged, page) is not None


def _find(merged, page) -> int | None:
    n = len(page)
    return next((i for i in range(len(merged) - n + 1) if _rows_agree(merged[i:i + n], page)), None)


def _fill(merged_rows, page_rows):
    """Slots covered on one page but visible on the other: take the visible one."""
    for mr, pr in zip(merged_rows, page_rows):
        for c, (ms, ps) in enumerate(zip(mr, pr)):
            if ms[0] == UNKNOWN and ps[0] != UNKNOWN:
                mr[c] = ps


def merge_pages(pages: list[list[list[Slot]]], log: list | None = None) -> list[list[Slot]]:
    """Stitch captured pages into one list of rows, counting every row once.

    - A page that already appears in what we have is skipped (captured twice, tab revisited, scrolled back).
    - Otherwise the largest k where the last k rows we have show the same items as the page's first k
      rows is the scroll overlap; only the rows after it are added.
    - No overlap: a new tab (or a jump), so the whole page is added.
    """
    merged: list[list[Slot]] = []
    for n, page in enumerate(pages, 1):
        at = _find(merged, page) if merged else None
        if at is not None:
            _fill(merged[at:at + len(page)], page)
            if log is not None:
                log.append(f"page {n}: already seen, skipped")
            continue
        best = 0
        for k in range(min(len(merged), len(page)), 0, -1):
            if _rows_agree(merged[-k:], page[:k]):
                best = k
                break
        if best:
            _fill(merged[-best:], page[:best])
        merged.extend(list(r) for r in page[best:])
        if log is not None:
            log.append(f"page {n}: " + (f"overlaps {best} rows, added {len(page) - best}" if best
                                        else f"no overlap, added all {len(page)} rows"))
    return merged


class PageWatcher:
    """Decides when to capture an inventory page automatically.

    Feed it frames a few times a second. It finds the inventory (by its landmark), looks at the item
    grid, and returns True once the grid has changed and then held still for `stable` frames, i.e.
    you scrolled or switched tabs and stopped, and it isn't a view captured before. Frames where the
    inventory isn't visible are ignored.
    """

    def __init__(self, cfg, stable: int = 2, diff: float = 4.0):
        self.cfg = cfg
        self.stable = stable
        self.diff = diff
        self._last = None
        self._count = 0
        self._captured: list = []

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
        if self._count >= self.stable and not any(self._same(sig, c) for c in self._captured):
            self._captured.append(sig)   # never capture the same view twice (e.g. a tab visited again)
            return True
        return False


def totals(tabs: dict[str, list[list[Slot]]]) -> dict[str, int]:
    """Total quantity per item id across all tabs."""
    out: dict[str, int] = {}
    for rows in tabs.values():
        for row in rows:
            for slot in row:
                iid, n = slot[0], slot[1]
                if iid and iid != UNKNOWN:
                    out[iid] = out.get(iid, 0) + n
    return out
