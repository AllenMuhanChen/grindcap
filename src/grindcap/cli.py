"""grindcap command line.

  grindcap calibrate              drag boxes around HP, MP, EXP and mesos on a screenshot
  grindcap snapshot               save a screenshot, the box overlay and each crop (for checking)
  grindcap watch                  print live readings so you can check calibration
  grindcap run                    track a live session (Ctrl+C to stop) and print a summary
  grindcap replay VIDEO           run the tracker on a screen recording
  grindcap summarize SESSION      summarise a saved session log
  grindcap export SESSION         print the values to paste into Grind Ledger
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .capture import ScreenSource, VideoSource
from .config import Config
from .session import (Tracker, default_session_path, format_summary, ledger_export, load_events,
                      read_values, summarize)

QUIET = {"hp_regen", "mp_regen"}


def _screen(cfg) -> ScreenSource:
    c = cfg["capture"]
    return ScreenSource(c["monitor"], c["region"], c["fps"])


def _print_event(e):
    if e.kind in QUIET:
        return
    extra = " ".join(f"{k}={v}" for k, v in e.data.items())
    print(f"{e.t:8.2f}s  {e.kind:<10} {extra}")


def cmd_calibrate(cfg, a):
    from .calibrate import calibrate, load_frame

    frame = load_frame(a.image, a.video, a.at, _screen(cfg))
    calibrate(cfg, frame, a.only)
    print(f"Saved {cfg.save(a.config)}")


def cmd_snapshot(cfg, a):
    from .calibrate import load_frame, save_snapshot
    from .readers import build_readers

    frame = load_frame(a.image, a.video, a.at, _screen(cfg))
    readings = read_values(build_readers(cfg), frame)
    folder = save_snapshot(cfg, frame, readings)
    print(f"Readings: {readings}\nSaved images to {folder}/")


def cmd_watch(cfg, a):
    from .readers import build_readers

    readers = build_readers(cfg)
    print("Live readings (Ctrl+C to stop)")
    try:
        for t, frame in _screen(cfg).frames():
            vals = read_values(readers, frame)
            print(f"\r{t:7.1f}s  " + "  ".join(f"{k}={v}" for k, v in vals.items()) + " " * 10, end="")
    except KeyboardInterrupt:
        print()


def _track(cfg, source, out, max_seconds=None):
    tr = Tracker(cfg, source, out, on_event=_print_event)
    print(f"Tracking {cfg['session']['monster']}. Logging to {out}. Press Ctrl+C to stop.")
    events = tr.run(max_seconds)
    print("\n" + format_summary(summarize(events)))
    return events


def cmd_run(cfg, a):
    _track(cfg, _screen(cfg), Path(a.out) if a.out else default_session_path(cfg), a.seconds)


def cmd_replay(cfg, a):
    src = VideoSource(a.video, cfg["capture"]["fps"], cfg["capture"]["region"] if a.crop else None)
    _track(cfg, src, Path(a.out) if a.out else default_session_path(cfg), a.seconds)


def cmd_summarize(cfg, a):
    header, events = load_events(a.session)
    s = summarize(events)
    print(json.dumps(s, indent=2) if a.json else format_summary(s))


def cmd_export(cfg, a):
    header, events = load_events(a.session)
    print(json.dumps(ledger_export(header, summarize(events)), indent=2))


def main(argv=None):
    p = argparse.ArgumentParser(prog="grindcap", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default="config.yaml", help="config file (default: config.yaml)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def frame_args(sp):
        sp.add_argument("--image", help="use a screenshot file instead of the live screen")
        sp.add_argument("--video", help="use a frame from a screen recording")
        sp.add_argument("--at", type=float, default=0.0, help="seconds into --video")

    sp = sub.add_parser("calibrate", help="set the HP/MP/EXP/meso boxes")
    frame_args(sp)
    sp.add_argument("--only", nargs="+", choices=["hp", "mp", "exp", "mesos"], help="calibrate just these")
    sp.set_defaults(fn=cmd_calibrate)

    sp = sub.add_parser("snapshot", help="save screenshot, overlay and crops")
    frame_args(sp)
    sp.set_defaults(fn=cmd_snapshot)

    sub.add_parser("watch", help="print live readings").set_defaults(fn=cmd_watch)

    for name, fn in (("run", cmd_run), ("replay", cmd_replay)):
        sp = sub.add_parser(name, help="track a live session" if name == "run" else "track a recording")
        if name == "replay":
            sp.add_argument("video")
            sp.add_argument("--crop", action="store_true", help="apply capture.region to the video frames")
        sp.add_argument("--out", help="session log path (default: sessions/<time>_<monster>.jsonl)")
        sp.add_argument("--seconds", type=float, help="stop after this many seconds")
        sp.set_defaults(fn=fn)

    for name, fn in (("summarize", cmd_summarize), ("export", cmd_export)):
        sp = sub.add_parser(name)
        sp.add_argument("session")
        if name == "summarize":
            sp.add_argument("--json", action="store_true")
        sp.set_defaults(fn=fn)

    a = p.parse_args(argv)
    cfg = Config.load(a.config)
    a.fn(cfg, a)


if __name__ == "__main__":
    sys.exit(main())
