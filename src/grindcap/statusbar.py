"""Level and EXP from the status bar, cross-checked against each other.

Level: the game draws each level digit white on its own orange tile ("LV. [2][7]"). The tiles are found
by colour inside the calibrated level box (with a margin, so a rough box is fine), only the white
pixels are kept, and Tesseract reads that clean black-on-white picture at a few sizes (majority vote).

EXP: the line reads "53,791 [97.98%]". OCR often turns "[" into "1" ("53.791197.98%"), so the number
and the percentage can't be split by text alone. Every split is tried, and the one that fits the
EXP table is kept: EXP / EXP-to-next-level must round to the shown percentage. That also checks the
level: a level that doesn't fit the EXP shown is replaced by the nearest level that does.
"""
from __future__ import annotations

import re
from collections import Counter

import numpy as np

from .gamedata import EXP_TO_NEXT


def _ocr(img, config: str, tesseract_cmd=None) -> str:
    from .readers import setup_tesseract

    return setup_tesseract(tesseract_cmd).image_to_string(img, config=config).strip()


def level_tiles(region: np.ndarray) -> list[tuple[int, int]]:
    """Column spans of the orange level tiles in a BGR region."""
    r = region.astype(np.int16)
    b, g, rr = r[..., 0], r[..., 1], r[..., 2]
    orange = (rr > 200) & (g > 80) & (g < 190) & (b < 90)
    cols = orange.sum(axis=0) > 3            # a column over the white digit still has orange above/below
    spans, start = [], None
    for x, on in enumerate(list(cols) + [False]):
        if on and start is None:
            start = x
        elif not on and start is not None:
            if x - start >= 6:
                spans.append((start, x))
            start = None
    return spans


def _read_tiles(reg, tesseract_cmd=None) -> int | None:
    import cv2

    spans = level_tiles(reg)
    if not spans:
        return None
    # keep the tiles that sit together (the level), drop stray orange further away
    group = [spans[0]]
    for s in spans[1:]:
        if s[0] - group[-1][1] <= 6:
            group.append(s)
        else:
            break
    widths = [b - a for a, b in group]
    if len(group) > 3 or max(widths) > 3 * min(widths) or max(widths) > 40:
        return None                          # not level tiles
    a, b = group[0][0], group[-1][1]
    sub = reg[:, a:b]
    r = sub.astype(np.int16)
    orange_rows = np.flatnonzero(((r[..., 2] > 200) & (r[..., 0] < 90)).sum(axis=1) > 3)
    if orange_rows.size:
        sub = sub[orange_rows[0]:orange_rows[-1] + 1]
    white = (sub.min(axis=2) > 150).astype(np.uint8) * 255
    votes = Counter()
    for sc in (3, 4, 6):
        u = cv2.resize(white, None, fx=sc, fy=sc, interpolation=cv2.INTER_CUBIC)
        img = cv2.copyMakeBorder(255 - u, 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=255)
        t = re.sub(r"\D", "", _ocr(img, "--psm 8 -c tessedit_char_whitelist=0123456789", tesseract_cmd))
        if t and len(t) == len(group):          # one digit per tile
            votes[int(t)] += 1
            if votes[int(t)] >= 2:
                break                           # two sizes agree: enough
    v = votes.most_common(1)[0][0] if votes else None
    return v if v is not None and 1 <= v <= 200 else None


def read_level(frame, box=None, tesseract_cmd=None, margin: int = 25) -> int | None:
    """Level from the orange tiles: inside the calibrated box (with a margin), else anywhere in the
    left part of the status bar at the bottom of the window."""
    if box:
        x, y, w, h = box
        reg = frame[max(0, y - margin):y + h + margin, max(0, x - margin):x + w + margin]
        v = _read_tiles(reg, tesseract_cmd)
        if v is not None:
            return v
    H, W = frame.shape[:2]
    return _read_tiles(frame[int(H * 0.93):, :int(W * 0.4)], tesseract_cmd)


EXP_LABEL = __import__("pathlib").Path(__file__).parent / "data" / "exp_label.png"


def exp_text_box(frame) -> list[int] | None:
    """Where "53,791 [97.98%]" is: just right of the "EXP." label on the status bar, found by template
    matching (cut from a real 1920x1080 screenshot, scaled by window height). None if not found."""
    import cv2

    t = cv2.imread(str(EXP_LABEL))
    H, W = frame.shape[:2]
    s = H / 1080
    if abs(s - 1) > 0.02:
        t = cv2.resize(t, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    y0 = int(H * 0.9)
    strip = frame[y0:]
    if strip.shape[0] < t.shape[0] or strip.shape[1] < t.shape[1]:
        return None
    r = cv2.matchTemplate(strip, t, cv2.TM_CCOEFF_NORMED)
    _, score, _, (x, y) = cv2.minMaxLoc(r)
    if score < 0.8:
        return None
    th, tw = t.shape[:2]
    return [x + tw + int(2 * s), y0 + y - int(2 * s), int(140 * s), th + int(4 * s)]


def read_exp_texts(frame, box, tesseract_cmd=None, good=None) -> list[str]:
    """OCR of the EXP number and the "[xx.xx%]" after it, at a few sizes. Uses the place right of the
    "EXP." label when that's found, else the calibrated box widened to the right."""
    import cv2

    auto = exp_text_box(frame)
    if auto is not None:
        x, y, w, h = auto
        crop = frame[max(0, y):y + h, max(0, x):x + w]
    elif box:
        x, y, w, h = box
        crop = frame[max(0, y):y + h, max(0, x):x + w + 8 * h]
    else:
        return []
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    out = []
    base = max(3, round(60 / max(1, g.shape[0])))
    for f in (base, base + 1, base - 1, base + 2):
        u = cv2.resize(g, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
        _, th = cv2.threshold(u, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if th.mean() < 127:
            th = 255 - th
        th = cv2.copyMakeBorder(th, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
        out.append(_ocr(th, "--psm 7 -c tessedit_char_whitelist=0123456789,.[]%", tesseract_cmd))
        if good is not None and good(out[-1]):
            break                               # this reading fits the EXP table: done
    return out


def _fits(exp: int, pct: float, level: int) -> bool:
    need = EXP_TO_NEXT.get(level)
    if not need or exp >= need:
        return False
    return abs(exp / need * 100 - pct) <= 0.0051   # the game rounds to 2 decimals (53791/54900 -> 97.98)


def exp_splits(text: str) -> list[tuple[int, float]]:
    """Every (exp, percent) the OCR text could mean."""
    t = text.replace(" ", "")
    out = []
    for m in re.finditer(r"(\d{1,3})\.(\d{2})%", t):
        for k in range(1, m.end(1) - m.start(1) + 1):          # pct may start inside the digit run
            ps = t[m.end(1) - k:m.end(1)] + "." + m.group(2)
            pct = float(ps)
            if pct > 100:
                continue
            head = t[:m.end(1) - k]
            for drop in (1, 0):                                # the "[" read as a digit, or lost
                h = head[:-drop] if drop else head
                digits = re.sub(r"\D", "", h)
                if digits:
                    out.append((int(digits), pct))
    return list(dict.fromkeys(out))


def resolve_many(texts: list[str], level_read: int | None, prior: int | None = None, up: int = 5) -> dict:
    """resolve() over several OCR attempts: the answer most attempts agree on, among those that fit."""
    rs = [resolve(t, level_read, prior, up) for t in texts]
    ok = [r for r in rs if r["checked"]]
    if not ok:
        return rs[0] if rs else {"exp": None, "pct": None, "level": level_read, "checked": False}
    c = Counter((r["exp"], r["level"]) for r in ok)
    top = c.most_common(1)[0][0]
    r = next(r for r in ok if (r["exp"], r["level"]) == top)
    return {**r, "texts": texts}


def resolve(text: str, level_read: int | None, prior: int | None = None, up: int = 5) -> dict:
    """Best (exp, pct, level) for this EXP text and level reading.

    `prior` is a level you were at before (the latest snapshot, or the configured level). Levels never
    go down, so only prior..prior+up are considered when it's known.
    Within those, the level read from the tiles wins if the EXP fits it; otherwise the fitting level
    closest to it (or to the prior). Returns what it used and whether the EXP fitted.
    """
    splits = exp_splits(text)
    if level_read is not None:            # the tiles' reading, if the EXP fits it, settles it
        fit = [(e, p) for e, p in splits if _fits(e, p, level_read)]
        if fit:
            e, p = max(fit)
            return {"exp": e, "pct": p, "level": level_read, "checked": True, "level_ocr": level_read,
                    "level_fixed": False, "level_options": []}
    levels = list(EXP_TO_NEXT)
    if prior:
        levels = [lv for lv in levels if prior <= lv <= prior + up]
    target = level_read if level_read in levels else (prior or level_read)
    best = None
    for exp, pct in splits:
        for lv in levels:
            if not _fits(exp, pct, lv):
                continue
            key = (abs(lv - target) if target else 0, 0 if level_read == lv else 1, -exp)
            if best is None or key < best[0]:
                best = (key, exp, pct, lv)
    if best is None:
        exp = splits[0][0] if splits else None
        lv = level_read if (not prior or level_read in levels) else prior
        return {"exp": exp, "pct": splits[0][1] if splits else None, "level": lv, "checked": False,
                "level_ocr": level_read}
    _, exp, pct, lv = best
    options = [x for x in levels if _fits(exp, pct, x)]
    return {"exp": exp, "pct": pct, "level": lv, "checked": True, "level_ocr": level_read,
            "level_fixed": level_read is not None and lv != level_read,
            # several levels fit this EXP and the tiles didn't settle it: worth a look in the review
            "level_options": options if len(options) > 1 and level_read not in options else []}


MESO_TEXT = re.compile(r"^\d{1,3}([.,]\d{3})*$")   # 86,676 (the comma often reads as a period)


def read_mesos_field(frame, grid, tesseract_cmd=None) -> tuple[int | None, str]:
    """The meso total in the inventory window: a white field below the item grid, found from the
    grid's position (so it moves with the window). Dark digits on white, read at a few sizes; a
    reading counts only if it looks like a meso total (groups of 3 digits) and two sizes agree.
    Returns (None, why) when the field isn't plain white, e.g. a tooltip is over it."""
    import cv2

    px, py = grid.pitch()
    x0, ly = grid.first[0], grid.last[1]
    xa, ya = int(x0 + 0.1 * px), int(ly + 1.0 * py)
    xb, yb = int(x0 + 4.6 * px), int(ly + 2.0 * py)
    reg = frame[max(0, ya):max(0, yb), max(0, xa):max(0, xb)]
    if reg.size == 0:
        return None, "field outside the picture"
    g = cv2.cvtColor(reg, cv2.COLOR_BGR2GRAY)
    white = g > 235
    rows = np.flatnonzero(white.mean(axis=1) > 0.5)
    cols = np.flatnonzero(white[rows].mean(axis=0) > 0.5) if rows.size else rows
    if rows.size < 0.15 * py or cols.size < 0.8 * px:
        return None, "meso field not visible (covered?)"
    fld = g[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]
    votes, texts = Counter(), []
    for k in (4, 3, 5):
        u = cv2.resize(fld, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
        _, th = cv2.threshold(u, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        th = cv2.copyMakeBorder(th, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
        t = _ocr(th, "--psm 7 -c tessedit_char_whitelist=0123456789,.", tesseract_cmd).replace(" ", "")
        texts.append(t)
        if MESO_TEXT.match(t):
            v = int(re.sub(r"\D", "", t))
            votes[v] += 1
            if votes[v] >= 2:
                return v, " | ".join(texts)
    return None, " | ".join(texts)
