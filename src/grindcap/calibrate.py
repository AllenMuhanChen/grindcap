"""Interactive calibration: drag a box around each UI element, and sample bar colours."""
from __future__ import annotations

from pathlib import Path

import numpy as np

# What to box, depending on whether the reader measures a bar or reads a number.
PROMPTS = {
    ("hp", "bar"): "HP: box the red HP bar",
    ("hp", "text"): "HP: box just the HP numbers next to the bar, e.g. 312/450",
    ("mp", "bar"): "MP: box the blue MP bar",
    ("mp", "text"): "MP: box just the MP numbers next to the bar, e.g. 120/200",
    ("exp", "text"): "EXP: box just your EXP number, e.g. 1234/20216",
    ("exp", "bar"): "EXP: box the EXP bar",
    ("mesos", "text"): "Mesos: box just the meso number in your inventory, e.g. 45,210",
    ("level", "text"): "Level: box just your level number, e.g. 32",
}


def sample_fill(frame: np.ndarray, box) -> list[int]:
    """Median colour of the left fifth of the bar's middle row. Calibrate with the bar fairly full."""
    x, y, w, h = box
    row = frame[y + h // 2, x: x + max(1, w // 5)]
    b, g, r = np.median(row, axis=0)
    return [int(r), int(g), int(b)]


def load_frame(image: str | None = None, video: str | None = None, at: float = 0.0, screen=None):
    import cv2

    if image:
        f = cv2.imread(image)
        if f is None:
            raise FileNotFoundError(image)
        return f
    if video:
        cap = cv2.VideoCapture(video)
        cap.set(cv2.CAP_PROP_POS_MSEC, at * 1000)
        ok, f = cap.read()
        cap.release()
        if not ok:
            raise RuntimeError(f"Could not read a frame at {at}s from {video}")
        return f
    return screen.grab_one()


def _screen_size() -> tuple[int, int]:
    try:
        import mss

        with mss.mss() as sct:
            m = sct.monitors[1]
            return m["width"], m["height"]
    except Exception:
        return 1920, 1080


def _select_scaled(title: str, frame: np.ndarray, fit: float, max_up: float = 1.0):
    import cv2

    sw, sh = _screen_size()
    h, w = frame.shape[:2]
    scale = min(max_up, fit * sw / w, fit * sh / h)
    shown = frame if scale == 1.0 else cv2.resize(frame, (int(w * scale), int(h * scale)),
                                                   interpolation=cv2.INTER_AREA)
    if scale > 1.0:
        shown = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_NEAREST)
    cv2.namedWindow(title, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
    cv2.resizeWindow(title, shown.shape[1], shown.shape[0])
    cv2.moveWindow(title, 0, 0)
    x, y, bw, bh = cv2.selectROI(title, shown, showCrosshair=False)
    cv2.destroyWindow(title)
    if bw == 0 or bh == 0:
        return 0, 0, 0, 0
    return (round(x / scale), round(y / scale), round(bw / scale), round(bh / scale))


def select_box(title: str, frame: np.ndarray, fit: float = 0.8):
    """Pick a box in two steps, so small UI elements are easy to box precisely.

    Step 1: the whole screenshot, shrunk to fit on screen (clear of the taskbar): drag roughly around
    the area. Step 2: that area zoomed in: drag tightly around the element. Returns full-resolution
    [x, y, w, h]. Press Enter with no box in step 2 to use the step 1 box as is.
    """
    x, y, w, h = _select_scaled(f"{title}  (step 1: drag roughly around it)", frame, fit)
    if w == 0 or h == 0:
        return 0, 0, 0, 0
    pad = 10
    x0, y0 = max(0, x - pad), max(0, y - pad)
    crop = frame[y0: y + h + pad, x0: x + w + pad]
    zx, zy, zw, zh = _select_scaled(f"{title}  (step 2: zoomed, drag tightly)", crop, fit, max_up=6.0)
    if zw == 0 or zh == 0:
        return x, y, w, h
    return x0 + zx, y0 + zy, zw, zh


def calibrate_inventory(cfg, frame: np.ndarray) -> None:
    import cv2

    inv = cfg["inventory"]
    for key, what in (("first_slot", "the TOP-LEFT inventory slot"), ("last_slot", "the BOTTOM-RIGHT visible slot")):
        title = f"Inventory: drag a box tightly around {what}  [Enter = confirm]"
        print(title)
        x, y, w, h = select_box(title, frame)
        if w == 0 or h == 0:
            print("  skipped inventory calibration")
            return
        inv[key] = [int(x), int(y), int(w), int(h)]
    questions = {
        "cols": "How many item squares ACROSS can you see in the inventory?",
        "rows": "How many rows of item squares DOWN can you see without scrolling?",
    }
    for key in ("cols", "rows"):
        while True:
            v = input(f"{questions[key]} Press Enter for {inv[key]}, or type the number: ").strip()
            if not v:
                break
            if v.isdigit() and int(v) > 0:
                inv[key] = int(v)
                break
            print("  Please type a whole number, like 4.")
    print(f"  inventory grid: first {inv['first_slot']}, last {inv['last_slot']}, {inv['cols']}x{inv['rows']}")
    calibrate_anchor(cfg, frame, "inventory",
                     "Landmark: box the inventory window's title at the top of the window")


def calibrate_anchor(cfg, frame: np.ndarray, name: str, prompt: str) -> None:
    from .anchors import save_anchor

    print(prompt)
    x, y, w, h = select_box(prompt + "  [C = skip]", frame)
    if w == 0 or h == 0:
        print(f"  skipped the {name} anchor: that window must then stay where it is now")
        return
    save_anchor(cfg, name, frame, (x, y, w, h))
    print(f"  {name} anchor saved: the tool will now find this window wherever you move it")


def calibrate(cfg, frame: np.ndarray, only: list[str] | None = None, save=None) -> None:
    """Ask for each box in turn. `save` is called after every step, so quitting halfway keeps progress."""
    save = save or (lambda: None)
    names = only or list(cfg["readers"]) + ["inventory"]
    for name in names:
        if name == "inventory":
            calibrate_inventory(cfg, frame)
            save()
            continue
        rc = cfg["readers"][name]
        if name in ("hp", "mp", "exp", "mesos", "level"):
            rc["mode"] = "text"  # read the numbers; bars are only a fallback you can set by hand
            rc.pop("fill_rgb", None)
        title = PROMPTS.get((name, rc.get("mode", "bar")), name) + "  [Enter = confirm, C = skip]"
        print(title)
        x, y, w, h = select_box(title, frame)
        if w == 0 or h == 0:
            print(f"  skipped {name}")
            continue
        rc["box"] = [int(x), int(y), int(w), int(h)]
        if rc.get("mode", "bar") == "bar":
            rc["fill_rgb"] = sample_fill(frame, rc["box"])
            print(f"  {name}: box {rc['box']}, fill colour {rc['fill_rgb']}")
        else:
            print(f"  {name}: box {rc['box']} (text)")
        save()
    if any(n in ("exp", "level", "hp", "mp") for n in names):
        calibrate_anchor(cfg, frame, "status",
                         "Landmark: box the word EXP (or LV) on the bottom bar, without the numbers")
        save()


def overlay(cfg, frame: np.ndarray, readings: dict | None = None) -> np.ndarray:
    """Draw the configured boxes (and current readings) on a copy of the frame."""
    import cv2

    out = frame.copy()
    for name, rc in cfg.configured_readers().items():
        x, y, w, h = rc["box"]
        cv2.rectangle(out, (x, y), (x + w, y + h), (0, 255, 255), 1)
        label = name if not readings or name not in readings else f"{name}: {readings[name]}"
        cv2.putText(out, label, (x, max(10, y - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
    inv = cfg["inventory"]
    if inv.get("first_slot") and inv.get("last_slot"):
        from .inventory import Grid

        for row in Grid.from_cfg(inv).slot_boxes():
            for (x, y, w, h) in row:
                cv2.rectangle(out, (x, y), (x + w, y + h), (255, 0, 255), 1)
    return out


def save_snapshot(cfg, frame, readings, folder="captures") -> Path:
    import time

    import cv2

    p = Path(folder)
    p.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    cv2.imwrite(str(p / f"{stamp}_raw.png"), frame)
    cv2.imwrite(str(p / f"{stamp}_boxes.png"), overlay(cfg, frame, readings))
    for name, rc in cfg.configured_readers().items():
        x, y, w, h = rc["box"]
        cv2.imwrite(str(p / f"{stamp}_{name}.png"), frame[y:y + h, x:x + w])
    return p
