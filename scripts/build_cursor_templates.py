"""Mouse-pointer templates for rejecting inventory pages with the pointer over the items.

The game draws its own pointer (a white glove). Two poses are cut:
  point: pointing finger, the usual pointer (tests/fixtures/cursor_page.png, a page picture the
         browser version saved: screen pixels of a 1920x1080 window, JPEG-compressed once)
  open:  open hand, shown over an item (tests/fixtures/use_tab_tooltip.png)
Mask = glove-coloured pixels (light, cyan-tinted white) + the dark outline next to them.
Writes web/data/cursors.json: {scale, cursors: [{name, w, h, grey: [...], mask: [...]}]}.
"""
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCALE = 1920 / 1366   # screen px per game px in both sources


def glove(img):
    b, g, r = [img[..., i].astype(int) for i in range(3)]
    return (g > r + 8) & (b > r + 8) & (np.abs(g - b) < 24) & (r > 140)


def dark(img):
    return img.astype(int).max(2) < 70


def cut(path, y, x, h, w, drop):
    img = cv2.imread(str(ROOT / path))[y:y + h, x:x + w].copy()
    g = glove(img)
    for (ya, yb, xa, xb) in drop:          # bits of the item or slot gap under the pointer
        g[ya:yb, xa:xb] = False
    g = cv2.morphologyEx(g.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)).astype(bool)
    ring = cv2.dilate(g.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool) & ~g & dark(img)
    mask = g | ring
    grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return {"w": w, "h": h, "grey": grey.flatten().tolist(), "mask": mask.astype(int).flatten().tolist()}


def main():
    point = cut("tests/fixtures/cursor_page.png", 225, 118, 40, 34, [(28, 40, 0, 34), (0, 15, 24, 34)])
    opened = cut("tests/fixtures/use_tab_tooltip.png", 347, 1620, 40, 32, [(0, 4, 0, 32), (0, 12, 0, 10)])
    out = {"scale": SCALE, "cursors": [dict(name="point", **point), dict(name="open", **opened)]}
    (ROOT / "web/data/cursors.json").write_text(json.dumps(out))
    print("wrote web/data/cursors.json", [(c["name"], sum(c["mask"])) for c in out["cursors"]])


if __name__ == "__main__":
    main()
