"""Find the game window on Windows, so only the game is captured (wherever it is, on any monitor).

Uses the Win32 API through ctypes, no extra dependency. On other systems every function returns None.
"""
from __future__ import annotations

import sys


def _user32():
    if sys.platform != "win32":
        return None
    import ctypes

    try:  # report real pixels on high-DPI screens, so window rects match the screenshot
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    return ctypes.windll.user32


def list_windows() -> list[tuple[str, dict, int]]:
    """Visible top-level windows: (title, client-area rect in screen pixels, handle)."""
    u = _user32()
    if u is None:
        return []
    import ctypes
    from ctypes import wintypes

    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not u.IsWindowVisible(hwnd):
            return True
        n = u.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, buf, n + 1)
        rect = client_rect(hwnd)
        if rect and (u.IsIconic(hwnd) or (rect["width"] > 100 and rect["height"] > 100)):
            out.append((buf.value, rect, hwnd))
        return True

    u.EnumWindows(cb, 0)
    return out


def client_rect(hwnd) -> dict | None:
    """The window's drawable area (no title bar or borders) in screen coordinates."""
    u = _user32()
    if u is None:
        return None
    import ctypes
    from ctypes import wintypes

    r = wintypes.RECT()
    if not u.GetClientRect(hwnd, ctypes.byref(r)):
        return None
    pt = wintypes.POINT(0, 0)
    u.ClientToScreen(hwnd, ctypes.byref(pt))
    return {"left": pt.x, "top": pt.y, "width": r.right - r.left, "height": r.bottom - r.top}


def is_minimized(hwnd) -> bool:
    u = _user32()
    return bool(u and u.IsIconic(hwnd))


BROWSERS_ETC = ("google chrome", "mozilla firefox", "microsoft edge", "opera", "brave", "discord",
                "visual studio code", "notepad", "file explorer", "grindcap", "obs ")


def find_game_window(title: str):
    """(handle, exact title, client rect) of the game window.

    A window titled exactly `title` wins. Otherwise the largest window whose title contains it,
    skipping browsers and other apps that often have the game's name in a tab or file title.
    """
    t = title.lower().strip()
    wins = [(hwnd, name, rect) for name, rect, hwnd in list_windows()]
    exact = [w for w in wins if w[1].lower().strip() == t]
    if exact:
        return max(exact, key=lambda h: h[2]["width"] * h[2]["height"])
    hits = [w for w in wins if t in w[1].lower() and not any(b in w[1].lower() for b in BROWSERS_ETC)]
    if not hits:
        return None
    return max(hits, key=lambda h: h[2]["width"] * h[2]["height"])


def find_game(title: str) -> dict | None:
    """Client rect of the game window, or None."""
    hit = find_game_window(title)
    return hit[2] if hit else None
