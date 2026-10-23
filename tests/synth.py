"""Synthetic game screens for tests: a fake status bar with HP/MP bars, EXP text and a meso count.

It is not what MapleStory looks like; it exercises the same code paths (bar fill, OCR, events).
"""
from __future__ import annotations

import cv2
import numpy as np

W, H = 640, 360
HP_BOX = [20, 320, 200, 12]
MP_BOX = [240, 320, 200, 12]
EXP_BOX = [460, 312, 160, 28]
MESO_BOX = [460, 20, 160, 28]
HP_RGB = [220, 40, 40]
MP_RGB = [40, 90, 220]
MAX_HP, MAX_MP = 1000, 400


def config_dict(text_mode=True):
    return {
        "capture": {"monitor": 1, "region": None, "fps": 8},
        "character": {"level": 20, "skills": {"Power Strike": 4, "Final Attack": 8},
                      "max_hp": MAX_HP, "max_mp": MAX_MP},
        "readers": {
            "hp": {"mode": "bar", "box": HP_BOX, "fill_rgb": HP_RGB, "tol": 45},
            "mp": {"mode": "bar", "box": MP_BOX, "fill_rgb": MP_RGB, "tol": 45},
            "exp": {"mode": "text", "box": EXP_BOX} if text_mode else {"mode": "text", "box": None},
            "mesos": {"mode": "text", "box": MESO_BOX} if text_mode else {"mode": "text", "box": None},
        },
        "session": {"monster": "Green Mushroom", "monster_exp": 26, "out_dir": "sessions"},
    }


def draw(hp, mp, exp, mesos, overlay_text=True) -> np.ndarray:
    img = np.full((H, W, 3), (60, 50, 45), np.uint8)
    for (x, y, w, h), val, mx, rgb in ((HP_BOX, hp, MAX_HP, HP_RGB), (MP_BOX, mp, MAX_MP, MP_RGB)):
        cv2.rectangle(img, (x, y), (x + w - 1, y + h - 1), (30, 30, 30), -1)
        fw = int(round(w * val / mx))
        if fw > 0:
            cv2.rectangle(img, (x, y), (x + fw - 1, y + h - 1), tuple(int(c) for c in rgb[::-1]), -1)
        if overlay_text:  # game-style white text over the bar centre
            cv2.putText(img, f"{val}/{mx}", (x + w // 2 - 30, y + h - 2), cv2.FONT_HERSHEY_PLAIN, 0.8,
                        (255, 255, 255), 1)
    for (x, y, w, h), text in ((EXP_BOX, f"{exp}"), (MESO_BOX, f"{mesos:,}")):
        cv2.rectangle(img, (x, y), (x + w, y + h), (255, 255, 255), -1)
        cv2.putText(img, text, (x + 6, y + h - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
    return img


def scripted_session(n_kills=6, fps=8):
    """Yields (t, frame) and the ground truth for a simple fight loop.

    Each kill: 2 s walking, Power Strike, a touch for 45 HP, Power Strike, kill (+26 EXP, +40 mesos).
    Every 3rd kill a Final Attack heals 30 HP. One HP potion (+150) halfway.
    """
    hp, mp, exp, mesos = 900, 380, 1000, 5000
    t = 0.0
    timeline = []  # (time, hp, mp, exp, mesos)

    def hold(seconds):
        nonlocal t
        timeline.append((t, hp, mp, exp, mesos))
        t += seconds

    truth = {"kills": 0, "touches": 0, "casts": 0, "mesos": 0, "exp": 0}
    for k in range(n_kills):
        hold(2.0)                      # walking to the next monster
        mp -= 4; truth["casts"] += 1; hold(0.9)
        hp -= 45; truth["touches"] += 1; hold(0.9)
        mp -= 4; truth["casts"] += 1; hold(0.9)
        if k % 3 == 2:
            mp -= 8; truth["casts"] += 1; hold(0.4)
            hp += 30; hold(0.9)
        exp += 26; mesos += 40; truth["kills"] += 1; truth["exp"] += 26; truth["mesos"] += 40
        hold(0.5)
        if k == n_kills // 2:
            hp += 150; hold(0.9)
    hold(2.0)

    frames = []
    step = 1.0 / fps
    i = 0
    for j, (t0, *state) in enumerate(timeline):
        t1 = timeline[j + 1][0] if j + 1 < len(timeline) else t0 + 1.0
        while i * step < t1:
            frames.append((i * step, draw(*state)))
            i += 1
    return frames, truth
