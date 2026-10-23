"""Before/after snapshots: EXP, level, mesos and the whole inventory, then compare.

  grindcap snap start      capture EXP/mesos, then page through each inventory tab
  ... grind ...
  grindcap snap end
  grindcap compare         EXP/hr, mesos/hr, and every item gained or used per hour
"""
from __future__ import annotations

import base64
import json
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from .gamedata import exp_to_next
from .inventory import Catalog, Grid, merge_pages, read_page, totals
from .readers import TextReader


def read_status(cfg, frame) -> dict:
    """EXP, level and meso total from one frame (whichever boxes are calibrated)."""
    out = {}
    tess = cfg["session"].get("tesseract_cmd")
    for key in ("exp", "level", "mesos"):
        rc = cfg["readers"].get(key) or {}
        if rc.get("box"):
            r = TextReader(rc["box"], tess).read(frame)
            out[key] = r.value
            out[f"{key}_raw"] = r.raw
    return out


def read_map_safe(cfg, frame):
    """Map shown in the minimap ({"street", "name", ...}), or None. Never raises: a missing minimap
    or OCR problem just means no map name (you can type it on the review page)."""
    from .mapname import download_maps, load_maps, read_map

    folder = Path(cfg["inventory"]["catalog_dir"]) / "itemdb"
    try:
        maps = load_maps(folder)
        if not maps and (cfg["inventory"].get("itemdb") or {}).get("enabled", True):
            try:
                maps = download_maps(folder)
            except Exception:
                maps = []
        return read_map(frame, maps, cfg["session"].get("tesseract_cmd"))
    except Exception:
        return None


def open_itemdb(cfg, download: bool = True, progress=print):
    """The item database for naming items, downloading it the first time. None if turned off or offline."""
    from .itemdb import ItemDB

    inv = cfg["inventory"]
    opt = inv.get("itemdb") or {}
    if not opt.get("enabled", True):
        return None
    db = ItemDB(Path(inv["catalog_dir"]) / "itemdb", opt.get("region", "MCW"), str(opt.get("version", "1")),
                min_ratio=opt.get("min_ratio", 1.25))
    if not db.ready and download:
        progress("Downloading item names and icons from maplestory.io (once, about a minute)...")
        try:
            db.download(progress=progress)
        except Exception as e:
            progress(f"Couldn't download item data ({e}); items keep their item-NNN ids for now.")
            return None
    return db if db.ready else None


def build_snapshot(cfg, status_frame, tab_pages: dict[str, list[np.ndarray]], catalog: Catalog,
                   when: float | None = None) -> dict:
    from .anchors import shifted
    from .digits import StackDigits

    inv = cfg["inventory"]
    digits = StackDigits(Path(inv["catalog_dir"]) / "digits.npz")
    itemdb = open_itemdb(cfg)
    tabs, first_page, boxes, merge_log = {}, None, {}, {}
    for tab, frames in tab_pages.items():
        pages = []
        for i, f in enumerate(frames, 1):
            fc = shifted(cfg, f, ("inventory",))  # the inventory may be anywhere on screen
            grid = Grid.from_cfg(fc["inventory"])
            key = f"{tab}_{i:02d}"                # = the screenshot's file name in the snapshot folder
            pages.append(read_page(f, grid, catalog, digits, inv["empty_std"], inv["match_threshold"],
                                   itemdb, page_key=key))
            for r, row in enumerate(grid.slot_boxes()):
                for c, b in enumerate(row):
                    boxes[f"{key}:r{r + 1}c{c + 1}"] = [int(v) for v in b]
            if first_page is None:
                first_page = (f, fc)
        tabs[tab] = merge_pages(pages, log := [])
        merge_log[tab] = log
    status = {}
    if status_frame is not None:
        status = read_status(shifted(cfg, status_frame, ("status",)), status_frame)
    map_frame = status_frame if status_frame is not None else (first_page[0] if first_page else None)
    where = read_map_safe(cfg, map_frame) if map_frame is not None else None
    if first_page is not None and (cfg["readers"].get("mesos") or {}).get("box"):
        # The meso total lives in the inventory window, so read it from an inventory page.
        f, fc = first_page
        m = read_status(fc, f).get("mesos")
        if m is not None:
            status["mesos"] = m
    return {
        "time": when if when is not None else time.time(),
        "when": datetime.fromtimestamp(when or time.time()).isoformat(timespec="seconds"),
        "level": status.get("level") or cfg["character"]["level"],
        "level_read": status.get("level") is not None,
        "exp": status.get("exp"),
        "mesos": status.get("mesos"),
        "status_raw": {k: v for k, v in status.items() if k.endswith("_raw")},
        "map": where,
        "tabs": {t: [[list(s) for s in row] for row in rows] for t, rows in tabs.items()},
        "items": totals(tabs),
        "merge_log": merge_log,
        # every counted slot, so single slots can be corrected later (see apply_fixes)
        "slots": [{"ref": s[2], "item": s[0], "qty": s[1], "box": boxes.get(s[2])}
                  for rows in tabs.values() for row in rows for s in row if s[0] and len(s) > 2],
    }


def save_snapshot(snap: dict, folder: Path, status_frame=None, tab_pages=None) -> Path:
    import cv2

    folder.mkdir(parents=True, exist_ok=True)
    (folder / "snapshot.json").write_text(json.dumps(snap, indent=2))
    if status_frame is not None:
        cv2.imwrite(str(folder / "status.png"), status_frame)
    for tab, frames in (tab_pages or {}).items():
        for i, f in enumerate(frames, 1):
            cv2.imwrite(str(folder / f"{tab}_{i:02d}.png"), f)
    return folder


def load_snapshot(path: str | Path) -> dict:
    """A saved snapshot, with your corrections (fixes.json next to it) attached as snap["fixes"]."""
    p = Path(path)
    if p.is_dir():
        p = p / "snapshot.json"
    snap = json.loads(p.read_text())
    fx = p.parent / "fixes.json"
    snap["fixes"] = json.loads(fx.read_text()) if fx.exists() else {}
    snap["folder"] = str(p.parent)
    return snap


def save_fixes(folder: str | Path, fixes: dict):
    (Path(folder) / "fixes.json").write_text(json.dumps(fixes, indent=2))


def apply_fixes(snap: dict) -> dict:
    """The snapshot as corrected: fixes["status"] overrides exp/mesos/level, fixes["slots"][ref] can
    reassign a slot ({"item": id}), fix its count ({"qty": n}) or drop it ({"ignore": true})."""
    fx = snap.get("fixes") or {}
    out = dict(snap)
    for k, v in (fx.get("status") or {}).items():
        if v is not None:
            out[k] = v
            if k == "level":
                out["level_read"] = True
    if "slots" in snap:
        sf = fx.get("slots") or {}
        items: dict[str, int] = {}
        for sl in snap["slots"]:
            f = sf.get(sl["ref"], {})
            if f.get("ignore"):
                continue
            iid, n = f.get("item", sl["item"]), f.get("qty", sl["qty"])
            if iid and iid != "?":
                items[iid] = items.get(iid, 0) + int(n)
        out["items"] = items
    if fx.get("deleted"):
        out["items"] = {k: v for k, v in out["items"].items() if k not in set(fx["deleted"])}
    return out


def latest_snapshot(root: Path, label: str) -> Path | None:
    found = sorted(root.glob(f"{label}-*/snapshot.json"))
    return found[-1].parent if found else None


def exp_gained(start: dict, end: dict) -> float | None:
    """EXP between two snapshots, adding whole levels if you levelled up in between."""
    if start.get("exp") is None or end.get("exp") is None:
        return None
    l0, l1 = int(start["level"]), int(end["level"])
    if l1 == l0 and end["exp"] < start["exp"] and not end.get("level_read"):
        l1 = l0 + 1  # EXP went down and the level wasn't read: assume one level-up
    if l1 == l0:
        return end["exp"] - start["exp"]
    total = (exp_to_next(l0) or 0) - start["exp"]
    for lv in range(l0 + 1, l1):
        total += exp_to_next(lv) or 0
    return total + end["exp"]


def compare(start: dict, end: dict, catalog: Catalog, minutes: float | None = None) -> dict:
    start, end = apply_fixes(start), apply_fixes(end)
    hours = (minutes / 60) if minutes else (end["time"] - start["time"]) / 3600
    per_hr = (lambda v: round(v / hours, 1)) if hours > 0 else (lambda v: None)
    ids = sorted(set(start["items"]) | set(end["items"]))
    if catalog.items:
        ids = [i for i in ids if i in catalog.items]   # items purged from the catalog don't count
    rows = []
    for iid in ids:
        a, b = start["items"].get(iid, 0), end["items"].get(iid, 0)
        if a == b:
            continue
        info = catalog.items.get(iid, {})
        price = catalog.price(iid)
        rows.append({"id": iid, "name": info.get("name") or iid, "before": a, "after": b, "change": b - a,
                     "per_hr": per_hr(b - a), "price": price,
                     "value": (b - a) * price if price is not None else None})
    rows.sort(key=lambda r: (-(r["value"] or 0), -r["change"]))
    xp = exp_gained(start, end)
    mesos = (end["mesos"] - start["mesos"]) if None not in (start.get("mesos"), end.get("mesos")) else None
    gained_value = sum(r["value"] for r in rows if r["value"] and r["change"] > 0)
    used_value = -sum(r["value"] for r in rows if r["value"] and r["change"] < 0)
    unpriced = [r["name"] for r in rows if r["price"] is None]
    return {
        "minutes": round(hours * 60, 1),
        "exp": xp, "exp_per_hr": per_hr(xp) if xp is not None else None,
        "levels": int(end["level"]) - int(start["level"]),
        "mesos": mesos, "mesos_per_hr": per_hr(mesos) if mesos is not None else None,
        "items_gained_value": gained_value, "items_used_value": used_value,
        "net_mesos_incl_items": (mesos or 0) + gained_value - used_value,
        "net_per_hr": per_hr((mesos or 0) + gained_value - used_value),
        "unpriced": unpriced,
        "items": rows,
    }


def format_compare(r: dict) -> str:
    def f(v):
        return "-" if v is None else (f"{v:,.0f}" if isinstance(v, (int, float)) else str(v))

    lines = [
        f"Time            {r['minutes']} min",
        f"EXP             {f(r['exp'])}  ({f(r['exp_per_hr'])}/hr){'  +' + str(r['levels']) + ' level(s)' if r['levels'] else ''}",
        f"Mesos           {f(r['mesos'])}  ({f(r['mesos_per_hr'])}/hr)",
        f"Items gained    {f(r['items_gained_value'])} mesos of value",
        f"Items used      {f(r['items_used_value'])} mesos of value",
        f"Net incl items  {f(r['net_mesos_incl_items'])}  ({f(r['net_per_hr'])}/hr)",
        "",
        f"{'Item':<28}{'Before':>8}{'After':>8}{'Change':>8}{'Per hr':>9}{'Value':>10}",
    ]
    for it in r["items"]:
        lines.append(f"{it['name'][:27]:<28}{it['before']:>8}{it['after']:>8}{it['change']:>+8}"
                     f"{f(it['per_hr']):>9}{f(it['value']):>10}")
    if r["unpriced"]:
        lines += ["", "No price set for: " + ", ".join(r["unpriced"]),
                  "Set one with: grindcap label ITEM-ID --name \"Name\" --price N"]
    return "\n".join(lines)


def html_report(r: dict, catalog: Catalog, path: Path) -> Path:
    """Report with item icons, so unlabeled ids are easy to identify."""
    def icon(iid):
        p = catalog.icons_dir / f"{iid}.png"
        if not p.exists():
            return ""
        b64 = base64.b64encode(p.read_bytes()).decode()
        return f'<img src="data:image/png;base64,{b64}" width="32" height="32">'

    rows = "".join(
        f"<tr><td>{icon(it['id'])}</td><td>{it['name']}</td><td>{it['id']}</td><td>{it['before']}</td>"
        f"<td>{it['after']}</td><td>{it['change']:+}</td><td>{it['per_hr'] if it['per_hr'] is not None else '-'}</td>"
        f"<td>{it['price'] if it['price'] is not None else '-'}</td></tr>" for it in r["items"])
    html = f"""<!doctype html><meta charset="utf-8"><title>Grind comparison</title>
<style>body{{font:14px system-ui;margin:24px}}td,th{{padding:4px 10px;border-bottom:1px solid #ddd;text-align:right}}
td:nth-child(2),th:nth-child(2){{text-align:left}}</style>
<h1>Grind comparison</h1>
<p>{r['minutes']} min · EXP {r['exp']} ({r['exp_per_hr']}/hr) · Mesos {r['mesos']} ({r['mesos_per_hr']}/hr) ·
Net including items {r['net_mesos_incl_items']} ({r['net_per_hr']}/hr)</p>
<table><tr><th></th><th>Item</th><th>Id</th><th>Before</th><th>After</th><th>Change</th><th>Per hr</th><th>Price</th></tr>{rows}</table>"""
    path.write_text(html)
    return path


class PageCollector:
    """Collects inventory screenshots on hotkeys (F8 capture, F9 next tab, F10 done).

    Falls back to the terminal (Enter = capture, t = next tab, q = done) if global hotkeys aren't available.
    """

    def __init__(self, grab, tabs=("Equip", "Use", "Etc", "Setup"), terminal_delay: float = 2.0):
        self.grab = grab
        self.terminal_delay = terminal_delay
        self.tab_names = list(tabs)
        self.pages: dict[str, list] = {}
        self.i = 0

    @property
    def tab(self):
        return self.tab_names[self.i] if self.i < len(self.tab_names) else f"Tab{self.i + 1}"

    def capture(self):
        self.pages.setdefault(self.tab, []).append(self.grab())
        print(f"  captured {self.tab} page {len(self.pages[self.tab])}")

    def next_tab(self):
        self.i += 1
        print(f"  now on tab: {self.tab}")

    def run(self) -> dict:
        print(f"Open the inventory on the {self.tab} tab, scrolled to the top.")
        try:
            from pynput import keyboard
        except ImportError:
            return self._terminal()
        done = {"v": False}

        def on_press(key):
            if key == keyboard.Key.f8:
                self.capture()
            elif key == keyboard.Key.f9:
                self.next_tab()
            elif key == keyboard.Key.f10:
                done["v"] = True
                return False

        print("In game: F8 = capture this page, scroll down and F8 again until the end of the tab.")
        print("         F9 = switch to the next tab, F10 = finished.")
        with keyboard.Listener(on_press=on_press) as listener:
            listener.join()
        return self.pages

    def _terminal(self) -> dict:
        print("Press Enter to capture each page, type t + Enter for the next tab, q + Enter when done.")
        while True:
            cmd = input(f"[{self.tab}] > ").strip().lower()
            if cmd == "q":
                return self.pages
            if cmd == "t":
                self.next_tab()
            else:
                print(f"  switch to the game: capturing in {self.terminal_delay:.0f} s")
                time.sleep(self.terminal_delay)
                self.capture()
