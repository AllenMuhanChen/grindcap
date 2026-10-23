"""Name inventory items by matching their icons against the game's own item data.

Source: maplestory.io, which serves the game's data files per region and version. Region "MCW" is
MapleStory Classic World, so names, icons and NPC sell prices are Classic World's own.

  db = ItemDB("data/itemdb")
  db.download()                       # once: item lists + one 32x32 icon per item (~1000 small PNGs)
  db.identify(native_bgr_patch)       # -> Match(name, item id, score, runner-up ratio) or None

Matching: inventory icons are the same pictures, drawn at native game resolution. So the slot is
mapped back to native pixels (see digits.native_view), then every candidate icon is slid over it and
compared pixel by pixel on the icon's opaque pixels only (mean squared BGR difference). The best match
is accepted only if it is clearly better than the best icon with a different name (`min_ratio`).
On the real 1920x1080 test frame all 18 items matched, with the runner-up at least 1.37x worse.
"""
from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np

API = "https://maplestory.io/api"
CATEGORIES = ("Etc", "Use", "Setup")   # the tabs with stacks; equipment can be added the same way
MIN_PIXELS = 40                        # icons with fewer opaque pixels are placeholders


@dataclass
class Match:
    item_id: int
    name: str
    score: float      # mean squared BGR difference over the icon's pixels (lower is better)
    ratio: float      # best score with a different name / this score
    runner_up: str
    neighbors: list   # ids of the closest-looking other icons (to re-check cheaply next time)


def _get(url: str, timeout: float = 60, tries: int = 3) -> bytes:
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "grindcap (inventory tracker)"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:   # the site sometimes times out on big requests; wait and retry
            last = e
            if getattr(e, "code", None) == 404:
                break
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"Couldn't fetch {url}: {last}")


class ItemDB:
    def __init__(self, folder: str | Path = "data/itemdb", region: str = "MCW", version: str = "1",
                 min_ratio: float = 1.25, max_score: float = 9000.0):
        self.folder = Path(folder)
        self.region, self.version = region, version
        self.min_ratio, self.max_score = min_ratio, max_score
        self.items_path = self.folder / "items.json"
        self.icons_dir = self.folder / "icons"
        self.items: dict[int, dict] = {}
        if self.items_path.exists():
            self.items = {int(k): v for k, v in json.loads(self.items_path.read_text()).items()}
        self._icons: dict[int, tuple[np.ndarray, np.ndarray]] | None = None

    @property
    def base(self) -> str:
        return f"{API}/{self.region}/{self.version}"

    @property
    def ready(self) -> bool:
        return bool(self.items) and self.icons_dir.exists()

    # ------------------------------------------------------------ download

    def download(self, categories=CATEGORIES, progress=print, page: int = 200, delay: float = 0.05):
        """Fetch item lists and icons. Already-downloaded icons are skipped, so it can be re-run."""
        self.folder.mkdir(parents=True, exist_ok=True)
        self.icons_dir.mkdir(exist_ok=True)
        for cat in categories:
            start = 0
            while True:
                url = f"{self.base}/item?overallCategoryFilter={cat}&startPosition={start}&count={page}"
                batch = json.loads(_get(url))
                for it in batch:
                    if it.get("isCash"):
                        continue
                    self.items[int(it["id"])] = {"name": it["name"], "category": cat,
                                                 "sub": (it.get("typeInfo") or {}).get("subCategory")}
                if len(batch) < page:
                    break
                start += page
            progress(f"{cat}: {sum(1 for v in self.items.values() if v['category'] == cat)} items")
        self.items_path.write_text(json.dumps(self.items, indent=1))
        todo = [i for i in self.items if not (self.icons_dir / f"{i}.png").exists()]
        for n, iid in enumerate(todo, 1):
            try:
                (self.icons_dir / f"{iid}.png").write_bytes(_get(f"{self.base}/item/{iid}/icon", 20))
            except RuntimeError as e:
                progress(f"  skipped {iid}: {e}")
            if n % 100 == 0:
                progress(f"icons: {n}/{len(todo)}")
            time.sleep(delay)
        self._icons = None
        progress(f"Item data ready: {len(self.items)} items in {self.folder}")

    def price(self, item_id: int) -> int | None:
        """NPC sell price (fetched once per item, then cached)."""
        it = self.items.get(item_id, {})
        if "price" not in it:
            try:
                meta = json.loads(_get(f"{self.base}/item/{item_id}", 20)).get("metaInfo") or {}
                it["price"] = meta.get("price")
                self.items_path.write_text(json.dumps(self.items, indent=1))
            except RuntimeError:
                return None
        return it.get("price")

    # ------------------------------------------------------------ matching

    def _load_icons(self):
        import cv2

        if self._icons is None:
            self._icons = {}
            for iid in self.items:
                p = self.icons_dir / f"{iid}.png"
                im = cv2.imread(str(p), cv2.IMREAD_UNCHANGED) if p.exists() else None
                if im is None or im.ndim != 3 or im.shape[2] != 4:
                    continue
                m = (im[..., 3] > 200).astype(np.float32)
                if m.sum() >= MIN_PIXELS:
                    self._icons[iid] = (np.ascontiguousarray(im[..., :3].astype(np.float32)),
                                        np.ascontiguousarray(np.dstack([m] * 3)))
        return self._icons

    def scores(self, patch: np.ndarray, ids) -> dict[int, float]:
        """Scores for just these item ids (fast: used to re-check an item seen before)."""
        import cv2

        patch = np.ascontiguousarray(patch.astype(np.float32))
        icons = self._load_icons()
        out = {}
        for iid in ids:
            if iid not in icons:
                continue
            img, mask = icons[iid]
            if img.shape[0] <= patch.shape[0] and img.shape[1] <= patch.shape[1]:
                r = cv2.matchTemplate(patch, img, cv2.TM_SQDIFF, mask=mask)
                out[iid] = float(r.min()) / float(mask.sum())
        return out

    def rank(self, patch: np.ndarray) -> list[tuple[float, int]]:
        """(score, item id) for every icon, best first. `patch` is native-resolution BGR around the
        slot, a few px larger than the icon. Stack digits drawn over the icon are simply part of the
        error; they cover too little of it to change which icon wins."""
        import cv2

        patch = np.ascontiguousarray(patch.astype(np.float32))
        out = []
        for iid, (img, mask) in self._load_icons().items():
            h, w = img.shape[:2]
            if h > patch.shape[0] or w > patch.shape[1]:
                continue
            r = cv2.matchTemplate(patch, img, cv2.TM_SQDIFF, mask=mask)
            out.append((float(r.min()) / float(mask.sum()), iid))
        out.sort()
        return out

    def ties(self, patch: np.ndarray, ratio: float = 1.05, limit: int = 40) -> list[int]:
        """Items whose icons fit this slot as well as the best one: several items drawn with the very
        same icon, like scrolls. One id per name; [] unless at least two such items fit well."""
        ranked = self.rank(patch)
        if not ranked or ranked[0][0] > 0.6 * self.max_score:
            return []
        cut = ranked[0][0] * ratio
        out, names = [], set()
        for s, i in ranked:
            if s > cut or len(out) >= limit:
                break
            if self.items[i]["name"] not in names:
                names.add(self.items[i]["name"])
                out.append(i)
        return out if len(out) > 1 else []

    def search(self, text: str, limit: int = 30) -> list[tuple[int, str]]:
        t = text.lower().strip()
        hits = [(i, it["name"]) for i, it in self.items.items() if t and t in it["name"].lower()]
        return sorted(hits, key=lambda h: (not h[1].lower().startswith(t), len(h[1]), h[1]))[:limit]

    def icon_path(self, item_id: int) -> Path:
        return self.icons_dir / f"{item_id}.png"

    def rescore(self, patch: np.ndarray, ignore: np.ndarray, ids) -> list[tuple[float, int]]:
        """Like rank() for a few ids, leaving out patch pixels marked in `ignore` (the stack number)."""
        patch = patch.astype(np.float32)
        keep = (~ignore).astype(np.float32)
        out = []
        for iid in ids:
            img, mask = self._load_icons()[iid]
            h, w = img.shape[:2]
            m1 = mask[..., 0]
            best = None
            for y in range(patch.shape[0] - h + 1):
                for x in range(patch.shape[1] - w + 1):
                    m = m1 * keep[y:y + h, x:x + w]
                    n = float(m.sum())
                    if n < 0.5 * float(m1.sum()):
                        continue
                    sc = float((((patch[y:y + h, x:x + w] - img) ** 2).sum(axis=2) * m).sum()) / (3 * n)
                    if best is None or sc < best:
                        best = sc
            if best is not None:
                out.append((best, iid))
        return sorted(out)

    def identify(self, patch: np.ndarray, ignore: np.ndarray | None = None) -> Match | None:
        """The item in this slot, or None if no icon matches clearly. With `ignore` (pixels of the
        stack number), the closest few icons are compared again without those pixels: big stacks
        ("1000") cover enough of an icon to blur look-alikes such as bow and crossbow arrows."""
        ranked = self.rank(patch)
        if ignore is not None and ignore.any() and ranked:
            top = ranked[:12]
            ranked = self.rescore(patch, ignore, [i for _, i in top]) + ranked[12:]
        if not ranked:
            return None
        s0, best = ranked[0]
        name = self.items[best]["name"]
        other = next(((s, i) for s, i in ranked[1:] if self.items[i]["name"] != name), None)
        ratio = (other[0] / s0 if s0 > 0 else float("inf")) if other else float("inf")
        if s0 > self.max_score or ratio < self.min_ratio:
            return None
        neighbors = [i for _, i in ranked[1:] if self.items[i]["name"] != name][:8]
        return Match(best, name, round(s0, 1), round(ratio, 2),
                     self.items[other[1]]["name"] if other else "", neighbors)
