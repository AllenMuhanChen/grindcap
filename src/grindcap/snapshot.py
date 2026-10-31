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


def last_level(cfg, before: float | None = None) -> tuple[int | None, int]:
    """(a level you were at before, how many levels you could have gained since): the latest snapshot
    whose level was confirmed by its EXP (+5), else the configured level (which may be old: +69)."""
    root = Path(cfg["inventory"]["snapshot_dir"])
    best = None
    for p in root.glob("*-*/snapshot.json"):
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        fx = p.parent / "fixes.json"
        fixed = (json.loads(fx.read_text()).get("status") or {}).get("level") if fx.exists() else None
        lv = fixed or d.get("level")
        if before is not None and d.get("time", 0) >= before:
            continue
        if lv and (d.get("exp_checked") or fixed) and (best is None or d.get("time", 0) > best[0]):
            best = (d.get("time", 0), int(lv))
    if best:
        return best[1], 5
    return cfg["character"].get("level"), 69


def read_status(cfg, frame, prior: int | None = None, when: float | None = None) -> dict:
    """EXP, level and meso total from one frame (whichever boxes are calibrated).

    Level comes from the orange level tiles and EXP from "53,791 [97.98%]"; the two are checked
    against the EXP table (statusbar.py), which also fixes a misread level digit."""
    from .statusbar import read_exp_texts, read_level, resolve, resolve_many

    out = {}
    tess = cfg["session"].get("tesseract_cmd")
    lv_box = (cfg["readers"].get("level") or {}).get("box")
    exp_box = (cfg["readers"].get("exp") or {}).get("box")
    level = read_level(frame, lv_box, tess)      # also finds the tiles without a box
    if level is not None:
        out["level"] = level
    pr, up = (prior, 5) if prior is not None else last_level(cfg, when)
    # finds the EXP text itself (the box is a fallback); stops at the first reading that fits
    texts = read_exp_texts(frame, exp_box, tess,
                           good=lambda t: resolve(t, level, pr, up)["checked"] and level is not None)
    if texts:
        r = resolve_many(texts, level, prior=pr, up=up)
        out["exp"], out["exp_pct"] = r["exp"], r["pct"]
        out["exp_raw"] = " | ".join(texts)
        out["exp_checked"] = r["checked"]
        out["level_options"] = r.get("level_options") or []
        if out["exp"] is None and exp_box:      # no "[xx.xx%]" read: plain OCR of the box as before
            t = TextReader(exp_box, tess).read(frame)
            out["exp"], out["exp_raw"] = t.value, t.raw
        if r["checked"] and r["level"] is not None:
            if level is not None and r["level"] != level:
                out["level_raw"] = f"read {level}, EXP fits {r['level']}"
            out["level"] = r["level"]
    rc = cfg["readers"].get("mesos") or {}
    if rc.get("box"):
        m = TextReader(rc["box"], tess).read(frame)
        out["mesos"], out["mesos_raw"] = m.value, m.raw
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
    if download and (not db.ready or db.missing_categories()):
        todo = db.missing_categories() if db.ready else None
        progress("Downloading item names and icons from maplestory.io (once, a minute or two)...")
        try:
            db.download(categories=todo, progress=progress) if todo else db.download(progress=progress)
        except Exception as e:
            progress(f"Couldn't download item data ({e}); items keep their item-NNN ids for now.")
            return None
    return db if db.ready else None


def read_mesos(cfg, frame):
    rc = cfg["readers"].get("mesos") or {}
    if not rc.get("box"):
        return None
    return TextReader(rc["box"], cfg["session"].get("tesseract_cmd")).read(frame).value


def build_snapshot(cfg, status_frame, tab_pages: dict[str, list[np.ndarray]], catalog: Catalog,
                   when: float | None = None, status: dict | None = None, progress=None) -> dict:
    """Read a snapshot. `status` = level/EXP/mesos/map already read from status_frame (e.g. when the
    snapshot was started), so they aren't read twice. `progress(text)` is told what's happening."""
    from .anchors import shifted
    from .digits import StackDigits

    inv = cfg["inventory"]
    digits = StackDigits(Path(inv["catalog_dir"]) / "digits.npz")
    itemdb = open_itemdb(cfg)
    from collections import Counter

    from .inventory import detect_tab, tab_from_items
    from .statusbar import meso_field_box, read_mesos_field

    say = progress or (lambda text: None)
    skip = set(inv.get("skip_tabs") or [])
    by_tab: dict[str, list] = {}
    first_page, boxes, merge_log, skipped = None, {}, {}, {}
    total = sum(len(v) for v in tab_pages.values())
    meso_reads = []      # the meso total, read on every page: the majority wins
    meso_where = []      # (value, page + field box) per read, for the picture on the review page
    done, seen = 0, []
    for given, frames in tab_pages.items():
        for i, f in enumerate(frames, 1):
            done += 1
            fc = shifted(cfg, f, ("inventory",))  # the inventory may be anywhere on screen
            grid = Grid.from_cfg(fc["inventory"])
            key = f"{given}_{i:02d}"              # = the screenshot's file name in the snapshot folder
            if first_page is None:
                first_page = (f, fc)
            if max(Counter(v for v, _ in meso_reads if v is not None).values(), default=0) < 3:
                mv, mraw = read_mesos_field(f, grid, cfg["session"].get("tesseract_cmd"))
                meso_reads.append((mv, mraw))
                meso_where.append((mv, {"page": key, "box": meso_field_box(grid)}))
            looks = detect_tab(f, grid) or given   # the open tab, from the highlighted tab button
            sig = _grid_crop_sig(f, grid)
            if sig is not None and any(float(np.abs(sig - o).mean()) < 1.0 for o in seen):
                continue                          # the very same view captured twice: nothing new
            seen.append(sig)
            say(f"Reading page {done} of {total} ({looks})")
            page = read_page(f, grid, catalog, digits, inv["empty_std"], inv["match_threshold"],
                             itemdb, page_key=key)
            # What's in the page decides the tab when it can (a tab with new items flashes, which
            # can fool the button check); the button is the fallback (e.g. Cash items aren't in the data).
            tab = tab_from_items(page, catalog, itemdb) or looks
            if tab in skip:
                skipped[tab] = skipped.get(tab, 0) + 1
                continue
            by_tab.setdefault(tab, []).append(page)
            for r, row in enumerate(grid.slot_boxes()):
                for c, b in enumerate(row):
                    boxes[f"{key}:r{r + 1}c{c + 1}"] = [int(v) for v in b]
    tabs = {}
    for tab, pages in by_tab.items():         # pages of one tab are stitched together, tabs separately
        tabs[tab] = merge_pages(pages, log := [])
        merge_log[tab] = log
    if status is not None:
        status = dict(status)
        where = status.pop("map", None)
    else:
        say("Reading level, EXP and map")
        status = {}
        if status_frame is not None:
            status = read_status(shifted(cfg, status_frame, ("status",)), status_frame, when=when)
        map_frame = status_frame if status_frame is not None else (first_page[0] if first_page else None)
        where = read_map_safe(cfg, map_frame) if map_frame is not None else None
    # The meso total lives in the inventory window: use what most pages agree on.
    seen_m = Counter(v for v, _ in meso_reads if v is not None)
    if seen_m:
        status["mesos"], n = seen_m.most_common(1)[0]
        status["mesos_raw"] = f"{n} of {len(meso_reads)} pages read {status['mesos']}"
        status["mesos_checked"] = n >= 2 or len(meso_reads) == 1
    elif first_page is not None and status.get("mesos") is None:
        f, fc = first_page                    # old way: the calibrated meso box
        m = read_mesos(fc, f)
        if m is not None:
            status["mesos"] = m
    # where the meso field is (a page that read the value used, else the first page tried)
    mesos_field = next((w for v, w in meso_where if v == status.get("mesos")),
                       meso_where[0][1] if meso_where else None)
    return {
        "time": when if when is not None else time.time(),
        "when": datetime.fromtimestamp(when or time.time()).isoformat(timespec="seconds"),
        "level": status.get("level") or cfg["character"]["level"],
        "level_read": status.get("level") is not None,
        "exp": status.get("exp"),
        "mesos": status.get("mesos"),
        "status_raw": {k: v for k, v in status.items() if k.endswith("_raw")},
        "exp_pct": status.get("exp_pct"),
        "exp_checked": status.get("exp_checked"),
        "mesos_checked": status.get("mesos_checked"),
        "mesos_field": mesos_field,
        "level_options": status.get("level_options") or [],
        "map": where,
        "tabs": {t: [[list(s) for s in row] for row in rows] for t, rows in tabs.items()},
        "items": totals(tabs),
        "merge_log": merge_log,
        "skipped_tabs": skipped,
        # every counted slot, so single slots can be corrected later (see apply_fixes)
        "slots": [{"ref": s[2], "item": s[0], "qty": s[1], "box": boxes.get(s[2]), "tab": tab}
                  for tab, rows in tabs.items() for row in rows for s in row if s[0] and len(s) > 2],
    }


def _grid_crop_sig(frame, grid):
    import cv2

    b = grid.slot_boxes()
    x0, y0 = b[0][0][0], b[0][0][1]
    x1, y1 = b[-1][-1][0] + b[-1][-1][2], b[-1][-1][1] + b[-1][-1][3]
    crop = frame[max(0, y0):y1, max(0, x0):x1]
    if crop.size == 0:
        return None
    return cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (60, 72), interpolation=cv2.INTER_AREA).astype(np.float32)


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
    from .sessions import load_pauses

    snap["pauses"] = load_pauses(p.parent)    # only a start snapshot has any
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
    from .sessions import paused_seconds

    start, end = apply_fixes(start), apply_fixes(end)
    paused = paused_seconds(start.get("pauses"), start["time"], end["time"])
    hours = (minutes / 60) if minutes else (end["time"] - start["time"] - paused) / 3600
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
        "paused_minutes": round(paused / 60, 1) if not minutes else 0,
        "exp": xp, "exp_per_hr": per_hr(xp) if xp is not None else None,
        "levels": int(end["level"]) - int(start["level"]),
        "mesos": mesos, "mesos_per_hr": per_hr(mesos) if mesos is not None else None,
        "items_gained_value": gained_value, "items_used_value": used_value,
        # revenue = what came in (mesos picked up, items gained); cost = what went out (items used,
        # mesos spent if your total went down)
        "revenue": max(mesos or 0, 0) + gained_value,
        "cost": used_value + max(-(mesos or 0), 0),
        "revenue_per_hr": per_hr(max(mesos or 0, 0) + gained_value),
        "cost_per_hr": per_hr(used_value + max(-(mesos or 0), 0)),
        "net_mesos_incl_items": (mesos or 0) + gained_value - used_value,
        "net_per_hr": per_hr((mesos or 0) + gained_value - used_value),
        "unpriced": unpriced,
        "items": rows,
    }


def _f(v):
    return "-" if v is None else (f"{v:,.0f}" if isinstance(v, (int, float)) else str(v))


def key_figures(r: dict) -> list[str]:
    """The headline lines of a comparison: net mesos/hr, EXP/hr, revenue/cost per hr, time."""
    f = _f
    m = r["minutes"] or 0
    paused = r.get("paused_minutes") or 0
    return [
        f"NET MESOS / HR  {f(r['net_per_hr'])}   (incl. items)",
        f"EXP / HR        {f(r['exp_per_hr'])}{'   +' + str(r['levels']) + ' level(s)' if r['levels'] else ''}",
        f"Revenue / hr    {f(r['revenue_per_hr'])}   Cost / hr {f(r['cost_per_hr'])}",
        f"Time            {int(m // 60)}:{int(round(m % 60)):02d}"
        + (f"   (+{paused:.0f} min paused, not counted)" if paused >= 0.5 else ""),
    ]


def live_exp(start: dict, reading: dict, now: float) -> dict | None:
    """EXP gained and EXP/hr so far, from the start snapshot and a status-bar reading taken now
    (skipping paused time). None unless the reading's EXP was confirmed by the EXP table."""
    from .sessions import active_seconds

    start = apply_fixes(start)
    if not reading.get("exp_checked") or reading.get("exp") is None or reading.get("level") is None:
        return None
    xp = exp_gained(start, {"exp": reading["exp"], "level": reading["level"], "level_read": True})
    secs = active_seconds(start["time"], now, start.get("pauses"))
    if xp is None or xp < 0 or secs <= 0:
        return None
    pct = _level_pct(start, reading)
    return {"exp": xp, "exp_per_hr": round(xp / secs * 3600, 1), "minutes": round(secs / 60, 1),
            "level": reading["level"], "pct_per_hr": round(pct / secs * 3600, 2) if pct is not None else None}


def _level_pct(start: dict, reading: dict) -> float | None:
    """Level progress between start and reading, in % of a level (a level-up counts 100%)."""
    def frac(s):
        need = exp_to_next(int(s["level"]))
        return int(s["level"]) + s["exp"] / need if need else None
    a, b = frac(start), frac(reading)
    return None if a is None or b is None else (b - a) * 100


def live_series(start: dict, rows: list[dict], tau_min: float = 5.0) -> list[dict]:
    """EXP/hr over a session from its live readings (<start>/live.jsonl rows: time, exp, level, checked).

    Per point: t = active minutes since start (paused time left out), exp = EXP gained so far,
    raw = EXP/hr since the previous point, ema = raw smoothed by an exponential moving average with
    time constant tau_min (weight 1 - exp(-dt/tau), so uneven gaps and pauses are handled),
    cum = EXP/hr since start, pct = level %/hr since start. Unconfirmed readings, and readings whose
    EXP went down (a misread), are skipped."""
    from math import exp as _exp

    from .sessions import active_seconds

    start = apply_fixes(start)
    if start.get("exp") is None or start.get("level") is None:
        return []
    out, prev_s, prev_x, ema = [], 0.0, 0.0, None
    for row in sorted(rows, key=lambda r: r.get("time", 0)):
        if not row.get("checked") or row.get("exp") is None or row.get("level") is None:
            continue
        reading = {"exp": row["exp"], "level": row["level"], "level_read": True}
        xp = exp_gained(start, reading)
        secs = active_seconds(start["time"], row["time"], start.get("pauses"))
        if xp is None or xp < prev_x or secs <= prev_s:
            continue
        dt = secs - prev_s
        raw = (xp - prev_x) / dt * 3600
        ema = raw if ema is None else ema + (1 - _exp(-dt / (tau_min * 60))) * (raw - ema)
        pct = _level_pct(start, reading)
        out.append({"t": round(secs / 60, 2), "exp": xp, "raw": round(raw, 1), "ema": round(ema, 1),
                    "cum": round(xp / secs * 3600, 1),
                    "pct": round(pct / secs * 3600, 2) if pct is not None else None})
        prev_s, prev_x = secs, xp
    return out


def y_range(points: list[dict]) -> tuple[float, float]:
    """Y-axis limits for an EXP/hr graph: the range of the smoothed and session lines plus 25% of it on
    each side (at least 5% of the top), not from 0, so a change of a few % is visible."""
    vals = [p[k] for p in points for k in ("ema", "cum")]
    lo, hi = min(vals), max(vals)
    pad = max((hi - lo) * 0.25, hi * 0.05, 1.0)
    return max(0.0, lo - pad), hi + pad


def load_live(start_folder) -> list[dict]:
    """Rows of <start>/live.jsonl ([] for sessions from before live readings were logged)."""
    p = Path(start_folder) / "live.jsonl"
    rows = []
    if p.exists():
        for line in p.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    return rows


def format_compare(r: dict) -> str:
    f = _f
    lines = key_figures(r) + [
        "",
        f"  mesos {f(r['mesos'])}, items gained {f(r['items_gained_value'])}, used {f(r['items_used_value'])}",
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
