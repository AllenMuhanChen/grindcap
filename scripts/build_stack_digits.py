"""Rebuild grindcap/data/stack_digits.npz from a labelled real screenshot (developer tool).

    python scripts/build_stack_digits.py

Uses tests/fixtures/game_frame.png (Etc tab open, 5x6 grid) and the stack numbers typed in below.
Tries digit-origin offsets around the nominal one and keeps the one where examples of the same digit
agree best, then saves every example as the built-in templates.
"""
from pathlib import Path

import cv2
import numpy as np

from grindcap import digits as D
from grindcap.inventory import Grid

ROOT = Path(__file__).resolve().parents[1]
FRAME = ROOT / "tests" / "fixtures" / "game_frame.png"
GRID = Grid([1492, 137, 46, 46], [1694, 376, 46, 46], cols=5, rows=6)
LABELS = [[1, 1, 1, 59, 68], [0, 0, 1, 0, 1], [0, 52, 52, 14, 0],
          [160, 81, 13, 0, 1], [105, 0, 0, 0, 0], [66, 0, 52, 0, 97]]


def main():
    frame = cv2.imread(str(FRAME))
    boxes = [b for row in GRID.slot_boxes() for b in row]
    labels = [str(n) if n else "" for row in LABELS for n in row]
    px, py = GRID.pitch()
    best = None
    for oy in range(D.DIGIT_TOP - 3, D.DIGIT_TOP + 4):
        for ox in range(-3, 4):
            sd = D.StackDigits(builtin=Path("/nonexistent"))
            sd.offset = (ox, oy)
            sd.locate = lambda view, origins, o=(ox, oy): o   # fixed offset while building
            sd.teach(frame, boxes, labels, px, py)
            # spread of examples around their median, over the digit pixels
            spread = np.mean([np.abs(np.stack(v) - np.median(np.stack(v), 0))[:, D.glyph_mask(np.median(np.stack(v), 0))].mean()
                              for v in sd.taught.values() if len(v) > 1])
            if best is None or spread < best[0]:
                best = (spread, (ox, oy), sd)
    spread, off, sd = best
    sd.builtin, sd.taught = sd.taught, {}
    sd.offset = off
    sd.save(D.BUILTIN, which="builtin")
    print(f"offset {off}, spread {spread:.1f}, examples:", {d: len(v) for d, v in sorted(sd.builtin.items())})


if __name__ == "__main__":
    main()
