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


def read_level(frame, box, tesseract_cmd=None, margin: int = 25) -> int | None:
    import cv2

    x, y, w, h = box
    x0, y0 = max(0, x - margin), max(0, y - margin)
    reg = frame[y0:y + h + margin, x0:x + w + margin]
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
    return votes.most_common(1)[0][0] if votes else None


def read_exp_texts(frame, box, tesseract_cmd=None) -> list[str]:
    """OCR of the EXP number and the "[xx.xx%]" after it, at a few sizes (the box is widened to the
    right to take in the percentage)."""
    import cv2

    x, y, w, h = box
    crop = frame[max(0, y):y + h, max(0, x):x + w + 8 * h]
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    out = []
    base = max(3, round(60 / max(1, g.shape[0])))
    for f in (base, base + 1, base - 1):
        u = cv2.resize(g, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
        _, th = cv2.threshold(u, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if th.mean() < 127:
            th = 255 - th
        th = cv2.copyMakeBorder(th, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
        out.append(_ocr(th, "--psm 7 -c tessedit_char_whitelist=0123456789,.[]%", tesseract_cmd))
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


def resolve_many(texts: list[str], level_read: int | None, prior: int | None = None) -> dict:
    """resolve() over several OCR attempts: the answer most attempts agree on, among those that fit."""
    rs = [resolve(t, level_read, prior) for t in texts]
    ok = [r for r in rs if r["checked"]]
    if not ok:
        return rs[0] if rs else {"exp": None, "pct": None, "level": level_read, "checked": False}
    c = Counter((r["exp"], r["level"]) for r in ok)
    top = c.most_common(1)[0][0]
    r = next(r for r in ok if (r["exp"], r["level"]) == top)
    return {**r, "texts": texts}


def resolve(text: str, level_read: int | None, prior: int | None = None) -> dict:
    """Best (exp, pct, level) for this EXP text and level reading.

    Preference: the level read from the tiles if the EXP fits it; else the fitting level closest to
    it (or to `prior`, e.g. the start snapshot's level). Returns what it used and whether it agreed.
    """
    splits = exp_splits(text)
    target = level_read or prior
    best = None
    for exp, pct in splits:
        for lv in EXP_TO_NEXT:
            if not _fits(exp, pct, lv):
                continue
            key = (abs(lv - target) if target else 0, 0 if level_read == lv else 1, -exp)
            if best is None or key < best[0]:
                best = (key, exp, pct, lv)
    if best is None:
        exp = splits[0][0] if splits else None
        return {"exp": exp, "pct": splits[0][1] if splits else None, "level": level_read, "checked": False}
    _, exp, pct, lv = best
    return {"exp": exp, "pct": pct, "level": lv, "checked": True, "level_ocr": level_read,
            "level_fixed": level_read is not None and lv != level_read}
