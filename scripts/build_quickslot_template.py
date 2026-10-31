"""Rebuild grindcap/data/quickslot_panel.png from real screenshots (developer tool).

    python scripts/build_quickslot_template.py

Cuts the quick slot panel (2 rows x 4 keys) out of tests/fixtures/game_frame.png (1920x1080) and keeps,
as the alpha channel, only the pixels that are the panel itself: outside the slot boxes (frame and the
dark gaps between slots), and the same in every screenshot below (so passing scenery is left out).
"""
from pathlib import Path

import cv2
import numpy as np

from grindcap import quickslot as Q

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
FRAMES = ["game_frame.png", "use_tab_tooltip.png", "etc_ant_tunnel.png", "equip_burnt_land.png"]
X, Y, W, H = Q.PANEL      # where the panel is in game_frame.png


def main():
    crops = [cv2.imread(str(FIX / f))[Y:Y + H, X:X + W].astype(int) for f in FRAMES]
    base = crops[0]
    same = np.all([np.abs(c - base).max(axis=2) < 30 for c in crops[1:]], axis=0)
    outside = np.ones((H, W), bool)
    for sx, sy in Q.slot_offsets(1.0):
        outside[int(sy) - 1:int(sy) + Q.SLOT + 1, int(sx) - 1:int(sx) + Q.SLOT + 1] = False
    alpha = ((same & outside) * 255).astype(np.uint8)
    out = np.dstack([base.astype(np.uint8), alpha])
    cv2.imwrite(str(Q.TEMPLATE), out)
    print(f"{Q.TEMPLATE}: {int(alpha.astype(bool).sum())} of {W * H} pixels kept")


if __name__ == "__main__":
    main()
