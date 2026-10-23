"""Frame sources. Everything downstream works on (timestamp_seconds, BGR numpy image)."""
from __future__ import annotations

import sys
import time
from typing import Iterator, Protocol

import numpy as np


class FrameSource(Protocol):
    def frames(self) -> Iterator[tuple[float, np.ndarray]]: ...


class ScreenSource:
    """Live screen capture with mss. Yields frames at roughly `fps`."""

    def __init__(self, monitor: int = 1, region: dict | None = None, fps: float = 8,
                 window_title: str | None = None):
        self.monitor = monitor
        self.region = region
        self.fps = fps
        self.window_title = window_title
        self.game = None
        if window_title and sys.platform == "win32":
            from .wincap import GameWindow

            self.game = GameWindow(window_title)

    @property
    def method(self) -> str:
        return (self.game.method if self.game and self.game.method else "screen")

    def grab_one(self) -> np.ndarray:
        import mss

        with mss.mss() as sct:
            return self._grab(sct)

    def _grab(self, sct) -> np.ndarray:
        if self.game is not None:
            return self.game.grab()  # the game window itself, even if covered
        mon = sct.monitors[self.monitor]
        if self.region:
            r = self.region
            area = {"left": mon["left"] + r["left"], "top": mon["top"] + r["top"],
                    "width": r["width"], "height": r["height"]}
        else:
            area = mon
        img = np.asarray(sct.grab(area))  # BGRA
        return img[:, :, :3].copy()

    def frames(self) -> Iterator[tuple[float, np.ndarray]]:
        import mss

        period = 1.0 / self.fps
        t0 = time.perf_counter()
        with mss.mss() as sct:
            nxt = t0
            while True:
                now = time.perf_counter()
                if now < nxt:
                    time.sleep(nxt - now)
                ts = time.perf_counter() - t0
                yield ts, self._grab(sct)
                nxt += period


class VideoSource:
    """Replay a screen recording. Timestamps come from the video, sampled at `fps`."""

    def __init__(self, path: str, fps: float = 8, region: dict | None = None):
        self.path = path
        self.fps = fps
        self.region = region

    def frames(self) -> Iterator[tuple[float, np.ndarray]]:
        import cv2

        cap = cv2.VideoCapture(self.path)
        if not cap.isOpened():
            raise FileNotFoundError(f"Could not open video: {self.path}")
        vfps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        step = max(1, round(vfps / self.fps))
        i = 0
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if i % step == 0:
                    if self.region:
                        r = self.region
                        frame = frame[r["top"]:r["top"] + r["height"], r["left"]:r["left"] + r["width"]]
                    yield i / vfps, frame
                i += 1
        finally:
            cap.release()
