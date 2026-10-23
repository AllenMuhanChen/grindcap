"""Capture the game window directly, even when other windows cover it (Windows only).

Three methods, tried in order until one gives a real picture:

  wgc          Windows Graphics Capture (what OBS "Window Capture" uses). Works when the game is
               covered by other windows. Needs `pip install windows-capture`. The game must not be
               minimized: a minimized game doesn't draw anything.
  printwindow  Win32 PrintWindow. Also works when covered, but some DirectX games give a black image,
               which is detected and skipped.
  screen       Plain screenshot of where the window is. Only works when the game is visible on top.

`GameWindow.grab()` returns a BGR image of the window and remembers which method worked.
"""
from __future__ import annotations

import sys
import threading
import time

import numpy as np

from . import winfind


class CaptureError(RuntimeError):
    pass


def _looks_blank(img: np.ndarray | None) -> bool:
    return img is None or img.size == 0 or float(img.std()) < 2.0


class _WGC:
    """A running Windows Graphics Capture session that keeps the latest frame."""

    def __init__(self, title: str):
        from windows_capture import WindowsCapture  # pip install windows-capture

        self._lock = threading.Lock()
        self._frame = None
        self._closed = False
        cap = WindowsCapture(cursor_capture=False, draw_border=False, window_name=title)

        @cap.event
        def on_frame_arrived(frame, capture_control):
            buf = frame.frame_buffer  # BGRA numpy array
            with self._lock:
                self._frame = np.ascontiguousarray(buf[:, :, :3])

        @cap.event
        def on_closed():
            self._closed = True

        self._control = cap.start_free_threaded()

    def latest(self, timeout: float = 2.0) -> np.ndarray | None:
        end = time.time() + timeout
        while time.time() < end:
            with self._lock:
                if self._frame is not None:
                    return self._frame.copy()
            if self._closed:
                return None
            time.sleep(0.02)
        return None

    def stop(self):
        try:
            self._control.stop()
        except Exception:
            pass


def _printwindow(hwnd) -> np.ndarray | None:
    import ctypes
    from ctypes import wintypes

    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    r = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        return None
    hdc = user32.GetDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    PW_CLIENTONLY, PW_RENDERFULLCONTENT = 1, 2
    ok = user32.PrintWindow(hwnd, mem, PW_CLIENTONLY | PW_RENDERFULLCONTENT)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

    bi = BITMAPINFOHEADER()
    bi.biSize, bi.biWidth, bi.biHeight = ctypes.sizeof(BITMAPINFOHEADER), w, -h  # top-down
    bi.biPlanes, bi.biBitCount = 1, 32
    buf = (ctypes.c_char * (w * h * 4))()
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hdc)
    if not ok:
        return None
    img = np.frombuffer(buf, np.uint8).reshape(h, w, 4)
    return img[:, :, :3].copy()


def _screen(rect) -> np.ndarray:
    import mss

    with mss.mss() as sct:
        return np.asarray(sct.grab(rect))[:, :, :3].copy()


class GameWindow:
    """The game window, found by (part of) its title."""

    def __init__(self, title: str, methods=("wgc", "printwindow", "screen")):
        self.title = title
        self.methods = list(methods)
        self.method: str | None = None   # the method that worked last
        self.window_title: str | None = None
        self._wgc: _WGC | None = None
        self._wgc_failed = False

    def find(self):
        hit = winfind.find_game_window(self.title)
        if not hit:
            raise CaptureError(f"Couldn't find a window with '{self.title}' in its title. Is the game open "
                               "(and not minimized)? Run `grindcap windows` to see window titles.")
        return hit  # (hwnd, exact title, client rect)

    def grab(self) -> np.ndarray:
        if sys.platform != "win32":
            raise CaptureError("Game-window capture only works on Windows.")
        hwnd, exact, rect = self.find()
        self.window_title = self.window_title if self._wgc else exact
        if winfind.is_minimized(hwnd):
            raise CaptureError("The game is minimized, so it isn't drawing anything. Restore it "
                               "(it can stay behind other windows).")
        errors = []
        for m in self.methods:
            try:
                if m == "wgc" and not self._wgc_failed:
                    if self._wgc is None or self.window_title != exact:
                        if self._wgc:
                            self._wgc.stop()
                        self._wgc, self.window_title = _WGC(exact), exact
                    img = self._wgc.latest()
                    if _looks_blank(img):
                        raise CaptureError("no frame")
                elif m == "printwindow":
                    img = _printwindow(hwnd)
                    if _looks_blank(img):
                        raise CaptureError("black image")
                elif m == "screen":
                    img = _screen(rect)
                else:
                    continue
                self.method = m
                return img
            except ImportError:
                self._wgc_failed = True
                errors.append(f"{m}: windows-capture not installed")
            except Exception as e:  # try the next method
                if m == "wgc":
                    self._wgc_failed = True
                errors.append(f"{m}: {e}")
        raise CaptureError("Couldn't capture the game window: " + "; ".join(errors))

    def close(self):
        if self._wgc:
            self._wgc.stop()
            self._wgc = None
