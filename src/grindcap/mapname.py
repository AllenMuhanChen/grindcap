"""Read the current map's name from the minimap window.

The minimap ("MINI MAP" title bar) shows two lines next to the map icon: the street name ("Victoria
Road") and the map name ("The Rain-Forest East of Henesys"). The title bar is found by template
matching (data/minimap_header.png, cut from a real 1920x1080 screenshot), the two lines are read with
Tesseract, then snapped to the closest real Classic World map name from maplestory.io when one is
close enough, which fixes small OCR slips.

read_map(frame) -> {"street": ..., "name": ..., "raw": [line1, line2], "matched": bool} or None.
"""
from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

import numpy as np

HEADER = Path(__file__).parent / "data" / "minimap_header.png"
# Offsets from the title bar's top-left (screen px at 1920x1080; scaled for other window heights).
TEXT_X, LINE1, LINE2 = 64, (30, 50), (50, 72)
MIN_SCORE = 0.8


def _scale_for(frame) -> float:
    return frame.shape[0] / 1080


def find_header(frame) -> tuple[int, int, float] | None:
    """(x, y, scale) of the minimap title bar, or None if the minimap isn't on screen."""
    import cv2

    t = cv2.imread(str(HEADER))
    s = _scale_for(frame)
    if abs(s - 1) > 0.02:
        t = cv2.resize(t, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    region = frame[: max(t.shape[0] + 1, frame.shape[0] * 3 // 4)]
    r = cv2.matchTemplate(region, t, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(r)
    return (loc[0], loc[1], s) if score >= MIN_SCORE else None


def _right_edge(frame, x0: int, y: int, max_w: int) -> int:
    """Where the minimap's plain title band ends (its width depends on the map)."""
    row = frame[y, x0:x0 + max_w].astype(int)
    bg = row[:4].mean(axis=0)
    off = np.abs(row - bg).max(axis=1) > 40
    for i in range(len(off) - 2):
        if off[i] and off[i + 1] and off[i + 2]:
            return x0 + i
    return x0 + len(off)


def _clean(txt: str) -> str:
    return re.sub(r"[|/\\_]+\s*$", "", txt.strip()).strip()


def _ocr(img, tesseract_cmd=None) -> str:
    import cv2

    from .readers import setup_tesseract

    tess = setup_tesseract(tesseract_cmd)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    return _clean(tess.image_to_string(255 - g, config="--psm 7"))   # white text on blue: invert


def _ocr_variants(img, tesseract_cmd=None) -> list[str]:
    """A few readings of one line: the plain one, and the white letters only (the minimap's own
    picture can show through behind the text and confuse the plain reading)."""
    import cv2

    from .readers import setup_tesseract

    tess = setup_tesseract(tesseract_cmd)
    out = [_ocr(img, tesseract_cmd)]
    for thr, k in ((200, 3), (200, 4), (170, 4)):
        w = (img.min(axis=2) > thr).astype(np.uint8) * 255
        u = cv2.resize(w, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
        out.append(_clean(tess.image_to_string(
            cv2.copyMakeBorder(255 - u, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255), config="--psm 7")))
    return [t for t in dict.fromkeys(out) if t]


def load_maps(folder: str | Path) -> list[dict]:
    p = Path(folder) / "maps.json"
    return json.loads(p.read_text()) if p.exists() else []


def download_maps(folder: str | Path, region="MCW", version="1") -> list[dict]:
    from .itemdb import API, _get

    maps = json.loads(_get(f"{API}/{region}/{version}/map"))
    Path(folder).mkdir(parents=True, exist_ok=True)
    (Path(folder) / "maps.json").write_text(json.dumps(maps))
    return maps


def _numerals(name: str) -> str:
    """A last word made only of I-like strokes is a Roman numeral the OCR spelt with l, i, 1 or |:
    "Excavation Site ill" -> "Excavation Site III" (else it snaps to the shorter "Excavation Site I")."""
    words = name.split()
    if len(words) > 1 and re.fullmatch(r"[iIl1|!]+", words[-1]):
        words[-1] = "I" * len(words[-1])
    elif len(words) > 1 and re.fullmatch(r"[iIl1|!]*[vVxX][iIl1|!]*", words[-1]):
        words[-1] = re.sub(r"[iIl1|!]", "I", words[-1]).upper()
    return " ".join(words)


def snap_name(street: str, name: str, maps: list[dict], cutoff: float = 0.75):
    """Closest real (street, name) to what was read, or None."""
    r = snap_score(street, name, maps, cutoff)
    return r[1] if r else None


def snap_score(street: str, name: str, maps: list[dict], cutoff: float = 0.75):
    """(similarity, (street, name)) of the closest real map, or None."""
    if not maps:
        return None
    name = _numerals(name)
    key = f"{street} | {name}".lower()
    best, br = None, 0.0
    for m in maps:
        k = f"{m.get('streetName') or ''} | {m.get('name') or ''}".lower()
        r = difflib.SequenceMatcher(None, key, k).ratio()
        if r > br:
            best, br = m, r
    if best is None or br < cutoff:
        # the street line may be cut off or misread: try the map name alone
        names = [(m.get("name") or "").lower() for m in maps]
        hit = difflib.get_close_matches(name.lower(), names, n=1, cutoff=cutoff)
        if not hit:
            return None
        best = maps[names.index(hit[0])]
        br = difflib.SequenceMatcher(None, name.lower(), hit[0]).ratio()
    return br, (best.get("streetName") or "", best.get("name") or "")


def read_map(frame, maps: list[dict] | None = None, tesseract_cmd=None) -> dict | None:
    h = find_header(frame)
    if h is None:
        return None
    x, y, s = h
    x0 = x + int(TEXT_X * s)
    right = _right_edge(frame, x0, y + int(27 * s), int(700 * s))
    variants = []
    for a, b in (LINE1, LINE2):
        crop = frame[y + int(a * s): y + int(b * s), x0:right]
        variants.append(_ocr_variants(crop, tesseract_cmd) if crop.size else [""])
    # the reading pair that's closest to a real map name wins
    best = None
    for st in variants[0] or [""]:
        for nm in variants[1] or [""]:
            r = snap_score(st, nm, maps or [])
            if r and (best is None or r[0] > best[0][0]):
                best = (r, st, nm)
    street, name = (best[1], best[2]) if best else ((variants[0] or [""])[0], (variants[1] or [""])[0])
    lines = [street, name]
    if not (street or name):
        return None
    snapped = best[0][1] if best else None
    out = {"street": street, "name": name, "raw": lines, "matched": snapped is not None}
    if snapped:
        out["street"], out["name"] = snapped
    return out


def label(m: dict | None) -> str:
    return m["name"] if m and m.get("name") else ""
