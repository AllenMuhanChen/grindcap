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

    @property
    def collecting(self) -> bool:
        return self.which is not None

    def start(self, which: str) -> dict:
        """Grab EXP/level/mesos now. Returns what was read so it can be shown for checking."""
        from .anchors import shifted

        self.which = which
        self.pages = []
        self.status_frame = self.grab()
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
        self.pages.append(frame if frame is not None else self.grab())
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

    def finish(self) -> dict:
        if not self.collecting:
            raise RuntimeError("No snapshot in progress.")
        cat = Catalog(self.cfg["inventory"]["catalog_dir"])
        snap = build_snapshot(self.cfg, self.status_frame, {"Inventory": self.pages}, cat)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        folder = save_snapshot(snap, Path(self.cfg["inventory"]["snapshot_dir"]) / f"{self.which}-{stamp}",
                               self.status_frame, {"Inventory": self.pages})
        which, self.which, self.watcher = self.which, None, None
        return {"which": which, "folder": str(folder), "pages": len(self.pages), "level": snap["level"],
                "exp": snap["exp"], "mesos": snap["mesos"], "kinds": len(snap["items"]),
                "count": sum(snap["items"].values()), "map": (snap.get("map") or {}).get("name")}

    def cancel(self):
        self.which, self.watcher, self.pages = None, None, []

    def compare(self, minutes: float | None = None) -> tuple[str, Path]:
        root = Path(self.cfg["inventory"]["snapshot_dir"])
        start, end = latest_snapshot(root, "start"), latest_snapshot(root, "end")
        if not start or not end:
            raise RuntimeError("Take a start snapshot and an end snapshot first.")
        cat = Catalog(self.cfg["inventory"]["catalog_dir"])
        r = compare(load_snapshot(start), load_snapshot(end), cat, minutes)
        report = html_report(r, cat, Path(end) / "report.html")
        return format_compare(r), report
