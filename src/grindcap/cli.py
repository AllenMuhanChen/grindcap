"""grindcap command line.

  grindcap calibrate              drag boxes around HP, MP, EXP and mesos on a screenshot
  grindcap snapshot               save a screenshot, the box overlay and each crop (for checking)
  grindcap watch                  print live readings so you can check calibration
  grindcap run                    track a live session (Ctrl+C to stop) and print a summary
  grindcap replay VIDEO           run the tracker on a screen recording
  grindcap summarize SESSION      summarise a saved session log
  grindcap export SESSION         print the values to paste into Grind Ledger

Before/after mode (simpler, no live tracking):
  grindcap snap start             capture EXP and mesos, then page through your inventory (F8/F9/F10)
  grindcap snap end               same, after grinding
  grindcap compare                EXP/hr, mesos/hr and every item gained or used, per hour
  grindcap teach-digits           teach it the stack-number font (once, before the first snapshot)
  grindcap items                  list known item icons and their names/prices
  grindcap label ITEM-ID          give an item id a name and price
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
    print("Progress is saved after every step. Press C to skip a step you've already done.")
    try:
        calibrate(cfg, frame, a.only, save=lambda: cfg.save(a.config))
    except KeyboardInterrupt:
        print("\nStopped. Everything up to the last finished step is saved.")
        return
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


def _catalog(cfg):
    from .inventory import Catalog

    return Catalog(cfg["inventory"]["catalog_dir"])


def cmd_snap(cfg, a):
    from .calibrate import load_frame
    from .snapshot import PageCollector, build_snapshot, save_snapshot

    screen = _screen(cfg)
    if a.image or a.video:
        status = load_frame(a.image, a.video, a.at, screen)
        pages = {"Inventory": [status]}
    else:
        print("Make sure your EXP and meso total are visible. Capturing status in 2 s...")
        time.sleep(2)
        status = screen.grab_one()
        pages = PageCollector(screen.grab_one, cfg["inventory"]["tabs"]).run()
    cat = _catalog(cfg)
    snap = build_snapshot(cfg, status, pages, cat)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    folder = save_snapshot(snap, Path(cfg["inventory"]["snapshot_dir"]) / f"{a.which}-{stamp}", status, pages)
    n_items = sum(snap["items"].values())
    print(f"Saved {folder}: level {snap['level']}, EXP {snap['exp']}, mesos {snap['mesos']}, "
          f"{len(snap['items'])} different items ({n_items} total)")
    if snap["exp"] is None:
        print("  EXP was not read. Check the exp box with `grindcap snapshot`.")


def cmd_compare(cfg, a):
    from .snapshot import compare, format_compare, html_report, latest_snapshot, load_snapshot

    root = Path(cfg["inventory"]["snapshot_dir"])
    start = a.start or latest_snapshot(root, "start")
    end = a.end or latest_snapshot(root, "end")
    if not start or not end:
        raise SystemExit("Need a start and an end snapshot. Run `grindcap snap start` and `grindcap snap end`.")
    cat = _catalog(cfg)
    r = compare(load_snapshot(start), load_snapshot(end), cat, a.minutes)
    print(f"Comparing {start} -> {end}\n")
    print(json.dumps(r, indent=2) if a.json else format_compare(r))
    out = Path(end) / "report.html"
    html_report(r, cat, out)
    print(f"\nReport with item icons: {out}")


def cmd_items(cfg, a):
    cat = _catalog(cfg)
    if not cat.items:
        print("No items yet. Take a snapshot first.")
    for iid, info in cat.items.items():
        print(f"{iid}  {info.get('name') or '(no name)':<28} price {info.get('price') if info.get('price') is not None else '-'}"
              f"   icon: {cat.icons_dir / (iid + '.png')}")


def cmd_label(cfg, a):
    cat = _catalog(cfg)
    cat.label(a.item, a.name, a.price)
    print(f"{a.item}: {cat.items[a.item]}")


def cmd_teach_digits(cfg, a):
    """Show each occupied slot and ask for its stack number, to learn the game's digit font."""
    import cv2

    from .calibrate import load_frame
    from .digits import DigitReader
    from .inventory import Grid, QtyReader, is_empty

    inv = cfg["inventory"]
    grid = Grid.from_cfg(inv)
    frame = load_frame(a.image, a.video, a.at, _screen(cfg))
    dr = DigitReader(Path(inv["catalog_dir"]) / "digits.npz")
    qty = QtyReader(grid.qty_box, digits=dr) if dr.ready else None
    region = lambda img: img[int(grid.qty_box[1] * img.shape[0]):, :int((grid.qty_box[0] + grid.qty_box[2]) * img.shape[1])]
    taught = 0
    print("For each slot: type the stack number shown, Enter if it has no number, q to stop.")
    for row in grid.slot_boxes():
        for (x, y, w, h) in row:
            img = frame[y:y + h, x:x + w]
            if is_empty(img, grid.qty_box, inv["empty_std"]):
                continue
            cv2.imshow("slot (enlarged)", cv2.resize(img, None, fx=6, fy=6, interpolation=cv2.INTER_NEAREST))
            cv2.waitKey(1)
            ans = input("number> ").strip()
            if ans.lower() == "q":
                break
            if ans.isdigit():
                ok = dr.teach(region(img), ans)
                taught += ok
                print("  learned" if ok else "  couldn't split that into digits; try another slot")
        else:
            continue
        break
    cv2.destroyAllWindows()
    have = "".join(sorted(dr.templates))
    if dr.color is not None:
        dr.save()
    print(f"Learned from {taught} slots. Digits known: {have or 'none'}." +
          ("" if len(have) == 10 else " Teach more slots until all of 0-9 are covered."))


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
    sp.add_argument("--only", nargs="+", choices=["hp", "mp", "exp", "mesos", "level", "inventory"], help="calibrate just these")
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

    sp = sub.add_parser("snap", help="before/after snapshot of EXP, mesos and inventory")
    sp.add_argument("which", choices=["start", "end"])
    frame_args(sp)
    sp.set_defaults(fn=cmd_snap)

    sp = sub.add_parser("compare", help="compare the latest start and end snapshots")
    sp.add_argument("--start", help="start snapshot folder (default: latest start-*)")
    sp.add_argument("--end", help="end snapshot folder (default: latest end-*)")
    sp.add_argument("--minutes", type=float, help="grinding time, if you paused between snapshots")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_compare)

    sub.add_parser("items", help="list known item icons").set_defaults(fn=cmd_items)

    sp = sub.add_parser("teach-digits", help="learn the game's stack-number font from your inventory")
    frame_args(sp)
    sp.set_defaults(fn=cmd_teach_digits)

    sp = sub.add_parser("label", help="name and price an item id")
    sp.add_argument("item")
    sp.add_argument("--name")
    sp.add_argument("--price", type=float, help="mesos each (sell price, or what it saves you)")
    sp.set_defaults(fn=cmd_label)

    a = p.parse_args(argv)
    cfg = Config.load(a.config)
    a.fn(cfg, a)


if __name__ == "__main__":
    sys.exit(main())
