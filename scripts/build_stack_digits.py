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
FIX = ROOT / "tests" / "fixtures"
# (screenshot, grid, stack numbers by row; 0 = no number or not used)
FRAMES = [
    (FIX / "game_frame.png", Grid([1492, 137, 46, 46], [1694, 376, 46, 46], cols=5, rows=6),
     [[1, 1, 1, 59, 68], [0, 0, 1, 0, 1], [0, 52, 52, 14, 0],
      [160, 81, 13, 0, 1], [105, 0, 0, 0, 0], [66, 0, 52, 0, 97]]),
    # Use tab; r5c3 has the mouse cursor on it and row 6 is under a tooltip, so they're left out
    (FIX / "use_tab_tooltip.png", Grid([1504, 138, 44, 44], [1706, 377, 44, 44], cols=5, rows=6),
     [[1000, 8, 1000, 30, 18], [46, 14, 90, 2, 1000], [1, 15, 4, 2, 20],
      [1, 337, 8, 86, 1000], [68, 16, 0, 1, 2], [0, 0, 0, 0, 0]]),
]
FRAME, GRID, LABELS = FRAMES[0]   # kept for tests and older scripts


def main():
    # The first frame fixes the digit offset relative to its grid boxes; later frames are located
    # with the templates learned from the first (their boxes were drawn differently).
    frame, grid, lab = FRAMES[0]
    boxes = [b for row in grid.slot_boxes() for b in row]
    labels = [str(n) if n else "" for row in lab for n in row]
    px, py = grid.pitch()
    best = None
    for oy in range(D.DIGIT_TOP - 3, D.DIGIT_TOP + 4):
        for ox in range(-3, 4):
            sd = D.StackDigits(builtin=Path("/nonexistent"))
            sd.offset = (ox, oy)
            sd.locate = lambda view, origins, o=(ox, oy): o   # fixed offset while building
            sd.teach(cv2.imread(str(frame)), boxes, labels, px, py)
            # The right offset puts each whole 11-px digit in the window: most digit pixels inside it
            # (a shifted window loses a row of outline), and examples of one digit agreeing best.
            meds = {d: np.median(np.stack(v), 0) for d, v in sd.taught.items()}
            inside = sum(int(D.glyph_mask(m).sum()) for m in meds.values())
            spread = np.mean([np.abs(np.stack(v) - meds[d])[:, D.glyph_mask(meds[d])].mean()
                              for d, v in sd.taught.items() if len(v) > 1])
            key = (-inside, spread)
            if best is None or key < best[0]:
                best = (key, (ox, oy), sd)
    (neg_inside, spread), off, sd = best
    del sd.locate
    for frame, grid, lab in FRAMES[1:]:
        b = [x for row in grid.slot_boxes() for x in row]
        sd.teach(cv2.imread(str(frame)), b, [str(n) if n else "" for row in lab for n in row], *grid.pitch())
    sd.builtin, sd.taught = sd.taught, {}
    sd.offset = off
    sd.save(D.BUILTIN, which="builtin")
    print(f"offset {off}, digit pixels {-neg_inside}, spread {spread:.1f}, examples:", {d: len(v) for d, v in sorted(sd.builtin.items())})


if __name__ == "__main__":
    main()
