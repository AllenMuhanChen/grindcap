"""Find UI windows wherever they are on screen.

During calibration you box a part of a window that never changes (the inventory's title bar, a fixed
label on the status bar). That patch is saved as an anchor. Later, the anchor is searched for in each
screenshot; the difference between where it is now and where it was at calibration is applied to every
box that belongs to that window. So you can move the inventory (or the whole game window) freely.

Anchors and the boxes that follow them:
  inventory -> inventory.first_slot, inventory.last_slot, readers.mesos
  status    -> readers.exp, readers.level, readers.hp, readers.mp
"""
from __future__ import annotations

import copy
from pathlib import Path

import numpy as np

FOLLOWERS = {
    "inventory": [("inventory", "first_slot"), ("inventory", "last_slot"), ("readers", "mesos")],
    "status": [("readers", "exp"), ("readers", "level"), ("readers", "hp"), ("readers", "mp")],
}


def anchor_path(cfg, name: str) -> Path:
    return Path(cfg["inventory"]["catalog_dir"]) / "anchors" / f"{name}.png"


def save_anchor(cfg, name: str, frame: np.ndarray, box) -> None:
    import cv2

    x, y, w, h = box
    p = anchor_path(cfg, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(p), frame[y:y + h, x:x + w])
    cfg["anchors"][name] = {"box": [int(x), int(y), int(w), int(h)]}


def locate(cfg, name: str, frame: np.ndarray, min_score: float | None = None):
    """(dx, dy) shift of an anchor from its calibrated position, or None if it isn't configured.

    Raises LookupError if the anchor is configured but can't be found (e.g. the window is closed).
    """
    import cv2

    a = (cfg["anchors"] or {}).get(name)
    p = anchor_path(cfg, name)
    if not a or not a.get("box") or not p.exists():
        return None
    tmpl = cv2.imread(str(p))
    if tmpl.shape[0] > frame.shape[0] or tmpl.shape[1] > frame.shape[1]:
        raise LookupError(f"The {name} anchor is bigger than the screenshot.")
    res = cv2.matchTemplate(frame, tmpl, cv2.TM_CCOEFF_NORMED)
    _, score, _, (x, y) = cv2.minMaxLoc(res)
    need = min_score if min_score is not None else cfg["anchors"].get("min_score", 0.8)
    if score < need:
        raise LookupError(f"Couldn't find the {name} window on screen (best match {score:.2f}). Is it open?")
    return x - a["box"][0], y - a["box"][1]


def shifted(cfg, frame: np.ndarray, names=("inventory", "status")):
    """A copy of the config with every box moved to where its window is in this frame."""
    out = copy.deepcopy(cfg)
    for name in names:
        d = locate(cfg, name, frame)
        if not d:
            continue
        dx, dy = d
        for section, key in FOLLOWERS[name]:
            target = out.data[section]
            if section == "readers":
                rc = target.get(key) or {}
                if rc.get("box"):
                    x, y, w, h = rc["box"]
                    rc["box"] = [x + dx, y + dy, w, h]
            elif target.get(key):
                x, y, w, h = target[key]
                target[key] = [x + dx, y + dy, w, h]
    return out
