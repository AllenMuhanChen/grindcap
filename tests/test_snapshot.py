"""Before/after snapshot mode on synthetic inventory screens."""
import shutil

import cv2
import numpy as np
import pytest

from grindcap.config import Config, DEFAULT_CONFIG, _merge
from grindcap.inventory import Catalog, merge_pages
from grindcap.snapshot import build_snapshot, compare, exp_gained

HAS_TESS = shutil.which("tesseract") is not None
SLOT, GAP, X0, Y0, COLS, ROWS = 32, 4, 20, 60, 4, 6   # 36 px pitch = the game at native size


def draw_number(cell: np.ndarray, n: int, x: int = 1, y: int = 20):
    """Stamp a stack number in the game's font (the built-in templates) onto a slot, like the game does."""
    from grindcap.digits import ADV, FONT_H, StackDigits

    font = StackDigits()
    for d in str(n):
        t = font.templates[d]
        reg = cell[y:y + FONT_H, x:x + ADV[d]]
        reg[t.mask] = np.clip(t.img[t.mask], 0, 255).astype(np.uint8)[:, None]
        x += ADV[d]


def icon(seed: int) -> np.ndarray:
    """A distinct, deterministic 32x32 'item icon'."""
    rng = np.random.default_rng(seed)
    img = np.full((SLOT, SLOT, 3), 235, np.uint8)
    for _ in range(5):
        c = tuple(int(v) for v in rng.integers(70, 210, 3))  # no near-black: stack digits are black here
        x, y = (int(v) for v in rng.integers(2, 20, 2))
        cv2.rectangle(img, (x, y), (x + int(rng.integers(8, 18)), y + int(rng.integers(6, 14))), c, -1)
    return img


def header(img, ox=0, oy=0):
    """The inventory window's title bar: fixed artwork above the grid."""
    cv2.rectangle(img, (X0 - 6 + ox, Y0 - 40 + oy), (X0 + 170 + ox, Y0 - 12 + oy), (40, 120, 200), -1)
    cv2.putText(img, "INVENTORY", (X0 + ox, Y0 - 18 + oy), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    cv2.circle(img, (X0 + 150 + ox, Y0 - 26 + oy), 7, (0, 0, 180), -1)


def inventory_screen(items: list[tuple[int, int] | None], top_row: int = 0, ox: int = 0, oy: int = 0) -> np.ndarray:
    """Draw the visible 4x6 window of a longer inventory list, scrolled so `top_row` is at the top.

    (ox, oy) moves the whole inventory window on screen.
    """
    img = np.full((460, 380, 3), (70, 60, 55), np.uint8)
    header(img, ox, oy)
    for r in range(ROWS):
        for c in range(COLS):
            i = (top_row + r) * COLS + c
            x, y = X0 + c * (SLOT + GAP) + ox, Y0 + r * (SLOT + GAP) + oy
            cell = np.full((SLOT, SLOT, 3), 235, np.uint8)  # empty slot: flat
            if i < len(items) and items[i]:
                seed, qty = items[i]
                cell = icon(seed)
                if qty > 1:
                    draw_number(cell, qty)
            img[y:y + SLOT, x:x + SLOT] = cell
    return img


def status_screen(exp: int, mesos: int) -> np.ndarray:
    img = np.full((120, 320, 3), 255, np.uint8)
    cv2.putText(img, str(exp), (8, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2)
    cv2.putText(img, f"{mesos:,}", (8, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2)
    return img


def cfg():
    c = Config(_merge(DEFAULT_CONFIG, {}))
    c.data["character"]["level"] = 20
    c.data["readers"]["exp"]["box"] = [0, 5, 320, 50]
    c.data["readers"]["mesos"]["box"] = [0, 65, 320, 50]
    inv = c.data["inventory"]
    inv["itemdb"]["enabled"] = False   # no downloads in tests
    inv["first_slot"] = [X0, Y0, SLOT, SLOT]
    inv["last_slot"] = [X0 + 3 * (SLOT + GAP), Y0 + 5 * (SLOT + GAP), SLOT, SLOT]
    return c


def slot_with(seed, qty):
    cell = icon(seed)
    draw_number(cell, qty)
    return cell


def test_stack_numbers_on_synthetic_slots():
    from grindcap.digits import StackDigits

    nums = [13, 40, 7, 25, 60, 9, 2, 3, 15, 98, 111, 1047]
    img = np.full((80, 36 * len(nums) + 20, 3), (70, 60, 55), np.uint8)
    boxes = []
    for i, n in enumerate(nums):
        x, y = 10 + 36 * i, 20
        img[y:y + SLOT, x:x + SLOT] = slot_with(i + 1, n)
        boxes.append((x, y, SLOT, SLOT))
    got = [r.value for r in StackDigits().read_slots(img, boxes, 36, 0)]
    assert got == nums


REAL = [[1, 1, 1, 59, 68], [0, 0, 1, 0, 1], [0, 52, 52, 14, 0],
        [160, 81, 13, 0, 1], [105, 0, 0, 0, 0], [66, 0, 52, 0, 97]]


@pytest.mark.parametrize("dx,dy,roll", [(0, 0, 0), (3, -2, 0), (-2, 3, 0), (0, 0, 3), (0, 0, 5)])
def test_stack_numbers_on_real_screenshot(dx, dy, roll):
    """The real game at 1920x1080 (drawn at 1366x768 and stretched). Boxes drawn a few pixels off and
    the picture shifted (a different sub-pixel offset) must still read every number."""
    from pathlib import Path

    from grindcap.digits import StackDigits
    from grindcap.inventory import Grid, is_empty

    frame = cv2.imread(str(Path(__file__).parent / "fixtures" / "game_frame.png"))
    frame = np.roll(frame, (roll, roll), axis=(0, 1))
    o = roll
    g = Grid([1494 + dx + o, 139 + dy + o, 44, 44], [1695 + dx + o, 377 + dy + o, 44, 44], cols=5, rows=6)
    boxes = [b for row in g.slot_boxes() for b in row]
    got = [r.value for r in StackDigits().read_slots(frame, boxes, *g.pitch())]
    want = [n or None for row in REAL for n in row]
    assert got == want
    empty = [is_empty(frame[y:y + h, x:x + w], g.qty_box, 6.0) for x, y, w, h in boxes]
    assert empty == [n == 0 for row in REAL for n in row]


def test_merge_pages_drops_overlap_and_keeps_empty_tail():
    a = [[("i1", 1)], [("i2", 3)], [("i3", 5)]]
    b = [[("i2", 3)], [("i3", 5)], [("i4", 2)]]
    c = [[("i4", 2)], [(None, 0)], [(None, 0)]]
    merged = merge_pages([a, b, c])
    assert [r[0][0] for r in merged] == ["i1", "i2", "i3", "i4", None, None]


def test_merge_pages_unscrolled_duplicate_page():
    a = [[("i1", 1)], [("i2", 3)]]
    assert merge_pages([a, a]) == a


def test_exp_gained_across_level_up():
    s = {"exp": 20000, "level": 20, "level_read": True}
    e = {"exp": 500, "level": 21, "level_read": True}
    assert exp_gained(s, e) == (20216 - 20000) + 500


@pytest.mark.skipif(not HAS_TESS, reason="Tesseract not installed")
def test_snapshot_compare_end_to_end(tmp_path):
    c = cfg()
    c.data["inventory"]["catalog_dir"] = str(tmp_path / "data")
    cat = Catalog(c["inventory"]["catalog_dir"])

    # 10 rows of inventory: seed = item identity, qty = stack size
    before = [(s, q) for s, q in [(1, 13), (2, 1), (3, 40), (4, 7), (5, 1), (6, 25), (7, 3), (8, 1),
                                   (9, 15), (10, 2), (11, 60), (12, 1), (13, 9)]] + [None] * 27
    after = list(before)
    after[0] = (1, 32)      # +19 of item 1 (e.g. an etc drop)
    after[2] = (3, 22)      # -18 of item 3 (potions drunk)
    after[13] = (14, 4)     # a new item
    pages = lambda items: [inventory_screen(items, 0), inventory_screen(items, 4)]  # rows 4-5 overlap

    s = build_snapshot(c, status_screen(5000, 1_000), {"Etc": pages(before)}, cat, when=0)
    e = build_snapshot(c, status_screen(6560, 4_300), {"Etc": pages(after)}, Catalog(c["inventory"]["catalog_dir"]), when=1800)
    assert sum(s["items"].values()) == sum(q for x in before if x for _, q in [x])
    r = compare(s, e, Catalog(c["inventory"]["catalog_dir"]))
    assert r["minutes"] == 30
    assert r["exp"] == 1560 and r["exp_per_hr"] == 3120
    assert r["mesos"] == 3300
    changes = sorted(it["change"] for it in r["items"])
    assert changes == [-18, 4, 19]


@pytest.mark.skipif(not HAS_TESS, reason="Tesseract not installed")
def test_inventory_found_after_moving_window(tmp_path):
    from grindcap.anchors import save_anchor

    c = cfg()
    c.data["inventory"]["catalog_dir"] = str(tmp_path / "data")
    items = [(1, 13), (2, 1), (3, 40), (4, 7), (5, 1), (6, 25)] + [None] * 18
    calib = inventory_screen(items)
    save_anchor(c, "inventory", calib, (X0 - 6, Y0 - 40, 176, 28))

    s = build_snapshot(c, None, {"Etc": [inventory_screen(items)]}, Catalog(c["inventory"]["catalog_dir"]), when=0)
    moved = list(items)
    moved[0] = (1, 20)
    e = build_snapshot(c, None, {"Etc": [inventory_screen(moved, ox=90, oy=55)]},
                       Catalog(c["inventory"]["catalog_dir"]), when=600)
    r = compare(s, e, Catalog(c["inventory"]["catalog_dir"]))
    assert [(it["before"], it["after"]) for it in r["items"]] == [(13, 20)]


def test_missing_window_is_reported(tmp_path):
    from grindcap.anchors import locate, save_anchor

    c = cfg()
    c.data["inventory"]["catalog_dir"] = str(tmp_path / "data")
    save_anchor(c, "inventory", inventory_screen([]), (X0 - 6, Y0 - 40, 176, 28))
    with pytest.raises(LookupError):
        locate(c, "inventory", np.full((460, 380, 3), (70, 60, 55), np.uint8))


def test_merge_skips_repeated_pages_even_with_one_slot_misread():
    tab_a = [[("a1", 5), ("a2", 1), ("a3", 9)], [("a4", 2), ("a5", 7), (None, 0)]]
    tab_b = [[("b1", 3), ("b2", 1), ("b3", 4)], [("b4", 8), (None, 0), (None, 0)]]
    a_again = [[("a1", 5), ("a2", 1), ("a3", 9)], [("a4", 2), ("x9", 7), (None, 0)]]  # cursor over a5
    merged = merge_pages([tab_a, tab_a, tab_b, a_again, tab_a])
    assert merged == tab_a + tab_b


def test_merge_scroll_overlap_tolerates_one_odd_slot():
    rows = [[(f"i{r}{c}", r + c) for c in range(5)] for r in range(9)]
    p1, p2 = rows[0:6], [list(r) for r in rows[3:9]]
    p2[0][2] = ("hover", 1)            # one slot looks different in the overlap
    merged = merge_pages([p1, p2])
    assert len(merged) == 9 and merged[3][2] == rows[3][2]


def test_merge_skips_page_scrolled_back_to():
    a = [[("i1", 1)], [("i2", 3)], [("i3", 5)]]
    b = [[("i3", 5)], [("i4", 2)], [("i5", 1)]]
    back = [[("i2", 3)], [("i3", 5)], [("i4", 2)]]   # scrolled back up one row
    merged = merge_pages([a, b, back])
    assert [r[0][0] for r in merged] == ["i1", "i2", "i3", "i4", "i5"]


def test_page_watcher_captures_once_per_settled_page(tmp_path):
    from grindcap.anchors import save_anchor
    from grindcap.inventory import PageWatcher

    c = cfg()
    c.data["inventory"]["catalog_dir"] = str(tmp_path / "data")
    items = [(s, s) for s in range(1, 41)]
    save_anchor(c, "inventory", inventory_screen(items), (X0 - 6, Y0 - 40, 176, 28))
    w = PageWatcher(c, stable=2)
    closed = np.full((460, 380, 3), (70, 60, 55), np.uint8)
    seq = ([closed] * 2                                   # inventory closed: nothing
           + [inventory_screen(items, 0)] * 4             # page 1 settles: capture once
           + [inventory_screen(items, 2)] * 1             # mid-scroll frame
           + [inventory_screen(items, 4, ox=30)] * 3      # page 2 (window also moved): capture once
           + [inventory_screen(items, 4, ox=30)] * 3)     # still the same: nothing
    caps = [i for i, f in enumerate(seq) if w.feed(f)]
    assert caps == [3, 8]


@pytest.mark.skipif(not HAS_TESS, reason="Tesseract not installed")
def test_snapflow_auto_pages_start_end_compare(tmp_path):
    from grindcap.anchors import save_anchor
    from grindcap.app import SnapFlow

    c = cfg()
    c.data["inventory"]["catalog_dir"] = str(tmp_path / "data")
    c.data["inventory"]["snapshot_dir"] = str(tmp_path / "snaps")
    before = [(1, 13), (2, 1), (3, 40), (4, 7), (5, 1), (6, 25), (7, 3), (8, 1), (9, 15), (10, 2)] + [None] * 30
    after = list(before)
    after[0] = (1, 33)
    after[2] = (3, 31)
    save_anchor(c, "inventory", inventory_screen(before), (X0 - 6, Y0 - 40, 176, 28))

    def run(items, which):
        frames = iter([inventory_screen(items)]                        # status grab (inventory open)
                      + [inventory_screen(items, 0)] * 3 + [inventory_screen(items, 4)] * 3)
        flow = SnapFlow(c, lambda: next(frames))
        flow.start(which)
        caught = sum(flow.poll() for _ in range(6))
        assert caught == 2
        return flow.finish(), flow

    info, _ = run(before, "start")
    assert info["count"] == sum(q for x in before if x for _, q in [x])
    _, flow = run(after, "end")
    text, report = flow.compare(minutes=30)
    assert report.exists()
    assert "+20" in text and "-9" in text


def fake_itemdb(folder, entries):
    """An ItemDB folder with the given {item_id: (name, seed)} icons (RGBA, transparent background)."""
    import json as _json

    from grindcap.itemdb import ItemDB

    (folder / "icons").mkdir(parents=True)
    items = {}
    for iid, (name, seed) in entries.items():
        rgb = icon(seed)
        alpha = np.where((rgb != 235).any(axis=2), 255, 0).astype(np.uint8)
        cv2.imwrite(str(folder / "icons" / f"{iid}.png"), np.dstack([rgb, alpha])[2:30, 2:30])
        items[iid] = {"name": name, "category": "Etc", "price": iid % 100}
    (folder / "items.json").write_text(_json.dumps(items))
    return ItemDB(folder)


def recolor(seed):
    """Same icon as `seed` with its colours shifted: a look-alike (like Iron Ore vs Mithril Ore)."""
    img = icon(seed).astype(int)
    m = (img != 235).any(axis=2)
    img[m] = np.clip(img[m][:, [2, 0, 1]], 0, 255)
    return img.astype(np.uint8)


def test_items_named_from_item_database(tmp_path):
    from grindcap.digits import StackDigits
    from grindcap.inventory import Grid, read_page

    db = fake_itemdb(tmp_path / "db", {4000001: ("Snail Shell", 1), 4000002: ("Blue Snail Shell", 2),
                                       4000003: ("Mushroom Spore", 3), 4000010: ("Pig's Ribbon", 4)})
    # a look-alike of item 1 with different colours, under its own id
    rgb = recolor(1)
    alpha = np.where((rgb != 235).any(axis=2), 255, 0).astype(np.uint8)
    cv2.imwrite(str(tmp_path / "db" / "icons" / "4000020.png"), np.dstack([rgb, alpha])[2:30, 2:30])
    db.items[4000020] = {"name": "Iron Ore", "category": "Etc", "price": 20}
    db._icons = None

    items = [(1, 13), (2, 5), (3, 40), (1, 7), (4, 2), (99, 3)] + [None] * 18
    img = inventory_screen(items)
    x, y = X0 + 2 * (SLOT + GAP), Y0 + 1 * (SLOT + GAP)       # 7th slot (row 2, col 3): the look-alike
    cell = recolor(1)
    draw_number(cell, 9)
    img[y:y + SLOT, x:x + SLOT] = cell
    c = cfg()
    cat = Catalog(tmp_path / "data")
    rows = read_page(img, Grid.from_cfg(c["inventory"]), cat, StackDigits(), itemdb=db)
    got = [(cat.name(s[0]), s[1]) for row in rows for s in row if s[0]]
    assert got[:5] == [("Snail Shell", 13), ("Blue Snail Shell", 5), ("Mushroom Spore", 40),
                       ("Snail Shell", 7), ("Pig's Ribbon", 2)]
    assert got[5][1] == 3 and got[5][0].startswith("item-")        # not in the database: stays unnamed
    assert got[6] == ("Iron Ore", 9)                               # look-alike told apart by colour
    assert cat.price(cat.by_db(4000001)) == 1                      # NPC price filled in
    assert cat.items[cat.by_db(4000001)]["price"] is None          # ...without becoming "your" price


@pytest.mark.skipif(not HAS_TESS, reason="Tesseract not installed")
@pytest.mark.parametrize("name", ["game_frame.png", "use_tab_tooltip.png"])
def test_map_name_from_minimap(name):
    from pathlib import Path

    from grindcap.mapname import read_map

    frame = cv2.imread(str(Path(__file__).parent / "fixtures" / name))
    m = read_map(frame, [{"streetName": "Victoria Road", "name": "The Rain-Forest East of Henesys"},
                         {"streetName": "Victoria Road", "name": "The Rain-Forest East of Henesys 2"}])
    assert (m["street"], m["name"], m["matched"]) == ("Victoria Road", "The Rain-Forest East of Henesys", True)
    assert read_map(np.zeros_like(frame)) is None      # no minimap on screen


@pytest.mark.skipif(not HAS_TESS, reason="Tesseract not installed")
@pytest.mark.parametrize("name,level,exp", [("game_frame.png", 26, 53791), ("use_tab_tooltip.png", 27, 10)])
def test_level_and_exp_from_real_status_bar(name, level, exp):
    from pathlib import Path

    from grindcap.snapshot import read_status

    c = cfg()
    c.data["readers"]["level"] = {"box": [455, 1040, 50, 30], "mode": "text"}
    c.data["readers"]["exp"] = {"box": [1050, 1035, 60, 18], "mode": "text"}
    c.data["readers"]["mesos"] = {}
    frame = cv2.imread(str(Path(__file__).parent / "fixtures" / name))
    st = read_status(c, frame)
    assert (st["level"], st["exp"], st["exp_checked"]) == (level, exp, True)
    # boxes drawn badly (or not at all): both are found on the status bar anyway
    c.data["readers"]["level"] = {"box": [600, 1000, 40, 20]}
    c.data["readers"]["exp"] = {"box": [1300, 1000, 40, 20]}
    st = read_status(c, frame)
    assert (st["level"], st["exp"], st["exp_checked"]) == (level, exp, True)


def test_exp_text_split_and_level_check():
    from grindcap.statusbar import resolve

    # "[" read as "1": 53,791 [97.98%] at level 26
    assert (lambda r: (r["exp"], r["pct"], r["level"]))(resolve("53.791197.98%]", 26)) == (53791, 97.98, 26)
    # the level read as 30, but 10 EXP showing 0.02% only fits levels 25-27: closest to 30 is 27
    r = resolve("1010.02%1", 30)
    assert (r["exp"], r["level"], r["level_fixed"]) == (10, 27, True)


def test_merge_keeps_repeated_stacks_of_one_item():
    """Several stacks of the same arrows: a later page can look like an earlier one by item alone."""
    A, B = "xbow", "bow"
    p1 = [[(A, 1000), (B, 1000), (A, 1000)], [(A, 1000), (B, 500), (None, 0)]]
    p2 = [[(A, 337), (B, 1000), (A, 1000)], [(A, 250), (B, 500), (None, 0)]]     # next rows, other counts
    merged = merge_pages([p1, p2])
    assert len(merged) == 4
    total = sum(s[1] for row in merged for s in row if s[0] == A)
    assert total == 1000 + 1000 + 1000 + 337 + 1000 + 250


@pytest.mark.skipif(not HAS_TESS, reason="Tesseract not installed")
def test_level_tiles_found_without_a_good_box():
    from pathlib import Path

    from grindcap.statusbar import read_level

    frame = cv2.imread(str(Path(__file__).parent / "fixtures" / "use_tab_tooltip.png"))
    assert read_level(frame, [700, 1040, 50, 30]) == 27      # box somewhere else on the bar
    assert read_level(frame, None) == 27


def test_wrong_level_corrected_from_previous_level():
    from grindcap.statusbar import resolve

    # read as 50, last snapshot was level 26: only 26-31 are possible, and 10 EXP at 0.02% fits 26-27
    r = resolve("1010.02%1", 50, prior=26)
    assert r["exp"] == 10 and r["level"] in (26, 27) and r["level_options"] == [26, 27]
    # read as 27 and it fits: no doubt
    assert resolve("1010.02%1", 27, prior=26)["level_options"] == []


def test_snapflow_finishes_itself_after_every_tab_and_times_the_grind(tmp_path, monkeypatch):
    from grindcap.app import SnapFlow
    from grindcap import inventory

    c = cfg()
    c.data["inventory"]["skip_tabs"] = ["Equip", "Setup", "Cash", "Deco"]
    c.data["inventory"]["auto_finish_after"] = 3
    tabs = iter(["Use", "Etc"])
    monkeypatch.setattr(inventory, "detect_tab", lambda frame, grid: next(tabs))
    flow = SnapFlow(c, lambda: inventory_screen([(1, 5)] + [None] * 23))
    flow.start("start")
    flow.add_page()
    assert flow.finish_in() is None                      # Etc not seen yet
    flow.add_page()
    t = flow.last_page_at
    assert flow.finish_in(t + 1) == pytest.approx(2) and flow.finish_in(t + 5) == 0
    assert flow.grind_time() == t                        # the session starts at the last page


def test_tab_comes_from_the_items_on_the_page(tmp_path):
    from grindcap.inventory import tab_from_items

    db = fake_itemdb(tmp_path / "db", {4000001: ("Snail Shell", 1), 4000002: ("Blue Snail Shell", 2),
                                       2000000: ("Red Potion", 3)})
    db.items[2000000]["category"] = "Use"
    cat = Catalog(tmp_path / "data")
    for iid, dbid in (("item-001", 4000001), ("item-002", 4000002), ("item-003", 2000000)):
        cat.items[iid] = {"name": "x", "db": {"id": dbid}}
    etc_page = [[("item-001", 3), ("item-002", 1), (None, 0)], [("item-001", 9), ("?", 0), (None, 0)]]
    assert tab_from_items(etc_page, cat, db) == "Etc"
    mixed = [[("item-001", 3), ("item-003", 1)]]            # 1 vs 1: not sure, use the tab button
    assert tab_from_items(mixed, cat, db) is None


@pytest.mark.skipif(not HAS_TESS, reason="Tesseract not installed")
def test_mesos_from_inventory_field():
    from pathlib import Path

    from grindcap.inventory import Grid
    from grindcap.statusbar import read_mesos_field

    fx = Path(__file__).parent / "fixtures"
    clear = cv2.imread(str(fx / "game_frame.png"))
    for dx, dy in ((0, 0), (3, -2), (-2, 3)):          # grid boxes drawn a little off
        g = Grid([1494 + dx, 139 + dy, 44, 44], [1695 + dx, 377 + dy, 44, 44], cols=5, rows=6)
        assert read_mesos_field(clear, g)[0] == 86676
    covered = cv2.imread(str(fx / "use_tab_tooltip.png"))   # a tooltip over the field: no guess
    g = Grid([1504, 138, 44, 44], [1706, 377, 44, 44], cols=5, rows=6)
    assert read_mesos_field(covered, g)[0] is None


ANT = [[20, 200, 12, 176, 4], [21, 6, 1, 1, 200], [11, 19, 0, 0, 0], [163, 98, 6, 0, 0], [0] * 5, [0] * 5]


@pytest.mark.skipif(not HAS_TESS, reason="Tesseract not installed")
def test_third_real_frame_ant_tunnel():
    """Etc tab in Ant Tunnel IV: meso total 222,540, level 33, 2,595 EXP [1.87%], dark minimap."""
    from pathlib import Path

    from grindcap.digits import StackDigits
    from grindcap.inventory import Grid
    from grindcap.mapname import read_map
    from grindcap.statusbar import read_exp_texts, read_level, read_mesos_field, resolve_many

    frame = cv2.imread(str(Path(__file__).parent / "fixtures" / "etc_ant_tunnel.png"))
    g = Grid([1492, 140, 44, 44], [1694, 379, 44, 44], cols=5, rows=6)
    assert read_mesos_field(frame, g)[0] == 222540
    lv = read_level(frame, None)
    assert (lv, resolve_many(read_exp_texts(frame, None), lv)["exp"]) == (33, 2595)
    maps = [{"streetName": "Dungeon", "name": n} for n in ("Ant Tunnel I", "Ant Tunnel II", "Ant Tunnel III",
                                                            "Ant Tunnel IV", "Deep Ant Tunnel I")]
    m = read_map(frame, maps)
    assert (m["street"], m["name"]) == ("Dungeon", "Ant Tunnel IV")
    boxes = [b for row in g.slot_boxes() for b in row]
    got = [r.value for r in StackDigits().read_slots(frame, boxes, *g.pitch())]
    assert got == [n or None for row in ANT for n in row]


@pytest.mark.skipif(not HAS_TESS, reason="Tesseract not installed")
def test_mesos_field_border_is_not_a_digit():
    """The light panel above the field used to be taken as part of it, so the field's dark top
    border was cropped in and its corner read as a leading "1" (492,177 -> 1492,177; a smaller
    total such as 92,177 would have passed as 192,177). Grid boxes a little off either way."""
    from pathlib import Path

    from grindcap.inventory import Grid
    from grindcap.statusbar import read_mesos_field

    fx = Path(__file__).parent / "fixtures"
    for name, first, last, truth in (("etc_ant_tunnel.png", (1492, 140), (1694, 379), 222540),
                                     ("equip_burnt_land.png", (1486, 137), (1688, 378), 492177)):
        frame = cv2.imread(str(fx / name))
        for dx, dy in ((0, -6), (3, -3), (0, 0), (-3, 3), (6, -6)):
            g = Grid([first[0] + dx, first[1] + dy, 44, 44], [last[0] + dx, last[1] + dy, 44, 44], cols=5, rows=6)
            assert read_mesos_field(frame, g)[0] == truth, (name, dx, dy)


EXCAVATION = [[20, 3, 23, 150, 200], [200, 100, 1, 3, 6], [200, 16, 40, 200, 200],
              [163, 200, 25, 200, 200], [3, 100, 200, 200, 200], [200, 200, 9, 158, 56]]


@pytest.mark.skipif(not HAS_TESS, reason="Tesseract not installed")
def test_fourth_real_frame_excavation_site():
    """Etc tab in Excavation Site III, level 38, 78 EXP [0.03%], 690,917 mesos. Used to misread:
    163 as 168 (an icon showing through the 3 made it fit 8 as well), the level as 7 (orange cliff
    left of the status bar taken for a level tile) and the map as Excavation Site I ("ill")."""
    from pathlib import Path

    from grindcap.digits import StackDigits
    from grindcap.inventory import Grid, detect_tab
    from grindcap.mapname import read_map
    from grindcap.statusbar import read_exp_texts, read_level, read_mesos_field, resolve_many

    frame = cv2.imread(str(Path(__file__).parent / "fixtures" / "etc_excavation.png"))
    for dx, dy in ((0, 0), (3, -2), (-2, 3)):
        g = Grid([1487 + dx, 139 + dy, 44, 44], [1689 + dx, 378 + dy, 44, 44], cols=5, rows=6)
        boxes = [b for row in g.slot_boxes() for b in row]
        got = [r.value for r in StackDigits().read_slots(frame, boxes, *g.pitch())]
        assert got == [n for row in EXCAVATION for n in row], (dx, dy)
        assert read_mesos_field(frame, g)[0] == 690917
        assert detect_tab(frame, g) == "Etc"
    lv = read_level(frame, None)
    assert (lv, resolve_many(read_exp_texts(frame, None), lv)["exp"]) == (38, 78)
    maps = [{"streetName": "Victoria Road", "name": f"Excavation Site {n}"} for n in ("I", "II", "III", "IV")]
    m = read_map(frame, maps)
    assert (m["street"], m["name"]) == ("Victoria Road", "Excavation Site III")


def test_paused_time_is_left_out_of_rates(tmp_path):
    from grindcap.sessions import active_seconds, is_paused, list_sessions, load_pauses, set_paused
    from grindcap.snapshot import key_figures, load_snapshot, save_snapshot

    root = tmp_path / "snaps"
    s = {"time": 1000.0, "exp": 100, "level": 20, "level_read": True, "mesos": 0, "items": {}}
    e = {"time": 1000.0 + 3600, "exp": 1900, "level": 20, "level_read": True, "mesos": 6000, "items": {}}
    sf = save_snapshot(s, root / "start-1")
    save_snapshot(e, root / "end-1")
    set_paused(sf, True, 1600)
    assert is_paused(load_pauses(sf))
    set_paused(sf, True, 1700)                       # already paused: no second pause
    set_paused(sf, False, 2800)                      # 20 min paused
    assert load_pauses(sf) == [[1600, 2800]]
    assert active_seconds(1000, 4600, load_pauses(sf)) == 2400
    assert active_seconds(1000, 2000, [[1600, None]]) == 600       # a running pause counts until now
    r = compare(load_snapshot(sf), load_snapshot(root / "end-1"), Catalog(str(tmp_path / "data")))
    assert r["minutes"] == 40 and r["paused_minutes"] == 20
    assert r["exp_per_hr"] == 2700 and r["mesos_per_hr"] == 9000
    assert "20 min paused" in key_figures(r)[3]
    assert list_sessions(root)[0]["minutes"] == 40


def test_live_exp_per_hour_so_far(tmp_path, monkeypatch):
    from grindcap import app
    from grindcap.app import SnapFlow
    from grindcap.sessions import set_paused
    from grindcap.snapshot import live_exp, save_snapshot

    start = {"time": 0.0, "exp": 20000, "level": 20, "level_read": True, "pauses": [[600, 1200]]}
    r = live_exp(start, {"exp": 500, "level": 21, "exp_checked": True}, 1800)
    assert r["exp"] == 716 and r["minutes"] == 20 and r["exp_per_hr"] == 2148
    assert live_exp(start, {"exp": 500, "level": 21, "exp_checked": False}, 1800) is None   # unconfirmed read

    sf = save_snapshot({"time": 1000.0, "exp": 100, "level": 20, "level_read": True, "items": {}},
                       tmp_path / "start-1")
    set_paused(sf, True, 1100)
    set_paused(sf, False, 1200)
    monkeypatch.setattr(app, "read_status", lambda cfg, frame, prior=None: {"exp": 400, "level": prior,
                                                                             "exp_checked": True})
    monkeypatch.setattr(app.time, "time", lambda: 1000.0 + 700)
    flow = SnapFlow(cfg(), lambda: np.zeros((50, 50, 3), np.uint8))
    r = flow.live(sf)
    assert r["exp"] == 300 and r["exp_per_hr"] == 1800            # 300 EXP in 10 active minutes
    assert '"exp_per_hr": 1800' in (sf / "live.jsonl").read_text()
