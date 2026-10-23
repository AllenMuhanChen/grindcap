"""Before/after snapshot mode on synthetic inventory screens."""
import shutil

import cv2
import numpy as np
import pytest

from grindcap.config import Config, DEFAULT_CONFIG, _merge
from grindcap.inventory import Catalog, merge_pages
from grindcap.snapshot import build_snapshot, compare, exp_gained

HAS_TESS = shutil.which("tesseract") is not None
SLOT, GAP, X0, Y0, COLS, ROWS = 40, 4, 20, 60, 4, 6


def icon(seed: int) -> np.ndarray:
    """A distinct, deterministic 40x40 'item icon'."""
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
                    cv2.putText(cell, str(qty), (1, SLOT - 3), cv2.FONT_HERSHEY_PLAIN, 1.0, (0, 0, 0), 1)
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
    inv["first_slot"] = [X0, Y0, SLOT, SLOT]
    inv["last_slot"] = [X0 + 3 * (SLOT + GAP), Y0 + 5 * (SLOT + GAP), SLOT, SLOT]
    return c


def slot_with(seed, qty):
    cell = icon(seed)
    cv2.putText(cell, str(qty), (1, SLOT - 3), cv2.FONT_HERSHEY_PLAIN, 1.0, (0, 0, 0), 1)
    return cell


def teach_digits(path, c):
    from grindcap.digits import DigitReader
    from grindcap.inventory import QtyReader

    dr = DigitReader(path)
    q = QtyReader(c["inventory"]["qty_box"], digits=dr) if False else None
    box = c["inventory"]["qty_box"]
    for i, n in enumerate(["10", "23", "45", "67", "89", "31"]):
        cell = slot_with(100 + i, int(n))
        h, w = cell.shape[:2]
        reg = cell[int(box[1] * h): int((box[1] + box[3]) * h), int(box[0] * w): int((box[0] + box[2]) * w)]
        assert dr.teach(reg, n)
    dr.save()
    return dr


def test_digit_templates_read_new_numbers(tmp_path):
    from grindcap.digits import DigitReader

    c = cfg()
    teach_digits(tmp_path / "d.npz", c)
    dr = DigitReader(tmp_path / "d.npz")
    box = c["inventory"]["qty_box"]
    for seed, n in [(1, 13), (3, 40), (4, 7), (6, 25), (11, 60), (13, 9), (10, 2), (7, 3), (9, 15), (2, 98)]:
        cell = slot_with(seed, n)
        h, w = cell.shape[:2]
        assert dr.read(cell[int(box[1] * h):, :int(box[2] * w)]) == n


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
    teach_digits(tmp_path / "data" / "digits.npz", c)

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
    teach_digits(tmp_path / "data" / "digits.npz", c)
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
    teach_digits(tmp_path / "data" / "digits.npz", c)
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
