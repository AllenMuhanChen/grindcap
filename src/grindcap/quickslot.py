"""Quick slots: which potions are on the 2x4 quick slot panel and how many are left, read off the screen.

The panel is found by template matching (data/quickslot_panel.png, cut from a real 1920x1080 screenshot
by scripts/build_quickslot_template.py; only the frame and the gaps between slots are compared, so the
items in the slots don't matter). A slot's number is the item's total count in the inventory, drawn in
the same font as inventory stack numbers, so digits.StackDigits reads it.

Which item a slot holds: quickslot.slots in config.yaml ({"Del": "Orange Potion"}) if set, else the item
database (itemdb.identify) with the key label and the number left out of the comparison. Whether it is
an HP or MP potion and what an NPC shop charges for it: POTIONS below, or quickslot.prices in config.

Potions used = the drops in each item's count between readings (rises are restocks or pickups and are
ignored). A single misread (a reading outside its neighbours' range while they agree) is skipped.
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


def read_quickslot(frame, digits, itemdb=None, names: dict | None = None, cache: dict | None = None) -> list[dict]:
    """Every slot with a number: {"key", "count", "name"} (name None if it couldn't be told).
    `names` = quickslot.slots from config (key -> item name). `cache` remembers identified icons
    (key -> (icon signature, name)) so an item is looked up once, not every minute."""
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
                name = _identify(patch, ignore, itemdb, key, cache)
        out.append({"key": key, "count": n, "name": name})
    return out


def _identify(patch, ignore, itemdb, key, cache) -> str | None:
    import cv2

    sig = cv2.resize(patch, (8, 8), interpolation=cv2.INTER_AREA).astype(np.float32)
    hit = cache.get(key)
    if hit and np.abs(hit[0] - sig).mean() < 12:     # same icon as last time: same item
        return hit[1]
    m = itemdb.identify(patch, ignore)
    cache[key] = (sig, m.name if m else None)
    return cache[key][1]


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


def potion_series(start: dict, rows: list[dict], price_table: dict) -> list[dict]:
    """Mesos spent on HP and MP potions over a session, from live readings that carry "potions"
    ([{"key", "count", "name"}]). Per point: t (active minutes), hp, mp (mesos used so far, at NPC
    shop price), used ({name: count}). Items without a known kind/price are left out."""
    from .sessions import active_seconds

    rows = sorted((r for r in rows if r.get("potions") is not None), key=lambda r: r["time"])
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
            if i and x is not None and sm[i - 1] is not None and x < sm[i - 1]:
                total += sm[i - 1] - x
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
        out.append({"t": round(secs / 60, 2), "hp": cost["hp"], "mp": cost["mp"], "used": used})
    return out
