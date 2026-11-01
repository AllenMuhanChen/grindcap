"""Quick slots: which potions are on the 2x4 quick slot panel and how many are left, read off the screen.

The panel is found by template matching (data/quickslot_panel.png, cut from a real 1920x1080 screenshot
by scripts/build_quickslot_template.py; only the frame and the gaps between slots are compared, so the
items in the slots don't matter). A slot's number is the item's total count in the inventory, drawn in
the same font as inventory stack numbers, so digits.StackDigits reads it.

Which item a slot holds: quickslot.slots in config.yaml ({"Del": "Orange Potion"}) if set, else the item
database (itemdb.identify) with the key label and the number left out of the comparison. Whether it is
an HP or MP potion and what an NPC shop charges for it: POTIONS below, or quickslot.prices in config.

Potions used = the net drop in each item's count between readings: potions gained (pickups, buying)
count as negative use. A single misread (a reading outside its neighbours' range while they agree) is skipped.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

TEMPLATE = Path(__file__).parent / "data" / "quickslot_panel.png"
PANEL = (1310, 880, 215, 112)      # panel box in tests/fixtures/game_frame.png (screen px at 1920x1080)
SLOT0 = (13, 7)                    # first slot's top-left inside the panel
PITCH = (49.3, 48.0)               # screen px between slots at 1920x1080
SLOT = 40                          # screen px
KEYS = ["Shift", "Ins", "Hm", "PgUp", "Ctrl", "Del", "End", "PgDn"]   # default key layout, row by row
LABEL_H = 10                       # native px of key label at the top of a slot
MAX_DIFF = 900                     # mean squared grey difference over the template's pixels to accept

# NPC shop price (mesos) and what each potion restores, for the potions general stores sell.
# Override or add with quickslot.prices in config.yaml: {"Name": ["hp"|"mp", price]}.
POTIONS = {
    "Red Potion": ("hp", 50),
    "Orange Potion": ("hp", 160),
    "White Potion": ("hp", 320),
    "Blue Potion": ("mp", 200),
    "Mana Elixir": ("mp", 620),
    "Lemon": ("mp", 150),          # restores MP; not sold by NPCs, 150 = what Allen pays (2026-11-01)
}


def slot_offsets(scale: float) -> list[tuple[float, float]]:
    """Top-left of each slot relative to the panel's top-left, row by row."""
    return [((SLOT0[0] + PITCH[0] * c) * scale, (SLOT0[1] + PITCH[1] * r) * scale)
            for r in range(2) for c in range(4)]


def find_panel(frame) -> tuple[int, int, float] | None:
    """(x, y, scale) of the quick slot panel, or None if it isn't on screen."""
    import cv2

    t = cv2.imread(str(TEMPLATE), cv2.IMREAD_UNCHANGED)
    s = frame.shape[0] / 1080
    if abs(s - 1) > 0.02:
        t = cv2.resize(t, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    y0 = frame.shape[0] * 2 // 3              # the panel sits at the bottom of the window
    region = cv2.cvtColor(frame[y0:], cv2.COLOR_BGR2GRAY).astype(np.float32)
    if region.shape[0] < t.shape[0] or region.shape[1] < t.shape[1]:
        return None
    tg = cv2.cvtColor(t[..., :3], cv2.COLOR_BGR2GRAY).astype(np.float32)
    m = (t[..., 3] > 127).astype(np.float32)
    r = cv2.matchTemplate(region, tg, cv2.TM_SQDIFF, mask=m) / max(float(m.sum()), 1.0)
    score, _, loc, _ = cv2.minMaxLoc(r)
    return (loc[0], loc[1] + y0, s) if score <= MAX_DIFF else None


def slot_boxes(frame) -> list[list[int]] | None:
    p = find_panel(frame)
    if p is None:
        return None
    x, y, s = p
    return [[round(x + dx), round(y + dy), round(SLOT * s), round(SLOT * s)] for dx, dy in slot_offsets(s)]


def read_quickslot(frame, digits, itemdb=None, names: dict | None = None, cache: dict | None = None,
                   candidates: list[int] | None = None) -> list[dict]:
    """Every slot with a number: {"key", "count", "name"} (name None if it couldn't be told).
    `names` = quickslot.slots from config (key -> item name). `cache` remembers identified icons
    (key -> (icon signature, name)) so an item is looked up once, not every minute. `candidates` =
    item database ids the slot can be (the Use items in your catalog, see use_candidates)."""
    from .digits import slot_patch

    boxes = slot_boxes(frame)
    if boxes is None:
        return []
    s = frame.shape[0] / 1080
    px, py = PITCH[0] * s, PITCH[1] * s
    view = digits.page_view(frame, boxes, px, color=itemdb is not None)
    origins = digits.slot_origins(view, boxes, px, py, boxes[0])
    readings = digits.read_view(view, origins)
    ox, oy = digits.last_offset
    names, cache = names or {}, cache if cache is not None else {}
    out = []
    for key, r, (u, v) in zip(KEYS, readings, origins):
        n = 0 if r.text == "0" and r.costs[0] < 0.2 else r.value     # a lone "0" must be a clear one
        if n is None:
            continue
        name = names.get(key)
        if name is None and itemdb is not None:
            patch = slot_patch(view, u, v)
            if patch is not None:
                ignore = digits.digit_mask(r, patch.shape[:2], -4 - ox, -4 - oy)
                ignore[:4 + LABEL_H] = True       # the key label is drawn over the icon's top
                name = _identify(patch, ignore, itemdb, key, cache, candidates)
        out.append({"key": key, "count": n, "name": name})
    return out


def match_by_count(potions: list[dict], items: dict[str, int], catalog, itemdb=None, near: int = 5) -> dict:
    """Name each quick slot from the start snapshot's inventory: a quick slot's number is that item's
    total in the inventory, so the item with the same count is the one (the inventory read names items
    reliably; a quick slot icon has its key label drawn over it). Only Use items count if the item
    database is there. Several items with that count: the icon match decides if it names one of them,
    else unknown. No exact count (a potion used while paging through the inventory): the closest
    count within `near`, if only one item is that close. Returns {key: name}."""
    def is_use(cid):
        db = (catalog.items.get(cid, {}).get("db") or {}).get("id")
        return itemdb is None or (db is not None and (itemdb.items.get(int(db)) or {}).get("category") == "Use")

    pool = [(cid, n, catalog.items[cid].get("name")) for cid, n in items.items()
            if cid in catalog.items and catalog.items[cid].get("name") and is_use(cid)]
    out = {}
    for p in potions or []:
        same = [name for _, n, name in pool if n == p["count"]]
        if len(same) == 1:
            out[p["key"]] = same[0]
        elif len(same) > 1:
            if p.get("name") in same:
                out[p["key"]] = p["name"]
        else:
            close = sorted((abs(n - p["count"]), name) for _, n, name in pool if abs(n - p["count"]) <= near)
            if close and (len(close) == 1 or close[1][0] > close[0][0]):
                out[p["key"]] = close[0][1]
    return out


def use_candidates(catalog, itemdb) -> list[int]:
    """Database ids of the Use items in your catalog: what you've ever had in the Use tab. Only things
    you own can be on a quick slot with a count, so a quick slot is matched against these only."""
    ids = []
    for it in catalog.items.values():
        db = (it.get("db") or {}).get("id")
        if db is not None and (itemdb.items.get(int(db)) or {}).get("category") == "Use" and int(db) not in ids:
            ids.append(int(db))
    return ids


def _identify(patch, ignore, itemdb, key, cache, candidates=None) -> str | None:
    """Closest icon among `candidates` (else among all Use items) with the key label and the number
    left out. The key label covers the icon's top, so the general match (every Etc/Use/Setup icon)
    mixes potions up with look-alikes from other tabs (an Orange Potion read as a brick)."""
    import cv2

    sig = cv2.resize(patch, (8, 8), interpolation=cv2.INTER_AREA).astype(np.float32)
    hit = cache.get(key)
    if hit and np.abs(hit[0] - sig).mean() < 12:     # same icon as last time: same item
        return hit[1]
    ids = candidates or [i for _, i in itemdb.rank(patch, None) if itemdb.items[i].get("category") == "Use"][:20]
    ranked = itemdb.rescore(patch, ignore, ids)
    name = None
    if ranked and ranked[0][0] <= itemdb.max_score:
        s0, best = ranked[0]
        name = itemdb.items[best]["name"]
        other = next((s for s, i in ranked[1:] if itemdb.items[i]["name"] != name), None)
        if other is not None and s0 > 0 and other / s0 < 1.1:     # two different items fit about equally
            name = None
    cache[key] = (sig, name)
    return name


def describe(potions: list[dict] | None, price_table: dict) -> str:
    """One line saying what the last quick slot reading found, so you can see the scan worked."""
    if potions is None:
        return "Potions: quick slots not found"
    parts = []
    for p in potions:
        name = p.get("name") or "unknown item"
        note = "" if p.get("name") in price_table else " (not counted)"
        parts.append(f"{p['key']} {name} {p['count']}{note}")
    return "Potions: " + (" · ".join(parts) if parts else "none on the quick slots")


def prices(cfg_prices: dict | None = None) -> dict[str, tuple[str, int]]:
    out = dict(POTIONS)
    for name, v in (cfg_prices or {}).items():
        out[name] = (str(v[0]).lower(), int(v[1]))
    return out


def _drop_misreads(xs: list) -> list:
    """A reading outside the range of its two neighbours while those two agree (within 20%) is a misread
    (90, 9, 85): it is replaced by the reading before it. Steps such as a restock (85, 200, 195) stay."""
    out = list(xs)
    for i in range(1, len(xs) - 1):
        a, x, b = out[i - 1], xs[i], xs[i + 1]
        if None in (a, x, b):
            continue
        if not min(a, b) <= x <= max(a, b) and abs(a - b) <= 0.2 * max(a, b, 1):
            out[i] = a
    return out


def load_names(start_folder) -> dict:
    """{key: item name} for a session's quick slots (<start>/quickslot.json), {} if not set."""
    import json

    p = Path(start_folder) / "quickslot.json"
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except ValueError:
        return {}


def potion_series(start: dict, rows: list[dict], price_table: dict, tau_min: float = 5.0,
                  key_names: dict | None = None) -> list[dict]:
    """Mesos spent on HP and MP potions over a session, from live readings that carry "potions"
    ([{"key", "count", "name"}]). Per point: t (active minutes), hp, mp (mesos used so far, at NPC
    shop price), used ({name: count}), and per kind (hp, mp) the spending rate in mesos/hr like the EXP
    graph: raw_* since the previous reading, ema_* (exponential moving average, time constant tau_min),
    cum_* since the start (rates are None on the first reading). Items without a known kind/price are
    left out. `key_names` ({key: name}, see load_names) overrides the names logged with each reading."""
    from math import exp as _exp

    from .sessions import active_seconds

    key_names = key_names or {}
    rows = sorted(({**r, "potions": [{**p, "name": key_names.get(p["key"], p.get("name"))} for p in r["potions"]]}
                   for r in rows if r.get("potions") is not None), key=lambda r: r["time"])
    if not rows:
        return []
    names = sorted({p["name"] for r in rows for p in r["potions"] if p.get("name") in price_table})
    counts = {n: [] for n in names}
    for r in rows:
        seen = {p["name"]: p["count"] for p in r["potions"] if p.get("name") in counts}
        for n in names:
            counts[n].append(seen.get(n))
    used_so_far = {}
    for n, xs in counts.items():
        # fill gaps (slot not read) with the previous value, then smooth single misreads
        last, filled = None, []
        for x in xs:
            last = x if x is not None else last
            filled.append(last)
        sm = _drop_misreads(filled)
        total, run = 0, []
        for i, x in enumerate(sm):
            if i and x is not None and sm[i - 1] is not None:
                total += sm[i - 1] - x          # net: potions gained (drops, buying) count as negative
            run.append(total)
        used_so_far[n] = run
    out = []
    for i, r in enumerate(rows):
        secs = active_seconds(start["time"], r["time"], start.get("pauses"))
        used = {n: used_so_far[n][i] for n in names}
        cost = {"hp": 0, "mp": 0}
        for n, k in used.items():
            kind, price = price_table[n]
            if kind in cost:
                cost[kind] += k * price
        p = {"t": round(secs / 60, 2), "hp": cost["hp"], "mp": cost["mp"], "used": used}
        prev = out[-1] if out else None
        dt = secs - prev["t"] * 60 if prev else 0
        for kind in ("hp", "mp"):
            raw = ema = cum = None
            if prev and dt > 0:
                raw = (p[kind] - prev[kind]) / dt * 3600
                pe = prev[f"ema_{kind}"]
                ema = raw if pe is None else pe + (1 - _exp(-dt / (tau_min * 60))) * (raw - pe)
                cum = p[kind] / secs * 3600
            elif prev:                              # no active time since the last reading: carry on
                raw, ema, cum = (prev[f"{x}_{kind}"] for x in ("raw", "ema", "cum"))
            p[f"raw_{kind}"], p[f"ema_{kind}"], p[f"cum_{kind}"] = (
                round(v, 1) if v is not None else None for v in (raw, ema, cum))
        out.append(p)
    return out
