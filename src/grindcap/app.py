"""The snapshot workflow, independent of any window toolkit (the GUI is a thin layer on top).

  flow = SnapFlow(cfg, grab)
  flow.start("start")        # grabs EXP/mesos right away
  flow.add_page(frame)       # inventory pages, by hand or from PageWatcher
  info = flow.finish()       # reads everything and saves the snapshot
  text, report = flow.compare()
"""
from __future__ import annotations

import time
from pathlib import Path

from .inventory import Catalog, PageWatcher
from .snapshot import (build_snapshot, compare, format_compare, html_report, latest_snapshot,
                       load_snapshot, read_status, save_snapshot)


class SnapFlow:
    def __init__(self, cfg, grab):
        self.cfg = cfg
        self.grab = grab
        self.which: str | None = None
        self.status_frame = None
        self.pages: list = []
        self.status: dict = {}
        self.watcher: PageWatcher | None = None
        self.pressed_at: float | None = None      # when Start/End snapshot was pressed
        self.tabs_seen: set[str] = set()
        self.last_page_at: float | None = None

    @property
    def needed_tabs(self) -> list[str]:
        """Tabs that must be captured before the snapshot can finish by itself."""
        from .inventory import TABS

        skip = set(self.cfg["inventory"].get("skip_tabs") or [])
        return [t for t in TABS if t not in skip]

    def finish_in(self, now: float | None = None) -> float | None:
        """Seconds until the snapshot finishes by itself: once every needed tab has a page and no new
        page came for inventory.auto_finish_after seconds (so you can still scroll a long tab).
        None while tabs are missing or auto-finish is off."""
        wait = self.cfg["inventory"].get("auto_finish_after", 4)
        if not self.collecting or not wait or self.last_page_at is None:
            return None
        if any(t not in self.tabs_seen for t in self.needed_tabs):
            return None
        return max(0.0, wait - ((now or time.time()) - self.last_page_at))

    def _catalog(self):
        if getattr(self, "_cat", None) is None:
            self._cat = Catalog(self.cfg["inventory"]["catalog_dir"])
        return self._cat

    def _itemdb(self):
        if getattr(self, "_db", None) is None:
            from .snapshot import open_itemdb

            self._db = open_itemdb(self.cfg, download=False) or False
        return self._db or None

    def grind_time(self) -> float:
        if self.which == "start":
            return self.last_page_at or time.time()
        return self.pressed_at or time.time()

    @property
    def collecting(self) -> bool:
        return self.which is not None

    def start(self, which: str) -> dict:
        """Grab EXP/level/mesos now. Returns what was read so it can be shown for checking."""
        from .anchors import shifted

        frame = self.grab()          # first: if the capture fails, nothing has changed
        self.which, self.pages, self.status_frame = which, [], frame
        self.pressed_at = time.time()
        self.tabs_seen, self.last_page_at = set(), None
        self._cat = None                 # re-read: the last snapshot may have added items
        try:
            fc = shifted(self.cfg, self.status_frame)
        except LookupError:
            fc = self.cfg
        self.status = read_status(fc, self.status_frame)
        from .snapshot import read_map_safe

        self.status["map"] = read_map_safe(self.cfg, self.status_frame)
        self.watcher = PageWatcher(self.cfg)
        return self.status

    def add_page(self, frame=None) -> int:
        from .anchors import shifted
        from .inventory import Grid, detect_tab, quick_tab

        frame = frame if frame is not None else self.grab()
        self.pages.append(frame)
        self.last_page_at = time.time()
        try:
            fc = shifted(self.cfg, frame, ("inventory",))
            grid = Grid.from_cfg(fc["inventory"])
            # the items on the page say which tab it is; the tab buttons (which flash when a tab
            # has new items) are only the fallback
            tab = quick_tab(frame, grid, self._catalog(), self._itemdb(), fc["inventory"]["match_threshold"],
                            fc["inventory"]["empty_std"]) or detect_tab(frame, grid)
        except Exception:
            tab = None
        if tab:
            self.tabs_seen.add(tab)
        return len(self.pages)

    def poll(self) -> bool:
        """Grab a frame and keep it as a page if the inventory just settled on a new view."""
        if not self.collecting or self.watcher is None:
            return False
        frame = self.grab()
        if self.watcher.feed(frame):
            self.add_page(frame)
            return True
        return False

    def finish(self, progress=None) -> dict:
        """Read and save the snapshot. Its time is when the grind starts or ends: for a start
        snapshot, when the last page was captured (reading the pages afterwards doesn't count); for
        an end snapshot, when End was pressed (paging through the inventory isn't grinding)."""
        if not self.collecting:
            raise RuntimeError("No snapshot in progress.")
        when = self.grind_time()
        cat = Catalog(self.cfg["inventory"]["catalog_dir"])
        snap = build_snapshot(self.cfg, self.status_frame, {"Inventory": self.pages}, cat, when=when,
                              status=self.status, progress=progress)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        folder = save_snapshot(snap, Path(self.cfg["inventory"]["snapshot_dir"]) / f"{self.which}-{stamp}",
                               self.status_frame, {"Inventory": self.pages})
        which, self.which, self.watcher = self.which, None, None
        return {"which": which, "folder": str(folder), "pages": len(self.pages), "level": snap["level"],
                "exp": snap["exp"], "mesos": snap["mesos"], "kinds": len(snap["items"]),
                "count": sum(snap["items"].values()), "map": (snap.get("map") or {}).get("name")}

    def live(self, start_folder) -> dict | None:
        """Read EXP/level off the status bar now and work out EXP/hr since the start snapshot (paused
        time left out). Each reading is appended to <start>/live.jsonl. None if the EXP wasn't read."""
        import json

        from .anchors import shifted
        from .snapshot import apply_fixes, live_exp

        start = load_snapshot(start_folder)
        frame = self.grab()
        now = time.time()
        try:
            fc = shifted(self.cfg, frame)
        except LookupError:
            fc = self.cfg
        lv = apply_fixes(start).get("level")
        reading = read_status(fc, frame, prior=int(lv) if lv else None)
        r = live_exp(start, reading, now)
        with open(Path(start_folder) / "live.jsonl", "a") as fh:
            fh.write(json.dumps({"time": now, "exp": reading.get("exp"), "level": reading.get("level"),
                                 "checked": bool(reading.get("exp_checked")),
                                 "exp_per_hr": r["exp_per_hr"] if r else None}) + "\n")
        return r

    def cancel(self):
        self.which, self.watcher, self.pages = None, None, []

    def compare(self, minutes: float | None = None) -> tuple[str, Path]:
        root = Path(self.cfg["inventory"]["snapshot_dir"])
        start, end = latest_snapshot(root, "start"), latest_snapshot(root, "end")
        if not start or not end:
            raise RuntimeError("Take a start snapshot and an end snapshot first.")
        cat = Catalog(self.cfg["inventory"]["catalog_dir"])
        r = compare(load_snapshot(start), load_snapshot(end), cat, minutes)
        self.last_result = r
        report = html_report(r, cat, Path(end) / "report.html")
        return format_compare(r), report
